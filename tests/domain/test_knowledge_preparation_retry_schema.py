"""Knowledge retries preserve exact engineering proof and historical wire identities."""

import json
from copy import deepcopy
from datetime import timedelta
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
    DeliveryResolutionKind,
    DeliveryWaitHandling,
    DeliveryWaitInvestigation,
    KnowledgePreparationRetryEvidence,
)
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.web_console.models import (
    ConsoleCommandResult,
    ConsoleOperation,
    ConsoleOperationStatus,
    HandleDeliveryWaitIntent,
)
from tests.domain.factories import NOW

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


def _evidence(role: AgentRole = AgentRole.CODER) -> dict[str, Any]:
    return {
        "scope": {
            "team_id": "team_knowledge_schema",
            "project_id": "project_knowledge_schema",
            "repository_id": "repository_knowledge_schema",
            "repository_root": "/tmp/ase-knowledge-schema",
        },
        "requirement_id": "requirement_knowledge_schema",
        "task_id": "task_knowledge_schema",
        "role": role.value,
        "work_item_id": "work_knowledge_schema",
        "original_lease_id": "lease_knowledge_schema",
        "original_claim_sha256": "a" * 64,
        "original_attempt": 1,
        "original_dispatch_sequence": 0,
        "checkpoint_sequence": 2,
        "previous_run_id": "run_knowledge_schema",
        "previous_context_manifest_id": "ctx_" + "b" * 64,
        "source_revision": "c" * 40,
        "snapshot_sha256": "d" * 64,
        "phase": "intent",
        "intent_sha256": "e" * 64,
        "outcome_sha256": "f" * 64,
        "request_sha256": "1" * 64,
        "execution_record_sha256s": ["2" * 64, "3" * 64],
        "root_intent_sha256": "e" * 64,
        "initial_timeout_seconds": 600,
        "current_timeout_seconds": 600,
        "next_timeout_seconds": 1200,
        "maximum_timeout_seconds": 2400,
        "expansion_number": 1,
        "budget_source": "frozen_work_attempt",
    }


def _proof(role: AgentRole = AgentRole.CODER) -> DeliveryWaitInvestigation:
    evidence = _evidence(role)
    facts = DeliveryFailureFacts(
        task_id=evidence["task_id"],
        work_item_id=evidence["work_item_id"],
        role=role,
        classification="KNOWLEDGE_PREPARATION_LIMIT",
        source_revision=evidence["source_revision"],
        task_intent_sha256="4" * 64,
        checkpoint_sequence=evidence["checkpoint_sequence"],
        budget_available=True,
        evidence_ids=("knowledge-preparation://" + evidence["outcome_sha256"],),
    )
    disposition = decide_delivery_disposition(facts)
    proof = DeliveryWaitInvestigation(
        task_id=facts.task_id,
        work_item_id=evidence["work_item_id"],
        disposition=disposition,
        disposition_sha256=disposition.disposition_sha256,
        task_intent_sha256=facts.task_intent_sha256,
        task_revision=2,
        task_snapshot_sha256="5" * 64,
        source_revision=facts.source_revision,
        checkpoint_sequence=2,
        step_sha256="6" * 64,
        original_run_id=evidence["previous_run_id"],
        knowledge_preparation=KnowledgePreparationRetryEvidence.model_validate(evidence),
        permitted_resolutions=(DeliveryResolutionKind.RETRY_KNOWLEDGE_PREPARATION,),
        next_action="平台核验原知识准备后, 以新的执行身份继续原需求。",
        inspected_at=NOW,
        proof_sha256="0" * 64,
    )
    return proof.model_copy(update={"proof_sha256": proof.recompute_sha256()})


def _decision(proof: DeliveryWaitInvestigation) -> DeliveryResolution:
    resolution = DeliveryResolution(
        task_id=proof.task_id,
        work_item_id=proof.work_item_id,
        expected_disposition_sha256=proof.disposition_sha256,
        expected_task_intent_sha256=proof.task_intent_sha256,
        expected_source_revision=proof.source_revision,
        expected_checkpoint_sequence=proof.checkpoint_sequence,
        task_revision=proof.task_revision,
        task_snapshot_sha256=proof.task_snapshot_sha256,
        step_sha256=proof.step_sha256,
        resolution_kind=DeliveryResolutionKind.RETRY_KNOWLEDGE_PREPARATION,
        proof_sha256=proof.proof_sha256,
        operator_principal=LocalOperatorPrincipal.trusted_local(),
        submitted_at=NOW + timedelta(seconds=1),
        knowledge_preparation=proof.knowledge_preparation,
        resolution_sha256="0" * 64,
    )
    return resolution.model_copy(update={"resolution_sha256": resolution.recompute_sha256()})


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMAS / (name + ".schema.json")).read_text()))


