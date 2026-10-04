"""Fail-closed restart classification and exact append-only approval contracts."""

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from jsonschema import Draft202012Validator

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.context import ContextBudget
from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.manager.delivery_checkpoint import DeliveryFailureCode, DeliveryStage
from ai_software_engineer.recovery import verification_snapshot as module
from ai_software_engineer.recovery.models import (
    RecoveryApprovalCommand,
    RecoveryAuthorization,
    RecoveryRejected,
    VerifiedRecoveryDecision,
)
from ai_software_engineer.recovery.restart_records import PreExecutionRestartPlan
from ai_software_engineer.recovery.store import FileRecoveryStore
from tests.e2e.test_delivery_checkpoint import _checkpoint, _full_fields
from tests.manager.test_dispatch_authority import _durable_facts
from tests.recovery.test_authorization import make_plan


def restart_plan(tmp_path: Path) -> PreExecutionRestartPlan:
    old = make_plan(tmp_path / "project")
    plan = PreExecutionRestartPlan(
        scope=old.source.scope,
        source_task_id=old.source.task_id,
        source_task_sha256="1" * 64,
        source_events_sha256="2" * 64,
        source_checkpoint_sha256="3" * 64,
        source_dispatch_id="dispatch_commit_" + "4" * 64,
        source_dispatch_sha256="4" * 64,
        approved_stages_sha256="5" * 64,
        target_preparation_sha256="6" * 64,
        target_base_revision="a" * 40,
        config_sha256="7" * 64,
        context_budget=ContextBudget(max_input_tokens=128_000, reserved_output_tokens=4000),
        created_at=old.created_at,
        plan_sha256="0" * 64,
    )
    return plan.model_copy(update={"plan_sha256": plan.recompute_sha256()})


def test_restart_plan_and_authorization_are_exact_durable_records(tmp_path: Path) -> None:
    plan = restart_plan(tmp_path)
    store = FileRecoveryStore.initialize(tmp_path / "records", scope=plan.scope)
    store.put_restart_plan(plan)
    schema = json.loads(Path("schemas/pre-execution-restart.schema.json").read_text())
    Draft202012Validator(schema).validate(plan.to_wire())
    assert store.get_restart_plan(plan.plan_sha256) == plan
    command = RecoveryApprovalCommand(
        operation_id="op_restart",
        plan_sha256=plan.plan_sha256,
        approval_reference="human-approved-exact-restart",
        submitted_at=plan.created_at,
    )
    decision = VerifiedRecoveryDecision(
        plan_sha256=plan.plan_sha256,
        approved=True,
        operator_id="human",
        approval_reference=command.approval_reference,
        rationale="Start an isolated new Task",
        decided_at=plan.created_at,
    )
    authorization = RecoveryAuthorization.create(command, decision)
    store.put_restart_authorization(authorization)
    assert (
        FileRecoveryStore(tmp_path / "records", scope=plan.scope).get_restart_authorization(
            plan.plan_sha256
        )
        == authorization
    )
    with pytest.raises(RecoveryRejected, match="digest"):
        store.put_restart_plan(plan.model_copy(update={"target_base_revision": "b" * 40}))
    with pytest.raises(RecoveryRejected, match="predates"):
        store.put_restart_authorization(
            RecoveryAuthorization.create(
                command.model_copy(update={"submitted_at": plan.created_at - timedelta(seconds=1)}),
                decision,
            )
        )
    foreign = plan.model_copy(
        update={"scope": plan.scope.model_copy(update={"team_id": "team_other"})}
    )
    foreign = foreign.model_copy(update={"plan_sha256": foreign.recompute_sha256()})
    with pytest.raises(RecoveryRejected, match="scope"):
        store.put_restart_plan(foreign)


def test_preparation_rebind_plan_is_an_exact_restart_record(tmp_path: Path) -> None:
    plan = restart_plan(tmp_path).model_copy(update={"restart_kind": "preparation_rebind"})
    plan = plan.model_copy(update={"plan_sha256": plan.recompute_sha256()})
    store = FileRecoveryStore.initialize(tmp_path / "rebind-records", scope=plan.scope)
    store.put_restart_plan(plan)
    schema = json.loads(Path("schemas/pre-execution-restart.schema.json").read_text())
    Draft202012Validator(schema).validate(plan.to_wire())
    assert store.get_restart_plan(plan.plan_sha256) == plan


