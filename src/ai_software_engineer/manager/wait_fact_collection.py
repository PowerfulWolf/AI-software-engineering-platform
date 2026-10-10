"""Bounded fact reconciliation for an exact idle engineering wait."""

from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from ai_software_engineer.agents.fallback import (
    FileModelRouteAttemptStore,
    RouteAttemptOutcome,
)
from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.domain import AgentRole, WorkItemStatus
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git import GitWorktreeManager, WorktreeCaptureRejected
from ai_software_engineer.git.mutation import MutationInventoryRejected
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.orchestration.capture_reconciliation import (
    reconcile_capture,
    validate_capture_stop,
)
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRecordMissing,
    ContinuationRejected,
    ContinuationScope,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.ports import QueueCorruption, QueueNotFound
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard


class WaitCollectionQueue(Protocol):
    def get(self, work_item_id: str) -> QueuedWorkItem: ...
    def step(self, work_item_id: str) -> QueuedRoleStep: ...
    def original_claim(self, lease_id: str) -> QueueClaim: ...
    def accepted(self, task_id: str) -> tuple[AcceptedRoleArtifact, ...]: ...


class WaitWorkspaceCaptureRejected(ContinuationRejected):
    """A fully bound stop was checked, but no complete source receipt was sealed."""

    def __init__(self) -> None:
        super().__init__("原执行停止已核验, 完整进度封存未通过校验, 原现场保留")


