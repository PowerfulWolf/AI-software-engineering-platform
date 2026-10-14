"""Claimed prerequisite gate before the durable model invocation window."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from ai_software_engineer.agents.model_input import FinalModelInputCapacityExceeded
from ai_software_engineer.agents.models import AgentRequest, AgentResult
from ai_software_engineer.context.models import ContextBundle
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.native_verification import (
    NativeVerificationWaiting,
    NativeVerificationWaitReason,
)
from ai_software_engineer.domain.task import Task
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.context_capacity import ContextCapacityReceipt
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
        prepare_input: Callable[[AgentRequest], None] | None = None,
        discard_prepared_input: Callable[[AgentRequest], None] | None = None,
        context_reader: Callable[[str], ContextBundle] | None = None,
    ) -> None:
        self.delegate, self.guard, self.task_reader = delegate, guard, task_reader
        self.inspect, self.records, self.failure_control = inspect, records, failure_control
        if (prepare_verifier is None) != (observe_verifier is None):
            raise ValueError("verifier preparation requires its trusted execution observation")
        self.prepare_verifier, self.observe_verifier = prepare_verifier, observe_verifier
        self.resumed_preparation = resumed_preparation
        self.prepare_input, self.discard_prepared_input = prepare_input, discard_prepared_input
        self.context_reader = context_reader

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
                # Verification prerequisites belong to the QA/Reviewer role.
                # A legacy Plan may contain a verification entry that the
                # current host cannot execute, but that must not prevent the
                # Coder from producing the candidate needed to re-evaluate it.
                # The role-specific preparation gate below remains mandatory
                # before QA/Reviewer model input is started.
        elif (
            request.role in (AgentRole.QA, AgentRole.REVIEWER) and self.prepare_verifier is not None
        ):
            self._prepare_verifier(request)
        try:
            if self.prepare_input is not None:
                self.guard.check()
                self.prepare_input(request)
                self.guard.check()
            return self.delegate.prepare(request)
        except FinalModelInputCapacityExceeded as error:
            if self.discard_prepared_input is not None:
                self.discard_prepared_input(request)
            self._capacity_wait(request, error)
            raise
        except BaseException:
            if self.discard_prepared_input is not None:
                self.discard_prepared_input(request)
            raise

    def _capacity_wait(self, request: AgentRequest, error: FinalModelInputCapacityExceeded) -> None:
        if self.context_reader is None:
            # Existing custom compositions keep their original exception boundary.
            return
        self.guard.check()
        task = self.task_reader()
        assert self.guard.lease is not None
        claim = self.guard.lease.claim
        item = claim.work_item
        context = self.context_reader(request.context_manifest_id)
        if (
            (item.task_id, item.role, item.attempt)
            != (request.task_id, request.role, request.attempt)
            or task.id != request.task_id
            or (
                context.context_id,
                context.task_id,
                context.role,
                context.attempt,
                context.source_revision,
            )
            != (
                request.context_manifest_id,
                request.task_id,
                request.role,
                request.attempt,
                request.source_revision,
            )
            or context.budget.max_input_tokens != error.max_input_tokens
        ):
            raise QueueConflict("上下文容量检查与当前真实执行身份不一致; 未启动模型")
        marker = ContextCapacityReceipt(
            origin="final_input",
            task_id=task.id,
            task_sha256=digest(task.to_wire()),
            task_intent_sha256=task_intent_sha256(task),
            task_revision=item.checkpoint_sequence,
            work_item_id=item.id,
            lease_id=claim.lease.id,
            assignment_id=claim.assignment.id,
            claim_sha256=digest(claim.to_wire()),
            dispatch_sequence=item.dispatch_sequence,
            checkpoint_sequence=item.checkpoint_sequence,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=context.context_id,
            context_sha256=digest(context.to_wire()),
            max_input_tokens=context.budget.max_input_tokens,
            context_input_tokens=context.budget.used_input_tokens,
            final_input_tokens=error.estimated_input_tokens,
            request=request,
            execution_baseline_sha256=request.execution_baseline_sha256,
            observed_at=datetime.now(UTC),
            receipt_sha256="0" * 64,
        )
        marker = marker.model_copy(
            update={
                "receipt_sha256": digest(marker.model_dump(mode="json", exclude={"receipt_sha256"}))
            }
        )
        marker.validate_integrity()
        with self.guard.write_scope():
            if self.delegate.has_started(request) or self.delegate.result(request) is not None:
                raise QueueConflict("当前执行已有模型开始或结果记录; 不能记为未启动容量等待")
            self.records.put("context-capacity-receipts", marker.receipt_sha256, marker)
        self.failure_control.wait(
            task,
            classification="CONTEXT_CAPACITY",
            reason="最终模型输入超过平台容量; 本次交付角色的模型调用未启动, "
            "原任务、完整输入与开发进度已保留。平台调整输入装配后需精确核验再继续。",
            source_revision=request.source_revision,
            artifact_ids=("context-capacity://" + marker.receipt_sha256,),
        )

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
