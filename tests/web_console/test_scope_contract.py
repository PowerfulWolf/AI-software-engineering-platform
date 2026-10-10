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


def test_approval_technical_facts_are_optional_and_preserve_legacy_serialization() -> None:
    legacy = ConsoleApprovalRequest(
        kind="coder_recovery",
        plan_sha256="a" * 64,
        title="保留进度并继续原需求",
        facts=("继续原需求并重新经过独立 QA/Reviewer",),
    )
    wire = legacy.to_wire()
    assert "technical_facts" not in wire
    assert ConsoleApprovalRequest.model_validate(wire).to_wire() == wire
    current = legacy.model_copy(update={"technical_facts": ("源 Task ID 用于核验",)})
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/console-operation.schema.json").read_text()
    )
    validator = Draft202012Validator(
        {"$ref": "#/$defs/ConsoleApprovalRequest", "$defs": schema["$defs"]}
    )
    validator.validate(wire)
    validator.validate(current.to_wire())
    assert ConsoleApprovalRequest.model_validate(current.to_wire()) == current
    for value in (("",), (1,)):
        invalid = {**wire, "technical_facts": value}
        with pytest.raises(ValidationError):
            ConsoleApprovalRequest.model_validate(invalid)
        with pytest.raises(SchemaValidationError):
            validator.validate({**invalid, "technical_facts": list(value)})
