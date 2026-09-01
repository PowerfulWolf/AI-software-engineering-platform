"""Evidence store immutability and corruption detection tests."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.evidence import (
    CommandEvidencePayload,
    CommandEvidenceRecord,
    CommandOutcome,
    EvidenceConflict,
    EvidenceCorruption,
    FileEvidenceStore,
    RunEvidenceConflict,
    RunEvidenceIdentity,
    RunEvidenceManifest,
    RunOutcome,
    seal_evidence_record,
    seal_run_manifest,
)


def _record() -> CommandEvidenceRecord:
    identity = RunEvidenceIdentity(
        project_id="project_store_001",
        task_id="task_store_001",
        run_id="run_store_001",
        agent_id="agent_store_001",
        role=AgentRole.QA,
        attempt=1,
        source_revision="a" * 40,
        context_manifest_id="ctx_" + "c" * 64,
    )
    return seal_evidence_record(
        CommandEvidenceRecord(
            evidence_id="ev_store_001",
            operation_id="command.store",
            identity=identity,
            description="store command",
            captured_at=datetime(2026, 9, 1, tzinfo=UTC),
            payload=CommandEvidencePayload(
                outcome=CommandOutcome.COMPLETED,
                argv=("pytest",),
                cwd="/tmp/worktree",
                returncode=0,
                duration_ms=1,
            ),
            record_sha256="0" * 64,
        )
    )


def test_store_is_immutable_and_exact_replay_is_idempotent(tmp_path: Path) -> None:
    store = FileEvidenceStore(tmp_path / "evidence", tmp_path / "runs")
    record = _record()
    assert store.put(record) == record
    assert store.put(record) == record

    changed = record.model_copy(update={"description": "changed"})
    changed = seal_evidence_record(changed)
    with pytest.raises(EvidenceConflict):
        store.put(changed)


def test_nonzero_digest_mismatch_is_rejected_at_model_boundary() -> None:
    record = _record()
    with pytest.raises(ValidationError, match="digest"):
        CommandEvidenceRecord.model_validate(
            record.model_copy(update={"record_sha256": "f" * 64}).to_wire()
        )


def test_store_rejects_tampered_record_and_manifest_on_replay(tmp_path: Path) -> None:
    store = FileEvidenceStore(tmp_path / "evidence", tmp_path / "runs")
    record = _record()
    store.put(record)
    path = tmp_path / "evidence" / f"{record.evidence_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["payload"]["stdout"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(EvidenceCorruption):
        store.get(record.evidence_id)

    # Restore the trusted record, then verify a modified manifest cannot replace it.
    path.write_text(json.dumps(record.to_wire()), encoding="utf-8")
    manifest = seal_run_manifest(
        RunEvidenceManifest(
            identity=record.identity,
            outcome=RunOutcome.SUCCEEDED,
            evidence_ids=(record.evidence_id,),
            started_at=record.captured_at,
            completed_at=record.captured_at,
            manifest_sha256="0" * 64,
        )
    )
    assert store.seal_run(manifest) == manifest
    changed = manifest.model_copy(update={"outcome": RunOutcome.FAILED})
    changed = seal_run_manifest(changed)
    with pytest.raises(RunEvidenceConflict):
        store.seal_run(changed)
