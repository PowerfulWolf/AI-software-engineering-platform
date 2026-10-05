"""Read-only proof for correcting a joint design before any native Task exists."""

import hashlib

from ai_software_engineer.design.context import DesignContextBuilder
from ai_software_engineer.design.models import DesignerAgentErrorCode, DesignRunOutcome
from ai_software_engineer.design.service import RunDesignerCommand, _command_digest
from ai_software_engineer.design.store import FileDesignRecordStore
from ai_software_engineer.domain.enums import AgentRole, ProductApprovalDecision
from ai_software_engineer.git import GitWorkspaceError, GitWorktreeManager, WorktreeSpec
from ai_software_engineer.manager.baseline import FileProjectBaselineCompilationStore
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryStage,
    FileProjectDeliveryCheckpointStore,
)
from ai_software_engineer.manager.production_backend import (
    _approval_operation_id,
    _designer_run_id,
)
from ai_software_engineer.manager.stages import StageAdvanceAuthorization
from ai_software_engineer.multi_directory.models import (
    ChildDelivery,
    JointCheckpoint,
    digest,
)
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.multi_directory.verification_recovery import (
    UnstartedDesignCorrectionProof,
    UnstartedDesignCorrectionRejected,
    native_work_absent,
    unstarted_design_rejection,
)
from ai_software_engineer.product.store import FileProductRecordStore
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.runtime_workspace import load_repository_profile


