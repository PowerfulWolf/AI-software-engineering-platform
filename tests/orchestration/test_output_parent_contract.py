"""Context inputs and direct artifact parents are distinct contracts."""

import json
from pathlib import Path

from ai_software_engineer.agents import AgentRequest, AgentResult
from ai_software_engineer.agents.openai_compatible import RequestPromptBuilder
from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.orchestration import BlockedResult, RetryClassification
from tests.orchestration.test_retry import ScriptedAdapter, _runner


class ContractCheckingAdapter(ScriptedAdapter):
    def run(self, request: AgentRequest) -> AgentResult:
        if request.role in (AgentRole.QA, AgentRole.REVIEWER):
            expected = (request.input_artifact_ids[-1],)
            assert request.expected_parent_artifact_ids == expected
            payload = json.loads(RequestPromptBuilder().build(request).messages[1].content)
            assert payload["output_contract"]["parent_artifact_ids"] == list(expected)
            assert len(request.input_artifact_ids) > len(expected)
        return super().run(request)


def test_runtime_transmits_exact_direct_parents_not_all_inputs(tmp_path: Path) -> None:
    task, repository, runner = _runner(tmp_path, ContractCheckingAdapter())
    try:
        assert runner.run_task(task.id).task.status is TaskStatus.DONE
    finally:
        repository.close()


class AllInputsAsParentsAdapter(ScriptedAdapter):
    def run(self, request: AgentRequest) -> AgentResult:
        result = super().run(request)
        if request.role is AgentRole.QA:
            assert result.artifact is not None
            return result.model_copy(
                update={
                    "artifact": result.artifact.model_copy(
                        update={"parent_artifact_ids": request.input_artifact_ids},
                    )
                }
            )
        return result


def test_real_qa_parent_pattern_is_invalid_output_not_platform_failure(tmp_path: Path) -> None:
    adapter = AllInputsAsParentsAdapter()
    task, repository, runner = _runner(tmp_path, adapter)
    try:
        result = runner.run_task(task.id)
        assert isinstance(result, BlockedResult)
        assert result.classification is RetryClassification.INVALID_OUTPUT
        assert result.task.status is TaskStatus.BLOCKED
        assert "parent lineage" in result.reason
        assert all(r.role is not AgentRole.REVIEWER for r in adapter.requests)
        assert sum(r.role is AgentRole.CODER for r in adapter.requests) == 1
    finally:
        repository.close()
