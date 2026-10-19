"""Inherited patch lineage requires real original queue facts, never lease state guesses."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.recovery.inherited_queue import (
    _original_claim,
    require_inherited_invocation_queue,
)
from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from tests.recovery.test_preparation_inspection_scope import preparation_fixture, seed_fixture


@pytest.mark.parametrize(
    "change",
    [
        None,
        "admission",
        "step",
        "allocation",
        "source",
        "lease",
        "attempt",
        "sequence",
        "repository",
        "baseline",
    ],
)
def test_original_queue_identity_and_boundary_are_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str | None
) -> None:
    fixture = preparation_fixture(tmp_path, monkeypatch)
    seed, _, request = seed_fixture(fixture)
    assert seed.guard is not None and seed.guard.lease is not None
    queue, claim = seed.guard.lease.queue, seed.guard.lease.claim
    start = seed.invocations.get("invocation-starts", claim.work_item.id, DeliveryInvocationStart)
    admission = queue.admission(request.task_id)
    assert admission is not None
    step = queue.step_for_invocation(claim.work_item.id, None)
    if change == "admission":
        admission = admission.model_copy(update={"allocation_sha256": "f" * 64})
    if change == "allocation":
        step = step.model_copy(update={"allocation_sha256": "f" * 64})
    if change == "source":
        step = step.model_copy(
            update={
                "boundary": step.boundary.__class__(
                    request.task_id,
                    AgentRole.CODER,
                    request.attempt,
                    start.checkpoint_sequence,
                    "f" * 40,
                )
            }
        )
    if change in {"lease", "attempt", "sequence", "repository"}:
        changes: dict[str, dict[str, object]] = {
            "lease": {"lease": claim.lease.model_copy(update={"id": "lease_foreign"})},
            "attempt": {
                "work_item": claim.work_item.model_copy(update={"attempt": request.attempt + 1})
            },
            "sequence": {
                "work_item": claim.work_item.model_copy(
                    update={"checkpoint_sequence": start.checkpoint_sequence + 1}
                )
            },
            "repository": {
                "work_item": claim.work_item.model_copy(update={"repository_scopes": ("/foreign",)})
            },
        }
        claim = claim.model_copy(update=changes[change])
    if change == "baseline":
        request = request.model_copy(
            update={"execution_baseline_sha256": "e" * 64, "execution_base_ref": "d" * 40}
        )
        start = start.model_copy(update={"request": request})
        from ai_software_engineer.recovery.models import digest

        start = start.model_copy(
            update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
        )

    def check() -> None:
        require_inherited_invocation_queue(
            start,
            seed.dispatch,
            seed.dispatch.task,
            fixture.plan.source.scope,
            "project_example",
            admission,
            () if change == "step" else (step,),
            (),
            claim,
        )

    if change is None:
        check()
    else:
        with pytest.raises(RecoveryRejected):
            check()


@pytest.mark.parametrize("change", [None, "legacy", "snapshot", "row", "event", "missing_body"])
def test_original_claim_checks_snapshot_and_index_without_requiring_stopped_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str | None
) -> None:
    fixture = preparation_fixture(tmp_path, monkeypatch)
    seed, _, _ = seed_fixture(fixture)
    assert seed.guard is not None and seed.guard.lease is not None
    claim = seed.guard.lease.claim
    current_lease = claim.lease.model_copy(
        update={"expires_at": claim.lease.expires_at + timedelta(hours=1)}
    )
    current = claim.model_copy(update={"lease": current_lease})
    row: dict[str, object] = {
        "lease_id": claim.lease.id,
        "work_item_id": claim.work_item.id,
        "task_id": claim.work_item.task_id,
        "agent_id": claim.lease.agent_id,
        "capacity_units": claim.lease.capacity_units,
        "assignment_json": json.dumps(claim.assignment.to_wire()),
        "lease_json": json.dumps(current_lease.to_wire()),
        "model_selection_json": json.dumps(claim.model_selection.to_wire()),
        "worker_id": claim.worker_id,
        "acquired_at": claim.lease.acquired_at.isoformat(),
        "expires_at": current_lease.expires_at.isoformat(),
        "owner_token_sha256": "e" * 64,
        # Active/released/expired is deliberately not a stop proof in this reader.
        "state": "ACTIVE",
    }
    snapshot = (
        claim.model_copy(update={"worker_id": "worker_foreign"}) if change == "snapshot" else claim
    )
    event: dict[str, object] = {
        "lease_id": claim.lease.id,
        "work_item_id": claim.work_item.id,
        "event_type": "CLAIMED",
        "from_status": "READY",
        "to_status": "LEASED",
        "occurred_at": claim.claimed_at.isoformat(),
        "payload_json": json.dumps(
            {
                "work_item": claim.work_item.to_wire(),
                "detail": {} if change == "legacy" else {"queue_claim": snapshot.to_wire()},
            }
        ),
    }
    if change == "row":
        row["agent_id"] = "agent_foreign"
    if change == "event":
        event["work_item_id"] = "work_foreign"
    if change == "missing_body":
        event["payload_json"] = '{"detail":{}}'
    if change in {"snapshot", "row", "event", "missing_body"}:
        with pytest.raises((RecoveryRejected, ValueError)):
            _original_claim(row, event)
    else:
        assert _original_claim(row, event) == (current if change == "legacy" else claim)
