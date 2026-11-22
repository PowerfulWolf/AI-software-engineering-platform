"""Local Claude Code CLI as a structured route for upstream roles."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentErrorCode, StructuredModelError, claude_cli
from ai_software_engineer.agents.claude_cli import (
    ClaudeCliStructuredModelClient,
    parse_claude_result,
)

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


def _client(tmp_path: Path, *, reads: bool = True) -> ClaudeCliStructuredModelClient:
    return ClaudeCliStructuredModelClient(
        repository_root=tmp_path,
        model="claude-opus-5-5",
        executable="/opt/claude",
        reasoning_effort="medium",
        environment={"PATH": "/usr/bin", "HOME": str(tmp_path), "SOL_6_API_KEY": "secret"},
        allow_repository_reads=reads,
    )


def test_argv_is_read_only_structured_and_pinned_to_the_model(tmp_path: Path) -> None:
    argv = _client(tmp_path).argv(SCHEMA)
    assert argv[:2] == ("/opt/claude", "-p")
    joined = " ".join(argv)
    assert "--model claude-opus-5-5" in joined and "--effort medium" in joined
    assert argv[argv.index("--tools") + 1] == "Read,Grep,Glob"
    assert "--no-session-persistence" in argv and "--strict-mcp-config" in argv
    assert json.loads(argv[argv.index("--json-schema") + 1])["required"] == ["answer"]
    for forbidden in ("Edit", "Write", "Bash", "--dangerously-skip-permissions"):
        assert forbidden not in argv


def test_manager_gets_no_tools(tmp_path: Path) -> None:
    argv = _client(tmp_path, reads=False).argv(SCHEMA)
    assert argv[argv.index("--tools") + 1] == ""
    assert "--allowedTools" not in argv


def test_environment_drops_unrelated_secrets(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert "SOL_6_API_KEY" not in client._environment
    assert client._environment["PATH"].startswith(str(tmp_path / ".local" / "bin"))


def test_structured_output_and_usage_are_parsed() -> None:
    stdout = json.dumps(
        {
            "is_error": False,
            "structured_output": {"answer": "ok"},
            "usage": {"input_tokens": 2, "cache_read_input_tokens": 10, "output_tokens": 5},
        }
    )
    result = parse_claude_result(0, stdout, "", started=time.monotonic())
    assert result.payload == {"answer": "ok"}
    assert result.usage is not None and result.usage.total_tokens == 17


def test_result_text_json_is_accepted_when_structured_field_is_absent() -> None:
    stdout = json.dumps({"is_error": False, "result": '{"answer": "ok"}'})
    assert parse_claude_result(0, stdout, "", started=0.0).payload == {"answer": "ok"}


@pytest.mark.parametrize(
    ("document", "code", "transient"),
    [
        ({"is_error": True, "result": "API Error: 529 Overloaded"}, "PROVIDER_UNAVAILABLE", True),
        ({"is_error": True, "api_error_status": 429, "result": "x"}, "PROVIDER_UNAVAILABLE", True),
        (
            {"is_error": True, "result": "Invalid API key · Please run /login"},
            "AUTHENTICATION_ERROR",
            False,
        ),
        ({"is_error": True, "subtype": "error_max_turns"}, "PROVIDER_ERROR", False),
    ],
)
def test_failures_are_classified(document: dict[str, object], code: str, transient: bool) -> None:
    with pytest.raises(StructuredModelError) as raised:
        parse_claude_result(1, json.dumps(document), "", started=0.0)
    assert raised.value.code is AgentErrorCode(code)
    assert raised.value.transient is transient


def test_missing_structured_output_is_invalid() -> None:
    with pytest.raises(StructuredModelError) as raised:
        parse_claude_result(0, json.dumps({"is_error": False, "result": "hello"}), "", started=0.0)
    assert raised.value.code is AgentErrorCode.INVALID_OUTPUT


def test_complete_runs_the_cli_and_returns_the_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_run(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["argv"], seen["cwd"], seen["input"] = argv, kwargs["cwd"], kwargs["input"]
        return subprocess.CompletedProcess(
            argv, 0, json.dumps({"structured_output": {"answer": "ok"}}), ""
        )

    monkeypatch.setattr(claude_cli, "run_structured_command", fake_run)
    result = _client(tmp_path).complete(
        instructions="Act as Designer.",
        input_payload={"k": 1},
        output_schema=SCHEMA,
        timeout_seconds=30,
    )
    assert result.payload == {"answer": "ok"}
    assert seen["cwd"] == tmp_path.resolve()
    assert "Act as Designer." in str(seen["input"])


def test_images_are_refused_so_fallback_can_choose_another_route(tmp_path: Path) -> None:
    with pytest.raises(StructuredModelError):
        _client(tmp_path).complete(
            instructions="x",
            input_payload={},
            output_schema=SCHEMA,
            timeout_seconds=30,
            input_images=(tmp_path / "a.png",),
        )
