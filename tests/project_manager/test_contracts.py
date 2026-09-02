"""Product, design, planning, approval, and Delivery Task contract tests."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError
from referencing import Registry, Resource

from ai_software_engineer.domain import (
    AcceptanceCriterion,
    AcceptanceDesignMapping,
    AgentRole,
    BrainTier,
    DesignComponent,
    DesignRisk,
    DesignStep,
    ExecutionPlan,
    PlanPhaseDemand,
    ProductApprovalDecision,
    ProductApprovalRequired,
    ProductDecision,
    ProductRequirement,
    ProductSpec,
    ProductSpecApproval,
    ProductSpecStatus,
    ProjectPreparation,
    ProjectRequest,
    ProjectRequestStatus,
    RequirementDesignMapping,
    RequirementPriority,
    RiskTier,
    StageContractMismatch,
    StageIntegrityError,
    TechnicalDesign,
    derive_delivery_task,
    require_product_approval,
)
from ai_software_engineer.domain.model import WirePayload

NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
SCHEMA_DIR = Path(__file__).parents[2] / "schemas"


def preparation(tmp_path: Path) -> ProjectPreparation:
    project = tmp_path / "project"
    project.mkdir()
    return ProjectPreparation.create(
        organization_id="organization_team_001",
        project_id="project_delivery_001",
        project_root=str(project),
        project_workspace_root=str(tmp_path / "sidecars" / "project_delivery_001"),
        organization_root=str(tmp_path / "organization"),
        project_profile_sha256="a" * 64,
        runtime_binding_sha256="b" * 64,
        baseline_spec_sha256="c" * 64,
        baseline_source_uris=(
            "platform://hard-safety/v1",
            "project://project_delivery_001/AGENTS.md",
        ),
        prepared_at=NOW,
    )


def request(prepared: ProjectPreparation) -> ProjectRequest:
    return ProjectRequest.create(
        request_id="request_delivery_001",
        project_id=prepared.project_id,
        preparation_sha256=prepared.preparation_sha256,
        title="Add auditable delivery intake",
        original_request="Let the AI team accept and deliver one project requirement.",
        status=ProjectRequestStatus.READY_FOR_DELIVERY,
        created_at=NOW,
    )


def product_spec(project_request: ProjectRequest, *, version: int = 1) -> ProductSpec:
    criterion = AcceptanceCriterion(
        id="ac_intake_01",
        description="A prepared project can produce a reviewable intake.",
        required=True,
        verification="Run the Project Manager contract test.",
        test_ids=("test_project_manager_contract",),
    )
    return ProductSpec.create(
        spec_id=f"product_spec_delivery_00{version}",
        request_id=project_request.id,
        project_id=project_request.project_id,
        version=version,
        status=ProductSpecStatus.READY_FOR_REVIEW,
        summary="Create an explicit, auditable intake-to-delivery contract.",
        goals=("Turn approved product intent into a Delivery Task.",),
        non_goals=("Do not auto-merge the candidate.",),
        requirements=(
            ProductRequirement(
                id="req_intake_01",
                statement="The team must preserve approved acceptance criteria.",
                priority=RequirementPriority.MUST,
                rationale="Delivery must remain traceable to the user decision.",
                acceptance_criterion_ids=(criterion.id,),
            ),
        ),
        acceptance_criteria=(criterion,),
        decisions=(
            ProductDecision(
                id="decision_approval_01",
                question="Must Product Spec be confirmed?",
                decision="Yes, exactly once per immutable version.",
                rationale="The Product Agent cannot approve its own work.",
                decided_by="user_owner_001",
                decided_at=NOW,
            ),
        ),
        created_at=NOW + timedelta(minutes=1),
    )


def approval(spec: ProductSpec) -> ProductSpecApproval:
    return ProductSpecApproval.create(
        spec,
        decision=ProductApprovalDecision.APPROVED,
        operator_id="user_owner_001",
        rationale="The scope and acceptance criteria match the requested outcome.",
        decided_at=NOW + timedelta(minutes=2),
    )


def technical_design(spec: ProductSpec, approved: ProductSpecApproval) -> TechnicalDesign:
    return TechnicalDesign.create(
        spec,
        approved,
        design_id="technical_design_delivery_001",
        version=1,
        summary="Add frozen stage models and an exact Task projection guard.",
        components=(
            DesignComponent(
                id="component_stage_contracts",
                name="Stage contracts",
                responsibility="Validate immutable upstream artifacts.",
                affected_paths=("src/ai_software_engineer/domain/project_delivery.py",),
            ),
        ),
        requirement_mappings=(
            RequirementDesignMapping(
                requirement_id="req_intake_01",
                component_ids=("component_stage_contracts",),
                approach="Validate lineage before Task construction.",
            ),
        ),
        acceptance_mappings=(
            AcceptanceDesignMapping(
                acceptance_criterion_id="ac_intake_01",
                verification_strategy="Exercise the public derivation guard.",
                test_levels=("contract", "unit"),
            ),
        ),
        implementation_steps=(
            DesignStep(
                id="design_step_contracts_01",
                description="Implement and verify the immutable stage chain.",
                component_ids=("component_stage_contracts",),
                verification="Run project manager tests.",
            ),
        ),
        risks=(
            DesignRisk(
                id="design_risk_lineage_01",
                description="A stale approval could unlock the wrong design.",
                tier=RiskTier.HIGH,
                mitigation="Bind approval to the exact ProductSpec digest.",
            ),
        ),
        created_at=NOW + timedelta(minutes=3),
    )


def execution_plan(spec: ProductSpec, design: TechnicalDesign) -> ExecutionPlan:
    phases = tuple(
        PlanPhaseDemand(
            id=f"phase_{role.value}_01",
            role=role,
            objective=f"Complete the {role.value} delivery responsibility.",
            required_capabilities=("python", "contract-validation"),
            risk=RiskTier.HIGH if role is AgentRole.CODER else RiskTier.NORMAL,
            minimum_brain_tier=(
                BrainTier.REASONING if role is AgentRole.CODER else BrainTier.STANDARD
            ),
            checkpoints=(f"{role.value} artifact is schema-valid",),
        )
        for role in (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER)
    )
    return ExecutionPlan.create(
        spec,
        design,
        plan_id="execution_plan_delivery_001",
        version=1,
        phases=phases,
        feasibility_evidence_uris=("scheduler-preview://request_delivery_001/v1",),
        created_at=NOW + timedelta(minutes=4),
    )


def stage_chain(
    tmp_path: Path,
) -> tuple[
    ProjectPreparation,
    ProjectRequest,
    ProductSpec,
    ProductSpecApproval,
    TechnicalDesign,
    ExecutionPlan,
]:
    prepared = preparation(tmp_path)
    project_request = request(prepared)
    spec = product_spec(project_request)
    approved = approval(spec)
    design = technical_design(spec, approved)
    plan = execution_plan(spec, design)
    return prepared, project_request, spec, approved, design, plan


def schema_registry() -> tuple[dict[str, dict[str, object]], Registry]:
    schemas: dict[str, dict[str, object]] = {}
    resources: list[tuple[str, Resource[object]]] = []
    for path in SCHEMA_DIR.glob("*.schema.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        schema = cast(dict[str, object], payload)
        schemas[path.name] = schema
        resources.append((cast(str, schema["$id"]), Resource.from_contents(schema)))
    return schemas, Registry().with_resources(resources)


@pytest.mark.parametrize(
    ("index", "schema_name"),
    (
        (0, "project-preparation.schema.json"),
        (1, "project-request.schema.json"),
        (2, "product-spec.schema.json"),
        (3, "product-spec-approval.schema.json"),
        (4, "technical-design.schema.json"),
        (5, "execution-plan.schema.json"),
    ),
)
def test_stage_models_match_canonical_json_schemas(
    tmp_path: Path,
    index: int,
    schema_name: str,
) -> None:
    schemas, registry = schema_registry()
    stage = stage_chain(tmp_path)[index]
    errors = Draft202012Validator(
        schemas[schema_name], registry=registry, format_checker=FormatChecker()
    ).iter_errors(stage.to_wire())

    assert sorted(error.message for error in errors) == []


def test_approved_stage_chain_derives_new_task_with_exact_acceptance(tmp_path: Path) -> None:
    prepared, project_request, spec, approved, design, plan = stage_chain(tmp_path)

    task = derive_delivery_task(
        prepared,
        project_request,
        spec,
        approved,
        design,
        plan,
        task_id="task_delivery_001",
        repository=prepared.project_root,
        base_ref="a" * 40,
        max_attempts=3,
        created_at=NOW + timedelta(minutes=5),
    )

    assert task.status.value == "NEW"
    assert task.acceptance_criteria == spec.acceptance_criteria
    assert task.metadata["product_spec_sha256"] == spec.product_spec_sha256
    assert task.metadata["execution_plan_sha256"] == plan.execution_plan_sha256


def test_request_changes_cannot_unlock_technical_design(tmp_path: Path) -> None:
    prepared = preparation(tmp_path)
    spec = product_spec(request(prepared))
    rejected = ProductSpecApproval.create(
        spec,
        decision=ProductApprovalDecision.REQUEST_CHANGES,
        operator_id="user_owner_001",
        rationale="Clarify the non-goals before design.",
        decided_at=NOW + timedelta(minutes=2),
    )

    with pytest.raises(ProductApprovalRequired, match="requested changes"):
        technical_design(spec, rejected)


def test_approval_for_another_spec_version_is_rejected(tmp_path: Path) -> None:
    prepared = preparation(tmp_path)
    project_request = request(prepared)
    first = product_spec(project_request, version=1)
    second = product_spec(project_request, version=2)

    with pytest.raises(StageContractMismatch, match="exact ProductSpec"):
        require_product_approval(second, approval(first))


def test_tampered_stage_digest_fails_closed(tmp_path: Path) -> None:
    _prepared, _request, spec, _approved, _design, _plan = stage_chain(tmp_path)
    tampered = spec.model_copy(update={"summary": "Changed after approval."})

    with pytest.raises(StageIntegrityError, match="ProductSpec"):
        tampered.validate_integrity()


def test_design_must_cover_every_product_requirement(tmp_path: Path) -> None:
    prepared = preparation(tmp_path)
    spec = product_spec(request(prepared))
    approved = approval(spec)

    with pytest.raises(StageContractMismatch, match="exact ProductSpec requirements"):
        TechnicalDesign.create(
            spec,
            approved,
            design_id="technical_design_missing_coverage",
            version=1,
            summary="Intentionally incomplete design.",
            components=(
                DesignComponent(
                    id="component_incomplete",
                    name="Incomplete",
                    responsibility="Test the coverage guard.",
                ),
            ),
            requirement_mappings=(
                RequirementDesignMapping(
                    requirement_id="req_unknown_01",
                    component_ids=("component_incomplete",),
                    approach="This must be rejected.",
                ),
            ),
            acceptance_mappings=(
                AcceptanceDesignMapping(
                    acceptance_criterion_id="ac_intake_01",
                    verification_strategy="Contract test.",
                    test_levels=("contract",),
                ),
            ),
            implementation_steps=(
                DesignStep(
                    id="design_step_incomplete_01",
                    description="Incomplete step.",
                    component_ids=("component_incomplete",),
                    verification="Contract test.",
                ),
            ),
            created_at=NOW + timedelta(minutes=3),
        )


def test_execution_plan_rejects_non_serial_orchestrator_phase(tmp_path: Path) -> None:
    prepared = preparation(tmp_path)
    spec = product_spec(request(prepared))
    design = technical_design(spec, approval(spec))
    valid = execution_plan(spec, design)
    payload = valid.to_wire()
    phases = payload["phases"]
    assert isinstance(phases, list)
    first = phases[0]
    assert isinstance(first, dict)
    first["role"] = "orchestrator"

    with pytest.raises(ValidationError, match="coder, qa, reviewer"):
        ExecutionPlan.model_validate(payload)


def test_schema_rejects_concrete_model_or_agent_allocation(tmp_path: Path) -> None:
    schemas, registry = schema_registry()
    payload: WirePayload = stage_chain(tmp_path)[5].to_wire()
    payload["model"] = "largest-model"
    payload["agent_id"] = "agent_planner_selected_itself"
    errors = Draft202012Validator(
        schemas["execution-plan.schema.json"],
        registry=registry,
        format_checker=FormatChecker(),
    ).iter_errors(payload)

    assert sorted(error.message for error in errors)
