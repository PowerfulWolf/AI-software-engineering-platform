"""QA execution failures must not be mistaken for candidate defects."""

from ai_software_engineer.domain import QaCriterionStatus, QaReportStatus, QaTestStatus
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationCompletion,
    CandidateVerificationDisposition,
)
from tests.domain.factories import make_qa_artifact


def _completion(
    *, criterion: QaCriterionStatus, test: QaTestStatus
) -> CandidateVerificationCompletion:
    qa = make_qa_artifact()
    qa = qa.model_copy(
        update={
            "content": qa.content.model_copy(
                update={
                    "status": QaReportStatus.FAIL,
                    "criteria_results": (
                        qa.content.criteria_results[0].model_copy(update={"status": criterion}),
                    ),
                    "tests_run": (qa.content.tests_run[0].model_copy(update={"status": test}),),
                }
            )
        }
    )
    return CandidateVerificationCompletion.create(
        plan_sha256="a" * 64,
        authorization_sha256="b" * 64,
        qa_invocation_sha256="c" * 64,
        qa=qa,
        completed_at=qa.created_at,
    )


def test_inconclusive_qa_requires_fresh_verification_not_coder() -> None:
    completion = _completion(
        criterion=QaCriterionStatus.NOT_TESTED,
        test=QaTestStatus.ERROR,
    )

    assert completion.disposition is CandidateVerificationDisposition.RETRY_VERIFICATION


def test_candidate_failure_still_requires_coder_remediation() -> None:
    criterion_failure = _completion(
        criterion=QaCriterionStatus.FAIL,
        test=QaTestStatus.ERROR,
    )
    test_failure = _completion(
        criterion=QaCriterionStatus.NOT_TESTED,
        test=QaTestStatus.FAIL,
    )

    assert criterion_failure.disposition is CandidateVerificationDisposition.REMEDIATE_CANDIDATE
    assert test_failure.disposition is CandidateVerificationDisposition.REMEDIATE_CANDIDATE
