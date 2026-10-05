"""Claimed prerequisite gate before the durable model invocation window."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from ai_software_engineer.agents.models import AgentRequest, AgentResult
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.native_verification import (
    NativeVerificationWaiting,
    NativeVerificationWaitReason,
)
from ai_software_engineer.domain.task import Task
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.delivery_preflight import (
    DeliveryPreflightCheckpoint,
    DeliveryPreflightReceipt,
)
from ai_software_engineer.manager.verifier_preparation import (
    VerifierPreparationCheckpoint,
    VerifierPreparationIntent,
    VerifierPreparationObservation,
)
from ai_software_engineer.work_queue.invocation import DurableInvocationControl
from ai_software_engineer.work_queue.models import QueueClaim
from ai_software_engineer.work_queue.ports import QueueConflict
from ai_software_engineer.work_queue.worker import (
    WorkerDeliveryFailureControl,
    WorkerExecutionGuard,
)


class PreflightInvocationControl:
    def __init__(
        self,
        *,
        delegate: DurableInvocationControl,
        guard: WorkerExecutionGuard,
        task_reader: Callable[[], Task],
        inspect: Callable[[Task, str], DeliveryPreflightReceipt | None],
        records: KnowledgeRecordStore,
        failure_control: WorkerDeliveryFailureControl,
        prepare_verifier: Callable[[AgentRequest], None] | None = None,
        observe_verifier: Callable[[AgentRequest, str], VerifierPreparationObservation]
        | None = None,
        resumed_preparation: Callable[[VerifierPreparationIntent, QueueClaim], bool] | None = None,
    ) -> None:
        self.delegate, self.guard, self.task_reader = delegate, guard, task_reader
        self.inspect, self.records, self.failure_control = inspect, records, failure_control
        if (prepare_verifier is None) != (observe_verifier is None):
            raise ValueError("verifier preparation requires its trusted execution observation")
        self.prepare_verifier, self.observe_verifier = prepare_verifier, observe_verifier
        self.resumed_preparation = resumed_preparation

    def prepare(self, request: AgentRequest) -> AgentRequest:
        if self.delegate.has_started(request):
            return self.delegate.prepare(request)
        if request.role is AgentRole.CODER:
            self.guard.check()
            task = self.task_reader()
            receipt = self.inspect(task, request.source_revision)
            if receipt is not None:
                receipt.validate_integrity()
                assert self.guard.lease is not None
                claim = self.guard.lease.claim
                checkpoint = DeliveryPreflightCheckpoint(
                    work_item_id=claim.work_item.id,
                    lease_id=claim.lease.id,
                    task_id=task.id,
                    task_snapshot_sha256=digest(task.to_wire()),
                    checkpoint_sequence=claim.work_item.checkpoint_sequence,
                    source_revision=request.source_revision,
                    receipt_sha256=receipt.receipt_sha256,
                    checked_at=receipt.checked_at,
                    checkpoint_sha256="0" * 64,
                )
                checkpoint = checkpoint.model_copy(
                    update={
                        "checkpoint_sha256": digest(
                            checkpoint.model_dump(mode="json", exclude={"checkpoint_sha256"})
                        ),
                    }
                )
                with self.guard.write_scope():
                    self.records.put("preflight-receipts", receipt.receipt_sha256, receipt)
                    self.records.put(
                        "preflight-checkpoints",
                        claim.work_item.id + ":" + receipt.receipt_sha256,
                        checkpoint,
                    )
                if receipt.status != "READY":
                    self.failure_control.wait(
                        task,
                        classification="ENVIRONMENT_UNAVAILABLE",
                        reason=_preflight_wait_summary(receipt),
                        source_revision=request.source_revision,
                        artifact_ids=("delivery-preflight://" + receipt.receipt_sha256,),
                    )
        elif (
            request.role in (AgentRole.QA, AgentRole.REVIEWER) and self.prepare_verifier is not None
        ):
            self._prepare_verifier(request)
        return self.delegate.prepare(request)

    def _prepare_verifier(self, request: AgentRequest) -> None:
        assert self.prepare_verifier is not None and self.observe_verifier is not None
        self.guard.check()
        task = self.task_reader()
        assert self.guard.lease is not None
        claim = self.guard.lease.claim
        prior_intents = tuple(
            value
            for value in self.records.list(
                "verifier-preparation-intents", VerifierPreparationIntent
            )
            if value.work_item_id == claim.work_item.id
            and value.checkpoint_sequence == claim.work_item.checkpoint_sequence
        )
        for value in prior_intents:
            value.validate_integrity()
        intent = max(prior_intents, key=lambda value: value.dispatch_sequence, default=None)
        if intent is not None:
            intent.validate_integrity()
            if (
                (
                    intent.work_item_id,
                    intent.task_id,
                    intent.task_snapshot_sha256,
                    intent.checkpoint_sequence,
                )
                != (
                    claim.work_item.id,
                    task.id,
                    digest(task.to_wire()),
                    claim.work_item.checkpoint_sequence,
                )
                or intent.dispatch_sequence > claim.work_item.dispatch_sequence
                or intent.request.model_dump(mode="json", exclude={"run_id", "context_manifest_id"})
                != request.model_dump(mode="json", exclude={"run_id", "context_manifest_id"})
            ):
                raise QueueConflict("原验证准备意图与当前任务或精确执行输入不一致。现场已保留。")
        if intent is None or (
            claim.work_item.dispatch_sequence > intent.dispatch_sequence
            and self.resumed_preparation is not None
            and self.resumed_preparation(intent, claim)
        ):
            intent = VerifierPreparationIntent.create(
                work_item_id=claim.work_item.id,
                lease_id=claim.lease.id,
                task_id=task.id,
                task_snapshot_sha256=digest(task.to_wire()),
                checkpoint_sequence=claim.work_item.checkpoint_sequence,
                dispatch_sequence=claim.work_item.dispatch_sequence,
                request=request,
                request_sha256=digest(request.to_wire()),
                started_at=datetime.now(UTC),
            )
            key = (
                f"{claim.work_item.id}:{claim.work_item.checkpoint_sequence}:"
                f"{claim.work_item.dispatch_sequence}"
            )
            with self.guard.write_scope():
                self.records.put("verifier-preparation-intents", key, intent)
        failure: NativeVerificationWaitReason | None = None
        if intent.lease_id != claim.lease.id or intent.request != request:
            # A crash may precede the model start and the final preparation marker.
            # The original durable intent, not a fresh Run namespace, is observed.
            request = intent.request
            failure = NativeVerificationWaitReason.FACTS_CHANGED
        else:
            try:
                self.prepare_verifier(request)
            except NativeVerificationWaiting as error:
                failure = error.reason
        self.guard.check()
        observation = self.observe_verifier(request, intent.lease_id)
        if observation.native_execution_state == "UNCERTAIN":
            failure = NativeVerificationWaitReason.EXECUTION_UNCERTAIN
        marker = VerifierPreparationCheckpoint.create(
            work_item_id=claim.work_item.id,
            lease_id=intent.lease_id,
            task_id=task.id,
            task_snapshot_sha256=digest(task.to_wire()),
            checkpoint_sequence=claim.work_item.checkpoint_sequence,
            dispatch_sequence=intent.dispatch_sequence,
            wait_dispatch_sequence=claim.work_item.dispatch_sequence,
            wait_lease_id=claim.lease.id,
            intent_sha256=intent.intent_sha256,
            source_revision=request.source_revision,
            run_id=request.run_id,
            role=request.role,
            attempt=request.attempt,
            context_manifest_id=request.context_manifest_id,
            request_sha256=digest(request.to_wire()),
            request=request,
            result="READY" if failure is None else "WAIT",
            observation=observation,
            failure_reason=failure,
            checked_at=datetime.now(UTC),
        )
        with self.guard.write_scope():
            self.records.put("verifier-preparations", marker.checkpoint_sha256, marker)
        if failure is not None:
            classification: Literal[
                "EXECUTION_UNCERTAIN",
                "ENGINEERING_AUTHORIZATION",
                "ENVIRONMENT_UNAVAILABLE",
            ] = (
                "EXECUTION_UNCERTAIN"
                if observation.native_execution_state == "UNCERTAIN"
                else "ENGINEERING_AUTHORIZATION"
                if failure
                in {
                    NativeVerificationWaitReason.FACTS_CHANGED,
                    NativeVerificationWaitReason.LEGACY_AUTHORITY,
                }
                else "ENVIRONMENT_UNAVAILABLE"
            )
            self.failure_control.wait(
                task,
                classification=classification,
                reason=(
                    "原验证准备已结束。角色模型尚未启动。工程负责人需核验当前前提和工作额度。"
                    "重新领取独立验收。"
                    if observation.native_execution_state == "FINISHED"
                    and observation.native_failure_code is None
                    else "验证准备尚未完成。原任务候选和角色记录已保留。工程处理需核验"
                    "精确执行事实。" + _preparation_reason(failure)
                ),
                source_revision=request.source_revision,
                artifact_ids=("verifier-preparation://" + marker.checkpoint_sha256,),
            )

    def result(self, request: AgentRequest) -> AgentResult | None:
        return self.delegate.result(request)

    def completed(self, request: AgentRequest, result: AgentResult) -> None:
        self.delegate.completed(request, result)


def _preparation_reason(reason: NativeVerificationWaitReason) -> str:
    labels = {
        NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE: "注册验证能力的当前工具或环境不可用。",
        NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT: "计划验证入口没有对应的注册执行能力。",
        NativeVerificationWaitReason.UNSUPPORTED_SWIFT_FILTER: (
            "现有验证能力不能执行指定的 Swift 测试过滤。"
        ),
        NativeVerificationWaitReason.NATIVE_UI_PREREQUISITE: "原生界面验证前提尚未满足。",
        NativeVerificationWaitReason.FACTS_CHANGED: "候选、权限或原角色执行事实发生变化。",
        NativeVerificationWaitReason.LEGACY_AUTHORITY: "现有授权没有覆盖当前验证能力。",
        NativeVerificationWaitReason.EXECUTION_UNCERTAIN: (
            "受控验证已开始。但没有确定的完成记录。禁止重复执行。"
        ),
        NativeVerificationWaitReason.COMMAND_TIMEOUT: (
            "受控验证命令已超时。需按封存结果处理验证重试。"
        ),
        NativeVerificationWaitReason.COMMAND_START_FAILED: "受控验证命令或隔离资源未能正常启动。",
    }
    return labels[reason]


def _preflight_wait_summary(receipt: DeliveryPreflightReceipt) -> str:
    labels = {
        "VERIFICATION_ENTRYPOINTS_REQUIRED": "执行计划尚未提供可执行的验收入口。",
        "VERIFICATION_INSPECTION_AUTHORIZATION_REQUIRED": "源码检查路径超出当前角色权限。",
        "VERIFICATION_INSPECTION_FILE_MISSING": "源码检查目标缺失且未列入本轮新增文件计划。",
        "CONTROLLED_VERIFICATION_CAPABILITY_REQUIRED": "所需验证能力尚未注册或当前环境不可用。",
        "VERIFICATION_COMMAND_AUTHORIZATION_REQUIRED": "验证命令尚未满足增量范围和执行权限要求。",
        "VERIFICATION_SELECTED_FILE_MISSING": "所选测试文件缺失且未列入本轮新增文件计划。",
        "VERIFICATION_EXECUTABLE_UNAVAILABLE": "验证命令所需工具当前不可用。",
    }
    explanations = dict.fromkeys(
        _preparation_reason(item.native_wait_reason)
        if item.native_wait_reason is not None
        else labels.get(item.reason_code, "验证前提核验尚未通过。")
        for item in receipt.observations
        if item.status != "READY"
    )
    return (
        "实施前验证前提尚未满足。"
        + "".join(explanations)
        + "工程负责人需处理所列前提。平台保留原交付检查点并等待重新核验。"
    )
