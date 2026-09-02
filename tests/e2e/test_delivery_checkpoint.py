"""Contract tests for the append-only unified-delivery checkpoint journal."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.domain.enums import TaskStatus
from ai_software_engineer.project_manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
    ProjectDeliveryCheckpointConflict,
    ProjectDeliveryCheckpointCorruption,
    ProjectDeliveryCheckpointNotFound,
    ProjectDeliveryCheckpointPathError,
    ProjectDeliveryIntake,
)

NOW = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


def _checkpoint(
    root: Path,
    **updates: object,
) -> ProjectDeliveryCheckpoint:
    values: dict[str, object] = {
        "delivery_id": "delivery_alpha",
        "sequence": 1,
        "previous_checkpoint_sha256": None,
        "project_id": "project_alpha",
        "project_root": str(root.resolve()),
        "stage": DeliveryStage.PREPARING,
        "stage_attempts": DeliveryStageAttempts(),
        "next_action": DeliveryNextAction.PREPARE_PROJECT,
        "failure_code": None,
        "failure_summary": None,
    }
    if "previous" in updates:
        updates["previous_checkpoint_sha256"] = updates.pop("previous")
    values.update(updates)
    sequence = values["sequence"]
    assert isinstance(sequence, int)
    values["checkpointed_at"] = NOW + timedelta(minutes=sequence)
    return ProjectDeliveryCheckpoint.create(**values)


def _product_fields() -> dict[str, object]:
    return {
        "preparation_sha256": "a" * 64,
        "request_id": "request_alpha",
        "request_revision": 1,
        "product_checkpoint_sha256": "b" * 64,
    }


def _full_fields() -> dict[str, object]:
    return {
        **_product_fields(),
        "product_spec_id": "product_spec_alpha",
        "product_spec_sha256": "c" * 64,
        "approval_id": "product_approval_" + "d" * 64,
        "approval_sha256": "e" * 64,
        "technical_design_id": "technical_design_alpha",
        "technical_design_sha256": "f" * 64,
        "execution_plan_id": "execution_plan_alpha",
        "execution_plan_sha256": "1" * 64,
        "planning_preview_id": "planning_preview_" + "2" * 64,
        "planning_preview_sha256": "3" * 64,
        "dispatch_commit_id": "dispatch_commit_" + "4" * 64,
        "dispatch_commit_sha256": "5" * 64,
        "task_id": "task_alpha",
        "task_revision": 7,
        "task_status": TaskStatus.DONE,
        "candidate_revision": "6" * 40,
    }


def _intake(root: Path, **updates: object) -> ProjectDeliveryIntake:
    values: dict[str, object] = {
        "delivery_id": "delivery_alpha",
        "project_id": "project_alpha",
        "project_root": str(root.resolve()),
        "title": "Deliver alpha",
        "requirement": "Add deterministic alpha behavior.",
        "submitted_at": NOW,
    }
    values.update(updates)
    return ProjectDeliveryIntake.create(**values)


def test_checkpoint_has_canonical_identity_and_strict_typed_shape(tmp_path: Path) -> None:
    checkpoint = _checkpoint(tmp_path)

    assert checkpoint.checkpoint_sha256 == checkpoint.recompute_sha256()
    assert ProjectDeliveryCheckpoint.model_validate(checkpoint.to_wire()) == checkpoint
    assert checkpoint.stage_attempts.preparing == 0

    with pytest.raises(ValidationError):
        ProjectDeliveryCheckpoint.model_validate(
            {**checkpoint.to_wire(), "unexpected": "ambient authority"}
        )

    with pytest.raises(ValidationError):
        _checkpoint(tmp_path, project_root="relative/project")


def test_checkpoint_requires_complete_ordered_native_fact_references(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="product specification reference"):
        _checkpoint(tmp_path, product_spec_id="product_spec_alpha")

    with pytest.raises(ValidationError, match="approval requires"):
        _checkpoint(
            tmp_path,
            approval_id="product_approval_" + "d" * 64,
            approval_sha256="e" * 64,
        )

    with pytest.raises(ValidationError, match="dispatch commit requires"):
        _checkpoint(
            tmp_path,
            dispatch_commit_id="dispatch_commit_" + "4" * 64,
            dispatch_commit_sha256="5" * 64,
        )

    with pytest.raises(ValidationError, match="candidate revision requires"):
        _checkpoint(tmp_path, candidate_revision="6" * 40)


def test_checkpoint_status_requires_its_last_verified_native_stage(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="DELIVERING requires"):
        _checkpoint(
            tmp_path,
            stage=DeliveryStage.DELIVERING,
            next_action=DeliveryNextAction.RUN_DELIVERY,
        )

    done = _checkpoint(
        tmp_path,
        stage=DeliveryStage.DONE,
        next_action=DeliveryNextAction.NONE,
        **_full_fields(),
    )
    assert done.task_status is TaskStatus.DONE

    with pytest.raises(ValidationError, match="failure details"):
        _checkpoint(
            tmp_path,
            stage=DeliveryStage.WAITING_HUMAN,
            next_action=DeliveryNextAction.REQUEST_HUMAN,
        )


def test_store_appends_chain_returns_current_and_replays_exactly(tmp_path: Path) -> None:
    store = FileProjectDeliveryCheckpointStore(tmp_path / "checkpoints")
    first = store.put(_checkpoint(tmp_path))
    second = _checkpoint(
        tmp_path,
        sequence=2,
        previous=first.checkpoint_sha256,
        stage=DeliveryStage.PRODUCT_DISCOVERY,
        next_action=DeliveryNextAction.CONTINUE_PRODUCT_DISCOVERY,
        stage_attempts=DeliveryStageAttempts(preparing=1, product_discovery=1),
        **_product_fields(),
    )

    assert store.put(second) == second
    record_path = tmp_path / "checkpoints" / "delivery_alpha" / "0000000002.json"
    before = record_path.stat().st_mtime_ns
    assert store.put(second) == second
    assert record_path.stat().st_mtime_ns == before
    assert store.get("delivery_alpha", 1) == first
    assert store.current("delivery_alpha") == second
    assert store.list("delivery_alpha") == (first, second)


def test_store_exactly_persists_intake_outside_checkpoint_chain(tmp_path: Path) -> None:
    root = tmp_path / "checkpoints"
    store = FileProjectDeliveryCheckpointStore(root)
    intake = _intake(tmp_path)

    assert store.put_intake(intake) == intake
    assert store.put_intake(intake) == intake
    assert store.get_intake("delivery_alpha") == intake
    assert store.list("delivery_alpha") == ()

    with pytest.raises(ProjectDeliveryCheckpointConflict, match="different content"):
        store.put_intake(_intake(tmp_path, title="A different title"))

    envelope_path = root / "intakes" / "delivery_alpha.json"
    envelope = json.loads(envelope_path.read_text())
    envelope["record"]["requirement"] = "tampered"
    envelope_path.write_text(json.dumps(envelope))
    with pytest.raises(ProjectDeliveryCheckpointCorruption):
        store.get_intake("delivery_alpha")


def test_store_rejects_wrong_predecessor_gap_and_changed_replay(tmp_path: Path) -> None:
    store = FileProjectDeliveryCheckpointStore(tmp_path / "checkpoints")
    first = store.put(_checkpoint(tmp_path))

    with pytest.raises(ProjectDeliveryCheckpointConflict, match="predecessor"):
        store.put(
            _checkpoint(
                tmp_path,
                sequence=2,
                previous="f" * 64,
                stage=DeliveryStage.PRODUCT_DISCOVERY,
                next_action=DeliveryNextAction.CONTINUE_PRODUCT_DISCOVERY,
                **_product_fields(),
            )
        )

    with pytest.raises(ProjectDeliveryCheckpointConflict, match="next sequence"):
        store.put(
            _checkpoint(
                tmp_path,
                sequence=3,
                previous=first.checkpoint_sha256,
                stage=DeliveryStage.PRODUCT_DISCOVERY,
                next_action=DeliveryNextAction.CONTINUE_PRODUCT_DISCOVERY,
                **_product_fields(),
            )
        )

    with pytest.raises(ProjectDeliveryCheckpointConflict, match="different content"):
        store.put(
            _checkpoint(
                tmp_path,
                next_action=DeliveryNextAction.CONTINUE_PRODUCT_DISCOVERY,
            )
        )


def test_store_fails_closed_on_tamper_gap_and_broken_chain(tmp_path: Path) -> None:
    root = tmp_path / "checkpoints"
    store = FileProjectDeliveryCheckpointStore(root)
    first = store.put(_checkpoint(tmp_path))
    second = _checkpoint(
        tmp_path,
        sequence=2,
        previous=first.checkpoint_sha256,
        stage=DeliveryStage.PRODUCT_DISCOVERY,
        next_action=DeliveryNextAction.CONTINUE_PRODUCT_DISCOVERY,
        **_product_fields(),
    )
    store.put(second)
    path = root / "delivery_alpha" / "0000000002.json"
    envelope = json.loads(path.read_text())
    envelope["record"]["previous_checkpoint_sha256"] = "f" * 64
    path.write_text(json.dumps(envelope))

    with pytest.raises(ProjectDeliveryCheckpointCorruption):
        store.current("delivery_alpha")

    other = FileProjectDeliveryCheckpointStore(tmp_path / "gap")
    other.put(_checkpoint(tmp_path))
    directory = tmp_path / "gap" / "delivery_alpha"
    os.rename(directory / "0000000001.json", directory / "0000000002.json")
    with pytest.raises(ProjectDeliveryCheckpointCorruption, match="contiguous"):
        other.current("delivery_alpha")


def test_store_rejects_unsafe_roots_and_swapped_delivery_directory(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ProjectDeliveryCheckpointPathError):
        FileProjectDeliveryCheckpointStore(link)

    root = tmp_path / "checkpoints"
    store = FileProjectDeliveryCheckpointStore(root)
    store.put(_checkpoint(tmp_path))
    delivery = root / "delivery_alpha"
    moved = root / "moved"
    delivery.rename(moved)
    delivery.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ProjectDeliveryCheckpointPathError):
        store.current("delivery_alpha")


def test_current_missing_delivery_is_typed_and_failure_is_safe(tmp_path: Path) -> None:
    store = FileProjectDeliveryCheckpointStore(tmp_path / "checkpoints")
    with pytest.raises(ProjectDeliveryCheckpointNotFound):
        store.current("delivery_missing")

    failed = _checkpoint(
        tmp_path,
        stage=DeliveryStage.FAILED,
        next_action=DeliveryNextAction.NONE,
        failure_code=DeliveryFailureCode.INVARIANT_VIOLATION,
        failure_summary="checkpoint integrity could not be proven",
    )
    assert "secret" not in failed.to_wire()
