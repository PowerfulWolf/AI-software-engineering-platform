"""Real native output stays bounded before the child has finished executing."""

from __future__ import annotations

import io
import json
import os
import selectors
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import IO, cast

import pytest

from ai_software_engineer.agents import _native_output
from ai_software_engineer.agents.codex_cli import (
    CodexExecutionUnconfirmed,
    CodexInvocationResult,
    SubprocessCodexCommandRunner,
    _bounded,
)
from ai_software_engineer.owned_processes import HostOwnedProcessRegistry, OwnedProcessesUncertain


def test_running_native_output_memory_is_bounded_for_both_streams(tmp_path: Path) -> None:
    driver = r'''
import json
import sys
import tracemalloc
from contextlib import contextmanager
from pathlib import Path
from ai_software_engineer.agents.codex_cli import SubprocessCodexCommandRunner

root = Path(sys.argv[1])
ready, release = root / "ready", root / "release"
samples = []

class Guard:
    inherited_fds = ()

    def check(self):
        if ready.exists() and not release.exists():
            samples.append(tracemalloc.get_traced_memory())
            release.touch()

    @contextmanager
    def write_scope(self):
        yield

child = r"""
import os, sys, time
from pathlib import Path
root = Path(sys.argv[1])
for index in range(128):
    os.write(1, b'o' * 65536)
    os.write(2, b'e' * 65536)
os.write(1, b'failure-marker-out')
os.write(2, b'failure-marker-err')
(root / 'ready').touch()
deadline = time.monotonic() + 8
while not (root / 'release').exists() and time.monotonic() < deadline:
    time.sleep(.01)
assert (root / 'release').exists(), 'fixture release was not observed'
"""
tracemalloc.start()
result = SubprocessCodexCommandRunner(Guard()).run(
    (sys.executable, "-c", child, str(root)), cwd=root, environment={},
    stdin="", timeout_seconds=12,
)
print(json.dumps({
    "samples": samples, "returncode": result.returncode, "timed_out": result.timed_out,
    "stdout_length": len(result.stdout), "stderr_length": len(result.stderr),
    "stdout_tail": result.stdout[-18:], "stderr_tail": result.stderr[-18:],
}))
'''
    execution = subprocess.run(
        (sys.executable, "-c", driver, str(tmp_path)),
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[2] / "src")},
        capture_output=True,
        text=True,
        timeout=18,
        check=True,
    )
    facts = json.loads(execution.stdout)
    assert facts["returncode"] == 0 and not facts["timed_out"]
    assert len(facts["samples"]) == 1, "sample must be taken while the child waits for release"
    current, peak = facts["samples"][0]
    assert current < 6 * 1024 * 1024, f"running output retained {current} bytes"
    assert peak < 12 * 1024 * 1024, f"running output allocated a {peak}-byte peak"
    assert facts["stdout_length"] == facts["stderr_length"] == 1_000_000
    assert facts["stdout_tail"].endswith("failure-marker-out")
    assert facts["stderr_tail"].endswith("failure-marker-err")


@pytest.fixture
def children(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[subprocess.Popen[bytes]]]:
    spawned: list[subprocess.Popen[bytes]] = []
    popen = cast("Callable[..., subprocess.Popen[bytes]]", subprocess.Popen)

    def capture(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        child = popen(*args, **kwargs)
        spawned.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", capture)
    try:
        yield spawned
    finally:
        for child in spawned:
            if child.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=2)
            for pipe in (child.stdout, child.stderr):
                if pipe is not None:
                    with suppress(OSError):
                        pipe.close()


def _assert_closed(children: list[subprocess.Popen[bytes]]) -> None:
    assert len(children) == 1
    child = children[0]
    assert child.poll() is not None
    assert child.stdout is not None and child.stdout.closed
    assert child.stderr is not None and child.stderr.closed


