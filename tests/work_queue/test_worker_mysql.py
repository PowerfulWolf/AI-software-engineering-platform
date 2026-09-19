"""Independent production Worker tests against an explicitly isolated MySQL database."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult
from ai_software_engineer.agents.structured import StructuredModelResult
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import AgentRole, RiskTier, StateEvent, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.workforce import TaskLease
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGapRaised,
    KnowledgeGapService,
    KnowledgeResolution,
    KnowledgeResolutionSource,
    KnowledgeResume,
)
from ai_software_engineer.knowledge.models import digest, text_digest
from ai_software_engineer.knowledge.runtime import KnowledgeRoleClients, KnowledgeRunContextBuilder
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager import MySqlDispatchAuthority
from ai_software_engineer.manager.production_backend import _terminal_delivery_result
from ai_software_engineer.manager.queue_capacity import production_role_queue
from ai_software_engineer.orchestration import FileRunContextBuilder, RetryDeliveryResult
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.runtime import (
    RuntimeConfig,
    RuntimePaths,
    RuntimePersistence,
    RuntimeSession,
)
from ai_software_engineer.scheduling import ModelRouter, PortfolioScheduler
from ai_software_engineer.store import MySqlTaskRepository, TaskNotFound
from ai_software_engineer.work_queue.dispatcher import DispatcherLoop, DispatcherTickStatus
from ai_software_engineer.work_queue.execution_store import (
    MySqlRoleQueue,
    QueuedRoleStep,
    RoleQueueAdmission,
)
from ai_software_engineer.work_queue.models import (
    QueueArtifactReceipt,
    QueueClaim,
    QueueCompletion,
    QueuedWorkItem,
)
from ai_software_engineer.work_queue.ports import (
    DeliveryQueuePending,
    QueueConflict,
    QueueCorruption,
    QueueLeaseLost,
    QueueNotFound,
)
from ai_software_engineer.work_queue.worker import (
    AcceptedArtifactStore,
    QueuedDeliverySupervisor,
    WorkerExecutionGuard,
    WorkerKnowledgeWait,
    WorkerLease,
)
from tests.domain.factories import make_implementation_artifact, make_plan_artifact, make_task
from tests.knowledge.test_consultation import Model
from tests.knowledge.test_delivery_context import Clients
from tests.knowledge.test_gaps import Approval
from tests.manager.test_dispatch_authority import _durable_facts
from tests.orchestration.test_retry import ScriptedAdapter
from tests.orchestration.test_runner import _definitions
from tests.work_queue.test_mysql_queue import agents, demand, policy

pytestmark = pytest.mark.mysql
REPOSITORY_ID = "repository_worker_qa"
ALLOCATION_SHA = "a" * 64
TOKEN = "worker-qa-owner-token-0001"


@pytest.fixture
def mysql_dsn() -> str:
    value = os.environ.get("ASE_TEST_MYSQL_DSN")
    if not value:
        pytest.skip("ASE_TEST_MYSQL_DSN is not configured")
    return value


def make_step(boundary: RoleRunBoundary, parent: str | None, now: datetime) -> QueuedRoleStep:
    return QueuedRoleStep(
        work_item=QueuedWorkItem(
            id=f"work_qa_{boundary.role.value}_{boundary.attempt}_{boundary.checkpoint_sequence}",
            task_id=boundary.task_id,
            repository_id=REPOSITORY_ID,
            role=boundary.role,
            attempt=boundary.attempt,
            checkpoint_sequence=boundary.checkpoint_sequence,
            repository_scopes=("/fixture/repository",),
            parent_work_item_id=parent,
            status=WorkItemStatus.READY,
            priority=500,
            risk=RiskTier.NORMAL,
            required_capabilities=("delivery",),
            created_at=now,
            updated_at=now,
        ),
        boundary=boundary,
        allocation_sha256=ALLOCATION_SHA,
    )


def dispatcher(queue: MySqlRoleQueue) -> DispatcherLoop:
    profiles = tuple(
        profile.model_copy(update={"id": f"agent_{profile.eligible_roles[0].value}_001"})
        for profile in agents()
    )
    return DispatcherLoop(
        queue=queue,
        scheduler=PortfolioScheduler(lease_duration=timedelta(minutes=15)),
        model_router=ModelRouter(
            route_context_capacities={
                (route.provider, route.model): 128_000 for route in policy().routes
            }
        ),
        agents=profiles,
        policies=(policy(),),
        demand_builder=demand,
        worker_id="worker_independent_qa",
        owner_token_factory=lambda: TOKEN,
    )


def admit(
    queue: MySqlRoleQueue, *, legacy: tuple[QueueArtifactReceipt, ...] = ()
) -> QueuedRoleStep:
    step = make_step(
        RoleRunBoundary("task_domain_001", AgentRole.CODER, 1, 0, "main"), None, datetime.now(UTC)
    )
    queue.admit(
        RoleQueueAdmission(
            task_id=step.boundary.task_id,
            repository_id=REPOSITORY_ID,
            allocation_sha256=ALLOCATION_SHA,
            legacy_artifacts=legacy,
        ),
        step,
    )
    return step


def claim_step(queue: MySqlRoleQueue, step: QueuedRoleStep) -> QueueClaim:
    tick = dispatcher(queue).tick(now=datetime.now(UTC), work_item_id=step.work_item.id)
    assert tick.status is DispatcherTickStatus.DISPATCHED and tick.claim is not None
    return tick.claim


class ObservedAdapter(ScriptedAdapter):
    """Observe the real Lease held around each deterministic role invocation."""

    def __init__(self, queue: MySqlRoleQueue, **scripts: tuple[int, ...]) -> None:
        super().__init__(**scripts)
        self.queue = queue
        self.invocation_claims: list[tuple[AgentRole, str]] = []

    def run(self, request: AgentRequest) -> AgentResult:
        active = tuple(
            lease
            for lease in self.queue.list_active_leases(now=datetime.now(UTC))
            if lease.task_id == request.task_id
        )
        if request.role is AgentRole.ORCHESTRATOR:
            assert not active
        else:
            assert len(active) == 1
            assignments = {
                assignment.id: assignment for assignment in self.queue.list_assignments()
            }
            assignment = assignments[active[0].assignment_id]
            assert assignment.role is request.role
            assert assignment.agent_id == f"agent_{request.role.value}_001"
            self.invocation_claims.append((request.role, active[0].id))
        return super().run(request)


@contextmanager
def runtime_fixture(
    tmp_path: Path,
    dsn: str,
    queue: MySqlRoleQueue,
    adapter: ScriptedAdapter,
    *,
    knowledge_clients: KnowledgeRoleClients | None = None,
) -> Iterator[tuple[RuntimeSession, QueuedDeliverySupervisor]]:
    root = tmp_path / "repository"
    root.mkdir(exist_ok=True)
    paths = RuntimePaths(
        database=str(tmp_path / "unused.sqlite"),
        artifacts=str(tmp_path / "artifacts"),
        contexts=str(tmp_path / "contexts"),
        evaluation_events=str(tmp_path / "events"),
        handoffs=str(tmp_path / "handoffs"),
        evidence=str(tmp_path / "evidence"),
        runs=str(tmp_path / "runs"),
    )
    config = RuntimeConfig(
        endpoint="https://runtime.invalid/v1/responses",
        model="model-standard",
        api_key_required=False,
        persistence=RuntimePersistence(backend="mysql"),
        paths=paths,
    )
    guard = WorkerExecutionGuard()
    accepted = AcceptedArtifactStore(
        FileArtifactStore(paths.artifacts), queue, "task_domain_001", guard
    )
    supervisor = QueuedDeliverySupervisor(
        queue=queue,
        guard=guard,
        artifacts=accepted,
        allocation_sha256=ALLOCATION_SHA,
        repository_id=REPOSITORY_ID,
        records=KnowledgeRecordStore(tmp_path / "knowledge"),
        locks_root=tmp_path / "locks",
        build_step=make_step,
        dispatcher=lambda _step: dispatcher(queue),
    )
    definitions = {
        role: value.model_copy(update={"provider": "codex", "model": "model-standard"})
        for role, value in _definitions().items()
    }
    contexts = FileContextStore(paths.contexts)
    knowledge = (
        KnowledgeRunContextBuilder(
            FileRunContextBuilder(root, context_store=contexts),
            contexts=contexts,
            clients=knowledge_clients,
            repository_root=root,
            records=supervisor.records,
            team_id="team_worker",
            project_id="project_worker",
            repository_id=REPOSITORY_ID,
            sources=(),
            wait_port=WorkerKnowledgeWait(guard, supervisor.records),
        )
        if knowledge_clients is not None
        else None
    )
    with RuntimeSession(
        config,
        environment={"ASE_MYSQL_DSN": dsn},
        agent_adapter=adapter,
        agent_definitions=definitions,
        repository_root=root,
        artifact_store=accepted,
        context_builder=knowledge,
    ) as runtime:
        try:
            runtime.task_repository.get("task_domain_001")
        except TaskNotFound:
            runtime.task_repository.create(make_task().model_copy(update={"repository": str(root)}))
        yield runtime, supervisor


def run_supervisor(
    runtime: RuntimeSession, supervisor: QueuedDeliverySupervisor
) -> RetryDeliveryResult:
    outcome = supervisor.run(
        runtime,
        "task_domain_001",
        terminal_result=lambda: _terminal_delivery_result(
            runtime.task_repository, supervisor.artifacts, "task_domain_001"
        ),
        close_worktrees=lambda: None,
    )
    assert isinstance(outcome, RetryDeliveryResult)
    return outcome


@pytest.mark.parametrize(
    "scripts, expected_roles",
    [
        ({}, [AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER]),
        (
            {"coder_timeouts": (1,)},
            [AgentRole.CODER, AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER],
        ),
        (
            {"coder_progress": (1,)},
            [AgentRole.CODER, AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER],
        ),
        (
            {"qa_failures": (1,)},
            [AgentRole.CODER, AgentRole.QA, AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER],
        ),
    ],
)
def test_supervisor_claims_each_serial_role_including_retry_boundaries(
    mysql_dsn: str,
    tmp_path: Path,
    scripts: dict[str, tuple[int, ...]],
    expected_roles: list[AgentRole],
) -> None:
    queue = MySqlRoleQueue(mysql_dsn)
    adapter = ObservedAdapter(queue, **scripts)
    with runtime_fixture(tmp_path, mysql_dsn, queue, adapter) as (runtime, supervisor):
        result = run_supervisor(runtime, supervisor)
        assert result.task.status is TaskStatus.DONE
        assert [role for role, _ in adapter.invocation_claims] == expected_roles
        assert len({lease for _, lease in adapter.invocation_claims}) == len(expected_roles)
        assert Counter(item.role for item in queue.items_for_task(result.task.id)) == Counter(
            expected_roles
        )
        assert all(
            item.status is WorkItemStatus.CLOSED for item in queue.items_for_task(result.task.id)
        )
        assert not queue.list_active_leases(now=datetime.now(UTC))
        records = queue.accepted(result.task.id)
        accepted = {record.receipt.artifact_id: record for record in records}
        for artifact_id in result.artifact_ids[1:]:
            artifact = supervisor.artifacts.get(artifact_id)
            receipt = accepted[artifact_id]
            assert receipt.receipt.sha256 == artifact.integrity.sha256
            assert receipt.run_id == artifact.producer.run_id
            assert receipt.context_manifest_id == artifact.context_manifest_id
            assert receipt.source_revision == artifact.source_revision
        assert (
            len(
                {
                    request.role
                    for request in adapter.requests
                    if request.role is not AgentRole.ORCHESTRATOR
                }
            )
            == 3
        )


@pytest.mark.parametrize("wrong_owner, expired", [(True, False), (False, True)])
def test_task_mutation_fence_rejects_wrong_owner_or_expired_lease(
    mysql_dsn: str, wrong_owner: bool, expired: bool
) -> None:
    queue = MySqlRoleQueue(mysql_dsn)
    claim = claim_step(queue, admit(queue))
    lease = WorkerLease(queue, claim, "incorrect-owner-token" if wrong_owner else TOKEN)
    with MySqlTaskRepository(mysql_dsn) as repository:
        task = make_task()
        repository.create(task)
        if expired:
            repository.mutation_fence = lambda cursor, task_id: queue.assert_owner(
                cursor, claim, TOKEN, now=claim.lease.expires_at
            )
        else:
            repository.mutation_fence = lease.mutation_fence
        with pytest.raises(QueueConflict):
            repository.record_attempt(task.id, 1)
        with pytest.raises(QueueConflict):
            repository.append_event(
                build_event(
                    task,
                    TaskStatus.PLANNING,
                    event_id="evt_fenced_planning",
                    reason="fixture",
                    source_revision=task.base_ref,
                    occurred_at=datetime.now(UTC),
                )
            )
        assert repository.get(task.id) == task
        assert repository.list_events(task.id) == ()
        assert repository.current_revision(task.id) == 0
        repository.mutation_fence = WorkerLease(queue, claim, TOKEN).mutation_fence
        repository.record_attempt(task.id, 1)
        assert repository.get(task.id).attempts == 1


def test_accepted_receipts_exclude_unaccepted_filesystem_residue(
    mysql_dsn: str, tmp_path: Path
) -> None:
    queue = MySqlRoleQueue(mysql_dsn)
    store = FileArtifactStore(tmp_path / "artifacts")
    plan = seal_artifact(make_plan_artifact(), validated_at=datetime.now(UTC))
    plan_ref = store.put(plan)
    step = admit(
        queue,
        legacy=(QueueArtifactReceipt(artifact_id=plan_ref.artifact_id, sha256=plan_ref.sha256),),
    )
    claim = claim_step(queue, step)
    guard = WorkerExecutionGuard()
    accepted_store = AcceptedArtifactStore(store, queue, plan.task_id, guard)
    output = seal_artifact(
        make_implementation_artifact().model_copy(
            update={"context_manifest_id": "ctx_" + "a" * 64}
        ),
        validated_at=datetime.now(UTC),
    )
    with pytest.raises(QueueConflict, match="active Worker"):
        accepted_store.put(output)
    residue = seal_artifact(
        output.model_copy(update={"artifact_id": "art_impl_residue"}),
        validated_at=datetime.now(UTC),
    )
    store.put(residue)
    assert len(store.list_for_task(plan.task_id)) == 2
    assert accepted_store.list_for_task(plan.task_id) == (plan,)
    with pytest.raises(QueueCorruption, match="accepted receipt"):
        accepted_store.get(residue.artifact_id)
    guard.lease = WorkerLease(queue, claim, "wrong-owner-token-0000")
    with pytest.raises(QueueConflict, match="owner"):
        accepted_store.put(output)
    assert not queue.accepted(plan.task_id)
    assert len(store.list_for_task(plan.task_id)) == 2
    guard.lease = WorkerLease(queue, claim, TOKEN)
    foreign_output = seal_artifact(
        output.model_copy(
            update={"producer": output.producer.model_copy(update={"agent_id": "agent_other_001"})}
        ),
        validated_at=datetime.now(UTC),
    )
    with pytest.raises(QueueConflict, match="claimed role"):
        accepted_store.put(foreign_output)
    assert not queue.accepted(plan.task_id)
    assert len(store.list_for_task(plan.task_id)) == 2
    reference = accepted_store.put(output)
    assert accepted_store.put(output) == reference
    (receipt,) = queue.accepted(plan.task_id)
    assert receipt.lease_id == claim.lease.id and receipt.work_item_id == step.work_item.id
    assert receipt.dispatch_sequence == claim.work_item.dispatch_sequence
    assert receipt.receipt.sha256 == output.integrity.sha256
    reopened = AcceptedArtifactStore(
        store, MySqlRoleQueue(mysql_dsn), plan.task_id, WorkerExecutionGuard()
    )
    assert {artifact.artifact_id for artifact in reopened.list_for_task(plan.task_id)} == {
        plan.artifact_id,
        output.artifact_id,
    }
    assert store.get(residue.artifact_id) == residue


def test_continued_coder_accepted_output_recovers_without_repeating_model_after_event_crash(
    mysql_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = MySqlRoleQueue(mysql_dsn)
    first = ObservedAdapter(queue, coder_progress=(1,))
    with runtime_fixture(tmp_path, mysql_dsn, queue, first) as (runtime, supervisor):
        append_event = runtime.task_repository.append_event

        def crash_before_candidate_event(event: StateEvent) -> None:
            if event.to_status is TaskStatus.QA:
                raise RuntimeError("fixture crash after accepted output before candidate event")
            append_event(event)

        monkeypatch.setattr(runtime.task_repository, "append_event", crash_before_candidate_event)
        with pytest.raises(RuntimeError, match="accepted output before candidate event"):
            run_supervisor(runtime, supervisor)
        task = runtime.task_repository.get("task_domain_001")
        assert task.status is TaskStatus.IMPLEMENTING and task.attempts == 2
        assert [role for role, _ in first.invocation_claims] == [AgentRole.CODER, AgentRole.CODER]
        assert {record.receipt.artifact_id for record in queue.accepted(task.id)} == {
            "art_progress_001",
            "art_impl_002",
        }
        (lease,) = queue.list_active_leases(now=datetime.now(UTC))
    reclaimed = queue.reclaim_expired(
        now=lease.expires_at, retry_at=lease.expires_at + timedelta(seconds=1)
    )
    assert len(reclaimed) == 1
    queue.make_ready(reclaimed[0].id, now=lease.expires_at + timedelta(seconds=2))
    resumed = ObservedAdapter(queue)
    with runtime_fixture(tmp_path, mysql_dsn, queue, resumed) as (runtime, supervisor):
        result = run_supervisor(runtime, supervisor)
        assert result.task.status is TaskStatus.DONE
        assert [role for role, _ in resumed.invocation_claims] == [AgentRole.QA, AgentRole.REVIEWER]


def test_same_task_two_roles_cannot_obtain_parallel_claims(mysql_dsn: str) -> None:
    queue = MySqlRoleQueue(mysql_dsn)
    coder = admit(queue)
    qa = make_step(
        RoleRunBoundary(coder.boundary.task_id, AgentRole.QA, 1, 1, "b" * 40),
        coder.work_item.id,
        datetime.now(UTC),
    )
    queue.enqueue(qa.work_item)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(
                lambda step: dispatcher(queue).tick(
                    now=datetime.now(UTC), work_item_id=step.work_item.id
                ),
                (coder, qa),
            )
        )
    assert sum(result.status is DispatcherTickStatus.DISPATCHED for result in results) == 1
    assert len(queue.list_active_leases(now=datetime.now(UTC))) == 1
    assert len(queue.list_assignments()) == 1


def test_adoption_releases_native_capacity_preserving_dispatch_and_assignment_history(
    mysql_dsn: str, tmp_path: Path
) -> None:
    _, snapshot, record, plans, revisions = _durable_facts(tmp_path)
    authority = MySqlDispatchAuthority(
        mysql_dsn, request_revisions=revisions, planner_records=plans
    )
    authority.seed_snapshot(snapshot)
    authority.commit_if_current(record, expected_snapshot_sha256=snapshot.snapshot_sha256)
    queue = production_role_queue(mysql_dsn)
    before = authority.current_snapshot(repository_id=record.repository_id, task_id=record.task_id)
    assert {phase.lease.id for phase in record.phases} <= {
        lease.id for lease in before.active_leases
    }
    assert {phase.lease.id for phase in record.phases} <= {
        lease.id for lease in queue.list_active_leases(now=record.committed_at)
    }
    boundary = RoleRunBoundary(record.task_id, AgentRole.CODER, 1, 0, record.task.base_ref)
    step = make_step(boundary, None, datetime.now(UTC))
    step = step.model_copy(
        update={
            "work_item": step.work_item.model_copy(update={"repository_id": record.repository_id})
        }
    )
    admission = RoleQueueAdmission(
        task_id=record.task_id,
        repository_id=record.repository_id,
        allocation_sha256=ALLOCATION_SHA,
        legacy_artifacts=(),
    )
    queue.admit(admission, step)
    after = authority.current_snapshot(repository_id=record.repository_id, task_id=record.task_id)
    assert not any(lease.task_id == record.task_id for lease in after.active_leases)
    assert not any(
        lease.task_id == record.task_id
        for lease in queue.list_active_leases(now=record.committed_at)
    )
    assert after.assignments == before.assignments
    assert authority.get_commit(record.id) == record
    assert queue.list_assignments() == tuple(phase.assignment for phase in record.phases)


class CrashBeforeCoderFinish(MySqlRoleQueue):
    """One injected crash after Task reaches QA but before queue completion."""

    crashed = False
    interrupted_claim: QueueClaim | None = None

    def finish(
        self,
        claim: QueueClaim,
        token: str,
        *,
        next_step: QueuedRoleStep | None,
        now: datetime,
        guard: Callable[[], None] | None = None,
    ) -> QueueCompletion:
        if not self.crashed and next_step is not None and next_step.boundary.role is AgentRole.QA:
            self.crashed = True
            self.interrupted_claim = claim
            raise RuntimeError("fixture crash after QA transition before queue finish")
        return super().finish(claim, token, next_step=next_step, now=now, guard=guard)


def test_crash_after_qa_transition_reconciles_claim_without_repeating_coder(
    mysql_dsn: str, tmp_path: Path
) -> None:
    queue = CrashBeforeCoderFinish(mysql_dsn)
    first = ObservedAdapter(queue)
    with runtime_fixture(tmp_path, mysql_dsn, queue, first) as (runtime, supervisor):
        with pytest.raises(RuntimeError, match="fixture crash"):
            run_supervisor(runtime, supervisor)
        assert runtime.task_repository.get("task_domain_001").status is TaskStatus.QA
        assert [role for role, _ in first.invocation_claims] == [AgentRole.CODER]
        assert len(queue.accepted("task_domain_001")) == 1
        with pytest.raises(DeliveryQueuePending):
            run_supervisor(runtime, supervisor)
        assert [role for role, _ in first.invocation_claims] == [AgentRole.CODER]
    assert queue.interrupted_claim is not None
    expires = queue.interrupted_claim.lease.expires_at
    reclaimed = queue.reclaim_expired(now=expires, retry_at=expires + timedelta(seconds=1))
    assert len(reclaimed) == 1
    queue.make_ready(reclaimed[0].id, now=expires + timedelta(seconds=2))
    reopened = MySqlRoleQueue(mysql_dsn)
    resumed = ObservedAdapter(reopened)
    with runtime_fixture(tmp_path, mysql_dsn, reopened, resumed) as (runtime, supervisor):
        result = run_supervisor(runtime, supervisor)
        assert result.task.status is TaskStatus.DONE
        assert [role for role, _ in resumed.invocation_claims] == [AgentRole.QA, AgentRole.REVIEWER]
        assert len(reopened.accepted(result.task.id)) == 3
        assert len(reopened.list_assignments()) == 4
        assert all(
            item.status is WorkItemStatus.CLOSED for item in reopened.items_for_task(result.task.id)
        )


class ResolvedKnowledgeModel(Model):
    """Only the interrupted Coder needs the approved fact; other roles ask no questions."""

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        self.calls.append(str(output_schema["title"]))
        return StructuredModelResult(payload={"queries": []}, duration_ms=0)


@pytest.mark.parametrize("crash_before_wait", [False, True])
def test_worker_knowledge_wait_and_restart_require_approved_resolution(
    mysql_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_before_wait: bool,
) -> None:
    clients = Clients()
    queue = MySqlRoleQueue(mysql_dsn)
    adapter = ObservedAdapter(queue)
    with runtime_fixture(
        tmp_path,
        mysql_dsn,
        queue,
        adapter,
        knowledge_clients=clients,
    ) as (runtime, supervisor):
        if crash_before_wait:
            with monkeypatch.context() as patch:

                def interrupted_wait(*args: object) -> None:
                    raise RuntimeError("crash after durable gap route")

                patch.setattr(WorkerKnowledgeWait, "wait", interrupted_wait)
                with pytest.raises(RuntimeError, match="durable gap route"):
                    run_supervisor(runtime, supervisor)
            (lease,) = queue.list_active_leases(now=datetime.now(UTC))
            (reclaimed,) = queue.reclaim_expired(
                now=lease.expires_at,
                retry_at=lease.expires_at + timedelta(seconds=1),
            )
            queue.make_ready(reclaimed.id, now=lease.expires_at + timedelta(seconds=2))
        with pytest.raises(KnowledgeGapRaised) as caught:
            run_supervisor(runtime, supervisor)
        gap = caught.value.gap
        retained = runtime.task_repository.get(gap.binding.task_id or "")
        assert retained.status is TaskStatus.IMPLEMENTING and retained.attempts == 1
        (waiting,) = queue.items_for_task(retained.id)
        assert waiting.status is WorkItemStatus.WAITING_HUMAN
        assert not queue.list_active_leases(now=datetime.now(UTC))
        assert adapter.invocation_claims == []
        assert clients.model.calls == ["KnowledgeIntent", "KnowledgeAssessment"]
    # A new Runtime/Worker does not retry either model while the gap remains open.
    with runtime_fixture(
        tmp_path,
        mysql_dsn,
        queue,
        adapter,
        knowledge_clients=clients,
    ) as (runtime, supervisor):
        with pytest.raises(KnowledgeGapRaised):
            run_supervisor(runtime, supervisor)
        assert runtime.task_repository.get(retained.id) == retained
        assert queue.get(waiting.id) == waiting
        answer = "Use the original payment identity."
        resolution = KnowledgeResolution(
            gap_id=gap.gap_id,
            previous_run_id=gap.binding.run_id,
            answer=answer,
            sources=(
                KnowledgeResolutionSource(
                    uri="human://worker-test/approval",
                    sha256=text_digest(answer),
                    content=answer,
                ),
            ),
            approval_reference="approval_worker_test",
            approved_by="human:owner",
            resolution_id="0" * 64,
        )
        resolution = resolution.model_copy(
            update={
                "resolution_id": digest(
                    resolution.model_dump(mode="json", exclude={"resolution_id"})
                ),
            }
        )
        KnowledgeGapService(supervisor.records).resolve(resolution, Approval(resolution))
    clients.model = ResolvedKnowledgeModel()
    with runtime_fixture(
        tmp_path,
        mysql_dsn,
        queue,
        adapter,
        knowledge_clients=clients,
    ) as (runtime, supervisor):
        result = run_supervisor(runtime, supervisor)
        assert result.task.status is TaskStatus.DONE and result.task.attempts == 1
        assert [role for role, _ in adapter.invocation_claims] == [
            AgentRole.CODER,
            AgentRole.QA,
            AgentRole.REVIEWER,
        ]
        (resume,) = supervisor.records.list("gap-resumes", KnowledgeResume)
        assert resume.previous_binding == gap.binding
        assert resume.resolution_id == resolution.resolution_id
        assert resume.new_binding.context_manifest_id != gap.binding.context_manifest_id
        assert queue.get(waiting.id).status is WorkItemStatus.CLOSED
        assert queue.get(waiting.id).dispatch_sequence > waiting.dispatch_sequence


def test_worker_heartbeats_and_fails_closed_on_renewal_loss(
    mysql_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = MySqlRoleQueue(mysql_dsn)
    claim = claim_step(queue, admit(queue))
    renewed, fail_renewal, failed = Event(), Event(), Event()
    original = queue.renew

    def renew(*args: object, **kwargs: object) -> TaskLease:
        if fail_renewal.is_set():
            failed.set()
            raise QueueConflict("injected ownership loss")
        result = original(*args, **kwargs)  # type: ignore[arg-type]
        renewed.set()
        return result

    monkeypatch.setattr(queue, "renew", renew)
    lease = WorkerLease(queue, claim, TOKEN)
    lease._ttl = timedelta(seconds=1)
    lease.start()
    try:
        assert renewed.wait(5)
        lease.check()
        fail_renewal.set()
        assert failed.wait(5)
        # stop joins the heartbeat so its lost-owner flag is visible deterministically.
        lease.stop()
        with pytest.raises(QueueConflict, match="renewal was lost"):
            lease.check()
        with pytest.raises(QueueConflict):
            lease.finish(None, datetime.now(UTC))
        assert queue.get(claim.work_item.id).status is WorkItemStatus.RUNNING
        assert not queue.accepted(claim.work_item.task_id)
    finally:
        lease.stop()


@pytest.mark.parametrize("loss_at", ["authority_lock", "release_claim", "heartbeat"])
def test_completion_rechecks_ownership_inside_transaction(
    mysql_dsn: str, monkeypatch: pytest.MonkeyPatch, loss_at: str
) -> None:
    queue = MySqlRoleQueue(mysql_dsn)
    claim = claim_step(queue, admit(queue))
    now = datetime.now(UTC)
    queue.start(claim.work_item.id, lease_id=claim.lease.id, owner_token=TOKEN, now=now)
    lease = WorkerLease(queue, claim, TOKEN)
    next_step = make_step(
        RoleRunBoundary(claim.work_item.task_id, AgentRole.QA, 1, 1, "candidate"),
        claim.work_item.id,
        now,
    )
    clock = now
    monkeypatch.setattr(queue, "_clock", lambda: clock, raising=False)
    lock = queue._lock_authority
    release = queue._release_claim

    def lock_with_delay(cursor: object) -> None:
        nonlocal clock
        lock(cursor)
        if loss_at == "authority_lock":
            clock = claim.lease.expires_at

    def release_with_delay(
        cursor: object, lease_id: str, *, state: str, ended_at: datetime
    ) -> None:
        nonlocal clock
        release(cursor, lease_id, state=state, ended_at=ended_at)
        if loss_at == "release_claim":
            clock = claim.lease.expires_at
        elif loss_at == "heartbeat":
            lease._lost.set()

    monkeypatch.setattr(queue, "_lock_authority", lock_with_delay)
    monkeypatch.setattr(queue, "_release_claim", release_with_delay)
    with pytest.raises(QueueLeaseLost):
        lease.finish(next_step, now)
    assert queue.get(claim.work_item.id).status is WorkItemStatus.RUNNING
    assert len(queue.list_active_leases(now=now)) == 1
    with pytest.raises(QueueNotFound):
        queue.get(next_step.work_item.id)
    with pytest.raises(QueueNotFound):
        queue.step(next_step.work_item.id)
