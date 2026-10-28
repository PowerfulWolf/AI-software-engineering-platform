"""Contain exhausted start-only Coder work without fabricating its final result."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import cast

from pymysql.cursors import DictCursor

from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore
from ai_software_engineer.artifacts import ArtifactStore
from ai_software_engineer.domain.contained_unknown_budget import (
    CONTAINED_UNKNOWN_BUDGET_REASON,
    ContainedUnknownBudgetSettlement,
    LocalStopConfirmation,
)
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryWaitHandling,
    DeliveryWaitInvestigation,
    HandleDeliveryWait,
)
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal, OperatorDuty
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.task import Task
from ai_software_engineer.evaluation import FileEvaluationEventStore
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.completed_output_checkpoint import (
    require_stopped_execution_workspace,
    validate_stopped_execution_capture,
)
from ai_software_engineer.manager.execution_baseline import retained_source_paths_for_request
from ai_software_engineer.manager.legacy_audit import contained_unknown_human_event
from ai_software_engineer.manager.legacy_containment import (
    LegacyExecutionContainment,
    LocalBootObserver,
    TrustedLocalBootObserver,
)
from ai_software_engineer.manager.legacy_local_execution import LegacyLocalExecutionObserver
from ai_software_engineer.manager.stopped_budget_settlement import StoppedBudgetSettlementService
from ai_software_engineer.manager.wait_fact_collection import DeliveryWaitFactCollector
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRecordMissing,
    ContinuationRejected,
    ExecutionCaptureStart,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.orchestration.state_machine import apply_event, build_event
from ai_software_engineer.store import TaskRepository
from ai_software_engineer.work_queue.execution_store import (
    AcceptedRoleArtifact,
    MySqlRoleQueue,
    QueuedRoleStep,
    record_digest,
)
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard


def _read_start_only(
    task: Task,
    item: QueuedWorkItem,
    step: QueuedRoleStep,
    *,
    collector: DeliveryWaitFactCollector,
    repository: TaskRepository,
    queue: MySqlRoleQueue,
    artifacts: ArtifactStore,
    guard: WorkerExecutionGuard,
) -> tuple[DeliveryInvocationStart, ExecutionCaptureStart, QueueClaim] | None:
    if not guard.inherited_fds:
        raise ContinuationRejected("start-only 隔离缺少独占 Task 锁")
    records = KnowledgeRecordStore(collector.state / "invocations", read_only=True)
    start = records.find("invocation-starts", item.id, DeliveryInvocationStart)
    if start is None:
        return None
    request = start.request
    ledger = FileContinuationStore(collector.state / "continuations" / task.id, task_id=task.id)
    try:
        capture_start = ledger.capture_start(request.run_id)
    except ContinuationRecordMissing:
        return None
    capture_start.validate_integrity()
    claim = queue.original_claim(start.lease_id)
    policy = task.interruption_continuation_policy
    if (
        task.status is not TaskStatus.IMPLEMENTING
        or not task.work_budget_exhausted
        or item.role is not AgentRole.CODER
        or item.status not in {WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY}
        or item.wait_disposition is None
        or item.wait_disposition.facts.classification != "EXECUTION_UNCERTAIN"
        or request.role is not AgentRole.CODER
        or claim.model_selection.route_kind != "codex_cli"
        or request.task_id != task.id
        or request.attempt != task.attempts
        or request.source_revision != step.boundary.source_revision
        or request.permissions.can_merge
        or request.permissions.can_change_state
        or task.constraints is None
        or request.permissions.write_paths != task.constraints.allowed_paths
        or task_intent_sha256(task) != capture_start.task_intent_sha256
        or policy is None
        or capture_start.policy_sha256 != policy.policy_sha256
        or capture_start.scope != collector.expected_continuation_scope
        or capture_start.request != request
        or capture_start.started_at < start.started_at
        or claim.claimed_at > start.started_at
        or capture_start.task_revision != repository.current_revision(task.id)
        or capture_start.claim.work_item.id != item.id
        or capture_start.claim.work_item != claim.work_item
        or capture_start.claim.lease.id != start.lease_id
        or capture_start.claim.assignment != claim.assignment
        or capture_start.claim.model_selection != claim.model_selection
        or capture_start.claim.worker_id != claim.worker_id
        or capture_start.claim.claimed_at != claim.claimed_at
        or capture_start.claim.lease.model_dump(exclude={"expires_at"})
        != claim.lease.model_dump(exclude={"expires_at"})
        or start.work_item_id != item.id
        or start.checkpoint_sequence != item.checkpoint_sequence
        or start.checkpoint_sequence != step.boundary.checkpoint_sequence
        or claim.work_item.task_id != task.id
        or claim.work_item.id != item.id
        or repository.get(task.id) != task
        or queue.get(item.id) != item
        or queue.step(item.id) != step
        or records.get("invocation-starts", item.id, DeliveryInvocationStart) != start
        or records.find("invocation-outcomes", item.id, DeliveryInvocationOutcome) is not None
        or any(
            receipt.request.run_id == request.run_id
            for receipt in ledger.receipts_for_task(task.id)
        )
        or any(
            artifact.producer.run_id == request.run_id
            for artifact in artifacts.list_for_task(task.id)
        )
        or any(
            publication.work_item_id == item.id or publication.run_id == request.run_id
            for publication in queue.accepted(task.id)
        )
        or any(
            event.artifact_ids
            for event in repository.list_events(task.id)[capture_start.task_revision :]
        )
    ):
        raise ContinuationRejected("start-only 隔离的原调用、claim、冻结权限或当前队列已变化")
    try:
        ledger.capture_stop(request.run_id)
    except ContinuationRecordMissing:
        pass
    else:
        raise ContinuationRejected("原执行已有 capture-stop, 不得转用人工 start-only 隔离")
    if (
        collector.routes is not None
        and collector.routes.is_dir()
        and FileModelRouteAttemptStore(collector.routes, read_only=True).list_for_run(
            request.run_id
        )
    ):
        raise ContinuationRejected("原执行已有路由结果, 不得转用人工 start-only 隔离")
    return start, capture_start, claim


def _capture_start_only(
    task: Task,
    capture_start: ExecutionCaptureStart,
    *,
    state: Path,
    git: GitWorktreeManager,
) -> tuple[str, CapturedMutations]:
    request = capture_start.request
    worktree = git.recover(
        WorktreeSpec(
            task_id=task.id,
            role=AgentRole.CODER,
            attempt=1,
            source_revision=request.source_revision,
        )
    )
    if worktree.detached or str(worktree.path) != capture_start.worktree_path:
        raise ContinuationRejected("start-only 隔离的 Coder 工作区身份已变化")
    if git.inspect(worktree).head_revision != request.source_revision:
        raise ContinuationRejected("start-only 隔离的 Coder Git 基线已变化")
    inventory = capture_mutation_inventory(worktree.path)
    captured = CapturedMutations.from_capture(
        git.capture_mutations(
            worktree,
            request.permissions,
            denied_paths=task.constraints.denied_paths if task.constraints else (),
            retained_source_paths=retained_source_paths_for_request(
                state, task, request, worktree.path
            ),
        )
    )
    validate_stopped_execution_capture(
        request, capture_start, captured, inventory, request.permissions
    )
    require_stopped_execution_workspace(
        request, capture_start, inventory, task.constraints.denied_paths if task.constraints else ()
    )
    if capture_mutation_inventory(worktree.path) != inventory:
        raise ContinuationRejected("封存期间 start-only 工作现场变化")
    return inventory.sha256, captured


class ContainedUnknownBudgetSettlementService:
    """Owns the exact local stop declaration and old Task terminal settlement."""

    def __init__(
        self,
        *,
        repository: TaskRepository,
        queue: MySqlRoleQueue,
        records: KnowledgeRecordStore,
        collector: DeliveryWaitFactCollector,
        git: GitWorktreeManager,
        artifacts: ArtifactStore,
        principal: LocalOperatorPrincipal,
        boot_observer: LocalBootObserver,
        local_execution_observer: LegacyLocalExecutionObserver,
        evaluation_root: Path,
        clock: Callable[[], datetime],
        idle_scope: Callable[[], AbstractContextManager[DictCursor]],
    ) -> None:
        self.repository, self.queue, self.records = repository, queue, records
        self.collector, self.git, self.artifacts = collector, git, artifacts
        self.principal, self.boot_observer = principal, boot_observer
        self.local_execution_observer = local_execution_observer
        self.evaluation_root = evaluation_root
        self.clock, self.idle_scope = clock, idle_scope

    def _observe(
        self, task: Task, item: QueuedWorkItem, step: QueuedRoleStep, guard: WorkerExecutionGuard
    ) -> (
        tuple[DeliveryInvocationStart, ExecutionCaptureStart, QueueClaim, str, CapturedMutations]
        | None
    ):
        source = _read_start_only(
            task,
            item,
            step,
            collector=self.collector,
            repository=self.repository,
            queue=self.queue,
            artifacts=self.artifacts,
            guard=guard,
        )
        if source is None:
            return None
        start, capture_start, claim = source
        inventory_sha, captured = _capture_start_only(
            task, capture_start, state=self.collector.state, git=self.git
        )
        repeated = _read_start_only(
            task,
            item,
            step,
            collector=self.collector,
            repository=self.repository,
            queue=self.queue,
            artifacts=self.artifacts,
            guard=guard,
        )
        if repeated != source:
            raise ContinuationRejected("封存期间 start-only 原执行事实已变化")
        return start, capture_start, claim, inventory_sha, captured

    def eligible(
        self, task: Task, item: QueuedWorkItem, step: QueuedRoleStep, guard: WorkerExecutionGuard
    ) -> bool:
        return self._observe(task, item, step, guard) is not None

    def replay(
        self, command: HandleDeliveryWait, guard: WorkerExecutionGuard
    ) -> DeliveryWaitHandling | None:
        result = self.records.find(
            "contained-unknown-budget-handlings", digest(command.to_wire()), DeliveryWaitHandling
        )
        if result is None:
            return None
        result.validate_integrity()
        if result.budget_settlement_sha256 is None:
            raise ContinuationRejected("start-only 收尾处理记录缺少精确决定")
        settlement = self.records.get(
            "contained-unknown-budget-settlements",
            result.budget_settlement_sha256,
            ContainedUnknownBudgetSettlement,
        )
        settlement.validate_integrity()
        self._bind_command(command, settlement)
        if (
            result.investigation != settlement.investigation
            or result.handled_at != settlement.event.occurred_at
        ):
            raise ContinuationRejected("start-only 收尾报告与精确决定不一致")
        with self.idle_scope() as cursor:
            if self.repository.get(settlement.task.id).status is TaskStatus.IMPLEMENTING:
                self._require_observation(settlement, guard)
            else:
                verify_settled_contained_unknown(
                    settlement,
                    repository=self.repository,
                    queue=self.queue,
                    state=self.collector.state,
                    route_root=self.collector.routes,
                    artifacts=self.artifacts,
                    git=self.git,
                    guard=guard,
                    boot_observer=self.boot_observer,
                    local_execution_observer=self.local_execution_observer,
                )
            self.queue.settle_stopped_budget(
                cursor,
                settlement,
                validate_current=lambda: self._verify_replay_current(settlement, guard),
            )
        self._publish_handling(result)
        self._publish_audit(settlement)
        return result

    @staticmethod
    def _bind_command(
        command: HandleDeliveryWait, settlement: ContainedUnknownBudgetSettlement
    ) -> None:
        StoppedBudgetSettlementService._bind(command, settlement.investigation)
        if (
            command.confirm_local_execution_stopped is not True
            or command.local_stop_reference != settlement.human_confirmation.reference
        ):
            raise ContinuationRejected("本机旧执行声明与已封存精确决定不一致")

    def _verify_replay_current(
        self, settlement: ContainedUnknownBudgetSettlement, guard: WorkerExecutionGuard
    ) -> None:
        if self.repository.get(settlement.task.id).status is TaskStatus.IMPLEMENTING:
            self._require_observation(settlement, guard)
        else:
            verify_settled_contained_unknown(
                settlement,
                repository=self.repository,
                queue=self.queue,
                state=self.collector.state,
                route_root=self.collector.routes,
                artifacts=self.artifacts,
                git=self.git,
                guard=guard,
                boot_observer=self.boot_observer,
                local_execution_observer=self.local_execution_observer,
            )

    def _require_observation(
        self, settlement: ContainedUnknownBudgetSettlement, guard: WorkerExecutionGuard
    ) -> None:
        observed = self._observe(settlement.task, settlement.work_item, settlement.step, guard)
        if observed is None or (
            observed[0],
            observed[1],
            observed[2],
            observed[3],
            observed[4].capture_sha256,
        ) != (
            settlement.containment.original_start,
            settlement.capture_start,
            settlement.containment.original_claim,
            settlement.inventory_sha256,
            settlement.retained_capture_sha256,
        ):
            raise ContinuationRejected("start-only 收尾前原执行或完整草稿已变化")
        sealed = self.records.get(
            "contained-unknown-budget-captures",
            settlement.retained_capture_sha256,
            CapturedMutations,
        )
        sealed.to_capture()
        if sealed != observed[4]:
            raise ContinuationRejected("start-only 收尾的完整草稿记录已变化")
        self._require_current_local_boundary(settlement)

    def _require_current_local_boundary(self, settlement: ContainedUnknownBudgetSettlement) -> None:
        boot = self.boot_observer.observe()
        old = settlement.containment
        if not boot.same_boot(old.boot) or old.local_execution_survey is None:
            raise ContinuationRejected("start-only 本机停止声明的启动会话已变化")
        survey = self.local_execution_observer.observe(
            worktree_root=Path(settlement.capture_start.worktree_path), boot=boot
        )
        survey.require_idle()
        if not old.local_execution_survey.same_boundary(survey):
            raise ContinuationRejected("start-only 本机账户或工作区调查边界已变化")
        if not boot.same_boot(self.boot_observer.observe()):
            raise ContinuationRejected("start-only 本机调查期间启动会话已变化")

    def _publish_handling(self, result: DeliveryWaitHandling) -> None:
        records = KnowledgeRecordStore(self.collector.state / "delivery-waits")
        records.put("wait-investigations", result.investigation.proof_sha256, result.investigation)
        records.put("wait-handlings", result.record_key, result)

    def _publish_audit(self, settlement: ContainedUnknownBudgetSettlement) -> None:
        # RuntimeSession refuses a terminal Task before its pre-run recorder.
        # The public HANDLE therefore publishes the human action after SQL commit;
        # exact replay repairs a crash between commit and this append.
        from ai_software_engineer.runtime import _default_case_id

        event = contained_unknown_human_event(
            settlement, _default_case_id(settlement.task.id), self.records
        )
        FileEvaluationEventStore(self.evaluation_root).append(event)

    def try_settle(
        self,
        command: HandleDeliveryWait,
        task: Task,
        item: QueuedWorkItem,
        step: QueuedRoleStep,
        proof: DeliveryWaitInvestigation,
        guard: WorkerExecutionGuard,
    ) -> DeliveryWaitHandling | None:
        if command.confirm_local_execution_stopped is not True:
            return None
        if command.local_stop_reference is None:
            raise ContinuationRejected("本机停止确认缺少可信答复引用")
        self.principal.require_duty(OperatorDuty.ENGINEERING)
        if not proof.local_stop_confirmation_available:
            raise ContinuationRejected("当前等待没有可确认的 start-only 本机隔离资格")
        StoppedBudgetSettlementService._bind(command, proof)
        with self.idle_scope() as cursor:
            observed = self._observe(task, item, step, guard)
            if observed is None:
                raise ContinuationRejected("当前 start-only 原执行事实已变化")
            start, capture_start, claim, inventory_sha, captured = observed
            boot = self.boot_observer.observe()
            survey = self.local_execution_observer.observe(
                worktree_root=Path(capture_start.worktree_path), boot=boot
            )
            survey.require_idle()
            if not boot.same_boot(self.boot_observer.observe()):
                raise ContinuationRejected("start-only 本机调查期间启动会话已变化")
            containment = LegacyExecutionContainment.create(
                scope=self.collector.scope,
                requirement_id=self.collector.expected_continuation_scope.requirement_id,
                dispatch_sha256=self.collector.expected_continuation_scope.dispatch_sha256,
                task_intent_sha256=task_intent_sha256(task),
                original_start=start,
                original_claim=claim,
                boot=boot,
                method="operator_confirmed_local_stop",
                local_execution_survey=survey,
            )
            at = self.clock()
            confirmation = LocalStopConfirmation.create(
                task_id=task.id,
                work_item_id=item.id,
                run_id=start.request.run_id,
                invocation_start_sha256=start.start_sha256,
                capture_start_sha256=capture_start.start_sha256,
                containment_sha256=containment.containment_sha256,
                principal=self.principal,
                reference=command.local_stop_reference,
                confirmed_at=at,
            )
            event = build_event(
                task,
                TaskStatus.BLOCKED,
                event_id="evt_contained_unknown_budget_" + digest(command.to_wire())[:30],
                reason=CONTAINED_UNKNOWN_BUDGET_REASON,
                source_revision=proof.source_revision,
                attempt=task.attempts,
                occurred_at=at,
            )
            closed = item.model_copy(
                update={
                    "status": WorkItemStatus.CLOSED,
                    "wait_reason": None,
                    "wait_disposition": None,
                    "available_at": None,
                    "updated_at": at,
                }
            )
            settlement = ContainedUnknownBudgetSettlement(
                task=task,
                investigation=proof,
                work_item=item,
                step=step,
                containment=containment,
                capture_start=capture_start,
                human_confirmation=confirmation,
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
            self.records.put("contained-unknown-budget-captures", captured.capture_sha256, captured)
            self.records.put(
                "contained-unknown-budget-settlements", settlement.settlement_sha256, settlement
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
                    "原开发调用没有最终记录; 已确认本机执行结束并完整保留草稿, 原结果仍为 UNKNOWN。"
                ),
                user_action="在原需求详情准备并精确批准恢复方案; 原执行历史和已消耗额度保留。",
                recheck_when="新恢复方案独立批准后继续原需求。",
                manual_resolution_allowed=False,
                handled_at=at,
                budget_settlement_sha256=settlement.settlement_sha256,
                handling_sha256="0" * 64,
            )
            result = result.model_copy(update={"handling_sha256": result.recompute_sha256()})
            self.records.put(
                "contained-unknown-budget-handlings", digest(command.to_wire()), result
            )
            self._require_observation(settlement, guard)
            self.queue.settle_stopped_budget(
                cursor,
                settlement,
                validate_current=lambda: self._require_observation(settlement, guard),
            )
        self._publish_handling(result)
        self._publish_audit(settlement)
        return result


def verify_settled_contained_unknown(
    settlement: ContainedUnknownBudgetSettlement,
    *,
    repository: TaskRepository,
    queue: MySqlRoleQueue,
    state: Path,
    route_root: Path | None,
    artifacts: ArtifactStore,
    git: GitWorktreeManager,
    guard: WorkerExecutionGuard,
    boot_observer: LocalBootObserver | None = None,
    local_execution_observer: LegacyLocalExecutionObserver | None = None,
) -> CapturedMutations:
    settlement.validate_integrity()
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
        raise ContinuationRejected("start-only 收尾的 Task 终态或队列事实已变化")
    old_repository = cast(TaskRepository, _PreSettlementRepository(repository, settlement))
    old_queue = cast(MySqlRoleQueue, _PreSettlementQueue(queue, settlement))
    collector = object.__new__(DeliveryWaitFactCollector)
    collector.state = state
    collector.routes = route_root or state / "model-routes"
    collector.expected_continuation_scope = settlement.capture_start.scope
    source = _read_start_only(
        settlement.task,
        settlement.work_item,
        settlement.step,
        collector=collector,
        repository=old_repository,
        queue=old_queue,
        artifacts=artifacts,
        guard=guard,
    )
    if source != (
        settlement.containment.original_start,
        settlement.capture_start,
        settlement.containment.original_claim,
    ):
        raise ContinuationRejected("start-only 收尾的原调用事实已变化")
    inventory_sha, capture = _capture_start_only(
        settlement.task, settlement.capture_start, state=state, git=git
    )
    sealed = KnowledgeRecordStore(state / "delivery-preflight", read_only=True).get(
        "contained-unknown-budget-captures",
        settlement.retained_capture_sha256,
        CapturedMutations,
    )
    sealed.to_capture()
    if (
        inventory_sha != settlement.inventory_sha256
        or capture != sealed
        or capture.capture_sha256 != settlement.retained_capture_sha256
    ):
        raise ContinuationRejected("start-only 收尾的完整草稿已变化")
    observer = boot_observer or TrustedLocalBootObserver()
    local: LegacyLocalExecutionObserver
    if local_execution_observer is None:
        from ai_software_engineer.manager.local_survey_observation import (
            IsolatedLegacyLocalExecutionObserver,
        )

        local = IsolatedLegacyLocalExecutionObserver()
    else:
        local = local_execution_observer
    boot = observer.observe()
    prior = settlement.containment
    if prior.local_execution_survey is None or (
        boot.machine_sha256 != prior.boot.machine_sha256 or boot.booted_at < prior.boot.booted_at
    ):
        raise ContinuationRejected("start-only 收尾的本机机器边界已变化")
    survey = local.observe(worktree_root=Path(settlement.capture_start.worktree_path), boot=boot)
    survey.require_idle()
    if not prior.local_execution_survey.same_boundary(survey, allow_new_boot=True):
        raise ContinuationRejected("start-only 收尾的工作区或账户边界已变化")
    if not boot.same_boot(observer.observe()):
        raise ContinuationRejected("start-only 收尾调查期间启动会话已变化")
    if (
        _read_start_only(
            settlement.task,
            settlement.work_item,
            settlement.step,
            collector=collector,
            repository=old_repository,
            queue=old_queue,
            artifacts=artifacts,
            guard=guard,
        )
        != source
    ):
        raise ContinuationRejected("读取草稿期间 start-only 原事实已变化")
    return capture


class _PreSettlementRepository:
    def __init__(
        self, repository: TaskRepository, record: ContainedUnknownBudgetSettlement
    ) -> None:
        self.repository, self.record = repository, record

    def get(self, task_id: str) -> Task:
        if task_id != self.record.task.id:
            raise ContinuationRejected("start-only 原 Task 身份不一致")
        return self.record.task

    def current_revision(self, task_id: str) -> int:
        self.get(task_id)
        return self.record.investigation.task_revision

    def list_events(self, task_id: str) -> tuple[StateEvent, ...]:
        self.get(task_id)
        return self.repository.list_events(task_id)[:-1]


class _PreSettlementQueue:
    def __init__(self, queue: MySqlRoleQueue, record: ContainedUnknownBudgetSettlement) -> None:
        self.queue, self.record = queue, record

    def get(self, item_id: str) -> QueuedWorkItem:
        if item_id != self.record.work_item.id:
            raise ContinuationRejected("start-only 原工作项身份不一致")
        return self.record.work_item

    def step(self, item_id: str) -> QueuedRoleStep:
        self.get(item_id)
        return self.record.step

    def original_claim(self, lease_id: str) -> QueueClaim:
        return self.queue.original_claim(lease_id)

    def accepted(self, task_id: str) -> tuple[AcceptedRoleArtifact, ...]:
        return self.queue.accepted(task_id)
