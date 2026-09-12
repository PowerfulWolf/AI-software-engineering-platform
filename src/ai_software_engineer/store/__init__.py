"""Persistence ports and the SQLite v0.1 implementation."""

from ai_software_engineer.store.mysql_repository import (
    MySqlConfigurationError,
    MySqlConnectionError,
    MySqlTaskRepository,
    open_mysql_connection,
    validate_mysql_dsn,
)
from ai_software_engineer.store.ports import TaskRepository
from ai_software_engineer.store.repository import (
    EventIdempotencyConflict,
    InvalidStateEvent,
    SqliteTaskRepository,
    StoreCorruption,
    StoreError,
    TaskAlreadyExists,
    TaskNotFound,
)

__all__ = [
    "EventIdempotencyConflict",
    "InvalidStateEvent",
    "MySqlConfigurationError",
    "MySqlConnectionError",
    "MySqlTaskRepository",
    "SqliteTaskRepository",
    "StoreCorruption",
    "StoreError",
    "TaskAlreadyExists",
    "TaskNotFound",
    "TaskRepository",
    "open_mysql_connection",
    "validate_mysql_dsn",
]
