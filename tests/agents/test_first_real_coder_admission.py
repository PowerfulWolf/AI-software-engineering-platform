"""Knowledge preparation can advance identity before the first main invocation."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentRequest,
    AgentRunStatus,
    CodexCliAgentAdapter,
    CodexInvocationResult,
    HttpResponse,
    ResponsesAgentAdapter,
)
from ai_software_engineer.agents.continuation import ContinuationExecutionUncertain
from ai_software_engineer.agents.workspace_admission import (
    FirstCoderRunWorkspaceAdmission,
    InitialWorkspaceAdmission,
)
from ai_software_engineer.knowledge.gaps import KnowledgeGap, KnowledgeGapRaised
from ai_software_engineer.knowledge.models import KnowledgeError, digest
from ai_software_engineer.recovery.admission import reject_invalid_admission
from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.work_queue.ports import DeliveryQueuePending, QueueLeaseLost
from tests.agents.test_codex_cli import _repository
from tests.agents.test_openai_compatible import StaticPromptBuilder
from tests.agents.test_responses import _request
from tests.knowledge.test_retrieval_contract import binding, snapshot


class Provider:
    calls = 0

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
    ) -> CodexInvocationResult:
        self.calls += 1
        return CodexInvocationResult(returncode=1, stderr="usage limit reached")

    def post(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> HttpResponse:
        self.calls += 1
        return HttpResponse(429, b'{"error":{"code":"insufficient_quota"}}')


def adapter_for(
    root: Path, base: str, provider: str, admission: InitialWorkspaceAdmission
) -> tuple[CodexCliAgentAdapter | ResponsesAgentAdapter, Provider, AgentRequest]:
    request, definition = _request(base)
    request = request.model_copy(update={"attempt": 2, "run_id": "run_first_actual_coder"})
    boundary = Provider()
    adapter = (
        CodexCliAgentAdapter(
            workspace_root=root,
            model="fixture",
            agent_id="agent_coder_001",
            agent_version="v0.1",
            prompt_builder=StaticPromptBuilder(),
            runner=boundary,
            initial_workspace_admission=FirstCoderRunWorkspaceAdmission(admission),
        )
        if provider == "codex"
        else ResponsesAgentAdapter(
            workspace_root=root,
            endpoint="https://example.invalid/v1/responses",
            api_key="test-key",
            model="fixture",
            agent=definition,
            transport=boundary,
            prompt_builder=StaticPromptBuilder(),
            initial_workspace_admission=FirstCoderRunWorkspaceAdmission(admission),
        )
    )
    return adapter, boundary, request


@pytest.mark.parametrize("provider", ["codex", "responses"])
@pytest.mark.parametrize("dirty_seed", [False, True])
def test_first_actual_coder_after_knowledge_only_failure_still_checks_seed_authority(
    tmp_path: Path, provider: str, dirty_seed: bool
) -> None:
    root, base = _repository(tmp_path)
    if dirty_seed:
        (root / "src").mkdir()
        (root / "src/retained.py").write_text("VALUE = 1\n", encoding="utf-8")

    class SeedAdmission:
        calls = 0

        def authorize(self, value: AgentRequest, workspace_root: Path) -> None:
            assert value.attempt == 2 and workspace_root == root
            self.calls += 1
            raise ValueError("the original approved seed authority changed before first main call")

    admission = SeedAdmission()
    adapter, boundary, request = adapter_for(root, base, provider, admission)
    result = adapter.run(request)
    assert (admission.calls, boundary.calls) == (1, 0)
    assert result.status is AgentRunStatus.FAILED
    assert result.error is not None
    assert result.error.code is AgentErrorCode.WORK_INTERRUPTED
    assert not result.error.transient
    assert "未调用模型" in result.error.message
    assert "original approved seed" not in result.error.message


@pytest.mark.parametrize("provider", ["codex", "responses"])
@pytest.mark.parametrize("phase", ["select", "authorize"])
@pytest.mark.parametrize(
    "kind", ["validation", "recovery", "store", "io", "lease", "unknown", "wait", "gap", "bug"]
)
def test_admission_rejection_and_control_signals_never_call_a_provider(
    tmp_path: Path, provider: str, phase: str, kind: str
) -> None:
    root, base = _repository(tmp_path)
    gap = KnowledgeGap(
        binding=binding(snapshot()),
        question="Which accepted rule applies?",
        required_decision="Confirm the rule",
        reason="MISSING",
        severity="BLOCKING",
        impact="Cannot determine acceptance",
        risk="high",
        evidence_ids=("a" * 64,),
        manifest_sha256="b" * 64,
        gap_id="0" * 64,
    )
    gap = gap.model_copy(update={"gap_id": digest(gap.model_dump(mode="json", exclude={"gap_id"}))})
    gap.validate_integrity()
    errors: dict[str, Exception] = {
        "validation": ValueError("invalid exact seed"),
        "recovery": RecoveryRejected("seed approval has changed"),
        "store": KnowledgeError("STORE_CORRUPT"),
        "io": OSError("trusted admission record unavailable"),
        "lease": QueueLeaseLost("owned claim expired"),
        "unknown": ContinuationExecutionUncertain("original execution remains unknown"),
        "wait": DeliveryQueuePending("wait for a dependency"),
        "gap": KnowledgeGapRaised(gap),
        "bug": RuntimeError("unexpected platform bug"),
    }
    original = errors[kind]

    class Admission:
        @reject_invalid_admission
        def for_request(self, value: AgentRequest) -> InitialWorkspaceAdmission:
            if phase == "select":
                raise original
            return self

        @reject_invalid_admission
        def authorize(self, value: AgentRequest, workspace_root: Path) -> None:
            raise original

    adapter, boundary, request = adapter_for(root, base, provider, Admission())
    if kind in {"lease", "unknown", "wait", "gap", "bug"}:
        with pytest.raises(type(original)) as caught:
            adapter.run(request)
        assert caught.value is original, "control signals retain exact ownership/wait semantics"
    else:
        result = adapter.run(request)
        assert result.status is AgentRunStatus.FAILED and result.error is not None
        assert result.error.code is AgentErrorCode.WORK_INTERRUPTED
        assert not result.error.transient and "未调用模型" in result.error.message
    assert boundary.calls == 0
