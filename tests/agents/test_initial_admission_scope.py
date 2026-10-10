"""Recovery seed admission is run-scoped, not tied to a provider object lifetime."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentRequest,
    AgentRunStatus,
    CodexCliAgentAdapter,
    CodexInvocationResult,
    HttpResponse,
    ResponsesAgentAdapter,
)
from ai_software_engineer.agents.workspace_admission import FirstCoderRunWorkspaceAdmission
from tests.agents.test_codex_cli import (
    _DirtySuccessRunner,
    _FailureRunner,
    _git,
    _ProgressRunner,
    _repository,
)
from tests.agents.test_openai_compatible import StaticPromptBuilder, _coder_request
from tests.agents.test_responses import _request as responses_request


class Admission:
    def __init__(self) -> None:
        self.attempts: list[int] = []

    def authorize(self, request: AgentRequest, workspace_root: Path) -> None:
        assert workspace_root.is_dir()
        self.attempts.append(request.attempt)
        if request.attempt != 1:
            raise ValueError("the recovery seed is only authorized for its initial Run")


def progress(tmp_path: Path) -> tuple[Path, AgentRequest, Admission]:
    root, base = _repository(tmp_path)
    first = _coder_request().model_copy(update={"source_revision": base})
    admission = Admission()
    result = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=_ProgressRunner(first),
        initial_workspace_admission=FirstCoderRunWorkspaceAdmission(admission),
    ).run(first)
    assert result.status is AgentRunStatus.SUCCEEDED
    assert result.artifact is not None and result.artifact.kind.value == "coder-progress"
    request = AgentRequest.model_validate(
        {
            **first.to_wire(),
            "run_id": "run_recovery_next",
            "attempt": 2,
            "input_artifact_ids": [result.artifact.artifact_id],
            "continuation_checkpoint_id": result.artifact.artifact_id,
            "continuation_changed_paths": ["src/partial.py"],
        }
    )
    return root, request, admission


def test_fresh_codex_adapter_resumes_accepted_progress_without_replaying_seed(
    tmp_path: Path,
) -> None:
    root, request, admission = progress(tmp_path)
    result = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=_DirtySuccessRunner(request, changed_path="src/partial.py"),
        initial_workspace_admission=FirstCoderRunWorkspaceAdmission(admission),
    ).run(request)
    assert result.status is AgentRunStatus.SUCCEEDED
    assert result.artifact is not None and result.artifact.kind.value == "implementation-report"
    assert admission.attempts == [1]
    assert _git(root, "status", "--porcelain") == ""


@pytest.mark.parametrize("provider", ["codex", "responses"])
@pytest.mark.parametrize("drift", ["none", "extra_path", "checkpoint", "head"])
def test_later_runs_keep_normal_checkpoint_and_source_checks(
    tmp_path: Path, provider: str, drift: str
) -> None:
    root, request, admission = progress(tmp_path)
    if drift == "extra_path":
        (root / "src/unreported.py").write_text("VALUE = 1\n")
    elif drift == "checkpoint":
        request = request.model_copy(update={"continuation_changed_paths": ("src/other.py",)})
    elif drift == "head":
        _git(root, "commit", "--allow-empty", "-qm", "source drift")

    class Provider:
        calls = 0

        def post(
            self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
        ) -> HttpResponse:
            self.calls += 1
            return HttpResponse(429, b'{"error":{"code":"insufficient_quota"}}')

    wrapped = FirstCoderRunWorkspaceAdmission(admission)
    if provider == "responses":
        _, definition = responses_request(request.source_revision)
        request = request.model_copy(update={"permissions": definition.permissions})
        transport = Provider()
        result = ResponsesAgentAdapter(
            workspace_root=root,
            endpoint="https://example.invalid/v1/responses",
            api_key="test-key",
            model="fixture",
            agent=definition,
            transport=transport,
            prompt_builder=StaticPromptBuilder(),
            initial_workspace_admission=wrapped,
        ).run(request)
        assert transport.calls == (1 if drift == "none" else 0)
    else:

        class Runner(_DirtySuccessRunner):
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
                return super().run(
                    argv,
                    cwd=cwd,
                    environment=environment,
                    stdin=stdin,
                    timeout_seconds=timeout_seconds,
                )

        runner = Runner(request, changed_path="src/partial.py")
        result = CodexCliAgentAdapter(
            workspace_root=root,
            model="fixture",
            agent_id="agent_coder_001",
            agent_version="v0.1",
            runner=runner,
            prompt_builder=StaticPromptBuilder(),
            initial_workspace_admission=wrapped,
        ).run(request)
        assert runner.calls == (1 if drift == "none" else 0)
    if provider == "codex" and drift == "none":
        assert result.status is AgentRunStatus.SUCCEEDED
    else:
        assert result.status is AgentRunStatus.FAILED and result.error is not None
        assert result.error.transient is (drift == "none")
    assert admission.attempts == [1]


class QuotaProvider:
    calls = 0

    def post(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> HttpResponse:
        self.calls += 1
        return HttpResponse(429, b'{"error":{"code":"insufficient_quota"}}')


@pytest.mark.parametrize("provider", ["codex", "responses"])
def test_default_baseline_admission_still_checks_every_run(tmp_path: Path, provider: str) -> None:
    root, base = _repository(tmp_path)
    request, definition = responses_request(base)
    request = request.model_copy(update={"attempt": 2})

    class BaselineAdmission:
        calls = 0

        def authorize(self, value: AgentRequest, workspace_root: Path) -> None:
            assert value.attempt == 2 and workspace_root == root
            self.calls += 1
            if self.calls > 1:
                raise ValueError("current baseline/claim drifted")

    admission = BaselineAdmission()
    transport = QuotaProvider()
    adapter = (
        CodexCliAgentAdapter(
            workspace_root=root,
            model="fixture",
            agent_id="agent_coder_001",
            agent_version="v0.1",
            initial_workspace_admission=admission,
            runner=_FailureRunner(),
            prompt_builder=StaticPromptBuilder(),
        )
        if provider == "codex"
        else ResponsesAgentAdapter(
            workspace_root=root,
            endpoint="https://example.invalid/v1/responses",
            api_key="test-key",
            model="fixture",
            agent=definition,
            transport=transport,
            prompt_builder=StaticPromptBuilder(),
            initial_workspace_admission=admission,
        )
    )
    for run_id in ["run_baseline_1", "run_baseline_2"]:
        current = request.model_copy(update={"run_id": run_id})
        # The baseline port must remain authoritative on later attempts. Unlike
        # the recovery seed it is not wrapped in first-Run-only policy.
        result = adapter.run(current)
        assert result.status is AgentRunStatus.FAILED and result.error is not None
        assert result.error.transient is (run_id == "run_baseline_1")
    assert admission.calls == 2
    if provider == "responses":
        assert transport.calls == 1


@pytest.mark.parametrize("provider", ["codex", "responses"])
def test_fresh_adapter_after_verifier_feedback_uses_clean_candidate(
    tmp_path: Path, provider: str
) -> None:
    root, base = _repository(tmp_path)
    first = _coder_request().model_copy(update={"source_revision": base})
    admission = Admission()
    result = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=_DirtySuccessRunner(first),
        initial_workspace_admission=FirstCoderRunWorkspaceAdmission(admission),
    ).run(first)
    assert result.artifact is not None and result.status is AgentRunStatus.SUCCEEDED
    request = first.model_copy(
        update={
            "run_id": "run_verifier_feedback",
            "attempt": 2,
            "source_revision": result.artifact.source_revision,
            "input_artifact_ids": ("art_qa_feedback",),
        }
    )
    transport = QuotaProvider()
    if provider == "responses":
        _, definition = responses_request(request.source_revision)
        request = request.model_copy(update={"permissions": definition.permissions})
        result = ResponsesAgentAdapter(
            workspace_root=root,
            endpoint="https://example.invalid/v1/responses",
            api_key="test-key",
            model="fixture",
            agent=definition,
            transport=transport,
            prompt_builder=StaticPromptBuilder(),
            initial_workspace_admission=FirstCoderRunWorkspaceAdmission(admission),
        ).run(request)
        assert transport.calls == 1
    else:
        result = CodexCliAgentAdapter(
            workspace_root=root,
            model="fixture",
            agent_id="agent_coder_001",
            agent_version="v0.1",
            prompt_builder=StaticPromptBuilder(),
            runner=_FailureRunner(),
            initial_workspace_admission=FirstCoderRunWorkspaceAdmission(admission),
        ).run(request)
    assert result.status is AgentRunStatus.FAILED and result.error is not None
    assert result.error.transient is True
    assert admission.attempts == [1]
    assert _git(root, "status", "--porcelain") == ""
