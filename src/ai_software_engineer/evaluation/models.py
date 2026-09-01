"""Typed, immutable facts used to recompute v0.1 delivery evaluations."""

from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import (
    AwareDatetime,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

from ai_software_engineer.agents import RunId
from ai_software_engineer.domain.artifact import ArtifactId
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import TaskId

EvaluationCaseId = Annotated[str, StringConstraints(pattern=r"^case_[a-z0-9][a-z0-9_-]{2,63}$")]
EvaluationEventId = Annotated[str, StringConstraints(pattern=r"^evalevt_[a-z0-9][a-z0-9_-]{2,63}$")]


class EvaluationEventKind(StrEnum):
    CASE_STARTED = "case_started"
    AGENT_RUN = "agent_run"
    HUMAN_ACTION = "human_action"
    REGRESSION_CHECK = "regression_check"


class ArtifactOutputStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    NOT_PRODUCED = "NOT_PRODUCED"


class HumanAction(StrEnum):
    START_TASK = "START_TASK"
    VIEW_HANDOFF = "VIEW_HANDOFF"
    MERGE_DELIVERY = "MERGE_DELIVERY"
    CLARIFY_REQUIREMENTS = "CLARIFY_REQUIREMENTS"
    MODIFY_CODE = "MODIFY_CODE"
    MODIFY_TESTS = "MODIFY_TESTS"
    REWRITE_VERDICT = "REWRITE_VERDICT"
    SUPPLY_EVIDENCE = "SUPPLY_EVIDENCE"
    OVERRIDE_POLICY = "OVERRIDE_POLICY"


class RegressionStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class EvaluationEventEnvelope(DomainModel):
    """Identity shared by every append-only evaluation fact."""

    event_id: EvaluationEventId
    case_id: EvaluationCaseId
    task_id: TaskId
    kind: EvaluationEventKind
    occurred_at: AwareDatetime


class CaseStartedEvent(EvaluationEventEnvelope):
    """Freeze the model, prompt, spec, base, and test entrypoints of one case."""

    kind: Literal[EvaluationEventKind.CASE_STARTED] = EvaluationEventKind.CASE_STARTED
    base_revision: NonEmptyStr
    model_id: NonEmptyStr
    prompt_version: NonEmptyStr
    spec_version: NonEmptyStr
    test_entrypoints: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    included: StrictBool = True

    @model_validator(mode="after")
    def validate_entrypoints(self) -> Self:
        ensure_unique(self.test_entrypoints, "evaluation test_entrypoints")
        return self


class AgentRunEvent(EvaluationEventEnvelope):
    """Record run validity and policy outcomes without storing provider payloads."""

    kind: Literal[EvaluationEventKind.AGENT_RUN] = EvaluationEventKind.AGENT_RUN
    run_id: RunId
    role: AgentRole
    attempt: Annotated[StrictInt, Field(ge=1, le=10)]
    output_status: ArtifactOutputStatus
    artifact_id: ArtifactId | None = None
    policy_violations: Annotated[StrictInt, Field(ge=0)] = 0
    caught_policy_violations: Annotated[StrictInt, Field(ge=0)] = 0
    duration_ms: Annotated[StrictInt, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def validate_run_outcome(self) -> Self:
        if self.caught_policy_violations > self.policy_violations:
            raise ValueError("caught_policy_violations cannot exceed policy_violations")
        if self.output_status is ArtifactOutputStatus.VALID and self.artifact_id is None:
            raise ValueError("VALID Agent run requires artifact_id")
        if self.output_status is not ArtifactOutputStatus.VALID and self.artifact_id is not None:
            raise ValueError("only VALID Agent runs may reference artifact_id")
        return self


class HumanActionEvent(EvaluationEventEnvelope):
    """Record human boundary activity explicitly instead of inferring autonomy."""

    kind: Literal[EvaluationEventKind.HUMAN_ACTION] = EvaluationEventKind.HUMAN_ACTION
    action: HumanAction
    evidence_uri: NonEmptyStr
    note: NonEmptyStr | None = None


class RegressionCheckEvent(EvaluationEventEnvelope):
    """Close an observation window with inspectable regression evidence."""

    kind: Literal[EvaluationEventKind.REGRESSION_CHECK] = EvaluationEventKind.REGRESSION_CHECK
    status: RegressionStatus
    window_started_at: AwareDatetime
    window_ended_at: AwareDatetime
    evidence_uri: NonEmptyStr
    hidden_tests: StrictBool = False

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.window_ended_at < self.window_started_at:
            raise ValueError("regression window cannot end before it starts")
        if self.occurred_at < self.window_ended_at:
            raise ValueError("regression event cannot occur before its observation window ends")
        return self


EvaluationEvent = Annotated[
    CaseStartedEvent | AgentRunEvent | HumanActionEvent | RegressionCheckEvent,
    Field(discriminator="kind"),
]
_EVALUATION_EVENT_ADAPTER: Final[TypeAdapter[EvaluationEvent]] = TypeAdapter(EvaluationEvent)


def validate_evaluation_event(payload: object) -> EvaluationEvent:
    """Validate an untrusted wire payload as one known evaluation event subtype."""
    return _EVALUATION_EVENT_ADAPTER.validate_python(payload)


__all__ = [
    "AgentRunEvent",
    "ArtifactOutputStatus",
    "CaseStartedEvent",
    "EvaluationCaseId",
    "EvaluationEvent",
    "EvaluationEventEnvelope",
    "EvaluationEventId",
    "EvaluationEventKind",
    "HumanAction",
    "HumanActionEvent",
    "RegressionCheckEvent",
    "RegressionStatus",
    "validate_evaluation_event",
]
