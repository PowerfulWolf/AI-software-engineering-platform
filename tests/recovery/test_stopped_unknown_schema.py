"""Additive unknown-source schema guards survive regeneration and keep old wires."""

import json
from copy import deepcopy
from pathlib import Path
from runpy import run_path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from ai_software_engineer.recovery.models import RecoveryPlan, RecoverySource
from tests.recovery.test_authorization import make_plan
from tests.recovery.test_stopped_unknown_source import stopped_plan

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize("generated", (False, True))
def test_stopped_unknown_schema_requires_real_run_exclusive_source_and_reapply(
    tmp_path: Path, generated: bool
) -> None:
    document = (
        RecoveryPlan.model_json_schema()
        if generated
        else json.loads((ROOT / "schemas/delivery-recovery.schema.json").read_text())
    )
    validator = Draft202012Validator(document)
    ordinary = make_plan(tmp_path / "old")
    plan = stopped_plan(tmp_path)
    validator.validate(ordinary.to_wire())
    validator.validate(plan.to_wire())
    for fault in ("run", "capacity", "mode"):
        wire: dict[str, Any] = deepcopy(plan.to_wire())
        if fault == "run":
            wire["source"]["failed_run_id"] = None
        elif fault == "capacity":
            wire["source"]["context_capacity_receipt_sha256"] = "e" * 64
        else:
            wire["input_mode"] = None
        assert not validator.is_valid(wire), (generated, fault)
    assert "stopped_unknown_settlement_sha256" not in ordinary.source.to_wire()
    assert RecoverySource.model_validate(ordinary.source.to_wire()) == ordinary.source


def test_unknown_schema_sync_is_additive_and_idempotent() -> None:
    synchronize = run_path(str(ROOT / "scripts/sync-stopped-unknown-recovery-schema.py"))[
        "synchronize"
    ]
    old = json.loads((ROOT / "schemas/delivery-recovery.schema.json").read_text())
    # A future unrelated historical guard must survive this narrow synchronizer.
    sentinel = {"properties": {"kind": {"enum": ["recovery_plan", "recovery_authorization"]}}}
    old.setdefault("allOf", []).append(sentinel)
    before = deepcopy(old)
    updated = synchronize(old)
    assert old == before
    assert sentinel in updated["allOf"]
    assert synchronize(updated) == updated
