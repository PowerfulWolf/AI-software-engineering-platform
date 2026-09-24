"""T047 fast path, durable routing, work-package and immutable revision contracts."""

from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.design.store import FileDesignRecordStore
from ai_software_engineer.domain.enums import ProjectRequestStatus, RiskTier
from ai_software_engineer.domain.project_delivery import (
    DesignComplexityFacts,
    ExecutionPlan,
    PlanRevisionFeedback,
    PlanTestItem,
    PlanTestMatrixError,
    PlanWorkGraph,
    PlanWorkPackage,
    TechnicalDesign,
    validate_plan_test_matrix,
)
from ai_software_engineer.planning import (
    FakePlannerAgentAdapter,
    FakePlannerBehavior,
    FakePlannerScenario,
    FileExecutionPlanStore,
    PlannerContextBuilder,
    PlannerRunOutcome,
    PlannerStageService,
    PlanningStageError,
    ProduceExecutionPlanCommand,
)
from ai_software_engineer.planning.gate import PlanningMode
from ai_software_engineer.planning.store import ExecutionPlanConflict
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


def _package(
    *, identity: str = "package_main", component: str = "component_planning_preview"
) -> PlanWorkPackage:
    return PlanWorkPackage(
        id=identity,
        component_ids=(component,),
        step_ids=("design_step_planner_01",),
        acceptance_criterion_ids=("ac_planner_01",),
        risk=RiskTier.LOW,
        checkpoints=("Native QA and Review verify exact criteria",),
        tests=(
            PlanTestItem(
                id="test_unit",
                acceptance_criterion_ids=("ac_planner_01",),
                level="unit",
                verification="Run isolated Planner unit tests",
            ),
            PlanTestItem(
                id="test_main",
                acceptance_criterion_ids=("ac_planner_01",),
                level="contract",
                verification="Run tests/planning",
            ),
        ),
    )


def _stage(
    tmp_path: Path, *, complex_change: bool = False
) -> tuple[
    ProduceExecutionPlanCommand,
    FileDesignRecordStore,
    FileProductRecordStore,
    FileExecutionPlanStore,
]:
    request = planning_request(preparation(tmp_path))
    current = request_revision(request)
    product = product_spec(request)
    approved = approval(product)
    design = technical_design(product, approved)
    if complex_change:
        design = TechnicalDesign.create(
            product,
            approved,
            design_id=design.id,
            version=design.version,
            summary=design.summary,
            components=design.components,
            requirement_mappings=design.requirement_mappings,
            acceptance_mappings=design.acceptance_mappings,
            implementation_steps=design.implementation_steps,
            created_at=design.created_at,
            complexity_facts=DesignComplexityFacts(database_migration=True),
        )
    design_store, checkpoint = committed_design_handoff(
        tmp_path, current, product, approved, design
    )
    authorization = design_store.get_run(checkpoint.run_id).planning_authorization
    assert authorization is not None
    request_store = FileProductRecordStore(tmp_path / "product-records")
    request_store.put_request_revision(designing_request_revision(request))
    request_store.put_request_revision(current)
    plan_store = FileExecutionPlanStore(tmp_path / "planning")
    command = ProduceExecutionPlanCommand(
        run_id="run_complex_planning_001",
        current_request_revision=current,
        product_spec=product,
        product_approval=approved,
        technical_design=design,
        design_checkpoint=checkpoint,
        planning_authorization=authorization,
        expected_execution_plan_version=1,
        transitioned_at=NOW + timedelta(minutes=5),
    )
    return command, design_store, request_store, plan_store


def test_native_simple_route_never_calls_adapter_and_recovers_from_durable_receipt(
    tmp_path: Path,
) -> None:
    command, design_store, request_store, plans = _stage(tmp_path)

    # Unconfigured adapter raises on any invocation, proving the zero-model boundary.
    def service() -> PlannerStageService:
        return PlannerStageService(
            context_builder=PlannerContextBuilder(),
            adapter=FakePlannerAgentAdapter(),
            execution_plans=plans,
            request_revisions=request_store,
            design_records=design_store,
            planning_decisions=plans,
        )

    result = service().produce(command)
    decision = FileExecutionPlanStore(tmp_path / "planning").get_planning_decision(command.run_id)
    assert decision.mode is PlanningMode.SIMPLE
    assert result.run_record.planning_decision == decision
    assert tuple(phase.role.value for phase in result.execution_plan.phases) == (
        "coder",
        "qa",
        "reviewer",
    )
    assert service().produce(command).replayed
    assert plans.get_run(command.run_id) == result.run_record
    changed = decision.model_copy(update={"mode": PlanningMode.COMPLEX})
    with pytest.raises(ValueError, match="deterministic"):
        plans.put_planning_decision(command.run_id, changed)


