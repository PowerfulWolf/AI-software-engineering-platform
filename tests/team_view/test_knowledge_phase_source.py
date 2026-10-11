"""Read-side source follows the exact claim and shared pure baseline overlay."""

import json
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.domain.enums import AgentRole, WorkItemStatus
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.workforce import TaskLease
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.team_view.knowledge_preparation import (
    RoleExecutionScope,
    read_claim_source,
)
from ai_software_engineer.work_queue.baseline import BaselineQueueConsumption, resolve_step_overlays
from ai_software_engineer.work_queue.execution_store import QueuedRoleStep, record_digest
from ai_software_engineer.work_queue.ports import QueueCorruption
from tests.manager.test_execution_baseline import authorize, setup
from tests.team_view.test_knowledge_preparation_phase import fixture


@dataclass(frozen=True)
class Saved:
    original: QueuedRoleStep
    record: BaselineQueueConsumption
    lease: TaskLease


@pytest.fixture(scope="module")
def saved(tmp_path_factory: pytest.TempPathFactory) -> Saved:
    root = tmp_path_factory.mktemp("knowledge-source")
    baseline = setup(root)
    facts = baseline.collector.facts
    facts = facts.model_copy(
        update={"scope": facts.scope.model_copy(update={"repository_id": "repository_phase"})}
    )
    baseline.collector.facts = facts.model_copy(
        update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    plan = baseline.service.propose(baseline.target)
    binding = baseline.service.execute(plan.plan_sha256, authority=authorize(plan))
    sample = fixture(root)
    item = type(sample.item).model_validate(
        {
            **sample.item.to_wire(),
            "id": facts.work_item_id,
            "task_id": facts.task.id,
            "repository_id": binding.scope.repository_id,
            "repository_scopes": (binding.scope.repository_root,),
            "attempt": facts.task.attempts,
            "checkpoint_sequence": facts.checkpoint_sequence,
            "dispatch_sequence": 0,
            "status": WorkItemStatus.READY,
        }
    )
    original = QueuedRoleStep(
        work_item=item,
        allocation_sha256="a" * 64,
        boundary=RoleRunBoundary(
            item.task_id,
            AgentRole.CODER,
            item.attempt,
            item.checkpoint_sequence,
            binding.prior_source_revision,
        ),
    )
    record = BaselineQueueConsumption(
        task_id=item.task_id,
        work_item_id=item.id,
        next_work_item_id=item.id,
        prior_step_sha256=record_digest(original),
        plan=plan,
        binding=binding,
    )
    lease = sample.claim.lease.model_copy(
        update={
            "task_id": item.task_id,
            "acquired_at": binding.completed_at + timedelta(seconds=1),
            "expires_at": binding.completed_at + timedelta(minutes=10),
        }
    )
    return Saved(original, record, lease)


def _row(record: DomainModel, identity: str, task_id: str) -> dict[str, object]:
    return {
        "id": identity,
        "task_id": task_id,
        "payload_json": record.model_dump_json(),
        "sha256": record_digest(record),
    }


class Cursor:
    def __init__(self, saved: Saved, *, baseline_sha: str | None) -> None:
        self.saved, self.baseline_sha = saved, baseline_sha
        self.rows: list[dict[str, object]] = []

    def execute(self, query: str, values: object = None) -> None:
        assert query.startswith("SELECT "), "phase reader must never mutate SQL"
        record, original, lease = self.saved.record, self.saved.original, self.saved.lease
        if "FROM work_queue_steps " in query:
            self.rows = [_row(original, original.work_item.id, original.work_item.task_id)]
        elif "event_type='CLAIMED'" in query:
            assert "FROM work_queue_events " in query
            item = original.work_item.model_copy(
                update={
                    "status": WorkItemStatus.LEASED,
                    "dispatch_sequence": 7,
                    "updated_at": lease.acquired_at,
                }
            )
            self.rows = [
                {
                    "sequence": 10,
                    "work_item_id": item.id,
                    "lease_id": lease.id,
                    "event_type": "CLAIMED",
                    "from_status": "READY",
                    "to_status": "LEASED",
                    "occurred_at": lease.acquired_at.isoformat(),
                    "payload_json": json.dumps({"work_item": item.to_wire(), "detail": {}}),
                }
            ]
        elif "event_type='EXECUTION_BASELINE_REBOUND'" in query:
            assert "FROM work_queue_events " in query
            item = original.work_item.model_copy(
                update={
                    "status": WorkItemStatus.WAITING_HUMAN,
                    "wait_reason": "baseline source rebound",
                    "dispatch_sequence": 6,
                    "updated_at": record.binding.completed_at,
                }
            )
            self.rows = (
                [
                    {
                        "sequence": 9,
                        "work_item_id": item.id,
                        "lease_id": None,
                        "event_type": "EXECUTION_BASELINE_REBOUND",
                        "from_status": "WAITING_HUMAN",
                        "to_status": "WAITING_HUMAN",
                        "occurred_at": record.binding.completed_at.isoformat(),
                        "payload_json": json.dumps(
                            {
                                "work_item": item.to_wire(),
                                "detail": {
                                    "binding_sha256": self.baseline_sha,
                                    "plan_sha256": record.plan.plan_sha256,
                                    "next_work_item_id": item.id,
                                    "budget_refund": False,
                                    "reservation": record.plan.facts.continuation,
                                },
                            }
                        ),
                    }
                ]
                if self.baseline_sha
                else []
            )
        elif "information_schema.TABLES" in query:
            self.rows = [{"TABLE_NAME": "work_queue_execution_baselines"}]
        elif "FROM work_queue_execution_baselines " in query:
            self.rows = [_row(record, record.binding.binding_sha256, record.task_id)]
        else:
            raise AssertionError(query)

    def fetchone(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


def _source(
    tmp_path: Path, saved: Saved, *, baseline_sha: str | None, cursor: Cursor | None = None
) -> str | None:
    record = saved.record
    item = saved.original.work_item.model_copy(
        update={"status": WorkItemStatus.RUNNING, "dispatch_sequence": 7}
    )
    scope = RoleExecutionScope(
        sidecar=tmp_path / "unused-sidecar",
        team_id=record.binding.scope.team_id,
        project_id=record.binding.scope.project_id,
        requirement_id="delivery_multi_source",
    )
    cursor = cursor or Cursor(saved, baseline_sha=baseline_sha)
    result = read_claim_source(
        cast(DictCursor, cursor),
        scope=scope,
        item=item,
        lease=saved.lease,
        allocation_sha256=saved.original.allocation_sha256,
    )
    assert not scope.sidecar.exists(), "source projection must not initialize any store"
    return result


@pytest.mark.parametrize("epoch", ["original", "rebound", "unknown"])
def test_source_uses_claim_epoch_not_task_base_or_newest_candidate(
    tmp_path: Path, saved: Saved, epoch: str
) -> None:
    binding = saved.record.binding
    selected = {"original": None, "rebound": binding.binding_sha256, "unknown": "f" * 64}[epoch]
    assert (
        _source(tmp_path, saved, baseline_sha=selected)
        == {
            "original": binding.prior_source_revision,
            "rebound": binding.execution_source_revision,
            "unknown": None,
        }[epoch]
    )


def test_pure_overlay_rejects_corrupted_predecessor_without_queue_access(saved: Saved) -> None:
    wrong = saved.original.model_copy(
        update={"boundary": replace(saved.original.boundary, source_revision="e" * 40)}
    )
    with pytest.raises(QueueCorruption, match="immutable predecessor"):
        resolve_step_overlays(
            wrong,
            (saved.record,),
            latest=False,
            baseline_sha256=saved.record.binding.binding_sha256,
        )


def test_pure_overlay_keeps_inherited_authorization_outside_read_projection(saved: Saved) -> None:
    inherited = saved.record.model_copy(update={"next_work_item_id": "work_inherited_phase"})
    selected, found = resolve_step_overlays(
        saved.original, (inherited,), latest=False, baseline_sha256=inherited.binding.binding_sha256
    )
    assert selected == saved.original and not found


@pytest.mark.parametrize(
    "malformed",
    ["claim_lease", "claim_payload", "rebound_order", "rebound_plan", "baseline_digest"],
)
def test_corrupt_event_or_consumption_cannot_supply_a_phase_source(
    tmp_path: Path, saved: Saved, malformed: str
) -> None:
    class CorruptCursor(Cursor):
        def execute(self, query: str, values: object = None) -> None:
            super().execute(query, values)
            if malformed.startswith("claim") and "event_type='CLAIMED'" in query:
                if malformed == "claim_lease":
                    self.rows[0]["lease_id"] = "lease_other_phase"
                else:
                    payload = json.loads(str(self.rows[0]["payload_json"]))
                    payload["detail"]["invented_authority"] = True
                    self.rows[0]["payload_json"] = json.dumps(payload)
            elif (
                malformed.startswith("rebound")
                and "event_type='EXECUTION_BASELINE_REBOUND'" in query
            ):
                if malformed == "rebound_order":
                    self.rows[0]["sequence"] = 11
                else:
                    payload = json.loads(str(self.rows[0]["payload_json"]))
                    payload["detail"]["plan_sha256"] = "f" * 64
                    self.rows[0]["payload_json"] = json.dumps(payload)
            elif malformed == "baseline_digest" and "FROM work_queue_execution_baselines " in query:
                self.rows[0]["sha256"] = "f" * 64

    cursor = CorruptCursor(saved, baseline_sha=saved.record.binding.binding_sha256)
    with pytest.raises((ValueError, QueueCorruption)):
        _source(tmp_path, saved, baseline_sha=saved.record.binding.binding_sha256, cursor=cursor)
