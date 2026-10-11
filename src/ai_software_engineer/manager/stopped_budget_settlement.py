"""Public HANDLE may safely end a misrouted, exhausted and actually stopped Task."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol

from pymysql.cursors import DictCursor

from ai_software_engineer.agents.models import AgentRunStatus
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryWaitHandling,
    DeliveryWaitInvestigation,
    HandleDeliveryWait,
)
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.stopped_budget_settlement import StoppedFailureBudgetSettlement
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.wait_fact_collection import DeliveryWaitFactCollector
from ai_software_engineer.orchestration.continuation_models import ContinuationRejected
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.store import TaskRepository
from ai_software_engineer.work_queue.execution_store import QueuedRoleStep, record_digest
from ai_software_engineer.work_queue.models import QueuedWorkItem
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard


class SettlementQueue(Protocol):
    def get(self, work_item_id: str) -> QueuedWorkItem: ...
    def step(self, work_item_id: str) -> QueuedRoleStep: ...
    def settle_stopped_budget(
        self, cursor: DictCursor, settlement: StoppedFailureBudgetSettlement
    ) -> None: ...


class StoppedBudgetSettlementService:
    """Caller holds the Task process lock and supplies the queue's idle SQL scope."""

    def __init__(
        self,
        *,
        repository: TaskRepository,
        queue: SettlementQueue,
        records: KnowledgeRecordStore,
        collector: DeliveryWaitFactCollector,
        git: GitWorktreeManager,
        clock: Callable[[], datetime],
        idle_scope: Callable[[], AbstractContextManager[DictCursor]],
    ) -> None:
        self.repository, self.queue, self.records = repository, queue, records
        self.collector, self.git, self.clock = collector, git, clock
        self.idle_scope = idle_scope

    def replay(
        self, command: HandleDeliveryWait, guard: WorkerExecutionGuard
    ) -> DeliveryWaitHandling | None:
        key = digest(command.to_wire())
        record = self.records.find("stopped-budget-handlings", key, DeliveryWaitHandling)
        if record is None:
            return None
        record.validate_integrity()
        if record.budget_settlement_sha256 is None:
            raise ContinuationRejected("额度收尾处理记录缺少精确决定")
        settlement = self.records.get(
            "stopped-budget-settlements",
            record.budget_settlement_sha256,
            StoppedFailureBudgetSettlement,
        )
        settlement.validate_integrity()
        if (
            record.investigation != settlement.investigation
            or record.handled_at != settlement.event.occurred_at
        ):
            raise ContinuationRejected("额度收尾报告与已封存决定不一致")
        self._bind(command, settlement.investigation)
        self._consume(settlement, guard)
        self.records.put("wait-handlings", record.record_key, record)
        return record

    def try_settle(
        self,
        command: HandleDeliveryWait,
        task: Task,
        item: QueuedWorkItem,
        step: QueuedRoleStep,
        proof: DeliveryWaitInvestigation,
        guard: WorkerExecutionGuard,
    ) -> DeliveryWaitHandling | None:
        if (
            task.status is not TaskStatus.IMPLEMENTING
            or not task.work_budget_exhausted
            or item.role is not AgentRole.CODER
            or item.wait_disposition is None
            or item.wait_disposition.facts.classification
            not in {"TRANSIENT_INFRA", "NONTRANSIENT_INFRA"}
        ):
            return None
        with self.idle_scope() as cursor:
            handling = self._settle_locked(command, task, item, step, proof, guard, cursor)
        if handling is not None:
            self.records.put("wait-handlings", handling.record_key, handling)
        return handling

    def _settle_locked(
        self,
        command: HandleDeliveryWait,
        task: Task,
        item: QueuedWorkItem,
        step: QueuedRoleStep,
        proof: DeliveryWaitInvestigation,
        guard: WorkerExecutionGuard,
        cursor: DictCursor,
    ) -> DeliveryWaitHandling | None:
        self._bind(command, proof)
        # The record must be frozen before SQL consumption; publication is then
        # replayable after a crash on either side of the atomic transaction.
        observation = self._observation(task, step, guard)
        if observation is None:
            return None
        start_sha, outcome_sha, capture_sha, stop_sha, inventory_sha, retained_sha = observation
        event = build_event(
            task,
            TaskStatus.BLOCKED,
            event_id="evt_stopped_budget_" + digest(command.to_wire())[:40],
            reason=(
                "BUDGET_EXHAUSTED: 原开发执行已失败并实际停止, 普通执行额度耗尽; "
                "原需求与完整进度保留, 请准备恢复方案后精确批准。"
            ),
            source_revision=proof.source_revision,
            attempt=task.attempts,
            occurred_at=self.clock(),
        )
        settlement = StoppedFailureBudgetSettlement(
            task=task,
            investigation=proof,
            expected_item_sha256=record_digest(item),
            closed_item_sha256=record_digest(
                item.model_copy(
                    update={
                        "status": WorkItemStatus.CLOSED,
                        "wait_reason": None,
                        "wait_disposition": None,
                        "available_at": None,
                        "updated_at": event.occurred_at,
                    }
                )
            ),
            invocation_start_sha256=start_sha,
            invocation_outcome_sha256=outcome_sha,
            capture_start_sha256=capture_sha,
            capture_stop_sha256=stop_sha,
            inventory_sha256=inventory_sha,
            retained_capture_sha256=retained_sha,
            event=event,
            settlement_sha256="0" * 64,
        )
        settlement = settlement.model_copy(
            update={"settlement_sha256": settlement.recompute_sha256()}
        )
        self.records.put("wait-investigations", proof.proof_sha256, proof)
        settlement = self.records.put(
            "stopped-budget-settlements", settlement.settlement_sha256, settlement
        )
        handling = DeliveryWaitHandling(
            task_id=task.id,
            work_item_id=item.id,
            disposition_sha256=proof.disposition_sha256,
            task_intent_sha256=proof.task_intent_sha256,
            source_revision=proof.source_revision,
            checkpoint_sequence=proof.checkpoint_sequence,
            investigation=proof,
            status="BUDGET_EXHAUSTED",
            summary="原开发执行已停止, 本轮任务的普通执行额度已耗尽。原需求与完整开发进度已保留。",
            user_action=(
                "在原需求详情准备恢复方案, 核对保留的进度和执行基线后批准继续; 不需要新建需求。"
            ),
            recheck_when="恢复方案获精确批准后继续; 重复处理不会增加旧任务额度。",
            manual_resolution_allowed=False,
            handled_at=event.occurred_at,
            budget_settlement_sha256=settlement.settlement_sha256,
            handling_sha256="0" * 64,
        )
        handling = handling.model_copy(update={"handling_sha256": handling.recompute_sha256()})
        key = digest(command.to_wire())
        self.records.put("stopped-budget-handlings", key, handling)
        self.queue.settle_stopped_budget(cursor, settlement)
        return handling

    @staticmethod
    def _bind(command: HandleDeliveryWait, proof: DeliveryWaitInvestigation) -> None:
        if (
            command.work_item_id,
            command.expected_disposition_sha256,
            command.expected_task_intent_sha256,
            command.expected_source_revision,
            command.expected_checkpoint_sequence,
        ) != (
            proof.work_item_id,
            proof.disposition_sha256,
            proof.task_intent_sha256,
            proof.source_revision,
            proof.checkpoint_sequence,
        ):
            raise ContinuationRejected("额度收尾记录未绑定本次原等待")

    def _consume(
        self, settlement: StoppedFailureBudgetSettlement, guard: WorkerExecutionGuard
    ) -> None:
        if not guard.inherited_fds:
            raise ContinuationRejected("额度收尾缺少独占任务锁")
        from ai_software_engineer.orchestration.continuation_capture import CapturedMutations

        capture = self.records.get(
            "stopped-budget-captures", settlement.retained_capture_sha256, CapturedMutations
        )
        capture.to_capture()
        if (
            capture.capture_sha256 != settlement.retained_capture_sha256
            or capture.task_id != settlement.task.id
        ):
            raise ContinuationRejected("额度收尾的完整草稿记录已变化")
        with self.idle_scope() as cursor:
            if self.repository.get(settlement.task.id).status is TaskStatus.IMPLEMENTING:
                observed = self._observation(
                    settlement.task, self.queue.step(settlement.investigation.work_item_id), guard
                )
                expected = (
                    settlement.invocation_start_sha256,
                    settlement.invocation_outcome_sha256,
                    settlement.capture_start_sha256,
                    settlement.capture_stop_sha256,
                    settlement.inventory_sha256,
                    settlement.retained_capture_sha256,
                )
                if observed != expected:
                    raise ContinuationRejected("额度收尾之前原执行或完整现场已经变化")
            self.queue.settle_stopped_budget(cursor, settlement)

    def _observation(
        self, task: Task, step: QueuedRoleStep, guard: WorkerExecutionGuard
    ) -> tuple[str, str, str, str, str, str] | None:
        observed = self.collector.stopped_failed_capture(task, step, guard)
        if observed is None:
            return None
        start, outcome, capture, stop = observed
        result = outcome.result
        if (
            result.status is not AgentRunStatus.FAILED
            or result.artifact is not None
            or result.error is None
            or result.error.transient
            or stop.process_stop.kind != "failed"
            or stop.process_stop.returncode in {None, 0}
            or stop.output_present
            or stop.cause is not None
            or stop.original_error_code is not result.error.code
        ):
            return None
        worktree = self.git.recover(
            WorktreeSpec(
                task_id=task.id,
                role=AgentRole.CODER,
                attempt=1,
                source_revision=start.request.source_revision,
            )
        )
        if worktree.detached or str(worktree.path) != capture.worktree_path:
            raise ContinuationRejected("额度收尾的工作区已不属于原开发执行")
        snapshot = self.git.inspect(worktree)
        if snapshot.head_revision != start.request.source_revision:
            raise ContinuationRejected("额度收尾的开发基线已变化")
        inventory = capture_mutation_inventory(worktree.path)
        if inventory != capture.inventory_before:
            raise ContinuationRejected("原失败调用之后完整工作现场已变化, 暂不能额度收尾")
        retained = self.git.capture_mutations(
            worktree,
            start.request.permissions,
            denied_paths=task.constraints.denied_paths if task.constraints else (),
        )
        from ai_software_engineer.manager.completed_output_checkpoint import (
            require_stopped_execution_workspace,
            validate_stopped_execution_capture,
        )
        from ai_software_engineer.orchestration.continuation_capture import CapturedMutations

        captured = CapturedMutations.from_capture(retained)
        validate_stopped_execution_capture(
            start.request, capture, captured, inventory, start.request.permissions
        )
        require_stopped_execution_workspace(
            start.request,
            capture,
            inventory,
            task.constraints.denied_paths if task.constraints else (),
        )
        if capture_mutation_inventory(worktree.path) != inventory:
            raise ContinuationRejected("封存期间完整工作现场已变化")
        if self.collector.stopped_failed_capture(task, step, guard) != observed:
            raise ContinuationRejected("封存期间原执行停止或结果记录已变化")
        self.records.put("stopped-budget-captures", captured.capture_sha256, captured)
        retained_sha = captured.capture_sha256
        return (
            start.start_sha256,
            outcome.outcome_sha256,
            capture.start_sha256,
            stop.observation_sha256,
            inventory.sha256,
            retained_sha,
        )
