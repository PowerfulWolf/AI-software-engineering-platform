"""A missing candidate test may only support an independent, commandless QA FAIL."""

from __future__ import annotations

import pytest

from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.agents.verification_output import (
    TrustedStaticQaMissingEntryOutputContract,
    VerificationOutputRejected,
    static_qa_missing_entry_output_contract,
    validate_static_qa_missing_entry_output,
)
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.artifact import Finding, QaReportArtifact
from ai_software_engineer.domain.enums import (
    EvidenceType,
    FindingSeverity,
    QaCriterionStatus,
    QaReportStatus,
)
from ai_software_engineer.domain.execution_window import PlannedVerificationRequirement
from ai_software_engineer.domain.native_verification import role_verification_digest
from ai_software_engineer.manager.candidate_test_entry_absence import (
    CandidateTestEntryAbsenceObservation,
    MissingPlannedTestEntry,
)
from tests.agents.test_openai_compatible import _request
from tests.domain.factories import make_qa_artifact

PATH = "tests/browser/fixture.test.cjs"


def _subject() -> tuple[AgentRequest, TrustedStaticQaMissingEntryOutputContract, QaReportArtifact]:
    request = _request(AgentRole.QA).model_copy(
        update={"input_artifact_ids": ("art_plan_001", "art_impl_001")}
    )
    row = PlannedVerificationRequirement(
        id="verify_browser",
        role=AgentRole.QA,
        criterion_ids=("ac_models_01",),
        argv=("node", "--test", PATH),
        verification_levels=("e2e",),
        planned_new_files=(PATH,),
    )
    observation = CandidateTestEntryAbsenceObservation.create(
        task_id=request.task_id,
        task_intent_sha256="a" * 64,
        candidate_revision=request.source_revision,
        plan_artifact_id="art_plan_001",
        plan_artifact_sha256="b" * 64,
        plan_requirements_sha256=role_verification_digest([row.to_wire()]),
        implementation_artifact_id="art_impl_001",
        implementation_artifact_sha256="c" * 64,
        missing=(
            MissingPlannedTestEntry(
                requirement=row,
                requirement_sha256=role_verification_digest(row.to_wire()),
                path=PATH,
            ),
        ),
    )
    contract = static_qa_missing_entry_output_contract(
        request,
        observation=observation,
        sealed_no_start_proof_sha256="d" * 64,
        authority_sha256="e" * 64,
        claim_sha256="f" * 64,
    )
    template = make_qa_artifact()
    evidence = template.evidence[0].model_copy(
        update={
            "type": EvidenceType.FILE,
            "uri": contract.proof_uri,
            "sha256": contract.proof_sha256,
            "required": True,
        }
    )
    report = template.model_copy(
        update={
            "task_id": request.task_id,
            "source_revision": request.source_revision,
            "context_manifest_id": request.context_manifest_id,
            "parent_artifact_ids": (contract.implementation_artifact_id,),
            "producer": template.producer.model_copy(update={"run_id": request.run_id}),
            "evidence": (evidence,),
            "content": template.content.model_copy(
                update={
                    "status": QaReportStatus.FAIL,
                    "tests_run": (),
                    "criteria_results": (
                        template.content.criteria_results[0].model_copy(
                            update={
                                "status": QaCriterionStatus.FAIL,
                                "evidence_ids": (evidence.evidence_id,),
                            }
                        ),
                    ),
                    "findings": (
                        Finding(
                            finding_id="finding_missing_entry",
                            severity=FindingSeverity.MAJOR,
                            code="MISSING_PLANNED_TEST_ENTRY",
                            message="Frozen browser test entry is absent from the candidate tree",
                            file=PATH,
                            evidence_ids=(evidence.evidence_id,),
                        ),
                    ),
                }
            ),
        }
    )
    return request, contract, report


def test_exact_static_qa_fail_is_admissible_without_a_command_claim() -> None:
    request, contract, report = _subject()
    validate_static_qa_missing_entry_output(request, report, contract)


def test_multiple_frozen_rows_for_one_file_preserve_all_affected_criteria() -> None:
    request = _request(AgentRole.QA).model_copy(
        update={"input_artifact_ids": ("art_plan_001", "art_impl_001")}
    )
    rows = tuple(
        PlannedVerificationRequirement(
            id=f"verify_browser_{index}",
            role=AgentRole.QA,
            criterion_ids=(criterion_id,),
            argv=("node", "--test", PATH),
            verification_levels=("e2e",),
            planned_new_files=(PATH,),
        )
        for index, criterion_id in enumerate(("ac_models_01", "ac_other_01"), start=1)
    )
    observation = CandidateTestEntryAbsenceObservation.create(
        task_id=request.task_id,
        task_intent_sha256="a" * 64,
        candidate_revision=request.source_revision,
        plan_artifact_id="art_plan_001",
        plan_artifact_sha256="b" * 64,
        plan_requirements_sha256=role_verification_digest([row.to_wire() for row in rows]),
        implementation_artifact_id="art_impl_001",
        implementation_artifact_sha256="c" * 64,
        missing=tuple(
            MissingPlannedTestEntry(
                requirement=row,
                requirement_sha256=role_verification_digest(row.to_wire()),
                path=PATH,
            )
            for row in rows
        ),
    )
    contract = static_qa_missing_entry_output_contract(
        request,
        observation=observation,
        sealed_no_start_proof_sha256="d" * 64,
        authority_sha256="e" * 64,
        claim_sha256="f" * 64,
    )
    assert len(contract.missing) == 1
    assert contract.missing[0].criterion_ids == ("ac_models_01", "ac_other_01")


