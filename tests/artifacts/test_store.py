"""Contract tests for artifact sealing, persistence, and lineage."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.artifacts import (
    ArtifactAlreadyExists,
    ArtifactCorruption,
    ArtifactIntegrityError,
    ArtifactNotFound,
    ArtifactParentError,
    ArtifactValidationError,
    FileArtifactStore,
    SchemaVersionError,
    artifact_digest,
    seal_artifact,
)
from ai_software_engineer.domain import ArtifactIntegrity, ArtifactKind
from tests.domain.factories import (
    NOW,
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
)


def test_sealed_plan_round_trips_through_public_store(tmp_path: Path) -> None:
    artifact = seal_artifact(make_plan_artifact(), validated_at=NOW)
    store = FileArtifactStore(tmp_path)

    reference = store.put(artifact)

    assert reference.artifact_id == artifact.artifact_id
    assert reference.task_id == artifact.task_id
    assert reference.kind is ArtifactKind.PLAN
    assert reference.sha256 == artifact.integrity.sha256
    assert store.get(artifact.artifact_id) == artifact
    assert reference.path == tmp_path / "art_plan_001.json"


def test_sealing_is_deterministic_and_does_not_mutate_input() -> None:
    original = make_plan_artifact()
    sealed = seal_artifact(original, validated_at=NOW)
    sealed_again = seal_artifact(original, validated_at=NOW)

    assert original.integrity.sha256 != sealed.integrity.sha256
    assert original.integrity.validated is True
    assert sealed_again.integrity.sha256 == sealed.integrity.sha256
    assert sealed.integrity.sha256 == artifact_digest(sealed)
    assert sealed.integrity.validated_at == NOW


def test_unsealed_artifact_is_rejected_before_file_creation(tmp_path: Path) -> None:
    artifact = make_plan_artifact().model_copy(
        update={
            "integrity": ArtifactIntegrity(
                sha256="0" * 64,
                validated=False,
            )
        }
    )
    store = FileArtifactStore(tmp_path)

    with pytest.raises(ArtifactIntegrityError):
        store.put(artifact)

    assert not tuple(tmp_path.iterdir())


def test_digest_mismatch_is_rejected(tmp_path: Path) -> None:
    sealed = seal_artifact(make_plan_artifact(), validated_at=NOW)
    tampered = sealed.model_copy(
        update={
            "integrity": ArtifactIntegrity(
                sha256="f" * 64,
                validated=True,
                validated_at=NOW,
            )
        }
    )

    with pytest.raises(ArtifactIntegrityError):
        FileArtifactStore(tmp_path).put(tampered)


def test_non_standard_json_number_is_rejected_during_sealing() -> None:
    artifact = make_qa_artifact()
    invalid_content = artifact.content.model_copy(update={"environment": {"score": float("nan")}})
    invalid = artifact.model_copy(update={"content": invalid_content})

    with pytest.raises(ArtifactValidationError):
        seal_artifact(invalid, validated_at=NOW)


def test_exact_duplicate_is_idempotent_but_changed_payload_is_immutable_conflict(
    tmp_path: Path,
) -> None:
    store = FileArtifactStore(tmp_path)
    sealed = seal_artifact(make_plan_artifact(), validated_at=NOW)
    store.put(sealed)

    duplicate = store.put(sealed)
    changed = seal_artifact(
        sealed.model_copy(update={"context_manifest_id": "ctx_plan_changed"}),
        validated_at=NOW,
    )

    assert duplicate.sha256 == sealed.integrity.sha256
    with pytest.raises(ArtifactAlreadyExists):
        store.put(changed)
    assert store.get(sealed.artifact_id) == sealed


def test_parent_must_exist_and_match_task(tmp_path: Path) -> None:
    missing_parent = seal_artifact(
        make_plan_artifact().model_copy(update={"parent_artifact_ids": ("art_missing_001",)}),
        validated_at=NOW,
    )

    with pytest.raises(ArtifactParentError):
        FileArtifactStore(tmp_path).put(missing_parent)

    parent = seal_artifact(make_plan_artifact(), validated_at=NOW)
    store = FileArtifactStore(tmp_path)
    store.put(parent)
    child = seal_artifact(make_implementation_artifact(), validated_at=NOW)

    reference = store.put(child)
    assert reference.kind is ArtifactKind.IMPLEMENTATION_REPORT


def test_parent_must_belong_to_the_same_task(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path)
    parent = seal_artifact(
        make_plan_artifact().model_copy(
            update={"artifact_id": "art_plan_other", "task_id": "task_other_001"}
        ),
        validated_at=NOW,
    )
    store.put(parent)
    child = seal_artifact(
        make_implementation_artifact().model_copy(
            update={"artifact_id": "art_impl_cross", "parent_artifact_ids": (parent.artifact_id,)}
        ),
        validated_at=NOW,
    )

    with pytest.raises(ArtifactParentError):
        store.put(child)


def test_supersedes_must_be_same_kind(tmp_path: Path) -> None:
    plan = seal_artifact(make_plan_artifact(), validated_at=NOW)
    store = FileArtifactStore(tmp_path)
    store.put(plan)
    implementation = seal_artifact(
        make_implementation_artifact().model_copy(update={"supersedes": plan.artifact_id}),
        validated_at=NOW,
    )

    with pytest.raises(ArtifactParentError):
        store.put(implementation)


def test_get_reports_missing_corrupt_and_tampered_files(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path)
    with pytest.raises(ArtifactNotFound):
        store.get("art_missing_001")

    corrupt_path = tmp_path / "art_plan_001.json"
    corrupt_path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ArtifactCorruption):
        store.get("art_plan_001")
    corrupt_path.unlink()

    sealed = seal_artifact(make_plan_artifact(), validated_at=NOW)
    store.put(sealed)
    corrupt_path.write_text('{"artifact_id":"art_plan_001"}', encoding="utf-8")
    with pytest.raises(ArtifactCorruption):
        store.get("art_plan_001")


def test_get_detects_valid_json_content_tampering(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path)
    sealed = seal_artifact(make_plan_artifact(), validated_at=NOW)
    reference = store.put(sealed)
    original = reference.path.read_text(encoding="utf-8")
    tampered = original.replace("ctx_plan_001", "ctx_plan_tampered")
    assert tampered != original
    reference.path.write_text(tampered, encoding="utf-8")

    with pytest.raises(ArtifactCorruption):
        store.get(sealed.artifact_id)


def test_unsupported_schema_version_is_rejected(tmp_path: Path) -> None:
    artifact = seal_artifact(
        make_plan_artifact().model_copy(update={"schema_version": "v9.0"}),
        validated_at=NOW,
    )

    with pytest.raises(SchemaVersionError):
        FileArtifactStore(tmp_path).put(artifact)


def test_successful_write_leaves_no_temp_file(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path)
    store.put(seal_artifact(make_plan_artifact(), validated_at=datetime.now(UTC)))

    assert tuple(path.name for path in tmp_path.iterdir()) == ("art_plan_001.json",)
