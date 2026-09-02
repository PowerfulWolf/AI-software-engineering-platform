"""Project Manager commit-dispatch current-fact and atomic persistence tests."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.domain.enums import (
    AgentRole,
    BrainTier,
    OrganizationRole,
    RiskTier,
    WorkItemStatus,
)
from ai_software_engineer.domain.project_delivery import ExecutionPlan, derive_delivery_task
from ai_software_engineer.domain.workforce import (
    AgentProfile,
    ModelPolicy,
    ModelRoute,
    RiskModelFloor,
    RunDemand,
    TaskLease,
    WorkItem,
)
from ai_software_engineer.planning.models import (
    PlannerCommitCheckpoint,
    PlannerRunOutcome,
    PlannerRunRecord,
)
from ai_software_engineer.planning.preview import PlanningPreviewService
from ai_software_engineer.product.models import ProjectRequestRevision
from ai_software_engineer.project_manager.dispatch import (
    CommitDispatchRequest,
    DispatchAuthorityConflict,
    DispatchCommitConflict,
    DispatchCommitCorruption,
    DispatchCommitRecord,
    DispatchPreviewStale,
    DispatchRejected,
    DispatchWorkforceSnapshot,
    FileDispatchCommitStore,
    ProjectManagerDispatchService,
)
from ai_software_engineer.project_manager.stages import (
    ProjectStage,
    ProjectStageAdvancer,
    StageAdvanceRequest,
)
from ai_software_engineer.scheduling import (
    AssignmentDecisionStatus,
    ModelRejectionCode,
    ModelRouter,
    ModelRoutingDecision,
    ModelRoutingDecisionStatus,
    ModelRoutingRefusal,
    PortfolioScheduler,
)
from tests.project_manager.test_contracts import NOW, stage_chain

PREVIEWED_AT = NOW + timedelta(minutes=5)
COMMITTED_AT = NOW + timedelta(minutes=6)


class RecordingDispatchStore:
    def __init__(self) -> None:
        self.records: list[DispatchCommitRecord] = []

    def commit(self, record: DispatchCommitRecord) -> DispatchCommitRecord:
        self.records.append(record)
        return record


class RecordingDispatchAuthority:
    def __init__(
        self,
        snapshot: DispatchWorkforceSnapshot,
        store: RecordingDispatchStore,
    ) -> None:
        self.snapshot = snapshot
        self.store = store

    def current_snapshot(
        self,
        *,
        project_id: str,
        task_id: str,
    ) -> DispatchWorkforceSnapshot:
        assert (project_id, task_id) == (self.snapshot.project_id, self.snapshot.task_id)
        return self.snapshot

    def commit_if_current(
        self,
        record: DispatchCommitRecord,
        *,
        expected_snapshot_sha256: str,
    ) -> DispatchCommitRecord:
        self.snapshot.validate_integrity()
        if self.snapshot.snapshot_sha256 != expected_snapshot_sha256:
            raise DispatchAuthorityConflict("authoritative snapshot changed before commit")
        return self.store.commit(record)


class DriftBeforeCommitAuthority(RecordingDispatchAuthority):
    """Simulate a concurrent organization writer after decisions but before reservation."""

    def commit_if_current(
        self,
        record: DispatchCommitRecord,
        *,
        expected_snapshot_sha256: str,
    ) -> DispatchCommitRecord:
        changed = self.snapshot.agents[0].model_copy(update={"version": "concurrent-v2"})
        self.snapshot = DispatchWorkforceSnapshot.create(
            project_id=self.snapshot.project_id,
            task_id=self.snapshot.task_id,
            work_item=self.snapshot.work_item,
            agents=(changed, *self.snapshot.agents[1:]),
            active_leases=self.snapshot.active_leases,
            assignments=self.snapshot.assignments,
            model_policies=self.snapshot.model_policies,
        )
        return super().commit_if_current(
            record,
            expected_snapshot_sha256=expected_snapshot_sha256,
        )


class RecordingDispatchStageFacts:
    def __init__(
        self,
        revision: ProjectRequestRevision,
        run: PlannerRunRecord,
        checkpoint: PlannerCommitCheckpoint,
    ) -> None:
        self.revision = revision
        self.run = run
        self.checkpoint = checkpoint
        self.revision_reads = 0

    def current_request_revision(self, request_id: str) -> ProjectRequestRevision:
        assert request_id == self.revision.request.id
        self.revision_reads += 1
        return self.revision

    def get_checkpoint(self, run_id: str) -> PlannerCommitCheckpoint:
        del run_id
        return self.checkpoint

    def get_run(self, run_id: str) -> PlannerRunRecord:
        del run_id
        return self.run

    def get_execution_plan(self, plan_id: str) -> ExecutionPlan:
        assert self.run.execution_plan is not None
        assert plan_id == self.run.execution_plan.id
        return self.run.execution_plan


class DriftOnSecondRevisionRead(RecordingDispatchStageFacts):
    """Advance the READY revision after routing but before workforce commit."""

    def current_request_revision(self, request_id: str) -> ProjectRequestRevision:
        current = super().current_request_revision(request_id)
        if self.revision_reads < 2:
            return current
        request = current.request
        changed = type(request).create(
            request_id=request.id,
            project_id=request.project_id,
            preparation_sha256=request.preparation_sha256,
            title=request.title,
            original_request=request.original_request,
            status=request.status,
            created_at=request.created_at,
            updated_at=request.updated_at + timedelta(seconds=1),
        )
        return ProjectRequestRevision.create(
            changed,
            revision=current.revision + 1,
            supersedes_sha256=current.request_revision_sha256,
            recorded_at=changed.updated_at,
        )


class RejectReviewerRouter(ModelRouter):
    def route(
        self,
        demand: RunDemand,
        agent: AgentProfile,
        policy: ModelPolicy,
        *,
        now: datetime,
    ) -> ModelRoutingDecision:
        if demand.role is AgentRole.REVIEWER:
            return ModelRoutingDecision(
                status=ModelRoutingDecisionStatus.REJECTED,
                task_id=demand.task_id,
                agent_id=agent.id,
                role=demand.role,
                refusal=ModelRoutingRefusal(
                    code=ModelRejectionCode.NO_ELIGIBLE_ROUTE,
                    message="review route disabled at commit",
                    required_tier=BrainTier.STANDARD,
                ),
                decided_at=now,
            )
        return super().route(demand, agent, policy, now=now)


def _agents() -> tuple[AgentProfile, AgentProfile, AgentProfile]:
    return tuple(  # type: ignore[return-value]
        AgentProfile(
            id=f"agent_{name}_001",
            version="v1",
            display_name=name,
            capabilities=("python", "contract-validation"),
            eligible_roles=(
                OrganizationRole.CODER,
                OrganizationRole.QA,
                OrganizationRole.REVIEWER,
            ),
            max_parallel_assignments=1,
            default_model_policy_id="model_policy_delivery_001",
        )
        for name in ("alpha", "beta", "gamma")
    )


def _policy() -> ModelPolicy:
    return ModelPolicy(
        id="model_policy_delivery_001",
        version="v1",
        default_tier=BrainTier.STANDARD,
        routes=tuple(
            ModelRoute(provider="provider_a", model=f"model_{tier.value}", tier=tier)
            for tier in BrainTier
        ),
        risk_floors=(
            RiskModelFloor(risk=RiskTier.LOW, minimum_tier=BrainTier.ECONOMY),
            RiskModelFloor(risk=RiskTier.NORMAL, minimum_tier=BrainTier.STANDARD),
            RiskModelFloor(risk=RiskTier.HIGH, minimum_tier=BrainTier.REASONING),
            RiskModelFloor(risk=RiskTier.CRITICAL, minimum_tier=BrainTier.CRITICAL),
        ),
    )


def _router() -> ModelRouter:
    return ModelRouter(
        route_context_capacities={
            ("provider_a", f"model_{tier.value}"): 100_000 for tier in BrainTier
        }
    )


def _future_lease(agent: AgentProfile, index: int) -> TaskLease:
    return TaskLease(
        id=f"lease_future_{index:03d}",
        assignment_id=f"assignment_future_{index:03d}",
        task_id=f"task_other_{index:03d}",
        agent_id=agent.id,
        acquired_at=PREVIEWED_AT + timedelta(seconds=30),
        expires_at=COMMITTED_AT + timedelta(minutes=10),
    )


def _facts(
    tmp_path: Path,
    *,
    active_leases: tuple[TaskLease, ...] = (),
) -> tuple[CommitDispatchRequest, DispatchWorkforceSnapshot]:
    prepared, project_request, spec, approval, design, plan = stage_chain(tmp_path)
    ready_revision = ProjectRequestRevision.create(
        project_request,
        revision=3,
        supersedes_sha256="d" * 64,
        recorded_at=project_request.updated_at,
    )
    planner_run = PlannerRunRecord.create(
        run_id="run_dispatch_planner_001",
        project_id=project_request.project_id,
        request_id=project_request.id,
        context_id="ctx_" + "a" * 64,
        input_sha256="b" * 64,
        input_request_revision_sha256="d" * 64,
        design_checkpoint_sha256="c" * 64,
        planning_authorization_sha256="e" * 64,
        outcome=PlannerRunOutcome.READY_FOR_DELIVERY,
        execution_plan=plan,
        ready_request_revision=ready_revision,
        recorded_at=plan.created_at,
    )
    planner_checkpoint = PlannerCommitCheckpoint.create(
        planner_run,
        committed_at=plan.created_at,
    )
    task = derive_delivery_task(
        prepared,
        project_request,
        spec,
        approval,
        design,
        plan,
        task_id="task_dispatch_001",
        repository=prepared.project_root,
        base_ref="a" * 40,
        max_attempts=3,
        created_at=PREVIEWED_AT,
    )
    work_item = WorkItem(
        task_id=task.id,
        project_id=prepared.project_id,
        status=WorkItemStatus.READY,
        priority=500,
        risk=RiskTier.HIGH,
        required_capabilities=("python", "contract-validation"),
        created_at=PREVIEWED_AT,
        updated_at=PREVIEWED_AT,
    )
    agents = _agents()
    policies = (_policy(),)
    preview = PlanningPreviewService(
        scheduler=PortfolioScheduler(),
        model_router=_router(),
    ).preview(
        task=task,
        work_item=work_item,
        execution_plan=plan,
        agents=agents,
        active_leases=active_leases,
        assignments=(),
        policies=policies,
        previewed_at=PREVIEWED_AT,
    )
    authorization = ProjectStageAdvancer().advance_stage(
        StageAdvanceRequest(
            target=ProjectStage.DELIVERY_DISPATCH,
            preparation=prepared,
            project_request=project_request,
            product_spec=spec,
            product_approval=approval,
            technical_design=design,
            execution_plan=plan,
        ),
        authorized_at=PREVIEWED_AT,
    )
    request = CommitDispatchRequest(
        preparation=prepared,
        project_request=project_request,
        product_spec=spec,
        product_approval=approval,
        technical_design=design,
        execution_plan=plan,
        ready_request_revision=ready_revision,
        planner_run_record=planner_run,
        planner_checkpoint=planner_checkpoint,
        stage_authorization=authorization,
        planning_preview=preview,
        task_id=task.id,
        repository=prepared.project_root,
        base_ref=task.base_ref,
        max_attempts=task.max_attempts,
        task_created_at=task.created_at,
        committed_at=COMMITTED_AT,
    )
    snapshot = DispatchWorkforceSnapshot.create(
        project_id=prepared.project_id,
        task_id=task.id,
        work_item=work_item,
        agents=agents,
        active_leases=active_leases,
        model_policies=policies,
    )
    return request, snapshot


def _service(
    store: RecordingDispatchStore,
    snapshot: DispatchWorkforceSnapshot,
    request: CommitDispatchRequest,
    *,
    stage_facts: RecordingDispatchStageFacts | None = None,
) -> ProjectManagerDispatchService:
    facts = stage_facts or RecordingDispatchStageFacts(
        request.ready_request_revision,
        request.planner_run_record,
        request.planner_checkpoint,
    )
    return ProjectManagerDispatchService(
        scheduler=PortfolioScheduler(),
        model_router=_router(),
        authority=RecordingDispatchAuthority(snapshot, store),
        request_revisions=facts,
        planner_records=facts,
    )


def test_commit_reruns_three_phases_and_atomically_persists_new_task(tmp_path: Path) -> None:
    store = RecordingDispatchStore()
    request, snapshot = _facts(tmp_path)
    record = _service(store, snapshot, request).commit_dispatch(request)

    assert store.records == [record]
    assert record.task.status.value == "NEW"
    assert tuple(phase.role for phase in record.phases) == (
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    )
    assert len({phase.agent_id for phase in record.phases}) == 3
    assert all(
        phase.assignment.task_id == record.task.id and phase.lease.task_id == record.task.id
        for phase in record.phases
    )
    record.validate_integrity()


def test_changed_current_workforce_or_expired_preview_writes_nothing(tmp_path: Path) -> None:
    store = RecordingDispatchStore()
    request, snapshot = _facts(tmp_path)
    changed_agent = snapshot.agents[0].model_copy(update={"version": "v2"})
    current = DispatchWorkforceSnapshot.create(
        project_id=snapshot.project_id,
        task_id=snapshot.task_id,
        work_item=snapshot.work_item,
        agents=(changed_agent, *snapshot.agents[1:]),
        active_leases=snapshot.active_leases,
        assignments=snapshot.assignments,
        model_policies=snapshot.model_policies,
    )

    with pytest.raises(DispatchPreviewStale, match="workforce"):
        _service(store, current, request).commit_dispatch(request)
    with pytest.raises(DispatchPreviewStale, match="expired"):
        _service(store, snapshot, request).commit_dispatch(
            request.model_copy(update={"committed_at": request.planning_preview.valid_until})
        )

    assert store.records == []


def test_commit_time_capacity_refusal_after_two_phase_calculations_writes_nothing(
    tmp_path: Path,
) -> None:
    agents = _agents()
    future_leases = tuple(_future_lease(agent, index) for index, agent in enumerate(agents, 1))
    request, snapshot = _facts(tmp_path, active_leases=future_leases)
    store = RecordingDispatchStore()

    with pytest.raises(DispatchRejected, match="capacity"):
        _service(store, snapshot, request).commit_dispatch(request)

    assert store.records == []


def test_model_refusal_at_last_phase_still_has_zero_partial_writes(tmp_path: Path) -> None:
    store = RecordingDispatchStore()
    request, snapshot = _facts(tmp_path)
    facts = RecordingDispatchStageFacts(
        request.ready_request_revision,
        request.planner_run_record,
        request.planner_checkpoint,
    )
    service = ProjectManagerDispatchService(
        scheduler=PortfolioScheduler(),
        model_router=RejectReviewerRouter(
            route_context_capacities={
                ("provider_a", f"model_{tier.value}"): 100_000 for tier in BrainTier
            }
        ),
        authority=RecordingDispatchAuthority(snapshot, store),
        request_revisions=facts,
        planner_records=facts,
    )

    with pytest.raises(DispatchRejected, match="review route disabled"):
        service.commit_dispatch(request)

    assert store.records == []


def test_commit_window_authority_drift_writes_nothing(tmp_path: Path) -> None:
    request, snapshot = _facts(tmp_path)
    store = RecordingDispatchStore()
    facts = RecordingDispatchStageFacts(
        request.ready_request_revision,
        request.planner_run_record,
        request.planner_checkpoint,
    )
    service = ProjectManagerDispatchService(
        scheduler=PortfolioScheduler(),
        model_router=_router(),
        authority=DriftBeforeCommitAuthority(snapshot, store),
        request_revisions=facts,
        planner_records=facts,
    )

    with pytest.raises(DispatchAuthorityConflict, match="changed before commit"):
        service.commit_dispatch(request)

    assert store.records == []


def test_fabricated_planner_checkpoint_is_not_accepted_as_durable_handoff(
    tmp_path: Path,
) -> None:
    request, snapshot = _facts(tmp_path)
    store = RecordingDispatchStore()
    durable = RecordingDispatchStageFacts(
        request.ready_request_revision,
        request.planner_run_record,
        request.planner_checkpoint,
    )
    predecessor = request.ready_request_revision.supersedes_sha256
    assert predecessor is not None
    fabricated_run = PlannerRunRecord.create(
        run_id="run_dispatch_planner_fabricated",
        project_id=request.project_request.project_id,
        request_id=request.project_request.id,
        context_id="ctx_" + "f" * 64,
        input_sha256="1" * 64,
        input_request_revision_sha256=predecessor,
        design_checkpoint_sha256="2" * 64,
        planning_authorization_sha256="3" * 64,
        outcome=PlannerRunOutcome.READY_FOR_DELIVERY,
        execution_plan=request.execution_plan,
        ready_request_revision=request.ready_request_revision,
        recorded_at=request.execution_plan.created_at,
    )
    fabricated = PlannerCommitCheckpoint.create(
        fabricated_run,
        committed_at=request.execution_plan.created_at,
    )
    changed_request = request.model_copy(
        update={"planner_run_record": fabricated_run, "planner_checkpoint": fabricated}
    )

    with pytest.raises(DispatchPreviewStale, match="no longer authoritative"):
        _service(
            store,
            snapshot,
            changed_request,
            stage_facts=durable,
        ).commit_dispatch(changed_request)

    assert store.records == []


def test_ready_revision_change_during_routing_prevents_dispatch_commit(
    tmp_path: Path,
) -> None:
    request, snapshot = _facts(tmp_path)
    store = RecordingDispatchStore()
    facts = DriftOnSecondRevisionRead(
        request.ready_request_revision,
        request.planner_run_record,
        request.planner_checkpoint,
    )

    with pytest.raises(DispatchPreviewStale, match="no longer authoritative"):
        _service(
            store,
            snapshot,
            request,
            stage_facts=facts,
        ).commit_dispatch(request)

    assert facts.revision_reads == 2
    assert store.records == []


def test_file_store_exact_replay_conflict_and_tamper_rejection(tmp_path: Path) -> None:
    memory = RecordingDispatchStore()
    request, snapshot = _facts(tmp_path)
    record = _service(memory, snapshot, request).commit_dispatch(request)
    store = FileDispatchCommitStore((tmp_path / "sidecar-dispatch").resolve())

    assert store.commit(record) == record
    assert store.commit(record) == record
    changed = DispatchCommitRecord.create(
        project_id=record.project_id,
        execution_plan=request.execution_plan,
        preview=request.planning_preview,
        ready_request_revision=request.ready_request_revision,
        planner_checkpoint=request.planner_checkpoint,
        planner_run_record=request.planner_run_record,
        stage_authorization=request.stage_authorization,
        task=record.task,
        phases=(record.phases[0], record.phases[1], record.phases[2]),
        committed_at=record.committed_at + timedelta(seconds=1),
    )
    with pytest.raises(DispatchCommitConflict):
        store.commit(changed)

    path = tmp_path / "sidecar-dispatch" / f"{record.id}.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["record"]["task"]["title"] = "tampered"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(DispatchCommitCorruption):
        store.get(record.id)


def test_preview_decisions_are_selected_before_commit(tmp_path: Path) -> None:
    request, _ = _facts(tmp_path)
    assert all(
        phase.assignment_decision.status is AssignmentDecisionStatus.ASSIGNED
        for phase in request.planning_preview.phases
    )
