"""Body-free native observations are original-stream diagnostics, never authority."""

from __future__ import annotations

import json
import os
import subprocess
import time
from contextlib import ExitStack
from typing import cast

import pytest

from ai_software_engineer.agents._codex_events import (
    CodexEventClassification,
    CodexJsonEventObserver,
)
from ai_software_engineer.agents._native_output import _NativeOutputDrain
from ai_software_engineer.agents.native_observation import (
    MAX_OBSERVATION_COUNT,
    NativeOutputObservation,
)
from ai_software_engineer.domain.model import JsonValue
from tests.orchestration.test_native_observation_store import output_observation


def classifier(_message: str) -> CodexEventClassification:
    return CodexEventClassification(source="delivery", code=None, transient=False)


def test_original_jsonl_observation_has_fixed_counts_without_payloads() -> None:
    observer = CodexJsonEventObserver(classifier)
    secret = "SYNTHETIC-OBSERVATION-SECRET"
    raw = (
        b'{"type":"thread.started"}\n'
        b'{"type":"turn.started"}\n'
        + json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": secret,
                    "nested": {"type": "turn.completed"},
                    "url": "https://invalid.test/private",
                },
            }
        ).encode()
        + b"\n"
        b'{"type":"future-event-name-that-must-not-survive"}\n'
    )
    for offset in range(0, len(raw), 3):
        observer.feed(raw[offset : offset + 3])
    observer.finish()
    stats = observer.observation()
    assert stats.stream_valid and stats.stdout_eof and not stats.partial_line
    assert stats.thread_started == stats.turn_started == stats.item_completed == 1
    assert stats.turn_completed == 0 and stats.other == 1 and stats.observed_lines == 4
    wire = stats.model_dump_json() + repr(stats)
    assert secret not in wire and "https://" not in wire
    assert "future-event-name" not in wire and "command_execution" not in wire


@pytest.mark.parametrize(
    "bad",
    [
        b'{"type":"turn.started","type":"turn.completed"}\n',
        b'{"type":"turn.started","body":{"x":1,"x":2}}\n',
        b'{"type":"turn.started","body":"\xff"}\n',
        b'{"type":"turn.started"}',
        b'{"type":"turn.started","body":"' + b"x" * 65_536 + b'"}\n',
    ],
    ids=["duplicate-root", "duplicate-nested", "invalid-utf8", "partial", "overlong"],
)
def test_poisoned_event_observation_never_restores_complete_trust(bad: bytes) -> None:
    observer = CodexJsonEventObserver(classifier)
    observer.feed(b'{"type":"thread.started"}\n')
    observer.feed(bad)
    observer.feed(b'{"type":"turn.completed"}\n')
    observer.finish()
    stats = observer.observation()
    assert not stats.stream_valid
    assert stats.thread_started == 1
    assert observer.result() is None
    assert stats.stdout_eof


class _Finished:
    def wait(self, *, timeout: float) -> int:
        return 0


def test_real_pipe_bytes_eof_and_split_unicode_are_observed_without_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_software_engineer.agents import _native_output

    monkeypatch.setattr(_native_output, "_READ_BYTES", 3)
    raw = b'{"type":"turn.started","text":"' + "中文😀".encode() + b'"}\n'
    err = b"SYNTHETIC-SECRET\xff\r\n"
    with ExitStack() as stack:
        out_r, out_w = os.pipe()
        err_r, err_w = os.pipe()
        stdout = stack.enter_context(os.fdopen(out_r, "rb"))
        stderr = stack.enter_context(os.fdopen(err_r, "rb"))
        os.write(out_w, raw)
        os.close(out_w)
        os.write(err_w, err)
        os.close(err_w)
        observer = CodexJsonEventObserver(classifier)
        drain = _NativeOutputDrain(stdout, stderr, codex_events=observer)
        stack.callback(drain.close)
        assert drain.poll(cast("subprocess.Popen[bytes]", _Finished()), timeout=1)
        stats = drain.observation()
        assert stats.stdout.raw_bytes == len(raw) and stats.stderr.raw_bytes == len(err)
        assert stats.stdout.eof and stats.stderr.eof
        assert stats.stdout.first_byte_seconds is not None
        assert stats.stdout.last_byte_seconds is not None
        assert stats.stdout.first_byte_seconds <= stats.stdout.last_byte_seconds
        assert stats.events is not None and stats.events.turn_started == 1
        assert "SYNTHETIC-SECRET" not in stats.model_dump_json()


