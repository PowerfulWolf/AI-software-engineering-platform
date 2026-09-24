"""Dispatch identity checks must distinguish immutable intent from runtime facts."""

from datetime import UTC, datetime, timedelta

import pytest

from ai_software_engineer.domain import AcceptanceCriterion, Task, TaskStatus
from ai_software_engineer.domain.retry_policy import (
    DeliveryRetryFailure,
    DeliveryRetryPolicy,
    TransientRetryPolicy,
)
from ai_software_engineer.team_view.reader import _validate_task_dispatch_identity


def _task(*, retry_policy: DeliveryRetryPolicy | None) -> Task:
    created_at = datetime(2026, 9, 24, 7, 3, 29, tzinfo=UTC)
    return Task(
        id="task_dispatch_identity",
        title="Visible project",
        description="Keep the project visible while delivery runs.",
        repository="/workspace/project",
        base_ref="a" * 40,
        acceptance_criteria=(
            AcceptanceCriterion(
                id="ac_visible",
                description="The project is readable.",
                required=True,
                verification="Read the Team snapshot.",
            ),
        ),
        status=TaskStatus.NEW,
        max_attempts=17,
        retry_policy=retry_policy,
        created_at=created_at,
        updated_at=created_at,
        metadata={"project_request_id": "request_dispatch_identity"},
    )


def _policy() -> DeliveryRetryPolicy:
    transient = TransientRetryPolicy(max_transient_failures=5)
    return DeliveryRetryPolicy(
        max_work_attempts=2,
        coder=transient,
        qa=transient,
        reviewer=transient,
    )


@pytest.mark.parametrize("status", [TaskStatus.QA, TaskStatus.BLOCKED])
def test_runtime_retry_failure_does_not_change_dispatch_identity(status: TaskStatus) -> None:
    policy = _policy()
    dispatch = _task(retry_policy=policy)
    current = dispatch.model_copy(
        update={
            "status": status,
            "attempts": 1,
            "updated_at": dispatch.updated_at + timedelta(minutes=2),
            "retry_failures": (
                DeliveryRetryFailure(role="coder", attempt=1, code="TIMEOUT"),
            ),
        }
    )

    _validate_task_dispatch_identity(current, dispatch)


def test_legacy_dispatch_without_retry_policy_remains_readable() -> None:
    policy = _policy()
    current = _task(retry_policy=policy)
    dispatch = _task(retry_policy=None)

    _validate_task_dispatch_identity(current, dispatch)


def test_dispatch_identity_rejects_immutable_drift() -> None:
    dispatch = _task(retry_policy=_policy())
    current = dispatch.model_copy(update={"description": "tampered intent"})

    with pytest.raises(ValueError, match="Task differs from dispatch intent"):
        _validate_task_dispatch_identity(current, dispatch)


def test_dispatch_retry_policy_is_immutable_when_present() -> None:
    dispatch = _task(retry_policy=_policy())
    current = dispatch.model_copy(
        update={
            "retry_policy": DeliveryRetryPolicy(max_work_attempts=3),
        }
    )

    with pytest.raises(ValueError, match="Task differs from dispatch intent"):
        _validate_task_dispatch_identity(current, dispatch)
