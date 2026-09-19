"""Manager complexity routing is deterministic and cannot be model-controlled."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.domain.project_delivery import DesignComplexityFacts
from ai_software_engineer.planning.gate import (
    HumanPlanningUpgrade,
    PlanningFacts,
    PlanningGate,
    PlanningMode,
)
from tests.planning.conftest import (
    NOW,
    approval,
    planning_request,
    preparation,
    product_spec,
    technical_design,
)


def test_simple_gate_replays_and_exact_upgrade_only(tmp_path: Path) -> None:
    spec = product_spec(planning_request(preparation(tmp_path)))
    design = technical_design(spec, approval(spec))
    facts = PlanningFacts.from_design(spec, design)
    decision = PlanningGate().classify(facts)
    assert decision.mode is PlanningMode.SIMPLE
    assert decision == PlanningGate().classify(facts)
    decision.validate_integrity()
    upgrade = HumanPlanningUpgrade(
        input_sha256=facts.digest(),
        operator_id="user_owner",
        rationale="Review dependencies",
        decided_at=NOW,
    )
    upgraded = PlanningGate().classify(facts, upgrade=upgrade)
    assert upgraded.mode is PlanningMode.COMPLEX
    assert "HUMAN_UPGRADE" in upgraded.reason_codes
    with pytest.raises(ValueError, match="exact input"):
        PlanningGate().classify(
            facts, upgrade=upgrade.model_copy(update={"input_sha256": "f" * 64})
        )
    with pytest.raises(ValidationError):
        HumanPlanningUpgrade.model_validate({**upgrade.to_wire(), "mode": "SIMPLE"})


@pytest.mark.parametrize(
    "field",
    [
        "database_migration",
        "interface_compatibility",
        "data_backfill",
        "security",
        "performance",
        "concurrency",
        "work_package_dependencies",
    ],
)
def test_each_structured_complexity_trigger(field: str, tmp_path: Path) -> None:
    spec = product_spec(planning_request(preparation(tmp_path)))
    design = technical_design(spec, approval(spec))
    facts = PlanningFacts.from_design(spec, design).model_copy(
        update={
            "design_facts": DesignComplexityFacts.model_validate({field: True}),
        }
    )
    result = PlanningGate().classify(facts)
    assert result.mode is PlanningMode.COMPLEX
    assert field.upper() in result.reason_codes


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("repository_count", 2, "MULTIPLE_REPOSITORIES"),
        ("component_count", 2, "MULTIPLE_MODULES"),
        ("integration_group_count", 2, "MULTIPLE_INTEGRATION_GROUPS"),
        ("technical_risk", "normal", "TECHNICAL_RISK"),
    ],
)
def test_count_and_risk_thresholds(field: str, value: object, reason: str, tmp_path: Path) -> None:
    spec = product_spec(planning_request(preparation(tmp_path)))
    design = technical_design(spec, approval(spec))
    wire = PlanningFacts.from_design(spec, design).to_wire()
    wire[field] = value  # type: ignore[assignment]
    result = PlanningGate().classify(PlanningFacts.model_validate(wire))
    assert result.mode is PlanningMode.COMPLEX
    assert reason in result.reason_codes
