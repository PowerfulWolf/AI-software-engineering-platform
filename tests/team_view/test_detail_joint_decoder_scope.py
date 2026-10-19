"""One exact detail owns decoder reuse, with two complete fresh observations."""

import gc
import os
import weakref
from asyncio import CancelledError
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_software_engineer.multi_directory import store as journal_module
from ai_software_engineer.multi_directory.models import JointCheckpoint
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.team_view import reader as read_module
from ai_software_engineer.team_view.models import TeamReadError
from ai_software_engineer.team_view.read_models import TeamDetailQuery, TeamDetailStale
from tests.team_view.test_joint_history_snapshot import _fixture


def test_detail_reuses_only_exact_byte_decode_and_keeps_both_complete_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader, project, writer, _ = _fixture(tmp_path)
    expected = reader.snapshot(project.manifest.project_id).requests[0]
    query = TeamDetailQuery.from_source(
        reader.summary(project.manifest.project_id).requests[0].detail_source
    )
    paths = frozenset(writer.root.glob("delivery_multi_*/*.json"))
    observations: dict[int, read_module._JointHistorySnapshot] = {}
    journals: dict[int, JointJournal] = {}
    original = read_module._JointHistorySnapshot.history

    def observed(
        snapshot: read_module._JointHistorySnapshot, delivery_id: str
    ) -> tuple[JointCheckpoint, ...]:
        observations[id(snapshot)] = snapshot
        journals[id(snapshot._journal)] = snapshot._journal
        return original(snapshot, delivery_id)

    monkeypatch.setattr(read_module._JointHistorySnapshot, "history", observed)
    with (
        patch.object(Path, "read_bytes", autospec=True, side_effect=Path.read_bytes) as reads,
        patch.object(
            JointCheckpoint, "model_validate_json", wraps=JointCheckpoint.model_validate_json
        ) as decode,
        patch.object(
            journal_module, "_validate_successor", wraps=journal_module._validate_successor
        ) as successor,
        patch.object(
            JointCheckpoint, "model_copy", autospec=True, side_effect=JointCheckpoint.model_copy
        ) as copies,
    ):
        detail = reader.detail(query)
    assert detail.resource == expected
    assert detail.scope == query.source()
    assert Counter(call.args[0] for call in reads.call_args_list if call.args[0] in paths) == {
        path: 2 for path in paths
    }
    assert decode.call_count == len(paths), "unchanged final observation must reuse exact decoding"
    assert successor.call_count == len(paths)
    assert copies.call_count == 2 * len(paths), "public history returns keep full defensive copies"
    assert all(call.kwargs == {"deep": True} for call in copies.call_args_list)
    assert len(observations) == 2, "complete histories must be observed independently"
    assert len(journals) == 1, "only the immutable decoder crosses observations"
    assert all(not journal._verified for journal in journals.values())


def test_later_detail_and_summary_start_with_new_decoders(tmp_path: Path) -> None:
    reader, project, writer, _ = _fixture(tmp_path)
    query = TeamDetailQuery.from_source(
        reader.summary(project.manifest.project_id).requests[0].detail_source
    )
    count = len(tuple(writer.root.glob("delivery_multi_*/*.json")))
    with patch.object(
        JointCheckpoint, "model_validate_json", wraps=JointCheckpoint.model_validate_json
    ) as decode:
        first = reader.detail(query)
        assert decode.call_count == count
        second = reader.detail(query)
        assert second.resource == first.resource
        assert decode.call_count == 2 * count
        reader.summary(project.manifest.project_id)
        assert decode.call_count == 3 * count


