"""Planner production service and append-only stage transition tests."""

from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.domain import (
    ExecutionPlan,
    ProductSpec,
    ProductSpecApproval,
    ProjectRequestStatus,
    TechnicalDesign,
)
from ai_software_engineer.planning import (
    FakePlannerAgentAdapter,
    FakePlannerBehavior,
    FakePlannerScenario,
    PlannerAgentRequest,
    PlannerAgentResult,
    PlannerCommitCheckpoint,
    PlannerContextBuilder,
    PlannerRunRecord,
    PlannerStageService,
    PlanningStageStaleRequest,
    ProduceExecutionPlanCommand,
)
from ai_software_engineer.product.models import ProjectRequestRevision
from ai_software_engineer.product.store import FileProductRecordStore
from tests.planning.conftest import (
    NOW,
    approval,
    committed_design_handoff,
    designing_request_revision,
    execution_plan,
    planning_request,
    preparation,
    product_spec,
    request_revision,
    technical_design,
)


class InMemoryExecutionPlanStore:
    """Append-only exact-replay test double for the plan publication port."""

    def __init__(self, *, fail_once_after_write: bool = False) -> None:
        self.records: dict[str, ExecutionPlan] = {}
        self.runs: dict[str, PlannerRunRecord] = {}
        self.checkpoints: dict[str, PlannerCommitCheckpoint] = {}
        self.fail_once_after_write = fail_once_after_write
        self.failed = False

    def put_execution_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        existing = self.records.get(plan.id)
        if existing is not None and existing != plan:
            raise RuntimeError("ExecutionPlan conflict")
        self.records[plan.id] = plan
        if self.fail_once_after_write and not self.failed:
            self.failed = True
            raise RuntimeError("simulated crash after immutable plan publication")
        return self.records[plan.id]

    def find_for_request(self, request_id: str) -> ExecutionPlan | None:
        matches = tuple(plan for plan in self.records.values() if plan.request_id == request_id)
        if not matches:
            return None
        return max(matches, key=lambda plan: plan.version)

    def put_run(self, record: PlannerRunRecord) -> PlannerRunRecord:
        existing = self.runs.setdefault(record.run_id, record)
        if existing != record:
            raise RuntimeError("Planner run conflict")
        return existing

    def find_run(self, run_id: str) -> PlannerRunRecord | None:
        return self.runs.get(run_id)

    def put_checkpoint(self, checkpoint: PlannerCommitCheckpoint) -> PlannerCommitCheckpoint:
        existing = self.checkpoints.setdefault(checkpoint.run_id, checkpoint)
        if existing != checkpoint:
            raise RuntimeError("Planner checkpoint conflict")
        return existing

    def find_checkpoint(self, run_id: str) -> PlannerCommitCheckpoint | None:
        return self.checkpoints.get(run_id)


class AdvanceRevisionDuringPlannerRun(FakePlannerAgentAdapter):
    """Simulate a concurrent request writer while the Planner model is running."""

    def __init__(
        self,
        scenario: FakePlannerScenario,
        store: FileProductRecordStore,
        current: ProjectRequestRevision,
    ) -> None:
        super().__init__(default=scenario)
        self._store = store
        self._current = current

    def run(self, request: PlannerAgentRequest) -> PlannerAgentResult:
        advanced = ProjectRequestRevision.create(
            self._current.request,
            revision=self._current.revision + 1,
            supersedes_sha256=self._current.request_revision_sha256,
            recorded_at=self._current.recorded_at,
        )
        self._store.compare_and_put_request_revision(
            advanced,
            expected_current_sha256=self._current.request_revision_sha256,
        )
        return super().run(request)


def _inputs(
    tmp_path: Path,
) -> tuple[
    ProjectRequestRevision,
    ProductSpec,
    ProductSpecApproval,
    TechnicalDesign,
    ExecutionPlan,
]:
    current_request = planning_request(preparation(tmp_path))
    current_revision = request_revision(current_request)
    spec = product_spec(current_request)
    approved = approval(spec)
    design = technical_design(spec, approved)
    plan = execution_plan(spec, design)
    return current_revision, spec, approved, design, plan


