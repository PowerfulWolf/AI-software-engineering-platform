"""Single-Worker supervision of existing bounded orchestration steps."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

from pymysql.cursors import DictCursor

from ai_software_engineer.artifacts import ArtifactStore
from ai_software_engineer.artifacts.ports import ArtifactRef
from ai_software_engineer.domain import Artifact, WorkItemStatus
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGap,
    KnowledgeGapRaised,
    KnowledgeGapRouting,
    KnowledgeResolution,
)
from ai_software_engineer.knowledge.models import KnowledgeRunBinding, digest
from ai_software_engineer.knowledge.queue import QueueKnowledgeWaitPort
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.orchestration import RetryResult
from ai_software_engineer.orchestration.steps import BoundedRunControl, RoleRunBoundary
from ai_software_engineer.runtime import RuntimeRunResult, RuntimeSession
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.dispatcher import DispatcherLoop, DispatcherTickStatus
from ai_software_engineer.work_queue.execution_store import (
    MySqlRoleQueue,
    QueuedRoleStep,
    RoleQueueAdmission,
)
from ai_software_engineer.work_queue.models import QueueArtifactReceipt, QueueClaim
from ai_software_engineer.work_queue.ports import (
    DeliveryQueuePending,
    QueueConflict,
    QueueCorruption,
    QueueLeaseLost,
)


class WorkerLease:
    def __init__(self, queue: MySqlRoleQueue, claim: QueueClaim, owner_token: str) -> None:
        self.queue, self.claim = queue, claim
        self._token = owner_token
        self._stop = Event()
        self._lost = Event()
        self._ttl = claim.lease.expires_at - claim.lease.acquired_at
        self._expires_at = claim.lease.expires_at
        self._thread = Thread(target=self._heartbeat, name="delivery-role-heartbeat", daemon=True)

    def start(self) -> None:
        self.queue.start(
            self.claim.work_item.id,
            lease_id=self.claim.lease.id,
            owner_token=self._token,
            now=datetime.now(UTC),
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(35)
        if self._thread.is_alive():
            self._lost.set()
            raise QueueLeaseLost("Worker heartbeat did not stop")

    def _heartbeat(self) -> None:
        while not self._stop.wait(min(10, self._ttl.total_seconds() / 3)):
            try:
                now = datetime.now(UTC)
                self.queue.renew(
                    self.claim.work_item.id,
                    lease_id=self.claim.lease.id,
                    owner_token=self._token,
                    now=now,
                    expires_at=now + self._ttl,
                )
                self._expires_at = now + self._ttl
            except Exception:
                self._lost.set()
                return

    def check(self) -> None:
        if self._lost.is_set() or datetime.now(UTC) >= self._expires_at:
            raise QueueLeaseLost("Worker lease renewal was lost")

    def mutation_fence(self, cursor: DictCursor, task_id: str) -> None:
        self.check()
        if task_id != self.claim.work_item.task_id:
            raise QueueConflict("Worker cannot mutate another Task")
        self.queue.assert_owner(cursor, self.claim, self._token, now=datetime.now(UTC))

    @contextmanager
    def write_scope(self) -> Iterator[None]:
        self.check()
        with self.queue.fence(self.claim, self._token):
            yield

    def accept(self, store: ArtifactStore, artifact: Artifact) -> ArtifactRef:
        self.check()
        return self.queue.accept_artifact(self.claim, self._token, store, artifact)

    def finish(self, next_step: QueuedRoleStep | None, now: datetime) -> None:
        self.check()
        self.queue.finish(self.claim, self._token, next_step=next_step, now=now, guard=self.check)

    def wait_for_knowledge(
        self,
        binding: KnowledgeRunBinding,
        routing: KnowledgeGapRouting,
        records: KnowledgeRecordStore,
    ) -> None:
        self.check()
        QueueKnowledgeWaitPort(
            self.queue,
            claim=self.claim,
            owner_token=self._token,
            binding=binding,
            records=records,
            clock=lambda: datetime.now(UTC),
        ).wait(binding, routing)
        self._stop.set()


class WorkerExecutionGuard:
    """Mutable binding owned by the supervisor, never exposed as an Agent tool."""

    def __init__(self) -> None:
        self.lease: WorkerLease | None = None
        self.inherited_fds: tuple[int, ...] = ()

    def check(self) -> None:
        if self.lease is None:
            raise QueueConflict("delivery execution requires an active Worker")
        self.lease.check()

    @contextmanager
    def write_scope(self) -> Iterator[None]:
        self.check()
        assert self.lease is not None
        with self.lease.write_scope():
            yield

    @contextmanager
    def task_scope(self, root: Path, task_id: str) -> Iterator[None]:
        if any(path.is_symlink() for path in (root, *root.parents)):
            raise QueueConflict("Worker lock root contains a symlink")
        root.mkdir(parents=True, exist_ok=True)
        # TaskId has already passed Task validation; hash it to keep this seam independent.
        import hashlib

        name = hashlib.sha256(task_id.encode()).hexdigest() + ".lock"
        fd = os.open(root / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise DeliveryQueuePending("Task still has a live execution process") from error
            self.inherited_fds = (fd,)
            yield
        finally:
            self.inherited_fds = ()
            os.close(fd)


class AcceptedArtifactStore:
    """Exclude unaccepted filesystem remnants from ordinary orchestrator recovery."""

    def __init__(
        self,
        delegate: ArtifactStore,
        queue: MySqlRoleQueue,
        task_id: str,
        guard: WorkerExecutionGuard,
    ) -> None:
        self.delegate, self.queue, self.task_id, self.guard = delegate, queue, task_id, guard

    def put(self, artifact: Artifact) -> ArtifactRef:
        if self.queue.admission(self.task_id) is None:
            # Only the deterministic approved-plan bootstrap runs before adoption.
            from ai_software_engineer.domain import AgentRole

            if artifact.producer.role is not AgentRole.ORCHESTRATOR:
                raise QueueConflict("unadopted Task cannot publish a delivery Artifact")
            return self.delegate.put(artifact)
        self.guard.check()
        assert self.guard.lease is not None
        return self.guard.lease.accept(self.delegate, artifact)

    def _accepted(self) -> dict[str, str] | None:
        admission = self.queue.admission(self.task_id)
        if admission is None:
            return None
        receipts = (
            *admission.legacy_artifacts,
            *(record.receipt for record in self.queue.accepted(self.task_id)),
        )
        return {item.artifact_id: item.sha256 for item in receipts}

    def get(self, artifact_id: str) -> Artifact:
        artifact = self.delegate.get(artifact_id)
        accepted = self._accepted()
        if artifact.task_id != self.task_id or (
            accepted is not None and accepted.get(artifact_id) != artifact.integrity.sha256
        ):
            raise QueueCorruption("Artifact has no matching accepted receipt")
        return artifact

    def list_for_task(self, task_id: str) -> tuple[Artifact, ...]:
        if task_id != self.task_id:
            raise QueueConflict("Worker Artifact store is Task-bound")
        accepted = self._accepted()
        if accepted is None:
            return self.delegate.list_for_task(task_id)
        return tuple(self.get(identity) for identity in sorted(accepted))


class WorkerKnowledgeWait:
    def __init__(self, guard: WorkerExecutionGuard, records: KnowledgeRecordStore) -> None:
        self.guard, self.records = guard, records

    def wait(self, binding: KnowledgeRunBinding, routing: KnowledgeGapRouting) -> None:
        self.guard.check()
        assert self.guard.lease is not None
        self.guard.lease.wait_for_knowledge(binding, routing, self.records)


StepBuilder = Callable[[RoleRunBoundary, str | None, datetime], QueuedRoleStep]
DispatcherFactory = Callable[[QueuedRoleStep], DispatcherLoop]


class QueuedDeliverySupervisor:
    """Compatibility Manager calls supervise real, separately claimed role steps."""

    def __init__(
        self,
        *,
        queue: MySqlRoleQueue,
        guard: WorkerExecutionGuard,
        artifacts: AcceptedArtifactStore,
        allocation_sha256: str,
        repository_id: str,
        records: KnowledgeRecordStore,
        locks_root: Path,
        build_step: StepBuilder,
        dispatcher: DispatcherFactory,
    ) -> None:
        self.queue, self.guard, self.artifacts = queue, guard, artifacts
        self.allocation_sha256, self.repository_id = allocation_sha256, repository_id
        self.records, self.locks_root = records, locks_root
        self.build_step, self.dispatcher = build_step, dispatcher

    def run(
        self,
        runtime: RuntimeSession,
        task_id: str,
        *,
        terminal_result: Callable[[], RetryResult | None],
        close_worktrees: Callable[[], None],
    ) -> RetryResult:
        with self.guard.task_scope(self.locks_root, task_id):
            result = self._run(runtime, task_id, terminal_result=terminal_result)
            # An interrupted/waiting Run keeps even its clean worktree: removing
            # it leaves its immutable branch behind and prevents exact reopening.
            # Dirty worktrees also remain subject to native recovery approval.
            close_worktrees()
            return result

    def _run(
        self,
        runtime: RuntimeSession,
        task_id: str,
        *,
        terminal_result: Callable[[], RetryResult | None],
    ) -> RetryResult:
        repository = runtime.task_repository
        if not isinstance(repository, MySqlTaskRepository):
            raise ValueError("production Worker requires MySQL Task mutation fencing")
        admission = self.queue.admission(task_id)
        if admission is None:
            existing = terminal_result()
            if existing is not None:
                return existing
            first = runtime.run_step(task_id, BoundedRunControl(repository))
            if not isinstance(first, RoleRunBoundary):
                return first.result
            step = self.build_step(first, None, datetime.now(UTC))
            admission = RoleQueueAdmission(
                task_id=task_id,
                repository_id=self.repository_id,
                allocation_sha256=self.allocation_sha256,
                legacy_artifacts=tuple(
                    QueueArtifactReceipt(artifact_id=a.artifact_id, sha256=a.integrity.sha256)
                    for a in self.artifacts.delegate.list_for_task(task_id)
                ),
            )
            self.queue.admit(admission, step)
        if (
            admission.allocation_sha256 != self.allocation_sha256
            or admission.repository_id != self.repository_id
        ):
            raise QueueConflict("queued delivery allocation changed")
        # A finite Task attempt budget bounds successful role invocations. Lease
        # recovery may wait briefly, but capacity shortage never spins forever.
        for _ in range(64):
            pending = tuple(
                item
                for item in self.queue.items_for_task(task_id)
                if item.status is not WorkItemStatus.CLOSED
            )
            if not pending:
                existing = terminal_result()
                if existing is None:
                    raise QueueCorruption("nonterminal adopted Task has no queued step")
                return existing
            if len(pending) != 1:
                raise QueueCorruption("serial Task has multiple open role steps")
            item = pending[0]
            step = self.queue.step(item.id)
            if item.status in {WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY}:
                self._resume_knowledge(item.id, item.wait_reason or "")
            tick = self.dispatcher(step).tick(now=datetime.now(UTC), work_item_id=item.id)
            if tick.status is not DispatcherTickStatus.DISPATCHED:
                raise DeliveryQueuePending(
                    "Role is queued or its previous execution lease has not expired"
                )
            assert tick.claim is not None and tick.lease_owner_token is not None
            lease = WorkerLease(self.queue, tick.claim, tick.lease_owner_token)
            lease.start()
            self.guard.lease = lease
            repository.mutation_fence = lease.mutation_fence
            try:
                existing = terminal_result()
                outcome = (
                    existing
                    if existing is not None
                    else runtime.run_step(
                        task_id,
                        BoundedRunControl(repository, permit=step.boundary, guard=lease.check),
                    )
                )
                now = datetime.now(UTC)
                next_step = (
                    self.build_step(outcome, item.id, now)
                    if isinstance(outcome, RoleRunBoundary)
                    else None
                )
                lease.finish(next_step, now)
                if next_step is None:
                    if isinstance(outcome, RoleRunBoundary):
                        raise QueueCorruption("terminal outcome is still a boundary")
                    return outcome.result if isinstance(outcome, RuntimeRunResult) else outcome
            finally:
                repository.mutation_fence = None
                self.guard.lease = None
                lease.stop()
        raise QueueCorruption("Worker exceeded serial Task scheduling bound")

    def _resume_knowledge(self, work_item_id: str, reason: str) -> None:
        prefix, gap_id, routing_sha256 = [*reason.split(":", 2), "", ""][:3]
        if prefix != "KNOWLEDGE_GAP":
            raise DeliveryQueuePending("WorkItem requires a verified external resume signal")
        gap = self.records.get("gaps", gap_id, KnowledgeGap)
        gap.validate_integrity()
        route = self.records.get("gap-routes", gap_id, KnowledgeGapRouting)
        if (
            route.gap_id != gap_id
            or route.routing_sha256 != routing_sha256
            or route.routing_sha256
            != digest(route.model_dump(mode="json", exclude={"routing_sha256"}))
        ):
            raise QueueCorruption("knowledge wait receipt changed")
        resolution = self.records.find("gap-resolutions", gap_id, KnowledgeResolution)
        if resolution is None:
            raise KnowledgeGapRaised(gap)
        resolution.validate_integrity()
        item = self.queue.get(work_item_id)
        if (
            resolution.gap_id != gap_id
            or resolution.previous_run_id != gap.binding.run_id
            or gap.binding.task_id != item.task_id
            or route.waiting_status != item.status.value
            or gap.binding.role.value != item.role.value
            or gap.binding.repository_ids != (item.repository_id,)
        ):
            raise QueueConflict("knowledge resolution belongs to another queued run")
        self.queue.make_ready(work_item_id, now=datetime.now(UTC))
