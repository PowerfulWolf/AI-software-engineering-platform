"""Continuation facts survive restart but cannot be rebound or consumed twice."""

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ai_software_engineer.orchestration.continuation_models import (
    ContinuationAdmission,
    ContinuationConflict,
    ContinuationRejected,
    ExecutionInterruptionReceipt,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.recovery.models import digest
from tests.orchestration.test_continuation_records import make_admission, make_receipt


def _store(tmp_path: Path) -> tuple[FileContinuationStore, ExecutionInterruptionReceipt]:
    receipt = make_receipt(tmp_path)
    root = tmp_path / receipt.request.task_id
    return FileContinuationStore.initialize(root, task_id=receipt.request.task_id), receipt


def test_read_only_open_never_initializes_and_exact_replay_survives_restart(
    tmp_path: Path,
) -> None:
    receipt = make_receipt(tmp_path)
    root = tmp_path / receipt.request.task_id
    with pytest.raises(ContinuationRejected):
        FileContinuationStore(root, task_id=receipt.request.task_id)
    assert not root.exists()
    store = FileContinuationStore.initialize(root, task_id=receipt.request.task_id)
    assert store.receipt_for_task(receipt.request.task_id) is None
    assert store.put_receipt(receipt) == receipt
    admission = make_admission(receipt)
    assert store.put_admission(admission) == admission
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    reopened = FileContinuationStore(root, task_id=receipt.request.task_id)
    assert reopened.put_receipt(receipt) == receipt
    assert reopened.get_receipt(receipt.request.run_id) == receipt
    assert reopened.receipt_for_task(receipt.request.task_id) == receipt
    assert reopened.put_admission(admission) == admission
    assert reopened.get_admission(receipt.request.task_id) == admission
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in root.iterdir())


def test_task_root_run_and_admission_aliases_never_grant_a_second_use(tmp_path: Path) -> None:
    store, receipt = _store(tmp_path)
    store.put_receipt(receipt)
    admission = make_admission(receipt)
    store.put_admission(admission)
    with pytest.raises(ContinuationRejected):
        store.get_receipt("run_foreign_001")
    with pytest.raises(ContinuationRejected):
        store.get_admission("task_foreign_001")
    with pytest.raises(ContinuationRejected):
        FileContinuationStore(tmp_path / receipt.request.task_id, task_id="task_foreign_001")
    changed = admission.new_request.model_copy(update={"run_id": "run_second_001"})
    second = ContinuationAdmission.create(**{**admission.to_wire(), "new_request": changed})
    with pytest.raises(ContinuationConflict):
        store.put_admission(second)
    assert store.get_admission(receipt.request.task_id) == admission


@pytest.mark.parametrize("field", ["scope", "receipt_sha256", "policy_sha256"])
def test_admission_cross_scope_or_receipt_rebinding_is_rejected_before_publication(
    tmp_path: Path, field: str
) -> None:
    store, receipt = _store(tmp_path)
    store.put_receipt(receipt)
    admission = make_admission(receipt)
    value: object = "f" * 64
    if field == "scope":
        value = receipt.scope.model_copy(update={"repository_id": "repository_foreign"})
    changed = ContinuationAdmission.create(**{**admission.to_wire(), field: value})
    with pytest.raises(ContinuationRejected, match="exact receipt"):
        store.put_admission(changed)
    assert not (tmp_path / receipt.request.task_id / "admission.json").exists()


def test_missing_parent_and_symlink_placement_never_create_an_outside_store(
    tmp_path: Path,
) -> None:
    task_id = "task_continuation_001"
    with pytest.raises(ContinuationRejected):
        FileContinuationStore.initialize(tmp_path / "missing" / task_id, task_id=task_id)
    assert not (tmp_path / "missing").exists()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ContinuationRejected):
        FileContinuationStore.initialize(link / task_id, task_id=task_id)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize(
    "tamper", ["envelope", "inner_hash", "duplicate_key", "symlink", "fifo", "root_swap"]
)
def test_corruption_is_never_reported_as_absent_or_used_for_continuation(
    tmp_path: Path, tamper: str
) -> None:
    store, receipt = _store(tmp_path)
    store.put_receipt(receipt)
    root = tmp_path / receipt.request.task_id
    path = root / "receipt.json"
    if tamper == "root_swap":
        root.rename(tmp_path / "original")
        root.mkdir(mode=0o700)
    elif tamper == "duplicate_key":
        path.write_text('{"record":{},"record":{},"sha256":"' + "0" * 64 + '"}')
    elif tamper in ("envelope", "inner_hash"):
        envelope = json.loads(path.read_text())
        envelope["record"]["inventory_after_sha256"] = "f" * 64
        if tamper == "inner_hash":
            envelope["sha256"] = digest(envelope["record"])
        path.write_text(json.dumps(envelope))
    else:
        path.unlink()
        if tamper == "fifo":
            os.mkfifo(path, mode=0o600)
        else:
            outside = tmp_path / "outside"
            outside.write_text("private fixture")
            path.symlink_to(outside)
    with pytest.raises(ContinuationRejected):
        store.receipt_for_task(receipt.request.task_id)


def test_concurrent_replacements_have_one_winner_without_overwriting_history(
    tmp_path: Path,
) -> None:
    store, receipt = _store(tmp_path)
    store.put_receipt(receipt)

    def publish(index: int) -> str:
        admission = make_admission(receipt)
        replacement = admission.new_request.model_copy(update={"run_id": f"run_new_{index:03}"})
        record = ContinuationAdmission.create(**{**admission.to_wire(), "new_request": replacement})
        reopened = FileContinuationStore(
            tmp_path / receipt.request.task_id, task_id=receipt.request.task_id
        )
        try:
            return reopened.put_admission(record).new_request.run_id
        except ContinuationConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(publish, (1, 2)))
    assert results.count("conflict") == 1
    assert store.get_admission(receipt.request.task_id).new_request.run_id in results
    assert not list((tmp_path / receipt.request.task_id).glob(".pending-*"))


def test_publication_crash_replay_preserves_the_first_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, receipt = _store(tmp_path)
    store.put_receipt(receipt)
    admission = make_admission(receipt)
    original = os.link

    def fail_after_link(
        src: str, dst: str, *, src_dir_fd: int, dst_dir_fd: int, follow_symlinks: bool
    ) -> None:
        original(
            src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks
        )
        raise OSError("simulated process stop after publication")

    monkeypatch.setattr(os, "link", fail_after_link)
    with pytest.raises(ContinuationRejected):
        store.put_admission(admission)
    monkeypatch.setattr(os, "link", original)
    assert store.put_admission(admission) == admission
    assert not list((tmp_path / receipt.request.task_id).glob(".pending-*"))