def test_all_embedded_failure_facts_keep_the_complete_runtime_contract() -> None:
    generated = DeliveryFailureFacts.model_json_schema()
    generated.pop("$defs")
    embedded_paths = []
    for path in sorted(SCHEMAS.glob("*.schema.json")):
        document = json.loads(path.read_text())
        embedded = document.get("$defs", {}).get("DeliveryFailureFacts")
        if embedded is not None:
            embedded_paths.append(path)
            assert embedded == generated, path.name
    assert len(embedded_paths) >= 10


@pytest.mark.parametrize(
    "name",
    [
        "DeliveryResolution",
        "DeliveryResolutionKind",
        "DeliveryWaitInvestigation",
        "KnowledgePreparationRetryEvidence",
    ],
)
def test_public_operation_embeds_the_same_complete_engineering_wire_guards(name: str) -> None:
    engineering = json.loads((SCHEMAS / "engineering-wait-resolution.schema.json").read_text())
    console = json.loads((SCHEMAS / "console-operation.schema.json").read_text())
    assert console["$defs"][name] == engineering["$defs"][name]


@pytest.mark.parametrize("role", [AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER])
def test_each_delivery_role_uses_the_same_exact_frozen_work_evidence(role: AgentRole) -> None:
    proof = _proof(role)
    decision = _decision(proof)
    proof.validate_integrity()
    decision.validate_integrity()
    for record in (proof, decision):
        _validator("engineering-wait-resolution").validate(record.to_wire())
    assert decision.retry_failure is None and decision.retry_cause is None
    assert decision.knowledge_preparation is not None
    assert decision.knowledge_preparation.budget_source == "frozen_work_attempt"


@pytest.mark.parametrize("role", [AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER])
def test_native_requirement_identity_does_not_rewrite_the_original_knowledge_scope(
    role: AgentRole,
) -> None:
    original = _proof(role)
    assert original.knowledge_preparation is not None
    original_wire = original.to_wire()
    evidence = KnowledgePreparationRetryEvidence.model_validate(
        {
            **original.knowledge_preparation.to_wire(),
            "delivery_requirement_id": "delivery_multi_knowledge_schema",
        }
    )
    assert evidence.requirement_id == original.knowledge_preparation.requirement_id
    proof = original.model_copy(update={"knowledge_preparation": evidence})
    proof = proof.model_copy(update={"proof_sha256": proof.recompute_sha256()})
    decision = _decision(proof)
    for record in (proof, decision):
        record.validate_integrity()
        _validator("engineering-wait-resolution").validate(record.to_wire())
    assert proof.proof_sha256 != original.proof_sha256
    assert original.to_wire() == original_wire


def test_absent_native_requirement_identity_preserves_existing_evidence_wire() -> None:
    original = _proof()
    assert original.knowledge_preparation is not None
    restored = KnowledgePreparationRetryEvidence.model_validate(
        {**original.knowledge_preparation.to_wire(), "delivery_requirement_id": None}
    )
    assert "delivery_requirement_id" not in restored.to_wire()
    assert "delivery_requirement_id" not in restored.model_dump(mode="json")
    assert restored.to_wire() == original.knowledge_preparation.to_wire()
    nested = original.model_copy(update={"knowledge_preparation": restored})
    assert nested.recompute_sha256() == original.proof_sha256


def test_native_requirement_identity_cannot_be_empty() -> None:
    wire: dict[str, Any] = _decision(_proof()).to_wire()
    wire["knowledge_preparation"]["delivery_requirement_id"] = ""
    with pytest.raises(ValidationError):
        DeliveryResolution.model_validate(wire)
    with pytest.raises(SchemaValidationError):
        _validator("engineering-wait-resolution").validate(wire)


