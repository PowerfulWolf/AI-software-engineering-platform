from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.web_console import (
    ConsoleCommandRejected,
    ConsoleCommandResult,
    ConsoleOperationConflict,
    ConsoleOperationStatus,
    CreateRequirementIntent,
    FileConsoleOperationStore,
    InMemoryConsoleOperationStore,
    ProductReplyIntent,
    ProjectConsole,
)

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