@pytest.mark.parametrize(
    "change", ["same-size-mtime", "resealed-ancestor", "missing-ancestor", "filename", "symlink"]
)
def test_final_observation_rejects_changed_history_with_shared_decoder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    reader, project, writer, _ = _fixture(tmp_path)
    query = TeamDetailQuery.from_source(
        reader.summary(project.manifest.project_id).requests[0].detail_source
    )
    path = writer.directory("delivery_multi_retired_snapshot") / "000001.json"
    ancestor = JointCheckpoint.model_validate_json(path.read_bytes())
    original = reader._read_snapshot
    owners: list[read_module._DetailJournalReads] = []
    journals: list[JointJournal] = []

    def read(*args: object, **kwargs: object) -> object:
        owner = kwargs["joint_reads"]
        assert isinstance(owner, read_module._DetailJournalReads)
        owners.append(owner)
        result = original(*args, **kwargs)  # type: ignore[arg-type]
        assert owner._journal is not None
        journals.append(owner._journal)
        if len(owners) == 1:
            if change == "same-size-mtime":
                before = path.stat()
                payload = path.read_bytes()
                changed = payload.replace(b"Retained", b"Tampered")
                assert payload != changed and len(changed) == len(payload)
                path.write_bytes(changed)
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                assert path.stat().st_size == before.st_size
                assert path.stat().st_mtime_ns == before.st_mtime_ns
            elif change == "resealed-ancestor":
                changed_ancestor = JointCheckpoint.seal(
                    {**ancestor.to_wire(), "next_action": "Changed old source"}
                )
                path.write_text(changed_ancestor.model_dump_json())
            elif change == "missing-ancestor":
                path.unlink()
            elif change == "filename":
                path.rename(path.with_name("000000.json"))
            else:
                external = tmp_path / "external.json"
                external.write_bytes(path.read_bytes())
                path.unlink()
                path.symlink_to(external)
        return result

    monkeypatch.setattr(reader, "_read_snapshot", read)
    with pytest.raises(TeamReadError) as retained_error:
        reader.detail(query)
    assert retained_error.value.__cause__ is not None
    assert len(owners) == 2, "changed history must be inspected by a new source observation"
    assert all(owner._journal is None for owner in owners)
    assert all(not journal._verified for journal in journals)


def test_final_observation_enumerates_and_decodes_new_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader, project, writer, current = _fixture(tmp_path)
    assert writer.current(current.delivery_id) == current
    query = TeamDetailQuery.from_source(
        reader.summary(project.manifest.project_id).requests[0].detail_source
    )
    appended = JointCheckpoint.seal(
        {
            **current.to_wire(),
            "sequence": 2,
            "previous_checkpoint_sha256": current.checkpoint_sha256,
            "next_action": "New source after the complete body",
        }
    )
    original = reader._read_snapshot
    observations = 0

    def read(*args: object, **kwargs: object) -> object:
        nonlocal observations
        result = original(*args, **kwargs)  # type: ignore[arg-type]
        observations += 1
        if observations == 1:
            writer.append(appended, expected=current.checkpoint_sha256)
        return result

    monkeypatch.setattr(reader, "_read_snapshot", read)
    with (
        patch.object(
            JointCheckpoint, "model_validate_json", wraps=JointCheckpoint.model_validate_json
        ) as decode,
        pytest.raises(TeamDetailStale),
    ):
        reader.detail(query)
    assert decode.call_count == 4, "three original records plus the newly enumerated tail"


@pytest.mark.parametrize("failure", ["body", "source", "cancel"])
def test_shared_decoder_releases_models_with_retained_error_or_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    reader, project, _, _ = _fixture(tmp_path)
    query = TeamDetailQuery.from_source(
        reader.summary(project.manifest.project_id).requests[0].detail_source
    )
    original = reader._read_snapshot
    owners: list[read_module._DetailJournalReads] = []
    journals: list[JointJournal] = []
    models: list[weakref.ReferenceType[JointCheckpoint]] = []

    def read(*args: object, **kwargs: object) -> object:
        owner = kwargs["joint_reads"]
        assert isinstance(owner, read_module._DetailJournalReads)
        owners.append(owner)
        result = original(*args, **kwargs)  # type: ignore[arg-type]
        assert owner._journal is not None
        journals.append(owner._journal)
        models.extend(weakref.ref(record[2]) for record in owner._journal._verified.values())
        if len(owners) == (2 if failure == "source" else 1):
            if failure == "cancel":
                raise CancelledError()
            raise OSError("failed after the complete observation")
        return result

    monkeypatch.setattr(reader, "_read_snapshot", read)
    error_type = CancelledError if failure == "cancel" else TeamReadError
    with pytest.raises(error_type) as retained_error:
        reader.detail(query)
    assert retained_error.value.__traceback__ is not None
    assert all(owner._journal is None for owner in owners)
    assert all(not journal._verified for journal in journals)
    assert models
    gc.collect()
    assert all(model() is None for model in models), "the shared decoder cannot retain graphs"