@pytest.mark.parametrize("field", ["knowledge_preparation", "resolution_kind"])
def test_new_resolution_cannot_omit_or_change_its_own_proof(field: str) -> None:
    wire: dict[str, Any] = _decision(_proof()).to_wire()
    if field == "knowledge_preparation":
        del wire[field]
    else:
        wire[field] = "RESUME_UNINVOKED"
    with pytest.raises(ValidationError):
        DeliveryResolution.model_validate(wire)
    with pytest.raises(SchemaValidationError):
        _validator("engineering-wait-resolution").validate(wire)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("role", "orchestrator"),
        ("budget_source", "provider_transient"),
        ("expansion_number", 3),
        ("next_timeout_seconds", 86_401),
        ("execution_record_sha256s", []),
        ("execution_record_sha256s", ["2" * 64, "2" * 64]),
    ],
)
def test_schema_rejects_non_delivery_or_unbounded_or_duplicate_retry_facts(
    field: str, value: object
) -> None:
    wire: dict[str, Any] = _decision(_proof()).to_wire()
    wire["knowledge_preparation"][field] = value
    with pytest.raises(ValidationError):
        DeliveryResolution.model_validate(wire)
    with pytest.raises(SchemaValidationError):
        _validator("engineering-wait-resolution").validate(wire)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("current_timeout_seconds", 601),
        ("next_timeout_seconds", 600),
        ("maximum_timeout_seconds", 4800),
        ("root_intent_sha256", "0" * 64),
    ],
)
def test_typed_evidence_rejects_changed_frozen_window_arithmetic(field: str, value: object) -> None:
    wire = _evidence()
    wire[field] = value
    with pytest.raises(ValidationError, match="finite doubled execution window"):
        KnowledgePreparationRetryEvidence.model_validate(wire)


@pytest.mark.parametrize("field", ["task_id", "work_item_id", "source_revision"])
def test_resolution_cannot_move_knowledge_retry_to_a_different_wait(field: str) -> None:
    wire: dict[str, Any] = _decision(_proof()).to_wire()
    wire["knowledge_preparation"][field] = "different_" + field
    with pytest.raises(ValidationError):
        DeliveryResolution.model_validate(wire)


@pytest.mark.parametrize("field", ["invocation_start_sha256", "invocation_outcome_sha256"])
def test_preparation_proof_cannot_hide_an_already_started_main_role(field: str) -> None:
    wire = _proof().to_wire()
    wire[field] = "0" * 64
    with pytest.raises(ValidationError):
        DeliveryWaitInvestigation.model_validate(wire)
    with pytest.raises(SchemaValidationError):
        _validator("engineering-wait-resolution").validate(wire)


def test_knowledge_preparation_cannot_advertise_an_uninvoked_or_checkpoint_action() -> None:
    wire = _proof().to_wire()
    wire["permitted_resolutions"] = ["RESUME_UNINVOKED"]
    with pytest.raises(ValidationError):
        DeliveryWaitInvestigation.model_validate(wire)
    with pytest.raises(SchemaValidationError):
        _validator("engineering-wait-resolution").validate(wire)


def test_new_resolution_and_investigation_validate_inside_the_public_operation() -> None:
    proof = _proof()
    decision = _decision(proof)
    queued = ConsoleOperation.queued(
        team_id="team_knowledge_schema",
        idempotency_key="knowledge-schema-retry",
        intent=HandleDeliveryWaitIntent(
            project_id="project_knowledge_schema",
            delivery_id="delivery_knowledge_schema",
            expected_checkpoint_sha256="7" * 64,
            work_item_id=proof.work_item_id,
            expected_disposition_sha256=proof.disposition_sha256,
            expected_task_intent_sha256=proof.task_intent_sha256,
            expected_source_revision=proof.source_revision,
            expected_checkpoint_sequence=proof.checkpoint_sequence,
        ),
        requested_at=NOW,
    )
    running = queued.transition(ConsoleOperationStatus.RUNNING, updated_at=NOW)
    operation = running.transition(
        ConsoleOperationStatus.SUCCEEDED,
        updated_at=NOW + timedelta(seconds=2),
        result=ConsoleCommandResult(
            project_id="project_knowledge_schema",
            delivery_id="delivery_knowledge_schema",
            checkpoint_sha256="7" * 64,
            stage="DELIVERING",
            next_action="以新的执行身份继续原需求。",
            engineering_wait_investigation=proof,
            engineering_wait_resolution=decision,
        ),
    )
    operation.validate_integrity()
    _validator("console-operation").validate(operation.to_wire())
    unsafe: dict[str, Any] = deepcopy(operation.to_wire())
    del unsafe["result"]["engineering_wait_resolution"]["knowledge_preparation"]
    with pytest.raises(ValidationError):
        ConsoleOperation.model_validate(unsafe)
    with pytest.raises(SchemaValidationError):
        _validator("console-operation").validate(unsafe)