@pytest.mark.parametrize("read_bytes", [1, 2, 3, 7])
def test_split_utf8_invalid_bytes_and_newlines_match_complete_text_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, read_bytes: int
) -> None:
    monkeypatch.setattr(_native_output, "_READ_BYTES", read_bytes)
    payload = b"start\r\n" + "中文😀".encode() + b"\rnext\xff\n\xe2\x82"
    expected = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8", errors="replace").read()
    result = SubprocessCodexCommandRunner().run(
        (sys.executable, "-c", f"import os; os.write(1, {payload!r}); os.write(2, {payload!r})"),
        cwd=tmp_path,
        environment={},
        stdin="",
        timeout_seconds=2,
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == expected


def test_long_unicode_output_matches_previous_complete_normalized_head_and_tail(
    tmp_path: Path,
) -> None:
    pattern = "头😀\r\n尾\r".encode() + b"\xff"
    raw = pattern * 170_000 + b"failure marker\r"
    expected = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", errors="replace").read()
    assert len(expected) > 1_000_000
    result = SubprocessCodexCommandRunner().run(
        (
            sys.executable,
            "-c",
            f"import os; raw = {pattern!r} * 170_000 + b'failure marker\\r'; "
            "os.write(1, raw); os.write(2, raw)",
        ),
        cwd=tmp_path,
        environment={},
        stdin="",
        timeout_seconds=3,
    )
    assert result.returncode == 0 and not result.timed_out
    assert result.stdout == result.stderr == _bounded(expected)
    assert result.stderr.endswith("failure marker\n")


def test_native_runner_preserves_the_explicit_inherited_task_descriptor(tmp_path: Path) -> None:
    with tempfile.TemporaryFile(mode="w+b") as lock:
        lock.write(b"owned Task descriptor")
        lock.seek(0)
        guard = _MarkerGuard(tmp_path / "absent")
        guard.inherited_fds = (lock.fileno(),)
        result = SubprocessCodexCommandRunner(guard).run(
            (
                sys.executable,
                "-c",
                f"import os; print(os.read({lock.fileno()}, 100).decode())",
            ),
            cwd=tmp_path,
            environment={},
            stdin="",
            timeout_seconds=1,
        )
        assert result.returncode == 0 and result.stdout == "owned Task descriptor\n"
        assert not lock.closed


class _MarkerGuard:
    inherited_fds: tuple[int, ...] = ()

    def __init__(self, marker: Path) -> None:
        self.marker = marker

    def check(self) -> None:
        if self.marker.exists():
            raise RuntimeError("fixture ownership was lost")

    @contextmanager
    def write_scope(self) -> Iterator[None]:
        self.check()
        yield
        self.check()


def _continuous_source() -> str:
    return (
        "import os,signal; from pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "Path('ready').touch()\n"
        "while True:\n"
        "    os.write(1, b'o' * 65536)\n"
        "    os.write(2, b'e' * 65536)\n"
    )


@pytest.mark.parametrize("lose_owner", [False, True])
def test_continuous_both_streams_cannot_starve_timeout_or_lost_owner(
    tmp_path: Path, children: list[subprocess.Popen[bytes]], lose_owner: bool
) -> None:
    registry = HostOwnedProcessRegistry()
    observed: list[CodexInvocationResult] = []
    threads = tuple(threading.enumerate())
    guard = _MarkerGuard(tmp_path / "ready") if lose_owner else None
    runner = SubprocessCodexCommandRunner(guard)
    started = time.monotonic()
    with registry.operation_scope("operation_continuous_output"):
        if lose_owner:
            with pytest.raises(RuntimeError, match="ownership"):
                runner.run_observed(
                    (sys.executable, "-c", _continuous_source()),
                    cwd=tmp_path,
                    environment={},
                    stdin="",
                    timeout_seconds=8,
                    observer=observed.append,
                )
        else:
            result = runner.run_observed(
                (sys.executable, "-c", _continuous_source()),
                cwd=tmp_path,
                environment={},
                stdin="",
                timeout_seconds=0.1,
                observer=observed.append,
            )
            assert result.timed_out
    assert (tmp_path / "ready").exists()
    assert time.monotonic() - started < 4
    assert tuple(threading.enumerate()) == threads
    assert len(observed) == 1
    assert observed[0].returncode == -signal.SIGKILL
    assert observed[0].process_stop is not None
    assert observed[0].process_stop.kind == ("failed" if lose_owner else "local_execution_limit")
    assert len(observed[0].stdout) == len(observed[0].stderr) == 1_000_000
    registry.require_stopped()
    _assert_closed(children)


@pytest.mark.parametrize("failure", ["setup", "read", "close"])
def test_output_setup_read_or_close_failure_stays_uncertain_and_releases_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    children: list[subprocess.Popen[bytes]],
    failure: str,
) -> None:
    registry = HostOwnedProcessRegistry()
    observed: list[CodexInvocationResult] = []
    threads = tuple(threading.enumerate())
    if failure == "setup":

        def broken_setup(*args: object, **kwargs: object) -> None:
            raise OSError("fixture selector initialization failed")

        monkeypatch.setattr(_native_output._NativeOutputDrain, "__init__", broken_setup)
    elif failure == "read":

        def broken_read(*args: object, **kwargs: object) -> bool:
            raise OSError("fixture pipe read failed")

        monkeypatch.setattr(_native_output._NativeOutputDrain, "poll", broken_read)
    else:
        close = _native_output._NativeOutputDrain.close

        def broken_close(drain: _native_output._NativeOutputDrain) -> None:
            close(drain)
            raise OSError("fixture selector close failed")

        monkeypatch.setattr(_native_output._NativeOutputDrain, "close", broken_close)
    with (
        registry.operation_scope("operation_failed_native_output"),
        pytest.raises(CodexExecutionUnconfirmed),
    ):
        SubprocessCodexCommandRunner().run_observed(
            (sys.executable, "-c", "print('fixture output')"),
            cwd=tmp_path,
            environment={},
            stdin="",
            timeout_seconds=1,
            observer=observed.append,
        )
    assert observed == []
    assert tuple(threading.enumerate()) == threads
    assert registry.snapshot()[0].state == "uncertain"
    with pytest.raises(OwnedProcessesUncertain):
        registry.require_stopped()
    _assert_closed(children)


