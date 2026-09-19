"""Durable Worker boundaries reject drift before touching execution state."""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.work_queue.execution_store import (
    AcceptedRoleArtifact,
    QueuedRoleStep,
    RoleQueueAdmission,
    _decode,
    record_digest,
)
from ai_software_engineer.work_queue.models import QueueArtifactReceipt
from ai_software_engineer.work_queue.ports import QueueCorruption
from tests.work_queue.test_schema import _ready_item


def test_execution_contract_schema_and_round_trip() -> None:
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/role-queue-execution.schema.json").read_text()
    )
    adapter: TypeAdapter[RoleQueueAdmission | QueuedRoleStep | AcceptedRoleArtifact] = TypeAdapter(
        RoleQueueAdmission | QueuedRoleStep | AcceptedRoleArtifact
    )
    assert {k: v for k, v in schema.items() if k not in {"$id", "$schema"}} == adapter.json_schema()
    item = _ready_item()
    records = (
        RoleQueueAdmission(
            task_id=item.task_id,
            repository_id=item.repository_id,
            allocation_sha256="a" * 64,
            legacy_artifacts=(),
        ),
        QueuedRoleStep(
            work_item=item,
            boundary=RoleRunBoundary(
                item.task_id, AgentRole.CODER, item.attempt, item.checkpoint_sequence, "main"
            ),
            allocation_sha256="a" * 64,
        ),
        AcceptedRoleArtifact(
            task_id=item.task_id,
            work_item_id=item.id,
            lease_id="lease_schema_001",
            dispatch_sequence=1,
            checkpoint_sequence=0,
            run_id="run_schema_001",
            context_manifest_id="ctx_" + "b" * 64,
            source_revision="c" * 40,
            receipt=QueueArtifactReceipt(artifact_id="art_schema_001", sha256="d" * 64),
        ),
    )
    for record in records:
        Draft202012Validator(schema).validate(record.to_wire())
        assert adapter.validate_json(record.model_dump_json()) == record
    bad = records[0].to_wire() | {"allocation_sha256": "not-a-digest"}
    assert list(Draft202012Validator(schema).iter_errors(bad))
    with pytest.raises(ValidationError):
        adapter.validate_python(bad)


@pytest.mark.parametrize(
    "role,attempt,sequence",
    [
        (AgentRole.ORCHESTRATOR, 1, 0),
        (AgentRole.CODER, 0, 0),
        (AgentRole.QA, True, 0),
        (AgentRole.REVIEWER, 1, -1),
    ],
)
def test_boundary_rejects_invalid_invocations(role: Any, attempt: Any, sequence: Any) -> None:
    with pytest.raises(ValidationError):
        RoleRunBoundary("task_schema_001", role, attempt, sequence, "main")


def test_record_decode_checks_sql_identity_as_well_as_payload_digest() -> None:
    record = RoleQueueAdmission(
        task_id="task_schema_001",
        repository_id="repository_schema_001",
        allocation_sha256="a" * 64,
        legacy_artifacts=(),
    )
    row: dict[str, object] = {
        "id": record.task_id,
        "task_id": record.task_id,
        "payload_json": record.model_dump_json(),
        "sha256": record_digest(record),
    }
    assert _decode(row, RoleQueueAdmission) == record
    for field in ("id", "task_id", "sha256"):
        with pytest.raises(QueueCorruption):
            _decode(row | {field: "wrong"}, RoleQueueAdmission)
