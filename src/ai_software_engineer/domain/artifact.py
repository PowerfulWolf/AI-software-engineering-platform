"""Immutable Artifact envelope and the four v0.1 Artifact kinds."""

from collections.abc import Iterable
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

from ai_software_engineer.domain.enums import (
    AgentRole,
    ArtifactKind,
    ChangeType,
    EvidenceType,
    FindingSeverity,
    ImplementationTestStatus,
    QaCriterionStatus,
    QaReportStatus,
    QaTestStatus,
    ReviewDimension,
    ReviewVerdict,
)
from ai_software_engineer.domain.model import (
    DomainModel,
    JsonValue,
    NonEmptyStr,
    ensure_known_references,
    ensure_unique,
)
from ai_software_engineer.domain.task import AcceptanceCriterionId, TaskId

ArtifactId = Annotated[str, StringConstraints(pattern=r"^art_[a-z0-9][a-z0-9_-]{2,63}$")]
EvidenceId = Annotated[str, StringConstraints(pattern=r"^ev_[a-z0-9][a-z0-9_-]{2,63}$")]
SchemaVersion = Annotated[str, StringConstraints(pattern=r"^v[0-9]+\.[0-9]+$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
CommitSha = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{7,64}$")]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(ge=1)]


class Evidence(DomainModel):
    """A stable reference to independently inspectable proof."""

    evidence_id: EvidenceId
    type: EvidenceType
    uri: NonEmptyStr
    locator: str | None = None
    description: NonEmptyStr
    sha256: Sha256
    required: StrictBool = False


class Finding(DomainModel):
    """A severity-rated issue linked to one or more Evidence entries."""

    finding_id: NonEmptyStr
    severity: FindingSeverity
    code: str | None = None
    message: NonEmptyStr
    file: str | None = None
    line: PositiveInt | None = None
    evidence_ids: Annotated[tuple[EvidenceId, ...], Field(min_length=1)]
    recommendation: str | None = None

    @model_validator(mode="after")
    def validate_unique_evidence(self) -> Self:
        ensure_unique(self.evidence_ids, "finding evidence_ids")
        return self


class AgentProducer(DomainModel):
    """The Agent Run identity that produced an Artifact."""

    role: AgentRole
    agent_id: NonEmptyStr
    agent_version: NonEmptyStr
    run_id: NonEmptyStr


class ArtifactIntegrity(DomainModel):
    """ArtifactStore-owned validation state and content digest."""

    sha256: Sha256
    validated: StrictBool
    validated_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_timestamp(self) -> Self:
        if self.validated and self.validated_at is None:
            raise ValueError("validated Artifact integrity requires validated_at")
        return self


class PlanStep(DomainModel):
    step_id: NonEmptyStr
    description: NonEmptyStr
    files: tuple[NonEmptyStr, ...]
    verification: NonEmptyStr


class PlanAcceptanceMapping(DomainModel):
    criterion_id: AcceptanceCriterionId
    step_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    test_strategy: NonEmptyStr


class PlanRisk(DomainModel):
    risk: NonEmptyStr
    mitigation: NonEmptyStr


class PlanContent(DomainModel):
    goal: NonEmptyStr
    assumptions: tuple[str, ...]
    steps: Annotated[tuple[PlanStep, ...], Field(min_length=1)]
    acceptance_mapping: tuple[PlanAcceptanceMapping, ...]
    risks: tuple[PlanRisk, ...]

    @model_validator(mode="after")
    def validate_plan_links(self) -> Self:
        step_ids = tuple(step.step_id for step in self.steps)
        ensure_unique(step_ids, "plan step IDs")
        ensure_unique(
            (mapping.criterion_id for mapping in self.acceptance_mapping),
            "plan acceptance criterion IDs",
        )
        mapped_steps = (
            step_id for mapping in self.acceptance_mapping for step_id in mapping.step_ids
        )
        unknown = sorted(set(mapped_steps) - set(step_ids))
        if unknown:
            raise ValueError(f"acceptance_mapping contains unknown step IDs: {', '.join(unknown)}")
        return self


class ChangedFile(DomainModel):
    path: NonEmptyStr
    change: ChangeType
    lines_added: NonNegativeInt
    lines_deleted: NonNegativeInt


class ImplementationAcceptanceMapping(DomainModel):
    criterion_id: AcceptanceCriterionId
    implementation: NonEmptyStr
    tests: tuple[NonEmptyStr, ...]


class ImplementationTestRun(DomainModel):
    command: NonEmptyStr
    status: ImplementationTestStatus
    evidence_id: EvidenceId
    duration_ms: NonNegativeInt | None = None


class ImplementationReportContent(DomainModel):
    commit_sha: CommitSha
    changed_files: Annotated[tuple[ChangedFile, ...], Field(min_length=1)]
    acceptance_mapping: tuple[ImplementationAcceptanceMapping, ...]
    tests_run: tuple[ImplementationTestRun, ...]
    known_risks: tuple[str, ...]
    blocked_reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_unique_entries(self) -> Self:
        ensure_unique((changed.path for changed in self.changed_files), "changed file paths")
        ensure_unique(
            (mapping.criterion_id for mapping in self.acceptance_mapping),
            "implementation acceptance criterion IDs",
        )
        return self


class QaCriterionResult(DomainModel):
    criterion_id: AcceptanceCriterionId
    status: QaCriterionStatus
    evidence_ids: tuple[EvidenceId, ...]
    notes: str | None = None

    @model_validator(mode="after")
    def validate_unique_evidence(self) -> Self:
        ensure_unique(self.evidence_ids, "QA criterion evidence_ids")
        return self


class QaTestRun(DomainModel):
    command: NonEmptyStr
    status: QaTestStatus
    evidence_id: EvidenceId
    duration_ms: NonNegativeInt | None = None


class QaReportContent(DomainModel):
    status: QaReportStatus
    criteria_results: Annotated[tuple[QaCriterionResult, ...], Field(min_length=1)]
    tests_run: tuple[QaTestRun, ...]
    findings: tuple[Finding, ...]
    environment: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def validate_verdict(self) -> Self:
        ensure_unique((result.criterion_id for result in self.criteria_results), "QA criterion IDs")
        ensure_unique((finding.finding_id for finding in self.findings), "QA finding IDs")
        if self.status is QaReportStatus.PASS:
            criteria_pass = all(
                result.status is QaCriterionStatus.PASS for result in self.criteria_results
            )
            tests_pass = all(test.status is QaTestStatus.PASS for test in self.tests_run)
            findings_pass = all(
                finding.severity not in {FindingSeverity.MAJOR, FindingSeverity.BLOCKER}
                for finding in self.findings
            )
            if not (criteria_pass and tests_pass and findings_pass):
                raise ValueError(
                    "QA PASS requires all reported criteria and tests to PASS "
                    "with no major findings"
                )
        return self


class ReviewReportContent(DomainModel):
    verdict: ReviewVerdict
    findings: tuple[Finding, ...]
    checked_dimensions: Annotated[tuple[ReviewDimension, ...], Field(min_length=1)]
    evidence: tuple[EvidenceId, ...]
    summary: str | None = None

    @model_validator(mode="after")
    def validate_verdict(self) -> Self:
        ensure_unique((finding.finding_id for finding in self.findings), "review finding IDs")
        ensure_unique(self.checked_dimensions, "checked_dimensions")
        ensure_unique(self.evidence, "review evidence")
        severe = {
            FindingSeverity.MAJOR,
            FindingSeverity.BLOCKER,
        }
        if self.verdict is ReviewVerdict.APPROVE and any(
            finding.severity is not FindingSeverity.INFO for finding in self.findings
        ):
            raise ValueError("Review APPROVE permits only INFO findings")
        if self.verdict is ReviewVerdict.REJECT and not any(
            finding.severity in severe for finding in self.findings
        ):
            raise ValueError("Review REJECT requires a MAJOR or BLOCKER finding")
        return self


class ArtifactEnvelope[ContentT: DomainModel](DomainModel):
    """Common immutable envelope shared by every v0.1 Artifact."""

    artifact_id: ArtifactId
    task_id: TaskId
    kind: ArtifactKind
    schema_version: SchemaVersion
    producer: AgentProducer
    source_revision: NonEmptyStr
    context_manifest_id: NonEmptyStr
    created_at: AwareDatetime
    parent_artifact_ids: tuple[ArtifactId, ...]
    supersedes: ArtifactId | None = None
    evidence: tuple[Evidence, ...]
    content: ContentT
    integrity: ArtifactIntegrity

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        ensure_unique(self.parent_artifact_ids, "parent_artifact_ids")
        ensure_unique((item.evidence_id for item in self.evidence), "Evidence IDs")
        if self.artifact_id in self.parent_artifact_ids:
            raise ValueError("Artifact cannot be its own parent")
        if self.supersedes == self.artifact_id:
            raise ValueError("Artifact cannot supersede itself")
        return self

    def ensure_evidence_references(self, references: Iterable[str]) -> None:
        ensure_known_references(
            references,
            (item.evidence_id for item in self.evidence),
            "Artifact content references",
        )


class PlanArtifact(ArtifactEnvelope[PlanContent]):
    kind: Literal[ArtifactKind.PLAN] = ArtifactKind.PLAN

    @model_validator(mode="after")
    def validate_plan_policy(self) -> Self:
        if self.producer.role is not AgentRole.ORCHESTRATOR:
            raise ValueError("plan Artifact must be produced by orchestrator")
        return self


class ImplementationReportArtifact(ArtifactEnvelope[ImplementationReportContent]):
    kind: Literal[ArtifactKind.IMPLEMENTATION_REPORT] = ArtifactKind.IMPLEMENTATION_REPORT

    @model_validator(mode="after")
    def validate_implementation_policy(self) -> Self:
        if self.producer.role is not AgentRole.CODER:
            raise ValueError("implementation-report Artifact must be produced by coder")
        self.ensure_evidence_references(test.evidence_id for test in self.content.tests_run)
        return self


class QaReportArtifact(ArtifactEnvelope[QaReportContent]):
    kind: Literal[ArtifactKind.QA_REPORT] = ArtifactKind.QA_REPORT

    @model_validator(mode="after")
    def validate_qa_policy(self) -> Self:
        if self.producer.role is not AgentRole.QA:
            raise ValueError("qa-report Artifact must be produced by qa")
        references = [
            evidence_id
            for result in self.content.criteria_results
            for evidence_id in result.evidence_ids
        ]
        references.extend(test.evidence_id for test in self.content.tests_run)
        references.extend(
            evidence_id for finding in self.content.findings for evidence_id in finding.evidence_ids
        )
        self.ensure_evidence_references(references)
        return self


class ReviewReportArtifact(ArtifactEnvelope[ReviewReportContent]):
    kind: Literal[ArtifactKind.REVIEW_REPORT] = ArtifactKind.REVIEW_REPORT

    @model_validator(mode="after")
    def validate_review_policy(self) -> Self:
        if self.producer.role is not AgentRole.REVIEWER:
            raise ValueError("review-report Artifact must be produced by reviewer")
        references = list(self.content.evidence)
        references.extend(
            evidence_id for finding in self.content.findings for evidence_id in finding.evidence_ids
        )
        self.ensure_evidence_references(references)
        return self


Artifact = Annotated[
    PlanArtifact | ImplementationReportArtifact | QaReportArtifact | ReviewReportArtifact,
    Field(discriminator="kind"),
]
_ARTIFACT_ADAPTER: Final[TypeAdapter[Artifact]] = TypeAdapter(Artifact)


def validate_artifact(payload: object, kind: ArtifactKind) -> Artifact:
    """Validate input and ensure its discriminated subtype matches the expected kind."""
    artifact = _ARTIFACT_ADAPTER.validate_python(payload)
    if artifact.kind is not kind:
        raise ValueError(f"expected {kind} Artifact, received {artifact.kind}")
    return artifact