def test_detail_journal_owner_clears_changed_root_and_empty_history(tmp_path: Path) -> None:
    _, project, _, current = _fixture(tmp_path)
    owner = read_module._DetailJournalReads()
    first = owner.journal(project.requirements_root)
    assert first.history(current.delivery_id) == (current,)
    other_root = tmp_path / "other-requirements"
    other_root.mkdir()
    second = owner.journal(other_root)
    assert second is not first and not first._verified
    assert second.history("delivery_multi_empty") == ()
    owner.clear()
    assert owner._journal is None and not second._verified


@pytest.mark.parametrize("failure", ["read", "successor"])
def test_hot_source_error_traceback_releases_original_private_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    reader, project, writer, _ = _fixture(tmp_path)
    query = TeamDetailQuery.from_source(
        reader.summary(project.manifest.project_id).requests[0].detail_source
    )
    original = reader._read_snapshot
    models: list[weakref.ReferenceType[JointCheckpoint]] = []
    path = writer.directory("delivery_multi_retired_snapshot") / "000002.json"

    def read(*args: object, **kwargs: object) -> object:
        result = original(*args, **kwargs)  # type: ignore[arg-type]
        if not models:
            owner = kwargs["joint_reads"]
            assert isinstance(owner, read_module._DetailJournalReads)
            assert owner._journal is not None
            models.extend(weakref.ref(record[2]) for record in owner._journal._verified.values())
            if failure == "read":
                external = tmp_path / "external.json"
                external.write_bytes(path.read_bytes())
                path.unlink()
                path.symlink_to(external)
            else:
                ancestor = path.with_name("000001.json")
                old = JointCheckpoint.model_validate_json(ancestor.read_bytes())
                new = JointCheckpoint.seal({**old.to_wire(), "next_action": "Resealed old source"})
                ancestor.write_text(new.model_dump_json())
        return result

    monkeypatch.setattr(reader, "_read_snapshot", read)
    with pytest.raises(TeamReadError) as retained_error:
        reader.detail(query)
    cause = retained_error.value.__cause__
    assert isinstance(cause, ValueError)
    assert cause.args == (
        "joint journal cannot traverse symlinks"
        if failure == "read"
        else "joint journal hash chain is broken",
    )
    assert cause.__traceback__ is not None
    locations = []
    trace = cause.__traceback__
    while trace is not None:
        locations.append(trace.tb_frame.f_code.co_name)
        trace = trace.tb_next
    assert "_validated_history" in locations
    assert ("_no_symlinks" if failure == "read" else "_validate_successor") in locations
    gc.collect()
    assert models and all(model() is None for model in models)


def test_decoder_eviction_preserves_complete_history(tmp_path: Path) -> None:
    _, project, writer, first = _fixture(tmp_path)
    records = [first]
    for sequence in range(2, 514):
        previous = records[-1]
        record = JointCheckpoint.seal(
            {
                **previous.to_wire(),
                "sequence": sequence,
                "previous_checkpoint_sha256": previous.checkpoint_sha256,
            }
        )
        (writer.directory(first.delivery_id) / f"{sequence:06d}.json").write_text(
            record.model_dump_json()
        )
        records.append(record)
    owner = read_module._DetailJournalReads()
    journal = owner.journal(project.requirements_root)
    assert journal.history(first.delivery_id) == tuple(records)
    assert len(journal._verified) == 512
    assert journal.history(first.delivery_id) == tuple(records)
    assert len(journal._verified) == 512
    owner.clear()
    assert not journal._verified
