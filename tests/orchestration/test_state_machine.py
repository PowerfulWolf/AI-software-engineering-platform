"""Contract tests for the v0.1 Task state machine."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from ai_software_engineer.domain import StateEvent, TaskStatus
from ai_software_engineer.orchestration.state_machine import (
    IllegalTransition,
    StaleEvent,
    TaskMismatch,
    TerminalTask,
    apply_event,
    build_event,
    validate_transition,
)
from tests.domain.factories import CANDIDATE_SHA, NOW, make_state_event, make_task


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    (
        (TaskStatus.NEW, TaskStatus.PLANNING),
        (TaskStatus.PLANNING, TaskStatus.IMPLEMENTING),
        (TaskStatus.IMPLEMENTING, TaskStatus.QA),
        (TaskStatus.QA, TaskStatus.REVIEW),
        (TaskStatus.QA, TaskStatus.IMPLEMENTING),
        (TaskStatus.QA, TaskStatus.BLOCKED),
        (TaskStatus.REVIEW, TaskStatus.DONE),
        (TaskStatus.REVIEW, TaskStatus.IMPLEMENTING),
        (TaskStatus.REVIEW, TaskStatus.BLOCKED),
        (TaskStatus.NEW, TaskStatus.FAILED),
        (TaskStatus.PLANNING, TaskStatus.FAILED),
        (TaskStatus.IMPLEMENTING, TaskStatus.FAILED),
        (TaskStatus.QA, TaskStatus.FAILED),
        (TaskStatus.REVIEW, TaskStatus.FAILED),
    ),
)
def test_documented_transition_is_accepted(from_status: TaskStatus, to_status: TaskStatus) -> None:
    task = make_task().model_copy(update={"status": from_status})
    validate_transition(task, to_status)


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    (
        (TaskStatus.NEW, TaskStatus.IMPLEMENTING),
        (TaskStatus.PLANNING, TaskStatus.QA),
        (TaskStatus.IMPLEMENTING, TaskStatus.REVIEW),
        (TaskStatus.QA, TaskStatus.DONE),
        (TaskStatus.REVIEW, TaskStatus.PLANNING),
        (TaskStatus.DONE, TaskStatus.NEW),
        (TaskStatus.BLOCKED, TaskStatus.IMPLEMENTING),
        (TaskStatus.FAILED, TaskStatus.NEW),
    ),
)
def test_undocumented_transition_is_rejected(
    from_status: TaskStatus, to_status: TaskStatus
) -> None:
    task = make_task().model_copy(update={"status": from_status})
    with pytest.raises((IllegalTransition, TerminalTask)):
        validate_transition(task, to_status)


@pytest.mark.parametrize("status", tuple(TaskStatus))
def test_self_transition_is_rejected(status: TaskStatus) -> None:
    task = make_task().model_copy(update={"status": status})
    with pytest.raises((IllegalTransition, TerminalTask)):
        validate_transition(task, status)


def test_build_event_is_orchestrator_owned_and_typed() -> None:
    task = make_task()
    event = build_event(
        task,
        TaskStatus.PLANNING,
        event_id="evt_t004_build_01",
        reason="task_validated",
        source_revision=CANDIDATE_SHA,
        artifact_ids=("art_plan_001",),
        occurred_at=NOW,
    )

    assert event.task_id == task.id
    assert event.from_status is TaskStatus.NEW
    assert event.to_status is TaskStatus.PLANNING
    assert event.actor.value == "orchestrator"
    assert event.to_wire()["source_revision"] == CANDIDATE_SHA


def test_build_event_rejects_old_timestamp() -> None:
    task = make_task()
    with pytest.raises(StaleEvent):
        build_event(
            task,
            TaskStatus.PLANNING,
            event_id="evt_t004_old_time",
            reason="task_validated",
            source_revision=CANDIDATE_SHA,
            occurred_at=NOW - timedelta(seconds=1),
        )


def test_apply_event_returns_new_snapshot_without_mutating_original() -> None:
    task = make_task()
    event = make_state_event()

    updated = apply_event(task, event)

    assert task.status is TaskStatus.NEW
    assert task.updated_at == NOW
    assert updated.status is TaskStatus.PLANNING
    assert updated.updated_at == NOW
    assert updated is not task


def test_apply_event_rejects_another_task() -> None:
    task = make_task()
    event = make_state_event(task_id="task_other_001")
    with pytest.raises(TaskMismatch):
        apply_event(task, event)


def test_apply_event_rejects_stale_status() -> None:
    task = make_task()
    event = make_state_event(from_status=TaskStatus.PLANNING)
    with pytest.raises(StaleEvent):
        apply_event(task, event)


def test_apply_event_rejects_illegal_edge_even_when_status_matches() -> None:
    task = make_task()
    event = make_state_event(to_status=TaskStatus.REVIEW)
    with pytest.raises(IllegalTransition):
        apply_event(task, event)


def test_apply_event_rejects_terminal_task() -> None:
    task = make_task().model_copy(update={"status": TaskStatus.DONE})
    event = make_state_event(from_status=TaskStatus.DONE, to_status=TaskStatus.FAILED)
    with pytest.raises(TerminalTask):
        apply_event(task, event)


def test_state_event_contract_still_rejects_non_orchestrator_actor() -> None:
    payload = make_state_event().to_wire()
    payload["actor"] = "coder"
    with pytest.raises(ValidationError):
        StateEvent.model_validate(payload)
