"""Rejected semantic knowledge gets a distinct ordinary-work engineering action."""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    DeliveryNextAction,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
)
from tests.domain.test_delivery_resolution_schema import _wire


def test_rejected_knowledge_has_distinct_resolution() -> None:
    kind = DeliveryResolutionKind("RETRY_REJECTED_KNOWLEDGE_PREPARATION")
    assert kind is not DeliveryResolutionKind.RETRY_KNOWLEDGE_PREPARATION
    assert kind is not DeliveryResolutionKind.RESUME_UNINVOKED


def _rejected_resolution() -> dict[str, Any]:
    wire = _wire("RESUME_UNINVOKED")
    wire["resolution_kind"] = "RETRY_REJECTED_KNOWLEDGE_PREPARATION"
    wire["rejected_knowledge"] = {
        "scope": {
            "team_id": "team_schema",
            "project_id": "project_schema",
            "repository_id": "repository_schema",
            "repository_root": "/tmp/schema",
        },
        "requirement_id": "delivery_schema",
        "task_id": "task_schema",
        "work_item_id": "work_schema",
        "role": "coder",
        "original_lease_id": "lease_schema",
        "original_claim_sha256": "a" * 64,
        "original_attempt": 2,
        "original_dispatch_sequence": 1,
        "checkpoint_sequence": 4,
        "previous_run_id": "run_schema",
        "previous_context_manifest_id": "ctx_" + "b" * 64,
        "source_revision": "c" * 40,
        "observation_sha256": "d" * 64,
        "context_sha256": "e" * 64,
        "workspace_inventory_sha256": "f" * 64,
        "workspace_capture_sha256": "a" * 64,
        "current_lease_id": "lease_schema",
        "current_claim_sha256": "a" * 64,
        "current_dispatch_sequence": 1,
        "budget_source": "frozen_work_attempt",
    }
    return dict(DeliveryResolution.model_validate(wire).to_wire())


@pytest.mark.parametrize("mutation", ["missing", "wrong_action", "wrong_budget"])
def test_rejected_knowledge_schema_requires_exact_distinct_ordinary_work_proof(
    mutation: str,
) -> None:
    wire = _rejected_resolution()
    validator = Draft202012Validator(
        json.loads(
            (
                Path(__file__).parents[2] / "schemas" / "engineering-wait-resolution.schema.json"
            ).read_text()
        )
    )
    validator.validate(wire)
    if mutation == "missing":
        del wire["rejected_knowledge"]
    elif mutation == "wrong_action":
        wire["resolution_kind"] = "RESUME_UNINVOKED"
    else:
        wire["rejected_knowledge"]["budget_source"] = "provider_refund"
    with pytest.raises(ValidationError):
        DeliveryResolution.model_validate(wire)
    with pytest.raises(SchemaValidationError):
        validator.validate(wire)


def test_old_resolution_omits_semantic_proof_and_preserves_its_canonical_hash() -> None:
    record = DeliveryResolution.model_validate(_wire("RESUME_UNINVOKED"))
    assert "rejected_knowledge" not in record.to_wire()
    assert "rejected_knowledge" not in record.model_dump(mode="json")
    record = record.model_copy(update={"resolution_sha256": record.recompute_sha256()})
    DeliveryResolution.model_validate(record.to_wire()).validate_integrity()


def test_sealed_semantic_rejection_retains_engineering_wait_at_exhausted_budget() -> None:
    facts = DeliveryFailureFacts.model_validate(
        {
            "task_id": "task_schema",
            "work_item_id": "work_schema",
            "role": "coder",
            "classification": "INVALID_OUTPUT",
            "source_revision": "c" * 40,
            "task_intent_sha256": "a" * 64,
            "checkpoint_sequence": 4,
            "budget_available": False,
            "retry_authorized": False,
            "evidence_ids": ["knowledge-assessment-rejection://" + "b" * 64],
        }
    )
    decision = decide_delivery_disposition(facts)
    assert decision.action is DeliveryNextAction.INVESTIGATE_EXECUTION
    assert not decision.facts.budget_available and not decision.facts.retry_authorized
    ordinary = decide_delivery_disposition(facts.model_copy(update={"evidence_ids": ()}))
    assert ordinary.action is DeliveryNextAction.TERMINATE


def test_carry_refusal_schema_matches_its_trusted_runtime_record() -> None:
    from ai_software_engineer.manager.rejected_knowledge_preparation import (
        RejectedKnowledgeCarryRefusal,
    )

    name = "rejected-knowledge-carry-refusal"
    wire = json.loads((Path(__file__).parents[2] / "schemas" / f"{name}.schema.json").read_text())
    assert wire.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert wire.pop("$id") == f"https://ai-software-engineer.local/schemas/{name}.schema.json"
    assert wire == RejectedKnowledgeCarryRefusal.model_json_schema()


@pytest.mark.parametrize(
    ("classification", "evidence", "allowed"),
    [
        ("PLATFORM_BUG", (), True),
        ("PLATFORM_BUG", ("foreign://observation",), False),
        ("INVALID_OUTPUT", (), False),
        ("EXECUTION_UNCERTAIN", (), False),
        ("POLICY_VIOLATION", (), False),
    ],
)
def test_generic_wait_semantic_proof_retains_exact_original_classification(
    classification: str, evidence: tuple[str, ...], allowed: bool
) -> None:
    from ai_software_engineer.domain.delivery_resolution import DeliveryWaitInvestigation
    from tests.domain.factories import make_task
    from tests.team_view.test_engineering_history import _rejected_knowledge_proof

    original = _rejected_knowledge_proof(make_task())
    facts = DeliveryFailureFacts.model_validate(
        {
            **original.disposition.facts.to_wire(),
            "classification": classification,
            "evidence_ids": evidence,
        }
    )
    disposition = decide_delivery_disposition(facts)
    wire = {
        **original.to_wire(),
        "disposition": disposition.to_wire(),
        "disposition_sha256": disposition.disposition_sha256,
    }
    if not allowed:
        with pytest.raises(ValidationError):
            DeliveryWaitInvestigation.model_validate(wire)
    else:
        value = DeliveryWaitInvestigation.model_validate(wire)
        assert value.disposition == disposition
        assert value.rejected_knowledge == original.rejected_knowledge
        assert value.permitted_resolutions == original.permitted_resolutions


def test_current_draft_requires_separate_human_engineering_decision() -> None:
    from ai_software_engineer.domain.delivery_resolution import RejectedKnowledgePreparationEvidence

    wire = _rejected_resolution()
    evidence = {**wire["rejected_knowledge"], "current_draft_sha256": "5" * 64}
    proposed = RejectedKnowledgePreparationEvidence.model_validate(evidence)
    assert proposed.current_draft_sha256 == "5" * 64
    record = DeliveryResolution.model_validate({**wire, "rejected_knowledge": proposed.to_wire()})
    assert record.authorization_source == "engineering_operator_decision"
