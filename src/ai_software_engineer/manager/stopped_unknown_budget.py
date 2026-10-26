"""Public deterministic end of exhausted UNKNOWN work, with full retained input."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import cast

from pymysql.cursors import DictCursor

from ai_software_engineer.artifacts import ArtifactStore
from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryWaitHandling,
    DeliveryWaitInvestigation,
    HandleDeliveryWait,
)
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.stopped_unknown_budget import (
    STOPPED_UNKNOWN_BUDGET_REASON,
    StoppedUnknownBudgetSettlement,
)
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.execution_baseline import retained_source_paths_for_request
from ai_software_engineer.manager.stopped_budget_settlement import StoppedBudgetSettlementService
from ai_software_engineer.manager.stopped_execution_checkpoint import (
    StoppedCoderExecutionProof,
    read_stopped_coder_execution,
    require_stopped_coder_workspace,
)
from ai_software_engineer.manager.wait_fact_collection import DeliveryWaitFactCollector
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import ContinuationRejected
from ai_software_engineer.orchestration.state_machine import apply_event, build_event
from ai_software_engineer.store import TaskRepository
from ai_software_engineer.work_queue.execution_store import (
    AcceptedRoleArtifact,
    MySqlRoleQueue,
    QueuedRoleStep,
    record_digest,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard


def _capture_unknown(
    task: Task, stopped: StoppedCoderExecutionProof, *, state: Path, git: GitWorktreeManager
) -> tuple[str, CapturedMutations]:
    request = stopped.invocation_start.request
    if (
        request.permissions.can_merge
        or request.permissions.can_change_state
        or task.constraints is None
        or request.permissions.write_paths != task.constraints.allowed_paths
    ):
        raise ContinuationRejected("未知结果额度收尾的原权限与冻结任务不一致")
    worktree = git.recover(
        WorktreeSpec(
            task_id=task.id,
            role=AgentRole.CODER,
            attempt=1,
            source_revision=request.source_revision,
        )
    )
    if worktree.detached or str(worktree.path) != stopped.capture_start.worktree_path:
        raise ContinuationRejected("未知结果额度收尾的开发工作区身份已变化")
    snapshot = git.inspect(worktree)
    if snapshot.head_revision != request.source_revision:
        raise ContinuationRejected("未知结果额度收尾的开发基线已变化")
    inventory = capture_mutation_inventory(worktree.path)
    capture = CapturedMutations.from_capture(
        git.capture_mutations(
            worktree,
            request.permissions,
            denied_paths=task.constraints.denied_paths if task.constraints else (),
            retained_source_paths=retained_source_paths_for_request(
                state, task, request, worktree.path
            ),
        )
    )
    require_stopped_coder_workspace(
        stopped,
        capture,
        inventory,
        request.permissions,
        task.constraints.denied_paths if task.constraints else (),
    )
    if capture_mutation_inventory(worktree.path) != inventory:
        raise ContinuationRejected("封存期间未知结果执行的完整工作现场已变化")
    return inventory.sha256, capture


class StoppedUnknownBudgetSettlementService:
    """The caller supplies the exclusive Task lock and idle SQL authority scope."""

    def __init__(
        self,
        *,
        repository: TaskRepository,
        queue: MySqlRoleQueue,
        records: KnowledgeRecordStore,
        collector: DeliveryWaitFactCollector,
        git: GitWorktreeManager,
        artifacts: ArtifactStore,
        clock: Callable[[], datetime],
        idle_scope: Callable[[], AbstractContextManager[DictCursor]],
    ) -> None:
        self.repository, self.queue, self.records = repository, queue, records
        self.collector, self.git, self.artifacts = collector, git, artifacts
        self.clock, self.idle_scope = clock, idle_scope

    def _observe(
        self, task: Task, item: QueuedWorkItem, step: QueuedRoleStep, guard: WorkerExecutionGuard
    ) -> tuple[StoppedCoderExecutionProof, str, CapturedMutations] | None:
        if not guard.inherited_fds:
            raise ContinuationRejected("未知结果额度收尾缺少独占任务锁")
        stopped = read_stopped_coder_execution(
            task,
            item,
            step,
            expected_scope=self.collector.expected_continuation_scope,
            state=self.collector.state,
            route_root=self.collector.routes,
            repository=self.repository,
            queue=self.queue,
            artifacts=self.artifacts,
            permissions=self._permissions(item),
            task_lock=guard,
        )
        if stopped is None:
            return None
        inventory_sha, captured = _capture_unknown(
            task, stopped, state=self.collector.state, git=self.git
        )
        repeated = read_stopped_coder_execution(
            task,
            item,
            step,
            expected_scope=self.collector.expected_continuation_scope,
            state=self.collector.state,
            route_root=self.collector.routes,
            repository=self.repository,
            queue=self.queue,
            artifacts=self.artifacts,
            permissions=stopped.invocation_start.request.permissions,
            task_lock=guard,
        )
        if repeated != stopped:
            raise ContinuationRejected("封存期间原未知结果执行事实已变化")
        return stopped, inventory_sha, captured

    def _permissions(self, item: QueuedWorkItem) -> AgentPermissions:
        # Read only the actual original start. The complete reader independently
        # binds it to the capture, original claim and frozen queue permissions.
        from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart

        start = KnowledgeRecordStore(self.collector.state / "invocations", read_only=True).get(
            "invocation-starts", item.id, DeliveryInvocationStart
        )
        return start.request.permissions

    def replay(
        self, command: HandleDeliveryWait, guard: WorkerExecutionGuard
    ) -> DeliveryWaitHandling | None:
        result = self.records.find(
            "stopped-unknown-budget-handlings", digest(command.to_wire()), DeliveryWaitHandling
        )
        if result is None:
            return None
        result.validate_integrity()
        if result.budget_settlement_sha256 is None:
            raise ContinuationRejected("未知结果额度收尾处理记录缺少精确决定")
        settlement = self.records.get(
            "stopped-unknown-budget-settlements",
            result.budget_settlement_sha256,
            StoppedUnknownBudgetSettlement,
        )
        settlement.validate_integrity()
        StoppedBudgetSettlementService._bind(command, settlement.investigation)
        if (
            result.investigation != settlement.investigation
            or result.handled_at != settlement.event.occurred_at
        ):
            raise ContinuationRejected("未知结果额度收尾报告与精确决定不一致")
        with self.idle_scope() as cursor:

            def verify() -> None:
                if self.repository.get(settlement.task.id).status is TaskStatus.IMPLEMENTING:
                    self._require_observation(settlement, guard)
                else:
                    verify_settled_stopped_unknown(
                        settlement,
                        repository=self.repository,
                        queue=self.queue,
                        state=self.collector.state,
                        route_root=self.collector.routes,
                        artifacts=self.artifacts,
                        git=self.git,
                        guard=guard,
                    )

            verify()
            self.queue.settle_stopped_budget(cursor, settlement, validate_current=verify)
        self._publish_handling(result)
        return result

    def _publish_handling(self, result: DeliveryWaitHandling) -> None:
        """Publish the immutable dependency before its read-side reference.

        Exact replay reaches this only after validating the original settlement
        and current stopped facts, and can repair the released missing-reference
        omission without changing any existing result or execution history.
        """
        records = KnowledgeRecordStore(self.collector.state / "delivery-waits")
        records.put("wait-investigations", result.investigation.proof_sha256, result.investigation)
        records.put("wait-handlings", result.record_key, result)

    def _require_observation(
        self, settlement: StoppedUnknownBudgetSettlement, guard: WorkerExecutionGuard
    ) -> None:
        observed = self._observe(settlement.task, settlement.work_item, settlement.step, guard)
        if observed is None or (observed[0], observed[1], observed[2].capture_sha256) != (
            settlement.stopped_execution,
            settlement.inventory_sha256,
            settlement.retained_capture_sha256,
        ):
            raise ContinuationRejected("未知结果额度收尾前原执行或完整草稿已经变化")
        stored = self.records.get(
            "stopped-unknown-budget-captures", settlement.retained_capture_sha256, CapturedMutations
        )
        stored.to_capture()
        if stored != observed[2]:
            raise ContinuationRejected("未知结果额度收尾的完整草稿记录已变化")

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
            or item.wait_disposition.facts.classification != "EXECUTION_UNCERTAIN"
        ):
            return None
        StoppedBudgetSettlementService._bind(command, proof)
        with self.idle_scope() as cursor:
            observed = self._observe(task, item, step, guard)
            if observed is None:
                return None
            stopped, inventory_sha, captured = observed
            event = build_event(
                task,
                TaskStatus.BLOCKED,
                event_id="evt_unknown_budget_" + digest(command.to_wire())[:40],
                reason=STOPPED_UNKNOWN_BUDGET_REASON,
                source_revision=proof.source_revision,
                attempt=task.attempts,
                occurred_at=self.clock(),
            )
            closed = item.model_copy(
                update={
                    "status": WorkItemStatus.CLOSED,
                    "wait_reason": None,
                    "wait_disposition": None,
                    "available_at": None,
                    "updated_at": event.occurred_at,
                }
            )
            settlement = StoppedUnknownBudgetSettlement(
                task=task,
                investigation=proof,
                work_item=item,
                step=step,
                stopped_execution=stopped,
                expected_item_sha256=record_digest(item),
                closed_item_sha256=record_digest(closed),
                inventory_sha256=inventory_sha,
                retained_capture_sha256=captured.capture_sha256,
                event=event,
                settlement_sha256="0" * 64,
            )
            settlement = settlement.model_copy(
                update={"settlement_sha256": settlement.recompute_sha256()}
            )
            self.records.put("stopped-unknown-budget-captures", captured.capture_sha256, captured)
            self.records.put(
                "stopped-unknown-budget-settlements", settlement.settlement_sha256, settlement
            )
            result = DeliveryWaitHandling(
                task_id=task.id,
                work_item_id=item.id,
                disposition_sha256=proof.disposition_sha256,
                task_intent_sha256=proof.task_intent_sha256,
                source_revision=proof.source_revision,
                checkpoint_sequence=proof.checkpoint_sequence,
                investigation=proof,
                status="BUDGET_EXHAUSTED",
                summary=(
                    "原开发执行已实际停止, 结果保持 UNKNOWN; "
                    "本轮普通工作额度已耗尽, 完整进度已保留。"
                ),
                user_action=(
                    "在原需求详情准备恢复方案, 核对完整草稿和新执行基线并精确批准; 不需要新建需求。"
                ),
                recheck_when="精确批准恢复方案后继续; 旧调用 UNKNOWN 历史和已消费额度保留。",
                manual_resolution_allowed=False,
                handled_at=event.occurred_at,
                budget_settlement_sha256=settlement.settlement_sha256,
                handling_sha256="0" * 64,
            )
            result = result.model_copy(update={"handling_sha256": result.recompute_sha256()})
            self.records.put("stopped-unknown-budget-handlings", digest(command.to_wire()), result)
            self._require_observation(settlement, guard)
            self.queue.settle_stopped_budget(
                cursor,
                settlement,
                validate_current=lambda: self._require_observation(settlement, guard),
            )
        self._publish_handling(result)
        return result


class _PreSettlementRepository:
    """Exact historical view, only after its current reducer was independently verified."""

    def __init__(
        self, repository: TaskRepository, settlement: StoppedUnknownBudgetSettlement
    ) -> None:
        self.repository, self.settlement = repository, settlement

    def get(self, task_id: str) -> Task:
        if task_id != self.settlement.task.id:
            raise ContinuationRejected("未知结果收尾的原任务身份不一致")
        return self.settlement.task

    def current_revision(self, task_id: str) -> int:
        self.get(task_id)
        return self.settlement.investigation.task_revision

    def list_events(self, task_id: str) -> tuple[StateEvent, ...]:
        self.get(task_id)
        return self.repository.list_events(task_id)[:-1]


class _PreSettlementQueue:
    def __init__(self, queue: MySqlRoleQueue, settlement: StoppedUnknownBudgetSettlement) -> None:
        self.queue, self.settlement = queue, settlement

    def get(self, item_id: str) -> QueuedWorkItem:
        if item_id != self.settlement.work_item.id:
            raise ContinuationRejected("未知结果收尾的原工作项身份不一致")
        return self.settlement.work_item

    def step(self, item_id: str) -> QueuedRoleStep:
        self.get(item_id)
        return self.settlement.step

    def original_claim(self, lease_id: str) -> QueueClaim:
        return self.queue.original_claim(lease_id)

    def accepted(self, task_id: str) -> tuple[AcceptedRoleArtifact, ...]:
        return self.queue.accepted(task_id)

    def rejected_output_artifact_ids(self, task_id: str) -> frozenset[str]:
        return self.queue.rejected_output_artifact_ids(task_id)


def verify_settled_stopped_unknown(
    settlement: StoppedUnknownBudgetSettlement,
    *,
    repository: TaskRepository,
    queue: MySqlRoleQueue,
    state: Path,
    route_root: Path | None,
    artifacts: ArtifactStore,
    git: GitWorktreeManager,
    guard: WorkerExecutionGuard,
) -> CapturedMutations:
    """Read-only current stop, terminal reducer, absence facts and full retained input.

    The source caller also verifies its complete SQL snapshot/audit and holds the
    Task lock. No historical invocation outcome or route is reconstructed here.
    """
    settlement.validate_integrity()

    def current() -> None:
        events = repository.list_events(settlement.task.id)
        if (
            repository.get(settlement.task.id) != apply_event(settlement.task, settlement.event)
            or repository.current_revision(settlement.task.id)
            != settlement.investigation.task_revision + 1
            or not events
            or events[-1] != settlement.event
            or record_digest(queue.get(settlement.work_item.id)) != settlement.closed_item_sha256
            or queue.step(settlement.work_item.id) != settlement.step
        ):
            raise ContinuationRejected("未知结果额度收尾的当前终态或精确队列事实已变化")

    current()

    def read_original() -> StoppedCoderExecutionProof | None:
        return read_stopped_coder_execution(
            settlement.task,
            settlement.work_item,
            settlement.step,
            expected_scope=settlement.stopped_execution.capture_start.scope,
            state=state,
            route_root=route_root,
            repository=cast(TaskRepository, _PreSettlementRepository(repository, settlement)),
            queue=cast(MySqlRoleQueue, _PreSettlementQueue(queue, settlement)),
            artifacts=artifacts,
            permissions=settlement.stopped_execution.invocation_start.request.permissions,
            task_lock=guard,
        )

    stopped = read_original()
    if stopped != settlement.stopped_execution:
        raise ContinuationRejected("未知结果额度收尾的原执行停止事实已变化")
    inventory_sha, capture = _capture_unknown(settlement.task, stopped, state=state, git=git)
    sealed = KnowledgeRecordStore(state / "delivery-preflight", read_only=True).get(
        "stopped-unknown-budget-captures", settlement.retained_capture_sha256, CapturedMutations
    )
    sealed.to_capture()
    if (
        inventory_sha != settlement.inventory_sha256
        or capture != sealed
        or capture.capture_sha256 != settlement.retained_capture_sha256
    ):
        raise ContinuationRejected("未知结果额度收尾的完整保留进度已变化")
    if read_original() != stopped:
        raise ContinuationRejected("读取完整进度期间原未知结果执行事实已变化")
    current()
    return capture
