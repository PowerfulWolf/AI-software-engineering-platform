"""Select only the latest interrupted verification's admitted, sealed QA PASS."""

from ai_software_engineer.artifacts import ArtifactStore
from ai_software_engineer.domain.artifact import (
    PlanArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
)
from ai_software_engineer.domain.enums import AgentRole, QaReportStatus
from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationInputs,
    CandidateVerificationPlan,
    RetainedVerificationQa,
)


def select_retained_qa(
    store: FileRecoveryStore,
    inputs: CandidateVerificationInputs,
    artifacts: ArtifactStore,
    *,
    excluding: str | None = None,
) -> tuple[CandidateVerificationPlan, RetainedVerificationQa] | None:
    if inputs.accepted_qa is not None:
        return None
    source = store.latest_verification_attempt(inputs.task_id, excluding=excluding)
    if (
        source is None
        or source.inputs.model_copy(update={"prior_run_ids": inputs.prior_run_ids}) != inputs
    ):
        return None
    try:
        store.get_verification_completion(source.plan_sha256)
    except RecoveryRecordMissing:
        pass
    else:
        return None
    try:
        reviewer = store.get_verification_invocation(source.plan_sha256, AgentRole.REVIEWER)
    except RecoveryRecordMissing:
        reviewer = None
    history = artifacts.list_for_task(inputs.task_id)
    # Even an as-yet uncompleted Review REJECT/APPROVE must be handled, not hidden by reuse.
    if reviewer is not None and any(
        isinstance(item, ReviewReportArtifact) and item.producer.run_id == reviewer.request.run_id
        for item in history
    ):
        return None
    if source.retained_qa is not None:
        qa = artifacts.get(source.retained_qa.qa.artifact_id)
    else:
        invocation = store.get_verification_invocation(source.plan_sha256, AgentRole.QA)
        reports = tuple(
            item
            for item in history
            if isinstance(item, QaReportArtifact)
            and item.producer.run_id == invocation.request.run_id
        )
        if len(reports) != 1:
            return None
        qa = reports[0]
    if not isinstance(qa, QaReportArtifact) or qa.content.status is not QaReportStatus.PASS:
        return None
    if reviewer is not None and reviewer.request.input_artifact_ids[-1] != qa.artifact_id:
        raise RecoveryRejected("interrupted Reviewer did not consume the admitted QA")
    if source.retained_qa is not None:
        if source.retained_qa.qa != qa:
            raise RecoveryRejected("interrupted Reviewer changed the retained QA")
        return source, source.retained_qa
    invocation = store.get_verification_invocation(source.plan_sha256, AgentRole.QA)
    return source, RetainedVerificationQa(
        plan_sha256=source.plan_sha256,
        qa_invocation_sha256=invocation.invocation_sha256,
        reviewer_invocation_sha256=reviewer.invocation_sha256 if reviewer is not None else None,
        qa=qa,
    )


def validate_retained_qa_artifacts(
    store: FileRecoveryStore, plan: CandidateVerificationPlan, artifacts: ArtifactStore
) -> QaReportArtifact | None:
    ref = plan.retained_qa
    if ref is None:
        return None
    store.validate_retained_qa(plan)
    latest = select_retained_qa(store, plan.inputs, artifacts, excluding=plan.plan_sha256)
    if latest is None or latest[1] != ref or artifacts.get(ref.qa.artifact_id) != ref.qa:
        raise RecoveryRejected("retained QA is no longer the latest interrupted verification")
    original = artifacts.get(plan.inputs.plan_id)
    # Required coverage is independently rechecked by the runner against the immutable Task.
    if not isinstance(original, PlanArtifact) or {
        c.criterion_id for c in ref.qa.content.criteria_results
    } != {c.criterion_id for c in original.content.acceptance_mapping}:
        raise RecoveryRejected("retained QA does not cover the approved criteria")
    return ref.qa