def test_stop_callback_runs_after_eof_group_absence_and_local_resource_cleanup(
    tmp_path: Path, children: list[subprocess.Popen[bytes]]
) -> None:
    registry = HostOwnedProcessRegistry()
    observed: list[CodexInvocationResult] = []

    def observe(result: CodexInvocationResult) -> None:
        _assert_closed(children)
        assert result.process_stop is not None
        with pytest.raises(ProcessLookupError):
            os.killpg(result.process_stop.group_id, 0)
        assert registry.snapshot(), "stop persistence must precede clearing Host ownership"
        observed.append(result)

    with registry.operation_scope("operation_stop_order"):
        result = SubprocessCodexCommandRunner().run_observed(
            (sys.executable, "-c", "import os; os.write(1, b'out'); os.write(2, b'err')"),
            cwd=tmp_path,
            environment={},
            stdin="",
            timeout_seconds=1,
            observer=observe,
        )
    assert observed == [result]
    assert result.stdout == "out" and result.stderr == "err"
    registry.require_stopped()


def test_partial_selector_registration_failure_closes_the_owned_selector_and_pipes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    children: list[subprocess.Popen[bytes]],
) -> None:
    opened_selectors: list[selectors.BaseSelector] = []
    registrations: dict[int, int] = {}

    class BrokenSecondRegistration(selectors.DefaultSelector):
        def register(
            self, fileobj: object, events: int, data: object = None
        ) -> selectors.SelectorKey:
            if self not in opened_selectors:
                opened_selectors.append(self)
            registrations[id(self)] = registrations.get(id(self), 0) + 1
            if registrations[id(self)] == 2:
                raise OSError("fixture second pipe registration failed")
            return super().register(cast(IO[bytes], fileobj), events, data)

    monkeypatch.setattr(selectors, "DefaultSelector", BrokenSecondRegistration)
    registry = HostOwnedProcessRegistry()
    observed: list[CodexInvocationResult] = []
    with (
        registry.operation_scope("operation_partial_selector_setup"),
        pytest.raises(CodexExecutionUnconfirmed),
    ):
        SubprocessCodexCommandRunner().run_observed(
            (sys.executable, "-c", "print('fixture output')"),
            cwd=tmp_path,
            environment={},
            stdin="",
            timeout_seconds=1,
            observer=observed.append,
        )
    assert observed == []
    assert opened_selectors
    assert all(selector.get_map() is None for selector in opened_selectors)
    assert registry.snapshot()[0].state == "uncertain"
    _assert_closed(children)


