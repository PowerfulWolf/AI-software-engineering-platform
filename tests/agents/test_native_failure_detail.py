"""Native failures preserve safe main details without changing retry authority."""

import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentRequest,
    AgentResult,
    CodexCliAgentAdapter,
    FallbackAgentAdapter,
    FileModelRouteAttemptStore,
    ProviderAgentRoute,
    RouteAttemptOutcome,
)
from ai_software_engineer.agents.codex_cli import (
    CodexInvocationResult,
    _classify_cli_failure,
    _safe_cli_failure_detail,
)
from ai_software_engineer.agents.execution import ExecutionAbortReason, ExecutionAuthorityLost
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.work_queue.invocation import DurableInvocationControl
from tests.agents.test_codex_cli import _FailureRunner, _repository
from tests.agents.test_openai_compatible import StaticPromptBuilder, _coder_request
from tests.work_queue.test_invocation_journal import guard

UNAVAILABLE = "未获得可安全展示的原生主错误详情"


@pytest.mark.parametrize(
    "proxy_key",
    ["synthetic key", "synthetic\tkey", "synthetic\nkey", "synthetic\x07key"],
)
def test_proxy_key_with_normalization_sensitive_characters_hides_detail(proxy_key: str) -> None:
    invocation = CodexInvocationResult(returncode=1, stderr="Error: native failure")
    assert (
        _safe_cli_failure_detail(invocation, proxy_key_required=True, proxy_key=proxy_key)
        == UNAVAILABLE
    )


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (
            "Error: stream disconnected before completion",
            "Error: stream disconnected before completion",
        ),
        (
            'Error: {"error":{"message":"native failure","prompt":"private"},"request":"private"}',
            "native failure",
        ),
        (
            'Error: provider failed\n{"message":"provider message","debug":"private"}',
            "provider message",
        ),
        (
            'Error: unexpected status 500: {"error":{"message":"native message"},'
            '"prompt":"private"}',
            "native message",
        ),
        ('Error: request failed with {"prompt":"private"}', UNAVAILABLE),
        ('Error: request failed with ["private"]', UNAVAILABLE),
        ('Error: {"message":"top message","error":{"code":"private"}}', "top message"),
        ('Error: {"error":{"code":"private"},"prompt":"private"}', UNAVAILABLE),
        (
            "Error: provider failed\nCaused by: private detail\n"
            "Traceback (most recent call last):\nprivate",
            "Error: provider failed",
        ),
        (
            "Error: provider failed\n2026-10-16T00:00:00Z MCP HTTP 401 private",
            "Error: provider failed",
        ),
        ("2026-10-16T00:00:00Z Error: background private", UNAVAILABLE),
        ("MCP::error: connection failed private", UNAVAILABLE),
        ("Error: MCP: failed private", UNAVAILABLE),
        ("untrusted transcript private", UNAVAILABLE),
        ('Error: {"error":{"message":"incomplete private"}', UNAVAILABLE),
        ("", UNAVAILABLE),
    ],
)
def test_only_selected_complete_main_diagnostic_is_displayable(stderr: str, expected: str) -> None:
    invocation = CodexInvocationResult(
        returncode=1, stderr=stderr, stdout='{"error":{"message":"stdout private"}}'
    )
    before = _classify_cli_failure(invocation)
    assert _safe_cli_failure_detail(invocation) == expected
    assert _classify_cli_failure(invocation) == before


def test_redaction_precedes_selection_and_truncation() -> None:
    stderr = (
        "Error: -----BEGIN PRIVATE KEY-----\n"
        "Error: synthetic-private-key-material\n"
        "-----END PRIVATE KEY-----"
    )
    assert _safe_cli_failure_detail(CodexInvocationResult(returncode=1, stderr=stderr)) == (
        "Error: [REDACTED:private_key]"
    )
    stderr = (
        "\x1b[31mError:\x1b[0m password=synthetic-password "
        "Bearer synthetic-bearer-token "
        "sk-abcdefghijklmnopqrstuvwxyz012345 "
        "https://user:synthetic-password@example.invalid/private "
        "mysql://user:synthetic-password@localhost/db\x07 " + "x" * 700
    )
    detail = _safe_cli_failure_detail(CodexInvocationResult(returncode=1, stderr=stderr))
    assert len(detail) == 500 and detail.endswith("…")
    assert "Error:" in detail and "[REDACTED:" in detail
    for private in (
        "synthetic-password",
        "synthetic-bearer",
        "sk-abc",
        "https://",
        "mysql://",
        "\x1b",
        "\x07",
    ):
        assert private not in detail


