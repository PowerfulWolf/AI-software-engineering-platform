"""Project Manager controller for normal delivery continuation and candidate remediation."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.project_manager.delivery import (
    ProjectDeliveryResult,
    ResumeProjectDelivery,
    UnifiedProjectEntryService,
)
from ai_software_engineer.project_manager.delivery_checkpoint import (
    DeliveryStage,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.project_manager.production_backend import (
    ProductionProjectDeliveryBackend,
)
from ai_software_engineer.recovery.entry import NativeRecoveryEntry
from ai_software_engineer.recovery.models import RecoveryPlan, RecoveryRejected
from ai_software_engineer.recovery.remediation import CandidateRemediationService
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.verification_entry import CandidateVerificationEntry
from ai_software_engineer.recovery.verification_native import (
    NativeCandidateSource,
    NativeCandidateSourceReader,
)
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationCompletion,
    CandidateVerificationPlan,
)


class DeliveryResumeOutcome(StrEnum):
    CONTINUED = "CONTINUED"
    WAITING_HUMAN = "WAITING_HUMAN"
    VERIFICATION_APPROVAL_REQUIRED = "VERIFICATION_APPROVAL_REQUIRED"
    RECOVERY_APPROVAL_REQUIRED = "RECOVERY_APPROVAL_REQUIRED"
    VERIFIED = "VERIFIED"
    RECOVERED = "RECOVERED"
    REMEDIATED = "REMEDIATED"


class DeliveryResumeResult(DomainModel):
    """Small public cursor; detailed facts remain in their authoritative stores."""

    outcome: DeliveryResumeOutcome
    checkpoint: ProjectDeliveryCheckpoint
    next_action: NonEmptyStr
    verification_plan_file: NonEmptyStr | None = None
    verification_plan_sha256: str | None = None
    verification_completion_sha256: str | None = None
    recovery_plan_file: NonEmptyStr | None = None
    recovery_plan_sha256: str | None = None


class DeliveryResumeController:
    """Classify one native Delivery and execute only its next authorized operation."""

    def __init__(
        self,
        *,
        config: ProductionConfig,
        environment: Mapping[str, str],
        backend: ProductionProjectDeliveryBackend,
        entry: UnifiedProjectEntryService,
        recovery: NativeRecoveryEntry,
        verification: CandidateVerificationEntry,
    ) -> None:
        self._config = config
        self._environment = dict(environment)
        self._backend = backend
        self._entry = entry
        self._recovery = recovery
        self._verification = verification

    def resume(self, command: ResumeProjectDelivery) -> DeliveryResumeResult:
        current = self._entry.status(command.delivery_id).checkpoint
        if current.stage not in {DeliveryStage.BLOCKED, DeliveryStage.FAILED}:
            result = self._entry.resume(command)
            outcome = (
                DeliveryResumeOutcome.WAITING_HUMAN
                if result.checkpoint.stage
                in {
                    DeliveryStage.WAITING_PRODUCT_REPLY,
                    DeliveryStage.WAITING_PRODUCT_APPROVAL,
                    DeliveryStage.WAITING_HUMAN,
                }
                else DeliveryResumeOutcome.CONTINUED
            )
            return self._result(
                outcome,
                result,
                next_action=str(result.checkpoint.next_action),
            )
        retried = self._entry.retry_interrupted_stage(command)
        if retried.checkpoint != current:
            outcome = (
                DeliveryResumeOutcome.WAITING_HUMAN
                if retried.checkpoint.stage
                in {
                    DeliveryStage.WAITING_PRODUCT_REPLY,
                    DeliveryStage.WAITING_PRODUCT_APPROVAL,
                    DeliveryStage.WAITING_HUMAN,
                    DeliveryStage.BLOCKED,
                    DeliveryStage.FAILED,
                }
                else DeliveryResumeOutcome.CONTINUED
            )
            return self._result(
                outcome,
                retried,
                next_action=str(retried.checkpoint.next_action),
            )
        if current.task_id is None:
            return self._result(
                DeliveryResumeOutcome.WAITING_HUMAN,
                ProjectDeliveryResult(checkpoint=current),
                next_action=(
                    "No verified candidate is available for automatic continuation; inspect the "
                    "terminal Task and use explicit recovery if it contains uncommitted Coder work."
                ),
            )
        if current.candidate_revision is None:
            return self._continue_coder_recovery(current, command)

        latest = self._verification.latest_project(
            project_root=current.project_root,
            delivery_id=current.delivery_id,
        )
        if latest is None:
            plan, path = self._verification.propose_project(
                project_root=current.project_root,
                delivery_id=current.delivery_id,
            )
            return self._approval_required(current, plan, path)
        store, plan, path = latest
        try:
            authorization = store.get_verification_authorization(plan.plan_sha256)
        except RecoveryRecordMissing:
            authorization = None
        if command.approved_plan_sha256 is not None:
            if command.approved_plan_sha256 != plan.plan_sha256:
                return self._approval_required(current, plan, path)
            assert command.approval_reference is not None
            self._verification.approve(
                path,
                confirmed_plan=command.approved_plan_sha256,
                reference=command.approval_reference,
            )
            authorization = store.get_verification_authorization(plan.plan_sha256)
        if authorization is None or not authorization.decision.approved:
            return self._approval_required(current, plan, path)

        try:
            completion = store.get_verification_completion(plan.plan_sha256)
        except RecoveryRecordMissing:
            completion = None
        if completion is None and self._has_admitted_invocation(store, plan):
            successor, successor_path = self._verification.propose_project(
                project_root=current.project_root,
                delivery_id=current.delivery_id,
            )
            return self._approval_required(current, successor, successor_path)
        if completion is None:
            completion = self._verification.execute(path)
        return self._continue_completion(plan, completion)

    def _continue_completion(
        self,
        plan: CandidateVerificationPlan,
        completion: CandidateVerificationCompletion,
    ) -> DeliveryResumeResult:
        if completion.verified:
            result = self._entry.accept_verification(plan, completion)
            return self._result(
                DeliveryResumeOutcome.VERIFIED,
                result,
                next_action="Candidate passed independent QA and Review; delivery is complete.",
                completion=completion,
            )
        source = self._verification.latest_project(
            project_root=plan.scope.project_root,
            delivery_id=plan.scope.delivery_id,
        )
        if source is None or source[1] != plan:
            raise ValueError("verification completion is no longer the current candidate result")
        store = source[0]
        native = CandidateRemediationService(
            backend=self._backend,
            config=self._config,
            environment=self._environment,
        ).prepare(source=self._native_source(plan), store=store, plan=plan, completion=completion)
        started = self._entry.begin_continuation(native.dispatch, at=completion.completed_at)
        if started.checkpoint.stage is not DeliveryStage.DELIVERING:
            return self._result(
                DeliveryResumeOutcome.CONTINUED,
                started,
                next_action=str(started.checkpoint.next_action),
                completion=completion,
            )
        delivered = self._backend.run_prepared_allocation(
            native.dispatch,
            native.preparation,
            native.source.stages.product,
            native.source.stages.design,
            native.source.stages.plan,
            extra_context=native.context_sources,
        )
        result = self._entry.finish_continuation(
            native.dispatch,
            delivered,
            at=delivered.task.updated_at,
        )
        return self._result(
            DeliveryResumeOutcome.REMEDIATED,
            result,
            next_action=str(result.checkpoint.next_action),
            completion=completion,
        )

    def _continue_coder_recovery(
        self,
        current: ProjectDeliveryCheckpoint,
        command: ResumeProjectDelivery,
    ) -> DeliveryResumeResult:
        try:
            latest = self._recovery.latest_delivery(current)
            if latest is None:
                plan, path = self._recovery.propose_delivery(current)
                return self._recovery_approval_required(current, plan, path)
        except RecoveryRejected as error:
            return self._recovery_human_gate(current, str(error))
        store, plan, path = latest
        authorization = store.find_authorization(plan.plan_sha256)
        if command.approved_plan_sha256 is not None:
            if command.approved_plan_sha256 != plan.plan_sha256:
                return self._recovery_approval_required(current, plan, path)
            assert command.approval_reference is not None
            self._recovery.approve(
                path,
                confirmed_plan=command.approved_plan_sha256,
                reference=command.approval_reference,
            )
            authorization = store.get_authorization(plan.plan_sha256)
        if authorization is None or not authorization.decision.approved:
            return self._recovery_approval_required(current, plan, path)
        try:
            execution = self._recovery.resume_execution(path)
        except RecoveryRejected as error:
            return self._recovery_human_gate(current, str(error))
        started = self._entry.begin_recovery(
            execution.plan,
            execution.dispatch,
            at=execution.dispatch.committed_at,
        )
        if started.checkpoint.stage is not DeliveryStage.DELIVERING:
            return self._result(
                DeliveryResumeOutcome.CONTINUED,
                started,
                next_action=str(started.checkpoint.next_action),
            )
        result = self._entry.finish_recovery(
            execution.plan,
            execution.dispatch,
            execution.delivery,
            at=execution.delivery.task.updated_at,
        )
        return self._result(
            DeliveryResumeOutcome.RECOVERED,
            result,
            next_action=str(result.checkpoint.next_action),
        )

    @staticmethod
    def _recovery_human_gate(
        checkpoint: ProjectDeliveryCheckpoint, reason: str
    ) -> DeliveryResumeResult:
        return DeliveryResumeResult(
            outcome=DeliveryResumeOutcome.WAITING_HUMAN,
            checkpoint=checkpoint,
            next_action=f"Coder recovery stopped safely: {reason}",
        )

    @staticmethod
    def _recovery_approval_required(
        checkpoint: ProjectDeliveryCheckpoint,
        plan: RecoveryPlan,
        path: Path,
    ) -> DeliveryResumeResult:
        return DeliveryResumeResult(
            outcome=DeliveryResumeOutcome.RECOVERY_APPROVAL_REQUIRED,
            checkpoint=checkpoint,
            next_action=(
                "Inspect the captured Coder changes, then rerun request resume with this exact "
                "plan digest and an approval reference."
            ),
            recovery_plan_file=str(path),
            recovery_plan_sha256=plan.plan_sha256,
        )

    def _native_source(self, plan: CandidateVerificationPlan) -> NativeCandidateSource:
        return NativeCandidateSourceReader(self._config, self._environment).inspect(plan.scope)

    @staticmethod
    def _has_admitted_invocation(store: FileRecoveryStore, plan: CandidateVerificationPlan) -> bool:
        for role in (AgentRole.QA, AgentRole.REVIEWER):
            try:
                store.get_verification_invocation(plan.plan_sha256, role)
            except RecoveryRecordMissing:
                continue
            return True
        return False

    @staticmethod
    def _approval_required(
        current: ProjectDeliveryCheckpoint,
        plan: CandidateVerificationPlan,
        path: Path,
    ) -> DeliveryResumeResult:
        return DeliveryResumeResult(
            outcome=DeliveryResumeOutcome.VERIFICATION_APPROVAL_REQUIRED,
            checkpoint=current,
            next_action=(
                "Approve the exact verification plan, then resume: "
                f"ase request resume {current.delivery_id} --approve-plan {plan.plan_sha256}"
            ),
            verification_plan_file=str(path),
            verification_plan_sha256=plan.plan_sha256,
        )

    @staticmethod
    def _result(
        outcome: DeliveryResumeOutcome,
        result: ProjectDeliveryResult,
        *,
        next_action: str,
        completion: CandidateVerificationCompletion | None = None,
    ) -> DeliveryResumeResult:
        return DeliveryResumeResult(
            outcome=outcome,
            checkpoint=result.checkpoint,
            next_action=next_action,
            verification_completion_sha256=(
                completion.completion_sha256 if completion is not None else None
            ),
        )


__all__ = [
    "DeliveryResumeController",
    "DeliveryResumeOutcome",
    "DeliveryResumeResult",
]