def test_stop_callback_failure_is_not_republished_and_keeps_host_uncertain(
    tmp_path: Path, children: list[subprocess.Popen[bytes]]
) -> None:
    registry = HostOwnedProcessRegistry()
    observed: list[CodexInvocationResult] = []

    def reject(result: CodexInvocationResult) -> None:
        observed.append(result)
        raise RuntimeError("fixture stop record write failed")

    with (
        registry.operation_scope("operation_stop_write_failure"),
        pytest.raises(RuntimeError, match="stop record"),
    ):
        SubprocessCodexCommandRunner().run_observed(
            (sys.executable, "-c", "print('fixture output')"),
            cwd=tmp_path,
            environment={},
            stdin="",
            timeout_seconds=1,
            observer=reject,
        )
    assert len(observed) == 1
    assert registry.snapshot()[0].state == "uncertain"
    with pytest.raises(OwnedProcessesUncertain):
        registry.require_stopped()
    _assert_closed(children)


@pytest.mark.parametrize("name", ["stdout", "stderr"])
def test_either_pipe_close_failure_keeps_host_uncertain_and_closes_the_other_pipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    children: list[subprocess.Popen[bytes]],
    name: str,
) -> None:
    class BrokenClose:
        def __init__(self, pipe: IO[bytes]) -> None:
            self.pipe = pipe

        @property
        def closed(self) -> bool:
            return self.pipe.closed

        def fileno(self) -> int:
            return self.pipe.fileno()

        def close(self) -> None:
            self.pipe.close()
            raise OSError("fixture pipe close failed")

    popen = cast("Callable[..., subprocess.Popen[bytes]]", subprocess.Popen)

    def broken_pipe(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        child = popen(*args, **kwargs)
        pipe = child.stdout if name == "stdout" else child.stderr
        assert pipe is not None
        setattr(child, name, cast(IO[bytes], BrokenClose(pipe)))
        return child

    monkeypatch.setattr(subprocess, "Popen", broken_pipe)
    registry = HostOwnedProcessRegistry()
    observed: list[CodexInvocationResult] = []
    with (
        registry.operation_scope("operation_pipe_close_failure"),
        pytest.raises(CodexExecutionUnconfirmed),
    ):
        SubprocessCodexCommandRunner().run_observed(
            (sys.executable, "-c", "print('fixture output')"),
            cwd=tmp_path,
            environment={},
            stdin="",
            timeout_seconds=1,
            observer=observed.append,
        )
    assert observed == []
    assert registry.snapshot()[0].state == "uncertain"
    with pytest.raises(OwnedProcessesUncertain):
        registry.require_stopped()
    _assert_closed(children)


@pytest.mark.parametrize("held_fd", [1, 2])
def test_escaped_descendant_holding_either_pipe_never_establishes_stop(
    tmp_path: Path, children: list[subprocess.Popen[bytes]], held_fd: int
) -> None:
    pid_file = tmp_path / "escaped.pid"
    source = (
        "import subprocess,sys; from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'], "
        "start_new_session=True, "
        f"stdout={'None' if held_fd == 1 else 'subprocess.DEVNULL'}, "
        f"stderr={'None' if held_fd == 2 else 'subprocess.DEVNULL'})\n"
        "Path('escaped.pid').write_text(str(child.pid))\n"
    )
    registry = HostOwnedProcessRegistry()
    observed: list[CodexInvocationResult] = []
    threads = tuple(threading.enumerate())
    started = time.monotonic()
    try:
        with (
            registry.operation_scope("operation_single_escaped_pipe"),
            pytest.raises(CodexExecutionUnconfirmed),
        ):
            SubprocessCodexCommandRunner().run_observed(
                (sys.executable, "-c", source),
                cwd=tmp_path,
                environment={},
                stdin="",
                timeout_seconds=0.1,
                observer=observed.append,
            )
        assert time.monotonic() - started < 4
        assert tuple(threading.enumerate()) == threads
        assert observed == []
        assert registry.snapshot()[0].state == "uncertain"
        with pytest.raises(OwnedProcessesUncertain):
            registry.require_stopped()
        _assert_closed(children)
    finally:
        if pid_file.exists():
            with suppress(ProcessLookupError):
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
