"""SQLite repository behavior through the TaskRepository public seam."""

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.domain import TaskStatus
from ai_software_engineer.store import (
    EventIdempotencyConflict,
    InvalidStateEvent,
    SqliteTaskRepository,
    TaskAlreadyExists,
    TaskNotFound,
)
from tests.domain.factories import NOW, make_state_event, make_task


def test_task_round_trips_after_repository_reopen(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    task = make_task()

    with SqliteTaskRepository(database) as repository:
        repository.create(task)
        assert repository.get(task.id) == task
        assert repository.current_revision(task.id) == 0

    with SqliteTaskRepository(database) as reopened:
        assert reopened.get(task.id) == task
        assert reopened.list_events(task.id) == ()


def test_create_rejects_duplicate_task_id(tmp_path: Path) -> None:
    task = make_task()
    with SqliteTaskRepository(tmp_path / "state.db") as repository:
        repository.create(task)

        with pytest.raises(TaskAlreadyExists):
            repository.create(task)


def test_append_event_atomically_advances_snapshot_and_revision(tmp_path: Path) -> None:
    task = make_task()
    event = make_state_event()
    with SqliteTaskRepository(tmp_path / "state.db") as repository:
        repository.create(task)
        repository.append_event(event)

        updated = repository.get(task.id)
        assert updated.status is TaskStatus.PLANNING
        assert updated.updated_at == NOW
        assert repository.current_revision(task.id) == 1
        assert repository.list_events(task.id) == (event,)


def test_exact_event_replay_is_an_idempotent_noop(tmp_path: Path) -> None:
    task = make_task()
    event = make_state_event()
    with SqliteTaskRepository(tmp_path / "state.db") as repository:
        repository.create(task)
        repository.append_event(event)
        repository.append_event(event)

        assert repository.current_revision(task.id) == 1
        assert repository.list_events(task.id) == (event,)


def test_reusing_event_id_with_changed_payload_is_rejected_without_mutation(tmp_path: Path) -> None:
    task = make_task()
    event = make_state_event()
    conflicting = make_state_event(event_id=event.event_id, to_status=TaskStatus.IMPLEMENTING)
    with SqliteTaskRepository(tmp_path / "state.db") as repository:
        repository.create(task)
        repository.append_event(event)

        with pytest.raises(EventIdempotencyConflict):
            repository.append_event(conflicting)

        assert repository.current_revision(task.id) == 1
        assert repository.get(task.id).status is TaskStatus.PLANNING
        assert repository.list_events(task.id) == (event,)


def test_stale_from_status_rolls_back_event_and_snapshot(tmp_path: Path) -> None:
    task = make_task()
    event = make_state_event(from_status=TaskStatus.PLANNING)
    with SqliteTaskRepository(tmp_path / "state.db") as repository:
        repository.create(task)

        with pytest.raises(InvalidStateEvent):
            repository.append_event(event)

        assert repository.current_revision(task.id) == 0
        assert repository.get(task.id).status is TaskStatus.NEW
        assert repository.list_events(task.id) == ()


def test_event_timestamp_becomes_task_updated_at(tmp_path: Path) -> None:
    task = make_task()
    occurred_at = NOW + timedelta(minutes=5)
    event = make_state_event()
    event = event.model_copy(update={"occurred_at": occurred_at})
    with SqliteTaskRepository(tmp_path / "state.db") as repository:
        repository.create(task)
        repository.append_event(event)

        assert repository.get(task.id).updated_at == occurred_at


def test_unknown_task_operations_raise_typed_error(tmp_path: Path) -> None:
    with SqliteTaskRepository(tmp_path / "state.db") as repository:
        with pytest.raises(TaskNotFound):
            repository.get("task_missing_001")
        with pytest.raises(TaskNotFound):
            repository.current_revision("task_missing_001")
        with pytest.raises(TaskNotFound):
            repository.list_events("task_missing_001")
        with pytest.raises(TaskNotFound):
            repository.append_event(make_state_event(task_id="task_missing_001"))


def test_sqlite_runtime_enables_foreign_keys_and_wal(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    with SqliteTaskRepository(database) as repository:
        assert repository.foreign_keys_enabled
        assert repository.journal_mode == "wal"

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        connection.close()
