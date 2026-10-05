"""Narrow correction of a published design rejected before native work existed."""

from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryStage,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.multi_directory.admission import (
    JointDesignVerificationRejected,
    require_native_verification_contract,
)
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage
from ai_software_engineer.multi_directory.scope import Digest


class UnstartedDesignCorrectionRejected(ValueError):
    """A missing native proof must never become general INVALID_OUTPUT retry."""


class UnstartedDesignCorrectionProof(DomainModel):
    checkpoint_sha256: Digest
    design_sha256: Digest
    native_run_sha256s: tuple[Digest, ...]


def native_work_absent(checkpoint: ProjectDeliveryCheckpoint) -> bool:
    return all(
        getattr(checkpoint, field) is None
        for field in (
            "technical_design_id",
            "technical_design_sha256",
            "execution_plan_id",
            "execution_plan_sha256",
            "planning_preview_id",
            "planning_preview_sha256",
            "dispatch_commit_id",
            "dispatch_commit_sha256",
            "task_id",
            "task_revision",
            "task_status",
            "candidate_revision",
            "verification_plan_sha256",
            "verification_completion_sha256",
        )
    )


def unstarted_design_rejection(
    checkpoint: JointCheckpoint,
) -> JointDesignVerificationRejected | None:
    """Structural read-side eligibility only; production separately proves all history."""
    if (
        checkpoint.stage is not JointStage.BLOCKED
        or checkpoint.product_spec is None
        or checkpoint.approval is None
        or checkpoint.design is None
        or checkpoint.plan is None
        or not checkpoint.children
        or checkpoint.integration is not None
        or checkpoint.integration_retry_approval is not None
        or checkpoint.single_repository_acceptance is not None
        or checkpoint.knowledge_gap_id is not None
        or checkpoint.knowledge_wait_stage is not None
        or any(
            child.checkpoint.stage is not DeliveryStage.BLOCKED
            or child.checkpoint.failed_stage is not DeliveryStage.DESIGNING
            or child.checkpoint.failure_code is not DeliveryFailureCode.INVALID_AGENT_OUTPUT
            or not native_work_absent(child.checkpoint)
            for child in checkpoint.children
        )
    ):
        return None
    try:
        require_native_verification_contract(checkpoint.design)
    except JointDesignVerificationRejected as error:
        if all(failure.code == "INSPECTION_LEVELS" for failure in error.failures):
            return error
    return None


def validate_unstarted_design_successor(previous: JointCheckpoint, item: JointCheckpoint) -> bool:
    if previous.design is None or item.design == previous.design:
        return False
    rejection = unstarted_design_rejection(previous)
    if rejection is None:
        return False
    if (
        item.stage is not JointStage.DESIGNING
        or item.design is not None
        or item.design_feedback != previous.design
        or item.plan is not None
        or item.planning_decision is not None
        or item.planning_upgrade is not None
        or item.planning_feedback is not None
        or item.children
        or item.attempts != previous.attempts
        or item.preparations != previous.preparations
        or item.dialogue != previous.dialogue
        or item.integration != previous.integration
        or item.integration_retry_approval != previous.integration_retry_approval
        or item.single_repository_acceptance != previous.single_repository_acceptance
        or item.knowledge_gap_id != previous.knowledge_gap_id
        or item.knowledge_wait_stage != previous.knowledge_wait_stage
        or item.knowledge_rechecks != previous.knowledge_rechecks
        or str(rejection) not in item.next_action
    ):
        raise UnstartedDesignCorrectionRejected(
            "设计修正必须保留原产物与预算, 且不得保留旧计划或执行任务。"
        )
    return True
