"""Durable append-only Product record store contract tests."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.domain import (
    AcceptanceCriterion,
    ProductApprovalDecision,
    ProductRequirement,
    ProductSpec,
    ProductSpecApproval,
    ProductSpecStatus,
    ProjectRequest,
    ProjectRequestStatus,
    RequirementPriority,
)
from ai_software_engineer.product.models import (
    ProductDialogueActor,
    ProductDialogueRecord,
    ProductDiscoveryCheckpoint,
    ProductDiscoveryStatus,
    ProductOperationKind,
    ProductOperationRecord,
    ProjectRequestRevision,
)
from ai_software_engineer.product.store import (
    FileProductRecordStore,
    ProductRecordConflict,
    ProductRecordCorruption,
    ProductRecordIntegrityError,
    ProductRecordLineageError,
    ProductRecordNotFound,
    ProductRecordPathError,
    ProductRecordStoreError,
)

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
REQUEST_ID = "request_product_001"
PROJECT_ID = "project_product_001"


def _request(
    *,
    status: ProjectRequestStatus = ProjectRequestStatus.PRODUCT_DISCOVERY,
    updated_at: datetime = NOW,
) -> ProjectRequest:
    return ProjectRequest.create(
        request_id=REQUEST_ID,
        project_id=PROJECT_ID,
        preparation_sha256="a" * 64,
        title="Add safe export",
        original_request="Let users export one report.",
        status=status,
        created_at=NOW,
        updated_at=updated_at,
    )


def _request_revision(
    *,
    revision: int = 1,
    previous: ProjectRequestRevision | None = None,
    status: ProjectRequestStatus = ProjectRequestStatus.PRODUCT_DISCOVERY,
) -> ProjectRequestRevision:
    updated_at = NOW + timedelta(minutes=revision - 1)
    return ProjectRequestRevision.create(
        _request(status=status, updated_at=updated_at),
        revision=revision,
        supersedes_sha256=(previous.request_revision_sha256 if previous else None),
        recorded_at=updated_at,
    )


def _dialogue(
    *,
    sequence: int = 1,
    previous: ProductDialogueRecord | None = None,
    actor: ProductDialogueActor = ProductDialogueActor.HUMAN,
) -> ProductDialogueRecord:
    return ProductDialogueRecord.create(
        request_id=REQUEST_ID,
        project_id=PROJECT_ID,
        sequence=sequence,
        actor=actor,
        content="CSV is required." if actor is ProductDialogueActor.HUMAN else "Include headers?",
        previous_dialogue_sha256=(previous.dialogue_sha256 if previous else None),
        recorded_at=NOW + timedelta(minutes=sequence),
    )


def _spec(*, version: int = 1, previous: ProductSpec | None = None) -> ProductSpec:
    criterion = AcceptanceCriterion(
        id=f"ac_export_{version:02d}",
        description="The user can export a CSV report.",
        required=True,
        verification="Run the export contract test.",
        test_ids=("test_export_contract",),
    )
    return ProductSpec.create(
        spec_id=f"product_spec_export_{version:03d}",
        request_id=REQUEST_ID,
        project_id=PROJECT_ID,
        version=version,
        status=ProductSpecStatus.READY_FOR_REVIEW,
        summary="Export a report without changing source data.",
        goals=("Provide one CSV export.",),
        requirements=(
            ProductRequirement(
                id=f"req_export_{version:02d}",
                statement="Users must export one CSV report.",
                priority=RequirementPriority.MUST,
                rationale="The request explicitly requires export.",
                acceptance_criterion_ids=(criterion.id,),
            ),
        ),
        acceptance_criteria=(criterion,),
        created_at=NOW + timedelta(minutes=version + 10),
        supersedes=previous.id if previous else None,
    )


def _checkpoint(
    request_revision: ProjectRequestRevision,
    *,
    revision: int = 1,
    previous: ProductDiscoveryCheckpoint | None = None,
    dialogue: tuple[ProductDialogueRecord, ...] = (),
    status: ProductDiscoveryStatus = ProductDiscoveryStatus.PRODUCT_DISCOVERY,
    spec: ProductSpec | None = None,
    approval: ProductSpecApproval | None = None,
) -> ProductDiscoveryCheckpoint:
    return ProductDiscoveryCheckpoint.create(
        request_id=REQUEST_ID,
        project_id=PROJECT_ID,
        revision=revision,
        previous_checkpoint_sha256=previous.checkpoint_sha256 if previous else None,
        request_revision=request_revision.revision,
        request_sha256=request_revision.request.request_sha256,
        dialogue_count=len(dialogue),
        dialogue_head_sha256=dialogue[-1].dialogue_sha256 if dialogue else None,
        current_product_spec_id=spec.id if spec else None,
        current_product_spec_sha256=spec.product_spec_sha256 if spec else None,
        current_product_spec_version=spec.version if spec else None,
        current_approval_id=approval.id if approval else None,
        current_approval_sha256=approval.approval_sha256 if approval else None,
        status=status,
        updated_at=NOW + timedelta(minutes=20 + revision),
    )


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def test_dialogue_request_and_operation_round_trip_exact_replay(tmp_path: Path) -> None:
    store = FileProductRecordStore(tmp_path / "product")
    request_revision = _request_revision()
    first = _dialogue()
    second = _dialogue(sequence=2, previous=first, actor=ProductDialogueActor.PRODUCT_AGENT)
    operation = ProductOperationRecord.create(
        operation_id="human_message_001",
        request_id=REQUEST_ID,
        operation_kind=ProductOperationKind.HUMAN_MESSAGE,
        input_sha256="b" * 64,
        result_identity=first.id,
        recorded_at=NOW,
    )

    assert store.put_request_revision(request_revision) == request_revision
    assert store.put_dialogue(first) == first
    assert store.put_dialogue(second) == second
    assert store.put_operation(operation) == operation
    assert store.put_dialogue(first.model_copy()) == first
    assert store.put_operation(operation.model_copy()) == operation
    assert store.current_request_revision(REQUEST_ID) == request_revision
    assert store.list_dialogue(REQUEST_ID) == (first, second)
    assert store.find_operation(operation.operation_id) == operation
    assert store.find_operation("missing_operation_001") is None


def test_changed_identity_conflicts_and_invalid_digest_never_writes(tmp_path: Path) -> None:
    store = FileProductRecordStore(tmp_path / "product")
    request_revision = _request_revision()
    first = _dialogue()
    store.put_request_revision(request_revision)
    store.put_dialogue(first)

    changed = ProductDialogueRecord.create(
        request_id=REQUEST_ID,
        project_id=PROJECT_ID,
        sequence=1,
        actor=ProductDialogueActor.HUMAN,
        content="JSON is required.",
        previous_dialogue_sha256=None,
        recorded_at=first.recorded_at,
    )
    with pytest.raises(ProductRecordConflict, match="different content"):
        store.put_dialogue(changed)

    invalid = first.model_copy(update={"dialogue_sha256": "f" * 64})
    with pytest.raises(ProductRecordIntegrityError):
        FileProductRecordStore(tmp_path / "other").put_dialogue(invalid)


def test_store_enforces_request_dialogue_and_spec_lineage(tmp_path: Path) -> None:
    store = FileProductRecordStore(tmp_path / "product")
    first_request = _request_revision()
    store.put_request_revision(first_request)

    wrong_second = ProjectRequestRevision.create(
        ProjectRequest.create(
            request_id=REQUEST_ID,
            project_id=PROJECT_ID,
            preparation_sha256="a" * 64,
            title="Changed immutable title",
            original_request="Let users export one report.",
            status=ProjectRequestStatus.WAITING_PRODUCT_APPROVAL,
            created_at=NOW,
            updated_at=NOW + timedelta(minutes=1),
        ),
        revision=2,
        supersedes_sha256=first_request.request_revision_sha256,
        recorded_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(ProductRecordLineageError, match="ProjectRequestRevision"):
        store.put_request_revision(wrong_second)

    orphan_dialogue = _dialogue(sequence=2, previous=_dialogue())
    with pytest.raises(ProductRecordNotFound):
        store.put_dialogue(orphan_dialogue)

    first_spec = _spec()
    assert store.put_product_spec(first_spec) == first_spec
    invalid_v2 = _spec(version=2)
    with pytest.raises(ProductRecordLineageError, match="version lineage"):
        store.put_product_spec(invalid_v2)


def test_spec_approval_and_checkpoint_follow_exact_durable_references(tmp_path: Path) -> None:
    store = FileProductRecordStore(tmp_path / "product")
    request_revision = _request_revision()
    dialogue = _dialogue()
    spec = _spec()
    store.put_request_revision(request_revision)
    store.put_dialogue(dialogue)
    store.put_product_spec(spec)

    initial = _checkpoint(request_revision, dialogue=(dialogue,))
    store.put_checkpoint(initial)
    waiting = _checkpoint(
        request_revision,
        revision=2,
        previous=initial,
        dialogue=(dialogue,),
        status=ProductDiscoveryStatus.WAITING_PRODUCT_APPROVAL,
        spec=spec,
    )
    assert store.put_checkpoint(waiting) == waiting

    approval = ProductSpecApproval.create(
        spec,
        decision=ProductApprovalDecision.APPROVED,
        operator_id="user_owner_001",
        rationale="Exact requirements are accepted.",
        decided_at=NOW + timedelta(minutes=30),
    )
    assert store.put_approval(approval) == approval
    approved = _checkpoint(
        request_revision,
        revision=3,
        previous=waiting,
        dialogue=(dialogue,),
        status=ProductDiscoveryStatus.APPROVED,
        spec=spec,
        approval=approval,
    )
    assert store.put_checkpoint(approved) == approved
    assert store.current_checkpoint(REQUEST_ID) == approved
    assert store.get_product_spec(REQUEST_ID, 1) == spec
    assert store.find_product_spec(spec.id) == spec
    assert store.get_approval(REQUEST_ID, spec.id) == approval
    assert store.find_approval(approval.id) == approval


def test_approval_and_checkpoint_reject_missing_or_changed_references(tmp_path: Path) -> None:
    store = FileProductRecordStore(tmp_path / "product")
    request_revision = _request_revision()
    spec = _spec()
    store.put_request_revision(request_revision)

    approval = ProductSpecApproval.create(
        spec,
        decision=ProductApprovalDecision.REQUEST_CHANGES,
        operator_id="user_owner_001",
        rationale="Clarify the columns.",
        decided_at=NOW,
    )
    with pytest.raises(ProductRecordLineageError, match="stored ProductSpec"):
        store.put_approval(approval)

    store.put_product_spec(spec)
    bad_checkpoint = ProductDiscoveryCheckpoint.create(
        request_id=REQUEST_ID,
        project_id=PROJECT_ID,
        revision=1,
        previous_checkpoint_sha256=None,
        request_revision=1,
        request_sha256=request_revision.request.request_sha256,
        dialogue_count=1,
        dialogue_head_sha256="f" * 64,
        status=ProductDiscoveryStatus.PRODUCT_DISCOVERY,
        updated_at=NOW,
    )
    with pytest.raises(ProductRecordLineageError, match="dialogue"):
        store.put_checkpoint(bad_checkpoint)


def test_read_detects_envelope_inner_digest_and_nonfinite_corruption(tmp_path: Path) -> None:
    root = tmp_path / "product"
    store = FileProductRecordStore(root)
    revision = _request_revision()
    store.put_request_revision(revision)
    path = root / "requests" / REQUEST_ID / "00000001.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["record"]["request"]["title"] = "Tampered"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ProductRecordCorruption, match="envelope digest"):
        store.get_request_revision(REQUEST_ID, 1)

    envelope["sha256"] = hashlib.sha256(
        _canonical_json(envelope["record"]).encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ProductRecordCorruption, match="inner digest"):
        store.get_request_revision(REQUEST_ID, 1)

    path.write_text('{"record":{"revision":NaN},"sha256":"bad"}', encoding="utf-8")
    with pytest.raises(ProductRecordCorruption):
        store.get_request_revision(REQUEST_ID, 1)


def test_listing_detects_gaps_and_unexpected_files(tmp_path: Path) -> None:
    root = tmp_path / "product"
    store = FileProductRecordStore(root)
    store.put_request_revision(_request_revision())
    request_dir = root / "requests" / REQUEST_ID
    (request_dir / "garbage.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ProductRecordCorruption, match="unexpected"):
        store.current_request_revision(REQUEST_ID)


def test_store_rejects_symlink_root_record_and_replaced_directory(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    root_link = tmp_path / "root-link"
    root_link.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ProductRecordPathError, match="root cannot be a symlink"):
        FileProductRecordStore(root_link)

    store = FileProductRecordStore(actual)
    operation = ProductOperationRecord.create(
        operation_id="start_product_001",
        request_id=REQUEST_ID,
        operation_kind=ProductOperationKind.START,
        input_sha256="a" * 64,
        result_identity="request_product_001@1",
        recorded_at=NOW,
    )
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    operations = actual / "operations"
    operations.mkdir()
    (operations / "start_product_001.json").symlink_to(outside)
    with pytest.raises(ProductRecordPathError, match=r"symlink|escapes"):
        store.get_operation(operation.operation_id)

    operations.rename(actual / "old-operations")
    operations.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ProductRecordPathError, match="directory"):
        store.put_operation(operation)


def test_atomic_failure_leaves_no_partial_or_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "product"
    store = FileProductRecordStore(root)
    operation = ProductOperationRecord.create(
        operation_id="start_product_001",
        request_id=REQUEST_ID,
        operation_kind=ProductOperationKind.START,
        input_sha256="a" * 64,
        result_identity="request_product_001@1",
        recorded_at=NOW,
    )

    def fail_link(source: str | Path, target: str | Path, **kwargs: object) -> None:
        del kwargs
        raise OSError(f"cannot link {source} to {target}")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(ProductRecordStoreError, match="atomically write"):
        store.put_operation(operation)

    assert not (root / "operations/start_product_001.json").exists()
    assert tuple((root / "operations").glob("*.tmp")) == ()


def test_concurrent_first_writer_is_read_back_and_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "product"
    store = FileProductRecordStore(root)
    winner = ProductOperationRecord.create(
        operation_id="start_product_001",
        request_id=REQUEST_ID,
        operation_kind=ProductOperationKind.START,
        input_sha256="a" * 64,
        result_identity="request_product_001@1",
        recorded_at=NOW,
    )
    contender = ProductOperationRecord.create(
        operation_id=winner.operation_id,
        request_id=REQUEST_ID,
        operation_kind=ProductOperationKind.START,
        input_sha256="b" * 64,
        result_identity="request_product_001@changed",
        recorded_at=NOW,
    )

    def publish_winner(source: str | Path, target: str | Path, **kwargs: object) -> None:
        del source
        payload = winner.to_wire()
        destination_fd = kwargs["dst_dir_fd"]
        assert isinstance(destination_fd, int)
        descriptor = os.open(
            str(target),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=destination_fd,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(
                _canonical_json(
                    {
                        "record": payload,
                        "sha256": hashlib.sha256(
                            _canonical_json(payload).encode("utf-8")
                        ).hexdigest(),
                    }
                )
            )
        raise FileExistsError(str(target))

    monkeypatch.setattr(os, "link", publish_winner)
    with pytest.raises(ProductRecordConflict, match="concurrently"):
        store.put_operation(contender)
    assert store.get_operation(winner.operation_id) == winner


def test_publish_race_cannot_write_through_replaced_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "product"
    store = FileProductRecordStore(root)
    operation = ProductOperationRecord.create(
        operation_id="start_product_race_001",
        request_id=REQUEST_ID,
        operation_kind=ProductOperationKind.START,
        input_sha256="a" * 64,
        result_identity="request_product_001@1",
        recorded_at=NOW,
    )
    operations = root / "operations"
    operations.mkdir()
    moved = tmp_path / "outside-operations"
    original_link = os.link

    def replace_before_link(
        source: str | Path,
        target: str | Path,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        operations.rename(moved)
        operations.symlink_to(tmp_path, target_is_directory=True)
        original_link(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(os, "link", replace_before_link)

    with pytest.raises(ProductRecordPathError, match="changed during publish"):
        store.put_operation(operation)

    assert not (moved / f"{operation.operation_id}.json").exists()
    assert not (tmp_path / f"{operation.operation_id}.json").exists()


def test_read_race_fails_closed_when_parent_directory_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "product"
    store = FileProductRecordStore(root)
    operation = ProductOperationRecord.create(
        operation_id="start_product_read_race_001",
        request_id=REQUEST_ID,
        operation_kind=ProductOperationKind.START,
        input_sha256="a" * 64,
        result_identity="request_product_001@1",
        recorded_at=NOW,
    )
    store.put_operation(operation)

    operations = root / "operations"
    moved = tmp_path / "moved-operations"
    replacement = tmp_path / "replacement-operations"
    replacement.mkdir()
    original_open = os.open

    def replace_after_record_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if (
            os.path.basename(os.fsdecode(path)) == f"{operation.operation_id}.json"
            and dir_fd is not None
        ):
            operations.rename(moved)
            operations.symlink_to(replacement, target_is_directory=True)
        return descriptor

    monkeypatch.setattr(os, "open", replace_after_record_open)

    with pytest.raises(ProductRecordPathError, match="changed during read"):
        store.get_operation(operation.operation_id)

    assert (moved / f"{operation.operation_id}.json").is_file()
    assert not (replacement / f"{operation.operation_id}.json").exists()
