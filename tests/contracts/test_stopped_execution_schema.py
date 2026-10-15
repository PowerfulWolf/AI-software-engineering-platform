"""Published and fresh wire graphs keep stopped-only engineering boundaries."""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.contracts.test_repair_schema_generation import generated_bundle as generated_fixture
from tests.manager.test_completed_output_rescue import public_input

generated_bundle = generated_fixture
ROOT = Path(__file__).resolve().parents[2]


def schema_node(schema: dict[str, Any], title: str) -> Draft202012Validator:
    return Draft202012Validator({"$defs": schema["$defs"], "$ref": f"#/$defs/{title}"})


@pytest.mark.parametrize("fresh", [False, True])
def test_stopped_public_proposal_is_target_free_preserve_only(
    generated_bundle: dict[str, dict[str, Any]], fresh: bool
) -> None:
    schema = (
        generated_bundle["console-operation.schema.json"]
        if fresh
        else json.loads((ROOT / "schemas/console-operation.schema.json").read_text())
    )
    validator = schema_node(schema, "ProposeExecutionBaselineIntent")
    wire = {**public_input(), "purpose": "stopped_execution_rescue"}
    validator.validate(wire)
    for change in ({"target_base_ref": "d" * 40}, {"input_mode": "coder_reapply"}):
        assert not validator.is_valid({**wire, **change})


@pytest.mark.parametrize("fresh", [False, True])
def test_stopped_reservation_keeps_no_result_refund_and_exact_new_work(
    generated_bundle: dict[str, dict[str, Any]], fresh: bool
) -> None:
    schema = (
        generated_bundle["console-operation.schema.json"]
        if fresh
        else json.loads((ROOT / "schemas/console-operation.schema.json").read_text())
    )
    validator = schema_node(schema, "BaselineExecutionReservation")
    wire = {
        "current_attempt": 1,
        "next_execution_attempt": 2,
        "retry_cause": "stopped_execution_unknown",
        "original_run_id": "run_original",
        "current_invocation_start_sha256": "a" * 64,
        "stopped_execution_sha256": "b" * 64,
    }
    validator.validate(wire)
    for change in (
        {"current_invocation_outcome_sha256": "c" * 64},
        {"interruption_receipt_sha256": "c" * 64},
        {"completed_output_sha256": "c" * 64},
        {"stopped_provider_failure_sha256": "c" * 64},
        {"reservation_already_applied": True},
        {"retry_cause": "provider_transient"},
        {"stopped_execution_sha256": None},
    ):
        assert not validator.is_valid({**wire, **change})


@pytest.mark.parametrize("fresh", [False, True])
def test_stopped_binding_must_pause_and_use_exact_human_authority(
    generated_bundle: dict[str, dict[str, Any]], fresh: bool
) -> None:
    schema = (
        generated_bundle["console-operation.schema.json"]
        if fresh
        else json.loads((ROOT / "schemas/console-operation.schema.json").read_text())
    )
    # Exercise canonical cross-field guards separately from unrelated mandatory IDs.
    node = schema["$defs"]["ExecutionBaselineBinding"]
    validator = Draft202012Validator({"allOf": node["allOf"]})
    wire = {
        "purpose": "stopped_execution_rescue",
        "stopped_execution_sha256": "a" * 64,
        "continuation_mode": "pause",
        "input_mode": "preserve_draft",
        "authority_source": "engineering_operator_decision",
    }
    validator.validate(wire)
    for change in (
        {"purpose": "source_rebind"},
        {"continuation_mode": "resume"},
        {"input_mode": "coder_reapply"},
        {"authority_source": "organization_engineering_policy"},
        {"legacy_containment_sha256": "b" * 64},
        {"completed_output_sha256": "b" * 64},
    ):
        assert not validator.is_valid({**wire, **change})