class DeliveryWaitFactCollector:
    """Caller owns Task process lock and queue idle fence, never a new role claim."""

    def __init__(
        self,
        *,
        sidecar_state: Path,
        route_root: Path,
        scope: EngineeringScope,
        expected_continuation_scope: ContinuationScope,
        git: GitWorktreeManager,
        queue: WaitCollectionQueue,
    ) -> None:
        self.state, self.routes, self.scope = sidecar_state, route_root, scope
        self.git, self.queue = git, queue
        self.expected_continuation_scope = expected_continuation_scope

    def collect(self, task: Task, step: QueuedRoleStep, guard: WorkerExecutionGuard) -> None:
        try:
            self._collect(task, step, guard)
        except (ValidationError, QueueCorruption, QueueNotFound) as error:
            raise ContinuationRejected("原执行结果或权限记录无法通过完整校验, 现场保留") from error

    def _original_invocation(
        self, task: Task, step: QueuedRoleStep, guard: WorkerExecutionGuard
    ) -> tuple[DeliveryInvocationStart, QueueClaim] | None:
        if not guard.inherited_fds:
            raise ContinuationRejected("工程事实收集缺少独占任务锁")
        self._require_current(task, step)
        root = self.state / "invocations"
        if not root.is_dir():
            return None
        records = KnowledgeRecordStore(root, read_only=True)
        start = records.find("invocation-starts", step.work_item.id, DeliveryInvocationStart)
        if start is None:
            return None
        start.validate_integrity()
        if (
            start.request.task_id,
            start.request.role,
            start.request.attempt,
            start.request.source_revision,
            start.checkpoint_sequence,
        ) != (
            task.id,
            step.boundary.role,
            step.boundary.attempt,
            step.boundary.source_revision,
            step.boundary.checkpoint_sequence,
        ):
            raise ContinuationRejected("原执行启动记录与当前等待不一致")
        historical = self.queue.original_claim(start.lease_id)
        if (
            historical.work_item.id,
            historical.work_item.task_id,
            historical.work_item.repository_id,
            historical.work_item.role,
            historical.work_item.attempt,
            historical.work_item.checkpoint_sequence,
        ) != (
            step.work_item.id,
            task.id,
            self.scope.repository_id,
            start.request.role,
            start.request.attempt,
            start.checkpoint_sequence,
        ):
            raise ContinuationRejected("原执行权限历史缺失或与当前等待不一致")
        return start, historical

    def _collect(self, task: Task, step: QueuedRoleStep, guard: WorkerExecutionGuard) -> None:
        original = self._original_invocation(task, step, guard)
        if original is None:
            return
        start, historical = original
        records = KnowledgeRecordStore(self.state / "invocations")
        outcome = records.find("invocation-outcomes", step.work_item.id, DeliveryInvocationOutcome)
        if outcome is not None:
            outcome.validate_integrity()
            if outcome.start != start:
                raise ContinuationRejected("原执行结果与启动记录不一致")
            return
        if self.routes.is_dir():
            routes = FileModelRouteAttemptStore(self.routes, read_only=True).list_for_run(
                start.request.run_id
            )
            for index, route in enumerate(routes, start=1):
                route.validate_integrity()
                if route.route_index != index or route.request_sha256 != digest(
                    start.request.to_wire()
                ):
                    raise ContinuationRejected("模型路由记录未绑定完整原调用")
                # Every intermediate route must explicitly have selected fallback.
                if index < len(routes) and route.outcome is not RouteAttemptOutcome.FALLBACK:
                    raise ContinuationRejected("模型路由最终结果存在冲突")
                DeliveryInvocationOutcome(start=start, result=route.result, outcome_sha256="0" * 64)
            if routes and routes[-1].outcome is not RouteAttemptOutcome.FALLBACK:
                result = DeliveryInvocationOutcome(
                    start=start, result=routes[-1].result, outcome_sha256="0" * 64
                )
                result = result.model_copy(
                    update={
                        "outcome_sha256": digest(
                            result.model_dump(mode="json", exclude={"outcome_sha256"})
                        )
                    }
                )
                self._require_current(task, step)
                records.put("invocation-outcomes", step.work_item.id, result)
                return
        if start.request.role is not AgentRole.CODER:
            return
        capture_root = self.state / "continuations" / task.id
        if not capture_root.is_dir():
            return
        store = FileContinuationStore(capture_root, task_id=task.id)
        try:
            receipt = store.get_receipt(start.request.run_id)
            if receipt.scope != self.expected_continuation_scope:
                raise ContinuationRejected("原停机现场记录不属于当前交付与分配")
            return
        except ContinuationRecordMissing:
            pass
        observation = self._capture_observation(task, step, start, historical, guard)
        if observation is None:
            return
        capture_start, capture_stop = observation
        try:
            reconcile_capture(
                start=capture_start,
                stop=capture_stop,
                task=task,
                task_revision=start.checkpoint_sequence,
                historical_claim=historical,
                store=store,
                git=self.git,
                task_lock=guard,
                validate_inputs=lambda request: self._validate_capture_inputs(
                    task, step, start, request
                ),
                has_output=lambda request: any(
                    item.run_id == request.run_id
                    and item.context_manifest_id == request.context_manifest_id
                    for item in self.queue.accepted(task.id)
                ),
            )
        except (WorktreeCaptureRejected, MutationInventoryRejected) as error:
            # Recheck the stop after capture refusal; never transfer rejected
            # source, exception text or checkpoint authority into the report.
            if self._capture_observation(task, step, start, historical, guard) is None:
                raise ContinuationRejected("原执行停止观察已不可用, 现场保留") from error
            raise WaitWorkspaceCaptureRejected() from error

    def observe_stop(
        self, task: Task, step: QueuedRoleStep, guard: WorkerExecutionGuard
    ) -> ExecutionCaptureStop | None:
        """Read-only original stop observation, also usable by INSPECT."""
        original = self._original_invocation(task, step, guard)
        if original is None:
            return None
        start, historical = original
        observation = self._capture_observation(task, step, start, historical, guard)
        return observation[1] if observation else None

    def _capture_observation(
        self,
        task: Task,
        step: QueuedRoleStep,
        start: DeliveryInvocationStart,
        historical: QueueClaim,
        guard: WorkerExecutionGuard,
    ) -> tuple[ExecutionCaptureStart, ExecutionCaptureStop] | None:
        if start.request.role is not AgentRole.CODER:
            return None
        root = self.state / "continuations" / task.id
        if not root.is_dir():
            return None
        store = FileContinuationStore(root, task_id=task.id)
        try:
            capture_start = store.capture_start(start.request.run_id)
            capture_stop = store.capture_stop(start.request.run_id)
        except ContinuationRecordMissing:
            return None  # Missing historical facts are never fabricated.
        if (
            capture_start.request != start.request
            or capture_start.scope != self.expected_continuation_scope
            or (
                capture_start.scope.team_id,
                capture_start.scope.project_id,
                capture_start.scope.repository_id,
            )
            != (self.scope.team_id, self.scope.project_id, self.scope.repository_id)
        ):
            raise ContinuationRejected("执行现场记录不属于当前项目与原调用")
        validate_capture_stop(
            start=capture_start,
            stop=capture_stop,
            task=task,
            task_revision=start.checkpoint_sequence,
            historical_claim=historical,
            task_lock=guard,
            validate_inputs=lambda request: self._validate_capture_inputs(
                task, step, start, request
            ),
        )
        return capture_start, capture_stop

    def _validate_capture_inputs(
        self,
        task: Task,
        step: QueuedRoleStep,
        start: DeliveryInvocationStart,
        request: AgentRequest,
    ) -> None:
        self._require_current(task, step)
        if request != start.request or request.source_revision != step.boundary.source_revision:
            raise ContinuationRejected("原调用输入已经变化")
        # Accepted input facts may not have advanced since the exact request.
        accepted = self.queue.accepted(task.id)
        if any(item.checkpoint_sequence > start.checkpoint_sequence for item in accepted):
            raise ContinuationRejected("原调用之后已有新的接纳事实, 必须重新核验输入")

    def _require_current(self, task: Task, step: QueuedRoleStep) -> None:
        current = self.queue.get(step.work_item.id)
        facts = current.wait_disposition.facts if current.wait_disposition else None
        if (
            current.status not in {WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY}
            or facts is None
            or current.task_id != task.id
            or current.repository_id != self.scope.repository_id
            or (current.id, current.role, current.attempt, current.checkpoint_sequence)
            != (
                step.work_item.id,
                step.boundary.role,
                step.boundary.attempt,
                step.boundary.checkpoint_sequence,
            )
            or task.repository != self.scope.repository_root
            or facts.task_intent_sha256 != task_intent_sha256(task)
            or facts.source_revision != step.boundary.source_revision
            or facts.checkpoint_sequence != step.boundary.checkpoint_sequence
            or self.queue.step(current.id) != step
        ):
            raise ContinuationRejected("工程收集期间等待或原任务事实已变化")
