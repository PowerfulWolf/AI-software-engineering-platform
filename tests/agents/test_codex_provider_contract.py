"""Provider admission regressions discovered during real self-delivery."""

import json

import pytest
from jsonschema import Draft202012Validator

from ai_software_engineer.agents.codex_cli import (
    CodexInvocationResult,
    _artifact_schema,
    _classify_cli_failure,
    _failure_diagnostic,
    _main_cli_failure_diagnostic,
    _recognized_cli_failure,
)
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.domain.enums import AgentRole
from tests.domain.factories import make_coder_progress_artifact, make_implementation_artifact


def test_coder_union_is_nested_under_object_root() -> None:
    schema = _artifact_schema(AgentRole.CODER)
    assert schema["type"] == "object"
    assert "anyOf" not in schema
    validator = Draft202012Validator(schema)
    for artifact in (make_coder_progress_artifact(), make_implementation_artifact()):
        # Strict output requires defaulted and nullable fields too.
        payload = json.loads(artifact.model_dump_json())
        # Durable reports omit empty observations to preserve historical hashes;
        # strict provider output must explicitly supply every schema property.
        if artifact.kind.value == "implementation-report":
            payload["content"]["project_observations"] = []
        validator.validate({"artifact": payload})
    assert not validator.is_valid({"artifact": {}})
    assert not validator.is_valid({"artifact": payload, "extra": True})


def test_invalid_schema_does_not_become_rate_limit_from_prompt_hash() -> None:
    result = CodexInvocationResult(
        returncode=1,
        stderr='user\nsha=abc429def rate limit\nERROR: {"error": '
        '{"code": "invalid_json_schema"}, "status": 400}',
    )
    assert _classify_cli_failure(result) == (AgentErrorCode.INVALID_OUTPUT, False)


def test_hash_digits_are_not_http_rate_limit() -> None:
    result = CodexInvocationResult(returncode=1, stderr="ERROR: request abc429def failed")
    assert _classify_cli_failure(result)[0] == AgentErrorCode.PROVIDER_UNAVAILABLE
    result = CodexInvocationResult(returncode=1, stderr="ERROR: HTTP 429 Too Many Requests")
    assert _classify_cli_failure(result) == (AgentErrorCode.RATE_LIMITED, True)


@pytest.mark.parametrize(
    "noise",
    [
        "mcp: fixture failed: 401 Unauthorized; sign in or login again",
        "2026-10-12T00:00:00Z ERROR rmcp::transport: authentication failed (403)",
        "Error: MCP server fixture startup failed: Missing API key (401)",
    ],
)
@pytest.mark.parametrize("position", ["before", "after"])
def test_background_auth_noise_does_not_classify_a_distinct_main_failure(
    noise: str, position: str
) -> None:
    primary = "ERROR: stream disconnected before completion: HTTP 503 Service Unavailable"
    stderr = "\n".join((noise, primary) if position == "before" else (primary, noise))
    assert _classify_cli_failure(CodexInvocationResult(returncode=1, stderr=stderr)) == (
        AgentErrorCode.PROVIDER_UNAVAILABLE,
        True,
    )


@pytest.mark.parametrize(
    "stderr",
    [
        "mcp: fixture failed: error: 401 Unauthorized; login required",
        "2026-10-12T00:00:00Z ERROR rmcp::client: HTTP 403 Forbidden; sign in again",
        "mcp startup: finished with errors; authentication unavailable",
    ],
)
def test_background_auth_noise_alone_does_not_establish_main_authentication(stderr: str) -> None:
    assert _classify_cli_failure(CodexInvocationResult(returncode=1, stderr=stderr)) == (
        AgentErrorCode.PROVIDER_UNAVAILABLE,
        True,
    )


