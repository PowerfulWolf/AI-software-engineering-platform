"""Snapshot decoding is scoped; original bytes and current authority stay fresh."""

import asyncio
import gc
import os
import weakref
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import cast

import pytest

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.read_record_scope import (
    RecoveryRecordReads,
    current_recovery_record_reads,
)
from ai_software_engineer.team_view.models import TeamReadError, TeamSnapshot
from ai_software_engineer.team_view.reader import ProductionTeamReader
from ai_software_engineer.web_console.transport import _team_snapshot
from tests.team_view.test_baseline_snapshot import _Fixture, _fixture, _read_snapshot_fixture


def _reader() -> ProductionTeamReader:
    # Only the composition around snapshot is replaced. Real stores and the
    # complete Task projection run; no production config/SQL/model is opened.
    return ProductionTeamReader(cast(ProductionConfig, object()), {})


def _project(fixture: _Fixture, monkeypatch: pytest.MonkeyPatch) -> TeamSnapshot:
    reads, native, base, dispatch = _read_snapshot_fixture(fixture, monkeypatch)
    view = reads.read(native, base, dispatch_override=dispatch)
    return TeamSnapshot(
        as_of=datetime(2026, 10, 12, tzinfo=UTC),
        team_id="team_snapshot",
        team_name="Snapshot",
        tasks=(view,),
    )


def _counts(
    fixture: _Fixture, monkeypatch: pytest.MonkeyPatch
) -> tuple[Counter[str], Counter[str]]:
    decodes: Counter[str] = Counter()
    reads: Counter[str] = Counter()
    original_decode = KnowledgeRecordStore._decode_payload
    original_read = KnowledgeRecordStore._read_payload

    def decode[T: DomainModel](payload: bytes, model: type[T]) -> T:
        decodes[model.__name__] += 1
        return original_decode(payload, model)

    def read(store: KnowledgeRecordStore, name: str) -> bytes | None:
        if store.root == fixture.store.root:
            reads[name.split("-")[1]] += 1
        return original_read(store, name)

    monkeypatch.setattr(KnowledgeRecordStore, "_decode_payload", staticmethod(decode))
    monkeypatch.setattr(KnowledgeRecordStore, "_read_payload", read)
    return decodes, reads


def test_snapshot_reuses_actual_projection_decoding_but_reopens_all_originals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    expected = _project(fixture, monkeypatch)
    saved = {path: path.read_bytes() for path in fixture.sidecar.rglob("*.json")}
    decodes, reads = _counts(fixture, monkeypatch)
    owned: list[RecoveryRecordReads] = []

    def snapshot(reader: ProductionTeamReader, project_id: str | None) -> TeamSnapshot:
        scope = current_recovery_record_reads()
        assert scope is not None
        owned.append(scope)
        return _project(fixture, monkeypatch)

    monkeypatch.setattr(ProductionTeamReader, "_snapshot", snapshot)
    reader = _reader()
    for number in (1, 2):
        result = reader.snapshot()
        assert result.to_wire() == expected.to_wire()
        assert len(result.tasks[0].timeline) == 4
        assert decodes["ExecutionBaselinePlan"] == number
        # Engineering history intentionally retains its ordinary full list
        # decoder; only the baseline selector uses the fixed Start read port.
        assert decodes["BaselineOperationStart"] == 2 * number
        assert decodes["BaselineOperatorAuthorization"] == 2 * number
        assert reads["plans"] == reads["starts"] == reads["authorities"] == 2 * number
        assert current_recovery_record_reads() is None
        assert owned[-1].closed and owned[-1].retained_entries == owned[-1].retained_bytes == 0
    assert owned[0] is not owned[1]
    assert saved == {path: path.read_bytes() for path in fixture.sidecar.rglob("*.json")}


def test_snapshot_returned_plan_metadata_cannot_poison_later_consumers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    original = fixture.store.plan(fixture.binding.plan_sha256).to_wire()

    def snapshot(reader: ProductionTeamReader, project_id: str | None) -> TeamSnapshot:
        assert current_recovery_record_reads() is not None
        first = fixture.store.plan(fixture.binding.plan_sha256)
        first.facts.task.metadata["caller_poison"] = {"nested": ["modified"]}
        assert fixture.store.plan(fixture.binding.plan_sha256).to_wire() == original
        return _project(fixture, monkeypatch)

    monkeypatch.setattr(ProductionTeamReader, "_snapshot", snapshot)
    assert _reader().snapshot().tasks[0].task_id == fixture.task.id
    assert fixture.store.plan(fixture.binding.plan_sha256).to_wire() == original
    assert current_recovery_record_reads() is None


