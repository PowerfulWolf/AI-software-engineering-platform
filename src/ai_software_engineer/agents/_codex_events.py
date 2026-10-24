"""Invocation-local trusted Codex JSONL observations, never transcript parsing."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from ai_software_engineer.agents.diagnostics import safe_diagnostic
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.agents.native_observation import (
    MAX_OBSERVATION_COUNT,
    NativeEventObservation,
)

_EVENT_LINE_BYTES = 65_536
_MAX_JSON_DEPTH = 32
_EVENT_COUNTS = {
    "thread.started": "thread_started",
    "turn.started": "turn_started",
    "turn.completed": "turn_completed",
    "turn.failed": "turn_failed",
    "item.started": "item_started",
    "item.completed": "item_completed",
    "error": "error",
}


@dataclass(frozen=True, slots=True)
class CodexEventClassification:
    source: Literal["delivery", "structured"]
    code: AgentErrorCode | None
    transient: bool
    timeout_provider_failure: bool = False
    main_error: bool = True


@dataclass(frozen=True, slots=True)
class CodexJsonFailure:
    event_type: Literal["error", "turn.failed"]
    ordinal: int
    event_sha256: str
    complete: bool
    classification: CodexEventClassification
    message: str | None = field(repr=False)


CodexEventClassifier = Callable[[str], CodexEventClassification]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate native event key")
        result[key] = value
    return result


def _integer(value: str) -> int:
    if len(value) > 100:
        raise ValueError("native event number exceeds bound")
    return int(value)


def _floating(value: str) -> float:
    if len(value) > 100:
        raise ValueError("native event number exceeds bound")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite native event number")
    return result


def _constant(value: str) -> object:
    raise ValueError("invalid native event constant")


def _bounded_json_depth(text: str) -> None:
    depth = 0
    quoted = escaped = False
    for character in text:
        if escaped:
            escaped = False
        elif quoted and character == "\\":
            escaped = True
        elif character == '"':
            quoted = not quoted
        elif not quoted:
            if character in "[{":
                depth += 1
                if depth > _MAX_JSON_DEPTH:
                    raise ValueError("native event nesting exceeds bound")
            elif character in "]}":
                depth -= 1


def _require_unicode(value: object) -> None:
    if isinstance(value, str):
        value.encode("utf-8", errors="strict")
    elif isinstance(value, dict):
        for key, child in value.items():
            _require_unicode(key)
            _require_unicode(child)
    elif isinstance(value, list):
        for child in value:
            _require_unicode(child)


class CodexJsonEventObserver:
    """One bounded raw line and one candidate; malformed input poisons this call."""

    def __init__(
        self,
        classify: CodexEventClassifier,
        *,
        exact_secret: str | None = None,
        secret_required: bool = False,
    ) -> None:
        self._classify = classify
        self._exact_secret = exact_secret
        self._secret_required = secret_required
        self._line = bytearray()
        self._discarding = False
        self._invalid = False
        self._finished = False
        self._ordinal = 0
        self._candidate: CodexJsonFailure | None = None
        self._counts = dict.fromkeys(
            (
                "observed_lines",
                "thread_started",
                "turn_started",
                "turn_completed",
                "turn_failed",
                "item_started",
                "item_completed",
                "error",
                "other",
                "invalid_lines",
            ),
            0,
        )
        self._counts_saturated = False
        self._partial_line = False
        self._has_partial = False

    def _count(self, name: str) -> None:
        value = self._counts[name]
        if value == MAX_OBSERVATION_COUNT:
            self._counts_saturated = True
        else:
            self._counts[name] = value + 1

    def _reject(self) -> None:
        if not self._invalid:
            self._count("invalid_lines")
        self._invalid = True
        self._candidate = None
        self._line.clear()

    def feed(self, data: bytes) -> None:
        if self._finished:
            raise ValueError("native event observation already finished")
        if data:
            self._has_partial = not data.endswith(b"\n")
        start = 0
        while start < len(data):
            end = data.find(b"\n", start)
            stop = len(data) if end < 0 else end
            if not self._invalid and not self._discarding:
                if len(self._line) + stop - start > _EVENT_LINE_BYTES:
                    self._discarding = True
                    self._reject()
                else:
                    self._line.extend(memoryview(data)[start:stop])
            if end < 0:
                break
            self._ordinal += 1
            self._count("observed_lines")
            if not self._invalid and not self._discarding:
                self._observe(bytes(self._line))
            self._line.clear()
            self._discarding = False
            start = end + 1

    def _observe(self, line: bytes) -> None:
        try:
            text = line.decode("utf-8", errors="strict")
            _bounded_json_depth(text)
            event: object = json.loads(
                text,
                object_pairs_hook=_unique_object,
                parse_int=_integer,
                parse_float=_floating,
                parse_constant=_constant,
            )
            _require_unicode(event)
        except (UnicodeError, ValueError, RecursionError, OverflowError):
            self._reject()
            return
        if not isinstance(event, dict):
            self._reject()
            return
        event_type = event.get("type")
        self._count(
            _EVENT_COUNTS.get(event_type, "other") if isinstance(event_type, str) else "other"
        )
        if event_type in ("turn.started", "turn.completed", "thread.started"):
            self._candidate = None
            return
        if event_type == "error":
            message = event.get("message")
        elif event_type == "turn.failed":
            error = event.get("error")
            message = error.get("message") if isinstance(error, dict) else None
        else:
            return
        if not isinstance(message, str) or not message.strip():
            self._reject()
            return
        # Classification consumes the complete original message exactly once.
        # Its safe display projection cannot establish or change authority.
        classification = self._classify(message)
        if not classification.main_error:
            self._candidate = None
            return
        secret = self._exact_secret
        hidden = (
            (self._secret_required and not secret)
            or (
                secret is not None
                and any(character.isspace() or not character.isprintable() for character in secret)
            )
            or (self._secret_required and "\\" in message)
        )
        cleaned = (
            None
            if hidden
            else safe_diagnostic(message, limit=_EVENT_LINE_BYTES, exact_secret=secret)
        )
        self._candidate = CodexJsonFailure(
            event_type=event_type,
            ordinal=self._ordinal,
            event_sha256=hashlib.sha256(line).hexdigest(),
            complete=True,
            classification=classification,
            message=cleaned,
        )

    def finish(self) -> None:
        if self._has_partial:
            self._partial_line = True
            self._reject()
        self._finished = True

    def result(self) -> CodexJsonFailure | None:
        if not self._finished:
            raise ValueError("native event stdout has not reached EOF")
        return None if self._invalid else self._candidate

    def observation(self) -> NativeEventObservation:
        if not self._finished:
            raise ValueError("native event stdout has not reached EOF")
        return NativeEventObservation.model_validate(
            {
                **self._counts,
                "saturated": self._counts_saturated,
                "stream_valid": not self._invalid,
                "stdout_eof": True,
                "partial_line": self._partial_line,
            }
        )
