"""Exact capacity plans preserve legacy hashes and reject incompatible reservations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_software_engineer.manager.baseline_models import (
    BaselineExecutionFacts,
    BaselineExecutionReservation,
)
from ai_software_engineer.manager.baseline_production import BaselineInvocationProof
from tests.manager.test_execution_baseline import setup

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def facts(tmp_path: Path) -> BaselineExecutionFacts:
    return setup(tmp_path).collector.facts


def capacity_facts(facts: BaselineExecutionFacts) -> BaselineExecutionFacts:
    return BaselineExecutionFacts.model_validate(
        {
            **facts.to_wire(),
            "context_capacity_receipt_sha256": "e" * 64,
            "continuation": BaselineExecutionReservation(
                current_attempt=facts.task.attempts,
                next_execution_attempt=facts.task.attempts,
                retry_cause="uninvoked",
                reservation_already_applied=True,
            ).to_wire(),
        }
    )


def test_absent_capacity_fields_preserve_old_facts_and_proof_serialization(
    facts: BaselineExecutionFacts,
) -> None:
    facts.validate_integrity()
    assert "context_capacity_receipt_sha256" not in facts.to_wire()
    proof = BaselineInvocationProof(
        work_item_id=facts.work_item_id,
        step_sha256="a" * 64,
        start_sha256=None,
        outcome_sha256=None,
        interruption_receipt_sha256=None,
        proof_kind="unclaimed",
    )
    assert "context_capacity_receipt_sha256s" not in proof.to_wire()


@pytest.mark.parametrize(
    "name",
    ["console-operation", "execution-baseline-plan", "execution-baseline-queue-consumption"],
)
def test_every_capacity_facts_schema_requires_the_unchanged_uninvoked_reservation(
    facts: BaselineExecutionFacts, name: str
) -> None:
    document = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
    schema = {**document["$defs"]["BaselineExecutionFacts"], "$defs": document["$defs"]}
    validator = Draft202012Validator(schema)
    capacity = capacity_facts(facts)
    assert capacity.continuation is not None
    reservation = capacity.continuation.to_wire()
    valid = capacity.to_wire()
    validator.validate(valid)
    validator.validate(facts.to_wire())
    assert "context_capacity_receipt_sha256" not in schema.get("required", [])
    for invalid in (
        {**valid, "continuation": None},
        {
            **valid,
            "continuation": {**reservation, "reservation_already_applied": False},
        },
        {
            **valid,
            "continuation": {**reservation, "retry_cause": "local_execution_limit"},
        },
        {**valid, "completed_output": {}},
        {**valid, "legacy_containment": {}},
        {**valid, "stopped_provider_failure": {}},
    ):
        assert list(validator.iter_errors(invalid))
        with pytest.raises(ValidationError):
            BaselineExecutionFacts.model_validate(invalid)


def test_capacity_facts_cannot_advance_attempt_without_a_model_invocation(
    facts: BaselineExecutionFacts,
) -> None:
    capacity = capacity_facts(facts)
    assert capacity.continuation is not None
    reservation = capacity.continuation.to_wire()
    valid = capacity.to_wire()
    with pytest.raises(ValidationError, match="容量恢复"):
        BaselineExecutionFacts.model_validate(
            {
                **valid,
                "continuation": {
                    **reservation,
                    "current_attempt": facts.task.attempts + 1,
                    "next_execution_attempt": facts.task.attempts + 1,
                },
            }
        )


@pytest.mark.parametrize("field", ["start_sha256", "outcome_sha256", "interruption_receipt_sha256"])
def test_capacity_quiescence_proof_cannot_invent_invocation_or_stop(field: str) -> None:
    value = {
        "work_item_id": "work_exact_capacity",
        "step_sha256": "a" * 64,
        "start_sha256": None,
        "outcome_sha256": None,
        "interruption_receipt_sha256": None,
        "context_capacity_receipt_sha256s": ["c" * 64],
        "proof_kind": "claimed_context_capacity",
    }
    BaselineInvocationProof.model_validate(value)
    with pytest.raises(ValidationError, match="不能冒充"):
        BaselineInvocationProof.model_validate({**value, field: "b" * 64})
    with pytest.raises(ValidationError, match="不能冒充"):
        BaselineInvocationProof.model_validate({**value, "context_capacity_receipt_sha256s": []})
