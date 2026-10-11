"""Drive the actual worker with deterministic Event time, without long sleeps."""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

from ai_software_engineer.web_console import (
    ConsoleCommandRejected,
    ConsoleOperation,
    ConsoleOperationStatus,
    FileConsoleOperationStore,
    InMemoryConsoleOperationStore,
    ProjectConsole,
)
from ai_software_engineer.web_console.shutdown import ShutdownState
from tests.web_console.test_core import TEAM_ID, _Clock, _create_intent, _Executor


class _ManualWake:
    def __init__(self) -> None:
        self.signaled = False
        self.waits: list[float] = []
        self.elapsed: list[float] = []
        self.on_wait: Callable[[int, float], None] = lambda _number, _timeout: None

    def set(self) -> None:
        self.signaled = True

    def clear(self) -> None:
        self.signaled = False

    def wait(self, timeout: float) -> bool:
        self.waits.append(timeout)
        assert len(self.waits) <= 100, "fake worker failed to terminate"
        self.on_wait(len(self.waits), timeout)
        self.elapsed.append(0.0 if self.signaled else timeout)
        return self.signaled


class _CountingStore(InMemoryConsoleOperationStore):
    def __init__(self) -> None:
        super().__init__(TEAM_ID)
        self.claims = 0

    def claim_next(self, *, at: datetime) -> ConsoleOperation | None:
        self.claims += 1
        return super().claim_next(at=at)


def _set_wake(console: ProjectConsole, monkeypatch: pytest.MonkeyPatch) -> _ManualWake:
    wake = _ManualWake()
    monkeypatch.setattr(console, "_wake", wake)
    return wake


def test_idle_waits_increase_and_cap_without_busy_spin(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _CountingStore()
    console = ProjectConsole(store=store, executor=_Executor())
    wake = _set_wake(console, monkeypatch)

    def stop_after(number: int, _timeout: float) -> None:
        if number == 64:
            console.begin_shutdown()

    wake.on_wait = stop_after
    console._run()

    assert wake.waits == [0.25, 1.0, 2.0] + [5.0] * 61
    assert store.claims == 64, "each real iteration still invokes the original claim port"
    fixed_poll_scans = sum(wake.elapsed) / 0.25
    assert store.claims / fixed_poll_scans < 0.10
    assert console.await_shutdown(0).state is ShutdownState.READY


@pytest.mark.parametrize("poll_seconds", [0.125, 5.0, 10.0])
def test_custom_initial_interval_remains_the_minimum(
    monkeypatch: pytest.MonkeyPatch, poll_seconds: float
) -> None:
    console = ProjectConsole(
        store=InMemoryConsoleOperationStore(TEAM_ID),
        executor=_Executor(),
        poll_seconds=poll_seconds,
    )
    wake = _set_wake(console, monkeypatch)

    def stop_after(number: int, _timeout: float) -> None:
        if number == 5:
            console.begin_shutdown()

    wake.on_wait = stop_after

    console._run()

    assert wake.waits == [
        poll_seconds,
        max(poll_seconds, 1.0),
        max(poll_seconds, 2.0),
        max(poll_seconds, 5.0),
        max(poll_seconds, 5.0),
    ]


def test_same_process_submit_wakes_max_wait_and_resets_delay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor = _Executor()
    console = ProjectConsole(store=InMemoryConsoleOperationStore(TEAM_ID), executor=executor)
    wake = _set_wake(console, monkeypatch)
    submitted: list[ConsoleOperation] = []

    def submit_or_stop(number: int, _timeout: float) -> None:
        if number == 4:
            submitted.append(
                console.submit(_create_intent(tmp_path), idempotency_key="wake-submit")
            )
        elif number == 6:
            console.begin_shutdown()

    wake.on_wait = submit_or_stop
    console._run()

    assert wake.waits == [0.25, 1.0, 2.0, 5.0, 0.25, 1.0]
    assert wake.elapsed[3] == 0.0, "submission signals Event instead of waiting five seconds"
    assert len(executor.intents) == 1
    assert console.get(submitted[0].operation_id).status is ConsoleOperationStatus.SUCCEEDED


def test_idempotent_terminal_submit_still_resets_idle_delay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor = _Executor()
    console = ProjectConsole(store=InMemoryConsoleOperationStore(TEAM_ID), executor=executor)
    intent = _create_intent(tmp_path)
    first = console.submit(intent, idempotency_key="wake-terminal-replay")
    assert console.run_once() is not None
    wake = _set_wake(console, monkeypatch)

    def replay_or_stop(number: int, _timeout: float) -> None:
        if number == 4:
            console.submit(intent, idempotency_key="wake-terminal-replay")
        elif number == 6:
            console.begin_shutdown()

    wake.on_wait = replay_or_stop
    console._run()

    assert wake.waits == [0.25, 1.0, 2.0, 5.0, 0.25, 1.0]
    assert wake.elapsed[3] == 0.0
    assert len(executor.intents) == 1, "waking must not duplicate a terminal Operation"
    assert console.get(first.operation_id).sequence == 3


@pytest.mark.parametrize("reject", [False, True])
def test_external_writer_is_found_at_next_bounded_poll_and_completion_resets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reject: bool
) -> None:
    store = FileConsoleOperationStore(tmp_path / "operations", team_id=TEAM_ID)
    external = FileConsoleOperationStore(store.root, team_id=TEAM_ID)
    executor = _Executor(
        failure=ConsoleCommandRejected("STALE_CHECKPOINT", "输入已变化。") if reject else None
    )
    console = ProjectConsole(store=store, executor=executor, clock=_Clock())
    wake = _set_wake(console, monkeypatch)
    submitted: list[ConsoleOperation] = []

    def write_or_stop(number: int, _timeout: float) -> None:
        if number == 4:
            submitted.append(
                external.submit(
                    intent=_create_intent(tmp_path),
                    idempotency_key="external-writer",
                    requested_at=_Clock()(),
                )
            )
            assert not wake.signaled, "another store has no ambient in-process wake authority"
        elif number == 6:
            console.begin_shutdown()

    wake.on_wait = write_or_stop
    console._run()

    assert wake.waits == [0.25, 1.0, 2.0, 5.0, 0.25, 1.0]
    assert wake.elapsed[3] == 5.0
    expected = ConsoleOperationStatus.FAILED if reject else ConsoleOperationStatus.SUCCEEDED
    assert external.get(submitted[0].operation_id).status is expected
    assert len(executor.intents) == 1


def test_stop_wakes_max_delay_and_resume_starts_from_initial_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console = ProjectConsole(store=InMemoryConsoleOperationStore(TEAM_ID), executor=_Executor())
    wake = _set_wake(console, monkeypatch)

    def stop_at_maximum_wait(number: int, _timeout: float) -> None:
        if number == 4:
            console.begin_shutdown()

    wake.on_wait = stop_at_maximum_wait
    console._run()

    assert wake.waits == [0.25, 1.0, 2.0, 5.0]
    assert wake.elapsed[-1] == 0.0
    assert console.await_shutdown(0).state is ShutdownState.READY
    assert console.cancel_shutdown().state is ShutdownState.RUNNING

    def stop_after_resume(_number: int, _timeout: float) -> None:
        console.begin_shutdown()

    wake.on_wait = stop_after_resume
    console._run()

    assert wake.waits[-1] == 0.25
    assert wake.elapsed[-1] == 0.0
    assert console.await_shutdown(0).state is ShutdownState.READY
