"""Bind a verifier's new claims to its trusted controlled execution receipt.

These values are application-only provenance, never model-authored authority or
durable Artifact fields. They do not turn command success into a role verdict.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from pydantic import Field

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
    QaCriterionStatus,
    QaReportStatus,
    ReviewVerdict,
)
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.native_verification import role_verification_digest
from ai_software_engineer.domain.task import AcceptanceCriterionId


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
