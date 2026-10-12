"""A final-input overflow is a claimed preparation fact, never an invocation."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ai_software_engineer.agents.model_input import FinalModelInputCapacityExceeded
from ai_software_engineer.context import ContextBudget, ContextBundle
from ai_software_engineer.context.models import ContextSection
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.manager.context_capacity import ContextCapacityReceipt
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
    DurableInvocationControl,
)
from ai_software_engineer.work_queue.ports import QueueConflict
from tests.domain.factories import NOW
from tests.manager.test_native_verification import _fixture
from tests.manager.test_verifier_preparation import _gate, _Wait


def test_final_capacity_failure_seals_exact_claim_before_wait_without_a_model_start(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    context = ContextBundle(
        context_id=fixture.request.context_manifest_id,
        task_id=fixture.task.id,
        role=fixture.request.role,
        attempt=fixture.request.attempt,
        source_revision=fixture.request.source_revision,
        sections=(
            ContextSection(
                name="policy",
                uri="policy://test",
                content="x",
                sha256="2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881",
                tokens=1,
                priority=1,
            ),
        ),
        budget=ContextBudget(max_input_tokens=10, reserved_output_tokens=1, used_input_tokens=1),
        built_at=NOW,
    )
    gate, _, failure, records = _gate(fixture, tmp_path)
    delegate = DurableInvocationControl(records, gate.guard)
    gate.delegate = delegate
    gate.prepare_verifier = gate.observe_verifier = None
    gate.context_reader = lambda _: context

    def overflow(_: object) -> None:
        raise FinalModelInputCapacityExceeded(estimated_input_tokens=11, max_input_tokens=10)

    gate.prepare_input = overflow
    with pytest.raises(_Wait):
        gate.prepare(fixture.request)
    (receipt,) = records.list("context-capacity-receipts", ContextCapacityReceipt)
    receipt.validate_integrity()
    assert receipt.origin == "final_input" and receipt.provider_started is False
    assert receipt.request == fixture.request
    assert receipt.claim_sha256 == digest(fixture.claim.to_wire())
    assert receipt.task_sha256 == digest(fixture.task.to_wire())
    assert receipt.task_intent_sha256 == task_intent_sha256(fixture.task)
    assert receipt.context_sha256 == digest(context.to_wire())
    assert receipt.final_input_tokens == 11 and receipt.max_input_tokens == 10
    assert len(failure.events) == 1
    assert failure.events[0].classification == "CONTEXT_CAPACITY"
    assert failure.events[0].artifact_ids == ("context-capacity://" + receipt.receipt_sha256,)
    assert not records.list("invocation-starts", DeliveryInvocationStart)
    assert not records.list("invocation-outcomes", DeliveryInvocationOutcome)
    wire = receipt.to_wire()
    assert "legacy_terminal_event_sha256" not in wire
    assert "legacy_terminal_source_revision" not in wire
    assert ContextCapacityReceipt.model_validate(wire) == receipt
    validator = Draft202012Validator(
        json.loads(
            (Path(__file__).parents[2] / "schemas/context-capacity-receipt.schema.json").read_text()
        )
    )
    validator.validate(wire)
    legacy_fields = {
        "legacy_terminal_event_sha256": "f" * 64,
        "legacy_terminal_source_revision": "a" * 40,
    }
    with pytest.raises(ValueError, match="cannot carry legacy"):
        ContextCapacityReceipt.model_validate({**wire, **legacy_fields})
    assert list(validator.iter_errors({**wire, **legacy_fields}))
    with pytest.raises(ValueError):
        ContextCapacityReceipt.model_validate({**wire, "provider_started": True})
    changed = receipt.model_copy(update={"final_input_tokens": 12})
    with pytest.raises(ValueError):
        changed.validate_integrity()


@pytest.mark.parametrize("change", ["context", "claim", "already_started", "store_failure"])
def test_capacity_failure_does_not_publish_wait_when_its_exact_facts_cannot_be_sealed(
    tmp_path: Path, change: str
) -> None:
    fixture = _fixture(tmp_path)
    gate, _delegate, failure, records = _gate(fixture, tmp_path)
    real_delegate = DurableInvocationControl(records, gate.guard)
    gate.delegate = real_delegate
    gate.prepare_verifier = gate.observe_verifier = None
    # The wrong context identity is refused before any durable wait publication.
    context = ContextBundle(
        context_id=fixture.request.context_manifest_id,
        task_id=fixture.task.id,
        role=fixture.request.role,
        attempt=fixture.request.attempt,
        source_revision=fixture.request.source_revision,
        sections=(
            ContextSection(
                name="policy",
                uri="policy://test",
                content="x",
                sha256="2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881",
                tokens=1,
                priority=1,
            ),
        ),
        budget=ContextBudget(max_input_tokens=10, reserved_output_tokens=1, used_input_tokens=1),
        built_at=NOW,
    )
    gate.context_reader = lambda _: context

    def overflow(_: object) -> None:
        raise FinalModelInputCapacityExceeded(estimated_input_tokens=11, max_input_tokens=10)

    gate.prepare_input = overflow
    if change == "context":
        context = context.model_copy(update={"source_revision": "f" * 40})
    elif change == "claim":
        assert fixture.guard.lease is not None
        fixture.guard.lease.claim = fixture.claim.model_copy(
            update={"work_item": fixture.claim.work_item.model_copy(update={"attempt": 99})}
        )
    elif change == "already_started":
        # A concurrent journal change is checked again under the write fence.
        calls = 0

        def started(_: object) -> bool:
            nonlocal calls
            calls += 1
            return calls > 1

        real_delegate.has_started = started  # type: ignore[method-assign, assignment]
    else:

        def broken_put(*_: object) -> None:
            raise OSError("private store failure")

        records.put = broken_put  # type: ignore[method-assign, assignment]
    with pytest.raises(OSError if change == "store_failure" else QueueConflict):
        gate.prepare(fixture.request)
    assert not failure.events
    assert not records.list("context-capacity-receipts", ContextCapacityReceipt)


def test_legacy_capacity_receipt_never_claims_a_missing_original_request(tmp_path: Path) -> None:
    # Reuse real claim identity while explicitly recording a later observation.
    fixture = _fixture(tmp_path)
    receipt = ContextCapacityReceipt(
        origin="legacy_terminal_context",
        task_id=fixture.task.id,
        task_sha256=digest(fixture.task.to_wire()),
        task_intent_sha256=task_intent_sha256(fixture.task),
        task_revision=2,
        work_item_id=fixture.claim.work_item.id,
        lease_id=fixture.claim.lease.id,
        assignment_id=fixture.claim.assignment.id,
        claim_sha256=digest(fixture.claim.to_wire()),
        dispatch_sequence=fixture.claim.work_item.dispatch_sequence,
        checkpoint_sequence=fixture.claim.work_item.checkpoint_sequence,
        role=fixture.request.role,
        attempt=fixture.request.attempt,
        source_revision=fixture.request.source_revision,
        context_manifest_id=fixture.request.context_manifest_id,
        context_sha256="a" * 64,
        max_input_tokens=256000,
        context_input_tokens=255325,
        observed_at=NOW,
        receipt_sha256="0" * 64,
    )
    receipt = receipt.model_copy(
        update={
            "receipt_sha256": digest(receipt.model_dump(mode="json", exclude={"receipt_sha256"}))
        }
    )
    receipt.validate_integrity()
    validator = Draft202012Validator(
        json.loads(
            (Path(__file__).parents[2] / "schemas/context-capacity-receipt.schema.json").read_text()
        )
    )
    validator.validate(receipt.to_wire())
    assert "legacy_terminal_event_sha256" not in receipt.to_wire()
    observed = ContextCapacityReceipt.model_validate(
        {
            **receipt.to_wire(),
            "legacy_terminal_event_sha256": "e" * 64,
            "legacy_terminal_source_revision": "f" * 40,
        }
    )
    observed = observed.model_copy(
        update={
            "receipt_sha256": digest(observed.model_dump(mode="json", exclude={"receipt_sha256"}))
        }
    )
    observed.validate_integrity()
    validator.validate(observed.to_wire())
    for field in ("legacy_terminal_event_sha256", "legacy_terminal_source_revision"):
        for remove in (True, False):
            wire = observed.to_wire()
            if remove:
                del wire[field]
            else:
                wire[field] = None
            with pytest.raises(ValueError, match="appear together"):
                ContextCapacityReceipt.model_validate(wire)
            assert list(validator.iter_errors(wire))
    for field in ({"request": fixture.request.to_wire()}, {"final_input_tokens": 281125}):
        with pytest.raises(ValueError, match="cannot invent"):
            ContextCapacityReceipt.model_validate({**receipt.to_wire(), **field})
