"""Collect real engineering proof and consume exact nonterminal wait decisions.

There is no caller-provided process-stopped flag and no free-text repair command.
Unknown invocations retain their wait until trusted execution proof exists.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from ai_software_engineer.agents.fallback import ModelRouteAttemptStoreError
from ai_software_engineer.agents.models import AgentErrorCode, AgentRunStatus
from ai_software_engineer.artifacts import ArtifactStore, ArtifactStoreError, artifact_digest
from ai_software_engineer.context import ContextStoreError
from ai_software_engineer.domain.artifact import (
    ImplementationReportArtifact,
    QaReportArtifact,
    classify_qa_failure,
)
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import DeliveryResponsibility
from ai_software_engineer.domain.delivery_resolution import (
    RESULT_REPLAY_REJECTED_CLASSIFICATIONS,
    DeliveryProofMissing,
    DeliveryResolution,
    DeliveryResolutionKind,
    DeliveryWaitCollectionFailure,
    DeliveryWaitHandling,
    DeliveryWaitHandlingStatus,
    DeliveryWaitInvestigation,
    HandleDeliveryWait,
    InspectDeliveryWait,
    KnowledgePreparationRetryEvidence,
    OriginalInvocationAuthority,
    RejectedCoderOutputEvidence,
    ResolveDeliveryWait,
    VerificationRetryEvidence,
    VerifierPreparationEvidence,
    delivery_wait_handling_record_key,
    delivery_wait_resolution_plan_sha256,
)
from ai_software_engineer.domain.engineering_authority import (
    EngineeringCapability,
    EngineeringScope,
    LocalOperatorPrincipal,
    OperatorDuty,
)
from ai_software_engineer.domain.enums import (
    AgentRole,
    QaFailureDisposition,
    QaReportStatus,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.native_verification import NativeVerificationCapabilityDetail
from ai_software_engineer.domain.retry_policy import TRANSIENT_CODES, DeliveryRetryFailure
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git import GitWorkspaceError, GitWorktreeManager
from ai_software_engineer.git.mutation import (
    MutationInventoryRejected,
    WorkspaceMutationInventory,
    capture_mutation_inventory,
)
from ai_software_engineer.knowledge.legacy_scope import require_delivery_requirement_scope
from ai_software_engineer.knowledge.models import KnowledgeError, digest
from ai_software_engineer.knowledge.preparation_retry import (
    KnowledgeWindowExhausted,
    preparation_retry_evidence,
    read_local_limit,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.capacity_input_reader import claimed_verifier_capacity
from ai_software_engineer.manager.delivery_preflight import (
    DeliveryPreflightCheckpoint,
    DeliveryPreflightReceipt,
)
from ai_software_engineer.manager.engineering_authority import (
    EngineeringAuthority,
    EngineeringAuthorityRejected,
    EngineeringRejectionKind,
)
from ai_software_engineer.manager.rejected_output_checkpoint import (
    read_rejected_checkpoint,
    verify_rejected_workspace,
)
from ai_software_engineer.manager.stopped_budget_settlement import StoppedBudgetSettlementService
from ai_software_engineer.manager.verifier_preparation import (
    VerifierPreparationCheckpoint,
    VerifierPreparationIntent,
    observe_verifier_preparation,
)
from ai_software_engineer.manager.wait_fact_collection import WaitWorkspaceCaptureRejected
from ai_software_engineer.orchestration.capture_reconciliation import CaptureStopProcessUncertain
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRecordMissing,
    ContinuationRejected,
    ExecutionCaptureStop,
    ExecutionInterruptionReceipt,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.recovery.models import RecoveryScope
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.store import TaskRepository
from ai_software_engineer.work_queue.execution_store import (
    AcceptedRoleArtifact,
    QueuedRoleStep,
    record_digest,
)
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.ports import DeliveryQueuePending, QueueError, QueueLeaseLost
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard


def delivery_wait_recovery_scope(task: Task, scope: EngineeringScope) -> RecoveryScope:
    """The exact Task-owned ledger scope shared by its writer and physical cleanup."""
    if (
        task.repository != scope.repository_root
        or task.engineering_policy is None
        or (task.engineering_policy.scope != scope)
    ):
        raise ValueError("delivery wait ledger does not match frozen Task authority")
    return RecoveryScope(
        team_id=scope.team_id,
        repository_id=scope.repository_id,
        repository_root=scope.repository_root,
        delivery_id="delivery_wait_" + task.id,
    )


class DeliveryWaitQueue(Protocol):
    def get(self, work_item_id: str) -> QueuedWorkItem: ...
    def step(self, work_item_id: str) -> QueuedRoleStep: ...
    def original_claim(self, lease_id: str) -> QueueClaim: ...
    def accepted(self, task_id: str) -> tuple[AcceptedRoleArtifact, ...]: ...
    def step_for_invocation(
        self, work_item_id: str, baseline_sha256: str | None
    ) -> QueuedRoleStep: ...


class DeliveryWaitRejected(ValueError):
    """Safe engineering diagnostic; no mutation of the waiting item or workspace."""


_CAPABILITY_DETAIL_ACTIONS: dict[NativeVerificationCapabilityDetail, str] = {
    NativeVerificationCapabilityDetail.PROCESS_STATE_UNCONFIRMED: (
        "验证探测进程的实际停止或记录收尾尚未核验; 重复检查 Docker 镜像无法补齐原执行事实"
    ),
    NativeVerificationCapabilityDetail.PLATFORM_UNSUPPORTED: "服务主机不是受控 macOS 验证环境",
    NativeVerificationCapabilityDetail.CODEX_EXECUTABLE_UNAVAILABLE: "找不到已配置的 Codex 执行器",
    NativeVerificationCapabilityDetail.DOCKER_EXECUTABLE_UNAVAILABLE: "找不到 Docker 执行器",
    NativeVerificationCapabilityDetail.DOCKER_CONTEXT_UNAVAILABLE: "无法读取本地 Docker 上下文",
    NativeVerificationCapabilityDetail.DOCKER_ENDPOINT_INVALID: "Docker 上下文不是本地 Unix 套接字",
    NativeVerificationCapabilityDetail.DOCKER_SOCKET_UNAVAILABLE: (
        "Docker Unix socket 不存在或类型不正确"
    ),
    NativeVerificationCapabilityDetail.DOCKER_DAEMON_UNAVAILABLE: "Docker 服务进程当前不可用",
    NativeVerificationCapabilityDetail.MYSQL_IMAGE_UNAVAILABLE: "本地没有已批准的 MySQL 8.0 镜像",
    NativeVerificationCapabilityDetail.PYTHON_RUNTIME_UNAVAILABLE: (
        "受控 Python 运行时或验证执行器不可用"
    ),
    NativeVerificationCapabilityDetail.DEPENDENCY_FINGERPRINT_FAILED: (
        "Python 运行时依赖无法完成完整指纹校验"
    ),
    NativeVerificationCapabilityDetail.RUNNER_UNAVAILABLE: "受控验证 runner 不可用",
}


def _preflight_detail_action(
    prerequisites: DeliveryPreflightReceipt | None,
) -> str | None:
    if prerequisites is None:
        return None
    details = tuple(
        dict.fromkeys(
            _CAPABILITY_DETAIL_ACTIONS[item.native_wait_detail]
            for item in prerequisites.observations
            if item.native_wait_detail is not None
            and item.native_wait_detail in _CAPABILITY_DETAIL_ACTIONS
        )
    )
    if not details:
        return None
    if any(
        item.native_wait_detail is NativeVerificationCapabilityDetail.PROCESS_STATE_UNCONFIRMED
        for item in prerequisites.observations
    ):
        next_step = (
            "。需由平台执行服务核验原探测进程及收尾记录; 补齐原执行结束事实后再重新调查工程等待。"
        )
    else:
        next_step = "。工程负责人处理后请重新调查工程等待。"
    return "执行前提尚未满足: " + "; ".join(details) + next_step


class DeliveryNativeExecutionUncertain(DeliveryWaitRejected):
    """A native command started without its exact sealed final execution record."""


PrerequisiteCollector = Callable[[Task, QueuedRoleStep], DeliveryPreflightReceipt | None]
WaitFactCollector = Callable[[Task, QueuedRoleStep, WorkerExecutionGuard], None]
WaitStopObserver = Callable[
    [Task, QueuedRoleStep, WorkerExecutionGuard], ExecutionCaptureStop | None
]


class DeliveryWaitService:
    def __init__(
        self,
        *,
        repository: TaskRepository,
        scope: EngineeringScope,
        queue: DeliveryWaitQueue,
        sidecar_state: Path,
        git: GitWorktreeManager,
        principal: LocalOperatorPrincipal,
        consume: Callable[[DeliveryResolution], None],
        prerequisite_collector: PrerequisiteCollector | None = None,
        artifacts: ArtifactStore | None = None,
        engineering_authority: EngineeringAuthority | None = None,
        fact_collector: WaitFactCollector | None = None,
        stop_observer: WaitStopObserver | None = None,
        knowledge_requirement_id: str | None = None,
        knowledge_retry: Callable[[str], KnowledgePreparationRetryEvidence | None] | None = None,
        clock: Callable[[], datetime] | None = None,
        budget_settlement: StoppedBudgetSettlementService | None = None,
    ) -> None:
        self.repository, self.queue, self.sidecar_state = repository, queue, sidecar_state
        self.scope = scope
        self.git, self.principal, self.consume = git, principal, consume
        self.prerequisite_collector = prerequisite_collector
        self.artifacts = artifacts
        self.engineering_authority, self.fact_collector = engineering_authority, fact_collector
        self.stop_observer = stop_observer
        self.knowledge_requirement_id, self.knowledge_retry = (
            knowledge_requirement_id,
            knowledge_retry,
        )
        self.clock = clock or (lambda: datetime.now(UTC))
        self.budget_settlement = budget_settlement
        self.records = KnowledgeRecordStore(sidecar_state / "delivery-waits")

    def inspect(self, command: InspectDeliveryWait) -> DeliveryWaitInvestigation:
        self.principal.require_duty(OperatorDuty.ENGINEERING)
        item, step, task = self._current(command)
        guard = WorkerExecutionGuard()
        try:
            with guard.task_scope(
                self.sidecar_state / "queue-worker-locks",
                task.id,
            ):
                proof = self._collect(item, step, task, guard=guard)
        except DeliveryQueuePending:
            proof = self._proof(item, step, task, missing=(DeliveryProofMissing.TASK_PROCESS_LIVE,))
        proof.validate_integrity()
        return self.records.put("wait-investigations", proof.proof_sha256, proof)

    def resolve(self, command: ResolveDeliveryWait) -> DeliveryResolution:
        self.principal.require_duty(OperatorDuty.ENGINEERING)
        self._reject_baseline_pause(command.work_item_id)
        return self._resolve(command)

    def handle(self, command: HandleDeliveryWait) -> DeliveryWaitHandling:
        """Collect once and use frozen policy; requesting handling adds no authority."""
        self._reject_baseline_pause(command.work_item_id)
        if self.budget_settlement is not None:
            replay_guard = WorkerExecutionGuard()
            with replay_guard.task_scope(
                self.sidecar_state / "queue-worker-locks",
                self.queue.get(command.work_item_id).task_id,
            ):
                replay = self.budget_settlement.replay(command, replay_guard)
                if replay is not None:
                    return replay
        binding_key = digest(command.to_wire())
        resolved = self.records.find("wait-handling-resolutions", binding_key, DeliveryWaitHandling)
        if resolved is not None:
            resolved.validate_integrity()
            self._require_handling_binding(resolved, command)
            assert resolved.resolution is not None
            self.consume(resolved.resolution)
            return resolved
        # The decision is sealed before queue consumption. Recover publication
        # after a crash without requiring the old item to remain WAITING.
        existing = self.records.find(
            "wait-resolutions",
            command.work_item_id + ":" + command.expected_disposition_sha256,
            DeliveryResolution,
        )
        if existing is not None:
            existing.validate_integrity()
            proof = self.records.get(
                "wait-investigations", existing.proof_sha256, DeliveryWaitInvestigation
            )
            self._require_proof_binding(proof, command)
            self.consume(existing)
            published = self.records.find(
                "wait-handlings", self._handling_identity(command, proof), DeliveryWaitHandling
            )
            if published is not None:
                published.validate_integrity()
                self._require_handling_binding(published, command)
                if published.resolution != existing:
                    raise DeliveryWaitRejected("已封存平台处理记录不符合原工程决定")
                return self.records.put("wait-handling-resolutions", binding_key, published)
            record = self._handling_record(
                proof,
                existing,
                "RESOLVED",
                "已找回原等待的精确工程决定, 原交付和审计历史保留。",
                "无需重复批准; 查看后续执行记录和独立 QA、Review 结果。",
                "无需重复处理本次等待。",
                at=existing.submitted_at,
            )
            record = self.records.put("wait-handlings", record.record_key, record)
            return self.records.put("wait-handling-resolutions", binding_key, record)
        item, step, task = self._current(command)
        guard = WorkerExecutionGuard()
        collector_failed = False
        capture_failed = False
        try:
            with guard.task_scope(self.sidecar_state / "queue-worker-locks", task.id):
                # This seam can recover sealed original facts. It cannot grant new
                # commands, invoke a model, consume queue state or invent a stop.
                if self.fact_collector is not None:
                    try:
                        self.fact_collector(task, step, guard)
                    except CaptureStopProcessUncertain:
                        raise
                    except WaitWorkspaceCaptureRejected:
                        collector_failed = capture_failed = True
                    except (
                        ContinuationRejected,
                        ModelRouteAttemptStoreError,
                        KnowledgeError,
                        GitWorkspaceError,
                        MutationInventoryRejected,
                    ):
                        collector_failed = True
                proof = self._collect(item, step, task, guard=guard)
                if not collector_failed and self.budget_settlement is not None:
                    settled = self.budget_settlement.try_settle(
                        command, task, item, step, proof, guard
                    )
                    if settled is not None:
                        return settled
        except QueueLeaseLost:
            proof = self._proof(
                item, step, task, missing=(DeliveryProofMissing.PROCESS_LIVE_OR_UNKNOWN,)
            )
        except CaptureStopProcessUncertain:
            proof = self._proof(
                item, step, task, missing=(DeliveryProofMissing.PROCESS_LIVE_OR_UNKNOWN,)
            )
        except DeliveryQueuePending:
            proof = self._proof(item, step, task, missing=(DeliveryProofMissing.TASK_PROCESS_LIVE,))
        status, summary, user_action, recheck_when = self._handling_presentation(proof)
        collection_failure = None
        if collector_failed:
            status = "PLATFORM_ATTENTION"
            summary = "平台收集原执行事实时校验失败, 原记录和工作现场保留。"
            user_action = (
                "已保存平台待处理记录。ASE 工程维护者需修复原执行记录的关联或完整性; "
                "本次没有批准恢复, 也没有修改原调查证明或角色结论。"
            )
            recheck_when = "原记录校验问题修复后再检查; 重复调查不能绕过完整性校验。"
            if (
                capture_failed
                and proof.process_stop_sha256
                and (
                    DeliveryProofMissing.STOP_UNRECORDED not in proof.missing
                    and DeliveryProofMissing.CHECKPOINT_UNAVAILABLE in proof.missing
                    and not proof.permitted_resolutions
                )
            ):
                collection_failure = DeliveryWaitCollectionFailure.WORKSPACE_CAPTURE_REJECTED
                summary = (
                    "原 Coder 已到本地执行时限并停止, 但保留进度的完整封存未通过平台校验。"
                    if proof.retry_cause == "local_execution_limit"
                    else "原 Coder 停止已核验, 但保留进度的完整封存未通过平台校验。"
                )
                user_action = (
                    "ASE 平台维护者需修复完整进度封存问题; 修复后点击“平台修复后重新处理”, "
                    "由平台核验并继续原需求。现有源码和停止记录保留, 本次没有批准恢复。"
                )
                recheck_when = "完整进度封存问题修复后再处理; 仅重新检查状态不能补齐封存记录。"
        identity = self._handling_identity(
            command, proof, collector_failed=collector_failed, collection_failure=collection_failure
        )
        prior = self.records.find("wait-handlings", identity, DeliveryWaitHandling)
        if prior is not None:
            prior.validate_integrity()
            self._require_handling_binding(prior, command)
            return prior
        proof.validate_integrity()
        # Pin the first exact proof before spending shared admission allowance.
        # A restart with unchanged facts must recover the same admission plan,
        # despite a new inspection timestamp or prerequisite receipt time.
        frozen = self.records.find("wait-handling-proofs", identity, DeliveryWaitInvestigation)
        if frozen is None:
            try:
                frozen = self.records.put("wait-handling-proofs", identity, proof)
            except KnowledgeError:
                # Another exact handler can have won exclusive publication.
                # Re-read and compare semantic identity; other errors still fail.
                concurrent = self.records.find(
                    "wait-handling-proofs", identity, DeliveryWaitInvestigation
                )
                if concurrent is None:
                    raise
                frozen = concurrent
        frozen.validate_integrity()
        self._require_proof_binding(frozen, command)
        if (
            self._handling_identity(
                command,
                frozen,
                collector_failed=collector_failed,
                collection_failure=collection_failure,
            )
            != identity
        ):
            raise DeliveryWaitRejected("平台处理记录绑定的原调查事实已变化")
        proof = frozen
        proof = self.records.put("wait-investigations", proof.proof_sha256, proof)
        resolution = None
        if not collector_failed and not proof.missing and proof.permitted_resolutions:
            try:
                resolution = self._resolve(
                    ResolveDeliveryWait.model_validate(
                        {
                            **command.to_wire(),
                            "resolution_kind": proof.permitted_resolutions[0],
                            "proof_sha256": proof.proof_sha256,
                            "submitted_at": self.clock(),
                        },
                    ),
                    automatic=True,
                )
                status = "RESOLVED"
                summary = "平台已核验恢复条件, 并按原任务冻结的工程授权记录了精确处理。"
                user_action = (
                    "无需重新定义需求或重复批准; 原需求由新的执行身份继续, 结果以执行记录为准。"
                )
                recheck_when = "无需重复处理本次等待; 查看后续执行记录及独立 QA、Review 结果。"
            except EngineeringAuthorityRejected as error:
                if error.kind is EngineeringRejectionKind.BUDGET_EXHAUSTED:
                    status = "BUDGET_EXHAUSTED"
                    summary = "恢复条件已核验, 但冻结的组织工程恢复额度已耗尽。"
                    user_action = "由工程负责人核对资源和剩余交付额度, 决定是否追加授权或结束交付。"
                    recheck_when = "获得独立、有效的新授权后再处理; 重复检查不会重置额度。"
                elif error.kind in {
                    EngineeringRejectionKind.LEGACY_AUTHORITY,
                    EngineeringRejectionKind.CAPABILITY_UNAVAILABLE,
                }:
                    status = "NEEDS_AUTHORIZATION"
                    summary = "恢复条件已核验, 但原任务没有授权平台自动执行此处理。"
                    user_action = (
                        "请核对下面的处理方式, 再记录精确工程决定; 批准不代表验收通过。"
                        if OperatorDuty.ENGINEERING in self.principal.duties
                        else "请有工程职责的负责人记录精确处理决定; 产品权限不能代替工程授权。"
                    )
                    recheck_when = "事实未改变时无需重新调查; 工程决定应使用本次已核验的证明。"
                else:
                    status = "PLATFORM_ATTENTION"
                    summary = "恢复条件已核验, 但冻结授权记录与当前事实不一致。"
                    user_action = (
                        "ASE 工程维护者需核对原授权范围与审计记录; 不能通过批准按钮绕过漂移。"
                    )
                    recheck_when = "授权记录的关联或读取问题修复后再检查。"
        record = self._handling_record(
            proof,
            resolution,
            status,
            summary,
            user_action,
            recheck_when,
            at=self.clock(),
            collection_failed=collector_failed,
            collection_failure=collection_failure,
        )
        try:
            sealed = self.records.put("wait-handlings", identity, record)
        except KnowledgeError:
            concurrent_handling = self.records.find(
                "wait-handlings", identity, DeliveryWaitHandling
            )
            if concurrent_handling is None:
                raise
            concurrent_handling.validate_integrity()
            self._require_handling_binding(concurrent_handling, command)
            if concurrent_handling.model_dump(
                mode="json", exclude={"handled_at", "handling_sha256"}
            ) != record.model_dump(mode="json", exclude={"handled_at", "handling_sha256"}):
                raise
            sealed = concurrent_handling
        if resolution is not None:
            self.records.put("wait-handling-resolutions", binding_key, sealed)
        return sealed

    def _handling_identity(
        self,
        command: HandleDeliveryWait,
        proof: DeliveryWaitInvestigation,
        *,
        collector_failed: bool = False,
        collection_failure: DeliveryWaitCollectionFailure | None = None,
    ) -> str:
        return delivery_wait_handling_record_key(
            command,
            proof,
            manual_resolution_allowed=OperatorDuty.ENGINEERING in self.principal.duties,
            collection_failed=collector_failed,
            collection_failure=collection_failure,
        )

    def _handling_record(
        self,
        proof: DeliveryWaitInvestigation,
        resolution: DeliveryResolution | None,
        status: DeliveryWaitHandlingStatus,
        summary: str,
        user_action: str,
        recheck_when: str,
        *,
        at: datetime,
        collection_failed: bool = False,
        collection_failure: DeliveryWaitCollectionFailure | None = None,
    ) -> DeliveryWaitHandling:
        record = DeliveryWaitHandling(
            task_id=proof.task_id,
            work_item_id=proof.work_item_id,
            disposition_sha256=proof.disposition_sha256,
            task_intent_sha256=proof.task_intent_sha256,
            source_revision=proof.source_revision,
            checkpoint_sequence=proof.checkpoint_sequence,
            investigation=proof,
            resolution=resolution,
            status=status,
            summary=summary,
            user_action=user_action,
            recheck_when=recheck_when,
            manual_resolution_allowed=OperatorDuty.ENGINEERING in self.principal.duties,
            collection_failed=collection_failed,
            collection_failure=collection_failure,
            handled_at=at,
            handling_sha256="0" * 64,
        )
        record = record.model_copy(update={"handling_sha256": record.recompute_sha256()})
        record.validate_integrity()
        return record

    @staticmethod
    def _require_handling_binding(
        record: DeliveryWaitHandling, command: InspectDeliveryWait
    ) -> None:
        proof = record.investigation
        DeliveryWaitService._require_proof_binding(proof, command)

    @staticmethod
    def _handling_presentation(
        proof: DeliveryWaitInvestigation,
    ) -> tuple[DeliveryWaitHandlingStatus, str, str, str]:
        missing = set(proof.missing)
        if missing & {
            DeliveryProofMissing.TASK_PROCESS_LIVE,
            DeliveryProofMissing.PROCESS_LIVE_OR_UNKNOWN,
        }:
            return (
                "WAITING_EXECUTION",
                "原执行仍在运行, 或尚不能证明其安全停止。",
                "保留原工作区; 不要重复启动 Coder。平台不会凭租约到期判定已经停机。",
                "原调用实际结束并封存停止记录后, 再检查状态。",
            )
        if DeliveryProofMissing.KNOWLEDGE_WINDOW_EXHAUSTED in missing:
            return (
                "BUDGET_EXHAUSTED",
                "知识准备已达到本任务冻结的扩窗上限。",
                "工程负责人需检查知识输入或执行器耗时, 修复后重新评估; "
                "平台保留原需求和历史, 不会继续放大时限或重复必败执行。",
                "工程团队完成原因修复或另行精确资源授权后再处理。",
            )
        if DeliveryProofMissing.BUDGET_EXHAUSTED in missing:
            return (
                "BUDGET_EXHAUSTED",
                "原任务的可用执行额度已耗尽。",
                "工程负责人需决定执行资源或结束交付; 平台不重置历史额度。",
                "新的精确资源授权生效后再处理。",
            )
        if DeliveryProofMissing.PREREQUISITES_UNVERIFIED in missing:
            return (
                "WAITING_PREREQUISITES",
                "当前验证工具或环境前提仍未满足。",
                proof.next_action,
                "所列工具或环境处理完成后, 再检查状态。",
            )
        if missing:
            if (
                proof.process_stop_sha256 is not None
                and DeliveryProofMissing.STOP_UNRECORDED not in missing
                and DeliveryProofMissing.CHECKPOINT_UNAVAILABLE in missing
            ):
                return (
                    "PLATFORM_ATTENTION",
                    "原执行停止已核验, 但尚无可安全继续的完整进度记录。",
                    "ASE 平台需核对原结果与完整进度; 处理完成后点击“平台修复后重新处理”, "
                    "重新核验并继续原需求。原现场和执行历史保留。",
                    "原结果与完整进度记录补齐后重新处理; 仅重新检查状态不会封存进度。",
                )
            return (
                "PLATFORM_ATTENTION",
                "平台已检查原执行, 但恢复所需的可信记录仍不完整。",
                "已保存本次平台待处理记录。ASE 工程维护者需核对原调用的最终结果、"
                "真实停止记录和完整现场; 当前没有可安全继续的决定, 也未自动创建修复任务。",
                "平台补齐原执行记录或修复记录读取后再检查; 现在重复调查不会补出缺失事实。",
            )
        return (
            "NEEDS_AUTHORIZATION",
            "恢复事实已核验, 正在检查原任务冻结的工程授权。",
            "平台只在原范围、已注册能力和冻结额度内处理。",
            "事实没有变化时无需重新调查。",
        )

    def _resolve(
        self, command: ResolveDeliveryWait, *, automatic: bool = False
    ) -> DeliveryResolution:
        key = command.work_item_id + ":" + command.expected_disposition_sha256
        prior = self.records.find("wait-resolutions", key, DeliveryResolution)
        if prior is not None:
            prior.validate_integrity()
            self._require_decision_binding(prior, command, automatic=automatic)
            self.consume(prior)
            return prior
        proof = self.records.get(
            "wait-investigations", command.proof_sha256, DeliveryWaitInvestigation
        )
        proof.validate_integrity()
        self._require_proof_binding(proof, command)
        if command.resolution_kind not in proof.permitted_resolutions or proof.missing:
            raise DeliveryWaitRejected(proof.next_action)
        item, step, task = self._current(command)
        guard = WorkerExecutionGuard()
        try:
            with guard.task_scope(
                self.sidecar_state / "queue-worker-locks",
                task.id,
            ):
                current = self._collect(item, step, task, guard=guard)
                excluded = {"proof_sha256", "inspected_at", "prerequisite_receipt_sha256"}
                if current.model_dump(mode="json", exclude=excluded) != proof.model_dump(
                    mode="json", exclude=excluded
                ):
                    raise DeliveryWaitRejected(
                        "工程调查之后事实已变化, 请重新调查; 原等待与现场保留"
                    )
                if command.submitted_at < proof.inspected_at:
                    raise DeliveryWaitRejected("工程决定早于对应调查, 不能消费此证明")
                admission = None
                if automatic:
                    policy = task.engineering_policy
                    if self.engineering_authority is None or policy is None:
                        raise EngineeringAuthorityRejected(
                            EngineeringRejectionKind.LEGACY_AUTHORITY,
                            "当前任务没有可用的冻结工程恢复授权。",
                        )
                    if not policy.allowance(EngineeringCapability.DELIVERY_WAIT_RESOLUTION):
                        raise EngineeringAuthorityRejected(
                            EngineeringRejectionKind.CAPABILITY_UNAVAILABLE,
                            "当前任务的冻结工程授权不包括自动处理此等待。",
                        )
                    store = FileRecoveryStore.initialize(
                        self.sidecar_state / ("delivery-wait-authority-" + digest(task.id)),
                        scope=delivery_wait_recovery_scope(task, self.scope),
                    )
                    admission = self.engineering_authority.admit(
                        task=task,
                        store=store,
                        plan_sha256=delivery_wait_resolution_plan_sha256(
                            proof.proof_sha256, command.resolution_kind
                        ),
                        facts_sha256=proof.proof_sha256,
                        capabilities=(EngineeringCapability.DELIVERY_WAIT_RESOLUTION,),
                        at=command.submitted_at,
                    )
                retry_failure = None
                retry_cause: (
                    Literal["local_execution_limit", "provider_transient", "service_pause"] | None
                ) = None
                if command.resolution_kind is DeliveryResolutionKind.RETRY_FROM_CHECKPOINT:
                    start, paused_outcome = self._invocation(item, step)
                    receipt = self._receipt(task, start)
                    if proof.verifier_pause is not None:
                        if (
                            paused_outcome is None
                            or paused_outcome.service_pause != proof.verifier_pause
                        ):
                            raise DeliveryWaitRejected("原验证暂停事实已变化, 不允许继续")
                        retry_cause = "service_pause"
                    else:
                        if receipt is None or receipt.cause == "service_pause":
                            raise DeliveryWaitRejected("原开发需要精确工程基线计划, 不允许通用续跑")
                        retry_cause = receipt.cause
                        if receipt.cause == "provider_transient":
                            retry_failure = self._retry_failure(receipt)
                resolution = DeliveryResolution(
                    task_id=task.id,
                    work_item_id=item.id,
                    expected_disposition_sha256=command.expected_disposition_sha256,
                    expected_task_intent_sha256=command.expected_task_intent_sha256,
                    expected_source_revision=command.expected_source_revision,
                    expected_checkpoint_sequence=command.expected_checkpoint_sequence,
                    task_revision=proof.task_revision,
                    task_snapshot_sha256=proof.task_snapshot_sha256,
                    step_sha256=proof.step_sha256,
                    resolution_kind=command.resolution_kind,
                    proof_sha256=proof.proof_sha256,
                    authorization_source=(
                        "organization_engineering_policy"
                        if automatic
                        else "engineering_operator_decision"
                    ),
                    operator_principal=None if automatic else self.principal,
                    engineering_admission=admission,
                    submitted_at=command.submitted_at,
                    resolution_sha256="0" * 64,
                    retry_failure=retry_failure,
                    retry_cause=retry_cause,
                    original_authority=(
                        proof.original_authority
                        if command.resolution_kind is DeliveryResolutionKind.REPLAY_RECORDED_RESULT
                        else None
                    ),
                    verification_retry=(
                        proof.verification_retry
                        if command.resolution_kind is DeliveryResolutionKind.REVERIFY_CANDIDATE
                        else None
                    ),
                    verifier_preparation=(
                        proof.verifier_preparation
                        if command.resolution_kind
                        in {
                            DeliveryResolutionKind.RESUME_UNINVOKED,
                            DeliveryResolutionKind.RETRY_VERIFIER_PREPARATION,
                        }
                        else None
                    ),
                    knowledge_preparation=(
                        proof.knowledge_preparation
                        if command.resolution_kind
                        is DeliveryResolutionKind.RETRY_KNOWLEDGE_PREPARATION
                        else None
                    ),
                    verifier_pause=proof.verifier_pause,
                    rejected_output=(
                        proof.rejected_output
                        if command.resolution_kind
                        is DeliveryResolutionKind.RETRY_REJECTED_CODER_OUTPUT
                        else None
                    ),
                )
                resolution = resolution.model_copy(
                    update={"resolution_sha256": resolution.recompute_sha256()}
                )
                sealed = self.records.put("wait-resolutions", key, resolution)
                # Atomic queue consumption owns live-claim/Task fences and the new
                # identity. Publication first makes an interrupted decision replayable.
                self.consume(sealed)
                return sealed
        except DeliveryQueuePending as error:
            raise DeliveryWaitRejected(
                "原 Task 仍有活跃执行进程, 不允许继续; 请等待受控执行器停止"
            ) from error

    def _current(self, command: InspectDeliveryWait) -> tuple[QueuedWorkItem, QueuedRoleStep, Task]:
        item = self.queue.get(command.work_item_id)
        disposition = item.wait_disposition
        if (
            item.status not in {WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY}
            or disposition is None
        ):
            raise DeliveryWaitRejected("工作项当前没有可处理的工程等待")
        self._reject_baseline_pause(item.id)
        facts = disposition.facts
        if disposition.responsibility is not DeliveryResponsibility.ENGINEERING:
            raise DeliveryWaitRejected("此等待需产品或团队处理, 不能用工程决定替代")
        if (
            disposition.disposition_sha256 != command.expected_disposition_sha256
            or facts.task_intent_sha256 != command.expected_task_intent_sha256
            or facts.source_revision != command.expected_source_revision
            or facts.checkpoint_sequence != command.expected_checkpoint_sequence
        ):
            raise DeliveryWaitRejected("显示的工程等待已变化, 请刷新后重新调查")
        step = self.queue.step(item.id)
        task = self.repository.get(item.task_id)
        if (
            task.status in {TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.FAILED}
            or task_intent_sha256(task) != facts.task_intent_sha256
            or self.repository.current_revision(task.id) != facts.checkpoint_sequence
            or (
                step.boundary.task_id,
                step.boundary.source_revision,
                step.boundary.checkpoint_sequence,
            )
            != (task.id, facts.source_revision, facts.checkpoint_sequence)
            or item.repository_id != self.scope.repository_id
            or item.repository_id != step.work_item.repository_id
            or task.repository != self.scope.repository_root
            or (task.engineering_policy is not None and task.engineering_policy.scope != self.scope)
        ):
            raise DeliveryWaitRejected("工程等待不再绑定当前非终态 Task checkpoint, 禁止修改旧事实")
        return item, step, task

    def _reject_baseline_pause(self, work_item_id: str) -> None:
        disposition = self.queue.get(work_item_id).wait_disposition
        if (
            disposition is not None
            and disposition.facts.classification == "EXECUTION_BASELINE_PAUSED"
        ):
            raise DeliveryWaitRejected(
                "开发进度已保留并主动暂停; 可先更新源码和规范, 再明确批准继续原需求"
            )

    def _collect(
        self,
        item: QueuedWorkItem,
        step: QueuedRoleStep,
        task: Task,
        *,
        guard: WorkerExecutionGuard | None = None,
    ) -> DeliveryWaitInvestigation:
        assert item.wait_disposition is not None
        missing: list[DeliveryProofMissing] = []
        permitted: tuple[DeliveryResolutionKind, ...] = ()
        start, outcome = self._invocation(item, step)
        receipt = self._receipt(task, start)
        if (
            outcome is not None
            and outcome.service_pause is not None
            and item.role in {AgentRole.QA, AgentRole.REVIEWER}
        ):
            try:
                assert start is not None
                self._original_authority(item, start)
                pause = outcome.service_pause
                pause.validate_integrity()
                if (
                    pause.request != start.request
                    or pause.request.source_revision != step.boundary.source_revision
                ):
                    raise ValueError("verifier pause belongs to another exact input")
                if pause.process_stop is not None:
                    NativeCoderContinuation._require_stopped(pause.process_stop, start.request)
                if task.work_budget_exhausted or task.attempts >= task.max_attempts:
                    missing.append(DeliveryProofMissing.BUDGET_EXHAUSTED)
                else:
                    permitted = (DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,)
            except (ContinuationRejected, ValueError, QueueError, OSError):
                missing.append(DeliveryProofMissing.PROCESS_LIVE_OR_UNKNOWN)
            return self._proof(
                item,
                step,
                task,
                start=start,
                outcome=outcome,
                missing=tuple(missing),
                permitted=permitted if not missing else (),
            )
        rejected_outcome = outcome is not None and (
            item.wait_disposition.facts.classification in RESULT_REPLAY_REJECTED_CLASSIFICATIONS
            or (
                outcome.result.status is not AgentRunStatus.SUCCEEDED
                and (
                    outcome.result.error is None
                    or not outcome.result.error.transient
                    or outcome.result.error.code.value not in TRANSIENT_CODES
                )
            )
        )
        reverify = (
            outcome is not None
            and not rejected_outcome
            and isinstance(outcome.result.artifact, QaReportArtifact)
            and outcome.result.artifact.content.status is QaReportStatus.FAIL
            and classify_qa_failure(outcome.result.artifact.content)
            is QaFailureDisposition.RETRY_VERIFICATION
        )
        verification_retry = None
        verifier_preparation = None
        knowledge_preparation = None
        rejected_output = None
        original_authority = None
        inventory: WorkspaceMutationInventory | None = None
        observed_stop: ExecutionCaptureStop | None = None
        rejected_checkpoint = (
            read_rejected_checkpoint(self.sidecar_state, item.id) if rejected_outcome else None
        )
        if rejected_checkpoint is not None:
            if (
                outcome != rejected_checkpoint.outcome
                or rejected_checkpoint.task_snapshot_sha256 != digest(task.to_wire())
                or rejected_checkpoint.step_sha256 != record_digest(step)
                or rejected_checkpoint.capture_start.task_revision
                != self.repository.current_revision(task.id)
                or rejected_checkpoint.evidence.scope != self.scope
            ):
                raise DeliveryWaitRejected("被拒产出的保留现场记录不再绑定当前工程等待")
            observed_stop = rejected_checkpoint.capture_stop
            try:
                verify_rejected_workspace(rejected_checkpoint, self.git, task)
                self._original_authority(item, rejected_checkpoint.outcome.start)
                inventory = rejected_checkpoint.inventory_after
                rejected_output = rejected_checkpoint.evidence
                if task.work_budget_exhausted or task.attempts >= task.max_attempts:
                    missing.append(DeliveryProofMissing.BUDGET_EXHAUSTED)
                else:
                    permitted = (DeliveryResolutionKind.RETRY_REJECTED_CODER_OUTPUT,)
            except (ContinuationRejected, GitWorkspaceError, ValueError, OSError, QueueError):
                missing.append(DeliveryProofMissing.CHECKPOINT_DRIFT)
        elif outcome is not None and not reverify and not rejected_outcome:
            # This decision never makes another model call. Worker uses the
            # sealed original request/result and normal artifact/verdict guards.
            assert start is not None
            try:
                original_authority = self._original_authority(item, start)
                permitted = (DeliveryResolutionKind.REPLAY_RECORDED_RESULT,)
            except (ValueError, DeliveryQueuePending, QueueError):
                missing.append(DeliveryProofMissing.ORIGINAL_CLAIM_UNAVAILABLE)
        elif start is not None and receipt is None and (outcome is None or rejected_outcome):
            if outcome is None:
                missing.append(DeliveryProofMissing.OUTCOME_UNKNOWN)
            if self.stop_observer is not None and guard is not None:
                try:
                    observed_stop = self.stop_observer(task, step, guard)
                    if observed_stop is not None:
                        observed_stop.validate_integrity()
                        if (observed_stop.task_id, observed_stop.run_id) != (
                            task.id,
                            start.request.run_id,
                        ):
                            raise ContinuationRejected("停止观察未绑定当前原执行")
                        try:
                            NativeCoderContinuation._require_stopped(
                                observed_stop.process_stop, start.request
                            )
                        except ContinuationRejected as error:
                            raise CaptureStopProcessUncertain(
                                "原执行进程组仍在运行或状态未知, 暂不能处理"
                            ) from error
                except (QueueLeaseLost, CaptureStopProcessUncertain):
                    observed_stop = None
                    missing.append(DeliveryProofMissing.PROCESS_LIVE_OR_UNKNOWN)
                except (ContinuationRejected, ValueError, OSError, KnowledgeError, QueueError):
                    observed_stop = None
            if observed_stop is None:
                missing.append(DeliveryProofMissing.STOP_UNRECORDED)
            missing.append(DeliveryProofMissing.CHECKPOINT_UNAVAILABLE)
        elif receipt is not None and start is not None:
            try:
                self._original_authority(item, start)
                self._verify_receipt(receipt, item, task, start)
                inventory = capture_mutation_inventory(Path(receipt.capture.worktree_path))
                if inventory != receipt.inventory_after:
                    missing.append(DeliveryProofMissing.CHECKPOINT_DRIFT)
            except ContinuationRejected:
                missing.append(DeliveryProofMissing.PROCESS_LIVE_OR_UNKNOWN)
            except QueueError:
                missing.append(DeliveryProofMissing.ORIGINAL_CLAIM_UNAVAILABLE)
            except (GitWorkspaceError, ValueError, OSError):
                missing.append(DeliveryProofMissing.CHECKPOINT_DRIFT)
        prerequisites = (
            self.prerequisite_collector(task, step) if self.prerequisite_collector else None
        )
        coder_preflight_uninvoked = (
            item.role is AgentRole.CODER
            and start is None
            and outcome is None
            and item.wait_disposition.facts.classification
            in {"ENVIRONMENT_UNAVAILABLE", "SERVICE_PAUSED"}
            and prerequisites is not None
            and self._claimed_uninvoked_preflight(item, task, step)
        )
        if (
            item.wait_disposition.facts.classification
            in {
                "ENVIRONMENT_UNAVAILABLE",
                "ENGINEERING_AUTHORIZATION",
                "SOURCE_PREPARATION_DRIFT",
            }
            and not coder_preflight_uninvoked
            and (prerequisites is None or prerequisites.status != "READY")
        ):
            missing.append(DeliveryProofMissing.PREREQUISITES_UNVERIFIED)
        if prerequisites is not None:
            prerequisites.validate_integrity()
            if (
                prerequisites.task_id,
                prerequisites.scope.team_id,
                prerequisites.scope.project_id,
                prerequisites.scope.repository_id,
                prerequisites.source_revision,
            ) != (
                task.id,
                self.scope.team_id,
                self.scope.project_id,
                item.repository_id,
                step.boundary.source_revision,
            ):
                raise DeliveryWaitRejected("前提调查不属于当前 Task 和 Repository")
            self.records.put("wait-prerequisites", prerequisites.receipt_sha256, prerequisites)
        if reverify:
            if prerequisites is None or prerequisites.status != "READY":
                missing.append(DeliveryProofMissing.PREREQUISITES_UNVERIFIED)
            elif task.work_budget_exhausted or task.attempts >= task.max_attempts:
                missing.append(DeliveryProofMissing.BUDGET_EXHAUSTED)
            else:
                assert start is not None and outcome is not None
                try:
                    verification_retry = self._verification_retry(
                        item, task, start, outcome, prerequisites
                    )
                    permitted = (DeliveryResolutionKind.REVERIFY_CANDIDATE,)
                except (ArtifactStoreError, ValueError, OSError, QueueError):
                    missing.append(DeliveryProofMissing.VERIFICATION_EVIDENCE_UNAVAILABLE)
        if receipt is not None and receipt.cause == "service_pause":
            # Coder drafts require a separately approved exact execution baseline.
            missing.append(DeliveryProofMissing.CHECKPOINT_UNAVAILABLE)
        if not missing and receipt is not None and (outcome is None or rejected_outcome):
            try:
                if receipt.cause == "provider_transient":
                    if rejected_outcome:
                        raise DeliveryWaitRejected("已拒绝的产出不能借提供方故障记录退款或再次重放")
                    reserved = task.with_retry_failure(self._retry_failure(receipt))
                    if reserved.attempts <= task.attempts:
                        raise ValueError("no fresh execution identity remains")
                elif task.work_budget_exhausted or task.attempts >= task.max_attempts:
                    raise ValueError("no frozen work allowance remains")
                permitted = (DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,)
            except DeliveryWaitRejected:
                missing.append(DeliveryProofMissing.OUTCOME_REJECTED)
            except ValueError:
                missing.append(DeliveryProofMissing.BUDGET_EXHAUSTED)
        if rejected_outcome and not permitted:
            missing.append(DeliveryProofMissing.OUTCOME_REJECTED)
        if item.wait_disposition.facts.classification == "CONTEXT_CAPACITY":
            if item.role not in {AgentRole.QA, AgentRole.REVIEWER}:
                # Coder capacity recovery uses its original exact baseline PAUSE/RESUME path.
                missing.append(DeliveryProofMissing.VERIFIER_PREPARATION_UNAVAILABLE)
            elif start is not None or outcome is not None:
                missing.append(DeliveryProofMissing.INVOCATION_UNRECORDED)
            elif prerequisites is None or prerequisites.status != "READY":
                missing.append(DeliveryProofMissing.PREREQUISITES_UNVERIFIED)
            elif self.artifacts is None or any(
                accepted.work_item_id == item.id for accepted in self.queue.accepted(task.id)
            ):
                missing.append(DeliveryProofMissing.VERIFIER_PREPARATION_UNAVAILABLE)
            else:
                try:
                    verifier_preparation = claimed_verifier_capacity(
                        item=item,
                        task=task,
                        step=step,
                        prerequisites=prerequisites,
                        state=self.sidecar_state,
                        queue=self.queue,
                        artifacts=self.artifacts,
                    )
                    permitted = (DeliveryResolutionKind.RESUME_UNINVOKED,)
                except (
                    ValueError,
                    QueueError,
                    OSError,
                    KnowledgeError,
                    ArtifactStoreError,
                    ContextStoreError,
                    ContinuationRejected,
                    ModelRouteAttemptStoreError,
                ):
                    missing.append(DeliveryProofMissing.VERIFIER_PREPARATION_UNAVAILABLE)
        elif item.wait_disposition.facts.classification == "KNOWLEDGE_PREPARATION_LIMIT":
            if start is not None or outcome is not None:
                missing.append(DeliveryProofMissing.KNOWLEDGE_PREPARATION_UNAVAILABLE)
            else:
                try:
                    knowledge_preparation = self._claimed_knowledge_preparation(item, task, step)
                    if task.work_budget_exhausted or task.attempts >= task.max_attempts:
                        missing.append(DeliveryProofMissing.BUDGET_EXHAUSTED)
                    else:
                        permitted = (DeliveryResolutionKind.RETRY_KNOWLEDGE_PREPARATION,)
                except KnowledgeWindowExhausted:
                    missing.append(DeliveryProofMissing.KNOWLEDGE_WINDOW_EXHAUSTED)
                except (QueueLeaseLost, ContinuationRejected):
                    missing.append(DeliveryProofMissing.PROCESS_LIVE_OR_UNKNOWN)
                except (ValueError, QueueError, OSError, KnowledgeError):
                    missing.append(DeliveryProofMissing.KNOWLEDGE_PREPARATION_UNAVAILABLE)
        elif start is None:
            preparation_ids = tuple(
                value
                for value in item.wait_disposition.facts.evidence_ids
                if value.startswith("verifier-preparation://")
            )
            if preparation_ids:
                try:
                    if prerequisites is None or prerequisites.status != "READY":
                        missing.append(DeliveryProofMissing.PREREQUISITES_UNVERIFIED)
                    else:
                        verifier_preparation = self._claimed_verifier_preparation(
                            item, task, step, prerequisites
                        )
                        if verifier_preparation.native_execution_state == "NOT_STARTED":
                            permitted = (DeliveryResolutionKind.RESUME_UNINVOKED,)
                        elif task.work_budget_exhausted or task.attempts >= task.max_attempts:
                            missing.append(DeliveryProofMissing.BUDGET_EXHAUSTED)
                        else:
                            permitted = (DeliveryResolutionKind.RETRY_VERIFIER_PREPARATION,)
                except DeliveryNativeExecutionUncertain:
                    missing.append(DeliveryProofMissing.NATIVE_EXECUTION_UNCERTAIN)
                except (ValueError, QueueError, OSError, KnowledgeError):
                    missing.append(DeliveryProofMissing.VERIFIER_PREPARATION_UNAVAILABLE)
            elif (
                item.wait_disposition.facts.classification
                in {"ENVIRONMENT_UNAVAILABLE", "SERVICE_PAUSED"}
                and prerequisites is not None
                and (prerequisites.status == "READY" or coder_preflight_uninvoked)
                and self._claimed_uninvoked_preflight(item, task, step)
            ):
                permitted = (DeliveryResolutionKind.RESUME_UNINVOKED,)
            else:
                missing.append(DeliveryProofMissing.INVOCATION_UNRECORDED)
        # Each executable path above verifies its real frozen allowance. The
        # recorded summary cannot veto work-budget recovery merely because the
        # separate provider-transient allowance is exhausted.
        if missing:
            permitted = ()
        return self._proof(
            item,
            step,
            task,
            missing=tuple(dict.fromkeys(missing)),
            permitted=permitted,
            start=start,
            outcome=outcome,
            receipt=receipt,
            inventory=inventory,
            prerequisites=prerequisites,
            original_authority=original_authority,
            verification_retry=verification_retry,
            verifier_preparation=verifier_preparation,
            knowledge_preparation=knowledge_preparation,
            rejected_output=rejected_output,
            observed_stop=observed_stop,
        )

    def _claimed_knowledge_preparation(
        self, item: QueuedWorkItem, task: Task, step: QueuedRoleStep
    ) -> KnowledgePreparationRetryEvidence:
        assert item.wait_disposition is not None
        evidence_ids = item.wait_disposition.facts.evidence_ids
        prefix = "knowledge-preparation://"
        if len(evidence_ids) != 1 or not evidence_ids[0].startswith(prefix):
            raise DeliveryWaitRejected("知识准备等待没有精确原执行记录")
        if any(record.work_item_id == item.id for record in self.queue.accepted(task.id)):
            raise DeliveryWaitRejected("主角色已有接纳结果, 不能作为尚未开始的知识准备继续")
        outcome = read_local_limit(
            self.sidecar_state.parent / "knowledge" / "runs", evidence_ids[0].removeprefix(prefix)
        )
        intent = outcome.intent
        if intent.claim is None:
            raise DeliveryWaitRejected("知识准备记录缺少原领取身份或不属于当前需求")
        if self.knowledge_requirement_id is not None:
            require_delivery_requirement_scope(
                intent.binding,
                self.knowledge_requirement_id,
                records=KnowledgeRecordStore(
                    self.sidecar_state.parent / "knowledge" / "runs", read_only=True
                ),
            )
        if item.parent_work_item_id is not None and self.knowledge_retry is None:
            raise DeliveryWaitRejected("缺少原知识准备窗口的已消费决定, 禁止重新计算窗口")
        previous = self.knowledge_retry(item.id) if self.knowledge_retry is not None else None
        return preparation_retry_evidence(
            outcome=outcome,
            task=task,
            item=item,
            source_revision=step.boundary.source_revision,
            scope=self.scope,
            historical_claim=self.queue.original_claim(intent.claim.lease.id),
            previous=previous,
            delivery_requirement_id=(
                self.knowledge_requirement_id or intent.binding.requirement_id
            ),
        )

    def _claimed_verifier_preparation(
        self,
        item: QueuedWorkItem,
        task: Task,
        step: QueuedRoleStep,
        prerequisites: DeliveryPreflightReceipt,
    ) -> VerifierPreparationEvidence:
        assert item.wait_disposition is not None
        identities = tuple(
            value.removeprefix("verifier-preparation://")
            for value in item.wait_disposition.facts.evidence_ids
            if value.startswith("verifier-preparation://")
        )
        if len(identities) != 1:
            raise DeliveryWaitRejected("缺少原角色执行前准备的精确记录")
        records = KnowledgeRecordStore(self.sidecar_state / "delivery-preflight", read_only=True)
        marker = records.get("verifier-preparations", identities[0], VerifierPreparationCheckpoint)
        marker.validate_integrity()
        request = marker.request
        claim = self.queue.original_claim(marker.lease_id)
        wait_claim = self.queue.original_claim(marker.wait_lease_id)
        intent = records.get(
            "verifier-preparation-intents",
            f"{marker.work_item_id}:{marker.checkpoint_sequence}:{marker.dispatch_sequence}",
            VerifierPreparationIntent,
        )
        intent.validate_integrity()
        if (
            marker.checkpoint_sha256 != identities[0]
            or marker.result != "WAIT"
            or (
                intent.work_item_id,
                intent.lease_id,
                intent.task_id,
                intent.task_snapshot_sha256,
                intent.checkpoint_sequence,
                intent.dispatch_sequence,
                intent.request,
                intent.request_sha256,
                intent.intent_sha256,
            )
            != (
                marker.work_item_id,
                marker.lease_id,
                marker.task_id,
                marker.task_snapshot_sha256,
                marker.checkpoint_sequence,
                marker.dispatch_sequence,
                marker.request,
                marker.request_sha256,
                marker.intent_sha256,
            )
            or intent.started_at > marker.checked_at
            or marker.dispatch_sequence > marker.wait_dispatch_sequence
            or marker.wait_dispatch_sequence != item.dispatch_sequence
            or (
                marker.work_item_id,
                marker.task_id,
                marker.task_snapshot_sha256,
                marker.checkpoint_sequence,
                marker.source_revision,
                marker.role,
                marker.attempt,
            )
            != (
                item.id,
                task.id,
                digest(task.to_wire()),
                step.boundary.checkpoint_sequence,
                step.boundary.source_revision,
                item.role,
                item.attempt,
            )
            or (
                claim.work_item.id,
                claim.work_item.task_id,
                claim.work_item.role,
                claim.work_item.attempt,
                claim.work_item.checkpoint_sequence,
                claim.work_item.repository_id,
                claim.work_item.dispatch_sequence,
                claim.lease.id,
            )
            != (
                item.id,
                task.id,
                item.role,
                item.attempt,
                item.checkpoint_sequence,
                item.repository_id,
                marker.dispatch_sequence,
                marker.lease_id,
            )
            or (
                wait_claim.work_item.id,
                wait_claim.work_item.task_id,
                wait_claim.work_item.role,
                wait_claim.work_item.attempt,
                wait_claim.work_item.checkpoint_sequence,
                wait_claim.work_item.repository_id,
                wait_claim.work_item.dispatch_sequence,
                wait_claim.lease.id,
            )
            != (
                item.id,
                task.id,
                item.role,
                item.attempt,
                item.checkpoint_sequence,
                item.repository_id,
                marker.wait_dispatch_sequence,
                marker.wait_lease_id,
            )
            or task.status
            is not (TaskStatus.QA if item.role is AgentRole.QA else TaskStatus.REVIEW)
            or item.role not in {AgentRole.QA, AgentRole.REVIEWER}
            or marker.request_sha256 != digest(request.to_wire())
        ):
            raise DeliveryWaitRejected("原验证准备记录与真实历史 claim 或当前候选不一致")
        observed = observe_verifier_preparation(
            repository_workspace_root=self.sidecar_state.parent,
            request=request,
            lease_id=marker.lease_id,
        )
        if observed.native_execution_state == "UNCERTAIN":
            raise DeliveryNativeExecutionUncertain("原生验证执行结果未知, 不允许重复执行")
        if observed != marker.observation:
            raise DeliveryWaitRejected("原验证准备记录与真实 native 执行记录不一致")
        finished = observed.native_execution_state == "FINISHED"
        return VerifierPreparationEvidence(
            candidate_revision=marker.source_revision,
            preparation_checkpoint_sha256=marker.checkpoint_sha256,
            previous_run_id=marker.run_id,
            previous_context_manifest_id=marker.context_manifest_id,
            request_sha256=marker.request_sha256,
            native_execution_state=observed.native_execution_state,
            native_binding_plan_sha256=observed.native_binding_plan_sha256,
            native_started_sha256=observed.native_started_sha256,
            native_finished_sha256=observed.native_finished_sha256,
            native_failure_code=observed.native_failure_code,
            prerequisite_facts_sha256=digest(
                prerequisites.model_dump(mode="json", exclude={"checked_at", "receipt_sha256"})
            ),
            budget_source="frozen_work_attempt" if finished else None,
        )

    def _verification_retry(
        self,
        item: QueuedWorkItem,
        task: Task,
        start: DeliveryInvocationStart,
        outcome: DeliveryInvocationOutcome,
        prerequisites: DeliveryPreflightReceipt,
    ) -> VerificationRetryEvidence:
        draft = outcome.result.artifact
        if self.artifacts is None or not isinstance(draft, QaReportArtifact):
            raise DeliveryWaitRejected("缺少受信候选与 QA 验收产物")
        qa = self.artifacts.get(draft.artifact_id)
        if (
            not isinstance(qa, QaReportArtifact)
            or not qa.integrity.validated
            or qa.integrity.sha256 != artifact_digest(qa)
            or artifact_digest(qa) != artifact_digest(draft)
        ):
            raise DeliveryWaitRejected("原 QA 返回与已接纳产物的精确内容或身份不一致")
        authority = self._original_authority(item, start)
        accepted = self.queue.accepted(task.id)
        qa_receipt = next(
            (record for record in accepted if record.receipt.artifact_id == qa.artifact_id), None
        )
        parents = tuple(self.artifacts.get(identity) for identity in qa.parent_artifact_ids)
        candidates = tuple(
            value for value in parents if isinstance(value, ImplementationReportArtifact)
        )
        candidate = candidates[0] if len(candidates) == 1 else None
        if (
            task.status is not TaskStatus.QA
            or item.role is not AgentRole.QA
            or qa_receipt is None
            or not isinstance(candidate, ImplementationReportArtifact)
            or not any(
                record.receipt.artifact_id == candidate.artifact_id
                and record.receipt.sha256 == candidate.integrity.sha256
                for record in accepted
            )
            or (
                qa_receipt.work_item_id,
                qa_receipt.task_id,
                qa_receipt.lease_id,
                qa_receipt.dispatch_sequence,
                qa_receipt.checkpoint_sequence,
                qa_receipt.run_id,
                qa_receipt.context_manifest_id,
                qa_receipt.source_revision,
                qa_receipt.receipt.sha256,
            )
            != (
                item.id,
                task.id,
                start.lease_id,
                self.queue.original_claim(start.lease_id).work_item.dispatch_sequence,
                start.checkpoint_sequence,
                start.request.run_id,
                start.request.context_manifest_id,
                start.request.source_revision,
                qa.integrity.sha256,
            )
            or qa.producer.agent_id != authority.assignment.agent_id
            or qa.producer.run_id != start.request.run_id
            or qa.producer.role is not AgentRole.QA
            or qa.task_id != task.id
            or qa.context_manifest_id != start.request.context_manifest_id
            or qa.source_revision != start.request.source_revision
            or candidate.source_revision != qa.source_revision
            or candidate.content.commit_sha != qa.source_revision
        ):
            raise DeliveryWaitRejected("新的候选复验未绑定已接纳的精确原 QA 和保留候选")
        return VerificationRetryEvidence(
            candidate_revision=candidate.content.commit_sha,
            previous_qa_artifact_id=qa.artifact_id,
            previous_qa_sha256=qa.integrity.sha256,
            previous_run_id=start.request.run_id,
            previous_context_manifest_id=start.request.context_manifest_id,
            invocation_outcome_sha256=outcome.outcome_sha256,
            prerequisite_facts_sha256=digest(
                prerequisites.model_dump(mode="json", exclude={"checked_at", "receipt_sha256"})
            ),
        )

    def _original_authority(
        self,
        item: QueuedWorkItem,
        start: DeliveryInvocationStart,
    ) -> OriginalInvocationAuthority:
        claim = self.queue.original_claim(start.lease_id)
        if (
            claim.work_item.id,
            claim.work_item.task_id,
            claim.work_item.repository_id,
            claim.work_item.role,
            claim.work_item.attempt,
            claim.work_item.checkpoint_sequence,
        ) != (
            item.id,
            start.request.task_id,
            item.repository_id,
            start.request.role,
            start.request.attempt,
            start.checkpoint_sequence,
        ):
            raise DeliveryWaitRejected("原调用的历史 claim 身份与封存 request 不一致")
        return OriginalInvocationAuthority(
            work_item_id=item.id,
            checkpoint_sequence=start.checkpoint_sequence,
            assignment=claim.assignment,
            lease=claim.lease,
            model_selection=claim.model_selection,
            request_permissions=start.request.permissions,
            run_id=start.request.run_id,
            context_manifest_id=start.request.context_manifest_id,
            source_revision=start.request.source_revision,
            request_sha256=digest(start.request.to_wire()),
        )

    def _claimed_uninvoked_preflight(
        self,
        item: QueuedWorkItem,
        task: Task,
        step: QueuedRoleStep,
    ) -> bool:
        assert item.wait_disposition is not None
        root = self.sidecar_state / "delivery-preflight"
        if not root.is_dir():
            return False
        records = KnowledgeRecordStore(root, read_only=True)
        prefixes = tuple(
            identity.removeprefix("delivery-preflight://")
            for identity in item.wait_disposition.facts.evidence_ids
            if identity.startswith("delivery-preflight://")
        )
        if len(prefixes) != 1:
            return False
        marker = records.find(
            "preflight-checkpoints", item.id + ":" + prefixes[0], DeliveryPreflightCheckpoint
        )
        prior = records.find("preflight-receipts", prefixes[0], DeliveryPreflightReceipt)
        if marker is None or prior is None:
            return False
        marker.validate_integrity()
        prior.validate_integrity()
        claim = self.queue.original_claim(marker.lease_id)
        return (
            (
                marker.work_item_id,
                marker.task_id,
                marker.task_snapshot_sha256,
                marker.checkpoint_sequence,
                marker.source_revision,
                marker.receipt_sha256,
            )
            == (
                item.id,
                task.id,
                digest(task.to_wire()),
                step.boundary.checkpoint_sequence,
                step.boundary.source_revision,
                prior.receipt_sha256,
            )
            and prior.task_id == task.id
            and prior.scope.repository_id == self.scope.repository_id
            and prior.status == "WAIT_ENGINEERING"
            and (
                claim.work_item.id,
                claim.work_item.task_id,
                claim.work_item.role,
                claim.work_item.attempt,
                claim.work_item.checkpoint_sequence,
                claim.work_item.repository_id,
            )
            == (
                item.id,
                task.id,
                item.role,
                item.attempt,
                item.checkpoint_sequence,
                item.repository_id,
            )
        )

    def _invocation(
        self, item: QueuedWorkItem, step: QueuedRoleStep
    ) -> tuple[DeliveryInvocationStart | None, DeliveryInvocationOutcome | None]:
        root = self.sidecar_state / "invocations"
        if not root.exists():
            return None, None
        records = KnowledgeRecordStore(root, read_only=True)
        start = records.find("invocation-starts", item.id, DeliveryInvocationStart)
        outcome = records.find("invocation-outcomes", item.id, DeliveryInvocationOutcome)
        if start is not None:
            start.validate_integrity()
            if (
                start.work_item_id,
                start.checkpoint_sequence,
                start.request.task_id,
                start.request.role,
                start.request.attempt,
                start.request.source_revision,
            ) != (
                item.id,
                item.checkpoint_sequence,
                item.task_id,
                item.role,
                item.attempt,
                step.boundary.source_revision,
            ):
                raise DeliveryWaitRejected("原调用身份与工程等待 checkpoint 不一致")
        if outcome is not None:
            outcome.validate_integrity()
            if outcome.start != start:
                raise DeliveryWaitRejected("原调用结果未绑定精确启动记录")
        return start, outcome

    def _receipt(
        self, task: Task, start: DeliveryInvocationStart | None
    ) -> ExecutionInterruptionReceipt | None:
        root = self.sidecar_state / "continuations" / task.id
        if start is None or not root.exists():
            return None
        try:
            return FileContinuationStore(root, task_id=task.id).get_receipt(start.request.run_id)
        except ContinuationRecordMissing:
            return None

    def _verify_receipt(
        self,
        receipt: ExecutionInterruptionReceipt,
        item: QueuedWorkItem,
        task: Task,
        start: DeliveryInvocationStart,
    ) -> None:
        receipt.validate_integrity()
        policy = task.interruption_continuation_policy
        if (
            receipt.request != start.request
            or receipt.original_work_item_id != item.id
            or receipt.claim_lease_id != start.lease_id
            or receipt.task_revision != item.checkpoint_sequence
            or receipt.task_intent_sha256 != task_intent_sha256(task)
            or (receipt.scope.team_id, receipt.scope.project_id, receipt.scope.repository_id)
            != (self.scope.team_id, self.scope.project_id, self.scope.repository_id)
            or policy is None
            or receipt.policy_sha256 != policy.policy_sha256
        ):
            raise DeliveryWaitRejected("停机现场记录未绑定原执行与冻结权限")
        NativeCoderContinuation._require_stopped(receipt.process_stop, receipt.request)
        denied = task.constraints.denied_paths if task.constraints else ()
        if isinstance(receipt.capture, CapturedMutations):
            self.git.verify_mutations(
                receipt.capture.to_capture(), start.request.permissions, denied_paths=denied
            )
        else:
            self.git.verify_capture(
                receipt.capture.to_capture(), start.request.permissions, denied_paths=denied
            )

    @staticmethod
    def _retry_failure(receipt: ExecutionInterruptionReceipt) -> DeliveryRetryFailure:
        return DeliveryRetryFailure.model_validate(
            {
                "role": receipt.request.role,
                "attempt": receipt.request.attempt,
                "run_id": receipt.request.run_id,
                "code": receipt.original_error_code.value,
            }
        )

    def _proof(
        self,
        item: QueuedWorkItem,
        step: QueuedRoleStep,
        task: Task,
        *,
        missing: tuple[DeliveryProofMissing, ...],
        permitted: tuple[DeliveryResolutionKind, ...] = (),
        start: DeliveryInvocationStart | None = None,
        outcome: DeliveryInvocationOutcome | None = None,
        receipt: ExecutionInterruptionReceipt | None = None,
        inventory: WorkspaceMutationInventory | None = None,
        prerequisites: DeliveryPreflightReceipt | None = None,
        original_authority: OriginalInvocationAuthority | None = None,
        verification_retry: VerificationRetryEvidence | None = None,
        verifier_preparation: VerifierPreparationEvidence | None = None,
        knowledge_preparation: KnowledgePreparationRetryEvidence | None = None,
        rejected_output: RejectedCoderOutputEvidence | None = None,
        observed_stop: ExecutionCaptureStop | None = None,
    ) -> DeliveryWaitInvestigation:
        assert item.wait_disposition is not None
        preflight_detail_action = _preflight_detail_action(prerequisites)
        provider_failure_code: Literal["AUTHENTICATION_ERROR"] | None = (
            "AUTHENTICATION_ERROR"
            if start is not None
            and outcome is not None
            and outcome.start == start
            and start.work_item_id == item.id
            and start.request.task_id == task.id
            and start.request.role is AgentRole.CODER
            and start.request.source_revision == step.boundary.source_revision
            and start.checkpoint_sequence == step.boundary.checkpoint_sequence
            and start.request.attempt == item.attempt
            and start.request.attempt == task.attempts
            and outcome.result.status is AgentRunStatus.FAILED
            and outcome.result.artifact is None
            and outcome.result.error is not None
            and outcome.result.error.code is AgentErrorCode.AUTHENTICATION_ERROR
            and not outcome.result.error.transient
            and not permitted
            else None
        )
        proof = DeliveryWaitInvestigation(
            task_id=task.id,
            work_item_id=item.id,
            disposition=item.wait_disposition,
            disposition_sha256=item.wait_disposition.disposition_sha256,
            task_intent_sha256=task_intent_sha256(task),
            task_revision=self.repository.current_revision(task.id),
            task_snapshot_sha256=digest(task.to_wire()),
            source_revision=step.boundary.source_revision,
            checkpoint_sequence=step.boundary.checkpoint_sequence,
            step_sha256=record_digest(step),
            original_run_id=(
                start.request.run_id
                if start
                else knowledge_preparation.previous_run_id
                if knowledge_preparation
                else (verifier_preparation.previous_run_id if verifier_preparation else None)
            ),
            invocation_start_sha256=start.start_sha256 if start else None,
            invocation_outcome_sha256=outcome.outcome_sha256 if outcome else None,
            provider_failure_code=provider_failure_code,
            interruption_receipt_sha256=receipt.receipt_sha256 if receipt else None,
            process_stop_sha256=(
                receipt.process_stop_sha256
                if receipt
                else observed_stop.process_stop.stop_sha256
                if observed_stop
                else None
            ),
            workspace_inventory_sha256=inventory.sha256 if inventory else None,
            prerequisite_receipt_sha256=prerequisites.receipt_sha256 if prerequisites else None,
            prerequisite_facts_sha256=digest(
                prerequisites.model_dump(
                    mode="json",
                    exclude={"checked_at", "receipt_sha256"},
                )
            )
            if prerequisites
            else None,
            original_authority=original_authority,
            verification_retry=verification_retry,
            verifier_preparation=verifier_preparation,
            knowledge_preparation=knowledge_preparation,
            rejected_output=rejected_output,
            verifier_pause=outcome.service_pause
            if outcome and item.role in {AgentRole.QA, AgentRole.REVIEWER}
            else None,
            retry_cause="service_pause"
            if outcome and outcome.service_pause
            else receipt.cause
            if receipt
            else observed_stop.cause
            if observed_stop
            else None,
            permitted_resolutions=permitted,
            missing=missing,
            next_action=(
                "原开发因服务重启暂停。工作现场保留; 请先审阅并批准精确的更新执行基线计划接续。"
                if receipt is not None and receipt.cause == "service_pause"
                else "原独立验收因服务重启暂停, 停止事实已核验。"
                "可使用剩余工作额度领取新的独立验证。"
                if outcome is not None and outcome.service_pause is not None and permitted
                else "原开发执行已结束, 进度报告的轮次编号不符合本次执行; 完整合法草稿已保留。"
                "可使用一次原授权工作额度, 由新的开发执行继续原需求并重新生成正确报告。"
                if permitted == (DeliveryResolutionKind.RETRY_REJECTED_CODER_OUTPUT,)
                else "已核验原验证准备和完整输入, 本次角色模型未启动。平台可保留同一候选和"
                "原工作预留, 重新领取独立验收; 原执行与容量记录保留, 不退款或增加执行轮次。"
                if permitted == (DeliveryResolutionKind.RESUME_UNINVOKED,)
                and verifier_preparation is not None
                and verifier_preparation.context_capacity_receipt_sha256 is not None
                else f"知识准备原执行已结束, 主角色尚未开始。可使用一次剩余工作额度, "
                f"把下次准备窗口扩大到 {knowledge_preparation.next_timeout_seconds} 秒, "
                "重新领取原任务继续; 原知识记录和执行历史保留。"
                if permitted == (DeliveryResolutionKind.RETRY_KNOWLEDGE_PREPARATION,)
                and knowledge_preparation is not None
                else "知识准备已达到冻结扩窗上限, 不再重复执行; "
                "工程负责人需检查知识输入与执行器耗时, 保留原需求和全部历史。"
                if DeliveryProofMissing.KNOWLEDGE_WINDOW_EXHAUSTED in missing
                else "已核验原验证准备已经结束而角色模型尚未启动; 可使用一次已授权工作额度"
                "重新领取独立验收, 原执行证据与结果保留。"
                if permitted == (DeliveryResolutionKind.RETRY_VERIFIER_PREPARATION,)
                else "已核验保留候选、原 QA 未完成的原因及当前前提; "
                "可使用一次已授权工作额度重新独立验收, 旧 QA 历史保留。"
                if permitted == (DeliveryResolutionKind.REVERIFY_CANDIDATE,)
                else "已核验原执行记录和精确恢复条件; 工程负责人可记录处理决定, "
                "实际进度与验收以之后的新执行事实为准。"
                if permitted
                else "已授权执行额度已耗尽。工程团队需核对原拒绝理由与现场; "
                "由团队负责人决定执行资源或结束交付, 不会重复接纳已拒绝的原产出。"
                if DeliveryProofMissing.BUDGET_EXHAUSTED in missing
                else "原提供方或本机调用的凭证前提未满足, 本次开发执行失败。"
                "请先检查并修复原调用配置, 再使用准备恢复方案入口保留合法草稿; "
                "由工程授权者确认精确方案并保持暂停, 最后明确继续原需求。"
                "平台不会自动验证提供方健康、退款或接纳原失败结果。"
                if provider_failure_code is not None
                else "原产出已被契约或非临时故障拒绝, 不能重复接纳。工程团队需查看原错误并"
                "修复产物或执行器契约; 核验真实停机与完整合法现场后, 按剩余工作额度重新调查。"
                "原产出、角色结论和历史保留。"
                if DeliveryProofMissing.OUTCOME_REJECTED in missing
                else preflight_detail_action
                if preflight_detail_action is not None
                else "原执行停止已核验, 但缺少可安全复用的完整进度封存; "
                "ASE 平台需核对或修复封存流程, 完成后使用平台处理入口继续原需求。"
                "原执行没有可接纳的完成结果, 原现场和历史保留。"
                if observed_stop is not None
                else "工程证明尚不完整, 等待和现场保留; 查看缺项, "
                "由受控执行器补齐原调用停机、完整 checkpoint 或当前前提记录后重新调查"
            ),
            inspected_at=self.clock(),
            proof_sha256="0" * 64,
        )
        return proof.model_copy(update={"proof_sha256": proof.recompute_sha256()})

    @staticmethod
    def _require_proof_binding(
        proof: DeliveryWaitInvestigation, command: InspectDeliveryWait
    ) -> None:
        if (
            proof.work_item_id,
            proof.disposition_sha256,
            proof.task_intent_sha256,
            proof.source_revision,
            proof.checkpoint_sequence,
        ) != (
            command.work_item_id,
            command.expected_disposition_sha256,
            command.expected_task_intent_sha256,
            command.expected_source_revision,
            command.expected_checkpoint_sequence,
        ):
            raise DeliveryWaitRejected("工程决定不属于这份精确调查")

    def _require_decision_binding(
        self, prior: DeliveryResolution, command: ResolveDeliveryWait, *, automatic: bool = False
    ) -> None:
        if (
            prior.work_item_id,
            prior.expected_disposition_sha256,
            prior.expected_task_intent_sha256,
            prior.expected_source_revision,
            prior.expected_checkpoint_sequence,
            prior.proof_sha256,
            prior.resolution_kind,
            prior.operator_principal,
        ) != (
            command.work_item_id,
            command.expected_disposition_sha256,
            command.expected_task_intent_sha256,
            command.expected_source_revision,
            command.expected_checkpoint_sequence,
            command.proof_sha256,
            command.resolution_kind,
            None if automatic else self.principal,
        ):
            raise DeliveryWaitRejected("此等待已记录不同工程决定, 不能覆盖审计历史")
