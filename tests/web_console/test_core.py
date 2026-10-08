from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread

import pytest

from ai_software_engineer.web_console import (
    ConsoleCommandRejected,
    ConsoleCommandResult,
    ConsoleIntent,
    ConsoleOperation,
    ConsoleOperationConflict,
    ConsoleOperationStatus,
    CreateRequirementIntent,
    FileConsoleOperationStore,
    InMemoryConsoleOperationStore,
    ProductReplyIntent,
    ProjectConsole,
)
from ai_software_engineer.web_console.shutdown import ShutdownState

TEAM_ID = "team_test"
CHECKPOINT = "1" * 64


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(microseconds=1)
        return current


class _Executor:
    def __init__(self, *, failure: ConsoleCommandRejected | None = None) -> None:
        self.failure = failure
        self.intents: list[object] = []

    def execute(self, intent: object) -> ConsoleCommandResult:
        self.intents.append(intent)
        if self.failure is not None:
            raise self.failure
        return ConsoleCommandResult(
            project_id="project_test",
            delivery_id="delivery_multi_" + "a" * 40,
            checkpoint_sha256="2" * 64,
            stage="READY_FOR_DISCUSSION",
            next_action="Discuss the requirement.",
        )


def test_resume_durable_callback_failure_keeps_admission_closed(tmp_path: Path) -> None:
    console = ProjectConsole(store=InMemoryConsoleOperationStore("team_test"), executor=_Executor())
    console.begin_shutdown()

    def fail() -> None:
        raise OSError("private lifecycle record")

    result = console.cancel_shutdown(before_resume=fail)
    assert result.state is ShutdownState.REFUSED
    assert "private" not in result.safe_summary
    with pytest.raises(ConsoleCommandRejected, match="安全停止"):
        console.submit(_create_intent(tmp_path), idempotency_key="after-failed-resume")
    assert console.cancel_shutdown().state is ShutdownState.REFUSED


def test_resume_dispatcher_start_failure_cannot_publish_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    console = ProjectConsole(store=InMemoryConsoleOperationStore("team_test"), executor=_Executor())
    console.start()
    assert console.close(timeout=1).state is ShutdownState.READY
    recorded: list[str] = []

    def fail(_: Thread) -> None:
        raise RuntimeError("private thread resource failure")

    monkeypatch.setattr(Thread, "start", fail)
    result = console.cancel_shutdown(before_resume=lambda: recorded.append("RUNNING"))
    assert result.state is ShutdownState.REFUSED
    assert recorded == []
    assert console.run_once() is None
    with pytest.raises(ConsoleCommandRejected, match="安全停止"):
        console.submit(_create_intent(tmp_path), idempotency_key="after-dispatcher-start-failure")


def _create_intent(tmp_path: Path, *, name: str = "Console delivery") -> CreateRequirementIntent:
    return CreateRequirementIntent(
        project_id="project_test",
        name=name,
        repository_roots=(str(tmp_path),),
    )


def _reply_intent(*, message: str = "Use the external workspace") -> ProductReplyIntent:
    return ProductReplyIntent(
        project_id="project_test",
        delivery_id="delivery_multi_" + "a" * 40,
        expected_checkpoint_sha256=CHECKPOINT,
        message=message,
    )


@pytest.mark.parametrize("store_kind", ["memory", "file"])
def test_submit_is_idempotent_and_changed_intent_is_rejected(
    tmp_path: Path, store_kind: str
) -> None:
    store = (
        InMemoryConsoleOperationStore(TEAM_ID)
        if store_kind == "memory"
        else FileConsoleOperationStore(tmp_path / "operations", team_id=TEAM_ID)
    )
    at = datetime(2026, 9, 12, tzinfo=UTC)

    first = store.submit(
        intent=_create_intent(tmp_path), idempotency_key="browser-action-0001", requested_at=at
    )
    replay = store.submit(
        intent=_create_intent(tmp_path), idempotency_key="browser-action-0001", requested_at=at
    )

    assert replay == first
    with pytest.raises(ConsoleOperationConflict, match="another console intent"):
        store.submit(
            intent=_create_intent(tmp_path, name="Changed"),
            idempotency_key="browser-action-0001",
            requested_at=at,
        )


