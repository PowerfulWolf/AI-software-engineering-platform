"""Unit and JSON Schema contracts for immutable Product records."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from ai_software_engineer.domain import ProjectRequest, ProjectRequestStatus
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.product.models import (
    ProductDialogueActor,
    ProductDialogueRecord,
    ProductDiscoveryCheckpoint,
    ProductDiscoveryStatus,
    ProductOperationKind,
    ProductOperationRecord,
    ProductRecordIntegrityError,
    ProjectRequestRevision,
)

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]


def _request(
    *, status: ProjectRequestStatus = ProjectRequestStatus.PRODUCT_DISCOVERY
) -> ProjectRequest:
    return ProjectRequest.create(
        request_id="request_product_001",
        project_id="project_product_001",
        preparation_sha256="a" * 64,
        title="Add safe export",
        original_request="Let users export one report.",
        status=status,
        created_at=NOW,
        updated_at=NOW,
    )


def _dialogue(
    sequence: int = 1,
    previous: str | None = None,
    *,
    actor: ProductDialogueActor = ProductDialogueActor.HUMAN,
) -> ProductDialogueRecord:
    return ProductDialogueRecord.create(
        request_id="request_product_001",
        project_id="project_product_001",
        sequence=sequence,
        actor=actor,
        content="CSV is required."
        if actor is ProductDialogueActor.HUMAN
        else "Should it include headers?",
        previous_dialogue_sha256=previous,
        recorded_at=NOW + timedelta(minutes=sequence),
    )


def test_dialogue_identity_is_deterministic_and_actor_is_explicit() -> None:
    first = _dialogue()
    replay = _dialogue()

    assert first == replay
    assert first.id == f"product_dialogue_{first.dialogue_sha256}"
    assert first.actor is ProductDialogueActor.HUMAN
    first.validate_integrity()

    changed = first.model_copy(update={"content": "JSON is required."})
    with pytest.raises(ProductRecordIntegrityError, match="identity"):
        changed.validate_integrity()


def test_dialogue_requires_exact_chain_shape_and_aware_time() -> None:
    with pytest.raises(ValidationError, match="previous digest"):
        _dialogue(sequence=2)
    with pytest.raises(ValidationError, match="cannot have a previous"):
        _dialogue(sequence=1, previous="b" * 64)
    with pytest.raises(ValidationError, match="timezone"):
        ProductDialogueRecord.create(
            request_id="request_product_001",
            project_id="project_product_001",
            sequence=1,
            actor=ProductDialogueActor.HUMAN,
            content="Need an export.",
            previous_dialogue_sha256=None,
            recorded_at=datetime(2026, 9, 2, 12, 0),
        )


def test_request_revision_seals_nested_request_and_supersedes_digest() -> None:
    first = ProjectRequestRevision.create(
        _request(), revision=1, supersedes_sha256=None, recorded_at=NOW
    )
    first.validate_integrity()
    second_request = ProjectRequest.create(
        request_id=first.request.id,
        project_id=first.request.project_id,
        preparation_sha256=first.request.preparation_sha256,
        title=first.request.title,
        original_request=first.request.original_request,
        status=ProjectRequestStatus.WAITING_PRODUCT_APPROVAL,
        created_at=first.request.created_at,
        updated_at=NOW + timedelta(minutes=2),
    )
    second = ProjectRequestRevision.create(
        second_request,
        revision=2,
        supersedes_sha256=first.request_revision_sha256,
        recorded_at=NOW + timedelta(minutes=2),
    )
    second.validate_integrity()

    with pytest.raises(ProductRecordIntegrityError, match="ProjectRequest digest"):
        ProjectRequestRevision.create(
            second_request.model_copy(update={"request_sha256": "f" * 64}),
            revision=2,
            supersedes_sha256=first.request_revision_sha256,
            recorded_at=NOW,
        )


def test_checkpoint_shapes_are_status_specific_and_digest_bound() -> None:
    initial = ProductDiscoveryCheckpoint.create(
        request_id="request_product_001",
        project_id="project_product_001",
        revision=1,
        previous_checkpoint_sha256=None,
        request_revision=1,
        request_sha256=_request().request_sha256,
        dialogue_count=0,
        dialogue_head_sha256=None,
        status=ProductDiscoveryStatus.PRODUCT_DISCOVERY,
        updated_at=NOW,
    )
    initial.validate_integrity()

    with pytest.raises(ValidationError, match="requires only a current ProductSpec"):
        ProductDiscoveryCheckpoint.create(
            request_id=initial.request_id,
            project_id=initial.project_id,
            revision=2,
            previous_checkpoint_sha256=initial.checkpoint_sha256,
            request_revision=1,
            request_sha256=initial.request_sha256,
            dialogue_count=0,
            dialogue_head_sha256=None,
            status=ProductDiscoveryStatus.WAITING_PRODUCT_APPROVAL,
            updated_at=NOW,
        )

    with pytest.raises(ProductRecordIntegrityError, match="digest"):
        initial.model_copy(update={"request_sha256": "f" * 64}).validate_integrity()


def test_operation_receipt_is_an_exact_digest_bound_replay_key() -> None:
    operation = ProductOperationRecord.create(
        operation_id="start_product_001",
        request_id="request_product_001",
        operation_kind=ProductOperationKind.START,
        input_sha256="a" * 64,
        result_identity="request_product_001@1",
        recorded_at=NOW,
    )
    operation.validate_integrity()
    with pytest.raises(ProductRecordIntegrityError, match="digest"):
        operation.model_copy(update={"input_sha256": "b" * 64}).validate_integrity()


@pytest.mark.parametrize(
    ("schema_name", "record"),
    (
        ("product-dialogue.schema.json", _dialogue()),
        (
            "product-discovery-checkpoint.schema.json",
            ProductDiscoveryCheckpoint.create(
                request_id="request_product_001",
                project_id="project_product_001",
                revision=1,
                previous_checkpoint_sha256=None,
                request_revision=1,
                request_sha256=_request().request_sha256,
                dialogue_count=0,
                dialogue_head_sha256=None,
                status=ProductDiscoveryStatus.PRODUCT_DISCOVERY,
                updated_at=NOW,
            ),
        ),
    ),
)
def test_product_records_match_json_schema(schema_name: str, record: DomainModel) -> None:
    schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    payload = record.to_wire()
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload))
    assert errors == []


def test_schemas_reject_extra_and_incomplete_status_fields() -> None:
    dialogue_schema = json.loads(
        (ROOT / "schemas/product-dialogue.schema.json").read_text(encoding="utf-8")
    )
    payload = _dialogue().to_wire() | {"session_memory": "forbidden"}
    assert list(Draft202012Validator(dialogue_schema).iter_errors(payload))

    checkpoint_schema = json.loads(
        (ROOT / "schemas/product-discovery-checkpoint.schema.json").read_text(encoding="utf-8")
    )
    checkpoint = ProductDiscoveryCheckpoint.create(
        request_id="request_product_001",
        project_id="project_product_001",
        revision=1,
        previous_checkpoint_sha256=None,
        request_revision=1,
        request_sha256=_request().request_sha256,
        dialogue_count=0,
        dialogue_head_sha256=None,
        status=ProductDiscoveryStatus.PRODUCT_DISCOVERY,
        updated_at=NOW,
    ).to_wire()
    checkpoint["status"] = "APPROVED"
    assert list(Draft202012Validator(checkpoint_schema).iter_errors(checkpoint))