def test_exact_missing_pytest_node_reaches_independent_qa_contract() -> None:
    request = _request(AgentRole.QA).model_copy(
        update={"input_artifact_ids": ("art_plan_001", "art_impl_001")}
    )
    path = "tests/learning_collection/test_live_a_to_b.py"
    node = path + "::test_production_a_to_b_live"
    rows = tuple(
        PlannedVerificationRequirement(
            id=f"verify_live_{index}",
            role=AgentRole.QA,
            criterion_ids=(criterion_id,),
            argv=("python", "-m", "pytest", "-q", node),
            verification_levels=("e2e",),
            planned_new_files=(path,),
        )
        for index, criterion_id in enumerate(("ac_models_01", "ac_other_01"), start=1)
    )
    observation = CandidateTestEntryAbsenceObservation.create(
        task_id=request.task_id,
        task_intent_sha256="a" * 64,
        candidate_revision=request.source_revision,
        plan_artifact_id="art_plan_001",
        plan_artifact_sha256="b" * 64,
        plan_requirements_sha256=role_verification_digest([row.to_wire() for row in rows]),
        implementation_artifact_id="art_impl_001",
        implementation_artifact_sha256="c" * 64,
        missing=tuple(
            MissingPlannedTestEntry(
                requirement=row,
                requirement_sha256=role_verification_digest(row.to_wire()),
                path=path,
                node_id=node,
            )
            for row in rows
        ),
    )
    contract = static_qa_missing_entry_output_contract(
        request,
        observation=observation,
        sealed_no_start_proof_sha256="d" * 64,
        authority_sha256="e" * 64,
        claim_sha256="f" * 64,
    )
    assert contract.missing[0].path == path
    assert contract.missing[0].criterion_ids == ("ac_models_01", "ac_other_01")
    assert contract.missing[0].node_ids == (node,)
    contract.model_validate(contract.to_wire())


def test_legacy_static_qa_contract_omits_node_extension() -> None:
    _, contract, _ = _subject()
    assert contract.missing[0].node_ids is None
    assert "node_ids" not in contract.model_dump(mode="json", exclude_none=True)["missing"][0]


@pytest.mark.parametrize(
    "defect",
    [
        "pass",
        "test_claim",
        "missing_criterion",
        "unrelated_finding",
        "proof",
        "extra_evidence",
        "wrong_run",
        "plan_parent",
        "missing_parent",
    ],
)
def test_static_qa_rejects_any_unbound_or_nonfailing_output(defect: str) -> None:
    request, contract, report = _subject()
    content = report.content
    if defect == "pass":
        content = content.model_copy(update={"status": QaReportStatus.PASS})
    elif defect == "test_claim":
        content = content.model_copy(update={"tests_run": make_qa_artifact().content.tests_run})
    elif defect == "missing_criterion":
        content = content.model_copy(
            update={
                "criteria_results": (
                    content.criteria_results[0].model_copy(
                        update={"status": QaCriterionStatus.NOT_TESTED}
                    ),
                )
            }
        )
    elif defect == "unrelated_finding":
        content = content.model_copy(
            update={
                "findings": (content.findings[0].model_copy(update={"file": "src/unrelated.py"}),)
            }
        )
    elif defect == "proof":
        report = report.model_copy(
            update={"evidence": (report.evidence[0].model_copy(update={"sha256": "0" * 64}),)}
        )
    elif defect == "extra_evidence":
        report = report.model_copy(
            update={
                "evidence": (
                    *report.evidence,
                    report.evidence[0].model_copy(update={"evidence_id": "ev_unrelated"}),
                )
            }
        )
    elif defect == "plan_parent":
        report = report.model_copy(update={"parent_artifact_ids": request.input_artifact_ids})
    elif defect == "missing_parent":
        report = report.model_copy(update={"parent_artifact_ids": ()})
    else:
        report = report.model_copy(
            update={"producer": report.producer.model_copy(update={"run_id": "run_other"})}
        )
    report = report.model_copy(update={"content": content})
    with pytest.raises(VerificationOutputRejected):
        validate_static_qa_missing_entry_output(request, report, contract)