@pytest.mark.parametrize(
    ("primary", "expected", "transient"),
    [
        ("ERROR: HTTP 401 Unauthorized", AgentErrorCode.AUTHENTICATION_ERROR, False),
        (
            "ERROR: provider request failed\n  HTTP 403 Forbidden",
            AgentErrorCode.AUTHENTICATION_ERROR,
            False,
        ),
        (
            "Error:\nAuthentication failed. Please sign in again.",
            AgentErrorCode.AUTHENTICATION_ERROR,
            False,
        ),
        (
            'ERROR: {\n  "error": {\n    "message": "401 Unauthorized"\n  }\n}',
            AgentErrorCode.AUTHENTICATION_ERROR,
            False,
        ),
        (
            'Error:\n{\n"error": {"message": "401 Unauthorized"}\n}',
            AgentErrorCode.AUTHENTICATION_ERROR,
            False,
        ),
        (
            "Error: provider request failed\n\nCaused by:\nHTTP 403 Forbidden",
            AgentErrorCode.AUTHENTICATION_ERROR,
            False,
        ),
        ("ERROR: HTTP 429 Too Many Requests", AgentErrorCode.RATE_LIMITED, True),
        ("ERROR: usage limit reached", AgentErrorCode.QUOTA_EXHAUSTED, True),
        ('ERROR: {"error": {"code": "invalid_json_schema"}}', AgentErrorCode.INVALID_OUTPUT, False),
    ],
)
def test_main_provider_failure_keeps_its_multiline_evidence_despite_background_noise(
    primary: str, expected: AgentErrorCode, transient: bool
) -> None:
    noise = "2026-10-12T00:00:00Z ERROR rmcp::client: 401 Unauthorized; login required"
    stderr = f"{noise}\n{primary}\n{noise}"
    assert _classify_cli_failure(CodexInvocationResult(returncode=1, stderr=stderr)) == (
        expected,
        transient,
    )


def test_only_the_latest_main_diagnostic_supplies_classification() -> None:
    stderr = (
        "ERROR: HTTP 401 Unauthorized\nERROR: stream disconnected: HTTP 503 Service Unavailable"
    )
    assert _classify_cli_failure(CodexInvocationResult(returncode=1, stderr=stderr)) == (
        AgentErrorCode.PROVIDER_UNAVAILABLE,
        True,
    )


@pytest.mark.parametrize(
    "marker", ["invalid_json_schema", "usage limit", "rate limit", "401 Unauthorized"]
)
def test_component_diagnostics_cannot_supply_any_main_failure_marker(marker: str) -> None:
    stderr = f"ERROR: connection failed\nmcp: fixture failed: error: {marker}"
    invocation = CodexInvocationResult(returncode=1, stderr=stderr)
    assert _recognized_cli_failure(invocation) is None
    assert "cause=UNKNOWN_EXIT" in _failure_diagnostic(invocation)


def test_successful_health_shape_and_stdout_transcript_are_not_failure_evidence() -> None:
    stderr = "\n".join(
        f"2026-10-12T00:00:00Z ERROR rmcp::client: {marker}"
        for marker in ["401 Unauthorized; login required", "authentication failed; sign in again"]
    )
    assert _recognized_cli_failure(CodexInvocationResult(returncode=0, stderr=stderr)) is None
    assert (
        _recognized_cli_failure(
            CodexInvocationResult(returncode=1, stdout="ERROR: HTTP 401 Unauthorized", stderr="")
        )
        is None
    )


def test_unrelated_prose_does_not_continue_a_json_provider_diagnostic() -> None:
    stderr = (
        'ERROR: {"error": {"message": "network failure"}}\n'
        "background authentication configured (401)"
    )
    assert _recognized_cli_failure(CodexInvocationResult(returncode=1, stderr=stderr)) is None


def test_indented_background_log_does_not_continue_a_main_error() -> None:
    stderr = "ERROR: connection failed\n  2026-10-12T00:00:00Z ERROR rmcp::client: 401 Unauthorized"
    assert _recognized_cli_failure(CodexInvocationResult(returncode=1, stderr=stderr)) is None


def test_native_diagnostic_selection_retains_fixed_tail_and_block_bounds() -> None:
    stderr = "noise" * 220_000 + "\nERROR: HTTP 403 Forbidden"
    assert _recognized_cli_failure(CodexInvocationResult(returncode=1, stderr=stderr)) is (
        AgentErrorCode.AUTHENTICATION_ERROR
    )
    stderr = "ERROR: connection failed\n  " + "x" * 64_001 + "401 Unauthorized"
    assert len(_main_cli_failure_diagnostic(stderr)) <= 64_000
    assert _recognized_cli_failure(CodexInvocationResult(returncode=1, stderr=stderr)) is None


