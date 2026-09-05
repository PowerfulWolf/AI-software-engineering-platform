"""MySQL implementation of the typed Task and state-event repository."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Self, cast
from urllib.parse import unquote, urlparse

import pymysql
from pydantic import ValidationError
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.domain.task import Task, TaskId
from ai_software_engineer.store.repository import (
    EventIdempotencyConflict,
    InvalidStateEvent,
    StoreCorruption,
    StoreError,
    TaskAlreadyExists,
    TaskNotFound,
)


class MySqlConfigurationError(StoreError):
    """Raised before connecting when a MySQL DSN is unsafe or incomplete."""


class MySqlConnectionError(StoreError):
    """Raised when MySQL is unavailable without exposing connection secrets."""


@dataclass(frozen=True, slots=True)
class _ConnectionSettings:
    host: str
    port: int
    user: str
    password: str
    database: str


class MySqlTaskRepository:
    """Durable Task snapshots and event log backed by MySQL 8/InnoDB."""

    def __init__(self, dsn: str) -> None:
        self._connection = open_mysql_connection(dsn)
        try:
            self._initialize_schema()
        except pymysql.MySQLError as error:
            self._connection.close()
            raise MySqlConnectionError("cannot open MySQL TaskRepository") from error

    def close(self) -> None:
        """Close the connection; reopening reads only committed durable state."""
        if self._connection.open:
            self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def create(self, task: Task) -> None:
        """Persist a new Task at revision zero."""
        with self._transaction(), self._connection.cursor() as cursor:
            try:
                cursor.execute(
                    """
                    INSERT INTO tasks (id, payload_json, status, revision, created_at, updated_at)
                    VALUES (%s, %s, %s, 0, %s, %s)
                    """,
                    (
                        task.id,
                        _encode(task.to_wire()),
                        task.status.value,
                        task.created_at.isoformat(),
                        task.updated_at.isoformat(),
                    ),
                )
            except pymysql.IntegrityError as error:
                if _mysql_error_code(error) == 1062:
                    raise TaskAlreadyExists(task.id) from error
                raise StoreError("failed to create Task") from error

    def get(self, task_id: TaskId) -> Task:
        """Load and validate the latest Task snapshot."""
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, payload_json FROM tasks WHERE id = %s",
                    (task_id,),
                )
                row = cast(Mapping[str, object] | None, cursor.fetchone())
        except pymysql.MySQLError as error:
            raise MySqlConnectionError("failed to read Task from MySQL") from error
        if row is None:
            raise TaskNotFound(task_id)
        return _decode_task(_text(row, "id"), _text(row, "payload_json"))

    def append_event(self, event: StateEvent) -> None:
        """Atomically append an event and advance its locked Task snapshot."""
        with self._transaction(), self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload_json FROM state_events WHERE event_id = %s FOR UPDATE",
                (event.event_id,),
            )
            existing = cast(Mapping[str, object] | None, cursor.fetchone())
            if existing is not None:
                existing_event = _decode_event(_text(existing, "payload_json"))
                if existing_event == event:
                    return
                raise EventIdempotencyConflict(event.event_id)

            cursor.execute(
                "SELECT id, payload_json, revision FROM tasks WHERE id = %s FOR UPDATE",
                (event.task_id,),
            )
            task_row = cast(Mapping[str, object] | None, cursor.fetchone())
            if task_row is None:
                raise TaskNotFound(event.task_id)
            task_id = _text(task_row, "id")
            task = _decode_task(task_id, _text(task_row, "payload_json"))
            revision = _non_negative_int(task_row, "revision")
            if task.status is not event.from_status:
                raise InvalidStateEvent(
                    f"Task {event.task_id} is {task.status}, event starts at {event.from_status}"
                )
            if event.attempt > task.max_attempts:
                raise InvalidStateEvent(
                    f"event {event.event_id} attempt {event.attempt} exceeds Task max_attempts"
                )

            next_task = task.model_copy(
                update={"status": event.to_status, "updated_at": event.occurred_at}
            )
            next_revision = revision + 1
            try:
                cursor.execute(
                    """
                    INSERT INTO state_events (event_id, task_id, revision, payload_json)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        event.event_id,
                        event.task_id,
                        next_revision,
                        _encode(event.to_wire()),
                    ),
                )
                updated = cursor.execute(
                    """
                    UPDATE tasks
                    SET payload_json = %s, status = %s, revision = %s, updated_at = %s
                    WHERE id = %s AND revision = %s
                    """,
                    (
                        _encode(next_task.to_wire()),
                        next_task.status.value,
                        next_revision,
                        next_task.updated_at.isoformat(),
                        event.task_id,
                        revision,
                    ),
                )
            except pymysql.IntegrityError as error:
                raise StoreError("failed to append state event") from error
            if updated != 1:
                raise StoreError("Task revision changed while appending state event")

    def record_attempt(self, task_id: TaskId, attempt: int) -> None:
        """Durably checkpoint an Agent attempt without a state transition."""
        if type(attempt) is not int or not 1 <= attempt <= 10:
            raise StoreError(f"attempt must be between 1 and 10: {attempt}")
        with self._transaction(), self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, payload_json FROM tasks WHERE id = %s FOR UPDATE",
                (task_id,),
            )
            row = cast(Mapping[str, object] | None, cursor.fetchone())
            if row is None:
                raise TaskNotFound(task_id)
            task = _decode_task(_text(row, "id"), _text(row, "payload_json"))
            if attempt > task.max_attempts:
                raise StoreError(f"attempt {attempt} exceeds Task max_attempts {task.max_attempts}")
            if attempt <= task.attempts:
                return
            next_task = task.model_copy(update={"attempts": attempt})
            updated = cursor.execute(
                "UPDATE tasks SET payload_json = %s WHERE id = %s",
                (_encode(next_task.to_wire()), task_id),
            )
            if updated != 1:
                raise StoreError("Task attempt checkpoint was not written")

    def list_events(self, task_id: TaskId) -> tuple[StateEvent, ...]:
        """Return a Task's events in replay order."""
        self._require_task(task_id)
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT payload_json FROM state_events
                    WHERE task_id = %s ORDER BY revision ASC
                    """,
                    (task_id,),
                )
                rows = cast(tuple[Mapping[str, object], ...], cursor.fetchall())
        except pymysql.MySQLError as error:
            raise MySqlConnectionError("failed to list Task events from MySQL") from error
        events = tuple(_decode_event(_text(row, "payload_json")) for row in rows)
        if any(event.task_id != task_id for event in events):
            raise StoreCorruption(f"event task_id mismatch for {task_id}")
        return events

    def current_revision(self, task_id: TaskId) -> int:
        """Return the durable per-Task event revision."""
        try:
            with self._connection.cursor() as cursor:
                cursor.execute("SELECT revision FROM tasks WHERE id = %s", (task_id,))
                row = cast(Mapping[str, object] | None, cursor.fetchone())
        except pymysql.MySQLError as error:
            raise MySqlConnectionError("failed to read Task revision from MySQL") from error
        if row is None:
            raise TaskNotFound(task_id)
        return _non_negative_int(row, "revision")

    def _require_task(self, task_id: TaskId) -> None:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute("SELECT 1 AS present FROM tasks WHERE id = %s", (task_id,))
                row = cursor.fetchone()
        except pymysql.MySQLError as error:
            raise MySqlConnectionError("failed to read Task from MySQL") from error
        if row is None:
            raise TaskNotFound(task_id)

    def _initialize_schema(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id VARCHAR(128) PRIMARY KEY,
                payload_json JSON NOT NULL,
                status VARCHAR(32) NOT NULL,
                revision INT UNSIGNED NOT NULL,
                created_at VARCHAR(40) NOT NULL,
                updated_at VARCHAR(40) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
            """,
            """
            CREATE TABLE IF NOT EXISTS state_events (
                event_id VARCHAR(128) PRIMARY KEY,
                task_id VARCHAR(128) NOT NULL,
                revision INT UNSIGNED NOT NULL,
                payload_json JSON NOT NULL,
                UNIQUE KEY uq_state_events_task_revision (task_id, revision),
                CONSTRAINT fk_state_events_task
                    FOREIGN KEY (task_id) REFERENCES tasks(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
            """,
        )
        with self._transaction(), self._connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            self._connection.begin()
            yield
        except (StoreError, ValidationError, ValueError):
            self._connection.rollback()
            raise
        except pymysql.MySQLError as error:
            self._connection.rollback()
            raise MySqlConnectionError("MySQL TaskRepository transaction failed") from error
        except BaseException:
            self._connection.rollback()
            raise
        else:
            try:
                self._connection.commit()
            except pymysql.MySQLError as error:
                self._connection.rollback()
                raise MySqlConnectionError("MySQL TaskRepository commit failed") from error


