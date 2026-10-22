"""Original native JSON events survive bounded output and remain invocation-local."""

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    CodexCliAgentAdapter,
    CodexCliStructuredModelClient,
    StructuredModelError,
)
from ai_software_engineer.agents.codex_cli import (
    CodexInvocationResult,
    SubprocessCodexCommandRunner,
    _classify_cli_failure,
)
from tests.agents.test_codex_cli import _repository
from tests.agents.test_openai_compatible import StaticPromptBuilder, _coder_request


class _ArgsRunner:
    argv: tuple[str, ...] = ()

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
    ) -> CodexInvocationResult:
        self.argv = argv
        return CodexInvocationResult(returncode=1, stderr="Error: fixture")


def test_delivery_explicitly_requests_json(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    runner = _ArgsRunner()
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=runner,
    )
    adapter.run(_coder_request().model_copy(update={"source_revision": base}))
    assert "--json" in runner.argv


def _executable(tmp_path: Path, source: str) -> Path:
    executable = tmp_path / "native-fixture"
    executable.write_text(f"#!{sys.executable}\n" + source)
    executable.chmod(0o700)
    return executable


def test_real_delivery_keeps_main_json_event_from_discarded_middle(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    executable = _executable(
        tmp_path,
        r"""
import json, os, sys
noise=(json.dumps({'type':'item.completed','item':{'text':'x'*10000}})+'\n').encode()
for _ in range(80):
    os.write(1, noise)
    os.write(2, b'background '+b'x'*10000+b'\n')
message = {'type':'turn.failed','error':{'message':'HTTP 429 quota window fixture'}}
os.write(1, (json.dumps(message)+'\n').encode())
for _ in range(80):
    os.write(1, noise)
    os.write(2, b'background '+b'x'*10000+b'\n')
sys.exit(1)
""",
    )
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        executable=str(executable),
    )
    result = adapter.run(_coder_request().model_copy(update={"source_revision": base}))
    assert result.error is not None
    assert result.error.code is AgentErrorCode.RATE_LIMITED and result.error.transient
    assert json.loads(result.error.message.split("; main_error=", 1)[1]) == (
        "HTTP 429 quota window fixture"
    )


def test_raw_json_requires_explicit_protocol_and_runner_resets_per_invocation(
    tmp_path: Path,
) -> None:
    raw = '{"type":"error","message":"HTTP 429 fixture"}\n'
    source = f"import os,sys; os.write(1,{raw.encode()!r}); sys.exit(1)"
    argv = (sys.executable, "-c", source)
    default = SubprocessCodexCommandRunner().run(
        argv, cwd=tmp_path, environment={}, stdin="", timeout_seconds=2
    )
    assert default.native_failure is None
    runner = SubprocessCodexCommandRunner(output_protocol="codex_json")
    first = runner.run(argv, cwd=tmp_path, environment={}, stdin="", timeout_seconds=2)
    second = runner.run(
        (sys.executable, "-c", "raise SystemExit(1)"),
        cwd=tmp_path,
        environment={},
        stdin="",
        timeout_seconds=2,
    )
    third = runner.run(argv, cwd=tmp_path, environment={}, stdin="", timeout_seconds=2)
    assert first.native_failure is not None and third.native_failure == first.native_failure
    assert second.native_failure is None
    assert first.process_stop is not None and third.process_stop is not None
    assert first.process_stop.process_id != third.process_stop.process_id


def test_observer_sees_same_invocation_after_actual_eof_and_owned_stop(tmp_path: Path) -> None:
    raw = b'{"type":"error","message":"HTTP 429 fixture"}\n'
    observed: list[CodexInvocationResult] = []

    def stopped(result: CodexInvocationResult) -> None:
        assert result.process_stop is not None
        assert result.native_failure is not None
        assert result.native_failure.ordinal == 1
        assert result.stdout == raw.decode()
        with pytest.raises(ProcessLookupError):
            os.killpg(result.process_stop.group_id, 0)
        observed.append(result)

    result = SubprocessCodexCommandRunner(output_protocol="codex_json").run_observed(
        (sys.executable, "-c", f"import os,sys; os.write(1,{raw!r}); sys.exit(1)"),
        cwd=tmp_path,
        environment={},
        stdin="",
        timeout_seconds=2,
        observer=stopped,
    )
    assert len(observed) == 1 and observed[0] is result
    assert _classify_cli_failure(result) == (AgentErrorCode.RATE_LIMITED, True)


