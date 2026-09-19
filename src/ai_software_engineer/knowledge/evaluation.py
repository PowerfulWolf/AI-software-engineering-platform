"""Replayable offline knowledge effectiveness metrics from typed run observations."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.knowledge.models import Digest, KnowledgeCitation, KnowledgeError, digest


class KnowledgeEvaluationObservation(DomainModel):
    case_id: NonEmptyStr
    condition: Literal["ENABLED", "DISABLED"]
    source_revision: NonEmptyStr
    context_manifest_id: NonEmptyStr
    snapshot_sha256: Digest
    skill_versions: tuple[NonEmptyStr, ...]
    provider: NonEmptyStr
    model: NonEmptyStr
    expected_citations: tuple[KnowledgeCitation, ...]
    allowed_citations: tuple[KnowledgeCitation, ...]
    actual_citations: tuple[KnowledgeCitation, ...]
    decisive_claims: Annotated[int, Field(ge=0)]
    supported_claims: Annotated[int, Field(ge=0)]
    gap_expected: bool
    gap_reported: bool
    acceptance_total: Annotated[int, Field(ge=0)]
    acceptance_covered: Annotated[int, Field(ge=0)]
    qa_rejected: bool
    review_rejected: bool
    token_count: Annotated[int, Field(ge=0)]
    latency_ms: Annotated[int, Field(ge=0)]


class KnowledgeEvaluationReport(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    observations: tuple[KnowledgeEvaluationObservation, ...]
    citation_precision: float | None = None
    hallucination_rate: float | None = None
    gap_recall: float | None = None
    scope_leakage_rate: float | None = None
    acceptance_coverage: float | None = None
    qa_rejection_rate: float | None = None
    review_rejection_rate: float | None = None
    additional_tokens: int
    additional_latency_ms: int
    passed: bool
    report_sha256: Digest

    def validate_integrity(self) -> None:
        if self.report_sha256 != digest(self.model_dump(mode="json", exclude={"report_sha256"})):
            raise KnowledgeError("EVALUATION_INTEGRITY")


def evaluate_knowledge(
    observations: tuple[KnowledgeEvaluationObservation, ...],
) -> KnowledgeEvaluationReport:
    citations = claims = supported = correct = leaks = expected_gaps = found_gaps = total = (
        covered
    ) = 0
    tokens = latency = 0
    passed = True
    for item in observations:
        if (
            item.supported_claims > item.decisive_claims
            or item.acceptance_covered > item.acceptance_total
        ):
            raise ValueError("evaluation observations contain impossible counts")
        citations += len(item.actual_citations)
        correct += sum(citation in item.expected_citations for citation in item.actual_citations)
        leaked = sum(citation not in item.allowed_citations for citation in item.actual_citations)
        leaks += leaked
        claims += item.decisive_claims
        supported += item.supported_claims
        expected_gaps += item.gap_expected
        found_gaps += item.gap_expected and item.gap_reported
        total += item.acceptance_total
        covered += item.acceptance_covered
        sign = 1 if item.condition == "ENABLED" else -1
        tokens += sign * item.token_count
        latency += sign * item.latency_ms
        passed &= not leaked and item.decisive_claims == item.supported_claims
        passed &= not item.gap_expected or item.gap_reported
        passed &= all(citation in item.expected_citations for citation in item.actual_citations)
        passed &= not (
            item.expected_citations and item.decisive_claims and not item.actual_citations
        )
    count = len(observations)
    provisional = KnowledgeEvaluationReport(
        observations=observations,
        citation_precision=_ratio(correct, citations),
        hallucination_rate=_ratio(claims - supported, claims),
        gap_recall=_ratio(found_gaps, expected_gaps),
        scope_leakage_rate=_ratio(leaks, citations),
        acceptance_coverage=_ratio(covered, total),
        qa_rejection_rate=_ratio(sum(o.qa_rejected for o in observations), count),
        review_rejection_rate=_ratio(sum(o.review_rejected for o in observations), count),
        additional_tokens=tokens,
        additional_latency_ms=latency,
        passed=passed and bool(count),
        report_sha256="0" * 64,
    )
    return provisional.model_copy(
        update={
            "report_sha256": digest(provisional.model_dump(mode="json", exclude={"report_sha256"}))
        }
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None