class ProductionUnstartedDesignVerifier:
    """No Host, preparation, model, SQL writer or publication is constructed here."""

    def __init__(self, project: ProjectWorkspace) -> None:
        self.project = project

    def verify(self, checkpoint: JointCheckpoint) -> UnstartedDesignCorrectionProof:
        try:
            return self._verify(checkpoint)
        except GitWorkspaceError as error:
            raise UnstartedDesignCorrectionRejected(
                "冻结源码工作区缺失或已变化, 未追加设计修正。请工程团队核验后刷新并继续。"
            ) from error

    def _verify(self, checkpoint: JointCheckpoint) -> UnstartedDesignCorrectionProof:
        self.project.validate_current()
        history = JointJournal(self.project.requirements_root, read_only=True).history(
            checkpoint.delivery_id
        )
        if (
            not history
            or history[-1] != checkpoint
            or unstarted_design_rejection(checkpoint) is None
        ):
            raise UnstartedDesignCorrectionRejected("当前需求不满足无执行任务的设计契约修正条件。")
        if (
            checkpoint.team_id != self.project.team.manifest.team_id
            or checkpoint.team_manifest_sha256 != self.project.team.manifest.manifest_sha256
            or checkpoint.project_id != self.project.manifest.project_id
            or checkpoint.project_manifest_sha256 != self.project.manifest.manifest_sha256
        ):
            raise UnstartedDesignCorrectionRejected("设计修正的 Team 或 Project 归属不匹配。")
        self._verify_sources(checkpoint)
        receipts: dict[tuple[str, str], str] = {}
        # Include every retained child, not only those still projected as current.
        retained: dict[tuple[str, str], tuple[JointCheckpoint, ChildDelivery]] = {}
        for record in history:
            for child in record.children:
                if not native_work_absent(child.checkpoint):
                    raise UnstartedDesignCorrectionRejected(
                        "历史仓库交付已存在任务或已接纳产物, 不能回退设计。"
                    )
                retained[(child.checkpoint.repository_id, child.checkpoint.delivery_id)] = (
                    record,
                    child,
                )
        for key, (parent, child) in retained.items():
            receipts[key] = self._verify_child(parent, child)
        assert checkpoint.design is not None
        return UnstartedDesignCorrectionProof(
            checkpoint_sha256=checkpoint.checkpoint_sha256,
            design_sha256=digest(checkpoint.design),
            native_run_sha256s=tuple(receipts[key] for key in sorted(receipts)),
        )

    def _verify_sources(self, checkpoint: JointCheckpoint) -> None:
        workspaces = {
            item.repository_id: item for item in self.project.repository_registry().discover()
        }
        for unit in checkpoint.scope.units:
            prepared = next(
                item.result for item in checkpoint.preparations if item.unit_id == unit.id
            )
            preparation = prepared.preparation
            workspace = workspaces.get(prepared.repository_id)
            if (
                preparation is None
                or workspace is None
                or str(workspace.repository_root) != unit.root
                or preparation.repository_root != unit.root
                or preparation.project_id != checkpoint.project_id
                or preparation.team_id != checkpoint.team_id
                or preparation.project_manifest_sha256 != checkpoint.project_manifest_sha256
                or unit.base_revision is None
            ):
                raise UnstartedDesignCorrectionRejected("需求冻结准备的仓库或范围归属不匹配。")
            profile = load_repository_profile(workspace.root, preparation.repository_profile_sha256)
            compilation = FileProjectBaselineCompilationStore().get(
                workspace, prepared.baseline_compilation_sha256 or ""
            )
            if (
                profile.source_revision != unit.base_revision
                or compilation.compiled_spec is None
                or compilation.compiled_spec.baseline_sha256 != preparation.baseline_spec_sha256
            ):
                raise UnstartedDesignCorrectionRejected("需求冻结规范与源码基线不匹配。")
            manager = GitWorktreeManager(
                unit.root,
                self.project.team.root.parent
                / "worktrees/requirements"
                / checkpoint.delivery_id
                / unit.id,
            )
            baseline = manager.recover(
                WorktreeSpec(
                    task_id="task_baseline_"
                    + hashlib.sha256(f"{checkpoint.delivery_id}:{unit.id}".encode()).hexdigest()[
                        :32
                    ],
                    role=AgentRole.REVIEWER,
                    attempt=1,
                    source_revision=unit.base_revision,
                )
            )
            if manager.inspect(baseline).dirty:
                raise UnstartedDesignCorrectionRejected("需求冻结基线已有改动, 不能执行设计修正。")

    def _verify_child(self, parent: JointCheckpoint, child: ChildDelivery) -> str:
        # Local import avoids a composition-module cycle; projection is pure.
        from ai_software_engineer.multi_directory.production import DerivedStageInputs

        projection = DerivedStageInputs(parent, child.unit_id)
        assert parent.approval is not None
        current = child.checkpoint
        workspace = next(
            (
                item
                for item in self.project.repository_registry().discover()
                if item.repository_id == current.repository_id
            ),
            None,
        )
        if workspace is None or str(workspace.repository_root) != projection.root:
            raise UnstartedDesignCorrectionRejected("原生交付的仓库或需求归属无法核验。")
        store = FileProjectDeliveryCheckpointStore(
            workspace.root / "state/project-deliveries", read_only=True
        )
        history = store.list(current.delivery_id)
        if (
            not history
            or history[-1] != current
            or any(not native_work_absent(cp) for cp in history)
        ):
            raise UnstartedDesignCorrectionRejected("原生历史已变化或存在执行任务, 不能回退设计。")
        intake = store.get_intake(current.delivery_id)
        preparation = projection.preparation.preparation
        assert preparation is not None
        if (
            intake.repository_id != current.repository_id
            or intake.repository_root != projection.root
            or intake.title != parent.title
            or intake.requirement != projection.requirement
            or intake.submitted_at != parent.submitted_at
            or current.preparation_sha256 != preparation.preparation_sha256
        ):
            raise UnstartedDesignCorrectionRejected(
                "原生交付输入未绑定当前已批准的联合产物与基线。"
            )
        product = FileProductRecordStore(workspace.root / "state/product", read_only=True)
        design = FileDesignRecordStore(workspace.root / "state/design", read_only=True)
        run_id = _designer_run_id(current.delivery_id)
        run = design.get_run(run_id)
        if (
            run.outcome is not DesignRunOutcome.FAILED
            or run.error_code is not DesignerAgentErrorCode.INVALID_OUTPUT
            or design.find_checkpoint(run_id) is not None
            or current.stage is not DeliveryStage.BLOCKED
            or current.failed_stage is not DeliveryStage.DESIGNING
            or current.request_id is None
            or current.product_spec_id is None
            or current.approval_id is None
        ):
            raise UnstartedDesignCorrectionRejected(
                "原生 Designer 缺少精确的失败记录或已发布交接, 不能回退。"
            )
        revision = product.current_request_revision(current.request_id)
        spec = product.find_product_spec(current.product_spec_id)
        approval = product.find_approval(current.approval_id)
        approved = product.current_checkpoint(current.request_id)
        operation = product.get_operation(_approval_operation_id(current.delivery_id))
        authorization_wire = operation.result_payload.get("authorization")
        if not isinstance(authorization_wire, dict):
            raise UnstartedDesignCorrectionRejected("原生 Product 批准缺少已封存的设计授权。")
        authorization = StageAdvanceAuthorization.model_validate(authorization_wire)
        authorization.validate_integrity()
        if (
            spec is None
            or approval is None
            or spec.product_spec_sha256 != current.product_spec_sha256
            or approval.approval_sha256 != current.approval_sha256
            or approval.decision is not ProductApprovalDecision.APPROVED
            or approval.rationale != projection.approval_reference
            or approval.decided_at != parent.approval.approved_at
            or revision.request.original_request != projection.requirement
            or revision.request.repository_id != current.repository_id
            or revision.revision != current.request_revision
            or revision.request_revision_sha256 != run.input_request_revision_sha256
            or approved.checkpoint_sha256 != current.product_checkpoint_sha256
            or (run.repository_id, run.request_id) != (current.repository_id, current.request_id)
        ):
            raise UnstartedDesignCorrectionRejected("原生请求、批准或 Designer 输入摘要不匹配。")
        calls = [cp for cp in history if cp.stage is DeliveryStage.DESIGNING]
        if not calls:
            raise UnstartedDesignCorrectionRejected("缺少 Designer 执行前的原生交付记录。")
        call = calls[-1]
        profile = load_repository_profile(workspace.root, preparation.repository_profile_sha256)
        compilation = FileProjectBaselineCompilationStore().get(
            workspace, projection.preparation.baseline_compilation_sha256 or ""
        )
        if compilation.compiled_spec is None or profile.source_revision != projection.base_revision:
            raise UnstartedDesignCorrectionRejected("原生 Designer 冻结规范或源码基线不匹配。")
        command = RunDesignerCommand(
            run_id=run_id,
            preparation=preparation,
            repository_profile=profile,
            project_baseline=compilation.compiled_spec,
            request_revision=revision,
            product_spec=spec,
            product_approval=approval,
            solution_design_authorization=authorization,
            submitted_at=call.checkpointed_at,
        )
        context = DesignContextBuilder().build(
            preparation,
            profile,
            compilation.compiled_spec,
            revision.request,
            spec,
            approval,
            authorization,
            built_at=call.checkpointed_at,
        )
        if (
            run.input_sha256 != _command_digest(command)
            or run.context_id != context.context_id
            or run.recorded_at != call.checkpointed_at
        ):
            raise UnstartedDesignCorrectionRejected(
                "Designer 失败记录未绑定完整的请求和上下文谱系。"
            )
        return run.run_record_sha256
