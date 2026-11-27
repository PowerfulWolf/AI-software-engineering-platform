"""Pydantic and published JSON Schema agree on exact engineering proof boundaries."""

import json
import os
import subprocess
import sys
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from shutil import copy2, copytree
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.delivery_disposition import decide_delivery_disposition
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryWaitInvestigation,
)
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.web_console.models import (
    ConsoleOperation,
    ExecuteExecutionBaselineIntent,
    ProposeExecutionBaselineIntent,
)
from tests.domain.factories import NOW, make_task
from tests.team_view.test_engineering_history import _proof

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


def _wire(kind: str) -> dict[str, Any]:
    value: dict[str, Any] = {
        "task_id": "task_schema",
        "work_item_id": "work_schema",
        "expected_disposition_sha256": "a" * 64,
        "expected_task_intent_sha256": "b" * 64,
        "expected_source_revision": "c" * 40,
        "expected_checkpoint_sequence": 4,
        "task_revision": 4,
        "task_snapshot_sha256": "d" * 64,
        "step_sha256": "e" * 64,
        "resolution_kind": kind,
        "proof_sha256": "f" * 64,
        "operator_principal": LocalOperatorPrincipal.trusted_local().to_wire(),
        "submitted_at": (NOW + timedelta(seconds=1)).isoformat(),
        "resolution_sha256": "0" * 64,
    }
    if kind == "REVERIFY_CANDIDATE":
        value["verification_retry"] = {
            "candidate_revision": "c" * 40,
            "previous_qa_artifact_id": "art_qa_schema",
            "previous_qa_sha256": "a" * 64,
            "previous_run_id": "run_schema",
            "previous_context_manifest_id": "ctx_" + "b" * 64,
            "invocation_outcome_sha256": "d" * 64,
            "prerequisite_facts_sha256": "e" * 64,
            "budget_source": "frozen_work_attempt",
        }
    elif kind == "RETRY_VERIFIER_PREPARATION":
        value["verifier_preparation"] = {
            "candidate_revision": "c" * 40,
            "preparation_checkpoint_sha256": "a" * 64,
            "previous_run_id": "run_schema",
            "previous_context_manifest_id": "ctx_" + "b" * 64,
            "request_sha256": "d" * 64,
            "native_execution_state": "FINISHED",
            "native_binding_plan_sha256": "e" * 64,
            "native_started_sha256": "f" * 64,
            "native_finished_sha256": "a" * 64,
            "native_failure_code": "COMMAND_TIMEOUT",
            "prerequisite_facts_sha256": "b" * 64,
            "budget_source": "frozen_work_attempt",
        }
    return dict(DeliveryResolution.model_validate(value).to_wire())


@pytest.mark.parametrize("kind", ["REVERIFY_CANDIDATE", "RETRY_VERIFIER_PREPARATION"])
def test_verification_retry_requires_its_exact_own_proof_in_both_wire_contracts(kind: str) -> None:
    validator = Draft202012Validator(
        json.loads(
            (SCHEMAS / "engineering-wait-resolution.schema.json").read_text(),
        )
    )
    wire = _wire(kind)
    record = DeliveryResolution.model_validate(wire)
    validator.validate(record.to_wire())
    field = "verification_retry" if kind == "REVERIFY_CANDIDATE" else "verifier_preparation"
    for replacement in (None, "missing"):
        changed = dict(wire)
        if replacement is None:
            changed[field] = None
        else:
            del changed[field]
        with pytest.raises(ValidationError):
            DeliveryResolution.model_validate(changed)
        with pytest.raises(SchemaValidationError):
            validator.validate(changed)


@pytest.mark.parametrize("field", ["verification_retry", "verifier_preparation"])
def test_another_resolution_cannot_acquire_verification_proof(field: str) -> None:
    wire = _wire("RESUME_UNINVOKED")
    source = _wire(
        "REVERIFY_CANDIDATE" if field == "verification_retry" else "RETRY_VERIFIER_PREPARATION"
    )
    wire[field] = source[field]
    validator = Draft202012Validator(
        json.loads(
            (SCHEMAS / "engineering-wait-resolution.schema.json").read_text(),
        )
    )
    with pytest.raises(ValidationError):
        DeliveryResolution.model_validate(wire)
    with pytest.raises(SchemaValidationError):
        validator.validate(wire)