def test_success_publishes_plan_then_appends_ready_request_revision(tmp_path: Path) -> None:
    current, spec, approved, design, plan = _inputs(tmp_path)
    request_store = FileProductRecordStore(tmp_path / "product-records")
    request_store.put_request_revision(designing_request_revision(current.request))
    request_store.put_request_revision(current)
    design_store, checkpoint = committed_design_handoff(tmp_path, current, spec, approved, design)
    design_run = design_store.get_run(checkpoint.run_id)
    assert design_run.planning_authorization is not None
    plan_store = InMemoryExecutionPlanStore()
    service = PlannerStageService(
        context_builder=PlannerContextBuilder(),
        adapter=FakePlannerAgentAdapter(
            default=FakePlannerScenario(
                behavior=FakePlannerBehavior.READY,
                execution_plan=plan,
            )
        ),
        execution_plans=plan_store,
        request_revisions=request_store,
        design_records=design_store,
    )
    command = ProduceExecutionPlanCommand(
        run_id="run_planner_service_001",
        current_request_revision=current,
        product_spec=spec,
        product_approval=approved,
        technical_design=design,
        design_checkpoint=checkpoint,
        planning_authorization=design_run.planning_authorization,
        expected_execution_plan_version=1,
        transitioned_at=NOW + timedelta(minutes=5),
    )

    result = service.produce(command)

    assert result.execution_plan == plan
    assert result.ready_request.status is ProjectRequestStatus.READY_FOR_DELIVERY
    assert result.ready_request_revision.revision == 3
    assert result.ready_request_revision.supersedes_sha256 == current.request_revision_sha256
    assert request_store.get_request_revision(current.request.id, 2) == current
    assert (
        request_store.get_request_revision(current.request.id, 3) == result.ready_request_revision
    )
    assert request_store.current_request_revision(current.request.id).revision == 3


def test_exact_retry_recovers_crash_between_plan_and_request_revision(tmp_path: Path) -> None:
    current, spec, approved, design, plan = _inputs(tmp_path)
    request_store = FileProductRecordStore(tmp_path / "product-records")
    request_store.put_request_revision(designing_request_revision(current.request))
    request_store.put_request_revision(current)
    design_store, checkpoint = committed_design_handoff(tmp_path, current, spec, approved, design)
    design_run = design_store.get_run(checkpoint.run_id)
    assert design_run.planning_authorization is not None
    plan_store = InMemoryExecutionPlanStore(fail_once_after_write=True)
    service = PlannerStageService(
        context_builder=PlannerContextBuilder(),
        adapter=FakePlannerAgentAdapter(
            default=FakePlannerScenario(
                behavior=FakePlannerBehavior.READY,
                execution_plan=plan,
            )
        ),
        execution_plans=plan_store,
        request_revisions=request_store,
        design_records=design_store,
    )
    command = ProduceExecutionPlanCommand(
        run_id="run_planner_recovery_001",
        current_request_revision=current,
        product_spec=spec,
        product_approval=approved,
        technical_design=design,
        design_checkpoint=checkpoint,
        planning_authorization=design_run.planning_authorization,
        expected_execution_plan_version=1,
        transitioned_at=NOW + timedelta(minutes=5),
    )

    with pytest.raises(RuntimeError, match="simulated crash"):
        service.produce(command)
    assert plan_store.records[plan.id] == plan
    assert request_store.get_request_revision(current.request.id, 3).request.status is (
        ProjectRequestStatus.READY_FOR_DELIVERY
    )
    assert plan_store.find_checkpoint(command.run_id) is None

    fresh_service = PlannerStageService(
        context_builder=PlannerContextBuilder(),
        adapter=FakePlannerAgentAdapter(
            default=FakePlannerScenario(behavior=FakePlannerBehavior.TIMEOUT)
        ),
        execution_plans=plan_store,
        request_revisions=request_store,
        design_records=design_store,
    )
    recovered = fresh_service.produce(command)
    replayed = fresh_service.produce(command)
    assert recovered == replayed
    assert request_store.get_request_revision(current.request.id, 2) == current
    assert (
        request_store.get_request_revision(current.request.id, 3)
        == recovered.ready_request_revision
    )


def test_agent_failure_never_publishes_plan_or_ready_revision(tmp_path: Path) -> None:
    current, spec, approved, design, _ = _inputs(tmp_path)
    request_store = FileProductRecordStore(tmp_path / "product-records")
    request_store.put_request_revision(designing_request_revision(current.request))
    request_store.put_request_revision(current)
    design_store, checkpoint = committed_design_handoff(tmp_path, current, spec, approved, design)
    design_run = design_store.get_run(checkpoint.run_id)
    assert design_run.planning_authorization is not None
    plan_store = InMemoryExecutionPlanStore()
    service = PlannerStageService(
        context_builder=PlannerContextBuilder(),
        adapter=FakePlannerAgentAdapter(
            default=FakePlannerScenario(behavior=FakePlannerBehavior.TIMEOUT)
        ),
        execution_plans=plan_store,
        request_revisions=request_store,
        design_records=design_store,
    )

    with pytest.raises(RuntimeError, match="did not produce"):
        service.produce(
            ProduceExecutionPlanCommand(
                run_id="run_planner_failure_001",
                current_request_revision=current,
                product_spec=spec,
                product_approval=approved,
                technical_design=design,
                design_checkpoint=checkpoint,
                planning_authorization=design_run.planning_authorization,
                expected_execution_plan_version=1,
                transitioned_at=NOW + timedelta(minutes=5),
            )
        )
    assert plan_store.records == {}
    assert request_store.current_request_revision(current.request.id) == current


