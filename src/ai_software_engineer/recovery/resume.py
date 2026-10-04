"""Manager controller for normal delivery continuation and candidate remediation."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import model_validator

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain import AgentRole, QaCriterionStatus, QaTestStatus, TaskStatus
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.prerequisite_repair import PrerequisiteRepairPlan
from ai_software_engineer.knowledge.gaps import KnowledgeGap
from ai_software_engineer.manager.delivery import (
    ProjectDeliveryResult,
    ResumeProjectDelivery,
    UnifiedProjectEntryService,
)
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryStage,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.production_backend import (
    ProductionProjectDeliveryBackend,
)
from ai_software_engineer.manager.python_verification import PythonMysqlSandboxCapability
from ai_software_engineer.manager.verification_coordination import ManagerVerificationAdvice
from ai_software_engineer.multi_directory.models import JointDeliveryResult, JointStage
from ai_software_engineer.recovery.context import approved_parent_context
from ai_software_engineer.recovery.entry import (
    NativeRecoveryEntry,
    NativeRecoveryExecution,
    read_recovery_task,
)
from ai_software_engineer.recovery.interruption import RecoveryInterruptionService
from ai_software_engineer.recovery.interruption_records import RecoveryInterruptionPlan
from ai_software_engineer.recovery.models import (
    RecoveryApprovalCommand,
    RecoveryAuthorization,
    RecoveryPlan,
    RecoveryRejected,
    RecoveryScope,
    RecoveryScopeRequest,
    RecoveryScopeSupplement,
    VerificationExecutionBlocked,
    VerifiedRecoveryDecision,
)
from ai_software_engineer.recovery.remediation import CandidateRemediationService
from ai_software_engineer.recovery.restart_records import PreExecutionRestartPlan
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.verification_entry import CandidateVerificationEntry
from ai_software_engineer.recovery.verification_native import (
    NativeCandidateSource,
    NativeCandidateSourceReader,
)
from ai_software_engineer.recovery.verification_records import (
    CandidateExecutorPrerequisite,
    CandidateRemediationEvidence,
    CandidateVerificationCompletion,
    CandidateVerificationDisposition,
    CandidateVerificationPlan,
)


class DeliveryResumeOutcome(StrEnum):
    CONTINUED = "CONTINUED"
    WAITING_HUMAN = "WAITING_HUMAN"
    VERIFICATION_APPROVAL_REQUIRED = "VERIFICATION_APPROVAL_REQUIRED"
    RECOVERY_APPROVAL_REQUIRED = "RECOVERY_APPROVAL_REQUIRED"
    RESTART_APPROVAL_REQUIRED = "RESTART_APPROVAL_REQUIRED"
    SCOPE_APPROVAL_REQUIRED = "SCOPE_APPROVAL_REQUIRED"
    REPAIR_APPROVAL_REQUIRED = "REPAIR_APPROVAL_REQUIRED"
    VERIFIED = "VERIFIED"
    RECOVERED = "RECOVERED"
    REMEDIATED = "REMEDIATED"


class DeliveryResumeResult(DomainModel):
    """Small public cursor; detailed facts remain in their authoritative stores."""

    outcome: DeliveryResumeOutcome
    checkpoint: ProjectDeliveryCheckpoint
    next_action: NonEmptyStr
    diagnostic: NonEmptyStr | None = None
    verification_plan_file: NonEmptyStr | None = None
    verification_plan_sha256: str | None = None
    verification_completion_sha256: str | None = None
    recovery_plan_file: NonEmptyStr | None = None
    recovery_plan_sha256: str | None = None
    scope_supplement_sha256: str | None = None
    scope_supplement_paths: tuple[NonEmptyStr, ...] = ()
    coder_scope_request: RecoveryScopeRequest | None = None
    prerequisite_repair_plan: PrerequisiteRepairPlan | None = None
    restart_plan: PreExecutionRestartPlan | None = None
    interruption_plan: RecoveryInterruptionPlan | None = None


class JointDeliveryResumeResult(JointDeliveryResult):
    """A refreshed parent cursor together with its exact native human gate."""

    continuation: DeliveryResumeResult

    @model_validator(mode="after")
    def require_current_child(self) -> Self:
        if (
            self.checkpoint.stage is not JointStage.BLOCKED
            or self.integration_retry_proposal is not None
            or not any(
                child.checkpoint == self.continuation.checkpoint
                for child in self.checkpoint.children
            )
        ):
            raise ValueError("joint continuation does not match the refreshed child checkpoint")
        return self


def _checkpoint_next_action(checkpoint: ProjectDeliveryCheckpoint) -> str:
    if (
        checkpoint.stage in {DeliveryStage.BLOCKED, DeliveryStage.FAILED}
        and checkpoint.failure_summary is not None
    ):
        return checkpoint.failure_summary
    return str(checkpoint.next_action)


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
        status = self._entry.status(command.delivery_id)
        current = status.checkpoint
        diagnostic = getattr(status, "diagnostic", None)
        # A preparation mismatch is a read-side fact, not permission to replay
        # the old cursor.  A sealed candidate is the one deliberate exception:
        # its QA/Review verification can still be proposed or consumed against
        # the current baseline, as required by delivery-recovery.
        has_candidate_boundary = (
            current.task_id is not None and current.candidate_revision is not None
        )
        if diagnostic and not has_candidate_boundary:
            # A materialized NEW Task with no role execution is safe to rebind to
            # the current preparation through the exact pre-execution approval
            # seam.  Other drift remains read-only and must not be replayed.
            if (
                current.stage is DeliveryStage.DELIVERING
                and current.task_status is TaskStatus.NEW
                and current.task_revision == 0
                and current.candidate_revision is None
                and current.failure_code is None
                and current.failed_stage is None
            ):
                restart = self._continue_pre_execution_restart(current, command)
                if restart is not None:
                    return restart
            return self._result(
                DeliveryResumeOutcome.WAITING_HUMAN,
                status,
                next_action=diagnostic,
            )
        if command.coder_scope_request is not None and (
            current.stage not in {DeliveryStage.BLOCKED, DeliveryStage.FAILED}
            or current.candidate_revision is not None
            or current.task_id is None
        ):
            raise RecoveryRejected("requested Coder scope requires terminal pre-candidate recovery")
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
                next_action=_checkpoint_next_action(result.checkpoint),
            )

        # A terminal candidate is already a sealed implementation boundary. Its
        # next operation is independent QA/Review verification, even when the
        # Delivery checkpoint still points at an older preparation digest. The
        # old native retry path re-runs that stale preparation gate and can make
        # a fresh verification plan unreachable after a harmless baseline drift.
        # Keep the latest plan in hand so the normal approval/execution handling
        # below can continue without retrying the old stage.
        latest: tuple[FileRecoveryStore, CandidateVerificationPlan, Path] | None = None
        terminal_candidate = (
            current.task_id is not None
            and current.candidate_revision is not None
            and current.task_status in {TaskStatus.BLOCKED, TaskStatus.FAILED}
        )
        if terminal_candidate:
            latest = self._verification.latest_project(
                repository_root=current.repository_root,
                delivery_id=current.delivery_id,
            )
            if latest is not None:
                verification_store, verification_plan, _ = latest
                try:
                    completion = verification_store.get_verification_completion(
                        verification_plan.plan_sha256
                    )
                except RecoveryRecordMissing:
                    completion = None
                if completion is not None:
                    return self._continue_completion(verification_plan, completion)

        if not terminal_candidate:
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
                    next_action=_checkpoint_next_action(retried.checkpoint),
                )
        if current.task_id is None:
            return self._result(
                DeliveryResumeOutcome.WAITING_HUMAN,
                ProjectDeliveryResult(checkpoint=current),
                next_action=(
                    "当前没有可自动继续的路径；请检查终态 Task，"  # noqa: RUF001
                    "如有未提交的 Coder 改动则使用明确的恢复流程。"
                ),
            )
        if current.candidate_revision is None:
            restart = (
                self._continue_pre_execution_restart(current, command)
                if command.coder_scope_request is None
                else None
            )
            if restart is not None:
                return restart
            try:
                NativeCandidateSourceReader(self._config, self._environment).inspect(
                    RecoveryScope(
                        team_id=self._config.team_id,
                        repository_id=current.repository_id,
                        repository_root=current.repository_root,
                        delivery_id=current.delivery_id,
                    )
                )
            except RecoveryRejected:
                return self._continue_coder_recovery(current, command)

        if command.coder_scope_request is not None:
            raise RecoveryRejected("requested Coder scope requires terminal pre-candidate recovery")

        if latest is None and not terminal_candidate:
            latest = self._verification.latest_project(
                repository_root=current.repository_root,
                delivery_id=current.delivery_id,
            )
        if command.python_mysql_tests is not None:
            if (
                latest is not None
                and isinstance(latest[1].executor_capability, PythonMysqlSandboxCapability)
                and latest[1].executor_capability.selections == command.python_mysql_tests
                and not self._has_admitted_invocation(latest[0], latest[1])
            ):
                return self._approval_required(current, latest[1], latest[2])
            python_plan, python_path = self._verification.propose_project(
                repository_root=current.repository_root,
                delivery_id=current.delivery_id,
                python_mysql_tests=command.python_mysql_tests,
            )
            return self._approval_required(current, python_plan, python_path)
        if command.native_ui_scenario is not None:
            from ai_software_engineer.manager.native_ui import native_ui_capability

            expected_ui = native_ui_capability(command.native_ui_scenario)
            if (
                latest is not None
                and latest[1].native_ui == expected_ui
                and not self._has_admitted_invocation(latest[0], latest[1])
            ):
                return self._approval_required(current, latest[1], latest[2])
            ui_plan, ui_path = self._verification.propose_project(
                repository_root=current.repository_root,
                delivery_id=current.delivery_id,
                native_ui_scenario=command.native_ui_scenario,
            )
            return self._approval_required(current, ui_plan, ui_path)
        if latest is None:
            plan, path = self._verification.propose_project(
                repository_root=current.repository_root,
                delivery_id=current.delivery_id,
            )
            return self._coordinate_prerequisites(current, plan) or self._approval_required(
                current, plan, path
            )
        store, plan, path = latest
        if command.prerequisite_repair is not None or command.approved_repair_sha256 is not None:
            return self._continue_prerequisite_repair(current, command, store, plan)
        coordinated = (
            None
            if self._has_admitted_invocation(store, plan)
            or isinstance(plan.executor_capability, PythonMysqlSandboxCapability)
            else self._coordinate_prerequisites(current, plan)
        )
        if coordinated is not None:
            return coordinated
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
            coordinated = (
                None
                if isinstance(plan.executor_capability, PythonMysqlSandboxCapability)
                else self._coordinate_prerequisites(current, plan)
            )
            if coordinated is not None:
                return coordinated
            successor, successor_path = self._verification.propose_project(
                repository_root=current.repository_root,
                delivery_id=current.delivery_id,
                native_ui_scenario=plan.native_ui.scenario if plan.native_ui else None,
                python_mysql_tests=plan.executor_capability.selections
                if isinstance(plan.executor_capability, PythonMysqlSandboxCapability)
                else None,
                manager_advice=plan.manager_advice,
            )
            return self._approval_required(current, successor, successor_path)
        if completion is None:
            try:
                completion = self._verification.execute(path)
            except VerificationExecutionBlocked as error:
                return self._coordinate_prerequisites(current, plan) or DeliveryResumeResult(
                    outcome=DeliveryResumeOutcome.WAITING_HUMAN,
                    checkpoint=current,
                    next_action=error.next_action,
                )
        return self._continue_completion(plan, completion)

    def _coordinate_prerequisites(
        self, current: ProjectDeliveryCheckpoint, plan: CandidateVerificationPlan
    ) -> DeliveryResumeResult | None:
        if isinstance(plan.executor_capability, PythonMysqlSandboxCapability):
            return None
        advice = self._verification.coordinate(plan)
        if advice is None:
            return None
        if advice.draft.prerequisite_repair is not None:
            latest = self._verification.latest_project(
                repository_root=current.repository_root,
                delivery_id=current.delivery_id,
            )
            if latest is None or latest[1] != plan:
                raise RecoveryRejected("Manager repair source is no longer current")
            return self._continue_prerequisite_repair(
                current,
                ResumeProjectDelivery(
                    delivery_id=current.delivery_id,
                    prerequisite_repair=advice.draft.prerequisite_repair,
                ),
                latest[0],
                plan,
                manager_advice=advice,
            )
        if advice.draft.native_ui_scenario is None:
            return DeliveryResumeResult(
                outcome=DeliveryResumeOutcome.WAITING_HUMAN,
                checkpoint=current,
                next_action=(
                    f"Manager: {advice.environment_prerequisite.next_action}"
                    if advice.environment_prerequisite is not None
                    and not advice.environment_prerequisite.ready
                    else f"Manager: {advice.draft.summary}\n{advice.draft.next_action}"
                ),
            )
        coordinated_plan, coordinated_path = self._verification.propose_project(
            repository_root=current.repository_root,
            delivery_id=current.delivery_id,
            native_ui_scenario=advice.draft.native_ui_scenario,
            manager_advice=advice,
        )
        return self._approval_required(current, coordinated_plan, coordinated_path)

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
            repository_root=plan.scope.repository_root,
            delivery_id=plan.scope.delivery_id,
        )
        if source is None or source[1] != plan:
            raise ValueError("verification completion is no longer the current candidate result")
        if completion.disposition is CandidateVerificationDisposition.RETRY_VERIFICATION:
            source[0].record_verification_incident(completion)
            current = self._entry.status(plan.scope.delivery_id).checkpoint
            successor, path = self._verification.propose_project(
                repository_root=plan.scope.repository_root,
                delivery_id=plan.scope.delivery_id,
                native_ui_scenario=plan.native_ui.scenario if plan.native_ui else None,
                python_mysql_tests=plan.executor_capability.selections
                if isinstance(plan.executor_capability, PythonMysqlSandboxCapability)
                else None,
                manager_advice=plan.manager_advice,
            )
            if successor.inputs.candidate_revision != plan.inputs.candidate_revision:
                raise ValueError("successor verification changed the retained candidate")
            return self._coordinate_prerequisites(current, successor) or self._approval_required(
                current, successor, path, completion=completion
            )
        store = source[0]
        return self._run_remediation(plan, completion, store)

    def _run_remediation(
        self,
        plan: CandidateVerificationPlan,
        completion: CandidateRemediationEvidence,
        store: FileRecoveryStore,
        repair_plan: PrerequisiteRepairPlan | None = None,
    ) -> DeliveryResumeResult:
        remediation_backend = self._verification.backend
        native = CandidateRemediationService(
            backend=remediation_backend,
            config=self._config,
            environment=self._environment,
        ).prepare(
            source=self._native_source(plan),
            store=store,
            plan=plan,
            completion=completion,
            **({"repair_plan": repair_plan} if repair_plan is not None else {}),
        )
        started = self._entry.begin_continuation(
            native.dispatch,
            plan,
            completion,
            at=native.dispatch.committed_at,
            **({"repair_plan": repair_plan} if repair_plan is not None else {}),
        )
        if started.checkpoint.stage is not DeliveryStage.DELIVERING:
            return self._result(
                DeliveryResumeOutcome.CONTINUED,
                started,
                next_action=_checkpoint_next_action(started.checkpoint),
                completion=completion
                if isinstance(completion, CandidateVerificationCompletion)
                else None,
            )
        delivered = remediation_backend.run_prepared_allocation(
            native.dispatch,
            native.preparation,
            native.source.stages.product,
            native.source.stages.design,
            native.source.stages.plan,
            extra_context=(
                *approved_parent_context(
                    self._config, plan.scope, plan.parent_delivery_id, plan.parent_checkpoint_sha256
                ),
                *native.context_sources,
            ),
        )
        result = self._entry.finish_continuation(
            native.dispatch,
            delivered,
            at=delivered.task.updated_at,
        )
        return self._result(
            DeliveryResumeOutcome.REMEDIATED,
            result,
            next_action=_checkpoint_next_action(result.checkpoint),
            completion=completion
            if isinstance(completion, CandidateVerificationCompletion)
            else None,
        )

    def _continue_prerequisite_repair(
        self,
        current: ProjectDeliveryCheckpoint,
        command: ResumeProjectDelivery,
        store: FileRecoveryStore,
        latest: CandidateVerificationPlan,
        *,
        manager_advice: ManagerVerificationAdvice | None = None,
    ) -> DeliveryResumeResult:
        with store.execution_lock():
            return self._locked_prerequisite_repair(current, command, store, latest, manager_advice)

    def _locked_prerequisite_repair(
        self,
        current: ProjectDeliveryCheckpoint,
        command: ResumeProjectDelivery,
        store: FileRecoveryStore,
        latest: CandidateVerificationPlan,
        manager_advice: ManagerVerificationAdvice | None = None,
    ) -> DeliveryResumeResult:
        # Only the latest sealed inconclusive result is eligible. A pending verification
        # plan may reference it, but its verification approval cannot authorize Coder.
        completion: CandidateRemediationEvidence
        incident_sha256: str | None = None
        failed = store.latest_verification_execution(latest)
        if failed is not None and failed.phase == "BLOCKED":
            source_plan = store.get_verification_plan(failed.plan_sha256)
            completion = store.record_executor_prerequisite(failed)
        elif latest.prerequisite_incident_sha256 is not None:
            incident = store.get_verification_incident(latest.prerequisite_incident_sha256)
            source_plan = store.get_verification_plan(incident.source_plan_sha256)
            completion = store.get_verification_completion(source_plan.plan_sha256)
            incident_sha256 = incident.incident_sha256
        else:
            source_plan = latest
            completion = store.get_verification_completion(source_plan.plan_sha256)
            incident = store.record_verification_incident(completion)
            incident_sha256 = incident.incident_sha256
        source = self._native_source(source_plan)
        prepared = self._verification.backend.prepare(current.repository_root).preparation
        if prepared is None:
            raise RecoveryRejected("repair requires a valid current project preparation")
        target_base = self._verification.backend.delivery_base_revision(
            Path(current.repository_root)
        )
        if command.prerequisite_repair is not None:
            repair = PrerequisiteRepairPlan(
                repository_root=current.repository_root,
                delivery_id=current.delivery_id,
                source_task_id=source.inputs.task_id,
                source_plan_sha256=source_plan.plan_sha256,
                completion_sha256=completion.completion_sha256
                if isinstance(completion, CandidateVerificationCompletion)
                else None,
                incident_sha256=incident_sha256,
                executor_prerequisite_sha256=completion.observation_sha256
                if isinstance(completion, CandidateExecutorPrerequisite)
                else None,
                manager_advice_input_sha256=manager_advice.input_sha256 if manager_advice else None,
                native_checkpoint_sha256=current.checkpoint_sha256,
                candidate_revision=source_plan.inputs.candidate_revision,
                target_base_revision=target_base,
                target_preparation_sha256=prepared.preparation_sha256,
                request=command.prerequisite_repair,
                created_at=completion.evidence_at,
                plan_sha256="0" * 64,
            )
            repair = store.put_repair_plan(
                repair.model_copy(update={"plan_sha256": repair.recompute_sha256()})
            )
            return DeliveryResumeResult(
                outcome=DeliveryResumeOutcome.REPAIR_APPROVAL_REQUIRED,
                checkpoint=current,
                prerequisite_repair_plan=repair,
                next_action=(
                    "Manager 已提出源码前提修复计划。请审核目标和精确文件范围; "
                    "批准后由 ASE Coder 实施, 新候选仍须独立 QA/Reviewer。"
                ),
            )
        assert command.approved_repair_sha256 is not None
        assert command.approval_reference is not None
        repair = store.get_repair_plan(command.approved_repair_sha256)
        if (
            repair.source_plan_sha256 != source_plan.plan_sha256
            or repair.source_evidence_sha256 != completion.evidence_sha256
            or repair.native_checkpoint_sha256 != current.checkpoint_sha256
            or repair.target_preparation_sha256 != prepared.preparation_sha256
            or repair.target_base_revision != target_base
            or repair.source_task_id != source.inputs.task_id
        ):
            raise RecoveryRejected(
                "repair source or target changed; a new exact proposal is required"
            )
        try:
            authorization = store.get_repair_authorization(repair.plan_sha256)
        except RecoveryRecordMissing:
            approval = RecoveryApprovalCommand(
                operation_id=f"repair_{repair.plan_sha256}",
                plan_sha256=repair.plan_sha256,
                approval_reference=command.approval_reference,
                submitted_at=command.submitted_at,
            )
            authorization = store.put_repair_authorization(
                RecoveryAuthorization.create(
                    approval,
                    VerifiedRecoveryDecision(
                        plan_sha256=repair.plan_sha256,
                        approval_reference=command.approval_reference,
                        approved=True,
                        operator_id="console-operator",
                        rationale="Approved source-changing prerequisite repair, not a QA verdict",
                        decided_at=command.submitted_at,
                    ),
                )
            )
        if not authorization.decision.approved:
            raise RecoveryRejected("prerequisite repair was not approved")
        return self._run_remediation(source_plan, completion, store, repair)

    def _continue_pre_execution_restart(
        self,
        current: ProjectDeliveryCheckpoint,
        command: ResumeProjectDelivery,
    ) -> DeliveryResumeResult | None:
        from ai_software_engineer.recovery.restart import PreExecutionRestartService

        service = PreExecutionRestartService(self._config, self._environment, self._backend)
        try:
            proposal = service.propose(current)
            if proposal is None:
                return None
            plan = proposal.store().put_restart_plan(proposal.plan)
            if command.approved_plan_sha256 != plan.plan_sha256:
                if plan.restart_kind == "pre_agent_worktree_conflict":
                    next_action = (
                        "原 Task 在 Coder 启动前因目标分支或工作区已被其他保留任务占用而阻塞，"  # noqa: RUF001
                        "没有待恢复的代码。请审核并批准精确重启计划；平台会使用唯一 successor 分支，"  # noqa: E501, RUF001
                        "重新执行 Coder、QA、Reviewer。"
                    )
                else:
                    next_action = (
                        "原 Task 在 Coder 启动前因上下文超限阻塞，没有待恢复的代码。"  # noqa: RUF001
                        "请审核并批准精确重启计划；新 Task 保留原需求范围，重新执行 Coder、QA、Reviewer。"  # noqa: E501, RUF001
                    )
                return DeliveryResumeResult(
                    outcome=DeliveryResumeOutcome.RESTART_APPROVAL_REQUIRED,
                    checkpoint=current,
                    restart_plan=plan,
                    next_action=next_action,
                )
            dispatch = service.approve_and_dispatch(proposal, command)
            self._entry.begin_pre_execution_restart(
                plan,
                dispatch,
                proposal.store().get_restart_authorization(plan.plan_sha256),
                at=dispatch.committed_at,
            )
        except RecoveryRejected as error:
            return DeliveryResumeResult(
                outcome=DeliveryResumeOutcome.WAITING_HUMAN,
                checkpoint=current,
                next_action=f"Coder 启动前重启已安全停止：{error}",  # noqa: RUF001
            )
        # Attachment precedes execution. A crash or verifier knowledge wait remains reachable
        # through normal native continuation; no second hidden execution path is needed.
        result = self._entry.resume(
            ResumeProjectDelivery(
                delivery_id=current.delivery_id,
                submitted_at=command.submitted_at,
            )
        )
        return self._result(
            DeliveryResumeOutcome.CONTINUED,
            result,
            next_action=_checkpoint_next_action(result.checkpoint),
        )

    def _continue_coder_recovery(
        self,
        current: ProjectDeliveryCheckpoint,
        command: ResumeProjectDelivery,
    ) -> DeliveryResumeResult:
        try:
            latest = self._recovery.latest_delivery(current)
            if (
                latest is not None
                and command.coder_scope_request is not None
                and (
                    latest[1].scope_supplement is None
                    or latest[1].scope_supplement.request != command.coder_scope_request
                )
            ):
                latest = None
            if latest is not None:
                try:
                    self._recovery.require_current_plan(latest[2])
                except RecoveryRejected:
                    # Immutable stale plans remain as evidence. Recompute the exact
                    # scope and plan instead of asking the user to approve stale facts.
                    latest = None
            if latest is None:
                supplement = self._recovery.scope_supplement(
                    current, request=command.coder_scope_request
                )
                if supplement is not None and (
                    command.approved_scope_sha256 != supplement.supplement_sha256
                ):
                    return self._scope_approval_required(current, supplement)
                if supplement is None and command.approved_scope_sha256 is not None:
                    return self._recovery_human_gate(
                        current, "recovery scope approval no longer matches current changed paths"
                    )
                plan, path = self._recovery.propose_delivery(
                    current,
                    approved_scope_sha256=command.approved_scope_sha256,
                    coder_scope_request=command.coder_scope_request,
                    scope_approval_reference=(
                        command.approval_reference
                        if command.approved_scope_sha256 is not None
                        else None
                    ),
                )
                return self._recovery_approval_required(current, plan, path)
        except RecoveryRejected as error:
            return self._recovery_human_gate(current, str(error))
        store, plan, path = latest
        try:
            waiting = self._recovery.pending_knowledge_wait(path)
        except RecoveryRejected as error:
            return self._recovery_human_gate(current, str(error))
        if waiting is not None:
            return self._finish_coder_recovery(waiting)
        interrupted = read_recovery_task(self._config, self._environment, store, plan)
        try:
            store.get_invocation(plan.plan_sha256)
        except RecoveryRecordMissing:
            admitted = False
        else:
            admitted = True
        if admitted and interrupted is not None and interrupted.status is TaskStatus.IMPLEMENTING:
            try:
                proposal = RecoveryInterruptionService(self._recovery, store, plan).propose()
                if command.approved_plan_sha256 != proposal.plan_sha256:
                    return DeliveryResumeResult(
                        outcome=DeliveryResumeOutcome.RECOVERY_APPROVAL_REQUIRED,
                        checkpoint=current,
                        interruption_plan=proposal,
                        next_action="请在已停止的精确工作区上批准一次新的 Coder 执行。",
                    )
                assert command.approval_reference is not None
                execution = self._recovery.execute_interruption(
                    path,
                    confirmed_plan=proposal.plan_sha256,
                    reference=command.approval_reference,
                )
            except RecoveryRejected as error:
                return self._recovery_human_gate(current, str(error))
            return self._finish_coder_recovery(execution)
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
        return self._finish_coder_recovery(execution)

    def _finish_coder_recovery(self, execution: NativeRecoveryExecution) -> DeliveryResumeResult:
        started = self._entry.begin_recovery(
            execution.plan,
            execution.dispatch,
            at=execution.dispatch.committed_at,
        )
        if started.checkpoint.stage is not DeliveryStage.DELIVERING:
            return self._result(
                DeliveryResumeOutcome.CONTINUED,
                started,
                next_action=_checkpoint_next_action(started.checkpoint),
            )
        if isinstance(execution.delivery, KnowledgeGap):
            return self._result(
                DeliveryResumeOutcome.WAITING_HUMAN,
                started,
                next_action=f"Manager 等待知识前提确认: {execution.delivery.gap_id}。"
                f"恢复 Task 已接回原需求; 保留当前 {execution.delivery.binding.role.value} "
                "checkpoint, 解答批准前不启动新执行。",
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
            next_action=_checkpoint_next_action(result.checkpoint),
        )

    @staticmethod
    def _recovery_human_gate(
        checkpoint: ProjectDeliveryCheckpoint, reason: str
    ) -> DeliveryResumeResult:
        return DeliveryResumeResult(
            outcome=DeliveryResumeOutcome.WAITING_HUMAN,
            checkpoint=checkpoint,
            next_action=f"Coder 恢复已安全停止：{reason}",  # noqa: RUF001
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
                "请检查已封存的 Coder 改动，然后携带该精确计划摘要和批准引用重新请求恢复。"  # noqa: RUF001
            ),
            recovery_plan_file=str(path),
            recovery_plan_sha256=plan.plan_sha256,
        )

    @staticmethod
    def _scope_approval_required(
        checkpoint: ProjectDeliveryCheckpoint,
        supplement: RecoveryScopeSupplement,
    ) -> DeliveryResumeResult:
        return DeliveryResumeResult(
            outcome=DeliveryResumeOutcome.SCOPE_APPROVAL_REQUIRED,
            checkpoint=checkpoint,
            next_action="请先批准精确的遗漏文件路径，再封存保留的改动。",  # noqa: RUF001
            scope_supplement_sha256=supplement.supplement_sha256,
            scope_supplement_paths=supplement.paths,
            coder_scope_request=supplement.request,
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
        *,
        completion: CandidateVerificationCompletion | None = None,
    ) -> DeliveryResumeResult:
        next_action = (
            "请检查并批准精确验证计划; 若前次 QA 存在未执行项或环境/权限阻塞, 请先解决后再批准。"
            f" ase request resume {current.delivery_id} --approve-plan {plan.plan_sha256}"
        )
        if completion is not None:
            not_tested = sum(
                criterion.status is QaCriterionStatus.NOT_TESTED
                for criterion in completion.qa.content.criteria_results
            )
            errors = sum(
                test.status is QaTestStatus.ERROR for test in completion.qa.content.tests_run
            )
            next_action = (
                f"QA 报告 {completion.qa.artifact_id} 未完成验证: "
                f"{not_tested} 项 NOT_TESTED, {errors} 项 ERROR。"
                "请先解决报告中的环境/权限阻塞, 再批准新计划; 候选未改变, 不会重新执行 Coder。"
            )
        if plan.prerequisite_incident_sha256 is not None:
            next_action = (
                f"Manager 已记录验证环境阻塞 {plan.prerequisite_incident_sha256[:12]}, "
                "等待人工处理。请核对 QA 的未执行项、工具链和 UI 验收前提; "
                "新计划批准只授权列明的受控能力, "
                "不表示环境已修复或验收通过。" + next_action
            )
        if plan.manager_advice is not None:
            next_action = (
                f"Manager 已提出验证补齐方案: {plan.manager_advice.draft.summary}。"
                f"{plan.manager_advice.draft.next_action}。"
                "请审核精确 UI 步骤及验收映射后批准; 执行成功仍须独立 QA/Reviewer 判定。"
            )
        if plan.reused_qa is not None:
            next_action = (
                f"复用已封存 QA PASS {plan.reused_qa.artifact_id}; "
                "请批准仅重新执行独立 Reviewer 的精确计划。不会重新执行 QA, "
                "不修改历史 Task 或 QA 结论; Reviewer 仍须独立审查后才能交付。"
            )
        return DeliveryResumeResult(
            outcome=DeliveryResumeOutcome.VERIFICATION_APPROVAL_REQUIRED,
            checkpoint=current,
            next_action=next_action,
            verification_plan_file=str(path),
            verification_plan_sha256=plan.plan_sha256,
            verification_completion_sha256=(
                completion.completion_sha256 if completion is not None else None
            ),
        )

    @staticmethod
    def _result(
        outcome: DeliveryResumeOutcome,
        result: ProjectDeliveryResult,
        *,
        next_action: str,
        completion: CandidateVerificationCompletion | None = None,
    ) -> DeliveryResumeResult:
        if result.checkpoint.stage in {
            DeliveryStage.WAITING_PRODUCT_REPLY,
            DeliveryStage.WAITING_PRODUCT_APPROVAL,
            DeliveryStage.WAITING_HUMAN,
            DeliveryStage.BLOCKED,
            DeliveryStage.FAILED,
        }:
            outcome = DeliveryResumeOutcome.WAITING_HUMAN
        return DeliveryResumeResult(
            outcome=outcome,
            checkpoint=result.checkpoint,
            next_action=next_action,
            diagnostic=result.diagnostic,
            verification_completion_sha256=(
                completion.completion_sha256 if completion is not None else None
            ),
        )


__all__ = [
    "DeliveryResumeController",
    "DeliveryResumeOutcome",
    "DeliveryResumeResult",
]