def test_finished_preparation_cannot_reuse_unused_attempt_or_fabricate_provider_failure() -> None:
    wire = _wire("RETRY_VERIFIER_PREPARATION")
    validator = Draft202012Validator(
        json.loads(
            (SCHEMAS / "engineering-wait-resolution.schema.json").read_text(),
        )
    )
    wire["verifier_preparation"]["budget_source"] = None
    with pytest.raises(ValidationError):
        DeliveryResolution.model_validate(wire)
    with pytest.raises(SchemaValidationError):
        validator.validate(wire)


def test_finished_success_before_model_start_has_no_fabricated_failure_code() -> None:
    wire = _wire("RETRY_VERIFIER_PREPARATION")
    del wire["verifier_preparation"]["native_failure_code"]
    record = DeliveryResolution.model_validate(wire)
    assert record.verifier_preparation is not None
    assert record.verifier_preparation.native_failure_code is None
    assert record.retry_failure is None
    Draft202012Validator(
        json.loads(
            (SCHEMAS / "engineering-wait-resolution.schema.json").read_text(),
        )
    ).validate(record.to_wire())


def test_public_baseline_operation_schema_and_historical_operation_hashes_remain_readable() -> None:
    validator = Draft202012Validator(
        json.loads((SCHEMAS / "console-operation.schema.json").read_text())
    )
    intents: tuple[ProposeExecutionBaselineIntent | ExecuteExecutionBaselineIntent, ...] = (
        ProposeExecutionBaselineIntent(
            project_id="project_schema",
            delivery_id="delivery_schema",
            task_id="task_schema",
            expected_checkpoint_sha256="a" * 64,
            expected_task_intent_sha256="b" * 64,
            expected_task_revision=4,
            expected_work_item_id="work_schema",
            expected_source_revision="c" * 40,
            target_base_ref="d" * 40,
        ),
        ExecuteExecutionBaselineIntent(
            project_id="project_schema",
            delivery_id="delivery_schema",
            task_id="task_schema",
            expected_checkpoint_sha256="a" * 64,
            expected_plan_sha256="b" * 64,
            reference="工程负责人批准精确计划",
        ),
    )
    for index, intent in enumerate(intents):
        operation = ConsoleOperation.queued(
            team_id="team_schema",
            idempotency_key=f"baseline-schema-{index}",
            intent=intent,
            requested_at=NOW,
        )
        validator.validate(operation.to_wire())
        restored = ConsoleOperation.model_validate(operation.to_wire())
        restored.validate_integrity()
        assert restored.operation_sha256 == operation.operation_sha256

    # Optional proof additions are absent from old wire and cannot change its hash.
    legacy = DeliveryResolution.model_validate(_wire("RESUME_UNINVOKED"))
    legacy = legacy.model_copy(update={"resolution_sha256": legacy.recompute_sha256()})
    wire = legacy.to_wire()
    assert "verification_retry" not in wire and "verifier_preparation" not in wire
    assert legacy.resolution_sha256 == digest(
        {key: value for key, value in wire.items() if key != "resolution_sha256"}
    )
    DeliveryResolution.model_validate(wire).validate_integrity()


def test_rejected_outcome_missing_fact_and_no_replay_match_published_schema() -> None:
    original = _proof(make_task())
    rejected = decide_delivery_disposition(
        original.disposition.facts.model_copy(update={"classification": "INVALID_OUTPUT"})
    )
    wire = {
        **original.to_wire(),
        "disposition": rejected.to_wire(),
        "disposition_sha256": rejected.disposition_sha256,
        "permitted_resolutions": [],
        "missing": ["OUTCOME_REJECTED"],
    }
    validator = Draft202012Validator(
        json.loads((SCHEMAS / "engineering-wait-resolution.schema.json").read_text())
    )
    record = DeliveryWaitInvestigation.model_validate(wire)
    validator.validate(record.to_wire())
    for missing in ([], ["OUTCOME_REJECTED"]):
        unsafe = {**wire, "missing": missing, "permitted_resolutions": ["REPLAY_RECORDED_RESULT"]}
        with pytest.raises(ValidationError, match="cannot authorize"):
            DeliveryWaitInvestigation.model_validate(unsafe)
        with pytest.raises(SchemaValidationError):
            validator.validate(unsafe)


