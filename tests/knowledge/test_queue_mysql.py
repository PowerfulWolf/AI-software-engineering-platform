"""The same knowledge wait bridge against the T046 real MySQL lifecycle boundary."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.domain.enums import WorkItemStatus
from ai_software_engineer.knowledge.queue import QueueKnowledgeWaitPort
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.work_queue import MySqlPersistentWorkQueue, QueueConflict
from tests.knowledge.test_queue import bound, route
from tests.work_queue.test_mysql_queue import (
    NOW,
    dispatcher,
    queued_item,
)
from tests.work_queue.test_mysql_queue import mysql_queue as _guarded_mysql_queue

guarded_mysql_queue = _guarded_mysql_queue

pytestmark = pytest.mark.mysql


def test_real_claim_releases_lease_and_rejects_old_owner_replay(
    guarded_mysql_queue: MySqlPersistentWorkQueue, tmp_path: Path
) -> None:
    queue = guarded_mysql_queue
    queue.enqueue(queued_item())
    dispatched = dispatcher(queue, "worker_knowledge_001").tick(now=NOW)
    assert dispatched.claim is not None and dispatched.lease_owner_token is not None
    binding = bound(dispatched.claim)
    records = KnowledgeRecordStore(tmp_path)
    routing = route(records, binding)
    wrong = QueueKnowledgeWaitPort(
        queue,
        claim=dispatched.claim,
        owner_token="wrong-owner-token-0001",
        binding=binding,
        records=records,
        clock=lambda: NOW + timedelta(seconds=1),
    )
    with pytest.raises(QueueConflict):
        wrong.wait(binding, routing)
    assert len(queue.list_active_leases(now=NOW + timedelta(seconds=1))) == 1
    port = QueueKnowledgeWaitPort(
        queue,
        claim=dispatched.claim,
        owner_token=dispatched.lease_owner_token,
        binding=binding,
        records=records,
        clock=lambda: NOW + timedelta(seconds=2),
    )
    port.wait(binding, routing)
    current = queue.get(dispatched.claim.work_item.id)
    assert current.status is WorkItemStatus.WAITING_HUMAN
    assert queue.list_active_leases(now=NOW + timedelta(seconds=2)) == ()
    with pytest.raises(QueueConflict):
        port.wait(binding, routing)
    queue.make_ready(current.id, now=NOW + timedelta(seconds=3))
    successor = dispatcher(queue, "worker_knowledge_002").tick(now=NOW + timedelta(seconds=4))
    assert successor.claim is not None
    with pytest.raises(QueueConflict):
        port.wait(binding, routing)
    assert len(queue.list_active_leases(now=NOW + timedelta(seconds=4))) == 1
