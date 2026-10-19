"""The positive no-start proof and its public wire guards agree."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryWaitInvestigation,
)
from ai_software_engineer.domain.knowledge_preparation_pause import (
    KnowledgePreparationPauseEvidence,
)
from tests.domain.test_knowledge_preparation_retry_schema import _decision, _evidence, _proof

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


def pause_evidence() -> dict[str, Any]:
    prior = _evidence()
    return {
        **{
            name: prior[name]
            for name in KnowledgePreparationPauseEvidence.model_fields
            if name in prior
        },
        "delivery_requirement_id": "delivery_multi_knowledge_schema",
        "proof_mode": "pre_admission_refusal",
        "pre_admission_pause_sha256": "7" * 64,
        "execution_record_sha256s": [],
    }


def pause_wire(kind: str) -> dict[str, Any]:
    proof = _proof()
    evidence = pause_evidence()
    facts = DeliveryFailureFacts.model_validate(
        {
            **proof.disposition.facts.to_wire(),
            "classification": "SERVICE_PAUSED",
            "evidence_ids": ["knowledge-pause://" + evidence["outcome_sha256"]],
        }
    )
    disposition = decide_delivery_disposition(facts)
    if kind == "DeliveryWaitInvestigation":
        return {
            **proof.to_wire(),
            "disposition": disposition.to_wire(),
            "disposition_sha256": disposition.disposition_sha256,
            "knowledge_preparation": None,
            "knowledge_pause": evidence,
            "permitted_resolutions": ["RESUME_UNINVOKED"],
        }
    return {
        **_decision(proof).to_wire(),
        "expected_disposition_sha256": disposition.disposition_sha256,
        "resolution_kind": "RESUME_UNINVOKED",
        "knowledge_preparation": None,
        "knowledge_pause": evidence,
    }


def validate_wire(kind: str, wire: dict[str, Any]) -> None:
    model = DeliveryWaitInvestigation if kind == "DeliveryWaitInvestigation" else DeliveryResolution
    model.model_validate(wire)
    for filename in (
        "engineering-wait-resolution.schema.json",
        "console-operation.schema.json",
        "stopped-failure-budget-settlement.schema.json",
    ):
        schema = json.loads((SCHEMAS / filename).read_text())
        if kind not in schema["$defs"]:
            assert filename == "stopped-failure-budget-settlement.schema.json"
            continue
        Draft202012Validator({"$ref": "#/$defs/" + kind, "$defs": schema["$defs"]}).validate(wire)


@pytest.mark.parametrize("kind", ["DeliveryWaitInvestigation", "DeliveryResolution"])
@pytest.mark.parametrize("mode", ["pre_admission_refusal", "native_admission_closed"])
def test_positive_exact_refusal_is_the_only_same_attempt_knowledge_resume(
    kind: str, mode: str
) -> None:
    wire = pause_wire(kind)
    if mode == "native_admission_closed":
        wire["knowledge_pause"].update(
            proof_mode=mode,
            pre_admission_pause_sha256=None,
            execution_record_sha256s=["2" * 64, "3" * 64],
        )
    validate_wire(kind, wire)


@pytest.mark.parametrize("kind", ["DeliveryWaitInvestigation", "DeliveryResolution"])
@pytest.mark.parametrize(
    "mutation", ["no_receipt", "mixed_receipt", "duplicate_pair", "wrong_action"]
)
def test_malformed_or_wrong_action_pause_is_refused_in_models_and_all_embedded_schemas(
    kind: str, mutation: str
) -> None:
    wire = pause_wire(kind)
    if mutation == "no_receipt":
        wire["knowledge_pause"]["pre_admission_pause_sha256"] = None
    elif mutation == "mixed_receipt":
        wire["knowledge_pause"]["execution_record_sha256s"] = ["2" * 64, "3" * 64]
    elif mutation == "duplicate_pair":
        wire["knowledge_pause"].update(
            proof_mode="native_admission_closed",
            pre_admission_pause_sha256=None,
            execution_record_sha256s=["2" * 64, "2" * 64],
        )
    elif kind == "DeliveryWaitInvestigation":
        wire["permitted_resolutions"] = ["REPLAY_RECORDED_RESULT"]
    else:
        wire["resolution_kind"] = "REPLAY_RECORDED_RESULT"
    model = DeliveryWaitInvestigation if kind == "DeliveryWaitInvestigation" else DeliveryResolution
    with pytest.raises(ValidationError):
        model.model_validate(wire)
    for filename in (
        "engineering-wait-resolution.schema.json",
        "console-operation.schema.json",
        "stopped-failure-budget-settlement.schema.json",
    ):
        schema = json.loads((SCHEMAS / filename).read_text())
        if kind not in schema["$defs"]:
            assert filename == "stopped-failure-budget-settlement.schema.json"
            continue
        with pytest.raises(SchemaValidationError):
            Draft202012Validator({"$ref": "#/$defs/" + kind, "$defs": schema["$defs"]}).validate(
                wire
            )


@pytest.mark.parametrize("kind", ["DeliveryWaitInvestigation", "DeliveryResolution"])
def test_pause_cannot_hide_another_knowledge_or_main_invocation_proof(kind: str) -> None:
    wire = pause_wire(kind)
    original = _proof().knowledge_preparation
    assert original is not None
    wire["knowledge_preparation"] = original.to_wire()
    model = DeliveryWaitInvestigation if kind == "DeliveryWaitInvestigation" else DeliveryResolution
    with pytest.raises(ValidationError):
        model.model_validate(wire)
    for filename in ("engineering-wait-resolution.schema.json", "console-operation.schema.json"):
        schema = json.loads((SCHEMAS / filename).read_text())
        with pytest.raises(SchemaValidationError):
            Draft202012Validator({"$ref": "#/$defs/" + kind, "$defs": schema["$defs"]}).validate(
                wire
            )


def test_old_no_pause_fields_preserve_nested_wire_and_digests() -> None:
    for value in (_proof(), _decision(_proof())):
        before = deepcopy(value.to_wire())
        restored = type(value).model_validate({**before, "knowledge_pause": None})
        assert "knowledge_pause" not in restored.model_dump(mode="json")
        assert restored.to_wire() == before
        assert restored.recompute_sha256() == value.recompute_sha256()


def test_pause_uri_cannot_authorize_resume_without_its_positive_proof() -> None:
    wire = pause_wire("DeliveryWaitInvestigation")
    wire["knowledge_pause"] = None
    with pytest.raises(ValidationError):
        DeliveryWaitInvestigation.model_validate(wire)
    for filename in ("engineering-wait-resolution.schema.json", "console-operation.schema.json"):
        schema = json.loads((SCHEMAS / filename).read_text())
        with pytest.raises(SchemaValidationError):
            Draft202012Validator(
                {
                    "$ref": "#/$defs/DeliveryWaitInvestigation",
                    "$defs": schema["$defs"],
                }
            ).validate(wire)
