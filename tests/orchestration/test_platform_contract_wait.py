"""Rejected role contracts retain new Task checkpoints; legacy Tasks remain terminal."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.domain import AgentRole, QaReportArtifact, Task, TaskStatus
from ai_software_engineer.domain.agent import DELIVERY_ROLE_INPUTS
from ai_software_engineer.domain.engineering_authority import (
    EngineeringPolicy,
    EngineeringScope,
    LocalOperatorPrincipal,
)
from ai_software_engineer.orchestration import FileRunContextBuilder, RetryingOrchestrator
from ai_software_engineer.orchestration.runner import DeliveryContractViolation
from ai_software_engineer.store import SqliteTaskRepository
from tests.orchestration.test_retry import AttemptIdentityFactory, ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions, _task


class _WrongQaCoverage(ScriptedAdapter):
    def run(self, request: AgentRequest) -> AgentResult:
        result = super().run(request)
        if isinstance(result.artifact, QaReportArtifact):
            qa = result.artifact
            result = result.model_copy(
                update={
                    "artifact": qa.model_copy(
                        update={
                            "content": qa.content.model_copy(
                                update={
                                    "criteria_results": tuple(
                                        criterion.model_copy(
                                            update={"criterion_id": "ac_unrequested"}
                                        )
                                        for criterion in qa.content.criteria_results
                                    )
                                }
                            )
                        }
                    )
                }
            )
        return result


class _WaitingRecorded(Exception):
    """Stop the serial pass exactly as an owner-fenced wait control does."""


@dataclass
class _WaitControl:
    calls: list[tuple[Task, str, str, tuple[str, ...]]]

    def wait(
        self,
        task: Task,
        *,
        classification: str,
        reason: str,
        source_revision: str,
        artifact_ids: tuple[str, ...],
    ) -> None:
        assert "exactly cover" in reason
        self.calls.append((task, classification, source_revision, artifact_ids))
        raise _WaitingRecorded()


@pytest.mark.parametrize("engineering", [False, True])
def test_schema_valid_wrong_qa_coverage_waits_instead_of_destroying_new_checkpoint(
    tmp_path: Path,
    engineering: bool,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    task = _task(project)
    if engineering:
        policy = EngineeringPolicy.bounded_local(
            scope=EngineeringScope(
                team_id="team_contract_wait",
                project_id="project_contract_wait",
                repository_id="repository_contract_wait",
                repository_root=str(project),
            ),
            principal=LocalOperatorPrincipal.trusted_local(),
        )
        task = task.model_copy(update={"engineering_policy": policy})
    adapter = _WrongQaCoverage()
    control = _WaitControl([])
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    with SqliteTaskRepository(tmp_path / "tasks.sqlite") as repository:
        repository.create(task)
        runner = RetryingOrchestrator(
            repository=repository,
            artifact_store=artifacts,
            context_builder=FileRunContextBuilder(project),
            agent_adapter=adapter,
            agent_definitions={
                role: definition.model_copy(update={"input_artifacts": DELIVERY_ROLE_INPUTS[role]})
                for role, definition in _definitions().items()
            },
            identities=AttemptIdentityFactory(),
            clock=_clock,
            delivery_failure_control=control,
        )
        with pytest.raises(_WaitingRecorded if engineering else DeliveryContractViolation):
            runner.run_task(task.id)
        current = repository.get(task.id)
        assert current.status is (TaskStatus.QA if engineering else TaskStatus.FAILED)
        assert current.base_ref == task.base_ref and current.attempts == 1
        assert [request.role for request in adapter.requests] == [
            AgentRole.ORCHESTRATOR,
            AgentRole.CODER,
            AgentRole.QA,
        ]
        qa = artifacts.get("art_qa_001")
        assert qa.integrity.validated and qa.artifact_id in {
            artifact.artifact_id for artifact in artifacts.list_for_task(task.id)
        }
        if engineering:
            (retained, classification, source, identities) = control.calls[0]
            assert retained.status is TaskStatus.QA and classification == "PLATFORM_BUG"
            assert source == "b" * 40 and qa.artifact_id in identities
            assert all(
                event.to_status is not TaskStatus.FAILED
                for event in repository.list_events(task.id)
            )
        else:
            assert not control.calls
            assert repository.list_events(task.id)[-1].source_revision == "b" * 40
