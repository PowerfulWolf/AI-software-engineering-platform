"""Immutable in-memory and filesystem EvaluationEventStore implementations."""

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.evaluation.models import (
    EvaluationCaseId,
    EvaluationEvent,
    EvaluationEventId,
    validate_evaluation_event,
)

_EVENT_ID_ADAPTER: Final[TypeAdapter[EvaluationEventId]] = TypeAdapter(EvaluationEventId)
_CASE_ID_ADAPTER: Final[TypeAdapter[EvaluationCaseId]] = TypeAdapter(EvaluationCaseId)


class EvaluationEventStoreError(RuntimeError):
    """Base class for stable Evaluation event persistence failures."""


class EvaluationEventNotFound(EvaluationEventStoreError):
    """Raised when an Evaluation event ID is absent or invalid."""


class EvaluationEventConflict(EvaluationEventStoreError):
    """Raised when an immutable event ID is reused with changed content."""


class EvaluationEventCorruption(EvaluationEventStoreError):
    """Raised when persisted Evaluation evidence can no longer be trusted."""


class InMemoryEvaluationEventStore:
    """Process-local store for contract tests and offline composition."""

    def __init__(self) -> None:
        self._events: dict[EvaluationEventId, EvaluationEvent] = {}

    def append(self, event: EvaluationEvent) -> EvaluationEvent:
        existing = self._events.get(event.event_id)
        if existing is not None:
            if existing == event:
                return existing
            raise EvaluationEventConflict(event.event_id)
        self._events[event.event_id] = event
        return event

    def get(self, event_id: EvaluationEventId) -> EvaluationEvent:
        try:
            return self._events[event_id]
        except KeyError as error:
            raise EvaluationEventNotFound(event_id) from error

    def find(self, event_id: EvaluationEventId) -> EvaluationEvent | None:
        return self._events.get(event_id)

    def list_for_case(self, case_id: EvaluationCaseId) -> tuple[EvaluationEvent, ...]:
        events = (event for event in self._events.values() if event.case_id == case_id)
        return tuple(sorted(events, key=_event_order))


class FileEvaluationEventStore:
    """Persist one canonical JSON file per append-only Evaluation event."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise EvaluationEventStoreError(
                f"cannot initialize EvaluationEventStore at {self._root}"
            ) from error

    def append(self, event: EvaluationEvent) -> EvaluationEvent:
        target = self._path(event.event_id)
        if target.exists():
            existing = self.get(event.event_id)
            if existing == event:
                return existing
            raise EvaluationEventConflict(event.event_id)
        event_payload = event.to_wire()
        record: WirePayload = {
            "event": event_payload,
            "sha256": _digest(event_payload),
        }
        _atomic_write(target, _canonical_json(record))
        return self.get(event.event_id)

    def get(self, event_id: EvaluationEventId) -> EvaluationEvent:
        target = self._path(event_id)
        if not target.is_file():
            raise EvaluationEventNotFound(event_id)
        try:
            payload: object = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise EvaluationEventCorruption(
                    f"Evaluation event record {event_id} is not an object"
                )
            event_payload = payload.get("event")
            digest = payload.get("sha256")
            if not isinstance(event_payload, dict) or not isinstance(digest, str):
                raise EvaluationEventCorruption(f"Evaluation event record {event_id} is incomplete")
            if digest != _digest(event_payload):
                raise EvaluationEventCorruption(f"Evaluation event digest mismatch for {event_id}")
            event = validate_evaluation_event(event_payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
            raise EvaluationEventCorruption(f"cannot decode Evaluation event {event_id}") from error
        if event.event_id != event_id:
            raise EvaluationEventCorruption(f"Evaluation event ID mismatch for {event_id}")
        return event

    def find(self, event_id: EvaluationEventId) -> EvaluationEvent | None:
        try:
            return self.get(event_id)
        except EvaluationEventNotFound:
            return None

    def list_for_case(self, case_id: EvaluationCaseId) -> tuple[EvaluationEvent, ...]:
        try:
            validated_case_id = _CASE_ID_ADAPTER.validate_python(case_id)
            paths = sorted(self._root.glob("evalevt_*.json"))
        except ValidationError as error:
            raise EvaluationEventNotFound(case_id) from error
        except OSError as error:
            raise EvaluationEventStoreError(
                f"cannot list Evaluation events for {case_id}"
            ) from error
        events = tuple(self.get(path.stem) for path in paths)
        return tuple(
            sorted(
                (event for event in events if event.case_id == validated_case_id),
                key=_event_order,
            )
        )

    def _path(self, event_id: EvaluationEventId) -> Path:
        try:
            validated_id = _EVENT_ID_ADAPTER.validate_python(event_id)
        except ValidationError as error:
            raise EvaluationEventNotFound(event_id) from error
        return self._root / f"{validated_id}.json"


def _event_order(event: EvaluationEvent) -> tuple[object, str]:
    return event.occurred_at, event.event_id


def _canonical_json(payload: WirePayload) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(payload: WirePayload) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _atomic_write(target: Path, content: str) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
    except OSError as error:
        raise EvaluationEventStoreError(f"failed to atomically write {target.name}") from error
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
