"""Idle dispatch avoids model replay, not byte/path/corruption checks."""

import os
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.web_console import (
    ConsoleOperation,
    ConsoleOperationConflict,
    FileConsoleOperationStore,
)
from tests.web_console.test_operation_budget import AT, _result, _running_store


def _completed(tmp_path: Path) -> FileConsoleOperationStore:
    store, operation_id, running_sha = _running_store(tmp_path)
    store.succeed(
        operation_id, expected=running_sha, result=_result(), at=AT + timedelta(seconds=2)
    )
    return store


def test_idle_rechecks_full_bytes_without_replaying_unchanged_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _completed(tmp_path)
    calls = [0]
    original = store._list_current

    def counted() -> tuple[ConsoleOperation, ...]:
        calls[0] += 1
        return original()

    monkeypatch.setattr(store, "_list_current", counted)
    before = {path: path.read_bytes() for path in store.root.rglob("*.json")}
    for _ in range(3):
        assert store.claim_next(at=AT + timedelta(seconds=3)) is None
    assert calls[0] == 1
    assert before == {path: path.read_bytes() for path in store.root.rglob("*.json")}
    assert len(store.list_current()) == 1
    assert calls[0] == 2, "history GET always verifies its current full facts"


def test_new_operation_from_another_store_is_discovered(tmp_path: Path) -> None:
    from tests.web_console.test_core import _create_intent

    store = _completed(tmp_path)
    assert store.claim_next(at=AT + timedelta(seconds=3)) is None
    other = FileConsoleOperationStore(store.root, team_id=store.team_id)
    submitted = other.submit(
        intent=_create_intent(tmp_path), idempotency_key="external-new", requested_at=AT
    )
    claimed = store.claim_next(at=AT + timedelta(seconds=4))
    assert claimed is not None and claimed.operation_id == submitted.operation_id
    assert other.claim_next(at=AT + timedelta(seconds=4)) is None


def test_same_length_and_mtime_history_tampering_invalidates_idle_result(tmp_path: Path) -> None:
    store = _completed(tmp_path)
    assert store.claim_next(at=AT + timedelta(seconds=3)) is None
    path = next(store.root.glob("operation_*/000001.json"))
    before = path.stat()
    original = path.read_bytes()
    tampered = original.replace(b'"team_test"', b'"team_fail"')
    assert tampered != original and len(tampered) == len(original)
    path.write_bytes(tampered)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises((ValueError, ConsoleOperationConflict)):
        store.claim_next(at=AT + timedelta(seconds=4))
    assert path.read_bytes() == tampered


@pytest.mark.parametrize("change", ["symlink", "missing_parent"])
def test_idle_result_cannot_hide_changed_history_paths(tmp_path: Path, change: str) -> None:
    store = _completed(tmp_path)
    assert store.claim_next(at=AT + timedelta(seconds=3)) is None
    path = next(store.root.glob("operation_*/000001.json"))
    target = tmp_path / "original.json"
    path.rename(target)
    if change == "symlink":
        path.symlink_to(target)
    with pytest.raises((ValueError, ConsoleOperationConflict)):
        store.claim_next(at=AT + timedelta(seconds=4))
