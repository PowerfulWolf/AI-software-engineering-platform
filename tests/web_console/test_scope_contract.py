"""Requested scope approval wire constraints match the typed Console boundary."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from ai_software_engineer.web_console.models import ConsoleApprovalRequest


def test_scope_request_cannot_be_smuggled_into_another_approval_kind() -> None:
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/console-operation.schema.json").read_text()
    )
    validator = Draft202012Validator(
        {
            "$ref": "#/$defs/ConsoleApprovalRequest",
            "$defs": schema["$defs"],
        }
    )
    wire = {
        "kind": "coder_scope",
        "plan_sha256": "a" * 64,
        "title": "Exact scope",
        "facts": ["No execution before plan approval"],
        "coder_scope_request": {
            "progress_artifact_id": "art_progress_001",
            "progress_sha256": "b" * 64,
            "paths": ["tests/test_contract.py"],
            "reason": "Necessary fixture update",
        },
    }
    validator.validate(wire)
    ConsoleApprovalRequest.model_validate(wire)
    for kind in ("candidate_verification", "coder_recovery", "prerequisite_repair"):
        invalid = {**wire, "kind": kind}
        with pytest.raises(SchemaValidationError):
            validator.validate(invalid)
        with pytest.raises(ValidationError):
            ConsoleApprovalRequest.model_validate(invalid)
        legacy = {k: v for k, v in invalid.items() if k != "coder_scope_request"}
        validator.validate(legacy)
        ConsoleApprovalRequest.model_validate(legacy)
