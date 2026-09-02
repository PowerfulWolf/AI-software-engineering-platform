"""Append-only Designer record store tests."""

import json
import os
from pathlib import Path

import pytest

import ai_software_engineer.design.store as design_store_module
from ai_software_engineer.design import (
    DesignerAgentErrorCode,
    DesignRecordConflict,
    DesignRecordCorruption,
    DesignRecordPathError,
    DesignRunOutcome,
    DesignRunRecord,
    FileDesignRecordStore,
)
from tests.design.factories import approved_facts, design_for


def test_design_and_failure_receipt_round_trip_exact_replay(tmp_path: Path) -> None:
    command, _, _ = approved_facts(tmp_path)
    design = design_for(command)
    receipt = DesignRunRecord.create(
        run_id=command.run_id,
        project_id=command.preparation.project_id,
        request_id=command.request_revision.request.id,
        context_id="ctx_" + "a" * 64,
        input_sha256="b" * 64,
        input_request_revision_sha256=command.request_revision.request_revision_sha256,
        outcome=DesignRunOutcome.FAILED,
        error_code=DesignerAgentErrorCode.INVALID_OUTPUT,
        error_message="invalid design",
        recorded_at=command.submitted_at,
    )
    store = FileDesignRecordStore(tmp_path / "design-records")

    assert store.put_design(design) == design
    assert store.put_design(design.model_copy()) == design
    assert store.get_design(design.id) == design
    assert store.find_design(design.id) == design
    assert store.put_run(receipt) == receipt
    assert store.put_run(receipt.model_copy()) == receipt
    assert store.get_run(receipt.run_id) == receipt


def test_store_rejects_changed_identity_tamper_and_symlinks(tmp_path: Path) -> None:
    command, _, _ = approved_facts(tmp_path)
    design = design_for(command)
    root = tmp_path / "design-records"
    store = FileDesignRecordStore(root)
    store.put_design(design)

    with pytest.raises(DesignRecordConflict):
        store.put_design(design_for(command, summary="A different immutable design."))

    path = root / "designs" / f"{design.id}.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["record"]["summary"] = "tampered"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(DesignRecordCorruption, match="envelope digest"):
        store.get_design(design.id)

    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "link"
    link.symlink_to(actual, target_is_directory=True)
    with pytest.raises(DesignRecordPathError, match="symlink"):
        FileDesignRecordStore(link)


def test_store_writes_all_bytes_when_os_write_is_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, _, _ = approved_facts(tmp_path)
    design = design_for(command)
    store = FileDesignRecordStore(tmp_path / "design-records")
    real_write = os.write
    short_writes = 0

    def write_part(descriptor: int, payload: bytes) -> int:
        nonlocal short_writes
        short_writes += 1
        return real_write(descriptor, payload[: max(1, len(payload) // 2)])

    monkeypatch.setattr(os, "write", write_part)

    assert store.put_design(design) == design
    assert store.get_design(design.id) == design
    assert short_writes > 1


def test_store_rejects_parent_swap_without_publishing_outside_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, _, _ = approved_facts(tmp_path)
    design = design_for(command)
    root = tmp_path / "design-records"
    store = FileDesignRecordStore(root)
    category = root / "designs"
    category.mkdir()
    displaced = root / "designs-displaced"
    outside = tmp_path / "outside"
    outside.mkdir()
    real_matches = design_store_module._directory_fd_matches_path
    swapped = False

    def swap_then_check(descriptor: int, path: Path) -> bool:
        nonlocal swapped
        if path == category and not swapped:
            swapped = True
            category.rename(displaced)
            category.symlink_to(outside, target_is_directory=True)
        return real_matches(descriptor, path)

    monkeypatch.setattr(design_store_module, "_directory_fd_matches_path", swap_then_check)

    with pytest.raises(DesignRecordPathError, match="changed during publication"):
        store.put_design(design)

    assert tuple(outside.iterdir()) == ()
    assert not (displaced / f"{design.id}.json").exists()
