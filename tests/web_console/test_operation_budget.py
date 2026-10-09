"""Console operation records admit full plans under one bounded wire-byte policy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.web_console import (
    ConsoleCommandResult,
    ConsoleOperationConflict,
    ConsoleOperationStatus,
    CreateRequirementIntent,
    FileConsoleOperationStore,
)
from ai_software_engineer.web_console import store as operation_store
from tests.manager.test_execution_baseline import setup

AT = datetime(2026, 10, 9, tzinfo=UTC)
MAX_RECORD_BYTES = 16 * 1024 * 1024


def _running_store(tmp_path: Path) -> tuple[FileConsoleOperationStore, str, str]:
    store = FileConsoleOperationStore(tmp_path / "operations", team_id="team_test")
    queued = store.submit(
        intent=CreateRequirementIntent(
            project_id="project_test", name="Full snapshot", repository_roots=(str(tmp_path),)
        ),
        idempotency_key="full-snapshot-record",
        requested_at=AT,
    )
    running = store.claim_next(at=AT + timedelta(seconds=1))
    assert running is not None
    return store, queued.operation_id, running.operation_sha256


def _result(next_action: str = "Review the exact plan.") -> ConsoleCommandResult:
    return ConsoleCommandResult(
        project_id="project_test",
        stage="ENGINEERING_BASELINE_PLAN",
        next_action=next_action,
    )


def test_full_baseline_plan_reopens_and_lists_without_truncating_its_snapshot(
    tmp_path: Path,
) -> None:
    fixture = setup(tmp_path)
    # Quotes/backslashes expand on the wire. A legitimate full source snapshot
    # can therefore be much larger than a short Console command or its patch.
    (fixture.worktree.path / "src/app.py").write_text(
        '# "\\quoted retained draft"\n' * 18_000, encoding="utf-8"
    )
    plan = fixture.service.propose(fixture.target)
    result = _result().model_copy(update={"execution_baseline_plan": plan})
    store, operation_id, running_sha = _running_store(tmp_path)
    completed = store.succeed(
        operation_id, expected=running_sha, result=result, at=AT + timedelta(seconds=2)
    )
    path = store.root / operation_id / "000003.json"
    assert 2_000_000 < path.stat().st_size < MAX_RECORD_BYTES
    before = {item.name: item.read_bytes() for item in path.parent.glob("*.json")}

    reopened = FileConsoleOperationStore(store.root, team_id="team_test")
    assert reopened.get(operation_id) == completed
    assert reopened.list_current() == (completed,)
    assert completed.result is not None
    assert completed.result.execution_baseline_plan == plan
    completed.validate_integrity()
    assert {item.name: item.read_bytes() for item in path.parent.glob("*.json")} == before


@pytest.mark.parametrize("corruption", ["digest", "sequence", "identity", "malformed"])
def test_large_record_does_not_weaken_operation_integrity(tmp_path: Path, corruption: str) -> None:
    store, operation_id, running_sha = _running_store(tmp_path)
    completed = store.succeed(
        operation_id,
        expected=running_sha,
        result=_result("Retained source summary. " * 15_000),
        at=AT + timedelta(seconds=2),
    )
    path = store.root / operation_id / "000003.json"
    if corruption == "malformed":
        path.write_bytes(b"{" + b" " * 300_000)
    else:
        changed = completed.model_copy(
            update={
                "operation_sha256": "0" * 64,
                "sequence": 4 if corruption == "sequence" else completed.sequence,
                "operation_id": "operation_" + "f" * 32
                if corruption == "identity"
                else operation_id,
            }
        )
        if corruption != "digest":
            changed = changed.model_copy(update={"operation_sha256": changed.recompute_sha256()})
        path.write_text(changed.model_dump_json(indent=2), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises((ValueError, ConsoleOperationConflict)):
        store.get(operation_id)
    with pytest.raises((ValueError, ConsoleOperationConflict)):
        store.list_current()
    assert path.read_bytes() == before


def test_oversized_existing_record_is_bounded_and_not_skipped(tmp_path: Path) -> None:
    store, operation_id, _ = _running_store(tmp_path)
    path = store.root / operation_id / "000003.json"
    with path.open("wb") as stream:
        stream.write(b"{")
        stream.truncate(MAX_RECORD_BYTES + 1)
    before = path.stat()
    with pytest.raises((ValueError, ConsoleOperationConflict), match="byte budget"):
        store.get(operation_id)
    with pytest.raises((ValueError, ConsoleOperationConflict), match="byte budget"):
        store.list_current()
    assert path.stat().st_size == before.st_size
    assert path.stat().st_mtime_ns == before.st_mtime_ns


def test_oversized_finish_is_refused_before_publishing_or_creating_a_temporary_file(
    tmp_path: Path,
) -> None:
    store, operation_id, running_sha = _running_store(tmp_path)
    directory = store.root / operation_id
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    # This string's characters fit the budget, but escaping six wire bytes per
    # control character produces an operation over the serialized-byte budget.
    result = _result("\x01" * (MAX_RECORD_BYTES // 6 + 1))
    with pytest.raises(ConsoleOperationConflict, match="byte budget"):
        store.succeed(
            operation_id, expected=running_sha, result=result, at=AT + timedelta(seconds=2)
        )
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == before
    assert store.get(operation_id).status is ConsoleOperationStatus.RUNNING
    assert store.get(operation_id).operation_sha256 == running_sha
    assert not tuple(store.root.rglob(".operation-*"))


@pytest.mark.parametrize("over_by", [0, 1])
def test_admission_and_reopen_use_the_same_exact_utf8_wire_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, over_by: int
) -> None:
    store, operation_id, running_sha = _running_store(tmp_path)
    result = _result('等待检查 "\\\x01' * 1_000)
    prospective = store.get(operation_id).transition(
        ConsoleOperationStatus.SUCCEEDED, result=result, updated_at=AT + timedelta(seconds=2)
    )
    payload = prospective.model_dump_json(indent=2).encode("utf-8")
    assert len(payload) > len(prospective.model_dump_json(indent=2))
    monkeypatch.setattr(operation_store, "MAX_CONSOLE_OPERATION_BYTES", len(payload) - over_by)

    if over_by:
        with pytest.raises(ConsoleOperationConflict, match="byte budget"):
            store.succeed(
                operation_id,
                expected=running_sha,
                result=result,
                at=AT + timedelta(seconds=2),
            )
        assert not (store.root / operation_id / "000003.json").exists()
        assert store.get(operation_id).operation_sha256 == running_sha
        return
    completed = store.succeed(
        operation_id, expected=running_sha, result=result, at=AT + timedelta(seconds=2)
    )
    assert (store.root / operation_id / "000003.json").read_bytes() == payload
    assert FileConsoleOperationStore(store.root, team_id="team_test").get(operation_id) == completed