@pytest.mark.parametrize("proxy_key", [None, ""])
def test_configured_proxy_without_exact_key_hides_detail(proxy_key: str | None) -> None:
    invocation = CodexInvocationResult(returncode=1, stderr="Error: unknown proxy value")
    assert (
        _safe_cli_failure_detail(invocation, proxy_key_required=True, proxy_key=proxy_key)
        == UNAVAILABLE
    )


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("encoding", ["json_string", "unicode", "mixed"])
def test_proxy_encoded_credential_fails_closed(structured: bool, encoding: str) -> None:
    key = 'synthetic"unlabeled\\credential'
    if encoding == "json_string":
        encoded = json.dumps(key)
    elif encoding == "unicode":
        encoded = "".join(f"\\u{ord(character):04x}" for character in key)
    else:
        encoded = "\\u0073" + json.dumps(key[1:])[1:-1]
    message = "failed proxy value " + encoded
    stderr = "Error: " + (json.dumps({"error": {"message": message}}) if structured else message)
    invocation = CodexInvocationResult(returncode=1, stderr=stderr)
    before = _classify_cli_failure(invocation)
    assert (
        _safe_cli_failure_detail(invocation, proxy_key_required=True, proxy_key=key) == UNAVAILABLE
    )
    assert _classify_cli_failure(invocation) == before


@pytest.mark.parametrize("formatting", ["\x1b[31m", "\x1b]8;;link\x07"])
@pytest.mark.parametrize("prefix_length", [0, 470])
def test_proxy_key_reconstructed_by_formatting_is_redacted_before_limit(
    formatting: str, prefix_length: int
) -> None:
    key = "synthetic-unlabeled-proxy-credential"
    stderr = "Error: failed " + "x" * prefix_length + key[:10] + formatting + key[10:]
    detail = _safe_cli_failure_detail(
        CodexInvocationResult(returncode=1, stderr=stderr),
        proxy_key_required=True,
        proxy_key=key,
    )
    assert key not in detail and key[:10] not in detail
    assert "[REDACTED:" in detail
    assert len(detail) <= 500


@pytest.mark.parametrize("stderr_truncated", [False, True])
def test_truncated_input_never_displays_partial_diagnostic(stderr_truncated: bool) -> None:
    invocation = CodexInvocationResult(
        returncode=1,
        stderr=("" if stderr_truncated else "x" * 1_000_001) + "\nError: private clipped body",
        stderr_truncated=stderr_truncated,
    )
    assert _safe_cli_failure_detail(invocation) == UNAVAILABLE


@pytest.mark.parametrize(
    "key", ["synthetic-unlabeled-proxy-credential", 'synthetic"unlabeled\\credential']
)
def test_adapter_redacts_unlabeled_exact_proxy_key(tmp_path: Path, key: str) -> None:
    root, base = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": base})
    result = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        proxy_base_url="http://127.0.0.1:8317/v1",
        proxy_api_key_env="ASE_CODEX_PROXY_API_KEY",
        environment={"PATH": "/usr/bin:/bin", "ASE_CODEX_PROXY_API_KEY": key},
        prompt_builder=StaticPromptBuilder(),
        runner=_FailureRunner(
            stderr="Error: "
            + json.dumps({"error": {"message": f"failure {key}"}, "debug": "private"})
        ),
    ).run(request)
    assert result.error is not None
    assert result.error.code is AgentErrorCode.PROVIDER_UNAVAILABLE
    assert not result.error.transient
    assert 'main_error="failure [REDACTED:api_key]"' in result.error.message
    assert key not in result.model_dump_json() and "debug" not in result.model_dump_json()


