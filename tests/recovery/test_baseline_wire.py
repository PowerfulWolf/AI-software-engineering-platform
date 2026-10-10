"""Bound recovery keeps frozen approval and effective patch base separate."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.recovery.models import RecoveryPlan, RecoverySource
from tests.recovery.test_authorization import make_plan
from tests.recovery.test_models import VALIDATOR


def test_absent_baseline_fields_preserve_historical_wire_and_digest(tmp_path: Path) -> None:
    plan = make_plan(tmp_path / "repo")
    wire, sha = plan.to_wire(), plan.plan_sha256
    source = RecoverySource.model_validate(
        {
            **plan.source.to_wire(),
            "execution_baseline_sha256": None,
            "execution_base_revision": None,
        }
    )
    assert source.to_wire() == plan.source.to_wire()
    restored = RecoveryPlan.model_validate({**wire, "source": source})
    assert restored.to_wire() == wire and restored.plan_sha256 == sha
    assert restored.source.effective_base_revision == restored.source.base_revision


def test_bound_plan_captures_effective_base_and_hashes_exact_references(tmp_path: Path) -> None:
    old = make_plan(tmp_path / "repo")
    source = RecoverySource.model_validate(
        {
            **old.source.to_wire(),
            "execution_baseline_sha256": "e" * 64,
            "execution_base_revision": "c" * 40,
        }
    )
    capture = old.capture.model_copy(
        update={"source_revision": "c" * 40, "base_revision": "c" * 40}
    )
    # Rebuild its exact digest from typed captured facts.
    capture = type(capture).from_capture(capture.to_capture())
    plan = RecoveryPlan.create(**{**old.to_wire(), "source": source, "capture": capture})
    plan.validate_integrity()
    VALIDATOR.validate(plan.to_wire())
    assert source.base_revision == "a" * 40
    assert source.effective_base_revision == "c" * 40
    assert plan.plan_sha256 != old.plan_sha256
    with pytest.raises(ValidationError, match="capture"):
        RecoveryPlan.create(**{**old.to_wire(), "source": source})


@pytest.mark.parametrize(
    "field,value",
    [
        ("execution_baseline_sha256", "d" * 64),
        ("execution_base_revision", "b" * 40),
    ],
)
@pytest.mark.parametrize("companion_null", [False, True])
def test_half_bound_source_is_rejected(
    tmp_path: Path, field: str, value: str, companion_null: bool
) -> None:
    old = make_plan(tmp_path / "repo")
    wire = {**old.source.to_wire(), field: value}
    if companion_null:
        companion = (
            "execution_base_revision"
            if field == "execution_baseline_sha256"
            else "execution_baseline_sha256"
        )
        wire[companion] = None
    assert list(VALIDATOR.iter_errors({**old.to_wire(), "source": wire}))
    with pytest.raises(ValidationError, match="together"):
        RecoverySource.model_validate(wire)
