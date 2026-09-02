"""Immutable ProjectPreparation store contract tests."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.domain import ProjectPreparation
from ai_software_engineer.project_manager.store import (
    FileProjectPreparationStore,
    ProjectPreparationConflict,
    ProjectPreparationCorruption,
    ProjectPreparationIntegrityError,
    ProjectPreparationNotFound,
    ProjectPreparationPathError,
    ProjectPreparationStoreError,
)

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _preparation(tmp_path: Path, *, prepared_at: datetime = NOW) -> ProjectPreparation:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    return ProjectPreparation.create(
        organization_id="organization_store_001",
        project_id="project_store_001",
        project_root=str(project),
        project_workspace_root=str(tmp_path / "sidecars" / "project_store_001"),
        organization_root=str(tmp_path / "organization"),
        project_profile_sha256="a" * 64,
        runtime_binding_sha256="b" * 64,
        baseline_spec_sha256="c" * 64,
        baseline_source_uris=("platform://hard-safety/v1",),
        prepared_at=prepared_at,
    )


def _record_path(root: Path) -> Path:
    return root / "project-preparation-project_store_001.json"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def test_store_round_trips_and_exact_replay_returns_first_record(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    before = tuple(project.iterdir())
    preparation = _preparation(tmp_path)
    policy_root = tmp_path / "sidecars" / "project_store_001" / "policy"
    store = FileProjectPreparationStore(policy_root)

    first = store.put(preparation)
    replay = store.put(preparation.model_copy())

    assert first == preparation
    assert replay == first
    assert store.get(preparation.project_id) == first
    assert store.find(preparation.project_id) == first
    assert tuple(project.iterdir()) == before
    record = json.loads(_record_path(policy_root).read_text(encoding="utf-8"))
    assert set(record) == {"preparation", "sha256"}


def test_store_rejects_changed_content_under_existing_project_identity(tmp_path: Path) -> None:
    preparation = _preparation(tmp_path)
    store = FileProjectPreparationStore(tmp_path / "policy")
    assert store.put(preparation) == preparation
    changed = _preparation(tmp_path, prepared_at=NOW + timedelta(minutes=1))

    with pytest.raises(ProjectPreparationConflict, match="different content"):
        store.put(changed)

    assert store.get(preparation.project_id) == preparation


def test_store_rejects_invalid_stage_digest_before_writing(tmp_path: Path) -> None:
    preparation = _preparation(tmp_path).model_copy(update={"preparation_sha256": "f" * 64})
    policy_root = tmp_path / "policy"
    store = FileProjectPreparationStore(policy_root)

    with pytest.raises(ProjectPreparationIntegrityError, match="digest mismatch"):
        store.put(preparation)

    assert not _record_path(policy_root).exists()


def test_store_detects_record_and_stage_digest_tampering(tmp_path: Path) -> None:
    preparation = _preparation(tmp_path)
    policy_root = tmp_path / "policy"
    store = FileProjectPreparationStore(policy_root)
    store.put(preparation)
    record_path = _record_path(policy_root)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["preparation"]["baseline_spec_sha256"] = "d" * 64
    record_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ProjectPreparationCorruption, match="record digest mismatch"):
        store.get(preparation.project_id)

    record["sha256"] = hashlib.sha256(
        _canonical_json(record["preparation"]).encode("utf-8")
    ).hexdigest()
    record_path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ProjectPreparationCorruption, match="digest mismatch"):
        store.get(preparation.project_id)


@pytest.mark.parametrize(
    "payload",
    (
        "not json",
        "[]",
        '{"preparation":{},"sha256":"missing-stage-contract"}',
        '{"preparation":{},"sha256":"0","unknown":true}',
    ),
)
def test_store_rejects_malformed_records(tmp_path: Path, payload: str) -> None:
    preparation = _preparation(tmp_path)
    policy_root = tmp_path / "policy"
    store = FileProjectPreparationStore(policy_root)
    _record_path(policy_root).write_text(payload, encoding="utf-8")

    with pytest.raises(ProjectPreparationCorruption):
        store.get(preparation.project_id)


def test_store_maps_non_finite_json_to_typed_corruption(tmp_path: Path) -> None:
    preparation = _preparation(tmp_path)
    policy_root = tmp_path / "policy"
    store = FileProjectPreparationStore(policy_root)
    _record_path(policy_root).write_text(
        '{"preparation":{"project_root":NaN},"sha256":"invalid"}',
        encoding="utf-8",
    )

    with pytest.raises(ProjectPreparationCorruption):
        store.get(preparation.project_id)


def test_find_only_converts_absence_to_none(tmp_path: Path) -> None:
    policy_root = tmp_path / "policy"
    store = FileProjectPreparationStore(policy_root)
    assert store.find("project_store_001") is None

    _record_path(policy_root).write_text("{", encoding="utf-8")
    with pytest.raises(ProjectPreparationCorruption):
        store.find("project_store_001")


def test_invalid_identity_cannot_select_a_path(tmp_path: Path) -> None:
    store = FileProjectPreparationStore(tmp_path / "policy")

    with pytest.raises(ProjectPreparationNotFound):
        store.get("../../outside")


def test_store_rejects_symlink_root_and_record(tmp_path: Path) -> None:
    actual_root = tmp_path / "actual-policy"
    actual_root.mkdir()
    symlink_root = tmp_path / "policy-link"
    symlink_root.symlink_to(actual_root, target_is_directory=True)
    with pytest.raises(ProjectPreparationPathError, match="root cannot be a symlink"):
        FileProjectPreparationStore(symlink_root)

    store = FileProjectPreparationStore(actual_root)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    _record_path(actual_root).symlink_to(outside)
    with pytest.raises(ProjectPreparationPathError, match="record cannot be a symlink"):
        store.get("project_store_001")


def test_find_rejects_record_path_that_is_not_a_file(tmp_path: Path) -> None:
    policy_root = tmp_path / "policy"
    store = FileProjectPreparationStore(policy_root)
    _record_path(policy_root).mkdir()

    with pytest.raises(ProjectPreparationPathError, match="record path is not a file"):
        store.find("project_store_001")


def test_atomic_failure_leaves_no_record_or_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preparation = _preparation(tmp_path)
    policy_root = tmp_path / "policy"
    store = FileProjectPreparationStore(policy_root)

    def fail_link(source: str | Path, target: str | Path) -> None:
        raise OSError(f"cannot link {source} to {target}")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(ProjectPreparationStoreError, match="atomically write"):
        store.put(preparation)

    assert not _record_path(policy_root).exists()
    assert tuple(policy_root.glob("*.tmp")) == ()


def test_concurrent_first_writer_cannot_be_overwritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    winner = _preparation(tmp_path)
    contender = _preparation(tmp_path, prepared_at=NOW + timedelta(minutes=1))
    policy_root = tmp_path / "policy"
    store = FileProjectPreparationStore(policy_root)

    def publish_winner_then_report_collision(source: str | Path, target: str | Path) -> None:
        del source
        preparation_payload = winner.to_wire()
        record = {
            "preparation": preparation_payload,
            "sha256": hashlib.sha256(
                _canonical_json(preparation_payload).encode("utf-8")
            ).hexdigest(),
        }
        Path(target).write_text(_canonical_json(record), encoding="utf-8")
        raise FileExistsError(str(target))

    monkeypatch.setattr(os, "link", publish_winner_then_report_collision)
    with pytest.raises(ProjectPreparationConflict, match="concurrently created"):
        store.put(contender)

    assert store.get(winner.project_id) == winner
