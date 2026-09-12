"""Receipt-bound seed application and at-most-once Coder invocation admission."""

from pathlib import Path

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import AgentPermissions, AgentRole
from ai_software_engineer.git import GitWorktreeManager, WorktreeRef
from ai_software_engineer.manager.dispatch import RecoveryDispatchRecord
from ai_software_engineer.recovery.context import validate_reapply_context
from ai_software_engineer.recovery.models import CapturedChanges, RecoveryRejected
from ai_software_engineer.recovery.records import RecoveryInvocationRecord, RecoverySeedRecord
from ai_software_engineer.recovery.sealing import RecoveryTaskSealingService
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing


class RecoverySeedService:
    def __init__(
        self,
        *,
        store: FileRecoveryStore,
        sealing: RecoveryTaskSealingService,
        manager: GitWorktreeManager,
        dispatch: RecoveryDispatchRecord,
        permissions: AgentPermissions,
        contexts: FileContextStore,
    ) -> None:
        self.store, self.sealing, self.manager = store, sealing, manager
        self.dispatch, self.permissions, self.contexts = dispatch, permissions, contexts

    def seed(self, target: WorktreeRef) -> RecoverySeedRecord:
        plan = self.store.get_plan(self.dispatch.recovery_plan_sha256)
        sealed = self.sealing.require_current(plan.plan_sha256)
        if sealed.record_sha256 != self.dispatch.recovery_task_record_sha256:
            raise RecoveryRejected("dispatch is not bound to current sealed Task")
        try:
            receipt = self.store.get_seed(plan.plan_sha256)
        except RecoveryRecordMissing:
            if plan.input_mode == "coder_reapply":
                capture = self.manager.capture_changes(
                    target, self.permissions, denied_paths=plan.denied_paths
                )
                if capture.patch:
                    raise RecoveryRejected(
                        "Coder reapplication requires a clean initial worktree"
                    ) from None
            else:
                capture = self.manager.seed_changes(
                    plan.capture.to_capture(),
                    target,
                    plan.permissions,
                    self.permissions,
                    source_denied_paths=plan.denied_paths,
                    target_denied_paths=plan.denied_paths,
                )
            receipt = self.store.put_seed(
                RecoverySeedRecord.create(
                    plan_sha256=plan.plan_sha256,
                    dispatch_sha256=self.dispatch.dispatch_sha256,
                    capture=CapturedChanges.from_capture(capture),
                )
            )
        if receipt.capture.to_capture().worktree != target:
            raise RecoveryRejected("seed receipt belongs to another target")
        self.verify(receipt)
        return receipt

    def verify(self, receipt: RecoverySeedRecord) -> None:
        plan = self.store.get_plan(self.dispatch.recovery_plan_sha256)
        if (
            receipt.recovery_plan_sha256 != plan.plan_sha256
            or receipt.dispatch_sha256 != self.dispatch.dispatch_sha256
        ):
            raise RecoveryRejected("seed dispatch lineage mismatch")
        self.manager.verify_capture(
            receipt.capture.to_capture(), self.permissions, denied_paths=plan.denied_paths
        )

    def authorize(self, request: AgentRequest, workspace_root: Path) -> None:
        """Called immediately before the provider, under the recovery execution lock."""
        plan = self.store.get_plan(self.dispatch.recovery_plan_sha256)
        receipt = self.store.get_seed(plan.plan_sha256)
        if (
            request.role is not AgentRole.CODER
            or request.task_id != self.dispatch.task_id
            or request.attempt != 1
            or request.source_revision != self.dispatch.task.base_ref
            or request.permissions != self.permissions
            or str(workspace_root) != receipt.capture.worktree_path
        ):
            raise RecoveryRejected("Coder request differs from authorized seed")
        context = self.contexts.get(request.context_manifest_id)
        if (
            context.task_id != request.task_id
            or context.role is not request.role
            or context.source_revision != request.source_revision
            or context.attempt != 1
        ):
            raise RecoveryRejected("Coder context differs from authorized seed")
        validate_reapply_context(plan, context)
        self.verify(receipt)
        try:
            self.store.get_invocation(plan.plan_sha256)
        except RecoveryRecordMissing:
            pass
        else:
            raise RecoveryRejected("Coder invocation already admitted; inspect durable runtime")
        self.sealing.require_current(plan.plan_sha256)
        invocation = RecoveryInvocationRecord(
            recovery_plan_sha256=plan.plan_sha256,
            seed_record_sha256=receipt.record_sha256,
            run_id=request.run_id,
            context_manifest_id=request.context_manifest_id,
            record_sha256="0" * 64,
        )
        self.store.put_invocation(
            invocation.model_copy(update={"record_sha256": invocation.recompute_sha256()})
        )
