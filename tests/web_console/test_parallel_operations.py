"""Different Requirements deliver concurrently; one Requirement stays serial."""

from __future__ import annotations

import time
from threading import Event, Lock

import pytest

from ai_software_engineer.web_console import InMemoryConsoleOperationStore
from ai_software_engineer.web_console.core import ProjectConsole
from ai_software_engineer.web_console.models import (
    ConsoleCommandResult,
    ConsoleIntent,
    ProductApprovalIntent,
)
from ai_software_engineer.web_console.store import ConsoleOperationConflict, operation_lane

PROJECT = "project_test"


def _approval(delivery: str) -> ProductApprovalIntent:
    return ProductApprovalIntent(
        project_id=PROJECT, delivery_id=delivery, expected_checkpoint_sha256="1" * 64
    )


class _HeldExecutor:
    def __init__(self) -> None:
        self.release = Event()
        self.lock = Lock()
        self.running: set[str] = set()
        self.peak = 0
        self.order: list[str] = []

    def execute(self, intent: ConsoleIntent) -> ConsoleCommandResult:
        delivery = getattr(intent, "delivery_id", None) or "none"
        with self.lock:
            self.running.add(delivery + f"#{len(self.order)}")
            self.order.append(delivery)
            self.peak = max(self.peak, len(self.running))
        assert self.release.wait(5)
        with self.lock:
            self.running = {item for item in self.running if not item.startswith(delivery)}
        return ConsoleCommandResult(project_id=PROJECT, stage="DONE", next_action="Done.")


def _wait(predicate, timeout: float = 3.0) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.01)


def test_different_requirements_run_concurrently_and_one_requirement_stays_serial() -> None:
    store = InMemoryConsoleOperationStore("team_test")
    executor = _HeldExecutor()
    console = ProjectConsole(
        store=store, executor=executor, poll_seconds=0.01, max_parallel_operations=3
    )
    a, b = "delivery_multi_" + "a" * 40, "delivery_multi_" + "b" * 40
    console.start()
    try:
        console.submit(_approval(a), idempotency_key="op-key-a-1")
        with pytest.raises(ConsoleOperationConflict):
            # One Requirement never runs two Manager operations at once.
            console.submit(_approval(a), idempotency_key="op-key-a-2")
        console.submit(_approval(b), idempotency_key="op-key-b-1")
        _wait(lambda: len(executor.order) == 2)
        assert sorted(executor.order) == sorted([a, b])
        assert executor.peak == 2
        executor.release.set()
        _wait(lambda: all(item.status.value == "SUCCEEDED" for item in console.list_operations()))
    finally:
        executor.release.set()
        console.close(timeout=5)


def test_parallelism_is_bounded() -> None:
    store = InMemoryConsoleOperationStore("team_test")
    executor = _HeldExecutor()
    console = ProjectConsole(
        store=store, executor=executor, poll_seconds=0.01, max_parallel_operations=2
    )
    console.start()
    try:
        for letter in "cde":
            console.submit(
                _approval("delivery_multi_" + letter * 40), idempotency_key="op-key-" + letter
            )
        _wait(lambda: len(executor.order) == 2)
        time.sleep(0.1)
        assert len(executor.order) == 2 and executor.peak == 2
        executor.release.set()
        _wait(lambda: len(executor.order) == 3)
    finally:
        executor.release.set()
        console.close(timeout=5)


def test_default_console_keeps_single_operation_execution() -> None:
    store = InMemoryConsoleOperationStore("team_test")
    executor = _HeldExecutor()
    console = ProjectConsole(store=store, executor=executor, poll_seconds=0.01)
    console.start()
    try:
        for letter in "fg":
            console.submit(
                _approval("delivery_multi_" + letter * 40), idempotency_key="op-key-" + letter
            )
        _wait(lambda: len(executor.order) == 1)
        time.sleep(0.1)
        assert executor.peak == 1
        executor.release.set()
        _wait(lambda: len(executor.order) == 2)
    finally:
        executor.release.set()
        console.close(timeout=5)


def test_lane_queue_skips_busy_lane_without_caching_idle() -> None:
    store = InMemoryConsoleOperationStore("team_test")
    a = "delivery_multi_" + "h" * 40
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    store.submit(intent=_approval(a), idempotency_key="op-key-h-1", requested_at=now)
    queued = store.list_current()[0]
    lane = operation_lane(queued)
    assert lane == f"delivery:{a}"
    assert store.claim_next(at=now, busy_lanes=frozenset({lane})) is None
    assert store.claim_next(at=now) is not None
