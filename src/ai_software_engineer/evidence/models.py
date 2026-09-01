"""Typed, integrity-checked evidence and per-run manifests."""

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Final, Literal, Self, cast

from pydantic import (
    AwareDatetime,
    BaseModel,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

from ai_software_engineer.agents import AgentErrorCode, AgentRunStatus, AgentUsage
from ai_software_engineer.domain.artifact import Evidence, EvidenceId, Sha256
from ai_software_engineer.domain.enums import AgentRole, EvidenceType
from ai_software_engineer.domain.identity import ContextId, ProjectId, RunId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, WirePayload, ensure_unique
from ai_software_engineer.domain.task import TaskId

OperationId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.:-]{0,127}$")]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
_UNSEALED_DIGEST = "0" * 64


class EvidenceKind(StrEnum):
    COMMAND = "command"
    DIFF = "diff"
    TEST = "test"
    AGENT_USAGE = "agent_usage"


class CommandOutcome(StrEnum):
    COMPLETED = "COMPLETED"
    TIMED_OUT = "TIMED_OUT"
    REJECTED = "REJECTED"
    FAILED_TO_START = "FAILED_TO_START"


class TestOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    NOT_RUN = "NOT_RUN"


class RunOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    REJECTED = "REJECTED"


class RedactionFact(DomainModel):
    kind: NonEmptyStr
    count: Annotated[StrictInt, Field(ge=1)]


class RunEvidenceIdentity(DomainModel):
    project_id: ProjectId
    task_id: TaskId
    run_id: RunId
    agent_id: NonEmptyStr
    role: AgentRole
    attempt: Annotated[StrictInt, Field(ge=1, le=10)]
    source_revision: NonEmptyStr
    context_manifest_id: ContextId


class CommandEvidencePayload(DomainModel):
    outcome: CommandOutcome
    argv: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    cwd: NonEmptyStr
    returncode: StrictInt | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: NonNegativeInt
    stdout_truncated: StrictBool = False
    stderr_truncated: StrictBool = False
    error_code: NonEmptyStr | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.outcome is CommandOutcome.COMPLETED:
            if self.returncode is None or self.error_code is not None:
                raise ValueError("completed command requires returncode and no error_code")
        elif self.returncode is not None or self.error_code is None:
            raise ValueError("non-completed command requires error_code and no returncode")
        return self


class DiffEvidencePayload(DomainModel):
    base_revision: NonEmptyStr
    candidate_revision: NonEmptyStr
    changed_paths: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    patch: str
    patch_truncated: StrictBool = False

    @model_validator(mode="after")
    def validate_paths(self) -> Self:
        ensure_unique(self.changed_paths, "diff changed_paths")
        return self


class TestEvidencePayload(DomainModel):
    framework: NonEmptyStr
    suite: NonEmptyStr
    outcome: TestOutcome
    command_evidence_id: EvidenceId
    required: StrictBool = True


class AgentUsageEvidencePayload(DomainModel):
    provider: NonEmptyStr
    model: NonEmptyStr
    status: AgentRunStatus
    duration_ms: NonNegativeInt
    usage: AgentUsage | None = None
    error_code: AgentErrorCode | None = None
    error_message: str | None = None
    transient: StrictBool | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.status is AgentRunStatus.SUCCEEDED:
            if self.error_code is not None or self.transient is not None:
                raise ValueError("successful Agent usage cannot carry an error")
        elif self.error_code is None or self.transient is None:
            raise ValueError("failed Agent usage requires error_code and transient")
        elif (
            self.status is AgentRunStatus.TIMED_OUT
            and self.error_code is not AgentErrorCode.TIMEOUT
        ):
            raise ValueError("timed out Agent usage requires TIMEOUT error")
        elif self.status is AgentRunStatus.FAILED and self.error_code is AgentErrorCode.TIMEOUT:
            raise ValueError("TIMEOUT Agent usage must use TIMED_OUT status")
        return self


