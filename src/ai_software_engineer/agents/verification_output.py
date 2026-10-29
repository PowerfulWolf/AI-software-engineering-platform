"""Bind a verifier's new claims to its trusted controlled execution receipt.

These values are application-only provenance, never model-authored authority or
durable Artifact fields. They do not turn command success into a role verdict.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from pydantic import Field, model_validator

from ai_software_engineer.agents.execution import ExecutionGuard
from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.domain.artifact import (
    Artifact,
    QaReportArtifact,
    ReviewReportArtifact,
    Sha256,
)
from ai_software_engineer.domain.enums import (
    AgentRole,
    EvidenceType,
    FindingSeverity,
    QaCriterionStatus,
    QaReportStatus,
    ReviewVerdict,
)
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.native_verification import role_verification_digest
from ai_software_engineer.domain.task import AcceptanceCriterionId

if TYPE_CHECKING:
    from ai_software_engineer.manager.candidate_test_entry_absence import (
        CandidateTestEntryAbsenceObservation,
    )


class VerificationOutputRule(StrEnum):
    IDENTITY = "VERIFICATION_RECEIPT_IDENTITY"
    MISSING = "VERIFICATION_RECEIPT_MISSING"
    REFERENCE = "VERIFICATION_RECEIPT_REFERENCE"
    COVERAGE = "VERIFICATION_RECEIPT_COVERAGE"
    COMMAND_FAILED = "VERIFICATION_COMMAND_FAILED"
    CURRENT = "VERIFICATION_RECEIPT_CHANGED"


class VerificationOutputRejected(ValueError):
    def __init__(self, rule: VerificationOutputRule) -> None:
        super().__init__("Controlled verification output does not match its trusted receipt")
        self.rule = rule


class TrustedVerificationOutputContract(DomainModel):
    request_sha256: Sha256
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    role: Literal[AgentRole.QA, AgentRole.REVIEWER]
    attempt: int = Field(ge=1, strict=True)
    source_revision: NonEmptyStr
    context_manifest_id: NonEmptyStr
    receipt_uri: NonEmptyStr
    receipt_sha256: Sha256
    authority_sha256: Sha256
    claim_sha256: Sha256 | None = None
    receipt_covered_required_criterion_ids: tuple[AcceptanceCriterionId, ...]
    command_returncodes: tuple[int, ...] = Field(min_length=1)


class StaticQaMissingEntry(DomainModel):
    path: NonEmptyStr
    criterion_ids: tuple[AcceptanceCriterionId, ...] = Field(min_length=1)
    node_ids: tuple[NonEmptyStr, ...] | None = None

    @model_validator(mode="after")
    def exact_source_nodes(self) -> StaticQaMissingEntry:
        if self.node_ids is not None:
            if not self.node_ids:
                raise ValueError("static QA nodes cannot be an empty set")
            ensure_unique(self.node_ids, "missing static QA nodes")
            if any(not node_id.startswith(self.path + "::") for node_id in self.node_ids):
                raise ValueError("static QA node does not belong to the frozen test path")
        return self


class TrustedStaticQaMissingEntryOutputContract(DomainModel):
    """App-owned output gate for an already sealed, no-start source-defect proof.

    This type grants no QA claim or wait resolution. Its caller must separately
    authenticate the current proof and fresh independent QA assignment.
    """

    request_sha256: Sha256
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    role: Literal[AgentRole.QA] = AgentRole.QA
    attempt: int = Field(ge=1, strict=True)
    source_revision: NonEmptyStr
    context_manifest_id: NonEmptyStr
    proof_uri: NonEmptyStr
    proof_sha256: Sha256
    authority_sha256: Sha256
    claim_sha256: Sha256
    observation_sha256: Sha256
    implementation_artifact_id: NonEmptyStr
    missing: tuple[StaticQaMissingEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_proof_shape(self) -> TrustedStaticQaMissingEntryOutputContract:
        ensure_unique((entry.path for entry in self.missing), "missing static QA paths")
        if self.proof_uri != "static-qa-missing-entry://" + self.proof_sha256:
            raise ValueError("static QA proof does not bind the exact candidate")
        return self


def static_qa_missing_entry_output_contract(
    request: AgentRequest,
    *,
    observation: CandidateTestEntryAbsenceObservation,
    sealed_no_start_proof_sha256: str,
    authority_sha256: str,
    claim_sha256: str,
) -> TrustedStaticQaMissingEntryOutputContract:
    """Construct only from trusted application facts, never model-authored data."""
    observation.validate_integrity()
    if (
        request.role is not AgentRole.QA
        or observation.task_id != request.task_id
        or observation.candidate_revision != request.source_revision
        or not {
            observation.plan_artifact_id,
            observation.implementation_artifact_id,
        }.issubset(request.input_artifact_ids)
    ):
        raise VerificationOutputRejected(VerificationOutputRule.IDENTITY)
    by_path: dict[str, list[AcceptanceCriterionId]] = {}
    nodes_by_path: dict[str, list[str]] = {}
    for entry in observation.missing:
        criteria = by_path.setdefault(entry.path, [])
        for criterion_id in entry.requirement.criterion_ids:
            if criterion_id not in criteria:
                criteria.append(criterion_id)
        if entry.node_id is not None:
            nodes = nodes_by_path.setdefault(entry.path, [])
            if entry.node_id not in nodes:
                nodes.append(entry.node_id)
    return TrustedStaticQaMissingEntryOutputContract(
        request_sha256=role_verification_digest(request.to_wire()),
        task_id=request.task_id,
        run_id=request.run_id,
        attempt=request.attempt,
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        proof_uri="static-qa-missing-entry://" + sealed_no_start_proof_sha256,
        proof_sha256=sealed_no_start_proof_sha256,
        authority_sha256=authority_sha256,
        claim_sha256=claim_sha256,
        observation_sha256=observation.observation_sha256,
        implementation_artifact_id=observation.implementation_artifact_id,
        missing=tuple(
            StaticQaMissingEntry(
                path=path,
                criterion_ids=tuple(criteria),
                node_ids=tuple(nodes_by_path[path]) if path in nodes_by_path else None,
            )
            for path, criteria in by_path.items()
        ),
    )


def validate_static_qa_missing_entry_output(
    request: AgentRequest,
    artifact: Artifact,
    contract: TrustedStaticQaMissingEntryOutputContract,
) -> None:
    """Accept only an independent QA-authored FAIL citing each absent planned entry."""
    try:
        type(contract).model_validate(contract.to_wire())
    except ValueError as error:
        raise VerificationOutputRejected(VerificationOutputRule.CURRENT) from error
    if (
        request.role is not AgentRole.QA
        or not isinstance(artifact, QaReportArtifact)
        or contract.request_sha256 != role_verification_digest(request.to_wire())
        or (contract.task_id, contract.run_id, contract.attempt)
        != (request.task_id, request.run_id, request.attempt)
        or contract.source_revision != request.source_revision
        or contract.context_manifest_id != request.context_manifest_id
        or artifact.task_id != request.task_id
        or artifact.source_revision != request.source_revision
        or artifact.context_manifest_id != request.context_manifest_id
        or artifact.parent_artifact_ids != (contract.implementation_artifact_id,)
        or artifact.producer.role is not AgentRole.QA
        or artifact.producer.run_id != request.run_id
    ):
        raise VerificationOutputRejected(VerificationOutputRule.IDENTITY)
    if len(artifact.evidence) != 1:
        raise VerificationOutputRejected(VerificationOutputRule.REFERENCE)
    evidence = artifact.evidence[0]
    if (
        evidence.type is not EvidenceType.FILE
        or evidence.uri != contract.proof_uri
        or evidence.sha256 != contract.proof_sha256
        or not evidence.required
    ):
        raise VerificationOutputRejected(VerificationOutputRule.MISSING)
    if artifact.content.status is not QaReportStatus.FAIL or artifact.content.tests_run:
        raise VerificationOutputRejected(VerificationOutputRule.COMMAND_FAILED)
    missing = contract.missing
    affected = {criterion_id for entry in missing for criterion_id in entry.criterion_ids}
    results = {item.criterion_id: item for item in artifact.content.criteria_results}
    if not affected.issubset(results):
        raise VerificationOutputRejected(VerificationOutputRule.COVERAGE)
    for criterion_id, result in results.items():
        if criterion_id in affected:
            if (
                result.status is not QaCriterionStatus.FAIL
                or evidence.evidence_id not in result.evidence_ids
            ):
                raise VerificationOutputRejected(VerificationOutputRule.COVERAGE)
        elif result.status is not QaCriterionStatus.NOT_TESTED or result.evidence_ids:
            raise VerificationOutputRejected(VerificationOutputRule.COVERAGE)
    paths = {entry.path for entry in missing}
    findings = artifact.content.findings
    if len(findings) != len(paths) or {finding.file for finding in findings} != paths:
        raise VerificationOutputRejected(VerificationOutputRule.COVERAGE)
    if any(
        finding.code != "MISSING_PLANNED_TEST_ENTRY"
        or finding.severity not in {FindingSeverity.MAJOR, FindingSeverity.BLOCKER}
        or finding.evidence_ids != (evidence.evidence_id,)
        for finding in findings
    ):
        raise VerificationOutputRejected(VerificationOutputRule.REFERENCE)


@runtime_checkable
class VerificationOutputCurrentValidator(Protocol):
    def validate_output_current(
        self,
        request: AgentRequest,
        workspace_root: Path,
        execution_guard: ExecutionGuard | None,
        contract: TrustedVerificationOutputContract,
    ) -> None:
        """Read current authority/receipt facts without replaying verification."""
        ...


def verification_output_contract(
    request: AgentRequest,
    *,
    receipt_uri: str,
    receipt_sha256: str,
    authority_sha256: str,
    receipt_covered_required_criterion_ids: tuple[str, ...],
    command_returncodes: tuple[int, ...],
    claim_sha256: str | None = None,
) -> TrustedVerificationOutputContract:
    if request.role not in (AgentRole.QA, AgentRole.REVIEWER):
        raise VerificationOutputRejected(VerificationOutputRule.IDENTITY)
    ensure_unique(receipt_covered_required_criterion_ids, "receipt-covered required criteria")
    return TrustedVerificationOutputContract(
        request_sha256=role_verification_digest(request.to_wire()),
        task_id=request.task_id,
        run_id=request.run_id,
        role=request.role,
        attempt=request.attempt,
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        receipt_uri=receipt_uri,
        receipt_sha256=receipt_sha256,
        authority_sha256=authority_sha256,
        claim_sha256=claim_sha256,
        receipt_covered_required_criterion_ids=receipt_covered_required_criterion_ids,
        command_returncodes=command_returncodes,
    )


def validate_verification_output(
    request: AgentRequest,
    artifact: Artifact,
    contract: TrustedVerificationOutputContract,
) -> None:
    if (
        contract.request_sha256 != role_verification_digest(request.to_wire())
        or (contract.task_id, contract.run_id, contract.role, contract.attempt)
        != (request.task_id, request.run_id, request.role, request.attempt)
        or contract.source_revision != request.source_revision
        or contract.context_manifest_id != request.context_manifest_id
        or artifact.task_id != contract.task_id
        or artifact.producer.role is not contract.role
        or artifact.producer.run_id != contract.run_id
        or artifact.source_revision != contract.source_revision
        or artifact.context_manifest_id != contract.context_manifest_id
    ):
        raise VerificationOutputRejected(VerificationOutputRule.IDENTITY)
    current_ids = {
        item.evidence_id
        for item in artifact.evidence
        if item.uri == contract.receipt_uri and item.sha256 == contract.receipt_sha256
    }
    if not current_ids:
        raise VerificationOutputRejected(VerificationOutputRule.MISSING)
    if isinstance(artifact, QaReportArtifact):
        if any(test.evidence_id not in current_ids for test in artifact.content.tests_run):
            raise VerificationOutputRejected(VerificationOutputRule.REFERENCE)
        required = set(contract.receipt_covered_required_criterion_ids)
        results = {item.criterion_id: item for item in artifact.content.criteria_results}
        if not required.issubset(results):
            raise VerificationOutputRejected(VerificationOutputRule.COVERAGE)
        if any(
            item.status is QaCriterionStatus.PASS
            and not current_ids.intersection(item.evidence_ids)
            for criterion_id, item in results.items()
            if criterion_id in required
        ):
            raise VerificationOutputRejected(VerificationOutputRule.COVERAGE)
        # One receipt may contain mixed command outcomes. A truthful QA FAIL can
        # report passing individual tests; only the overall PASS needs all zero.
        if artifact.content.status is QaReportStatus.PASS and any(contract.command_returncodes):
            raise VerificationOutputRejected(VerificationOutputRule.COMMAND_FAILED)
    elif isinstance(artifact, ReviewReportArtifact):
        if not current_ids.intersection(artifact.content.evidence):
            raise VerificationOutputRejected(VerificationOutputRule.REFERENCE)
        if artifact.content.verdict is ReviewVerdict.APPROVE and any(contract.command_returncodes):
            raise VerificationOutputRejected(VerificationOutputRule.COMMAND_FAILED)
    else:
        raise VerificationOutputRejected(VerificationOutputRule.IDENTITY)
