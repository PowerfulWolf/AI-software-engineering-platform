"""Unsupported live Artifact versions take the normal fenced failure path."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult
from ai_software_engineer.domain import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.engineering_authority import (
    EngineeringPolicy,
    EngineeringScope,
    LocalOperatorPrincipal,
)
from ai_software_engineer.domain.retry_policy import DeliveryRetryPolicy
from ai_software_engineer.manager.production_backend import _terminal_delivery_result
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
from ai_software_engineer.work_queue.worker import DeliveryWaiting
from tests.work_queue.test_worker_mysql import (
    REPOSITORY_ID,
    ObservedAdapter,
    runtime_fixture,
)
from tests.work_queue.test_worker_mysql import mysql_dsn as mysql_dsn

pytestmark = pytest.mark.mysql


@pytest.mark.parametrize("role", [AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER])
def test_unsupported_version_waits_durably_and_releases_original_claim(
    mysql_dsn: str, tmp_path: Path, role: AgentRole
) -> None:
    queue = MySqlRoleQueue(mysql_dsn)

    class UnsupportedVersion(ObservedAdapter):
        def run(self, request: AgentRequest) -> AgentResult:
            result = super().run(request)
            if request.role is not role:
                return result
            assert result.artifact is not None
            return result.model_copy(
                update={"artifact": result.artifact.model_copy(update={"schema_version": "v1.0"})}
            )

    adapter = UnsupportedVersion(queue)
    engineering = EngineeringPolicy.bounded_local(
        scope=EngineeringScope(
            team_id="team_worker",
            project_id="project_worker",
            repository_id=REPOSITORY_ID,
            repository_root=str(tmp_path / "repository"),
        ),
        principal=LocalOperatorPrincipal.trusted_local(),
    )
    with runtime_fixture(
        tmp_path,
        mysql_dsn,
        queue,
        adapter,
        retry_policy=DeliveryRetryPolicy(max_work_attempts=3),
        engineering_policy=engineering,
    ) as (runtime, supervisor):

        def deliver() -> object:
            return supervisor.run(
                runtime,
                "task_domain_001",
                close_worktrees=lambda: None,
                terminal_result=lambda: _terminal_delivery_result(
                    runtime.task_repository, supervisor.artifacts, "task_domain_001"
                ),
            )

        with pytest.raises(DeliveryWaiting) as waiting:
            deliver()
        disposition = waiting.value.disposition
        assert disposition.facts.classification == "INVALID_OUTPUT"
        assert disposition.facts.budget_available
        (item,) = tuple(
            item
            for item in queue.items_for_task("task_domain_001")
            if item.status is not WorkItemStatus.CLOSED
        )
        assert item.status is WorkItemStatus.WAITING_DEPENDENCY
        assert disposition.action.value == "INVESTIGATE_EXECUTION"
        assert item.wait_disposition == disposition
        assert not queue.list_active_leases(now=datetime.now(UTC))
        assert supervisor.guard.lease is None
        current = runtime.task_repository.get(item.task_id)
        assert (
            current.status
            is {
                AgentRole.CODER: TaskStatus.IMPLEMENTING,
                AgentRole.QA: TaskStatus.QA,
                AgentRole.REVIEWER: TaskStatus.REVIEW,
            }[role]
        )
        assert current.attempts == current.work_attempt == 1
        assert current.retry_failures is None
        accepted = supervisor.artifacts.list_for_task(item.task_id)
        assert all(artifact.schema_version == "v0.1" for artifact in accepted)
        assert all(artifact.producer.role is not role for artifact in accepted)
        previous_requests = tuple(adapter.requests)
        with pytest.raises(DeliveryWaiting):
            deliver()
        assert tuple(adapter.requests) == previous_requests
        assert queue.get(item.id) == item
