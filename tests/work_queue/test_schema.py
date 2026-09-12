"""Wire-schema coverage for persistent queue facts."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from ai_software_engineer.domain import (
    AgentRole,
    BrainTier,
    ModelRouteReason,
    RiskTier,
    WorkItemStatus,
)
from ai_software_engineer.domain.workforce import ModelSelection, RoleAssignment, TaskLease
from ai_software_engineer.work_queue import (
    DispatcherTickResult,
    DispatcherTickStatus,
    QueueArtifactReceipt,
    QueueClaim,
    QueueCompletion,
    QueuedWorkItem,
)

SCHEMA_DIR = Path(__file__).parents[2] / "schemas"
NOW = datetime(2026, 9, 8, 16, 0, tzinfo=UTC)


def _assert_valid(payload: Mapping[str, object], schema_name: str) -> None:
    schemas = [
        cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
        for path in SCHEMA_DIR.glob("*.schema.json")
    ]
    by_name = {cast(str, schema["$id"]).rsplit("/", 1)[-1]: schema for schema in schemas}
    registry = Registry().with_resources(
        (cast(str, schema["$id"]), Resource.from_contents(schema)) for schema in schemas
    )
    errors = list(
        Draft202012Validator(
            by_name[schema_name], registry=registry, format_checker=FormatChecker()
        ).iter_errors(payload)
    )
    assert errors == [], [error.message for error in errors]


def _ready_item() -> QueuedWorkItem:
    return QueuedWorkItem(
        id="work_schema_coder_001",
        task_id="task_schema_queue_001",
        repository_id="repository_schema_queue_001",
        role=AgentRole.CODER,
        attempt=1,
        checkpoint_sequence=0,
        dispatch_sequence=0,
        repository_scopes=("/code/api",),
        status=WorkItemStatus.READY,
        priority=600,
        risk=RiskTier.NORMAL,
        required_capabilities=("python",),
        created_at=NOW,
        updated_at=NOW,
    )


def test_queue_item_claim_and_completion_match_canonical_schema() -> None:
    ready = _ready_item()
    leased = ready.model_copy(update={"status": WorkItemStatus.LEASED})
    assignment = RoleAssignment(
        id="assignment_schema_queue_001",
        repository_id=ready.repository_id,
        task_id=ready.task_id,
        agent_id="agent_schema_coder_001",
        role=ready.role,
        attempt=ready.attempt,
        lease_id="lease_schema_queue_001",
        assigned_at=NOW,
    )
    lease = TaskLease(
        id=assignment.lease_id,
        assignment_id=assignment.id,
        task_id=ready.task_id,
        agent_id=assignment.agent_id,
        acquired_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    selection = ModelSelection(
        policy_id="model_policy_schema_queue_001",
        policy_version="v1",
        provider="codex",
        model="gpt-5.5",
        tier=BrainTier.STANDARD,
        reasons=(ModelRouteReason.DEFAULT,),
        selected_at=NOW,
    )
    claim = QueueClaim(
        work_item=leased,
        assignment=assignment,
        lease=lease,
        model_selection=selection,
        worker_id="worker_schema_queue_001",
        claimed_at=NOW,
    )
    closed = leased.model_copy(update={"status": WorkItemStatus.CLOSED})
    completion = QueueCompletion(
        work_item=closed,
        artifacts=(QueueArtifactReceipt(artifact_id="artifact_impl", sha256="a" * 64),),
        completed_at=NOW + timedelta(minutes=1),
    )

    _assert_valid(ready.to_wire(), "workforce.schema.json")
    _assert_valid(ready.to_wire(), "work-queue.schema.json")
    _assert_valid(claim.to_wire(), "work-queue.schema.json")
    _assert_valid(completion.to_wire(), "work-queue.schema.json")
    _assert_valid(
        DispatcherTickResult(
            status=DispatcherTickStatus.DISPATCHED,
            claim=claim,
            lease_owner_token="not-persisted-or-serialized",
            ticked_at=NOW,
        ).to_wire(),
        "work-queue.schema.json",
    )
    _assert_valid(
        DispatcherTickResult(
            status=DispatcherTickStatus.IDLE,
            reclaimed_work_item_ids=(ready.id,),
            ticked_at=NOW,
        ).to_wire(),
        "work-queue.schema.json",
    )
