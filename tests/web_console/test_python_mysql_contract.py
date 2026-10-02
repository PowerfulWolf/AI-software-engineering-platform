"""Precise incremental selections are proposals, never an approval or shell expansion."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.web_console.models import ContinueDeliveryIntent


def validator():
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/console-operation.schema.json").read_text()
    )
    return Draft202012Validator(
        {"$ref": "#/$defs/ContinueDeliveryIntent", "$defs": schema["$defs"]}
    )


def wire():
    return {
        "action": "CONTINUE_DELIVERY",
        "project_id": "project_fixture",
        "delivery_id": "delivery_fixture",
        "expected_checkpoint_sha256": "a" * 64,
        "python_mysql_tests": [
            {"node_id": "tests/test_sql.py::test_exact", "criterion_ids": ["ac_01"]}
        ],
    }


def test_python_proposal_roundtrip_and_legacy_operation_hash_input_are_preserved():
    payload = wire()
    validator().validate(payload)
    intent = ContinueDeliveryIntent.model_validate(payload)
    assert intent.to_wire() == payload
    legacy = {k: v for k, v in payload.items() if k != "python_mysql_tests"}
    assert ContinueDeliveryIntent.model_validate(legacy).to_wire() == legacy
    command = ResumeProjectDelivery(
        delivery_id=intent.delivery_id, python_mysql_tests=intent.python_mysql_tests
    )
    assert command.python_mysql_tests == intent.python_mysql_tests


@pytest.mark.parametrize(
    "other", ["approved_plan_sha256", "approved_scope_sha256", "approved_repair_sha256"]
)
def test_python_proposal_cannot_include_any_approval(other):
    payload = {**wire(), other: "b" * 64}
    with pytest.raises(ValidationError):
        ContinueDeliveryIntent.model_validate(payload)
    with pytest.raises(SchemaValidationError):
        validator().validate(payload)
    with pytest.raises(ValidationError):
        ResumeProjectDelivery.model_validate(
            {
                "delivery_id": "delivery_fixture",
                "python_mysql_tests": payload["python_mysql_tests"],
                other: "b" * 64,
                "approval_reference": "delegated-fixture",
            }
        )


@pytest.mark.parametrize(
    "node",
    ["tests", "tests/test_sql.py", "tests/test_sql.py::*", "tests/test_sql.py::test_exact -q"],
)
def test_nonincremental_test_inputs_are_rejected_by_both_wire_contracts(node):
    payload = wire()
    payload["python_mysql_tests"][0]["node_id"] = node
    with pytest.raises(ValidationError):
        ContinueDeliveryIntent.model_validate(payload)
    with pytest.raises(SchemaValidationError):
        validator().validate(payload)