class _MustNotRun:
    def run(self, request: AgentRequest) -> AgentResult:
        raise AssertionError("persisted nontransient failure must not call a provider")


class _InvocationRunner:
    def __init__(self, invocation: CodexInvocationResult) -> None:
        self.invocation = invocation

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
    ) -> CodexInvocationResult:
        del argv, cwd, environment, stdin, timeout_seconds
        return self.invocation


@pytest.mark.parametrize("abort", [False, True])
def test_timeout_and_guard_abort_do_not_publish_provider_prose(tmp_path: Path, abort: bool) -> None:
    root, base = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": base})
    invocation = CodexInvocationResult(
        returncode=-1,
        stderr="Error: private provider body",
        timed_out=not abort,
        execution_abort_reason=ExecutionAbortReason() if abort else None,
    )
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=_InvocationRunner(invocation),
    )
    if abort:
        with pytest.raises(ExecutionAuthorityLost) as captured:
            adapter.run(request)
        assert "private provider body" not in str(captured.value)
    else:
        result = adapter.run(request)
        assert result.error is not None and result.error.code is AgentErrorCode.TIMEOUT
        assert result.error.transient
        assert "main_error=" not in result.error.message
        assert "private provider body" not in result.error.message


def test_native_subprocess_safe_failure_survives_route_and_outcome_reopen(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    executable = tmp_path / "offline-codex"
    stderr = (
        'Error: {"error":{"message":"stream disconnected password=synthetic-password"},'
        '"prompt":"private"}'
    )
    executable.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "sys.stdin.read()\n"
        f"sys.stderr.write({stderr!r})\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    request = _coder_request().model_copy(update={"source_revision": base})
    native = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        executable=str(executable),
        environment={"PATH": "/usr/bin:/bin"},
        prompt_builder=StaticPromptBuilder(),
    )
    records_root = tmp_path / "invocations"
    control = DurableInvocationControl(KnowledgeRecordStore(records_root), guard(request))
    control.prepare(request)
    routes_root = tmp_path / "routes"
    routes = (
        ProviderAgentRoute("codex", "fixture", native),
        ProviderAgentRoute("backup", "fixture", _MustNotRun()),
    )
    result = FallbackAgentAdapter(
        routes, attempt_store=FileModelRouteAttemptStore(routes_root)
    ).run(request)
    control.completed(request, result)
    assert result.error is not None
    assert result.error.code is AgentErrorCode.PROVIDER_UNAVAILABLE and not result.error.transient
    assert (
        'main_error="stream disconnected password=[REDACTED:secret_assignment]"'
        in result.error.message
    )
    assert "stderr_sha256=" + hashlib.sha256(stderr.encode()).hexdigest() in result.error.message
    assert "synthetic-password" not in result.model_dump_json()
    assert "private" not in result.model_dump_json()
    assert AgentResult.model_validate_json(result.model_dump_json()) == result
    original_bytes = {
        path: path.read_bytes()
        for parent in (routes_root, records_root)
        for path in parent.rglob("*.json")
    }
    reopened_routes = FileModelRouteAttemptStore(routes_root)
    attempts = reopened_routes.list_for_run(request.run_id)
    assert len(attempts) == 1 and attempts[0].outcome is RouteAttemptOutcome.FAILED
    assert attempts[0].result == result
    replayed = FallbackAgentAdapter(
        tuple(ProviderAgentRoute(route.provider, route.model, _MustNotRun()) for route in routes),
        attempt_store=reopened_routes,
    ).run(request)
    assert replayed == result
    reopened = DurableInvocationControl(KnowledgeRecordStore(records_root), guard(request))
    assert reopened.prepare(request) == request
    assert reopened.result(request) == result
    assert all(path.read_bytes() == body for path, body in original_bytes.items())