def capacity_resolution_wire() -> dict[str, Any]:
    """A capacity stop retains its exact unused model reservation, even after native tests."""
    wire = _wire("RETRY_VERIFIER_PREPARATION")
    wire["resolution_kind"] = "RESUME_UNINVOKED"
    proof = wire["verifier_preparation"]
    proof.pop("native_failure_code", None)
    proof.pop("budget_source", None)
    proof["context_capacity_receipt_sha256"] = "a" * 64
    proof["context_capacity_claim_sha256"] = "b" * 64
    return dict(DeliveryResolution.model_validate(wire).to_wire())


def capacity_investigation_wire() -> dict[str, Any]:
    task = make_task().model_copy(update={"base_ref": "c" * 40})
    original = _proof(task)
    evidence = capacity_resolution_wire()["verifier_preparation"]
    disposition = decide_delivery_disposition(
        original.disposition.facts.model_copy(
            update={
                "role": AgentRole.QA,
                "classification": "CONTEXT_CAPACITY",
                "evidence_ids": (
                    "context-capacity://" + evidence["context_capacity_receipt_sha256"],
                ),
            }
        )
    )
    wire = {
        **original.to_wire(),
        "disposition": disposition.to_wire(),
        "disposition_sha256": disposition.disposition_sha256,
        "original_run_id": evidence["previous_run_id"],
        "prerequisite_facts_sha256": evidence["prerequisite_facts_sha256"],
        "retry_cause": None,
        "verifier_preparation": evidence,
        "permitted_resolutions": ["RESUME_UNINVOKED"],
    }
    return dict(DeliveryWaitInvestigation.model_validate(wire).to_wire())


@pytest.mark.parametrize(
    "schema_name",
    [
        "engineering-wait-resolution",
        "console-operation",
        "stopped-failure-budget-settlement",
    ],
)
def test_capacity_proof_full_shape_and_guard_agree_in_all_embedded_schemas(
    schema_name: str,
) -> None:
    schema = json.loads((SCHEMAS / f"{schema_name}.schema.json").read_text())
    for model, wire in (
        ("VerifierPreparationEvidence", capacity_resolution_wire()["verifier_preparation"]),
        ("DeliveryWaitInvestigation", capacity_investigation_wire()),
    ):
        validator = Draft202012Validator({"$defs": schema["$defs"], "$ref": f"#/$defs/{model}"})
        validator.validate(wire)
        evidence = wire if model == "VerifierPreparationEvidence" else wire["verifier_preparation"]
        for field, value in (
            ("context_capacity_claim_sha256", None),
            ("context_capacity_receipt_sha256", None),
            ("native_execution_state", "UNCERTAIN"),
            ("budget_source", "frozen_work_attempt"),
            ("native_failure_code", "COMMAND_TIMEOUT"),
            ("native_finished_sha256", None),
        ):
            changed = json.loads(json.dumps(wire))
            target = (
                changed
                if model == "VerifierPreparationEvidence"
                else changed["verifier_preparation"]
            )
            target[field] = value
            assert not validator.is_valid(changed), (schema_name, model, field)
        assert evidence["native_execution_state"] == "FINISHED"


