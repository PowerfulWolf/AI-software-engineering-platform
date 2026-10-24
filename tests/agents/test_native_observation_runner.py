"""Native EOF statistics and optional publication cannot alter execution outcomes."""

import fcntl
import os
import sys
from collections.abc import Callable, Iterator, Mapping
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.agents.codex_cli import (
    CodexCliAgentAdapter,
    CodexInvocationResult,
    SubprocessCodexCommandRunner,
)
from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.orchestration.continuation_models import ContinuationRejected
from tests.agents.test_openai_compatible import StaticPromptBuilder
from tests.orchestration.test_native_continuation import NOW, Fixture, Guard
from tests.orchestration.test_native_observation_store import output_observation


@pytest.fixture
def native_fixture(tmp_path: Path) -> Iterator[Fixture]:
    descriptor = os.open(tmp_path / "original.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    fixture = Fixture(tmp_path, Guard(descriptor))
    try:
        yield fixture
    finally:
        fixture.repository.close()
        os.close(descriptor)


def test_real_timeout_keeps_fixed_original_stream_statistics(tmp_path: Path) -> None:
    raw = b'{"type":"thread.started"}\n{"type":"turn.started"}\n'
    script = "import os,time; os.write(1," + repr(raw) + "); os.write(2,b'secret'); time.sleep(10)"
    observed: list[CodexInvocationResult] = []
    result = SubprocessCodexCommandRunner(output_protocol="codex_json").run_observed(
        (sys.executable, "-c", script),
        cwd=tmp_path,
        environment={},
        stdin="",
        timeout_seconds=0.2,
        observer=observed.append,
    )
    assert result.timed_out and result.process_stop is not None
    assert result.process_stop.kind == "local_execution_limit"
    assert observed == [result]
    stats = result.output_observation
    assert stats is not None and stats.stdout.raw_bytes == len(raw) and stats.stderr.raw_bytes == 6
    assert stats.elapsed_seconds >= 0.2
    assert (
        stats.events is not None and stats.events.thread_started == stats.events.turn_started == 1
    )
    assert stats.events.stream_valid and stats.stdout.eof and stats.stderr.eof
    assert "secret" not in stats.model_dump_json()


def test_unselected_event_protocol_has_no_inferred_event_counts(tmp_path: Path) -> None:
    result = SubprocessCodexCommandRunner().run(
        (sys.executable, "-c", 'print(\'{"type":"turn.started"}\')'),
        cwd=tmp_path,
        environment={},
        stdin="",
        timeout_seconds=2,
    )
    assert result.output_observation is not None
    assert result.output_observation.events is None
    assert result.output_observation.stdout.raw_bytes > 0


class _FixtureRunner(SubprocessCodexCommandRunner):
    def __init__(self, stop: NativeProcessStop, before_publish: Callable[[], None]) -> None:
        super().__init__()
        self._stop = stop
        self._before_publish = before_publish

    def run_observed(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
        observer: Callable[[CodexInvocationResult], None],
    ) -> CodexInvocationResult:
        (cwd / "src/app.py").write_text("VALUE = 3\n")
        self._before_publish()
        result = CodexInvocationResult(
            -15,
            timed_out=True,
            process_stop=self._stop,
            output_observation=output_observation(),
        )
        observer(result)
        return result


@pytest.mark.parametrize("failure", ["none", "observation", "mandatory_stop"])
def test_optional_observation_failure_preserves_stop_and_original_interruption(
    native_fixture: Fixture,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    fixture = native_fixture
    control = fixture.service()
    stop = NativeProcessStop.create(
        **fixture.stopped().model_dump(exclude={"stopped_at", "stop_sha256"}),
        stopped_at=NOW + timedelta(seconds=1),
    )
    calls: list[str] = []
    real_stop = control.record_native_stop
    real_observation = control.record_native_observation

    def mandatory(*args: object, **kwargs: object) -> None:
        calls.append("stop")
        if failure == "mandatory_stop":
            raise ContinuationRejected("mandatory fixture refusal")
        real_stop(*args, **kwargs)  # type: ignore[arg-type]

    def diagnostic(*args: object, **kwargs: object) -> None:
        calls.append("observation")
        assert fixture.store.capture_stop(fixture.request.run_id).process_stop == stop
        if failure == "observation":
            raise OSError("SYNTHETIC-SECRET-EXCEPTION")
        real_observation(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(control, "record_native_stop", mandatory)
    monkeypatch.setattr(control, "record_native_observation", diagnostic)
    result = CodexCliAgentAdapter(
        workspace_root=fixture.worktree.path,
        model="fixture-model",
        agent_id="agent_native_coder",
        agent_version="v1",
        prompt_builder=StaticPromptBuilder(),
        environment={"PATH": os.environ["PATH"]},
        runner=_FixtureRunner(
            stop,
            lambda: monkeypatch.setattr(
                control,
                "_clock",
                lambda: NOW + timedelta(seconds=2),
            ),
        ),
        execution_guard=fixture.guard,
        interruption_control=control,
    ).run(fixture.request)
    assert result.error is not None and result.error.code is AgentErrorCode.WORK_INTERRUPTED
    assert "SYNTHETIC-SECRET" not in result.error.message
    if failure == "mandatory_stop":
        assert calls == ["stop"]
        assert (
            fixture.store.native_observation(fixture.request.run_id).availability == "UNAVAILABLE"
        )
        assert fixture.store.receipts_for_task(fixture.task.id) == ()
    else:
        assert calls == ["stop", "observation"]
        read = fixture.store.native_observation(fixture.request.run_id)
        assert read.availability == ("UNAVAILABLE" if failure == "observation" else "AVAILABLE")
        assert ("UNAVAILABLE" in result.error.message) is (failure == "observation")
        assert fixture.store.capture_stop(fixture.request.run_id).process_stop == stop
