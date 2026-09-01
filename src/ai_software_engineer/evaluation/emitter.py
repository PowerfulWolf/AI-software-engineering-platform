"""AgentAdapter instrumentation that emits replay-safe Evaluation facts."""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from ai_software_engineer.agents import (
    AgentAdapter,
    AgentErrorCode,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.evaluation.models import (
    AgentRunEvent,
    ArtifactOutputStatus,
    EvaluationCaseId,
)
from ai_software_engineer.evaluation.ports import EvaluationEventStore

Clock = Callable[[], datetime]


class EvaluationEmissionError(RuntimeError):
    """Raised when an existing metric fact disagrees with a replayed Agent run."""


class EvaluatingAgentAdapter:
    """Decorate any AgentAdapter and persist one typed fact per returned result."""

    def __init__(
        self,
        *,
        case_id: EvaluationCaseId,
        delegate: AgentAdapter,
        event_store: EvaluationEventStore,
        clock: Clock | None = None,
    ) -> None:
        self._case_id = case_id
        self._delegate = delegate
        self._event_store = event_store
        self._clock = clock or _utc_now

    def run(self, request: AgentRequest) -> AgentResult:
        result = self._delegate.run(request)
        event_id = _event_id(self._case_id, result.run_id)
        existing = self._event_store.find(event_id)
        if existing is not None and not isinstance(existing, AgentRunEvent):
            raise EvaluationEmissionError(f"evaluation event {event_id} is not an AgentRunEvent")
        occurred_at = existing.occurred_at if existing is not None else self._clock()
        event = _event(self._case_id, request, result, event_id, occurred_at)
        try:
            persisted = self._event_store.append(event)
        except RuntimeError as error:
            raise EvaluationEmissionError(
                f"Agent run {result.run_id} conflicts with persisted evaluation facts"
            ) from error
        if persisted != event:
            raise EvaluationEmissionError(
                f"Agent run {result.run_id} replay differs from persisted evaluation facts"
            )
        return result


def _event(
    case_id: EvaluationCaseId,
    request: AgentRequest,
    result: AgentResult,
    event_id: str,
    occurred_at: datetime,
) -> AgentRunEvent:
    output_status = ArtifactOutputStatus.NOT_PRODUCED
    artifact_id = None
    if result.status is AgentRunStatus.SUCCEEDED and result.artifact is not None:
        output_status = ArtifactOutputStatus.VALID
        artifact_id = result.artifact.artifact_id
    elif result.error is not None and result.error.code is AgentErrorCode.INVALID_OUTPUT:
        output_status = ArtifactOutputStatus.INVALID
    policy_violation = int(
        result.error is not None and result.error.code is AgentErrorCode.POLICY_VIOLATION
    )
    return AgentRunEvent(
        event_id=event_id,
        case_id=case_id,
        task_id=request.task_id,
        occurred_at=occurred_at,
        run_id=request.run_id,
        role=request.role,
        attempt=request.attempt,
        output_status=output_status,
        artifact_id=artifact_id,
        policy_violations=policy_violation,
        caught_policy_violations=policy_violation,
        duration_ms=result.duration_ms,
    )


def _event_id(case_id: EvaluationCaseId, run_id: str) -> str:
    digest = hashlib.sha256(f"{case_id}\0{run_id}".encode()).hexdigest()
    return f"evalevt_{digest}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = ["EvaluatingAgentAdapter", "EvaluationEmissionError"]