def test_capacity_resolution_rejects_retry_and_mixed_invocation_proof() -> None:
    value: Any
    validator = Draft202012Validator(
        json.loads((SCHEMAS / "engineering-wait-resolution.schema.json").read_text())
    )
    wire = capacity_resolution_wire()
    validator.validate(wire)
    for field, value in (
        ("resolution_kind", "RETRY_VERIFIER_PREPARATION"),
        ("retry_cause", "provider_transient"),
    ):
        unsafe = {**wire, field: value}
        with pytest.raises(ValidationError):
            DeliveryResolution.model_validate(unsafe)
        with pytest.raises(SchemaValidationError):
            validator.validate(unsafe)
    wire = capacity_investigation_wire()
    validator.validate(wire)
    for field, value in (
        ("invocation_start_sha256", "c" * 64),
        ("invocation_outcome_sha256", "d" * 64),
        ("process_stop_sha256", "e" * 64),
        ("retry_cause", "local_execution_limit"),
        ("permitted_resolutions", ["RETRY_VERIFIER_PREPARATION"]),
    ):
        unsafe = {**wire, field: value}
        with pytest.raises(ValidationError):
            DeliveryWaitInvestigation.model_validate(unsafe)
        with pytest.raises(SchemaValidationError):
            validator.validate(unsafe)
    for field, value in (
        ("role", "coder"),
        ("classification", "ENVIRONMENT_UNAVAILABLE"),
        ("evidence_ids", ["verifier-preparation://" + "a" * 64]),
    ):
        unsafe = json.loads(json.dumps(wire))
        unsafe["disposition"]["facts"][field] = value
        with pytest.raises(ValidationError):
            DeliveryWaitInvestigation.model_validate(unsafe)
        with pytest.raises(SchemaValidationError):
            validator.validate(unsafe)


def test_legacy_verifier_evidence_omits_capacity_fields_and_keeps_digest() -> None:
    wire = _wire("RETRY_VERIFIER_PREPARATION")
    evidence = wire["verifier_preparation"]
    assert "context_capacity_receipt_sha256" not in evidence
    assert "context_capacity_claim_sha256" not in evidence
    record = DeliveryResolution.model_validate(wire)
    assert record.to_wire() == wire
    assert record.recompute_sha256() == digest(
        {key: value for key, value in wire.items() if key != "resolution_sha256"}
    )


VERIFIER_SCHEMAS = (
    "engineering-wait-resolution.schema.json",
    "console-operation.schema.json",
    "console-deletion-cleanup.schema.json",
)


def _verifier_decision(role: str = "qa") -> dict[str, Any]:
    wire = _wire("RESUME_UNINVOKED")
    wire["resolution_kind"] = "RETRY_REJECTED_VERIFIER_OUTPUT"
    evidence: dict[str, Any] = {
        "task_id": "task_schema",
        "work_item_id": "work_schema",
        "role": role,
        "candidate_revision": "c" * 40,
        "plan_artifact_id": "art_plan_schema",
        "plan_artifact_sha256": "a" * 64,
        "implementation_artifact_id": "art_impl_schema",
        "implementation_artifact_sha256": "b" * 64,
        "original_lease_id": "lease_schema",
        "original_claim_sha256": "c" * 64,
        "original_attempt": 2,
        "original_dispatch_sequence": 1,
        "checkpoint_sequence": 4,
        "previous_run_id": "run_schema",
        "previous_context_manifest_id": "ctx_" + "d" * 64,
        "invocation_start_sha256": "e" * 64,
        "invocation_outcome_sha256": "f" * 64,
        "execution_stop_sha256": "0" * 64,
    }
    if role == "reviewer":
        evidence["accepted_qa_artifact_id"] = "art_qa_schema"
        evidence["accepted_qa_artifact_sha256"] = "1" * 64
    wire["rejected_verifier_output"] = evidence
    return dict(DeliveryResolution.model_validate(wire).to_wire())


def _resolution_validator(filename: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS / filename).read_text(encoding="utf-8"))
    return Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": schema["$defs"],
            "$ref": "#/$defs/DeliveryResolution",
        }
    )


@pytest.mark.parametrize("filename", VERIFIER_SCHEMAS)
@pytest.mark.parametrize("role", ("qa", "reviewer"))
@pytest.mark.parametrize(
    "mutation",
    (
        "none",
        "missing_evidence",
        "other_kind",
        "policy",
        "role_inputs",
        "retry_cause",
        "wrong_error",
    ),
)
def test_verifier_rerun_resolution_model_and_schema_agree(
    filename: str, role: str, mutation: str
) -> None:
    validator = _resolution_validator(filename)
    wire = _verifier_decision(role)
    validator.validate(wire)
    DeliveryResolution.model_validate(wire)
    if mutation == "none":
        return
    changed = deepcopy(wire)
    evidence = changed["rejected_verifier_output"]
    if mutation == "missing_evidence":
        changed.pop("rejected_verifier_output")
    elif mutation == "other_kind":
        changed["resolution_kind"] = "RETRY_REJECTED_CODER_OUTPUT"
    elif mutation == "policy":
        changed["authorization_source"] = "organization_engineering_policy"
    elif mutation == "role_inputs":
        if role == "qa":
            evidence["accepted_qa_artifact_id"] = "art_qa_schema"
            evidence["accepted_qa_artifact_sha256"] = "1" * 64
        else:
            evidence.pop("accepted_qa_artifact_id")
            evidence.pop("accepted_qa_artifact_sha256")
    elif mutation == "retry_cause":
        changed["retry_cause"] = "provider_transient"
    else:
        evidence["error_code"] = "POLICY_VIOLATION"
    with pytest.raises(ValidationError):
        DeliveryResolution.model_validate(changed)
    with pytest.raises(SchemaValidationError):
        validator.validate(changed)


