"""Completed output recovery is a separate exact proof, not a fabricated interruption."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
    DeliveryWaitInvestigation,
    RejectedCoderOutputEvidence,
)
from ai_software_engineer.domain.engineering_authority import (
    EngineeringScope,
    LocalOperatorPrincipal,
)
from ai_software_engineer.domain.enums import AgentRole
from tests.domain.factories import NOW
from tests.domain.test_knowledge_preparation_retry_schema import _proof as knowledge_proof

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


def evidence() -> RejectedCoderOutputEvidence:
    return RejectedCoderOutputEvidence(
        scope=EngineeringScope(
            team_id="team_rejected",
            project_id="project_rejected",
            repository_id="repository_rejected",
            repository_root="/tmp/rejected-fixture",
        ),
        requirement_id="requirement_rejected",
        task_id="task_rejected",
        work_item_id="work_rejected",
        original_lease_id="lease_rejected",
        original_claim_sha256="1" * 64,
        original_attempt=4,
        original_dispatch_sequence=1,
        checkpoint_sequence=8,
        previous_run_id="run_rejected",
        previous_context_manifest_id="ctx_" + "2" * 64,
        source_revision="a" * 40,
        invocation_start_sha256="3" * 64,
        invocation_outcome_sha256="4" * 64,
        rejected_artifact_id="art_rejected",
        rejected_artifact_sha256="5" * 64,
        expected_sequence=4,
        reported_sequence=9,
        process_stop_sha256="6" * 64,
        capture_sha256="7" * 64,
        workspace_inventory_sha256="8" * 64,
        checkpoint_sha256="9" * 64,
    )


def proof() -> DeliveryWaitInvestigation:
    fact = evidence()
    disposition = decide_delivery_disposition(
        DeliveryFailureFacts(
            task_id=fact.task_id,
            work_item_id=fact.work_item_id,
            role=AgentRole.CODER,
            classification="PLATFORM_BUG",
            source_revision=fact.source_revision,
            task_intent_sha256="b" * 64,
            checkpoint_sequence=fact.checkpoint_sequence,
            budget_available=True,
        )
    )
    result = DeliveryWaitInvestigation(
        task_id=fact.task_id,
        work_item_id=fact.work_item_id,
        disposition=disposition,
        disposition_sha256=disposition.disposition_sha256,
        task_intent_sha256="b" * 64,
        task_revision=8,
        task_snapshot_sha256="c" * 64,
        source_revision=fact.source_revision,
        checkpoint_sequence=fact.checkpoint_sequence,
        step_sha256="d" * 64,
        original_run_id=fact.previous_run_id,
        invocation_start_sha256=fact.invocation_start_sha256,
        invocation_outcome_sha256=fact.invocation_outcome_sha256,
        process_stop_sha256=fact.process_stop_sha256,
        workspace_inventory_sha256=fact.workspace_inventory_sha256,
        rejected_output=fact,
        permitted_resolutions=(DeliveryResolutionKind.RETRY_REJECTED_CODER_OUTPUT,),
        next_action="保留原草稿, 使用新的受控开发执行更正产出。",
        inspected_at=NOW,
        proof_sha256="0" * 64,
    )
    return result.model_copy(update={"proof_sha256": result.recompute_sha256()})


def decision() -> DeliveryResolution:
    source = proof()
    result = DeliveryResolution(
        task_id=source.task_id,
        work_item_id=source.work_item_id,
        expected_disposition_sha256=source.disposition_sha256,
        expected_task_intent_sha256=source.task_intent_sha256,
        expected_source_revision=source.source_revision,
        expected_checkpoint_sequence=source.checkpoint_sequence,
        task_revision=source.task_revision,
        task_snapshot_sha256=source.task_snapshot_sha256,
        step_sha256=source.step_sha256,
        resolution_kind=DeliveryResolutionKind.RETRY_REJECTED_CODER_OUTPUT,
        proof_sha256=source.proof_sha256,
        operator_principal=LocalOperatorPrincipal.trusted_local(),
        submitted_at=NOW,
        rejected_output=source.rejected_output,
        resolution_sha256="0" * 64,
    )
    return result.model_copy(update={"resolution_sha256": result.recompute_sha256()})


@pytest.mark.parametrize("schema", ["engineering-wait-resolution", "console-operation"])
@pytest.mark.parametrize("model", ["DeliveryResolution", "DeliveryWaitInvestigation"])
def test_new_action_requires_exact_rejected_output_in_every_public_schema(
    schema: str, model: str
) -> None:
    document = json.loads((SCHEMAS / (schema + ".schema.json")).read_text())
    validator = Draft202012Validator({"$defs": document["$defs"], "$ref": "#/$defs/" + model})
    record = decision() if model == "DeliveryResolution" else proof()
    record.validate_integrity()
    wire = record.to_wire()
    assert validator.is_valid(wire)
    wire.pop("rejected_output")
    assert not validator.is_valid(wire)


@pytest.mark.parametrize("drift", ["timeout", "replay", "role", "classification"])
def test_rejected_proof_cannot_masquerade_as_another_route(drift: str) -> None:
    wire: dict[str, Any] = deepcopy(proof().to_wire())
    if drift == "timeout":
        wire["retry_cause"] = "local_execution_limit"
    elif drift == "replay":
        wire["permitted_resolutions"] = ["REPLAY_RECORDED_RESULT"]
    elif drift == "role":
        wire["disposition"]["facts"]["role"] = "qa"
    else:
        wire["disposition"]["facts"]["classification"] = "PROVIDER_UNAVAILABLE"
    with pytest.raises(ValidationError):
        DeliveryWaitInvestigation.model_validate(wire)
    schema = json.loads((SCHEMAS / "engineering-wait-resolution.schema.json").read_text())
    assert not Draft202012Validator(schema).is_valid(wire)


def test_rejected_proof_requires_real_mismatch_and_preserves_old_optional_wire() -> None:
    original = evidence().to_wire()
    with pytest.raises(ValidationError, match="real run sequence mismatch"):
        RejectedCoderOutputEvidence.model_validate({**original, "reported_sequence": 4})
    old = knowledge_proof()
    assert "rejected_output" not in old.to_wire()
    restored = DeliveryWaitInvestigation.model_validate(old.to_wire())
    assert restored == old and restored.proof_sha256 == old.proof_sha256