@pytest.mark.parametrize("store_kind", ["memory", "file"])
def test_one_delivery_admits_only_one_active_operation(tmp_path: Path, store_kind: str) -> None:
    store = (
        InMemoryConsoleOperationStore(TEAM_ID)
        if store_kind == "memory"
        else FileConsoleOperationStore(tmp_path / "operations", team_id=TEAM_ID)
    )
    at = datetime(2026, 9, 12, tzinfo=UTC)
    store.submit(intent=_reply_intent(), idempotency_key="browser-action-0001", requested_at=at)

    with pytest.raises(ConsoleOperationConflict, match="active console operation"):
        store.submit(
            intent=_reply_intent(message="A second message"),
            idempotency_key="browser-action-0002",
            requested_at=at,
        )


def test_console_persists_before_execution_and_returns_terminal_result(tmp_path: Path) -> None:
    store = InMemoryConsoleOperationStore(TEAM_ID)
    executor = _Executor()
    console = ProjectConsole(store=store, executor=executor, clock=_Clock())

    queued = console.submit(_create_intent(tmp_path), idempotency_key="browser-action-0001")

    assert queued.status is ConsoleOperationStatus.QUEUED
    assert executor.intents == []
    completed = console.run_once()
    assert completed is not None
    assert completed.status is ConsoleOperationStatus.SUCCEEDED
    assert completed.result is not None
    assert completed.result.stage == "READY_FOR_DISCUSSION"
    assert len(executor.intents) == 1
    assert console.get(queued.operation_id) == completed


def test_console_records_only_safe_rejection(tmp_path: Path) -> None:
    rejection = ConsoleCommandRejected("STALE_CHECKPOINT", "The displayed request changed.")
    console = ProjectConsole(
        store=InMemoryConsoleOperationStore(TEAM_ID),
        executor=_Executor(failure=rejection),
        clock=_Clock(),
    )
    queued = console.submit(_create_intent(tmp_path), idempotency_key="browser-action-0001")

    completed = console.run_once()

    assert completed is not None
    assert completed.operation_id == queued.operation_id
    assert completed.status is ConsoleOperationStatus.FAILED
    assert completed.error_code == "STALE_CHECKPOINT"
    assert completed.error_summary == "The displayed request changed."
    assert completed.result is None


def test_unknown_failure_has_safe_type_and_operation_correlation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class Executor:
        def execute(self, intent: object) -> ConsoleCommandResult:
            raise RuntimeError("mysql+pymysql://user:private-password@host/db")

    console = ProjectConsole(
        store=InMemoryConsoleOperationStore(TEAM_ID), executor=Executor(), clock=_Clock()
    )
    console.submit(_create_intent(tmp_path), idempotency_key="unknown-error")
    failed = console.run_once()
    assert failed is not None and failed.error_summary is not None
    assert failed.error_code == "MANAGER_FAILURE"
    assert "RuntimeError" in failed.error_summary
    assert failed.operation_id in caplog.text
    assert "private-password" not in caplog.text + failed.error_summary
    assert "Traceback" not in caplog.text


class _BlockedExecutor(_Executor):
    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def execute(self, intent: object) -> ConsoleCommandResult:
        self.entered.set()
        assert self.release.wait(2)
        return super().execute(intent)


def test_close_refuses_while_claimed_operation_is_still_executing(tmp_path: Path) -> None:
    executor = _BlockedExecutor()
    console = ProjectConsole(store=InMemoryConsoleOperationStore(TEAM_ID), executor=executor)
    queued = console.submit(_create_intent(tmp_path), idempotency_key="shutdown-active-0001")
    console.start()
    assert executor.entered.wait(1)
    try:
        result = console.close(timeout=0.01)

        assert result is not None, "close must not silently return while execution is active"
        assert result.state.value == "REFUSED"
        assert console.get(queued.operation_id).status is ConsoleOperationStatus.RUNNING
    finally:
        executor.release.set()
        console.close(timeout=1)


def test_close_refuses_new_submission_after_drain_begins(tmp_path: Path) -> None:
    executor = _BlockedExecutor()
    console = ProjectConsole(store=InMemoryConsoleOperationStore(TEAM_ID), executor=executor)
    console.submit(_create_intent(tmp_path), idempotency_key="shutdown-active-0001")
    console.start()
    assert executor.entered.wait(1)
    try:
        console.close(timeout=0.01)

        with pytest.raises(ConsoleCommandRejected, match="安全停止"):
            console.submit(_create_intent(tmp_path), idempotency_key="shutdown-new-0002")
    finally:
        executor.release.set()
        console.close(timeout=1)