def test_concurrent_revision_advance_during_planner_call_writes_no_receipt_or_plan(
    tmp_path: Path,
) -> None:
    current, spec, approved, design, plan = _inputs(tmp_path)
    request_store = FileProductRecordStore(tmp_path / "product-records")
    request_store.put_request_revision(designing_request_revision(current.request))
    request_store.put_request_revision(current)
    design_store, checkpoint = committed_design_handoff(tmp_path, current, spec, approved, design)
    design_run = design_store.get_run(checkpoint.run_id)
    assert design_run.planning_authorization is not None
    plan_store = InMemoryExecutionPlanStore()
    service = PlannerStageService(
        context_builder=PlannerContextBuilder(),
        adapter=AdvanceRevisionDuringPlannerRun(
            FakePlannerScenario(
                behavior=FakePlannerBehavior.READY,
                execution_plan=plan,
            ),
            request_store,
            current,
        ),
        execution_plans=plan_store,
        request_revisions=request_store,
        design_records=design_store,
    )

    with pytest.raises(PlanningStageStaleRequest):
        service.produce(
            ProduceExecutionPlanCommand(
                run_id="run_planner_concurrent_001",
                current_request_revision=current,
                product_spec=spec,
                product_approval=approved,
                technical_design=design,
                design_checkpoint=checkpoint,
                planning_authorization=design_run.planning_authorization,
                expected_execution_plan_version=1,
                transitioned_at=NOW + timedelta(minutes=5),
            )
        )

    assert plan_store.runs == {}
    assert plan_store.records == {}
    assert plan_store.checkpoints == {}


def test_stale_request_revision_is_rejected_before_agent_or_plan_write(tmp_path: Path) -> None:
    current, spec, approved, design, plan = _inputs(tmp_path)
    request_store = FileProductRecordStore(tmp_path / "product-records")
    request_store.put_request_revision(designing_request_revision(current.request))
    request_store.put_request_revision(current)
    design_store, checkpoint = committed_design_handoff(tmp_path, current, spec, approved, design)
    design_run = design_store.get_run(checkpoint.run_id)
    assert design_run.planning_authorization is not None
    newer_request = current.request.model_copy(
        update={"updated_at": current.request.updated_at + timedelta(seconds=1)}
    )
    # Rebuild the digest rather than relying on an unchecked model copy.
    newer_request = type(current.request).create(
        request_id=newer_request.id,
        project_id=newer_request.project_id,
        preparation_sha256=newer_request.preparation_sha256,
        title=newer_request.title,
        original_request=newer_request.original_request,
        status=newer_request.status,
        created_at=newer_request.created_at,
        updated_at=newer_request.updated_at,
    )
    newer_revision = ProjectRequestRevision.create(
        newer_request,
        revision=3,
        supersedes_sha256=current.request_revision_sha256,
        recorded_at=newer_request.updated_at,
    )
    request_store.put_request_revision(newer_revision)
    plan_store = InMemoryExecutionPlanStore()
    service = PlannerStageService(
        context_builder=PlannerContextBuilder(),
        adapter=FakePlannerAgentAdapter(
            default=FakePlannerScenario(
                behavior=FakePlannerBehavior.READY,
                execution_plan=plan,
            )
        ),
        execution_plans=plan_store,
        request_revisions=request_store,
        design_records=design_store,
    )

    with pytest.raises(PlanningStageStaleRequest):
        service.produce(
            ProduceExecutionPlanCommand(
                run_id="run_planner_stale_001",
                current_request_revision=current,
                product_spec=spec,
                product_approval=approved,
                technical_design=design,
                design_checkpoint=checkpoint,
                planning_authorization=design_run.planning_authorization,
                expected_execution_plan_version=1,
                transitioned_at=NOW + timedelta(minutes=5),
            )
        )
    assert plan_store.records == {}
