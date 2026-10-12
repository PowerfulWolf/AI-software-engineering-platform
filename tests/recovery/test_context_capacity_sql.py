"""Legacy capacity queue observation is SELECT-only and uses the immutable claim."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import ai_software_engineer.recovery.context_capacity as module
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.execution_baseline import BaselineInputMode
from ai_software_engineer.recovery.baseline_source import RecoveryBaselineEpoch
from ai_software_engineer.recovery.models import RecoveryScope
from ai_software_engineer.work_queue.baseline import BaselineQueueConsumption
from ai_software_engineer.work_queue.execution_store import RoleQueueAdmission, record_digest
from ai_software_engineer.work_queue.mysql import _RISK_RANK, MySqlPersistentWorkQueue
from tests.manager.test_execution_baseline import authorize, setup
from tests.orchestration.test_native_continuation import claim as make_claim
from tests.recovery.test_terminal_baseline_context import _fixture


def test_capacity_queue_reads_real_sealed_baseline_and_rejects_unsafe_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "baseline").mkdir()
    f = setup(tmp_path / "baseline")
    baseline_plan = f.service.propose(f.target, input_mode=BaselineInputMode.CODER_REAPPLY)
    binding = f.service.execute(baseline_plan.plan_sha256, authority=authorize(baseline_plan))
    epochs = (RecoveryBaselineEpoch(binding, 2),)
    task = f.collector.facts.task.model_copy(update={"status": TaskStatus.BLOCKED, "attempts": 2})
    scope = RecoveryScope(
        team_id="team_capacity",
        repository_id="repository_capacity",
        repository_root=task.repository,
        delivery_id="delivery_capacity",
    )
    claim = make_claim(task, 2)
    claim = claim.model_copy(
        update={
            "work_item": claim.work_item.model_copy(
                update={
                    "repository_id": scope.repository_id,
                    "checkpoint_sequence": 2,
                    "dispatch_sequence": 1,
                }
            ),
            "assignment": claim.assignment.model_copy(
                update={"repository_id": scope.repository_id}
            ),
        }
    )
    _, _, context, _, _ = _fixture(tmp_path / "context")
    context = context.model_copy(update={"built_at": datetime.now(UTC)})
    ended_at = context.built_at + timedelta(seconds=1)
    expected = module.CapacityContextClaim(
        task_id=task.id,
        work_item_id=claim.work_item.id,
        lease_id=claim.lease.id,
        assignment_id=claim.assignment.id,
        role=AgentRole.CODER,
        attempt=2,
        checkpoint_sequence=2,
        dispatch_sequence=1,
    )
    closed = claim.work_item.model_copy(update={"status": WorkItemStatus.CLOSED})
    item_row = {
        "id": closed.id,
        "task_id": task.id,
        "repository_id": closed.repository_id,
        "status": closed.status.value,
        "role": closed.role.value,
        "attempt": closed.attempt,
        "checkpoint_sequence": closed.checkpoint_sequence,
        "priority": closed.priority,
        "risk_rank": _RISK_RANK[closed.risk.value],
        "available_at": None,
        "created_at": MySqlPersistentWorkQueue._time_key(closed.created_at),
        "updated_at": MySqlPersistentWorkQueue._time_key(closed.updated_at),
        "payload_json": closed.model_dump_json(),
    }
    claim_row = {
        "task_id": task.id,
        "work_item_id": claim.work_item.id,
        "lease_id": claim.lease.id,
        "agent_id": claim.lease.agent_id,
        "capacity_units": claim.lease.capacity_units,
        "state": "RELEASED",
        "ended_at": MySqlPersistentWorkQueue._time_key(ended_at),
        "owner_token_sha256": "a" * 64,
        "worker_id": claim.worker_id,
        "acquired_at": MySqlPersistentWorkQueue._time_key(claim.lease.acquired_at),
        "expires_at": MySqlPersistentWorkQueue._time_key(claim.lease.expires_at),
        "last_heartbeat_at": MySqlPersistentWorkQueue._time_key(ended_at),
        "assignment_json": claim.assignment.model_dump_json(),
        "lease_json": claim.lease.model_dump_json(),
        "model_selection_json": claim.model_selection.model_dump_json(),
    }
    claim_event = {
        "work_item_id": claim.work_item.id,
        "lease_id": claim.lease.id,
        "from_status": "READY",
        "to_status": "LEASED",
        "occurred_at": MySqlPersistentWorkQueue._time_key(claim.claimed_at),
        "payload_json": json.dumps({"work_item": claim.work_item.to_wire()}),
    }
    admission = RoleQueueAdmission(
        task_id=task.id,
        repository_id=scope.repository_id,
        allocation_sha256="d" * 64,
        legacy_artifacts=(),
    )
    admitted = {
        "id": task.id,
        "task_id": task.id,
        "payload_json": admission.model_dump_json(),
        "sha256": record_digest(admission),
    }
    consumed = BaselineQueueConsumption(
        task_id=task.id,
        work_item_id=baseline_plan.facts.work_item_id,
        next_work_item_id=claim.work_item.id,
        prior_step_sha256="a" * 64,
        plan=baseline_plan,
        binding=binding,
    )
    rebound = {
        "id": binding.binding_sha256,
        "task_id": task.id,
        "payload_json": consumed.model_dump_json(),
        "sha256": record_digest(consumed),
    }
    monkeypatch.setattr(ProductionConfig, "require_mysql_dsn", lambda *_: "offline-fixture")
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="offline", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    reader = module.LegacyContextCapacitySourceReader(config, {})
    for fault in (
        None,
        "active",
        "running",
        "columns",
        "missing_claim",
        "claim_event",
        "claim_dispatch",
        "missing_admission",
        "missing_baseline",
        "task_changed",
    ):
        cursor, connection = MagicMock(), MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        task_row = {
            "payload_json": task.model_dump_json(),
            "revision": 4 if fault == "task_changed" else 3,
        }
        changed_item = {**item_row}
        if fault == "running":
            changed_item["payload_json"] = closed.model_copy(
                update={"status": WorkItemStatus.RUNNING}
            ).model_dump_json()
            changed_item["status"] = "RUNNING"
        elif fault == "columns":
            changed_item["status"] = "RUNNING"
        changed_event = {**claim_event}
        if fault == "claim_dispatch":
            changed_event["payload_json"] = json.dumps(
                {"work_item": claim.work_item.model_copy(update={"dispatch_sequence": 0}).to_wire()}
            )
        cursor.fetchone.side_effect = [
            task_row,
            {"lease_id": "lease_active"} if fault == "active" else None,
            None if fault == "missing_claim" else claim_row,
            None if fault == "missing_admission" else admitted,
        ]
        cursor.fetchall.side_effect = [
            [changed_item],
            [] if fault == "claim_event" else [changed_event],
            [] if fault == "missing_baseline" else [rebound],
            [],
        ]
        monkeypatch.setattr(module, "open_mysql_connection", MagicMock(return_value=connection))
        if fault is None:
            assert reader._claim(scope, task, 3, "d" * 64, expected, context, epochs) == claim
        else:
            with pytest.raises(ValueError):
                reader._claim(scope, task, 3, "d" * 64, expected, context, epochs)
        connection.rollback.assert_called_once()
        connection.close.assert_called_once()
        connection.commit.assert_not_called()
        commands = [call.args[0] for call in cursor.execute.call_args_list]
        assert commands[:2] == [
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ",
            "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY",
        ]
        assert all(
            command.startswith(("SELECT ", "SET TRANSACTION ", "START TRANSACTION "))
            for command in commands
        )
        assert not any("FOR UPDATE" in command for command in commands)