def test_complex_route_calls_planner_and_retains_exact_gate(tmp_path: Path) -> None:
    command, designs, requests, plans = _stage(tmp_path, complex_change=True)
    base = execution_plan(command.product_spec, command.technical_design)
    plan = ExecutionPlan.create(
        command.product_spec,
        command.technical_design,
        plan_id=base.id,
        version=1,
        phases=base.phases,
        created_at=base.created_at,
        work_graph=PlanWorkGraph(packages=(_package(),)),
    )
    adapter = FakePlannerAgentAdapter(
        default=FakePlannerScenario(
            behavior=FakePlannerBehavior.READY,
            execution_plan=plan,
        )
    )
    result = PlannerStageService(
        context_builder=PlannerContextBuilder(),
        adapter=adapter,
        execution_plans=plans,
        request_revisions=requests,
        design_records=designs,
        planning_decisions=plans,
    ).produce(command)
    assert result.execution_plan == plan
    decision = plans.get_planning_decision(command.run_id)
    assert decision.mode is PlanningMode.COMPLEX
    assert decision.reason_codes == ("DATABASE_MIGRATION",)
    assert result.run_record.planning_decision == decision


def test_graph_rejects_cycles_uncovered_tests_and_concrete_allocations() -> None:
    package = _package()
    with pytest.raises(ValidationError, match="dependency"):
        PlanWorkGraph(packages=(package.model_copy(update={"depends_on": (package.id,)}),))
    with pytest.raises(ValidationError, match="exact package acceptance"):
        PlanWorkPackage.model_validate(
            {**package.to_wire(), "acceptance_criterion_ids": ["ac_missing"]}
        )
    for field in ("agent_id", "model", "provider", "assignment", "lease"):
        with pytest.raises(ValidationError):
            PlanWorkPackage.model_validate({**package.to_wire(), field: "forbidden"})
    with pytest.raises(ValidationError, match="disjoint"):
        PlanWorkGraph(packages=(package, _package(identity="second")), max_parallelism=2)
    assert (
        PlanWorkGraph(
            packages=(package, _package(identity="second", component="component_other")),
            max_parallelism=2,
        ).max_parallelism
        == 2
    )


def test_plan_revisions_bind_exact_prior_and_never_overwrite(tmp_path: Path) -> None:
    command, _, _, plans = _stage(tmp_path)
    first = execution_plan(command.product_spec, command.technical_design)
    plans.put_execution_plan(first)
    feedback = PlanRevisionFeedback(
        previous_plan_id=first.id,
        previous_plan_sha256=first.execution_plan_sha256,
        reason_codes=("TEST_MATRIX",),
        required_changes=("Expand tests",),
    )
    second = ExecutionPlan.create(
        command.product_spec,
        command.technical_design,
        plan_id="execution_plan_revised_002",
        version=2,
        phases=first.phases,
        created_at=NOW,
        revision_feedback=feedback,
    )
    plans.put_execution_plan(second)
    reopened = FileExecutionPlanStore(tmp_path / "planning")
    assert reopened.get_execution_plan(first.id) == first
    assert reopened.find_for_request(first.request_id) == second
    bad = ExecutionPlan.create(
        command.product_spec,
        command.technical_design,
        plan_id="execution_plan_revised_bad",
        version=2,
        phases=first.phases,
        created_at=NOW,
        revision_feedback=feedback.model_copy(update={"previous_plan_sha256": "f" * 64}),
    )
    with pytest.raises(ExecutionPlanConflict, match="predecessor"):
        plans.put_execution_plan(bad)


