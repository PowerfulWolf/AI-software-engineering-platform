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


TURN = {
    "model": "m",
    "input": [
        {"role": "system", "content": [{"type": "input_text", "text": "You are the Coder."}]},
        {"role": "user", "content": [{"type": "input_text", "text": "Fix the FAQ."}]},
        {"type": "reasoning", "id": "r", "summary": []},
        {"type": "function_call", "call_id": "c1", "name": "read_file", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": "line 1"},
    ],
    "tools": [
        {"type": "function", "name": "read_file", "parameters": {"type": "object"}},
        {"type": "function", "name": "write_file", "parameters": {"type": "object"}},
    ],
    "text": {"format": {"type": "json_schema", "schema": {"type": "object", "title": "Art"}}},
}


def test_turn_rendering_keeps_the_whole_conversation_and_tool_contract() -> None:
    from ai_software_engineer.agents.claude_cli import render_responses_turn

    prompt, schema = render_responses_turn(TURN)
    assert "You are the Coder." in prompt and "Fix the FAQ." in prompt
    assert "TOOL RESULT [c1]:\nline 1" in prompt and '"title": "Art"' in prompt
    names = schema["properties"]["tool_calls"]["items"]["properties"]["name"]["enum"]  # type: ignore[index]
    assert names == ["read_file", "write_file"]


def _transport(monkeypatch: pytest.MonkeyPatch, stdout: str, code: int = 0):  # type: ignore[no-untyped-def]
    from ai_software_engineer.agents.claude_cli import ClaudeCliResponsesTransport

    seen: dict[str, object] = {}

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        seen["argv"], seen["input"] = argv, kwargs["input"]
        return subprocess.CompletedProcess(argv, code, stdout, "")

    monkeypatch.setattr("ai_software_engineer.owned_processes.run_owned_subprocess", fake_run)
    return ClaudeCliResponsesTransport(model="claude-opus-5-5", executable="/opt/claude"), seen


def test_transport_turns_tool_requests_into_function_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    structured_output = {
        "action": "call_tools",
        "tool_calls": [{"name": "write_file", "arguments_json": '{"path": "a.md"}'}],
        "final_json": "",
    }
    transport, seen = _transport(monkeypatch, json.dumps({"structured_output": structured_output}))
    response = transport.post("u", {}, json.dumps(TURN).encode(), 60)
    output = json.loads(response.body)["output"]
    assert response.status_code == 200
    assert output[0]["type"] == "function_call" and output[0]["name"] == "write_file"
    assert json.loads(output[0]["arguments"]) == {"path": "a.md"}
    argv = seen["argv"]
    assert argv[argv.index("--tools") + 1] == ""  # type: ignore[union-attr]


def test_transport_returns_the_final_artifact_as_output_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    structured_output = {"action": "final", "tool_calls": [], "final_json": '{"ok": true}'}
    transport, _ = _transport(monkeypatch, json.dumps({"structured_output": structured_output}))
    output = json.loads(transport.post("u", {}, json.dumps(TURN).encode(), 60).body)["output"]
    assert output[0]["content"][0]["text"] == '{"ok": true}'


@pytest.mark.parametrize(
    ("document", "status"),
    [
        ({"is_error": True, "result": "API Error: 529 Overloaded"}, 503),
        ({"is_error": True, "result": "Please run /login"}, 401),
    ],
)
def test_transport_maps_cli_failures_to_http_status(
    monkeypatch: pytest.MonkeyPatch, document: dict[str, object], status: int
) -> None:
    transport, _ = _transport(monkeypatch, json.dumps(document), code=1)
    assert transport.post("u", {}, json.dumps(TURN).encode(), 60).status_code == status


def test_agent_route_failures_fall_back_but_work_failures_do_not() -> None:
    from ai_software_engineer.agents.fallback import _allows_fallback
    from ai_software_engineer.agents.models import AgentFailure, AgentResult, AgentRunStatus

    def failed(code: AgentErrorCode, transient: bool) -> AgentResult:
        return AgentResult.model_construct(
            status=AgentRunStatus.FAILED,
            error=AgentFailure(code=code, message="x", transient=transient),
        )

    assert _allows_fallback(failed(AgentErrorCode.QUOTA_EXHAUSTED, False))
    assert _allows_fallback(failed(AgentErrorCode.RATE_LIMITED, False))
    assert not _allows_fallback(failed(AgentErrorCode.AUTHENTICATION_ERROR, False))
    assert not _allows_fallback(failed(AgentErrorCode.INVALID_OUTPUT, False))
    assert not _allows_fallback(failed(AgentErrorCode.POLICY_VIOLATION, False))


def test_responses_agent_runs_platform_tools_through_the_claude_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.agents.claude_cli import (
        CLAUDE_CLI_ENDPOINT,
        ClaudeCliResponsesTransport,
    )
    from ai_software_engineer.agents.responses import ResponsesAgentAdapter
    from tests.agents.test_openai_compatible import StaticPromptBuilder
    from tests.agents.test_responses import _repository
    from tests.agents.test_responses_boundary_diagnostics import _qa

    root, base = _repository(tmp_path)
    request, definition = _qa(base)
    prompts: list[str] = []
    replies = [
        {
            "action": "call_tools",
            "tool_calls": [{"name": "read_file", "arguments_json": '{"path": "README.md"}'}],
            "final_json": "",
        },
        {"action": "final", "tool_calls": [], "final_json": "{}"},
    ]

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        prompts.append(kwargs["input"])
        reply = replies[min(len(prompts), len(replies)) - 1]
        return subprocess.CompletedProcess(argv, 0, json.dumps({"structured_output": reply}), "")

    monkeypatch.setattr("ai_software_engineer.owned_processes.run_owned_subprocess", fake_run)
    adapter = ResponsesAgentAdapter(
        workspace_root=root,
        endpoint=CLAUDE_CLI_ENDPOINT,
        api_key="claude-cli-local",
        model="claude-opus-5-5",
        agent=definition,
        prompt_builder=StaticPromptBuilder(),
        transport=ClaudeCliResponsesTransport(model="claude-opus-5-5", executable="/opt/claude"),
    )
    adapter.run(request)
    assert len(prompts) >= 2
    # The platform executed read_file and sent its result back on the next turn.
    assert "TOOL RESULT [" in prompts[1]


def test_transport_runs_a_real_tracked_process(tmp_path: Path) -> None:
    from ai_software_engineer.agents.claude_cli import ClaudeCliResponsesTransport

    fake = tmp_path / "claude"
    fake.write_text(
        "#!/bin/sh\ncat >/dev/null\n"
        'echo \'{"structured_output": {"action": "final", "tool_calls": [], '
        '"final_json": "{\\"ok\\": true}"}}\'\n'
    )
    fake.chmod(0o755)
    transport = ClaudeCliResponsesTransport(model="claude-opus-5-5", executable=str(fake))
    response = transport.post("u", {}, json.dumps(TURN).encode(), 30)
    assert response.status_code == 200
    assert json.loads(response.body)["output"][0]["content"][0]["text"] == '{"ok": true}'
