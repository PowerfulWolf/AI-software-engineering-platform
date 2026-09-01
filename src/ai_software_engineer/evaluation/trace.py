"""Assemble replayable EvaluationTrace values from durable ports."""

from pydantic import ValidationError

from ai_software_engineer.artifacts import ArtifactStore
from ai_software_engineer.evaluation.metrics import EvaluationTrace
from ai_software_engineer.evaluation.models import CaseStartedEvent, EvaluationCaseId
from ai_software_engineer.evaluation.ports import EvaluationEventStore
from ai_software_engineer.store import TaskRepository


class EvaluationTraceError(RuntimeError):
    """Base class for stable trace assembly failures."""


class EvaluationTraceNotFound(EvaluationTraceError):
    """Raised when a case has no immutable CaseStartedEvent."""


class EvaluationTraceConflict(EvaluationTraceError):
    """Raised when a case identity has more than one start fact."""


class EvaluationTraceContractError(EvaluationTraceError):
    """Raised when facts across stores disagree on identity or ordering."""


class EvaluationTraceBuilder:
    """Read organization-owned stores without mutating their delivery facts."""

    def __init__(
        self,
        *,
        repository: TaskRepository,
        artifact_store: ArtifactStore,
        event_store: EvaluationEventStore,
    ) -> None:
        self._repository = repository
        self._artifact_store = artifact_store
        self._event_store = event_store

    def build(self, case_id: EvaluationCaseId) -> EvaluationTrace:
        events = self._event_store.list_for_case(case_id)
        starts = tuple(event for event in events if isinstance(event, CaseStartedEvent))
        if not starts:
            raise EvaluationTraceNotFound(case_id)
        if len(starts) != 1:
            raise EvaluationTraceConflict(f"case {case_id} has {len(starts)} start events")
        case = starts[0]
        task = self._repository.get(case.task_id)
        if case.base_revision != task.base_ref:
            raise EvaluationTraceContractError(
                f"case {case_id} base_revision differs from Task base_ref"
            )
        try:
            return EvaluationTrace(
                case=case,
                task=task,
                state_events=self._repository.list_events(task.id),
                artifacts=self._artifact_store.list_for_task(task.id),
                evaluation_events=events,
            )
        except (ValueError, ValidationError) as error:
            raise EvaluationTraceContractError(f"case {case_id} facts are inconsistent") from error


__all__ = [
    "EvaluationTraceBuilder",
    "EvaluationTraceConflict",
    "EvaluationTraceContractError",
    "EvaluationTraceError",
    "EvaluationTraceNotFound",
]