@pytest.mark.parametrize(
    "change",
    [
        None,
        "unknown_failure",
        "coder_started",
        "retry",
        "artifact",
        "revision",
        "source",
        "task",
        "active_claim",
        "queue_admission",
        "checkpoint",
    ],
)
def test_restart_requires_exact_initial_context_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str | None,
) -> None:
    _, _, dispatch, _, _ = _durable_facts(tmp_path)
    task = dispatch.task.model_copy(update={"status": TaskStatus.BLOCKED, "attempts": 1})
    events = tuple(
        StateEvent(
            event_id=f"evt_pre_execution_{index}",
            task_id=task.id,
            from_status=start,
            to_status=end,
            actor=AgentRole.ORCHESTRATOR,
            reason=reason,
            artifact_ids=(),
            source_revision=task.base_ref,
            occurred_at=task.updated_at,
            attempt=1,
        )
        for index, (start, end, reason) in enumerate(
            (
                (TaskStatus.NEW, TaskStatus.PLANNING, "task_validated"),
                (TaskStatus.PLANNING, TaskStatus.BLOCKED, module._PRE_AGENT_CONTEXT_BUDGET_REASON),
            )
        )
    )
    fields = {
        **_full_fields(),
        "repository_id": dispatch.repository_id,
        "dispatch_commit_id": dispatch.id,
        "dispatch_commit_sha256": dispatch.dispatch_sha256,
        "task_id": task.id,
        "task_revision": 2,
        "task_status": task.status,
        "candidate_revision": None,
        "stage": DeliveryStage.BLOCKED,
        "failure_code": DeliveryFailureCode.RETRY_BUDGET_EXHAUSTED,
        "failure_summary": "Initial context limit",
        "failed_stage": DeliveryStage.DELIVERING,
    }
    cp = _checkpoint(Path(task.repository), **fields)
    revision = 2
    if change == "unknown_failure":
        events = (events[0], events[1].model_copy(update={"reason": "unknown interruption"}))
    elif change == "coder_started":
        events = (events[0], events[1].model_copy(update={"from_status": TaskStatus.IMPLEMENTING}))
    elif change == "retry":
        task = task.model_copy(update={"attempts": 2})
    elif change == "artifact":
        events = (events[0], events[1].model_copy(update={"artifact_ids": ("art_plan_exists",)}))
    elif change == "revision":
        revision = 3
    elif change == "source":
        events = (events[0], events[1].model_copy(update={"source_revision": "f" * 40}))
    elif change == "task":
        task = task.model_copy(update={"title": "silently changed scope"})
    elif change == "checkpoint":
        cp = cp.model_copy(update={"task_revision": 1})
    cursor, connection = MagicMock(), MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = (
        [None, {"id": "admitted"}]
        if change == "queue_admission"
        else [{"lease_id": "claimed"}]
        if change == "active_claim"
        else [None, None]
    )
    monkeypatch.setattr(module, "open_mysql_connection", lambda _: connection)
    monkeypatch.setattr(ProductionConfig, "require_mysql_dsn", lambda *_: "offline-fixture")
    monkeypatch.setattr(module, "_read_task_facts", lambda *_: (task, revision, events))
    monkeypatch.setattr(module, "_read_allocations", lambda *_: {dispatch.id: dispatch})
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex",
                model="offline",
                kind=ModelProviderKind.CODEX_CLI,
            ),
        ),
    )
    if change in {"artifact", "source", "task", "active_claim", "queue_admission", "checkpoint"}:
        with pytest.raises(RecoveryRejected):
            module.read_pre_execution_snapshot(config, {}, (cp,))
    else:
        result = module.read_pre_execution_snapshot(config, {}, (cp,))
        assert (result is not None) == (change is None)
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()


def test_worktree_conflict_before_coder_is_restartable_without_agent_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, dispatch, _, _ = _durable_facts(tmp_path)
    task = dispatch.task.model_copy(update={"status": TaskStatus.IMPLEMENTING, "attempts": 1})
    events = tuple(
        StateEvent(
            event_id=f"evt_worktree_conflict_{index}",
            task_id=task.id,
            from_status=start,
            to_status=end,
            actor=AgentRole.ORCHESTRATOR,
            reason=reason,
            artifact_ids=("art_plan_worktree_conflict",) if index == 1 else (),
            source_revision=task.base_ref,
            occurred_at=task.updated_at,
            attempt=1,
        )
        for index, (start, end, reason) in enumerate(
            (
                (TaskStatus.NEW, TaskStatus.PLANNING, "task_validated"),
                (TaskStatus.PLANNING, TaskStatus.IMPLEMENTING, "plan_validated"),
            )
        )
    )
    cp = _checkpoint(
        Path(task.repository),
        **{
            **_full_fields(),
            "repository_id": dispatch.repository_id,
            "dispatch_commit_id": dispatch.id,
            "dispatch_commit_sha256": dispatch.dispatch_sha256,
            "task_id": task.id,
            "task_revision": 2,
            "task_status": task.status,
            "candidate_revision": None,
            "stage": DeliveryStage.BLOCKED,
            "failure_code": DeliveryFailureCode.INVARIANT_VIOLATION,
            "failure_summary": "Delivery stopped safely (WorktreeAlreadyExists)",
            "failed_stage": DeliveryStage.DELIVERING,
        },
    )
    cursor, connection = MagicMock(), MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = [None, None]
    monkeypatch.setattr(module, "open_mysql_connection", lambda _: connection)
    monkeypatch.setattr(ProductionConfig, "require_mysql_dsn", lambda *_: "offline-fixture")
    monkeypatch.setattr(module, "_read_task_facts", lambda *_: (task, 2, events))
    monkeypatch.setattr(module, "_read_allocations", lambda *_: {dispatch.id: dispatch})
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex",
                model="offline",
                kind=ModelProviderKind.CODEX_CLI,
            ),
        ),
    )
    result = module.read_pre_execution_snapshot(config, {}, (cp,))
    assert result is not None
    assert result.task.status is TaskStatus.IMPLEMENTING
    assert result.events[-1].reason == "plan_validated"
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()