def test_legacy_proof_and_decision_omit_the_new_optional_field_from_nested_wire() -> None:
    # Historical RESUME_UNINVOKED records did not carry a knowledge model call.
    proof = _proof()
    wire: dict[str, Any] = proof.to_wire()
    old_facts = DeliveryFailureFacts.model_validate(
        {
            **wire["disposition"]["facts"],
            "classification": "EXECUTION_UNCERTAIN",
            "evidence_ids": [],
        }
    )
    old_disposition = decide_delivery_disposition(old_facts)
    wire["disposition"] = old_disposition.to_wire()
    wire["disposition_sha256"] = old_disposition.disposition_sha256
    del wire["knowledge_preparation"]
    wire["original_run_id"] = None
    wire["permitted_resolutions"] = ["RESUME_UNINVOKED"]
    legacy = DeliveryWaitInvestigation.model_validate(wire)
    legacy = legacy.model_copy(update={"proof_sha256": legacy.recompute_sha256()})
    assert "knowledge_preparation" not in legacy.to_wire()
    assert "knowledge_preparation" not in legacy.model_dump(mode="json")
    assert legacy.proof_sha256 == digest(
        {key: value for key, value in legacy.to_wire().items() if key != "proof_sha256"}
    )
    decision_wire = _decision(proof).to_wire()
    del decision_wire["knowledge_preparation"]
    decision_wire.update(
        resolution_kind="RESUME_UNINVOKED",
        expected_disposition_sha256=legacy.disposition_sha256,
        proof_sha256=legacy.proof_sha256,
    )
    decision = DeliveryResolution.model_validate(decision_wire)
    decision = decision.model_copy(update={"resolution_sha256": decision.recompute_sha256()})
    decision.validate_integrity()
    assert "knowledge_preparation" not in decision.model_dump(mode="json")
    nested = DeliveryWaitHandling(
        task_id=legacy.task_id,
        work_item_id=legacy.work_item_id,
        disposition_sha256=legacy.disposition_sha256,
        task_intent_sha256=legacy.task_intent_sha256,
        source_revision=legacy.source_revision,
        checkpoint_sequence=legacy.checkpoint_sequence,
        investigation=legacy,
        status="NEEDS_AUTHORIZATION",
        summary="需要工程负责人记录精确决定。",
        user_action="核对已保存的原调查证明。",
        recheck_when="事实未改变时无需重复调查。",
        manual_resolution_allowed=True,
        handled_at=NOW,
        handling_sha256="0" * 64,
    )
    nested = nested.model_copy(update={"handling_sha256": nested.recompute_sha256()})
    restored = DeliveryWaitHandling.model_validate(nested.to_wire())
    restored.validate_integrity()
    assert "knowledge_preparation" not in restored.model_dump(mode="json")["investigation"]
    assert restored.handling_sha256 == nested.handling_sha256
    # Captured with the pre-change classes from HEAD; includes optional nulls and
    # nested records, as used by historical record identities outside to_wire().
    assert digest(legacy.model_dump(mode="json")) == (
        "d31db790f34e2120de0f5e33ea7650219382cedcf244e80654bc8749255316b7"
    )
    assert digest(decision.model_dump(mode="json")) == (
        "d2260bb5e7af50cd260a0f7dbda84496c5a6e9e8c4d6889e67f554ddeb64fb34"
    )
    assert digest(restored.model_dump(mode="json")) == (
        "d1ef1f1c0ed29631be95f1038673734684aaa08fb0f2002466175347b0d31d3e"
    )
