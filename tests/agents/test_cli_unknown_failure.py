"""Only recognized native main errors establish a transient provider failure."""

from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentErrorCode, AgentRunStatus, CodexCliAgentAdapter
from ai_software_engineer.agents.codex_cli import CodexInvocationResult, _classify_cli_failure
from tests.agents.test_codex_cli import _FailureRunner, _repository
from tests.agents.test_openai_compatible import StaticPromptBuilder, _coder_request


@pytest.mark.parametrize(
    "invocation",
    [
        CodexInvocationResult(returncode=1),
        CodexInvocationResult(returncode=1, stdout="Error: HTTP 401 Unauthorized"),
        CodexInvocationResult(returncode=1, stdout="truncated native transcript"),
        CodexInvocationResult(returncode=1, stderr="Error: unclassified native exit"),
        CodexInvocationResult(returncode=1, stderr="2026-10-12T00:00:00Z MCP HTTP 503"),
        CodexInvocationResult(returncode=1, stderr="MCP::error: connection failed"),
    ],
)
def test_unknown_native_exit_is_not_a_transient_provider_fact(
    invocation: CodexInvocationResult,
) -> None:
    assert _classify_cli_failure(invocation) == (AgentErrorCode.PROVIDER_UNAVAILABLE, False)


@pytest.mark.parametrize("status", [408, 500, 502, 503, 504])
def test_explicit_main_http_service_failure_keeps_bounded_transient_retry(status: int) -> None:
    invocation = CodexInvocationResult(returncode=1, stderr=f"Error: HTTP {status} Service failure")
    assert _classify_cli_failure(invocation) == (AgentErrorCode.PROVIDER_UNAVAILABLE, True)


def test_explicit_main_connection_failure_keeps_bounded_transient_retry() -> None:
    assert _classify_cli_failure(
        CodexInvocationResult(returncode=1, stderr="Error: connection failed")
    ) == (AgentErrorCode.PROVIDER_UNAVAILABLE, True)


def test_unknown_failure_is_preserved_by_actual_adapter_without_credential_guess(
    tmp_path: Path,
) -> None:
    root, base = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": base})
    result = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=_FailureRunner(stderr="Error: unclassified native exit"),
    ).run(request)
    assert result.status is AgentRunStatus.FAILED
    assert result.artifact is None and result.error is not None
    assert result.error.code is AgentErrorCode.PROVIDER_UNAVAILABLE
    assert not result.error.transient
    assert "AUTHENTICATION" not in result.error.message
    assert "unclassified native exit" not in result.error.message
