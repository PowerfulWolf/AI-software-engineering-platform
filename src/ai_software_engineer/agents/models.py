"""Typed request, result, and scenario values for Agent Execution Plane."""

from enum import StrEnum
from typing import Annotated, Final, Self

from pydantic import Field, StrictBool, StrictInt, StringConstraints, model_validator

from ai_software_engineer.context.models import ContextId
from ai_software_engineer.domain.agent import ROLE_OUTPUT, AgentPermissions, TimeoutSeconds
from ai_software_engineer.domain.artifact import Artifact, ArtifactId
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import TaskId

RunId = Annotated[str, StringConstraints(pattern=r"^run_[a-z0-9][a-z0-9_-]{2,63}$")]
AgentAttempt = Annotated[StrictInt, Field(ge=1, le=10)]
DurationMs = Annotated[StrictInt, Field(ge=0)]
ROLE_OUTPUT_SCHEMA: Final[dict[AgentRole, str]] = {
    AgentRole.ORCHESTRATOR: "schemas/plan.schema.json",
    AgentRole.CODER: "schemas/implementation-report.schema.json",
    AgentRole.QA: "schemas/qa-report.schema.json",
    AgentRole.REVIEWER: "schemas/review-report.schema.json",
}


class AgentRunStatus(StrEnum):
    """Terminal status of one isolated Agent Run."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class AgentErrorCode(StrEnum):
    """Stable failure categories consumed by Orchestrator retry routing."""

    TIMEOUT = "TIMEOUT"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    POLICY_VIOLATION = "POLICY_VIOLATION"


class FakeBehavior(StrEnum):
    """Scriptable outcomes supported by the offline FakeAgentAdapter."""

    SUCCESS = "success"
    QA_FAIL = "qa_fail"
    REVIEW_REJECT = "review_reject"
    TIMEOUT = "timeout"
    INVALID_OUTPUT = "invalid_output"
    PROVIDER_ERROR = "provider_error"


class AgentFailure(DomainModel):
    """Typed failure evidence with an explicit retry classification."""

    code: AgentErrorCode
    message: NonEmptyStr
    transient: StrictBool


class AgentRequest(DomainModel):
    """Immutable input envelope supplied to one Agent adapter invocation."""

    run_id: RunId
    task_id: TaskId
    role: AgentRole
    attempt: AgentAttempt
    source_revision: NonEmptyStr
    context_manifest_id: ContextId
    input_artifact_ids: tuple[ArtifactId, ...]
    permissions: AgentPermissions
    output_schema: NonEmptyStr
    timeout_seconds: TimeoutSeconds

    @model_validator(mode="after")
    def validate_artifact_ids(self) -> Self:
        ensure_unique(self.input_artifact_ids, "AgentRequest input_artifact_ids")
        expected_schema = ROLE_OUTPUT_SCHEMA[self.role]
        if self.output_schema != expected_schema:
            raise ValueError(
                f"AgentRequest output_schema for {self.role.value} must be {expected_schema}"
            )
        return self


class AgentResult(DomainModel):
    """Immutable typed output; success and failure states are mutually exclusive."""

    run_id: RunId
    task_id: TaskId
    role: AgentRole
    attempt: AgentAttempt
    source_revision: NonEmptyStr
    context_manifest_id: ContextId
    status: AgentRunStatus
    artifact: Artifact | None = None
    error: AgentFailure | None = None
    duration_ms: DurationMs = 0

    @model_validator(mode="after")
    def validate_result_state(self) -> Self:
        if self.status is AgentRunStatus.SUCCEEDED:
            if self.artifact is None or self.error is not None:
                raise ValueError("SUCCEEDED AgentResult requires artifact and no error")
            self._validate_artifact_identity(self.artifact)
        elif self.artifact is not None or self.error is None:
            raise ValueError("failed AgentResult requires error and no artifact")
        if self.status is AgentRunStatus.TIMED_OUT and (
            self.error is None or self.error.code is not AgentErrorCode.TIMEOUT
        ):
            raise ValueError("TIMED_OUT AgentResult requires TIMEOUT error")
        if (
            self.status is AgentRunStatus.FAILED
            and self.error is not None
            and self.error.code is AgentErrorCode.TIMEOUT
        ):
            raise ValueError("TIMEOUT error must use TIMED_OUT status")
        return self

    def _validate_artifact_identity(self, artifact: Artifact) -> None:
        if artifact.task_id != self.task_id:
            raise ValueError("AgentResult Artifact task_id mismatch")
        if artifact.producer.role is not self.role:
            raise ValueError("AgentResult Artifact producer role mismatch")
        if artifact.producer.run_id != self.run_id:
            raise ValueError("AgentResult Artifact producer run_id mismatch")
        if artifact.kind is not ROLE_OUTPUT[self.role]:
            raise ValueError("AgentResult Artifact kind mismatch")
        if artifact.source_revision != self.source_revision:
            raise ValueError("AgentResult Artifact source_revision mismatch")
        if artifact.context_manifest_id != self.context_manifest_id:
            raise ValueError("AgentResult Artifact context_manifest_id mismatch")


class FakeScenario(DomainModel):
    """One deterministic fake behavior and optional typed Artifact payload."""

    behavior: FakeBehavior
    artifact: Artifact | None = None
    message: NonEmptyStr = "simulated fake Agent outcome"
    duration_ms: DurationMs = 0

    @model_validator(mode="after")
    def validate_artifact_requirement(self) -> Self:
        needs_artifact = self.behavior in {
            FakeBehavior.SUCCESS,
            FakeBehavior.QA_FAIL,
            FakeBehavior.REVIEW_REJECT,
        }
        if needs_artifact and self.artifact is None:
            raise ValueError(f"{self.behavior} scenario requires an artifact")
        if not needs_artifact and self.artifact is not None:
            raise ValueError(f"{self.behavior} scenario cannot carry an artifact")
        return self


__all__ = [
    "ROLE_OUTPUT_SCHEMA",
    "AgentAttempt",
    "AgentErrorCode",
    "AgentFailure",
    "AgentRequest",
    "AgentResult",
    "AgentRunStatus",
    "FakeBehavior",
    "FakeScenario",
    "RunId",
]
