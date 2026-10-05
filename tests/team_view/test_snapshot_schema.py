"""Published Team snapshot schema accepts trusted waiting facts and rejects extra input."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.enums import AgentRole, WorkItemStatus
from ai_software_engineer.team_view.models import (
    RoleQueueView,
    ScopeView,
    TaskView,
    TeamSnapshot,
)


def _schema() -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads((Path(__file__).parents[2] / "schemas/team-snapshot.schema.json").read_text()),
    )


def _snapshot() -> TeamSnapshot:
    intent_sha256 = "a" * 64
    disposition = decide_delivery_disposition(
        DeliveryFailureFacts(
            task_id="task_snapshot",
            work_item_id="work_snapshot",
            role=AgentRole.CODER,
            classification="EXECUTION_UNCERTAIN",
            source_revision="b" * 40,
            task_intent_sha256=intent_sha256,
            checkpoint_sequence=4,
            budget_available=True,
            evidence_ids=("evidence_interruption",),
        )
    )
    now = datetime(2026, 10, 5, tzinfo=UTC)
    return TeamSnapshot(
        as_of=now,
        team_id="team_snapshot",
        team_name="Snapshot contract",
        selected_project_id="project_snapshot",
        tasks=(
            TaskView(
                id="delivery_snapshot",
                project_id="project_snapshot",
                request_id="delivery_multi_snapshot",
                task_id="task_snapshot",
                task_revision=4,
                task_intent_sha256=intent_sha256,
                title="Preserved execution checkpoint",
                scope=ScopeView(
                    root="/workspace/source",
                    selected_paths=("src", "tests"),
                    delivery_id="delivery_snapshot",
                ),
                status="IMPLEMENTING",
                checkpoint_stage="DELIVERING",
                terminal=False,
                last_activity=now,
                next_action=disposition.next_action,
                role_queue=(
                    RoleQueueView(
                        work_item_id="work_snapshot",
                        role=AgentRole.CODER,
                        attempt=1,
                        status=WorkItemStatus.WAITING_DEPENDENCY,
                        wait_reason=disposition.reason,
                        wait_disposition=disposition,
                        wait_disposition_sha256=disposition.disposition_sha256,
                    ),
                ),
            ),
        ),
    )


def test_team_snapshot_published_schema_has_exact_model_parity() -> None:
    schema = _schema()
    assert schema.pop("$id") == (
        "https://ai-software-engineer.local/schemas/team-snapshot.schema.json"
    )
    assert schema.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert schema == TeamSnapshot.model_json_schema()


def test_team_snapshot_schema_accepts_exact_typed_task_and_waiting_facts() -> None:
    snapshot = _snapshot()
    payload = snapshot.to_wire()
    Draft202012Validator(_schema(), format_checker=FormatChecker()).validate(payload)

    restored = TeamSnapshot.model_validate(payload)

    assert restored == snapshot
    task = restored.tasks[0]
    assert task.task_revision == 4
    assert task.task_intent_sha256 == "a" * 64
    queue = task.role_queue[0]
    assert queue.wait_disposition is not None
    assert queue.wait_disposition.facts.task_intent_sha256 == task.task_intent_sha256
    assert queue.wait_disposition_sha256 == queue.wait_disposition.disposition_sha256


@pytest.mark.parametrize("representation", ["omitted", "null"])
def test_team_snapshot_schema_preserves_legacy_absent_optional_waiting_facts(
    representation: str,
) -> None:
    payload = json.loads(_snapshot().model_dump_json())
    task = payload["tasks"][0]
    queue = task["role_queue"][0]
    for record, fields in (
        (task, ("task_revision", "task_intent_sha256")),
        (queue, ("wait_disposition", "wait_disposition_sha256")),
    ):
        for field in fields:
            if representation == "omitted":
                record.pop(field)
            else:
                record[field] = None

    Draft202012Validator(_schema(), format_checker=FormatChecker()).validate(payload)
    restored = TeamSnapshot.model_validate(payload)

    assert restored.tasks[0].task_revision is None
    assert restored.tasks[0].task_intent_sha256 is None
    assert restored.tasks[0].role_queue[0].wait_disposition is None
    assert restored.tasks[0].role_queue[0].wait_disposition_sha256 is None


@pytest.mark.parametrize("location", ["snapshot", "task", "queue", "disposition", "facts"])
def test_team_snapshot_schema_rejects_unknown_fields_at_every_waiting_boundary(
    location: str,
) -> None:
    payload = json.loads(_snapshot().model_dump_json())
    task = payload["tasks"][0]
    queue = task["role_queue"][0]
    disposition = queue["wait_disposition"]
    selected = {
        "snapshot": payload,
        "task": task,
        "queue": queue,
        "disposition": disposition,
        "facts": disposition["facts"],
    }[location]
    selected["unrecognized_authority"] = True

    assert list(Draft202012Validator(_schema()).iter_errors(payload))
    with pytest.raises(ValidationError):
        TeamSnapshot.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_revision", "not-a-revision"),
        ("task_intent_sha256", 17),
        ("wait_disposition", "untyped disposition"),
        ("wait_disposition_sha256", {"hash": "a" * 64}),
    ],
)
def test_team_snapshot_schema_rejects_wrong_optional_field_types(field: str, value: object) -> None:
    payload = deepcopy(json.loads(_snapshot().model_dump_json()))
    task = payload["tasks"][0]
    selected = task["role_queue"][0] if field.startswith("wait_") else task
    selected[field] = value

    assert list(Draft202012Validator(_schema()).iter_errors(payload))
    with pytest.raises(ValidationError):
        TeamSnapshot.model_validate(payload)
