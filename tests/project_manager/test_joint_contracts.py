"""Joint artifact coverage, authorization, and exported Schema regression tests."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.execution import CommandResult
from ai_software_engineer.multi_directory.integration_commands import is_test_command
from ai_software_engineer.multi_directory.models import (
    JointApproval,
    JointCheckpoint,
    JointExecutionPlan,
    JointProductSpec,
    JointStage,
    JointTechnicalDesign,
    digest,
)
from ai_software_engineer.multi_directory.production import (
    DerivedStageInputs,
    _require_nonempty_test_run,
)
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit
from ai_software_engineer.multi_directory.service import CreateRequirementProject
from ai_software_engineer.project_manager.production_agents import ProductDraft
from tests.e2e.test_joint_delivery import JointModels


def checkpoint(tmp_path: Path) -> JointCheckpoint:
    scope = DirectoryScope(
        units=tuple(
            DirectoryUnit(
                id="unit_" + c * 16,
                root=str(tmp_path / c),
                selected_paths=(".",),
                base_revision=c * 40,
            )
            for c in ("a", "b")
        )
    )
    models = JointModels()
    draft = ProductDraft.model_validate(
        models.complete(
            instructions="",
            input_payload={},
            output_schema=ProductDraft.model_json_schema(),
            timeout_seconds=1,
        ).payload
    )
    product = JointProductSpec(scope_sha256=digest(scope), version=1, product=draft)
    design = JointTechnicalDesign.model_validate(
        models.complete(
            instructions="",
            input_payload={"scope": scope.to_wire(), "product_spec_sha256": digest(product)},
            output_schema=JointTechnicalDesign.model_json_schema(),
            timeout_seconds=1,
        ).payload
    )
    plan = JointExecutionPlan.model_validate(
        models.complete(
            instructions="",
            input_payload={"scope": scope.to_wire(), "design_sha256": digest(design)},
            output_schema=JointExecutionPlan.model_json_schema(),
            timeout_seconds=1,
        ).payload
    )
    return JointCheckpoint.seal(
        {
            "delivery_id": "delivery_multi_contract",
            "company_id": "company_test",
            "company_manifest_sha256": "0" * 64,
            "sequence": 1,
            "scope": scope,
            "title": "Test",
            "submitted_at": datetime.now(UTC),
            "stage": JointStage.DELIVERING,
            "product_spec": product,
            "approval": JointApproval(
                product_spec_sha256=digest(product),
                checkpoint_sha256="0" * 64,
                reference="approved",
                approved_at=datetime.now(UTC),
            ),
            "design": design,
            "plan": plan,
            "next_action": "Deliver exact projected units",
        }
    )


def test_joint_design_rejects_write_escape_and_duplicate_mapping(tmp_path: Path) -> None:
    cp = checkpoint(tmp_path)
    assert cp.design and cp.product_spec
    unit = cp.design.units[0]
    component = unit.design.components[0].model_copy(update={"affected_paths": ("../escape",)})
    changed = unit.model_copy(
        update={"design": unit.design.model_copy(update={"components": (component,)})}
    )
    with pytest.raises(ValueError, match="selected directories"):
        cp.design.model_copy(update={"units": (changed, cp.design.units[1])}).validate_for(
            cp.scope, cp.product_spec
        )
    duplicate = unit.design.model_copy(
        update={"requirement_mappings": unit.design.requirement_mappings * 2}
    )
    with pytest.raises(ValueError, match="unique"):
        cp.design.model_copy(
            update={"units": (unit.model_copy(update={"design": duplicate}), cp.design.units[1])}
        ).validate_for(cp.scope, cp.product_spec)


def test_dependency_order_and_done_require_joint_evidence(tmp_path: Path) -> None:
    cp = checkpoint(tmp_path)
    assert cp.plan and cp.product_spec and cp.design
    with pytest.raises(ValueError, match="dependency"):
        cp.plan.model_copy(update={"units": tuple(reversed(cp.plan.units))}).validate_for(
            cp.scope, cp.product_spec, cp.design
        )
    with pytest.raises(ValueError, match="integration evidence"):
        JointCheckpoint.seal({**cp.to_wire(), "stage": JointStage.DONE})
    with pytest.raises(ValueError, match="approved joint"):
        DerivedStageInputs(
            JointCheckpoint.seal({**cp.to_wire(), "plan": None}), cp.scope.units[0].id
        )


def test_projection_is_deterministic_and_requires_exact_root(tmp_path: Path) -> None:
    cp = checkpoint(tmp_path)
    unit = cp.scope.units[0]
    first = DerivedStageInputs(cp, unit.id)
    second = DerivedStageInputs(cp, unit.id)
    assert first.product == second.product
    assert first.requirement == second.requirement
    assert first.design.requirement_mappings[0].requirement_id == "req_001"
    with pytest.raises(ValueError, match="another repository"):
        first.for_project(tmp_path / "foreign")


@pytest.mark.parametrize(
    "argv",
    [
        ("git", "status"),
        ("python", "-c", "print(1)"),
        ("npm", "install"),
        ("sh", "test.sh"),
        ("echo", "PASS"),
        ("pytest", "--collect-only"),
        ("python3", "-m", "unittest", "--help"),
        ("mvn", "test", "-DskipTests=true"),
        ("npm", "test", "--", "--passWithNoTests"),
    ],
)
def test_integration_rejects_non_test_commands(argv: tuple[str, ...]) -> None:
    assert not is_test_command(argv)


def test_integration_zero_test_success_is_not_a_pass(tmp_path: Path) -> None:
    result = CommandResult(
        argv=("python3", "-m", "unittest"),
        cwd=str(tmp_path),
        returncode=0,
        stdout="",
        stderr="Ran 0 tests in 0.001s\nOK",
        duration_ms=1,
    )
    with pytest.raises(ValueError, match="no executed tests"):
        _require_nonempty_test_run(result)
    _require_nonempty_test_run(result.model_copy(update={"stderr": "Ran 1 test in 0.1s\nOK"}))


def test_reference_only_unit_needs_no_native_delivery(tmp_path: Path) -> None:
    cp = checkpoint(tmp_path)
    assert cp.design and cp.product_spec and cp.plan
    first, second = cp.scope.units
    design = cp.design.model_copy(
        update={"units": cp.design.units[:1], "reference_only": (second.id,)}
    )
    design.validate_for(cp.scope, cp.product_spec)
    check = cp.plan.integration_checks[0].model_copy(update={"unit_id": first.id})
    plan = cp.plan.model_copy(
        update={
            "design_sha256": digest(design),
            "units": cp.plan.units[:1],
            "integration_checks": (check,),
        }
    )
    plan.validate_for(cp.scope, cp.product_spec, design)


def test_joint_schemas_are_in_sync_with_models() -> None:
    models: dict[str, type[DomainModel]] = {
        "requirement-project-create": CreateRequirementProject,
        "requirement-project-checkpoint": JointCheckpoint,
        "joint-product-spec": JointProductSpec,
        "joint-technical-design": JointTechnicalDesign,
        "joint-execution-plan": JointExecutionPlan,
    }
    for name, model in models.items():
        schema = json.loads(
            (Path(__file__).parents[2] / "schemas" / f"{name}.schema.json").read_text()
        )
        schema.pop("$id")
        schema.pop("$schema")
        assert schema == model.model_json_schema()