@pytest.mark.parametrize("timed_out", [False, True])
@pytest.mark.parametrize(
    "message,expected",
    [
        ("unexpected status 401", AgentErrorCode.AUTHENTICATION_ERROR),
        ("unexpected status 429", AgentErrorCode.RATE_LIMITED),
        ("unexpected status 503", AgentErrorCode.PROVIDER_UNAVAILABLE),
        ("unexpected status 504", AgentErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_real_structured_caller_preserves_failure_and_watchdog_classification(
    tmp_path: Path,
    timed_out: bool,
    message: str,
    expected: AgentErrorCode,
) -> None:
    raw = json.dumps({"type": "turn.failed", "error": {"message": message}}) + "\n"
    executable = _executable(
        tmp_path,
        f"import os,sys,time\nos.write(1,{raw.encode()!r})\n"
        + ("time.sleep(10)\n" if timed_out else "sys.exit(1)\n"),
    )
    client = CodexCliStructuredModelClient(
        repository_root=tmp_path,
        model="fixture",
        executable=str(executable),
    )
    with pytest.raises(StructuredModelError) as raised:
        client.complete(instructions="Act", input_payload={}, output_schema={}, timeout_seconds=1)
    assert raised.value.code is expected
    assert raised.value.retryable is (expected is not AgentErrorCode.AUTHENTICATION_ERROR)
    assert raised.value.timeout_kind is None


def test_real_structured_unknown_timeout_stays_local_limit(tmp_path: Path) -> None:
    raw = b'{"type":"error","message":"unknown native failure"}\n'
    executable = _executable(
        tmp_path,
        f"import os,time\nos.write(1,{raw!r})\ntime.sleep(10)\n",
    )
    client = CodexCliStructuredModelClient(
        repository_root=tmp_path,
        model="fixture",
        executable=str(executable),
    )
    with pytest.raises(StructuredModelError) as raised:
        client.complete(instructions="Act", input_payload={}, output_schema={}, timeout_seconds=1)
    assert raised.value.code is AgentErrorCode.TIMEOUT
    assert raised.value.timeout_kind == "local_execution_limit" and not raised.value.retryable


@pytest.mark.parametrize("timed_out", [False, True])
def test_real_structured_component_error_cannot_supply_provider_auth(
    tmp_path: Path,
    timed_out: bool,
) -> None:
    raw = b'{"type":"error","message":"MCP server authentication 401 HTTP 429"}\n'
    executable = _executable(
        tmp_path,
        f"import os,sys,time\nos.write(1,{raw!r})\n"
        + ("time.sleep(10)\n" if timed_out else "sys.exit(1)\n"),
    )
    client = CodexCliStructuredModelClient(
        repository_root=tmp_path,
        model="fixture",
        executable=str(executable),
    )
    with pytest.raises(StructuredModelError) as raised:
        client.complete(instructions="Act", input_payload={}, output_schema={}, timeout_seconds=1)
    if timed_out:
        assert raised.value.code is AgentErrorCode.TIMEOUT
        assert raised.value.timeout_kind == "local_execution_limit"
        assert not raised.value.retryable
    else:
        assert raised.value.code is AgentErrorCode.PROVIDER_UNAVAILABLE
        assert raised.value.retryable


@pytest.mark.parametrize("ending", ["success", "signal", "timeout"])
def test_real_native_event_cannot_override_higher_priority_process_outcome(
    tmp_path: Path,
    ending: str,
) -> None:
    raw = '{"type":"error","message":"错误 HTTP 401 Unauthorized"}\n'.encode()
    finish = {
        "success": "sys.exit(0)",
        "signal": "os.kill(os.getpid(),signal.SIGTERM)",
        "timeout": "time.sleep(10)",
    }[ending]
    source = (
        "import os,sys,time,signal\n"
        f"data={raw!r}\nfor byte in data: os.write(1,bytes((byte,)))\n" + finish
    )
    result = SubprocessCodexCommandRunner(output_protocol="codex_json").run(
        (sys.executable, "-c", source),
        cwd=tmp_path,
        environment={},
        stdin="",
        timeout_seconds=1,
    )
    assert result.process_stop is not None
    if ending == "success":
        assert result.returncode == 0 and not result.timed_out
    elif ending == "signal":
        assert result.returncode < 0 and not result.timed_out
        assert _classify_cli_failure(result) == (AgentErrorCode.PROVIDER_ERROR, False)
    else:
        assert result.timed_out and result.process_stop.kind == "local_execution_limit"


@pytest.mark.parametrize("timed_out", [False, True])
def test_real_structured_component_event_preserves_real_stderr_provider_failure(
    tmp_path: Path,
    timed_out: bool,
) -> None:
    raw = b'{"type":"error","message":"MCP server authentication 401 HTTP 429"}\n'
    stderr = (
        b"Error: HTTP 504 Service failure\n" if timed_out else b"Error: HTTP 401 Unauthorized\n"
    )
    executable = _executable(
        tmp_path,
        f"import os,sys,time\nos.write(1,{raw!r})\nos.write(2,{stderr!r})\n"
        + ("time.sleep(10)\n" if timed_out else "sys.exit(1)\n"),
    )
    client = CodexCliStructuredModelClient(
        repository_root=tmp_path,
        model="fixture",
        executable=str(executable),
    )
    with pytest.raises(StructuredModelError) as raised:
        client.complete(instructions="Act", input_payload={}, output_schema={}, timeout_seconds=1)
    if timed_out:
        assert raised.value.code is AgentErrorCode.PROVIDER_UNAVAILABLE
        assert raised.value.timeout_kind is None and raised.value.retryable
    else:
        assert raised.value.code is AgentErrorCode.AUTHENTICATION_ERROR
        assert not raised.value.retryable
