"""MySQL integration contract for the production TaskRepository adapter."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest

from ai_software_engineer.domain import StateEvent, Task, TaskStatus
from ai_software_engineer.store import (
    EventIdempotencyConflict,
    InvalidStateEvent,
    MySqlTaskRepository,
    TaskAlreadyExists,
    TaskNotFound,
)
from tests.domain.factories import NOW, make_state_event, make_task

pytestmark = pytest.mark.mysql


def _dsn() -> str:
    value = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not value:
        pytest.skip("ASE_TEST_MYSQL_DSN is not configured")
    return value


@pytest.fixture
def repository() -> Iterator[MySqlTaskRepository]:
    opened = MySqlTaskRepository(_dsn())
    try:
        yield opened
    finally:
        opened.close()


def _facts() -> tuple[Task, StateEvent]:
    identity = uuid4().hex
    task = make_task().model_copy(update={"id": f"task_mysql_{identity}"})
    event = make_state_event().model_copy(
        update={
            "event_id": f"evt_mysql_{identity}",
            "task_id": task.id,
        }
    )
    return task, event


def test_task_round_trips_after_repository_reopen(
    repository: MySqlTaskRepository,
) -> None:
    task, _ = _facts()
    repository.create(task)
    assert repository.get(task.id) == task
    assert repository.current_revision(task.id) == 0
    repository.close()

    with MySqlTaskRepository(_dsn()) as reopened:
        assert reopened.get(task.id) == task
        assert reopened.list_events(task.id) == ()


def test_create_rejects_duplicate_task_id(repository: MySqlTaskRepository) -> None:
    task, _ = _facts()
    repository.create(task)

    with pytest.raises(TaskAlreadyExists):
        repository.create(task)


def test_append_event_atomically_advances_snapshot_and_revision(
    repository: MySqlTaskRepository,
) -> None:
    task, event = _facts()
    repository.create(task)
    repository.append_event(event)

    updated = repository.get(task.id)
    assert updated.status is TaskStatus.PLANNING
    assert updated.updated_at == NOW
    assert repository.current_revision(task.id) == 1
    assert repository.list_events(task.id) == (event,)


def test_exact_event_replay_is_idempotent(repository: MySqlTaskRepository) -> None:
    task, event = _facts()
    repository.create(task)
    repository.append_event(event)
    repository.append_event(event)

    assert repository.current_revision(task.id) == 1
    assert repository.list_events(task.id) == (event,)


def test_conflicting_event_id_rolls_back(repository: MySqlTaskRepository) -> None:
    task, event = _facts()
    conflicting = event.model_copy(update={"to_status": TaskStatus.IMPLEMENTING})
    repository.create(task)
    repository.append_event(event)

    with pytest.raises(EventIdempotencyConflict):
        repository.append_event(conflicting)

    assert repository.current_revision(task.id) == 1
    assert repository.get(task.id).status is TaskStatus.PLANNING


def test_stale_from_status_rolls_back(repository: MySqlTaskRepository) -> None:
    task, event = _facts()
    repository.create(task)

    with pytest.raises(InvalidStateEvent):
        repository.append_event(event.model_copy(update={"from_status": TaskStatus.PLANNING}))

    assert repository.current_revision(task.id) == 0
    assert repository.list_events(task.id) == ()


def test_attempt_checkpoint_survives_reopen(
    repository: MySqlTaskRepository,
) -> None:
    task, _ = _facts()
    repository.create(task)
    repository.record_attempt(task.id, 2)
    repository.close()

    with MySqlTaskRepository(_dsn()) as reopened:
        assert reopened.get(task.id).attempts == 2
        assert reopened.current_revision(task.id) == 0


def test_event_timestamp_becomes_task_updated_at(
    repository: MySqlTaskRepository,
) -> None:
    task, event = _facts()
    event = event.model_copy(update={"occurred_at": NOW + timedelta(minutes=5)})
    repository.create(task)
    repository.append_event(event)

    assert repository.get(task.id).updated_at == event.occurred_at


def test_unknown_task_operations_raise_typed_error(
    repository: MySqlTaskRepository,
) -> None:
    with pytest.raises(TaskNotFound):
        repository.get("task_missing_001")
    with pytest.raises(TaskNotFound):
        repository.current_revision("task_missing_001")
    with pytest.raises(TaskNotFound):
        repository.list_events("task_missing_001")


def test_competing_connections_cannot_publish_the_same_revision(
    repository: MySqlTaskRepository,
) -> None:
    task, first = _facts()
    second = first.model_copy(
        update={
            "event_id": f"evt_mysql_competing_{uuid4().hex}",
            "to_status": TaskStatus.IMPLEMENTING,
        }
    )
    repository.create(task)
    other = MySqlTaskRepository(_dsn())
    try:

        def append(repo: MySqlTaskRepository, event: StateEvent) -> Exception | None:
            try:
                repo.append_event(event)
            except Exception as error:
                return error
            return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(
                future.result()
                for future in (
                    pool.submit(append, repository, first),
                    pool.submit(append, other, second),
                )
            )

        assert sum(outcome is None for outcome in outcomes) == 1
        assert sum(isinstance(outcome, InvalidStateEvent) for outcome in outcomes) == 1
        assert repository.current_revision(task.id) == 1
        assert len(repository.list_events(task.id)) == 1
    finally:
        other.close()
