"""Ports owned by the Evaluation and Human Boundary layer."""

from typing import Protocol

from ai_software_engineer.evaluation.models import (
    EvaluationCaseId,
    EvaluationEvent,
    EvaluationEventId,
)


class EvaluationEventStore(Protocol):
    """Append-only facts used by EvaluationTraceBuilder."""

    def append(self, event: EvaluationEvent) -> EvaluationEvent: ...

    def get(self, event_id: EvaluationEventId) -> EvaluationEvent: ...

    def find(self, event_id: EvaluationEventId) -> EvaluationEvent | None: ...

    def list_for_case(self, case_id: EvaluationCaseId) -> tuple[EvaluationEvent, ...]: ...


__all__ = ["EvaluationEventStore"]
