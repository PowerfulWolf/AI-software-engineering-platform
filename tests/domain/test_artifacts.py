"""Artifact invariants tested through the public validation seam."""

from collections.abc import Callable
from typing import Protocol

import pytest

from ai_software_engineer.domain import (
    ArtifactKind,
    Finding,
    FindingSeverity,
    PlanArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
    validate_artifact,
)
from ai_software_engineer.domain.model import WirePayload
from tests.domain.factories import (
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
    make_review_artifact,
)


class WireArtifact(Protocol):
    def to_wire(self) -> WirePayload: ...


type ArtifactFactory = Callable[[], WireArtifact]


def test_discriminated_artifact_validation_returns_the_typed_subclass() -> None:
    artifact = validate_artifact(make_plan_artifact().to_wire(), ArtifactKind.PLAN)

    assert isinstance(artifact, PlanArtifact)


@pytest.mark.parametrize(
    ("factory", "wrong_role"),
    (
        (make_plan_artifact, "coder"),
        (make_implementation_artifact, "qa"),
        (make_qa_artifact, "reviewer"),
        (make_review_artifact, "orchestrator"),
    ),
)
def test_each_artifact_kind_rejects_a_producer_role_mismatch(
    factory: ArtifactFactory, wrong_role: str
) -> None:
    payload = factory().to_wire()
    payload["producer"] = {
        "role": wrong_role,
        "agent_id": f"agent_{wrong_role}_001",
        "agent_version": "v0.1",
        "run_id": f"run_{wrong_role}_001",
    }

    with pytest.raises(ValueError, match=r"must be produced by"):
        validate_artifact(payload, ArtifactKind.PLAN)


def test_artifact_rejects_dangling_content_evidence_reference() -> None:
    payload = make_qa_artifact().to_wire()
    payload["content"] = {
        "status": "PASS",
        "criteria_results": [
            {
                "criterion_id": "ac_models_01",
                "status": "PASS",
                "evidence_ids": ["ev_missing"],
            }
        ],
        "tests_run": [],
        "findings": [],
    }

    with pytest.raises(ValueError, match=r"unknown Evidence IDs.*ev_missing"):
        QaReportArtifact.model_validate(payload)


def test_qa_pass_rejects_not_tested_criterion() -> None:
    payload = make_qa_artifact().to_wire()
    payload["content"] = {
        "status": "PASS",
        "criteria_results": [
            {
                "criterion_id": "ac_models_01",
                "status": "NOT_TESTED",
                "evidence_ids": ["ev_qa_tests"],
            }
        ],
        "tests_run": [],
        "findings": [],
    }

    with pytest.raises(ValueError, match="QA PASS"):
        QaReportArtifact.model_validate(payload)


def test_review_approve_rejects_major_findings() -> None:
    report = make_review_artifact()
    payload = report.to_wire()
    payload["content"] = {
        **report.content.to_wire(),
        "findings": [
            Finding(
                finding_id="finding_contract_drift",
                severity=FindingSeverity.MAJOR,
                message="The public contract drifted.",
                evidence_ids=("ev_review_diff",),
            ).to_wire()
        ],
    }

    with pytest.raises(ValueError, match="APPROVE"):
        ReviewReportArtifact.model_validate(payload)


def test_review_reject_requires_major_or_blocker_finding() -> None:
    report = make_review_artifact()
    payload = report.to_wire()
    payload["content"] = {
        **report.content.to_wire(),
        "verdict": "REJECT",
        "findings": [
            Finding(
                finding_id="finding_style_note",
                severity=FindingSeverity.MINOR,
                message="A small naming improvement is possible.",
                evidence_ids=("ev_review_diff",),
            ).to_wire()
        ],
    }

    with pytest.raises(ValueError, match="REJECT"):
        ReviewReportArtifact.model_validate(payload)


def test_valid_qa_and_review_artifacts_keep_independent_verdicts() -> None:
    qa = validate_artifact(make_qa_artifact().to_wire(), ArtifactKind.QA_REPORT)
    review = validate_artifact(make_review_artifact().to_wire(), ArtifactKind.REVIEW_REPORT)

    assert isinstance(qa, QaReportArtifact)
    assert isinstance(review, ReviewReportArtifact)
    assert qa.producer.run_id != review.producer.run_id


def test_artifact_validation_rejects_an_unexpected_kind() -> None:
    with pytest.raises(ValueError, match=r"expected review-report"):
        validate_artifact(make_plan_artifact().to_wire(), ArtifactKind.REVIEW_REPORT)
