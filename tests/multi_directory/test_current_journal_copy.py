"""Current copies only its return while freshly validating every historical record."""

import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit
from ai_software_engineer.multi_directory.store import JointJournal


def _chain(tmp_path: Path) -> tuple[JointJournal, tuple[JointCheckpoint, ...]]:
    writer = JointJournal(tmp_path / "requirements")
    first = JointCheckpoint.seal(
        {
            "delivery_id": "delivery_multi_current_copy",
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
            "title": "Current copy",
            "submitted_at": datetime.now(UTC),
            "next_action": "Prepare the repository",
        }
    )
    writer.append(first, expected=None)
    records = [first]
    for _ in range(3):
        records.append(_append_next(writer, records[-1]))
    return writer, tuple(records)


def _append_next(writer: JointJournal, previous: JointCheckpoint) -> JointCheckpoint:
    item = JointCheckpoint.seal(
        {
            **previous.to_wire(),
            "sequence": previous.sequence + 1,
            "previous_checkpoint_sha256": previous.checkpoint_sha256,
        }
    )
    return writer.append(item, expected=previous.checkpoint_sha256)


@pytest.mark.parametrize("warm", [False, True])
def test_current_deep_copies_only_the_final_return(tmp_path: Path, warm: bool) -> None:
    writer, records = _chain(tmp_path)
    reader = JointJournal(writer.root, read_only=True)
    if warm:
        assert reader.current(records[0].delivery_id) == records[-1]
    with patch.object(
        JointCheckpoint, "model_copy", autospec=True, side_effect=JointCheckpoint.model_copy
    ) as copies:
        returned = reader.current(records[0].delivery_id)
    assert returned == records[-1]
    assert returned is not records[-1]
    assert copies.call_count == 1
    assert copies.call_args is not None
    assert copies.call_args.kwargs == {"deep": True}


@pytest.mark.parametrize("warm", [False, True])
def test_history_still_deep_copies_every_returned_record(tmp_path: Path, warm: bool) -> None:
    writer, records = _chain(tmp_path)
    reader = JointJournal(writer.root, read_only=True)
    if warm:
        assert reader.history(records[0].delivery_id) == records
    with patch.object(
        JointCheckpoint, "model_copy", autospec=True, side_effect=JointCheckpoint.model_copy
    ) as copies:
        history = reader.history(records[0].delivery_id)
    assert history == records
    assert copies.call_count == len(records)
    assert all(call.kwargs == {"deep": True} for call in copies.call_args_list)
    assert all(
        returned is not original for returned, original in zip(history, records, strict=True)
    )


def test_current_freshly_reads_every_byte_with_unchanged_validation_reuse(tmp_path: Path) -> None:
    writer, records = _chain(tmp_path)
    reader = JointJournal(writer.root, read_only=True)
    paths = tuple(sorted(writer.directory(records[0].delivery_id).glob("*.json")))
    with (
        patch.object(Path, "read_bytes", autospec=True, side_effect=Path.read_bytes) as reads,
        patch.object(
            JointCheckpoint, "model_validate_json", wraps=JointCheckpoint.model_validate_json
        ) as decode,
    ):
        assert reader.current(records[0].delivery_id) == records[-1]
        assert tuple(call.args[0] for call in reads.call_args_list) == paths
        assert decode.call_count == len(records)
        reads.reset_mock()
        assert reader.current(records[0].delivery_id) == records[-1]
        assert tuple(call.args[0] for call in reads.call_args_list) == paths
        assert decode.call_count == len(records)


def test_warm_current_observes_appends_and_only_decodes_new_records(tmp_path: Path) -> None:
    writer, records = _chain(tmp_path)
    reader = JointJournal(writer.root, read_only=True)
    assert reader.current(records[0].delivery_id) == records[-1]
    appended = _append_next(writer, records[-1])
    paths = tuple(sorted(writer.directory(records[0].delivery_id).glob("*.json")))
    with (
        patch.object(Path, "read_bytes", autospec=True, side_effect=Path.read_bytes) as reads,
        patch.object(
            JointCheckpoint, "model_validate_json", wraps=JointCheckpoint.model_validate_json
        ) as decode,
    ):
        assert reader.current(records[0].delivery_id) == appended
    assert tuple(call.args[0] for call in reads.call_args_list) == paths
    assert decode.call_count == 1


def test_warm_current_rejects_same_size_and_mtime_historical_tampering(tmp_path: Path) -> None:
    writer, records = _chain(tmp_path)
    reader = JointJournal(writer.root, read_only=True)
    assert reader.current(records[0].delivery_id) == records[-1]
    path = writer.directory(records[0].delivery_id) / "000001.json"
    before = path.stat()
    payload = path.read_bytes()
    changed = payload.replace(b"Prepare the repository", b"Prepare the repositors")
    assert changed != payload and len(changed) == len(payload)
    path.write_bytes(changed)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    with pytest.raises(ValueError, match="joint checkpoint digest mismatch"):
        reader.current(records[0].delivery_id)


@pytest.mark.parametrize(
    "change", ["missing-prefix", "missing-middle", "resealed-ancestor", "filename", "symlink"]
)
def test_warm_current_still_rejects_historical_path_and_chain_breaks(
    tmp_path: Path, change: str
) -> None:
    writer, records = _chain(tmp_path)
    reader = JointJournal(writer.root, read_only=True)
    assert reader.current(records[0].delivery_id) == records[-1]
    path = writer.directory(records[0].delivery_id) / "000001.json"
    if change == "missing-prefix":
        path.unlink()
    elif change == "missing-middle":
        path.with_name("000002.json").unlink()
    elif change == "resealed-ancestor":
        changed = JointCheckpoint.seal({**records[0].to_wire(), "next_action": "Changed old fact"})
        path.write_text(changed.model_dump_json())
    elif change == "filename":
        path.rename(path.with_name("000000.json"))
    else:
        external = tmp_path / "external.json"
        external.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(external)
    with pytest.raises(ValueError):
        reader.current(records[0].delivery_id)


def test_current_return_isolates_nested_mutations_from_cached_and_future_facts(
    tmp_path: Path,
) -> None:
    writer, records = _chain(tmp_path)
    reader = JointJournal(writer.root, read_only=True)
    returned = reader.current(records[0].delivery_id)
    assert returned is not None
    returned.attempts["coder"] = 99
    assert reader.current(records[0].delivery_id) == records[-1]
    assert reader.history(records[0].delivery_id) == records


def test_history_returns_isolate_each_nested_mutation_from_later_reads(tmp_path: Path) -> None:
    writer, records = _chain(tmp_path)
    reader = JointJournal(writer.root, read_only=True)
    returned = reader.history(records[0].delivery_id)
    returned[0].attempts["coder"] = 99
    assert all(item.attempts == {} for item in returned[1:])
    returned[-1].attempts["reviewer"] = 77
    assert reader.history(records[0].delivery_id) == records
    assert reader.current(records[0].delivery_id) == records[-1]


def test_empty_current_and_history_do_not_copy_or_read_models(tmp_path: Path) -> None:
    root = tmp_path / "requirements"
    root.mkdir()
    reader = JointJournal(root, read_only=True)
    with (
        patch.object(
            JointCheckpoint, "model_copy", autospec=True, side_effect=JointCheckpoint.model_copy
        ) as copies,
        patch.object(Path, "read_bytes", autospec=True, side_effect=Path.read_bytes) as reads,
    ):
        assert reader.current("delivery_multi_empty") is None
        assert reader.history("delivery_multi_empty") == ()
    assert copies.call_count == 0
    assert reads.call_count == 0
