"""Reject invalid progress before publication without rewriting sealed invocation history."""

from pathlib import Path
from typing import Literal

import pytest

from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentRequest,
    AgentResult,
)
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.orchestration import (
    AgentRunFailed,
    FileRunContextBuilder,
    SerialOrchestrator,
)
from ai_software_engineer.store import SqliteTaskRepository
from tests.domain.factories import make_plan_artifact
from tests.orchestration.test_runner import FixedIdentityFactory, _clock, _definitions, _task
from tests.work_queue.test_invocation_journal import _progress_result


class _Adapter:
    def __init__(self, sequence: int) -> None:
        self.sequence = sequence
        self.calls = 0

    def run(self, request: AgentRequest) -> AgentResult:
        self.calls += 1
        return _progress_result(request, self.sequence)


class _InvocationControl:
    def __init__(self, mode: Literal["live", "replay", "replay_rejected"], sequence: int) -> None:
        self.mode, self.sequence = mode, sequence
        self.completions: list[AgentResult] = []

    def prepare(self, request: AgentRequest) -> AgentRequest:
        return request

    def has_started(self, request: AgentRequest) -> bool:
        return self.mode != "live"

    def result(self, request: AgentRequest) -> AgentResult | None:
        if self.mode == "live":
            return None
        result = _progress_result(request, self.sequence)
        if self.mode == "replay_rejected":
            result.validate_current_output()
        return result

    def completed(self, request: AgentRequest, result: AgentResult) -> None:
        self.completions.append(result)


@pytest.mark.parametrize("sequence", [4, 8, 9])
@pytest.mark.parametrize("mode", ["live", "replay", "replay_rejected"])
def test_progress_acceptance_precedes_artifact_publication_and_preserves_replay(
    tmp_path: Path, mode: Literal["live", "replay", "replay_rejected"], sequence: int
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    task = _task(root).model_copy(update={"status": TaskStatus.IMPLEMENTING, "attempts": 4})
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    plan = seal_artifact(make_plan_artifact(), validated_at=_clock())
    artifacts.put(plan)
    adapter = _Adapter(sequence)
    invocation = _InvocationControl(mode, sequence)
    with SqliteTaskRepository(tmp_path / "state.sqlite3") as repository:
        repository.create(task)
        runner = SerialOrchestrator(
            repository=repository,
            artifact_store=artifacts,
            context_builder=FileRunContextBuilder(root),
            agent_adapter=adapter,
            agent_definitions=_definitions(),
            identities=FixedIdentityFactory(),
            clock=_clock,
            invocation_control=invocation,
        )
        if sequence == 4:
            runner._run_agent(
                task,
                AgentRole.CODER,
                attempt=4,
                candidate_revision=None,
                input_artifacts=(plan,),
                expected_parents=("art_plan_001",),
                seen_run_ids=set(),
            )
            assert len(artifacts.list_for_task(task.id)) == 2
        else:
            with pytest.raises(AgentRunFailed) as captured:
                runner._run_agent(
                    task,
                    AgentRole.CODER,
                    attempt=4,
                    candidate_revision=None,
                    input_artifacts=(plan,),
                    expected_parents=("art_plan_001",),
                    seen_run_ids=set(),
                )
            error = captured.value.result.error
            assert error is not None and error.code is AgentErrorCode.INVALID_OUTPUT
            assert not error.transient
            assert captured.value.result.artifact is None
            assert artifacts.list_for_task(task.id) == (plan,)
        assert adapter.calls == int(mode == "live")
        assert len(invocation.completions) == int(mode == "live")
        if mode == "live" and sequence != 4:
            assert invocation.completions[0].error is not None
            assert invocation.completions[0].error.code is AgentErrorCode.INVALID_OUTPUT