def test_observation_requires_real_pipe_eof() -> None:
    with ExitStack() as stack:
        out_r, out_w = os.pipe()
        err_r, err_w = os.pipe()
        stack.callback(os.close, out_w)
        stack.callback(os.close, err_w)
        stdout = stack.enter_context(os.fdopen(out_r, "rb"))
        stderr = stack.enter_context(os.fdopen(err_r, "rb"))
        drain = _NativeOutputDrain(stdout, stderr)
        stack.callback(drain.close)
        with pytest.raises(OSError, match="EOF"):
            drain.observation()


def test_both_pipes_and_elapsed_use_the_original_runner_epoch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time, "monotonic", lambda: 100.0)
    with ExitStack() as stack:
        out_r, out_w = os.pipe()
        err_r, err_w = os.pipe()
        stdout = stack.enter_context(os.fdopen(out_r, "rb"))
        stderr = stack.enter_context(os.fdopen(err_r, "rb"))
        os.write(out_w, b"out")
        os.close(out_w)
        os.write(err_w, b"err")
        os.close(err_w)
        drain = _NativeOutputDrain(stdout, stderr, started_at=90.0)
        stack.callback(drain.close)
        assert drain.poll(cast("subprocess.Popen[bytes]", _Finished()), timeout=1)
        stats = drain.observation()
        assert stats.elapsed_seconds == 10.0
        for stream in (stats.stdout, stats.stderr):
            assert stream.first_byte_seconds == stream.last_byte_seconds == 10.0


@pytest.mark.parametrize("poison_first", [False, True])
def test_genuine_unterminated_final_line_stays_explicit_after_poison(poison_first: bool) -> None:
    observer = CodexJsonEventObserver(classifier)
    if poison_first:
        observer.feed(b"malformed\n")
    observer.feed(b'{"type":"turn.started"}')
    observer.finish()
    stats = observer.observation()
    assert stats.partial_line and not stats.stream_valid and stats.stdout_eof
    assert stats.invalid_lines == 1 and stats.turn_started == 0
    assert stats.observed_lines == int(poison_first)


def test_saturation_keeps_fixed_bounds_and_explicit_overflow() -> None:
    from ai_software_engineer.agents._native_output import _Stream

    with open(os.devnull, "rb") as pipe:
        stream = _Stream(
            pipe,
            raw_bytes=MAX_OBSERVATION_COUNT - 1,
            first_byte_seconds=0.0,
            last_byte_seconds=0.0,
        )
        stream.observe(b"xx", 1.0)
        stream.observe(b"", 2.0)
        assert stream.observation().raw_bytes == MAX_OBSERVATION_COUNT
        assert stream.observation().saturated
    observer = CodexJsonEventObserver(classifier)
    observer._counts["observed_lines"] = MAX_OBSERVATION_COUNT
    observer.feed(b'{"type":"turn.started"}\n')
    observer.finish()
    stats = observer.observation()
    assert stats.saturated and stats.observed_lines == MAX_OBSERVATION_COUNT
    assert stats.turn_started == 1


@pytest.mark.parametrize(
    "change",
    [
        {"raw_bytes": 0},
        {"first_byte_seconds": None},
        {"last_byte_seconds": 0.01},
        {"last_byte_seconds": 3.0},
        {"last_byte_seconds": float("nan")},
        {"raw_bytes": MAX_OBSERVATION_COUNT + 1},
        {"saturated": True},
        {"eof": False},
    ],
)
def test_impossible_stream_facts_are_rejected(change: dict[str, JsonValue]) -> None:
    wire = output_observation().to_wire()
    stdout = wire["stdout"]
    assert isinstance(stdout, dict)
    stdout.update(change)
    with pytest.raises(ValueError):
        NativeOutputObservation.model_validate(wire)
