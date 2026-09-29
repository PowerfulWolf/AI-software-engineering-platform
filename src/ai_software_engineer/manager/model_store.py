"""Manager records commit in the same MySQL transaction as their owner fence."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import closing, contextmanager
from contextvars import ContextVar
from typing import Protocol

from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.store.mysql_repository import open_mysql_connection


class ManagerRecordStore(Protocol):
    def put[T: DomainModel](self, namespace: str, key: str, record: T) -> T: ...
    def find[T: DomainModel](self, namespace: str, key: str, model: type[T]) -> T | None: ...
    def list[T: DomainModel](self, namespace: str, model: type[T]) -> tuple[T, ...]: ...


_writer: ContextVar[tuple[Connection, str] | None] = ContextVar(
    "manager_record_writer", default=None
)


@contextmanager
def manager_record_transaction(connection: Connection, team_id: str) -> Iterator[None]:
    """Only an owned authority opens this scope; commit follows its final fence check."""
    connection.begin()
    token = _writer.set((connection, team_id))
    try:
        yield
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        _writer.reset(token)


class MySqlManagerRecordStore:
    def __init__(self, dsn: str, team_id: str) -> None:
        self._dsn, self._team_id = dsn, team_id
        with (
            closing(open_mysql_connection(dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS manager_coordination_records (
                    team_id VARCHAR(128) NOT NULL,
                    namespace VARCHAR(64) NOT NULL,
                    record_key CHAR(64) NOT NULL,
                    payload_json JSON NOT NULL,
                    sha256 CHAR(64) NOT NULL,
                    PRIMARY KEY (team_id, namespace, record_key)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
            """)
            cursor.execute("SHOW COLUMNS FROM manager_coordination_records")
            if {row["Field"] for row in cursor.fetchall()} != {
                "team_id",
                "namespace",
                "record_key",
                "payload_json",
                "sha256",
            }:
                raise ValueError("unexpected Manager coordination record schema")
            connection.commit()

    def put[T: DomainModel](self, namespace: str, key: str, record: T) -> T:
        owner = _writer.get()
        if owner is None or owner[1] != self._team_id:
            raise ValueError("Manager record publication requires an owned transaction")
        wire = record.to_wire()
        payload = json.dumps(wire, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(payload.encode()) > 8_000_000:
            raise ValueError("Manager record exceeds its storage limit")
        with owner[0].cursor(DictCursor) as cursor:
            cursor.execute(
                "SELECT payload_json, sha256 FROM manager_coordination_records "
                "WHERE team_id=%s AND namespace=%s AND record_key=%s FOR UPDATE",
                (self._team_id, namespace, digest(key)),
            )
            row = cursor.fetchone()
            if row is not None:
                found = self._decode(row, type(record))
                if found != record:
                    raise ValueError("Manager record identity conflict")
                return found
            cursor.execute(
                "INSERT INTO manager_coordination_records "
                "(team_id, namespace, record_key, payload_json, sha256) VALUES (%s,%s,%s,%s,%s)",
                (self._team_id, namespace, digest(key), payload, digest(wire)),
            )
        return record

    def find[T: DomainModel](self, namespace: str, key: str, model: type[T]) -> T | None:
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT payload_json, sha256 FROM manager_coordination_records "
                "WHERE team_id=%s AND namespace=%s AND record_key=%s",
                (self._team_id, namespace, digest(key)),
            )
            row = cursor.fetchone()
            return None if row is None else self._decode(row, model)

    def list[T: DomainModel](self, namespace: str, model: type[T]) -> tuple[T, ...]:
        with (
            closing(open_mysql_connection(self._dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT payload_json, sha256 FROM manager_coordination_records "
                "WHERE team_id=%s AND namespace=%s",
                (self._team_id, namespace),
            )
            return tuple(self._decode(row, model) for row in cursor.fetchall())

    @staticmethod
    def _decode[T: DomainModel](row: dict[str, object], model: type[T]) -> T:
        raw = row["payload_json"]
        if not isinstance(raw, str):
            raise ValueError("Manager record payload is invalid")
        payload = json.loads(raw)
        if digest(payload) != row["sha256"]:
            raise ValueError("Manager record digest mismatch")
        return model.model_validate(payload)