def test_ansi_main_prefix_does_not_change_stream_digests_or_publish_private_body() -> None:
    private = "synthetic-private-fixture-body"
    invocation = CodexInvocationResult(
        returncode=1, stderr="\x1b[31mERROR:\x1b[0m HTTP 401 Unauthorized " + private
    )
    assert _recognized_cli_failure(invocation) is AgentErrorCode.AUTHENTICATION_ERROR
    diagnostic = _failure_diagnostic(invocation)
    assert "AUTHENTICATION_ERROR" in diagnostic
    assert private not in diagnostic and "\x1b" not in diagnostic


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (
            'ERROR: provider request failed\n{"error": {"message": "401 Unauthorized"}}',
            AgentErrorCode.AUTHENTICATION_ERROR,
        ),
        (
            'HTTP 500 Internal Server Error\n{\n  "error": {"code": "invalid_json_schema"}\n}',
            AgentErrorCode.INVALID_OUTPUT,
        ),
        (
            "Error: provider request failed\n{\n"
            '  "error": {"message": "HTTP 403 Forbidden", "details": ["}", "{\\""]}\n'
            "}\n  Background task: usage limit reached",
            AgentErrorCode.AUTHENTICATION_ERROR,
        ),
    ],
)
def test_complete_json_body_keeps_the_main_provider_failure(
    stderr: str, expected: AgentErrorCode
) -> None:
    assert _classify_cli_failure(CodexInvocationResult(returncode=1, stderr=stderr)) == (
        expected,
        False,
    )


@pytest.mark.parametrize(
    "stderr",
    [
        'ERROR: {"error": {"message": "connection failed"}}\n'
        '{"message": "401 Unauthorized; MCP login required"}',
        "ERROR: connection failed\n"
        "  Background task initialization failed: MCP 401 Unauthorized; login required",
        "ERROR: connection failed\n  2026-10-12 00:00:00 ERROR rmcp::client: 401 Unauthorized",
        'ERROR: provider request failed\n{"error": {"message": "connection failed"}}\n'
        '  {"message": "401 Unauthorized; MCP login required"}',
        'ERROR: provider request failed\n{"error": {"message": "connection failed"}}\n'
        "  HTTP 401 Unauthorized",
    ],
)
def test_completed_json_and_untyped_indentation_cannot_supply_authentication(stderr: str) -> None:
    result = CodexInvocationResult(returncode=1, stderr=stderr)
    assert _recognized_cli_failure(result) is None
    assert _classify_cli_failure(result) == (AgentErrorCode.PROVIDER_UNAVAILABLE, True)


def test_tail_clipping_cannot_create_a_main_error_from_a_timestamped_log() -> None:
    header = "ERROR: 401 Unauthorized\n"
    retained = header + "x" * (1_000_000 - len(header))
    result = CodexInvocationResult(returncode=1, stderr="2026-10-12T00:00:00Z " + retained)
    assert _recognized_cli_failure(result) is None


def test_json_body_must_be_complete_within_the_diagnostic_bound() -> None:
    stderr = 'ERROR: provider request failed\n{"error": {"message": "401 Unauthorized", "data": "'
    stderr += "x" * 64_000 + '"}}'
    result = CodexInvocationResult(returncode=1, stderr=stderr)
    assert _recognized_cli_failure(result) is None
    assert _classify_cli_failure(result) == (AgentErrorCode.PROVIDER_UNAVAILABLE, False)
    assert len(_main_cli_failure_diagnostic(stderr)) <= 64_000


@pytest.mark.parametrize(
    "stderr",
    [
        'ERROR: {"error": {"message": "401 Unauthorized"',
        'ERROR: provider request failed\n{"error": {"message": "401 Unauthorized"',
        "ERROR: usage limit reached " + "x" * 64_000,
    ],
    ids=["invalid-inline-json", "invalid-following-json", "oversize-root"],
)
def test_incomplete_main_diagnostic_cannot_authorize_provider_fallback(stderr: str) -> None:
    assert _classify_cli_failure(CodexInvocationResult(returncode=1, stderr=stderr))[1] is False
