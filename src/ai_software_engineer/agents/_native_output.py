"""Private single-call, bounded POSIX pipe capture for the owned native runner."""

from __future__ import annotations

import codecs
import io
import os
import selectors
import subprocess
import time
from dataclasses import dataclass, field
from typing import IO, cast

from ai_software_engineer.agents._codex_events import CodexJsonEventObserver, CodexJsonFailure
from ai_software_engineer.agents.native_observation import (
    MAX_OBSERVATION_COUNT,
    NativeOutputObservation,
    NativeStreamObservation,
)

_STREAM_LIMIT = 1_000_000
_READ_BYTES = 64 * 1024


@dataclass(slots=True)
class _BoundedText:
    """Retain a fixed head and rolling tail, never the discarded middle."""

    head: str = ""
    tail: str = ""
    truncated: bool = False

    def append(self, text: str) -> None:
        head_remaining = _STREAM_LIMIT // 2 - len(self.head)
        if head_remaining:
            self.head += text[:head_remaining]
            text = text[head_remaining:]
        if text:
            if len(self.tail) + len(text) > _STREAM_LIMIT - _STREAM_LIMIT // 2:
                self.truncated = True
            self.tail = (self.tail + text)[-(_STREAM_LIMIT - _STREAM_LIMIT // 2) :]

    def value(self) -> str:
        return self.head + self.tail


@dataclass(slots=True)
class _Stream:
    pipe: IO[bytes]
    decoder: io.IncrementalNewlineDecoder = field(
        default_factory=lambda: io.IncrementalNewlineDecoder(
            codecs.getincrementaldecoder("utf-8")(errors="replace"), translate=True
        )
    )
    text: _BoundedText = field(default_factory=_BoundedText)
    raw_bytes: int = 0
    saturated: bool = False
    first_byte_seconds: float | None = None
    last_byte_seconds: float | None = None
    eof: bool = False

    def observe(self, data: bytes, elapsed: float) -> None:
        if not data:
            self.eof = True
            return
        total = self.raw_bytes + len(data)
        self.saturated = self.saturated or total > MAX_OBSERVATION_COUNT
        self.raw_bytes = min(total, MAX_OBSERVATION_COUNT)
        if self.first_byte_seconds is None:
            self.first_byte_seconds = elapsed
        self.last_byte_seconds = elapsed

    def observation(self) -> NativeStreamObservation:
        return NativeStreamObservation(
            raw_bytes=self.raw_bytes,
            saturated=self.saturated,
            first_byte_seconds=self.first_byte_seconds,
            last_byte_seconds=self.last_byte_seconds,
            eof=self.eof,
        )


class _NativeOutputDrain:
    """Fairly drain both pipes within each ownership/watchdog polling window.

    No reader threads or transcript files. Only actual empty reads establish EOF;
    closing this local selector or either local pipe is never completion proof.
    """

    def __init__(
        self,
        stdout: IO[bytes],
        stderr: IO[bytes],
        *,
        codex_events: CodexJsonEventObserver | None = None,
        started_at: float | None = None,
    ) -> None:
        self._codex_events = codex_events
        self._started_at = time.monotonic() if started_at is None else started_at
        self._selector = selectors.DefaultSelector()
        try:
            self._stdout, self._stderr = _Stream(stdout), _Stream(stderr)
            self._pending = 2
            for stream in (self._stdout, self._stderr):
                os.set_blocking(stream.pipe.fileno(), False)
                self._selector.register(stream.pipe, selectors.EVENT_READ, stream)
        except BaseException:
            self._selector.close()
            raise

    def poll(self, process: subprocess.Popen[bytes], *, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            if not self._pending:
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    return False
                return True
            if not remaining:
                return False
            # One bounded read per ready stream, then check the time again. A
            # continuously ready stdout must not starve stderr or owner checks.
            for key, _events in self._selector.select(remaining):
                stream = cast(_Stream, key.data)
                try:
                    data = os.read(key.fd, _READ_BYTES)
                except BlockingIOError:
                    continue
                stream.observe(data, max(0.0, time.monotonic() - self._started_at))
                if stream is self._stdout and self._codex_events is not None:
                    if data:
                        self._codex_events.feed(data)
                    else:
                        self._codex_events.finish()
                stream.text.append(stream.decoder.decode(data, final=not data))
                if not data:
                    self._selector.unregister(stream.pipe)
                    self._pending -= 1

    def result(self) -> tuple[str, str]:
        if self._pending:
            raise OSError("native output has not reached EOF")
        return self._stdout.text.value(), self._stderr.text.value()

    def observation(self) -> NativeOutputObservation:
        if self._pending:
            raise OSError("native output has not reached EOF")
        return NativeOutputObservation(
            elapsed_seconds=max(0.0, time.monotonic() - self._started_at),
            stdout=self._stdout.observation(),
            stderr=self._stderr.observation(),
            events=self._codex_events.observation() if self._codex_events is not None else None,
        )

    @property
    def native_failure(self) -> CodexJsonFailure | None:
        if self._pending:
            raise OSError("native output has not reached EOF")
        return self._codex_events.result() if self._codex_events is not None else None

    @property
    def stderr_truncated(self) -> bool:
        return self._stderr.text.truncated

    def close(self) -> None:
        self._selector.close()