def test_drain_preserves_queued_operations_and_finalizes_only_current(tmp_path: Path) -> None:
    executor = _BlockedExecutor()
    console = ProjectConsole(store=InMemoryConsoleOperationStore(TEAM_ID), executor=executor)
    first = console.submit(_create_intent(tmp_path), idempotency_key="shutdown-first-0001")
    second = console.submit(
        _create_intent(tmp_path, name="Later request"), idempotency_key="shutdown-second-0002"
    )
    console.start()
    assert executor.entered.wait(1)

    assert console.begin_shutdown().state is ShutdownState.DRAINING
    assert console.run_once() is None
    executor.release.set()
    assert console.await_shutdown(1).state is ShutdownState.READY

    assert console.get(first.operation_id).status is ConsoleOperationStatus.SUCCEEDED
    assert console.get(second.operation_id).status is ConsoleOperationStatus.QUEUED
    assert len(executor.intents) == 1
    assert console.close(timeout=0).state is ShutdownState.READY


class _FinishBarrierStore(InMemoryConsoleOperationStore):
    def __init__(self, *, fail_storage: bool = False) -> None:
        super().__init__(TEAM_ID)
        self.entered = Event()
        self.release = Event()
        self.fail_storage = fail_storage

    def _finish(
        self,
        operation_id: str,
        *,
        expected: str,
        status: ConsoleOperationStatus,
        at: datetime,
        result: ConsoleCommandResult | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> ConsoleOperation:
        self.entered.set()
        assert self.release.wait(2)
        if self.fail_storage:
            raise OSError("private-dsn-must-not-be-logged")
        return super()._finish(
            operation_id,
            expected=expected,
            status=status,
            at=at,
            result=result,
            error_code=error_code,
            error_summary=error_summary,
        )


@pytest.mark.parametrize("rejected", [False, True])
def test_readiness_waits_for_terminal_operation_record_not_executor_return(
    tmp_path: Path, rejected: bool
) -> None:
    store = _FinishBarrierStore()
    executor = _Executor(
        failure=ConsoleCommandRejected("STALE_CHECKPOINT", "Input changed.") if rejected else None
    )
    console = ProjectConsole(store=store, executor=executor)
    queued = console.submit(_create_intent(tmp_path), idempotency_key="final-write-0001")
    console.start()
    assert store.entered.wait(1)
    try:
        result = console.close(timeout=0.01)
        assert result.state is ShutdownState.REFUSED
        assert result.active_operations == 1
        assert console.get(queued.operation_id).status is ConsoleOperationStatus.RUNNING
    finally:
        store.release.set()
        assert console.close(timeout=1).state is ShutdownState.READY

    expected = ConsoleOperationStatus.FAILED if rejected else ConsoleOperationStatus.SUCCEEDED
    assert console.get(queued.operation_id).status is expected


@pytest.mark.parametrize("dispatcher", [False, True])
def test_failed_terminal_save_latches_refusal_even_after_execution_thread_exits(
    tmp_path: Path, dispatcher: bool, caplog: pytest.LogCaptureFixture
) -> None:
    store = _FinishBarrierStore(fail_storage=True)
    store.release.set()
    console = ProjectConsole(store=store, executor=_Executor())
    queued = console.submit(_create_intent(tmp_path), idempotency_key="failed-save-0001")
    if dispatcher:
        console.start()
        assert store.entered.wait(1)
    else:
        with pytest.raises(OSError):
            console.run_once()

    result = console.close(timeout=1)
    assert result.state is ShutdownState.REFUSED
    assert "保存" in result.safe_summary
    assert console.cancel_shutdown().state is ShutdownState.REFUSED
    assert console.get(queued.operation_id).status is ConsoleOperationStatus.RUNNING
    with pytest.raises(ConsoleCommandRejected):
        console.submit(_create_intent(tmp_path), idempotency_key="unsafe-save-retry-0002")
    assert "private-dsn" not in caplog.text + result.safe_summary


def test_directly_claimed_operation_is_included_in_shutdown(tmp_path: Path) -> None:
    executor = _BlockedExecutor()
    console = ProjectConsole(store=InMemoryConsoleOperationStore(TEAM_ID), executor=executor)
    console.submit(_create_intent(tmp_path), idempotency_key="direct-operation-0001")
    with ThreadPoolExecutor(max_workers=1) as pool:
        execution = pool.submit(console.run_once)
        assert executor.entered.wait(1)
        assert console.close(timeout=0.01).state is ShutdownState.REFUSED
        executor.release.set()
        assert execution.result(timeout=1) is not None
    assert console.await_shutdown(1).state is ShutdownState.READY


def test_cancel_drain_resumes_queued_work_without_interrupting_current(tmp_path: Path) -> None:
    class Executor(_BlockedExecutor):
        def __init__(self) -> None:
            super().__init__()
            self.completed_second = Event()

        def execute(self, intent: object) -> ConsoleCommandResult:
            result = super().execute(intent)
            if len(self.intents) == 2:
                self.completed_second.set()
            return result

    executor = Executor()
    console = ProjectConsole(store=InMemoryConsoleOperationStore(TEAM_ID), executor=executor)
    first = console.submit(_create_intent(tmp_path), idempotency_key="cancel-first-0001")
    second = console.submit(_create_intent(tmp_path), idempotency_key="cancel-second-0002")
    console.start()
    assert executor.entered.wait(1)
    assert console.close(timeout=0.01).state is ShutdownState.REFUSED
    assert console.cancel_shutdown().state is ShutdownState.RUNNING
    executor.release.set()
    assert executor.completed_second.wait(1)
    assert console.close(timeout=1).state is ShutdownState.READY
    assert console.get(first.operation_id).status is ConsoleOperationStatus.SUCCEEDED
    assert console.get(second.operation_id).status is ConsoleOperationStatus.SUCCEEDED


def test_cancel_ready_drain_starts_dispatcher_again(tmp_path: Path) -> None:
    executor = _BlockedExecutor()
    executor.release.set()
    console = ProjectConsole(store=InMemoryConsoleOperationStore(TEAM_ID), executor=executor)
    console.start()
    assert console.close(timeout=1).state is ShutdownState.READY
    assert console.cancel_shutdown().state is ShutdownState.RUNNING
    console.submit(_create_intent(tmp_path), idempotency_key="cancel-ready-0001")
    assert executor.entered.wait(1)
    assert console.close(timeout=1).state is ShutdownState.READY


def test_operation_scope_owns_execution_through_terminal_record(tmp_path: Path) -> None:
    store = InMemoryConsoleOperationStore(TEAM_ID)
    observed: list[tuple[str, ConsoleOperationStatus]] = []

    @contextmanager
    def scope(operation_id: str) -> Iterator[None]:
        observed.append((operation_id, store.get(operation_id).status))
        yield
        observed.append((operation_id, store.get(operation_id).status))

    console = ProjectConsole(store=store, executor=_Executor(), operation_scope=scope)
    queued = console.submit(_create_intent(tmp_path), idempotency_key="owned-operation-0001")
    assert console.run_once() is not None
    assert observed == [
        (queued.operation_id, ConsoleOperationStatus.RUNNING),
        (queued.operation_id, ConsoleOperationStatus.SUCCEEDED),
    ]


def test_claim_save_failure_cannot_be_treated_as_idle_shutdown(tmp_path: Path) -> None:
    class Store(InMemoryConsoleOperationStore):
        def claim_next(self, *, at: datetime) -> ConsoleOperation | None:
            super().claim_next(at=at)
            raise OSError("private-dsn-must-not-be-logged")

    console = ProjectConsole(store=Store(TEAM_ID), executor=_Executor())
    queued = console.submit(_create_intent(tmp_path), idempotency_key="failed-claim-0001")
    with pytest.raises(OSError):
        console.run_once()
    result = console.close(timeout=0)
    assert result.state is ShutdownState.REFUSED
    assert console.get(queued.operation_id).status is ConsoleOperationStatus.RUNNING


def test_nonstandard_dispatcher_exit_is_not_shutdown_proof(tmp_path: Path) -> None:
    class Store(InMemoryConsoleOperationStore):
        def claim_next(self, *, at: datetime) -> ConsoleOperation | None:
            super().claim_next(at=at)
            raise SystemExit("unsealed operation")

    console = ProjectConsole(store=Store(TEAM_ID), executor=_Executor())
    queued = console.submit(_create_intent(tmp_path), idempotency_key="dispatcher-exit-0001")
    with pytest.raises(SystemExit):
        console.run_once()
    assert console.close(timeout=0).state is ShutdownState.REFUSED
    assert console.get(queued.operation_id).status is ConsoleOperationStatus.RUNNING


def test_shutdown_waits_for_submit_linearization_and_keeps_accepted_queue(tmp_path: Path) -> None:
    class Store(InMemoryConsoleOperationStore):
        def __init__(self) -> None:
            super().__init__(TEAM_ID)
            self.entered = Event()
            self.release = Event()

        def submit(
            self, *, intent: ConsoleIntent, idempotency_key: str, requested_at: datetime
        ) -> ConsoleOperation:
            self.entered.set()
            assert self.release.wait(1)
            return super().submit(
                intent=intent, idempotency_key=idempotency_key, requested_at=requested_at
            )

    store = Store()
    console = ProjectConsole(store=store, executor=_Executor())
    with ThreadPoolExecutor(max_workers=2) as pool:
        submission = pool.submit(
            console.submit, _create_intent(tmp_path), idempotency_key="admission-race-0001"
        )
        assert store.entered.wait(1)
        shutdown = pool.submit(console.begin_shutdown)
        store.release.set()
        queued = submission.result(timeout=1)
        assert shutdown.result(timeout=1).state is ShutdownState.DRAINING
    assert console.run_once() is None
    assert console.close(timeout=0).state is ShutdownState.READY
    assert console.get(queued.operation_id).status is ConsoleOperationStatus.QUEUED


@pytest.mark.parametrize("timeout", [-1, float("inf"), float("nan")])
def test_invalid_shutdown_timeout_does_not_change_admission(timeout: float) -> None:
    console = ProjectConsole(store=InMemoryConsoleOperationStore(TEAM_ID), executor=_Executor())
    with pytest.raises(ValueError):
        console.close(timeout=timeout)
    assert console.shutdown_status().state is ShutdownState.RUNNING


def test_file_store_reopens_hash_chain_and_interrupts_orphan(tmp_path: Path) -> None:
    root = tmp_path / "operations"
    at = datetime(2026, 9, 12, tzinfo=UTC)
    store = FileConsoleOperationStore(root, team_id=TEAM_ID)
    queued = store.submit(
        intent=_create_intent(tmp_path), idempotency_key="browser-action-0001", requested_at=at
    )
    running = store.claim_next(at=at + timedelta(seconds=1))
    assert running is not None

    reopened = FileConsoleOperationStore(root, team_id=TEAM_ID)
    interrupted = reopened.interrupt_running(at=at + timedelta(seconds=2))

    assert len(interrupted) == 1
    current = reopened.get(queued.operation_id)
    assert current.status is ConsoleOperationStatus.INTERRUPTED
    assert current.error_code == "HOST_INTERRUPTED"
    assert current.sequence == 3
    current.validate_integrity()


def test_file_store_rejects_rehashed_illegal_transition(tmp_path: Path) -> None:
    root = tmp_path / "operations"
    at = datetime(2026, 9, 12, tzinfo=UTC)
    store = FileConsoleOperationStore(root, team_id=TEAM_ID)
    queued = store.submit(
        intent=_create_intent(tmp_path), idempotency_key="browser-action-0001", requested_at=at
    )
    illegal = queued.model_copy(
        update={
            "status": ConsoleOperationStatus.INTERRUPTED,
            "sequence": 2,
            "updated_at": at + timedelta(seconds=1),
            "previous_operation_sha256": queued.operation_sha256,
            "error_code": "HOST_INTERRUPTED",
            "error_summary": "Rehashed but semantically invalid.",
            "operation_sha256": "0" * 64,
        }
    )
    illegal = illegal.model_copy(update={"operation_sha256": illegal.recompute_sha256()})
    record = root / queued.operation_id / "000002.json"
    record.write_text(illegal.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(ConsoleOperationConflict, match="transition is invalid"):
        FileConsoleOperationStore(root, team_id=TEAM_ID).get(queued.operation_id)
