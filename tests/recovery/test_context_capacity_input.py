"""A capacity recovery preserves the exact retained patch as required input."""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.domain.execution_baseline import RetainedExecutionPatch
from ai_software_engineer.recovery.context import recovery_context_sources
from ai_software_engineer.recovery.models import RecoveryPlan
from tests.recovery.test_authorization import make_plan


def capacity_plan(project: Path) -> RecoveryPlan:
    plan = make_plan(project)
    patch = "diff --git a/src/app.py b/src/app.py\n+retained complete development\n"
    reference = RetainedExecutionPatch(
        uri="baseline://complete/patch",
        sha256=hashlib.sha256(patch.encode()).hexdigest(),
        bytes=len(patch.encode()),
    )
    wire = plan.to_wire()
    wire.pop("plan_sha256")
    wire["input_mode"] = "coder_reapply"
    wire["source"] = {
        **plan.source.to_wire(),
        "failed_run_id": None,
        "context_capacity_receipt_sha256": "d" * 64,
        "execution_baseline_sha256": "e" * 64,
        "execution_base_revision": plan.source.base_revision,
    }
    wire["context_capacity_input"] = {
        "execution_baseline_sha256": "e" * 64,
        "retained_patch": reference.to_wire(),
        "patch": patch,
    }
    return RecoveryPlan.create(**wire)


def test_capacity_plan_uses_complete_retained_patch_instead_of_empty_clean_capture(
    tmp_path: Path,
) -> None:
    capacity = capacity_plan(tmp_path / "project")
    assert capacity.capture.patch == ""
    sources = recovery_context_sources(capacity)
    assert sources[1].source_id == "recovery.patch"
    assert capacity.context_capacity_input is not None
    assert sources[1].content == capacity.context_capacity_input.patch
    assert sources[1].required


def test_capacity_wire_keeps_ordinary_run_required_and_exact_no_start_input(tmp_path: Path) -> None:
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(
        json.loads(
            (Path(__file__).parents[2] / "schemas/delivery-recovery.schema.json").read_text()
        )
    )
    ordinary = make_plan(tmp_path / "project")
    capacity = capacity_plan(tmp_path / "project")
    assert "failed_run_id" not in capacity.source.to_wire()
    assert "context_capacity_input" not in ordinary.to_wire()
    validator.validate(ordinary.to_wire())
    validator.validate(capacity.to_wire())
    assert RecoveryPlan.model_validate(capacity.to_wire()) == capacity
    for fault in ("run", "receipt", "input", "mode", "files"):
        wire = capacity.to_wire()
        if fault == "run":
            wire["source"]["failed_run_id"] = "run_invented"
        elif fault == "receipt":
            del wire["source"]["context_capacity_receipt_sha256"]
        elif fault == "input":
            del wire["context_capacity_input"]
        elif fault == "mode":
            wire["input_mode"] = None
        else:
            wire["capture"]["files"] = [{"path": "src/app.py", "sha256": "a" * 64}]
        assert list(validator.iter_errors(wire)), fault
        with pytest.raises(ValidationError):
            RecoveryPlan.model_validate(wire)
    wire = ordinary.to_wire()
    del wire["source"]["failed_run_id"]
    assert list(validator.iter_errors(wire))
    with pytest.raises(ValidationError):
        RecoveryPlan.model_validate(wire)


@pytest.mark.parametrize("fault", ("missing_receipt", "invented_run", "patch", "dirty", "mode"))
def test_capacity_recovery_cannot_invent_execution_or_drop_patch(
    tmp_path: Path, fault: str
) -> None:
    from ai_software_engineer.recovery.models import ContextCapacityRecoveryInput

    plan = make_plan(tmp_path / "project")
    patch = "retained complete patch\n"
    reference = RetainedExecutionPatch(
        uri="baseline://complete/patch",
        sha256=hashlib.sha256(patch.encode()).hexdigest(),
        bytes=len(patch.encode()),
    )
    payload = ContextCapacityRecoveryInput(
        execution_baseline_sha256="e" * 64, retained_patch=reference, patch=patch
    )
    wire = json.loads(plan.model_dump_json())
    wire.pop("plan_sha256")
    wire["input_mode"] = "coder_reapply"
    wire["source"]["failed_run_id"] = None
    wire["source"]["context_capacity_receipt_sha256"] = "d" * 64
    wire["source"]["execution_baseline_sha256"] = "e" * 64
    wire["source"]["execution_base_revision"] = plan.source.base_revision
    wire["context_capacity_input"] = payload.to_wire()
    if fault == "missing_receipt":
        wire["source"].pop("context_capacity_receipt_sha256")
    elif fault == "invented_run":
        wire["source"]["failed_run_id"] = "run_invented"
    elif fault == "patch":
        wire["context_capacity_input"]["patch"] += "modified"
    elif fault == "dirty":
        wire["capture"]["patch"] = "different actual dirty worktree"
    else:
        wire["input_mode"] = None
    with pytest.raises(ValidationError):
        RecoveryPlan.create(**wire)
