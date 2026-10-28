"""The separate start-only source survives published Schema regeneration."""

import json
from copy import deepcopy
from pathlib import Path
from runpy import run_path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from ai_software_engineer.recovery.models import RecoveryPlan
from tests.recovery.test_authorization import make_plan

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("generated", (False, True))
def test_contained_unknown_schema_requires_unique_real_run_and_reapply(
    tmp_path: Path, generated: bool
) -> None:
    schema = (
        RecoveryPlan.model_json_schema()
        if generated
        else json.loads((ROOT / "schemas/delivery-recovery.schema.json").read_text())
    )
    validator = Draft202012Validator(schema)
    ordinary = make_plan(tmp_path / "ordinary")
    plan = RecoveryPlan.create(
        **{
            **ordinary.to_wire(),
            "input_mode": "coder_reapply",
            "source": {
                **ordinary.source.to_wire(),
                "contained_unknown_settlement_sha256": "d" * 64,
            },
        }
    )
    validator.validate(ordinary.to_wire())
    validator.validate(plan.to_wire())
    for fault in ("run", "stopped", "capacity", "mode", "snapshot"):
        wire: dict[str, Any] = deepcopy(plan.to_wire())
        if fault == "run":
            wire["source"]["failed_run_id"] = None
        elif fault == "stopped":
            wire["source"]["stopped_unknown_settlement_sha256"] = "e" * 64
        elif fault == "capacity":
            wire["source"]["context_capacity_receipt_sha256"] = "e" * 64
        elif fault == "mode":
            wire["input_mode"] = None
        else:
            wire["workspace_snapshot"] = {}
        assert not validator.is_valid(wire), (generated, fault)
    assert "contained_unknown_settlement_sha256" not in ordinary.source.to_wire()


def test_contained_unknown_schema_sync_is_additive_and_idempotent() -> None:
    synchronize = run_path(str(ROOT / "scripts/sync-stopped-unknown-recovery-schema.py"))[
        "synchronize"
    ]
    old = json.loads((ROOT / "schemas/delivery-recovery.schema.json").read_text())
    sentinel = {"properties": {"kind": {"enum": ["recovery_plan", "recovery_authorization"]}}}
    old.setdefault("allOf", []).append(sentinel)
    before = deepcopy(old)
    updated = synchronize(old)
    assert old == before
    assert sentinel in updated["allOf"]
    assert synchronize(updated) == updated