def _parse_dsn(dsn: str) -> _ConnectionSettings:
    if not isinstance(dsn, str) or not dsn or any(ord(character) < 32 for character in dsn):
        raise MySqlConfigurationError("MySQL DSN must be non-empty text without controls")
    parsed = urlparse(dsn)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise MySqlConfigurationError("MySQL DSN scheme must be mysql or mysql+pymysql")
    if parsed.hostname is None or parsed.username is None or parsed.password is None:
        raise MySqlConfigurationError("MySQL DSN requires host, username, and password")
    database = unquote(parsed.path.removeprefix("/"))
    if not database or "/" in database:
        raise MySqlConfigurationError("MySQL DSN requires one database name")
    if parsed.query or parsed.fragment:
        raise MySqlConfigurationError("MySQL DSN query and fragment are not supported")
    try:
        port = parsed.port or 3306
    except ValueError as error:
        raise MySqlConfigurationError("MySQL DSN port is invalid") from error
    return _ConnectionSettings(
        host=parsed.hostname,
        port=port,
        user=unquote(parsed.username),
        password=unquote(parsed.password),
        database=database,
    )


def open_mysql_connection(dsn: str) -> Connection:
    """Open one bounded MySQL connection from a validated, never-logged DSN."""
    settings = _parse_dsn(dsn)
    try:
        return pymysql.connect(
            host=settings.host,
            port=settings.port,
            user=settings.user,
            password=settings.password,
            database=settings.database,
            charset="utf8mb4",
            autocommit=False,
            cursorclass=DictCursor,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
        )
    except pymysql.MySQLError as error:
        raise MySqlConnectionError("cannot open MySQL connection") from error


def _mysql_error_code(error: pymysql.MySQLError) -> int | None:
    value: Any = error.args[0] if error.args else None
    return value if type(value) is int else None


def _encode(payload: WirePayload) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(row: Mapping[str, object], key: str) -> str:
    value = row[key]
    if not isinstance(value, str):
        raise StoreCorruption(f"MySQL column {key} is not text")
    return value


def _non_negative_int(row: Mapping[str, object], key: str) -> int:
    value = row[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise StoreCorruption(f"MySQL column {key} is not a non-negative integer")
    return value


def _decode_task(task_id: str, payload_json: str) -> Task:
    try:
        payload: object = json.loads(payload_json)
        task = Task.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as error:
        raise StoreCorruption(f"invalid Task payload for {task_id}") from error
    if task.id != task_id:
        raise StoreCorruption(f"Task payload ID mismatch for {task_id}")
    return task


def _decode_event(payload_json: str) -> StateEvent:
    try:
        payload: object = json.loads(payload_json)
        return StateEvent.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as error:
        raise StoreCorruption("invalid StateEvent payload") from error


__all__ = [
    "MySqlConfigurationError",
    "MySqlConnectionError",
    "MySqlTaskRepository",
    "open_mysql_connection",
]
