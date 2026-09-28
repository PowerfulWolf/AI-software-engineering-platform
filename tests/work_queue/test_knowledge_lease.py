"""A committed knowledge wait revokes execution without pretending the lease was lost."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import cast

import pytest

from ai_software_engineer.knowledge.gaps import KnowledgeGapRaised
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
from ai_software_engineer.work_queue.ports import QueueConflict
from ai_software_engineer.work_queue.worker import WorkerLease
from tests.knowledge.test_queue import OWNER, FencedQueue, bound, route
from tests.work_queue.test_dispatcher import agent, dispatcher


def test_committed_wait_prevents_further_execution_with_the_exact_gap(tmp_path: Path) -> None:
    queue = FencedQueue()
    tick = dispatcher(queue, agent("coder")).tick(now=datetime.now(UTC))
    assert tick.claim is not None
    binding = bound(tick.claim)
    records = KnowledgeRecordStore(tmp_path)
    routing = route(records, binding)
    lease = WorkerLease(cast(MySqlRoleQueue, queue), tick.claim, OWNER)

    lease.wait_for_knowledge(binding, routing, records)

    with pytest.raises(KnowledgeGapRaised) as caught:
        lease.check()
    assert caught.value.gap.gap_id == routing.gap_id
    with pytest.raises(KnowledgeGapRaised):
        lease.finish(None, datetime.now(UTC))
    assert queue.released and not lease._lost.is_set()


def test_rejected_wait_does_not_publish_a_local_wait(tmp_path: Path) -> None:
    queue = FencedQueue()
    tick = dispatcher(queue, agent("coder")).tick(now=datetime.now(UTC))
    assert tick.claim is not None
    binding = bound(tick.claim)
    records = KnowledgeRecordStore(tmp_path)
    routing = route(records, binding)
    lease = WorkerLease(cast(MySqlRoleQueue, queue), tick.claim, "wrong-owner")

    with pytest.raises(QueueConflict, match="owner"):
        lease.wait_for_knowledge(binding, routing, records)

    assert not queue.released and not lease._stop.is_set()
    assert lease._knowledge_wait is None
    lease.check()


def test_heartbeat_cannot_renew_a_claim_during_knowledge_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = FencedQueue()
    tick = dispatcher(queue, agent("coder")).tick(now=datetime.now(UTC))
    assert tick.claim is not None
    binding = bound(tick.claim)
    records = KnowledgeRecordStore(tmp_path)
    routing = route(records, binding)
    lease = WorkerLease(cast(MySqlRoleQueue, queue), tick.claim, OWNER)
    lease._ttl = timedelta(milliseconds=3)
    released, finish_wait, renewed = Event(), Event(), Event()
    original_wait = queue.wait

    def waiting(*args: object, **kwargs: object) -> object:
        result = original_wait(*args, **kwargs)  # type: ignore[arg-type]
        released.set()
        assert finish_wait.wait(3)
        return result

    def renew(*args: object, **kwargs: object) -> None:
        renewed.set()
        raise RuntimeError("released claim cannot renew")

    monkeypatch.setattr(queue, "wait", waiting)
    monkeypatch.setattr(queue, "renew", renew, raising=False)
    errors: list[Exception] = []

    def release() -> None:
        try:
            lease.wait_for_knowledge(binding, routing, records)
        except Exception as error:
            errors.append(error)

    waiter = Thread(target=release)
    waiter.start()
    try:
        assert released.wait(3)
        lease._thread.start()
        assert not renewed.wait(0.1), "heartbeat raced the committed wait"
    finally:
        finish_wait.set()
        waiter.join(3)
        lease.stop()
    assert not waiter.is_alive() and not errors
    assert not lease._lost.is_set()
