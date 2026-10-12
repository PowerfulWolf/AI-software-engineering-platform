"""Heartbeat mutation must never alter independently sealed original claim bytes."""

from __future__ import annotations

import json
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest

from ai_software_engineer.domain.enums import WorkItemStatus
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.work_queue.claim_snapshot import require_claim_snapshot
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
from ai_software_engineer.work_queue.ports import QueueCorruption
from tests.manager.test_execution_baseline_invocations import _claim
from tests.work_queue.test_mysql_queue import queued_item
from tests.work_queue.test_worker_mysql import TOKEN, admit, claim_step
from tests.work_queue.test_worker_mysql import mysql_dsn as mysql_dsn


def test_exact_original_snapshot_allows_only_lease_expiry_and_requires_full_raw_hash() -> None:
    original = _claim(queued_item(), "lease_snapshot_original")
    historical = original.model_copy(
        update={
            "lease": original.lease.model_copy(
                update={"expires_at": original.lease.expires_at + timedelta(seconds=10)}
            )
        }
    )
    assert (
        require_claim_snapshot(original, historical, expected_sha256=digest(original.to_wire()))
        == original
    )
    with pytest.raises(ValueError, match="完整摘要"):
        require_claim_snapshot(original, historical, expected_sha256=digest(historical.to_wire()))
    for field, changed in (
        ("worker_id", "worker_another_owner"),
        ("claimed_at", original.claimed_at + timedelta(seconds=1)),
        (
            "assignment",
            original.assignment.model_copy(
                update={"assigned_at": original.assignment.assigned_at + timedelta(seconds=1)}
            ),
        ),
        (
            "model_selection",
            original.model_selection.model_copy(
                update={"selected_at": original.model_selection.selected_at - timedelta(seconds=1)}
            ),
        ),
        (
            "work_item",
            original.work_item.model_copy(
                update={"updated_at": original.work_item.updated_at + timedelta(seconds=1)}
            ),
        ),
        (
            "lease",
            historical.lease.model_copy(
                update={"acquired_at": original.lease.acquired_at + timedelta(seconds=1)}
            ),
        ),
    ):
        with pytest.raises(ValueError, match="真实历史分配"):
            require_claim_snapshot(original, historical.model_copy(update={field: changed}))


@pytest.mark.mysql
def test_original_claim_is_byte_identical_after_real_multiple_renewals(mysql_dsn: str) -> None:
    queue = MySqlRoleQueue(mysql_dsn)
    step = admit(queue)
    original = claim_step(queue, step)
    sealed = original.model_dump_json()
    raw_sha = digest(original.to_wire())
    queue.start(
        step.work_item.id, lease_id=original.lease.id, owner_token=TOKEN, now=datetime.now(UTC)
    )
    for extra in (20, 40):
        now = datetime.now(UTC)
        lease = queue.renew(
            step.work_item.id,
            lease_id=original.lease.id,
            owner_token=TOKEN,
            now=now,
            expires_at=original.lease.expires_at + timedelta(seconds=extra),
        )
        assert lease.expires_at != original.lease.expires_at
        assert queue.original_claim(original.lease.id).model_dump_json() == sealed
        assert digest(queue.original_claim(original.lease.id).to_wire()) == raw_sha
        assert queue.claims_for_work_item(step.work_item.id) == (original,)
        assert queue.step_for_claim(original) == step
    queue.wait(
        step.work_item.id,
        lease_id=original.lease.id,
        owner_token=TOKEN,
        status=WorkItemStatus.WAITING_DEPENDENCY,
        reason="fixture held",
        now=datetime.now(UTC),
    )
    assert queue.original_claim(original.lease.id) == original


@pytest.mark.mysql
@pytest.mark.parametrize(
    "invalid",
    ["null", "worker", "time", "event_item", "expiry_index", "legacy_event_clock", "from_status"],
)
def test_present_but_invalid_claim_snapshot_never_falls_back_to_legacy(
    mysql_dsn: str, invalid: str
) -> None:
    queue = MySqlRoleQueue(mysql_dsn)
    original = claim_step(queue, admit(queue))
    snapshot = original.to_wire()
    if invalid == "worker":
        snapshot["worker_id"] = "worker_wrong_owner"
    elif invalid == "time":
        snapshot["claimed_at"] = (original.claimed_at + timedelta(seconds=1)).isoformat()
    with closing(open_mysql_connection(mysql_dsn)) as connection, connection.cursor() as cursor:
        if invalid == "legacy_event_clock":
            cursor.execute(
                "UPDATE work_queue_events SET payload_json=%s,occurred_at=%s "
                "WHERE lease_id=%s AND event_type='CLAIMED'",
                (
                    json.dumps({"work_item": original.work_item.to_wire(), "detail": {}}),
                    (original.claimed_at + timedelta(seconds=1)).isoformat(),
                    original.lease.id,
                ),
            )
        elif invalid == "from_status":
            cursor.execute(
                "UPDATE work_queue_events SET from_status='RUNNING' "
                "WHERE lease_id=%s AND event_type='CLAIMED'",
                (original.lease.id,),
            )
        elif invalid == "expiry_index":
            cursor.execute(
                "UPDATE work_queue_claims SET expires_at=%s WHERE lease_id=%s",
                ((original.lease.expires_at + timedelta(seconds=1)).isoformat(), original.lease.id),
            )
        else:
            payload = {
                "work_item": original.work_item.to_wire(),
                "detail": {"queue_claim": None if invalid == "null" else snapshot},
            }
            if invalid == "event_item":
                payload["work_item"] = original.work_item.model_copy(
                    update={"priority": 1}
                ).to_wire()
            cursor.execute(
                "UPDATE work_queue_events SET payload_json=%s "
                "WHERE lease_id=%s AND event_type='CLAIMED'",
                (json.dumps(payload), original.lease.id),
            )
        connection.commit()
    with pytest.raises(QueueCorruption, match="不可变完整快照"):
        queue.original_claim(original.lease.id)