class EvidenceRecordEnvelope[PayloadT: DomainModel](DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    evidence_id: EvidenceId
    kind: EvidenceKind
    operation_id: OperationId
    identity: RunEvidenceIdentity
    description: NonEmptyStr
    captured_at: AwareDatetime
    redactions: tuple[RedactionFact, ...] = ()
    payload: PayloadT
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        ensure_unique((item.kind for item in self.redactions), "evidence redaction kinds")
        if self.record_sha256 != _UNSEALED_DIGEST and self.record_sha256 != evidence_record_digest(
            self
        ):
            raise ValueError("evidence record digest does not match content")
        return self

    def validate_integrity(self) -> None:
        """Reject evidence whose durable content no longer matches its digest."""
        if self.record_sha256 != evidence_record_digest(self):
            raise ValueError("evidence record digest does not match content")

    @property
    def uri(self) -> str:
        return (
            f"evidence://{self.identity.project_id}/{self.identity.task_id}/"
            f"{self.identity.run_id}/{self.evidence_id}"
        )

    def to_artifact_evidence(self, *, required: bool = False) -> Evidence:
        mapping = {
            EvidenceKind.COMMAND: EvidenceType.COMMAND,
            EvidenceKind.DIFF: EvidenceType.DIFF,
            EvidenceKind.TEST: EvidenceType.TEST,
            EvidenceKind.AGENT_USAGE: EvidenceType.METRIC,
        }
        return Evidence(
            evidence_id=self.evidence_id,
            type=mapping[self.kind],
            uri=self.uri,
            description=self.description,
            sha256=self.record_sha256,
            required=required,
        )


class CommandEvidenceRecord(EvidenceRecordEnvelope[CommandEvidencePayload]):
    kind: Literal[EvidenceKind.COMMAND] = EvidenceKind.COMMAND


class DiffEvidenceRecord(EvidenceRecordEnvelope[DiffEvidencePayload]):
    kind: Literal[EvidenceKind.DIFF] = EvidenceKind.DIFF


class TestEvidenceRecord(EvidenceRecordEnvelope[TestEvidencePayload]):
    kind: Literal[EvidenceKind.TEST] = EvidenceKind.TEST


class AgentUsageEvidenceRecord(EvidenceRecordEnvelope[AgentUsageEvidencePayload]):
    kind: Literal[EvidenceKind.AGENT_USAGE] = EvidenceKind.AGENT_USAGE


EvidenceRecord = Annotated[
    CommandEvidenceRecord | DiffEvidenceRecord | TestEvidenceRecord | AgentUsageEvidenceRecord,
    Field(discriminator="kind"),
]
_EVIDENCE_ADAPTER: Final[TypeAdapter[EvidenceRecord]] = TypeAdapter(EvidenceRecord)


class RunEvidenceManifest(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    identity: RunEvidenceIdentity
    outcome: RunOutcome
    evidence_ids: Annotated[tuple[EvidenceId, ...], Field(min_length=1)]
    started_at: AwareDatetime
    completed_at: AwareDatetime
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        ensure_unique(self.evidence_ids, "run evidence IDs")
        if self.completed_at < self.started_at:
            raise ValueError("run evidence completed_at cannot precede started_at")
        if self.manifest_sha256 != _UNSEALED_DIGEST and self.manifest_sha256 != run_manifest_digest(
            self
        ):
            raise ValueError("run evidence manifest digest does not match content")
        return self

    def validate_integrity(self) -> None:
        """Reject a manifest whose durable content no longer matches its digest."""
        if self.manifest_sha256 != run_manifest_digest(self):
            raise ValueError("run evidence manifest digest does not match content")


def evidence_record_digest(record: BaseModel) -> Sha256:
    payload = record.model_dump(mode="json", exclude={"record_sha256"})
    return _sha256(_canonical_json(cast(WirePayload, payload)))


def run_manifest_digest(manifest: RunEvidenceManifest) -> Sha256:
    payload = manifest.model_dump(mode="json", exclude={"manifest_sha256"})
    return _sha256(_canonical_json(cast(WirePayload, payload)))


def seal_evidence_record[RecordT: BaseModel](record: RecordT) -> RecordT:
    sealed = record.model_copy(update={"record_sha256": evidence_record_digest(record)})
    validated = _EVIDENCE_ADAPTER.validate_python(sealed)
    validated.validate_integrity()
    return cast(RecordT, validated)


def seal_run_manifest(manifest: RunEvidenceManifest) -> RunEvidenceManifest:
    sealed = manifest.model_copy(update={"manifest_sha256": run_manifest_digest(manifest)})
    sealed.validate_integrity()
    return RunEvidenceManifest.model_validate(sealed)


def validate_evidence_record(payload: object) -> EvidenceRecord:
    return _EVIDENCE_ADAPTER.validate_python(payload)


def _canonical_json(payload: WirePayload) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(content: str) -> Sha256:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


__all__ = [
    "AgentUsageEvidencePayload",
    "AgentUsageEvidenceRecord",
    "CommandEvidencePayload",
    "CommandEvidenceRecord",
    "CommandOutcome",
    "DiffEvidencePayload",
    "DiffEvidenceRecord",
    "EvidenceKind",
    "EvidenceRecord",
    "OperationId",
    "RedactionFact",
    "RunEvidenceIdentity",
    "RunEvidenceManifest",
    "RunOutcome",
    "TestEvidencePayload",
    "TestEvidenceRecord",
    "TestOutcome",
    "evidence_record_digest",
    "run_manifest_digest",
    "seal_evidence_record",
    "seal_run_manifest",
    "validate_evidence_record",
]