@pytest.mark.parametrize(
    "invalid",
    (
        "initial_feedback",
        "missing_predecessor",
        "missing_feedback",
        "wrong_predecessor",
        "stale_predecessor",
        "version_gap",
    ),
)
def test_invalid_revision_is_failed_before_success_receipt_or_ready(
    tmp_path: Path, invalid: str
) -> None:
    command, designs, requests, plans = _stage(tmp_path)
    first = execution_plan(command.product_spec, command.technical_design)
    feedback = PlanRevisionFeedback(
        previous_plan_id=first.id,
        previous_plan_sha256=first.execution_plan_sha256,
        reason_codes=("TEST_MATRIX",),
        required_changes=("Preserve all design tests",),
    )
    latest: ExecutionPlan | None = None
    if invalid not in {"initial_feedback", "missing_predecessor"}:
        latest = plans.put_execution_plan(first)
    if invalid == "stale_predecessor":
        latest = plans.put_execution_plan(
            ExecutionPlan.create(
                command.product_spec,
                command.technical_design,
                plan_id="execution_plan_existing_002",
                version=2,
                phases=first.phases,
                created_at=NOW,
                revision_feedback=feedback,
            )
        )
    version = 1 if invalid == "initial_feedback" else 2
    if invalid == "version_gap":
        version = 3
    if invalid == "wrong_predecessor":
        feedback = feedback.model_copy(update={"previous_plan_sha256": "f" * 64})
    plan = ExecutionPlan.create(
        command.product_spec,
        command.technical_design,
        plan_id="execution_plan_invalid_001",
        version=version,
        phases=first.phases,
        created_at=NOW,
        revision_feedback=None if invalid == "missing_feedback" else feedback,
    )
    command = command.model_copy(update={"expected_execution_plan_version": version})
    service = PlannerStageService(
        context_builder=PlannerContextBuilder(),
        adapter=FakePlannerAgentAdapter(
            default=FakePlannerScenario(
                behavior=FakePlannerBehavior.READY,
                execution_plan=plan,
            )
        ),
        execution_plans=plans,
        request_revisions=requests,
        design_records=designs,
    )
    with pytest.raises(PlanningStageError, match="output is invalid"):
        service.produce(command)
    failed = plans.get_run(command.run_id)
    assert failed.outcome is PlannerRunOutcome.FAILED
    assert failed.execution_plan is None and failed.ready_request_revision is None
    if invalid == "initial_feedback":
        assert failed.error_message is not None
        assert "initial plan requires version 1" in failed.error_message
    assert (
        requests.current_request_revision(first.request_id).request.status
        is ProjectRequestStatus.PLANNING
    )
    assert plans.find_for_request(first.request_id) == latest
    assert plans.find_checkpoint(command.run_id) is None
    with pytest.raises(ExecutionPlanConflict):
        plans.put_execution_plan(plan)


def test_native_plan_test_matrix_cannot_weaken_design_levels(tmp_path: Path) -> None:
    command, _, _, _ = _stage(tmp_path)
    first = execution_plan(command.product_spec, command.technical_design)
    package = _package()
    graph = PlanWorkGraph(packages=(package.model_copy(update={"tests": package.tests[:1]}),))
    with pytest.raises(ValueError, match="missing test levels contract"):
        ExecutionPlan.create(
            command.product_spec,
            command.technical_design,
            plan_id=first.id,
            version=1,
            phases=first.phases,
            created_at=NOW,
            work_graph=graph,
        )


def test_test_matrix_reports_all_missing_criteria_without_aliasing() -> None:
    graph = PlanWorkGraph(packages=(_package(),))
    with pytest.raises(PlanTestMatrixError) as raised:
        validate_plan_test_matrix(
            graph,
            {
                "ac_planner_02": ("manual_ui",),
                "ac_planner_01": ("contract", "accessibility"),
            },
        )
    first, second = raised.value.issues
    assert first.acceptance_criterion_id == "ac_planner_01"
    assert first.observed_levels == ("contract", "unit")
    assert first.missing_levels == ("accessibility",)
    assert second.acceptance_criterion_id == "ac_planner_02"
    assert second.observed_levels == () and second.missing_levels == ("manual_ui",)
    assert "unit_id" not in first.to_wire()
    validate_plan_test_matrix(graph, {"ac_planner_01": ("unit", "contract")})
