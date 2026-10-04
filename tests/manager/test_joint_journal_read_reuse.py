"""Repeated recovery reads reuse exact bytes, never stale or mutable journal facts."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit
from ai_software_engineer.multi_directory.store import JointJournal


def _first(tmp_path: Path) -> JointCheckpoint:
    return JointCheckpoint.seal(
        {
            "delivery_id": "delivery_multi_read_reuse",
            "team_id": "team_test",
            "team_manifest_sha256": "0" * 64,
            "project_id": "project_test",
            "project_manifest_sha256": "1" * 64,
            "sequence": 1,
            "stage": JointStage.PREPARING,
            "scope": DirectoryScope(
                units=(
                    DirectoryUnit(
                        id="unit_" + "a" * 16,
                        root=str(tmp_path / "repository"),
                        selected_paths=(".",),
                        base_revision="a" * 40,
                    ),
                )
            ),
            "title": "Read reuse",
            "submitted_at": datetime.now(UTC),
            "next_action": "Prepare the repository",
        }
    )


def test_same_bytes_are_decoded_once_and_appends_are_visible(tmp_path: Path) -> None:
    writer = JointJournal(tmp_path / "requirements")
    first = _first(tmp_path)
    writer.append(first, expected=None)
    reader = JointJournal(writer.root, read_only=True)
    with patch.object(
        JointCheckpoint, "model_validate_json", wraps=JointCheckpoint.model_validate_json
    ) as decode:
        assert reader.current(first.delivery_id) == first
        assert reader.current(first.delivery_id) == first
        assert decode.call_count == 1
        second = JointCheckpoint.seal(
            {
                **first.to_wire(),
                "sequence": 2,
                "previous_checkpoint_sha256": first.checkpoint_sha256,
                "next_action": "Prepare again",
            }
        )
        # Write through a distinct validated journal instance.
        writer.append(second, expected=first.checkpoint_sha256)
        before = decode.call_count
        assert reader.current(first.delivery_id) == second
        assert decode.call_count == before + 1


def test_returned_nested_dict_cannot_poison_cached_facts(tmp_path: Path) -> None:
    writer = JointJournal(tmp_path / "requirements")
    first = _first(tmp_path)
    writer.append(first, expected=None)
    reader = JointJournal(writer.root, read_only=True)
    returned = reader.current(first.delivery_id)
    assert returned is not None
    returned.attempts["coder"] = 99
    assert reader.current(first.delivery_id) == first


@pytest.mark.parametrize("change", ["body", "resealed-ancestor", "missing-initial", "symlink"])
def test_warm_cache_rechecks_historical_bytes_and_paths(tmp_path: Path, change: str) -> None:
    writer = JointJournal(tmp_path / "requirements")
    first = _first(tmp_path)
    writer.append(first, expected=None)
    second = JointCheckpoint.seal(
        {
            **first.to_wire(),
            "sequence": 2,
            "previous_checkpoint_sha256": first.checkpoint_sha256,
        }
    )
    writer.append(second, expected=first.checkpoint_sha256)
    reader = JointJournal(writer.root, read_only=True)
    assert reader.current(first.delivery_id) == second
    path = writer.directory(first.delivery_id) / "000001.json"
    if change == "body":
        wire = json.loads(path.read_text())
        wire["title"] = "tampered title"
        path.write_text(json.dumps(wire))
    elif change == "resealed-ancestor":
        changed = JointCheckpoint.seal({**first.to_wire(), "next_action": "Changed old fact"})
        path.write_text(changed.model_dump_json())
    elif change == "missing-initial":
        path.unlink()
    else:
        external = tmp_path / "external.json"
        external.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(external)
    with pytest.raises(ValueError):
        reader.current(first.delivery_id)


def test_validation_cache_has_a_fixed_bound(tmp_path: Path) -> None:
    writer = JointJournal(tmp_path / "requirements")
    first = _first(tmp_path)
    previous = first
    for sequence in range(1, 515):
        item = (
            first
            if sequence == 1
            else JointCheckpoint.seal(
                {
                    **first.to_wire(),
                    "sequence": sequence,
                    "previous_checkpoint_sha256": previous.checkpoint_sha256,
                }
            )
        )
        path = writer.directory(item.delivery_id) / f"{sequence:06d}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(item.model_dump_json())
        previous = item
    reader = JointJournal(writer.root, read_only=True)
    assert reader.current(first.delivery_id) == previous
    assert len(reader._verified) == 512
