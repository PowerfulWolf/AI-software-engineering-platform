from __future__ import annotations

from threading import Event, Thread

import pytest

from ai_software_engineer.knowledge.index import KnowledgeIndexWorker


def test_index_shutdown_does_not_claim_success_while_tick_is_running() -> None:
    entered, release = Event(), Event()
    ticks: list[int] = []

    def tick() -> None:
        ticks.append(1)
        entered.set()
        assert release.wait(3)

    worker = KnowledgeIndexWorker(tick, interval=0.1)
    worker.start()
    try:
        assert entered.wait(1)
        assert worker.close(timeout=0.01) is False
        assert bool(worker.is_alive)
    finally:
        release.set()
        assert worker.close(timeout=1) is True
    alive = worker.is_alive
    assert alive is False
    assert ticks == [1]


@pytest.mark.parametrize("error_type", [OSError, SystemExit])
def test_index_tick_persistence_failure_cannot_be_resumed_or_reported_stopped(
    error_type: type[BaseException],
) -> None:
    failed = Event()

    def tick() -> None:
        failed.set()
        raise error_type("private store payload")

    worker = KnowledgeIndexWorker(tick)
    worker.start()
    assert failed.wait(1)
    assert worker.close(timeout=1) is False
    assert worker.shutdown_failed
    worker.cancel_shutdown()
    assert worker.close(timeout=1) is False


def test_thread_start_failure_has_no_phantom_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_: Thread) -> None:
        raise RuntimeError("cannot start new thread")

    monkeypatch.setattr(Thread, "start", fail)
    worker = KnowledgeIndexWorker(lambda: None)
    with pytest.raises(RuntimeError, match="cannot start"):
        worker.start()
    assert worker.close(timeout=0) is True
    assert not worker.shutdown_failed
