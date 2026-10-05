"""Published nested plan contracts accept real verification inputs and reject extras."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from ai_software_engineer.domain.project_delivery import PlanTestItem


@pytest.mark.parametrize(
    "name",
    [
        "joint-execution-plan",
        "requirement-checkpoint",
        "knowledge-stage-workflow",
        "plan-work-graph",
        "project-stage-defs",
    ],
)
@pytest.mark.parametrize("inspection", [False, True])
def test_embedded_plan_accepts_native_verification(name: str, inspection: bool) -> None:
    value = {
        "id": "test_verification",
        "acceptance_criterion_ids": ["ac_001_001"],
        "level": "ui" if inspection else "unit",
        "verification": "Verify the exact candidate acceptance criterion.",
        "verification_argv": None if inspection else ["pytest", "tests/test_focused.py"],
        "planned_test_files": ["tests/test_focused.py"],
        "verification_inspection": (
            {
                "kind": "native_ui",
                "checklist": ["Inspect the candidate accessibility tree."],
                "scenario_sha256": "a" * 64,
            }
            if inspection
            else None
        ),
        "controlled_capability_kind": "macos_mock_ax_v1" if inspection else None,
    }
    PlanTestItem.model_validate(value)
    path = Path(__file__).parents[2] / "schemas" / f"{name}.schema.json"
    root = json.loads(path.read_text())
    validator = Draft202012Validator(
        {"$schema": root["$schema"], "$defs": root["$defs"], "$ref": "#/$defs/PlanTestItem"}
    )
    validator.validate(value)
    with pytest.raises(ValidationError, match="Additional properties"):
        validator.validate({**value, "unapproved_execution": True})
