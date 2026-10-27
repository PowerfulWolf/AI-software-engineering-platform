"""Published wait schemas retain the exact static QA decision guards."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from ai_software_engineer.domain.delivery_resolution import DeliveryResolution
from tests.domain.test_delivery_resolution_schema import _wire

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


def _static_decision() -> dict[str, Any]:
    wire = _wire("RESUME_UNINVOKED")
    wire["resolution_kind"] = "STATIC_QA_MISSING_ENTRY"
    wire["verifier_preparation"] = {
        "candidate_revision": "c" * 40,
        "preparation_checkpoint_sha256": "a" * 64,
        "previous_run_id": "run_schema",
        "previous_context_manifest_id": "ctx_" + "b" * 64,
        "request_sha256": "d" * 64,
        "native_execution_state": "NOT_STARTED",
        "prerequisite_facts_sha256": "e" * 64,
    }
    wire["static_qa_missing_entry"] = {
        "candidate_revision": "c" * 40,
        "observation_sha256": "f" * 64,
        "plan_artifact_id": "art_plan_schema",
        "plan_artifact_sha256": "a" * 64,
        "implementation_artifact_id": "art_impl_schema",
        "implementation_artifact_sha256": "b" * 64,
        "preparation_checkpoint_sha256": "a" * 64,
        "original_lease_id": "lease_original_schema",
        "wait_lease_id": "lease_wait_schema",
        "original_dispatch_sequence": 0,
        "wait_dispatch_sequence": 1,
        "original_claim_sha256": "c" * 64,
        "wait_claim_sha256": "d" * 64,
        "previous_run_id": "run_schema",
        "previous_context_manifest_id": "ctx_" + "b" * 64,
        "prerequisite_facts_sha256": "e" * 64,
    }
    return dict(DeliveryResolution.model_validate(wire).to_wire())


@pytest.mark.parametrize(
    "filename",
    (
        "engineering-wait-resolution.schema.json",
        "console-operation.schema.json",
        "console-deletion-cleanup.schema.json",
    ),
)
@pytest.mark.parametrize(
    "mutation",
    ("none", "missing_static", "wrong_kind", "missing_preparation", "finished", "policy"),
)
def test_static_decision_schema_roundtrip_and_tamper(filename: str, mutation: str) -> None:
    schema = json.loads((SCHEMAS / filename).read_text(encoding="utf-8"))
    validator = Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": schema["$defs"],
            "$ref": "#/$defs/DeliveryResolution",
        }
    )
    wire = _static_decision()
    validator.validate(wire)
    DeliveryResolution.model_validate(wire)
    if mutation == "none":
        return
    changed = deepcopy(wire)
    if mutation == "missing_static":
        changed.pop("static_qa_missing_entry")
    elif mutation == "wrong_kind":
        changed["resolution_kind"] = "RESUME_UNINVOKED"
    elif mutation == "missing_preparation":
        changed.pop("verifier_preparation")
    elif mutation == "finished":
        changed["verifier_preparation"]["native_execution_state"] = "FINISHED"
    else:
        changed["authorization_source"] = "organization_engineering_policy"
    with pytest.raises(ValidationError):
        DeliveryResolution.model_validate(changed)
    with pytest.raises(SchemaValidationError):
        validator.validate(changed)
