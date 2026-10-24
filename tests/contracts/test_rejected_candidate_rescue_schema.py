"""Published candidate rescue gates preserve the narrow historical distinction."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
from ai_software_engineer.domain.model import JsonValue, WirePayload
from ai_software_engineer.manager.baseline_models import BaselineExecutionReservation
from tests.manager.test_rejected_candidate_baseline_models import _binding, _reservation
from tests.manager.test_rejected_candidate_output import RejectedCandidateFixture
from tests.manager.test_rejected_candidate_output import (
    rejected_candidate_proof_fixture as rejected_candidate_proof_fixture,
)

SCHEMAS = Path(__file__).parents[2] / "schemas"


def _object(value: JsonValue) -> WirePayload:
    assert isinstance(value, dict)
    return value


def _validator(filename: str, title: str) -> Draft202012Validator:
    document = json.loads((SCHEMAS / filename).read_text())
    if document.get("title") != title:
        document = {"$defs": document["$defs"], "$ref": f"#/$defs/{title}"}
    return Draft202012Validator(document)


@pytest.mark.parametrize(
    "filename",
    [
        "rejected-candidate-output.schema.json",
        "execution-baseline-plan.schema.json",
        "execution-baseline-queue-consumption.schema.json",
        "console-operation.schema.json",
    ],
)
def test_original_successful_unsupported_report_remains_readable_but_narrow(
    rejected_candidate_proof_fixture: RejectedCandidateFixture,
    filename: str,
) -> None:
    check = _validator(filename, "RejectedCandidateOutputProof")
    wire = rejected_candidate_proof_fixture.proof.to_wire()
    check.validate(wire)
    for change in (
        "supported_version",
        "failed",
        "no_session",
        "missing_output",
        "terminal",
        "publication",
    ):
        value = deepcopy(wire)
        result = _object(_object(value["outcome"])["result"])
        stop = _object(value["capture_stop"])
        if change == "supported_version":
            _object(result["artifact"])["schema_version"] = "v0.1"
        elif change == "failed":
            result["status"] = "FAILED"
        elif change == "no_session":
            _object(stop["process_stop"]).pop("session_proof")
        elif change == "missing_output":
            stop["output_present"] = False
        elif change == "terminal":
            _object(value["task"])["status"] = "DONE"
        else:
            value["publication_absent"] = False
        assert not check.is_valid(value), (filename, change)


@pytest.mark.parametrize(
    "filename",
    [
        "execution-baseline.schema.json",
        "execution-baseline-plan.schema.json",
        "execution-baseline-queue-consumption.schema.json",
        "console-operation.schema.json",
    ],
)
def test_new_binding_digest_cannot_be_mixed_with_old_purpose_or_resume(
    filename: str,
) -> None:
    check = _validator(filename, "ExecutionBaselineBinding")
    wire = ExecutionBaselineBinding.create(**_binding()).to_wire()
    check.validate(wire)
    updates: tuple[dict[str, object], ...] = (
        {"purpose": "source_rebind"},
        {"purpose": "completed_output_rescue"},
        {"continuation_mode": "resume"},
        {"authority_source": "organization_engineering_policy"},
        {"input_mode": "coder_reapply"},
        {"completed_output_sha256": "f" * 64},
        {"service_pause_outcome_sha256": "f" * 64},
        {"rejected_candidate_output_sha256": None},
    )
    for update in updates:
        assert not check.is_valid({**wire, **update}), (filename, update)


@pytest.mark.parametrize(
    "filename", ["execution-baseline-plan.schema.json", "console-operation.schema.json"]
)
def test_reservation_requires_the_original_outcome_and_normal_unapplied_work(filename: str) -> None:
    check = _validator(filename, "BaselineExecutionReservation")
    wire = BaselineExecutionReservation.model_validate(_reservation()).to_wire()
    check.validate(wire)
    updates: tuple[dict[str, object], ...] = (
        {"retry_cause": "uninvoked"},
        {"reservation_already_applied": True},
        {"original_run_id": None},
        {"current_invocation_outcome_sha256": None},
        {"completed_output_sha256": "f" * 64},
        {"retry_failure": {}},
    )
    for update in updates:
        assert not check.is_valid({**wire, **update}), (filename, update)


def test_public_proposal_is_target_free_and_cannot_reapply() -> None:
    check = _validator("console-operation.schema.json", "ProposeExecutionBaselineIntent")
    wire: dict[str, object] = {
        "action": "PROPOSE_EXECUTION_BASELINE",
        "project_id": "project_fixture",
        "delivery_id": "delivery_fixture",
        "expected_checkpoint_sha256": "a" * 64,
        "task_id": "task_domain_001",
        "expected_task_intent_sha256": "b" * 64,
        "expected_task_revision": 2,
        "expected_work_item_id": "work_fixture",
        "expected_source_revision": "c" * 40,
        "purpose": "rejected_candidate_rescue",
        "input_mode": "preserve_draft",
    }
    check.validate(wire)
    assert not check.is_valid({**wire, "target_base_ref": "d" * 40})
    assert not check.is_valid({**wire, "input_mode": "coder_reapply"})
