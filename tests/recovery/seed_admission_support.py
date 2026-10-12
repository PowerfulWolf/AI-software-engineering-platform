"""Offline queue port with real immutable invocation files for seed gate tests."""

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import cast

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.domain import AgentRole, WorkItemStatus
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.recovery.seed import RecoverySeedService
from ai_software_engineer.work_queue.execution_store import (
    AcceptedRoleArtifact,
    MySqlRoleQueue,
    QueuedRoleStep,
    RoleQueueAdmission,
)
from ai_software_engineer.work_queue.invocation import DurableInvocationControl
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.ports import QueueLeaseLost
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard, WorkerLease
from tests.orchestration.test_native_continuation import claim as native_claim


class SeedQueue(MySqlRoleQueue):
    def __init__(self, service: RecoverySeedService) -> None:
        self.service = service
        self.items: dict[str, QueuedWorkItem] = {}
        self.steps: dict[str, QueuedRoleStep] = {}
        self.publications: list[AcceptedRoleArtifact] = []
        self.read_keys: list[str] = []
        self.claims: dict[str, QueueClaim] = {}

    def admission(self, task_id: str) -> RoleQueueAdmission | None:
        dispatch = self.service.dispatch
        assert task_id == dispatch.task_id
        return RoleQueueAdmission(
            task_id=task_id,
            repository_id=dispatch.repository_id,
            allocation_sha256=dispatch.dispatch_sha256,
            legacy_artifacts=(),
        )

    def items_for_task(self, task_id: str) -> tuple[QueuedWorkItem, ...]:
        assert task_id == self.service.dispatch.task_id
        return tuple(self.items.values())

    def step_for_invocation(self, work_item_id: str, baseline_sha256: str | None) -> QueuedRoleStep:
        self.read_keys.append(work_item_id)
        assert baseline_sha256 is None
        return self.steps[work_item_id]

    def accepted(self, task_id: str) -> tuple[AcceptedRoleArtifact, ...]:
        assert task_id == self.service.dispatch.task_id
        return tuple(self.publications)

    def original_claim(self, lease_id: str) -> QueueClaim:
        return self.claims[lease_id]

    def rejected_output_artifact_ids(self, task_id: str) -> frozenset[str]:
        assert task_id == self.service.dispatch.task_id
        return frozenset()


class SeedGuard(WorkerExecutionGuard):
    def __init__(self, queue: SeedQueue) -> None:
        super().__init__()
        self.queue = queue
        self.lost = False
        self.fences = 0

    def check(self) -> None:
        if self.lost or self.lease is None:
            raise QueueLeaseLost("fixture Worker is not current")

    @contextmanager
    def write_scope(self) -> Iterator[None]:
        self.check()
        self.fences += 1
        yield
        self.check()

    def bind(
        self, request: AgentRequest, *, start: bool = True, dispatch_sequence: int = 0
    ) -> QueueClaim:
        service, dispatch = self.queue.service, self.queue.service.dispatch
        template = native_claim(dispatch.task, request.attempt)
        item = template.work_item.model_copy(
            update={
                "repository_id": dispatch.repository_id,
                "checkpoint_sequence": 2,
                "status": WorkItemStatus.RUNNING,
                "dispatch_sequence": dispatch_sequence,
            }
        )
        claim = QueueClaim(
            work_item=item.model_copy(update={"status": WorkItemStatus.LEASED}),
            assignment=template.assignment.model_copy(
                update={"repository_id": dispatch.repository_id}
            ),
            lease=template.lease,
            model_selection=template.model_selection,
            worker_id=template.worker_id,
            claimed_at=template.claimed_at,
        )
        self.queue.items[item.id] = item
        self.queue.steps[item.id] = QueuedRoleStep(
            work_item=item,
            boundary=RoleRunBoundary(
                item.task_id,
                AgentRole.CODER,
                item.attempt,
                item.checkpoint_sequence,
                request.source_revision,
            ),
            allocation_sha256=dispatch.dispatch_sha256,
        )
        self.lease = cast(WorkerLease, SimpleNamespace(queue=self.queue, claim=claim))
        self.queue.claims[claim.lease.id] = claim
        if start:
            DurableInvocationControl(service.invocations, self).prepare(request)
        return claim


def bind_seed_runtime(
    service: RecoverySeedService,
    request: AgentRequest,
    *,
    start: bool = True,
    dispatch_sequence: int = 0,
) -> SeedGuard:
    guard = SeedGuard(SeedQueue(service))
    service.guard = guard
    guard.bind(request, start=start, dispatch_sequence=dispatch_sequence)
    return guard
