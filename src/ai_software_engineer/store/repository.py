"""SQLite implementation of the typed Task and state-event repository."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.domain.task import Task, TaskId


class StoreError(RuntimeError):
    """Base class for typed repository failures."""


class TaskAlreadyExists(StoreError):
    """Raised when a Task ID is already persisted."""


class TaskNotFound(StoreError):
    """Raised when a Task ID does not exist."""


class EventIdempotencyConflict(StoreError):
    """Raised when an existing event ID is reused with different content."""


class InvalidStateEvent(StoreError):
    """Raised when an event does not originate from the current Task status."""


class StoreCorruption(StoreError):
    """Raised when durable JSON no longer satisfies its typed contract."""


class SqliteTaskRepository:
    """Durable Task snapshots and event log backed by one SQLite database."""

    def __init__(self, database: str | Path) -> None:
        self._database = Path(database)
        self._database.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._database, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = NORMAL")
        self._initialize_schema()

    def close(self) -> None:
        """Close the database connection; reopening reads only durable state."""
        self._connection.close()

    @property
    def foreign_keys_enabled(self) -> bool:
        """Expose the connection-level foreign-key safety setting for health checks."""
        row = self._connection.execute("PRAGMA foreign_keys").fetchone()
        value: object = row[0] if row is not None else None
        return value == 1

    @property
    def journal_mode(self) -> str:
        """Expose the durable journal mode for health checks and diagnostics."""
        row = self._connection.execute("PRAGMA journal_mode").fetchone()
        value: object = row[0] if row is not None else None
        if not isinstance(value, str):
            raise StoreCorruption("SQLite journal_mode is not text")
        return value.lower()

    def __enter__(self) -> "SqliteTaskRepository":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def create(self, task: Task) -> None:
        """Persist a new Task at revision zero."""
        payload = _encode(task.to_wire())
        with self._transaction():
            try:
                self._connection.execute(
                    """
                    INSERT INTO tasks (id, payload_json, status, revision, created_at, updated_at)
                    VALUES (?, ?, ?, 0, ?, ?)
                    """,
                    (
                        task.id,
                        payload,
                        task.status.value,
                        task.created_at.isoformat(),
                        task.updated_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                if "UNIQUE constraint failed: tasks.id" in str(error):
                    raise TaskAlreadyExists(task.id) from error
                raise StoreError("failed to create Task") from error

    def get(self, task_id: TaskId) -> Task:
        """Load and validate the latest Task snapshot."""
        row = self._connection.execute(
            "SELECT id, payload_json FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise TaskNotFound(task_id)
        return self._decode_task(_text(row, "id"), _text(row, "payload_json"))

    def append_event(self, event: StateEvent) -> None:
        """Atomically append an event and advance its Task snapshot."""
        with self._transaction():
            existing = self._connection.execute(
                "SELECT payload_json FROM state_events WHERE event_id = ?", (event.event_id,)
            ).fetchone()
            if existing is not None:
                existing_event = self._decode_event(_text(existing, "payload_json"))
                if existing_event == event:
                    return
                raise EventIdempotencyConflict(event.event_id)

            task_row = self._connection.execute(
                "SELECT id, payload_json, revision FROM tasks WHERE id = ?", (event.task_id,)
            ).fetchone()
            if task_row is None:
                raise TaskNotFound(event.task_id)
            task_id = _text(task_row, "id")
            task = self._decode_task(task_id, _text(task_row, "payload_json"))
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
                update={
                    "status": event.to_status,
                    "updated_at": event.occurred_at,
                }
            )
            next_revision = revision + 1
            try:
                self._connection.execute(
                    """
                    INSERT INTO state_events (event_id, task_id, revision, payload_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (event.event_id, event.task_id, next_revision, _encode(event.to_wire())),
                )
                updated = self._connection.execute(
                    """
                    UPDATE tasks
                    SET payload_json = ?, status = ?, revision = ?, updated_at = ?
                    WHERE id = ? AND revision = ?
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
                if updated.rowcount != 1:
                    raise StoreError("Task revision changed while appending state event")
            except sqlite3.IntegrityError as error:
                raise StoreError("failed to append state event") from error

    def record_attempt(self, task_id: TaskId, attempt: int) -> None:
        """Durably checkpoint an Agent attempt without inventing a state transition."""
        if type(attempt) is not int or not 1 <= attempt <= 10:
            raise StoreError(f"attempt must be between 1 and 10: {attempt}")
        with self._transaction():
            row = self._connection.execute(
                "SELECT id, payload_json FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise TaskNotFound(task_id)
            task = self._decode_task(_text(row, "id"), _text(row, "payload_json"))
            if attempt > task.max_attempts:
                raise StoreError(f"attempt {attempt} exceeds Task max_attempts {task.max_attempts}")
            if attempt <= task.attempts:
                return
            next_task = task.model_copy(update={"attempts": attempt})
            updated = self._connection.execute(
                "UPDATE tasks SET payload_json = ? WHERE id = ?",
                (_encode(next_task.to_wire()), task_id),
            )
            if updated.rowcount != 1:
                raise StoreError("Task attempt checkpoint was not written")

    def list_events(self, task_id: TaskId) -> tuple[StateEvent, ...]:
        """Return a Task's events in replay order."""
        self._require_task(task_id)
        rows = self._connection.execute(
            "SELECT payload_json FROM state_events WHERE task_id = ? ORDER BY revision ASC",
            (task_id,),
        ).fetchall()
        events = tuple(self._decode_event(_text(row, "payload_json")) for row in rows)
        if any(event.task_id != task_id for event in events):
            raise StoreCorruption(f"event task_id mismatch for {task_id}")
        return events

    def current_revision(self, task_id: TaskId) -> int:
        """Return the durable per-Task event revision."""
        row = self._connection.execute(
            "SELECT revision FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise TaskNotFound(task_id)
        return _non_negative_int(row, "revision")

    def _require_task(self, task_id: TaskId) -> None:
        row = self._connection.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise TaskNotFound(task_id)

    def _initialize_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision >= 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS state_events (
                event_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(id),
                revision INTEGER NOT NULL CHECK (revision >= 1),
                payload_json TEXT NOT NULL,
                UNIQUE(task_id, revision)
            );
            CREATE INDEX IF NOT EXISTS idx_state_events_task_revision
                ON state_events(task_id, revision);
            """
        )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()

    @staticmethod
    def _decode_task(task_id: str, payload_json: str) -> Task:
        try:
            payload: object = json.loads(payload_json)
            task = Task.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as error:
            raise StoreCorruption(f"invalid Task payload for {task_id}") from error
        if task.id != task_id:
            raise StoreCorruption(f"Task payload ID mismatch for {task_id}")
        return task

    @staticmethod
    def _decode_event(payload_json: str) -> StateEvent:
        try:
            payload: object = json.loads(payload_json)
            return StateEvent.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as error:
            raise StoreCorruption("invalid StateEvent payload") from error


def _encode(payload: WirePayload) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(row: sqlite3.Row, key: str) -> str:
    value: object = row[key]
    if not isinstance(value, str):
        raise StoreCorruption(f"SQLite column {key} is not text")
    return value


def _non_negative_int(row: sqlite3.Row, key: str) -> int:
    value: object = row[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise StoreCorruption(f"SQLite column {key} is not a non-negative integer")
    return value