def test_verifier_rerun_rejects_coder_role() -> None:
    wire = _verifier_decision()
    wire["rejected_verifier_output"]["role"] = "coder"
    with pytest.raises(ValidationError):
        DeliveryResolution.model_validate(wire)
    with pytest.raises(SchemaValidationError):
        _resolution_validator(VERIFIER_SCHEMAS[0]).validate(wire)


def test_engineering_wait_resolution_schema_parity(tmp_path: Path) -> None:
    """Regeneration reproduces the published bytes and a second run is byte-stable."""
    root = tmp_path / "regeneration"
    copytree(SCHEMAS, root / "schemas")
    (root / "scripts").mkdir()
    for name in (
        "sync-engineering-authority-schemas.py",
        "sync-contained-unknown-contracts.py",
    ):
        copy2(SCHEMAS.parent / "scripts" / name, root / "scripts" / name)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(SCHEMAS.parent / "src")
    published = {path.name: path.read_bytes() for path in SCHEMAS.glob("*.schema.json")}
    for _ in range(2):
        subprocess.run(
            (
                sys.executable,
                str(root / "scripts/sync-engineering-authority-schemas.py"),
                "--wait-only",
            ),
            check=True,
            env=environment,
        )
        regenerated = {
            path.name: path.read_bytes() for path in (root / "schemas").glob("*.schema.json")
        }
        assert regenerated == published
    for filename in (
        *VERIFIER_SCHEMAS,
        "stopped-failure-budget-settlement.schema.json",
        "stopped-unknown-budget-settlement.schema.json",
    ):
        definitions = json.loads(published[filename])["$defs"]
        assert "RETRY_REJECTED_VERIFIER_OUTPUT" in definitions["DeliveryResolutionKind"]["enum"]
        assert "RejectedVerifierOutputEvidence" in definitions
        guards = json.dumps(definitions["DeliveryWaitInvestigation"]["allOf"])
        assert "RETRY_REJECTED_VERIFIER_OUTPUT" in guards


@pytest.mark.parametrize(
    "kind", ("RESUME_UNINVOKED", "REVERIFY_CANDIDATE", "RETRY_VERIFIER_PREPARATION")
)
def test_existing_recovery_paths_unchanged(kind: str) -> None:
    """Old decisions omit the new field, keep their digest and cannot borrow the new proof."""
    wire = _wire(kind)
    assert "rejected_verifier_output" not in wire
    record = DeliveryResolution.model_validate(wire)
    assert record.to_wire() == wire
    assert record.recompute_sha256() == digest(
        {key: value for key, value in wire.items() if key != "resolution_sha256"}
    )
    for filename in VERIFIER_SCHEMAS:
        validator = _resolution_validator(filename)
        validator.validate(wire)
        borrowed = {
            **wire,
            "rejected_verifier_output": _verifier_decision()["rejected_verifier_output"],
        }
        with pytest.raises(SchemaValidationError):
            validator.validate(borrowed)
    with pytest.raises(ValidationError):
        DeliveryResolution.model_validate(
            {
                **wire,
                "rejected_verifier_output": _verifier_decision()["rejected_verifier_output"],
            }
        )
    legacy = _proof(make_task())
    assert "rejected_verifier_output" not in legacy.to_wire()
    DeliveryWaitInvestigation.model_validate(legacy.to_wire()).validate_integrity()