@pytest.mark.parametrize("change", ["same_size_mtime", "authority_missing", "symlink"])
def test_warm_snapshot_rejects_changed_complete_bytes_or_missing_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    fixture = _fixture(tmp_path)
    namespace = "baseline-authorities" if change == "authority_missing" else "baseline-plans"
    path = fixture.store.root / fixture.store.records._name(namespace, fixture.binding.plan_sha256)
    original = path.read_bytes()
    metadata = path.stat()
    owned: list[RecoveryRecordReads] = []

    def snapshot(reader: ProductionTeamReader, project_id: str | None) -> TeamSnapshot:
        scope = current_recovery_record_reads()
        assert scope is not None
        owned.append(scope)
        _project(fixture, monkeypatch)
        assert scope.retained_entries == 2
        if change == "same_size_mtime":
            changed = original.replace(b"VALUE = 2", b"VALUE = 9")
            assert changed != original and len(changed) == len(original)
            path.write_bytes(changed)
            os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        elif change == "authority_missing":
            path.unlink()
        else:
            external = tmp_path / "external-plan.json"
            external.write_bytes(original)
            path.unlink()
            path.symlink_to(external)
        fixture.store.bindings_for_task(fixture.task.id)
        raise AssertionError("changed historical bytes/authority must reject the snapshot")

    monkeypatch.setattr(ProductionTeamReader, "_snapshot", snapshot)
    with pytest.raises(TeamReadError, match="Team data unavailable"):
        _reader().snapshot()
    assert current_recovery_record_reads() is None
    assert owned[0].closed and owned[0].retained_entries == owned[0].retained_bytes == 0
    if path.is_symlink():
        path.unlink()
    path.write_bytes(original)
    assert fixture.store.bindings_for_task(fixture.task.id) == (fixture.binding,)


@pytest.mark.parametrize("failure", ["none", "validation", "read"])
def test_http_snapshot_releases_private_models_after_success_or_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    fixture = _fixture(tmp_path)
    owned: list[RecoveryRecordReads] = []
    references: list[weakref.ReferenceType[DomainModel]] = []

    def snapshot(reader: ProductionTeamReader, project_id: str | None) -> TeamSnapshot:
        scope = current_recovery_record_reads()
        assert scope is not None
        owned.append(scope)
        result = _project(fixture, monkeypatch)
        references.extend(weakref.ref(record.value) for record in scope._records.values())
        assert references and scope.retained_entries == 2
        if failure == "validation":
            raise ValueError("invalid historical projection")
        if failure == "read":

            def fail_read(store: KnowledgeRecordStore, name: str) -> bytes | None:
                raise OSError("private fixture read failed")

            monkeypatch.setattr(KnowledgeRecordStore, "_read_payload", fail_read)
            fixture.store.plan(fixture.binding.plan_sha256)
            raise AssertionError("read failure must reject")
        return result

    monkeypatch.setattr(ProductionTeamReader, "_snapshot", snapshot)
    response = asyncio.run(_team_snapshot(_reader(), None, Lock()))
    assert response.status_code == (200 if failure == "none" else 503)
    assert current_recovery_record_reads() is None
    assert owned[0].closed and owned[0].retained_entries == owned[0].retained_bytes == 0
    gc.collect()
    assert all(reference() is None for reference in references)


def test_snapshot_zero_decode_capacity_preserves_complete_results_and_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    expected = _project(fixture, monkeypatch)
    decodes, reads = _counts(fixture, monkeypatch)

    def snapshot(reader: ProductionTeamReader, project_id: str | None) -> TeamSnapshot:
        scope = current_recovery_record_reads()
        assert scope is not None
        scope.maximum_bytes = 0
        result = _project(fixture, monkeypatch)
        assert scope.retained_entries == scope.retained_bytes == 0
        return result

    monkeypatch.setattr(ProductionTeamReader, "_snapshot", snapshot)
    assert _reader().snapshot().to_wire() == expected.to_wire()
    assert decodes["ExecutionBaselinePlan"] == decodes["BaselineOperationStart"] == 2
    assert decodes["BaselineOperatorAuthorization"] == 2
    assert reads["plans"] == reads["starts"] == reads["authorities"] == 2
    assert current_recovery_record_reads() is None
