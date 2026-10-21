"""Published semantic recovery contracts keep exact wait and human draft authority."""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError

from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import DeliveryWaitInvestigation
from tests.domain.factories import make_task
from tests.team_view.test_engineering_history import _rejected_knowledge_proof
from tests.work_queue.test_rejected_knowledge_contract import _rejected_resolution

ROOT = Path(__file__).resolve().parents[2]


def _schemas_with(model: str) -> list[dict[str, Any]]:
    values = [json.loads(path.read_text()) for path in (ROOT / "schemas").glob("*.schema.json")]
    return [value for value in values if model in value.get("$defs", {})]


def test_generic_platform_wait_schema_accepts_only_exact_empty_evidence_shape() -> None:
    proposal = _rejected_knowledge_proof(make_task())
    facts = DeliveryFailureFacts.model_validate(
        {
            **proposal.disposition.facts.to_wire(),
            "classification": "PLATFORM_BUG",
            "evidence_ids": [],
        }
    )
    disposition = decide_delivery_disposition(facts)
    original = {
        **proposal.to_wire(),
        "disposition": disposition.to_wire(),
        "disposition_sha256": disposition.disposition_sha256,
    }
    DeliveryWaitInvestigation.model_validate(original)
    for schema in _schemas_with("DeliveryWaitInvestigation"):
        validator = Draft202012Validator(
            {"$defs": schema["$defs"], "$ref": "#/$defs/DeliveryWaitInvestigation"}
        )
        validator.validate(original)
        changed = json.loads(json.dumps(original))
        changed["disposition"]["facts"]["evidence_ids"] = ["foreign://observation"]
        with pytest.raises(SchemaValidationError):
            validator.validate(changed)


def test_current_draft_wire_guard_requires_current_operator_decision_in_every_embedding() -> None:
    wire = _rejected_resolution()
    wire["rejected_knowledge"]["current_draft_sha256"] = "e" * 64
    for schema in _schemas_with("DeliveryResolution"):
        # Exercise the authority guard independently of unrelated admission fields.
        # A shape-valid automatic declaration must never authorize present draft bytes.
        validator = Draft202012Validator({"allOf": schema["$defs"]["DeliveryResolution"]["allOf"]})
        validator.validate(wire)
        changed = {
            **wire,
            "authorization_source": "organization_engineering_policy",
            "operator_principal": None,
            "engineering_admission": {},
        }
        with pytest.raises(SchemaValidationError):
            validator.validate(changed)


def test_complete_current_draft_standalone_schema_matches_trusted_record() -> None:
    from ai_software_engineer.manager.rejected_knowledge_draft import RejectedKnowledgeCurrentDraft

    name = "rejected-knowledge-current-draft"
    wire = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
    assert wire.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert wire.pop("$id") == f"https://ai-software-engineer.local/schemas/{name}.schema.json"
    assert wire == RejectedKnowledgeCurrentDraft.model_json_schema()
