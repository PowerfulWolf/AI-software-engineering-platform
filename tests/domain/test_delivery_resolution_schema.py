"""Pydantic and published JSON Schema agree on exact engineering proof boundaries."""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

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
