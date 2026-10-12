"""Input capacity is a pre-invocation dependency, not an exhausted retry allowance."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.context import ContextBudgetExceeded, ContextBundle
from ai_software_engineer.domain import AgentRole, Artifact, Task, TaskStatus
from ai_software_engineer.domain.agent import AgentDefinition
from ai_software_engineer.domain.engineering_authority import (
    EngineeringPolicy,
    EngineeringScope,
    LocalOperatorPrincipal,
)
from ai_software_engineer.orchestration import (
    BlockedResult,
    FileRunContextBuilder,
    RetryingOrchestrator,
)
from ai_software_engineer.store import SqliteTaskRepository
from tests.manager.test_terminal_candidate_reconstruction import _BaselineResolver, _binding
from tests.orchestration.test_retry import AttemptIdentityFactory, ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions, _task


class _CapacityContexts(FileRunContextBuilder):
    def __init__(self, root: Path, role: AgentRole) -> None:
        super().__init__(root)
        self.role = role

    def build(
        self,
        task: Task,
        agent: AgentDefinition,
        *,
        attempt: int,
        candidate_revision: str | None = None,
        input_artifacts: tuple[Artifact, ...] = (),
    ) -> ContextBundle:
        if agent.role is self.role:
            raise ContextBudgetExceeded("required input exceeds frozen capacity")
        return super().build(
            task,
            agent,
            attempt=attempt,
            candidate_revision=candidate_revision,
            input_artifacts=input_artifacts,
        )


class _FinalInputAdapter(ScriptedAdapter):
    """Separate the adapter's final-input preflight from its provider launch."""

    def __init__(self, role: AgentRole) -> None:
        super().__init__()
        self.role = role

    def run(self, request: AgentRequest) -> AgentResult:
        if request.role is self.role:
            raise ContextBudgetExceeded("final provider input exceeds frozen capacity")
        return super().run(request)


class _WaitingRecorded(Exception):
    pass


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
        assert "上下文" in reason and "未启动" in reason
        self.calls.append((task, classification, source_revision, artifact_ids))
        raise _WaitingRecorded()


@pytest.mark.parametrize("engineering", [False, True])
@pytest.mark.parametrize("final_input", [False, True])
@pytest.mark.parametrize("role", [AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER])
def test_capacity_failure_keeps_checkpoint_and_does_not_launch_role(
    tmp_path: Path, engineering: bool, final_input: bool, role: AgentRole
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    task = _task(project)
    if engineering:
        task = task.model_copy(
            update={
                "engineering_policy": EngineeringPolicy.bounded_local(
                    scope=EngineeringScope(
                        team_id="team_capacity",
                        project_id="project_capacity",
                        repository_id="repository_capacity",
                        repository_root=str(project),
                    ),
                    principal=LocalOperatorPrincipal.trusted_local(),
                )
            }
        )
    adapter = _FinalInputAdapter(role) if final_input else ScriptedAdapter()
    contexts = FileRunContextBuilder(project) if final_input else _CapacityContexts(project, role)
    control = _WaitControl([])
    with SqliteTaskRepository(tmp_path / "tasks.sqlite") as repository:
        repository.create(task)
        runner = RetryingOrchestrator(
            repository=repository,
            artifact_store=FileArtifactStore(tmp_path / "artifacts"),
            context_builder=contexts,
            agent_adapter=adapter,
            agent_definitions=_definitions(),
            identities=AttemptIdentityFactory(),
            clock=_clock,
            delivery_failure_control=control,
        )
        if engineering:
            with pytest.raises(_WaitingRecorded):
                runner.run_task(task.id)
        else:
            result = runner.run_task(task.id)
            assert isinstance(result, BlockedResult)
            assert result.classification.value == "CONTEXT_CAPACITY"
        current = repository.get(task.id)
        expected = {
            AgentRole.CODER: TaskStatus.IMPLEMENTING,
            AgentRole.QA: TaskStatus.QA,
            AgentRole.REVIEWER: TaskStatus.REVIEW,
        }[role]
        assert current.status is (expected if engineering else TaskStatus.BLOCKED)
        assert current.attempts == 1 and current.retry_failures == task.retry_failures
        assert current.base_ref == task.base_ref
        assert role not in {request.role for request in adapter.requests}
        events = repository.list_events(task.id)
        if engineering:
            ((retained, classification, source, artifact_ids),) = control.calls
            assert retained == current and classification == "CONTEXT_CAPACITY"
            assert source == (task.base_ref if role is AgentRole.CODER else "b" * 40)
            assert artifact_ids == tuple(
                dict.fromkeys(artifact_id for event in events for artifact_id in event.artifact_ids)
            )
            assert all(
                event.to_status not in {TaskStatus.BLOCKED, TaskStatus.FAILED} for event in events
            )
        else:
            assert not control.calls
            assert events[-1].reason.startswith("CONTEXT_CAPACITY: ")


def test_capacity_failure_binds_current_execution_source_instead_of_old_event_source(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    task = _task(project)
    task = task.model_copy(update={"base_ref": "a" * 40, "branch_name": "ai/feature/capacity"})
    binding = _binding(task)
    assert binding.execution_source_revision != task.base_ref
    adapter = ScriptedAdapter()
    with SqliteTaskRepository(tmp_path / "task.sqlite") as repository:
        repository.create(task)
        runner = RetryingOrchestrator(
            repository=repository,
            artifact_store=FileArtifactStore(tmp_path / "artifacts"),
            context_builder=_CapacityContexts(project, AgentRole.CODER),
            agent_adapter=adapter,
            agent_definitions=_definitions(),
            identities=AttemptIdentityFactory(),
            clock=_clock,
            coder_execution_inputs=_BaselineResolver(binding),
        )
        result = runner.run_task(task.id)
        assert isinstance(result, BlockedResult)
        assert result.classification.value == "CONTEXT_CAPACITY"
        events = repository.list_events(task.id)
        assert events[-2].source_revision == task.base_ref
        assert events[-1].source_revision == binding.execution_source_revision
        assert result.task.base_ref == task.base_ref
        assert [request.role for request in adapter.requests] == [AgentRole.ORCHESTRATOR]
