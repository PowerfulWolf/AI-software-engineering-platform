"""Fail-closed restart classification and exact append-only approval contracts."""

import fcntl
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from jsonschema import Draft202012Validator

from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.context import ContextBudget
from ai_software_engineer.domain import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.retry_policy import DeliveryRetryFailure
from ai_software_engineer.manager.delivery_checkpoint import DeliveryFailureCode, DeliveryStage
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.recovery import verification_snapshot as module
from ai_software_engineer.recovery.models import (
    RecoveryApprovalCommand,
    RecoveryAuthorization,
    RecoveryRejected,
    VerifiedRecoveryDecision,
)
from ai_software_engineer.recovery.restart import _require_no_execution
from ai_software_engineer.recovery.restart_records import PreExecutionRestartPlan
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.work_queue.execution_store import (
    AcceptedRoleArtifact,
    QueuedRoleStep,
    RoleQueueAdmission,
    record_digest,
)
from ai_software_engineer.work_queue.models import QueueArtifactReceipt
from ai_software_engineer.work_queue.ports import QueueCorruption
from tests.domain.factories import make_plan_artifact
from tests.e2e.test_delivery_checkpoint import _checkpoint, _full_fields
from tests.manager.test_dispatch_authority import _durable_facts
from tests.recovery.test_authorization import make_plan
from tests.work_queue.test_dispatcher import item


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "legacy",
        "unknown_tail",
        "attempt",
        "retry",
        "event_source",
        "extra_event",
        "different_plan",
        "active_claim",
        "missing_admission",
        "bad_admission_digest",
        "extra_step",
        "step_source",
        "item_running",
        "item_row",
        "accepted_artifact",
        "successor",
    ],
)
def test_knowledge_timeout_restart_requires_complete_absence_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str | None,
) -> None:
    _, _, dispatch, _, _ = _durable_facts(tmp_path)
    task = dispatch.task.model_copy(update={"status": TaskStatus.BLOCKED, "attempts": 1})
    reason = (
        "coder knowledge preparation failed: TIMEOUT"
        if fault == "legacy"
        else "coder knowledge preparation reached local time limit"
    )
    receipt = QueueArtifactReceipt(artifact_id="art_plan_timeout", sha256="a" * 64)
    events = tuple(
        StateEvent(
            event_id=f"evt_knowledge_timeout_{i}",
            task_id=task.id,
            from_status=start,
            to_status=end,
            actor=AgentRole.ORCHESTRATOR,
            reason=why,
            artifact_ids=() if i == 0 else (receipt.artifact_id,),
            source_revision=task.base_ref,
            occurred_at=task.updated_at,
            attempt=1,
        )
        for i, (start, end, why) in enumerate(
            (
                (TaskStatus.NEW, TaskStatus.PLANNING, "task_validated"),
                (TaskStatus.PLANNING, TaskStatus.IMPLEMENTING, "plan_validated"),
                (TaskStatus.IMPLEMENTING, TaskStatus.BLOCKED, "TRANSIENT_INFRA: " + reason),
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
            "task_revision": 3,
            "task_status": task.status,
            "candidate_revision": None,
            "stage": DeliveryStage.BLOCKED,
            "failure_code": (
                DeliveryFailureCode.RETRY_BUDGET_EXHAUSTED
                if fault == "legacy"
                else DeliveryFailureCode.RESOURCE_UNAVAILABLE
            ),
            "failure_summary": reason,
            "failed_stage": DeliveryStage.DELIVERING,
        },
    )
    if fault == "attempt":
        task = task.model_copy(update={"attempts": 2})
    elif fault == "retry":
        task = task.model_copy(
            update={
                "retry_failures": (
                    DeliveryRetryFailure(role=AgentRole.CODER, attempt=1, code="TIMEOUT"),
                )
            }
        )
    elif fault == "unknown_tail":
        events = (*events[:2], events[2].model_copy(update={"reason": "unknown interruption"}))
    elif fault == "event_source":
        events = (*events[:2], events[2].model_copy(update={"source_revision": "f" * 40}))
    elif fault == "different_plan":
        events = (*events[:2], events[2].model_copy(update={"artifact_ids": ("art_plan_other",)}))
    elif fault == "extra_event":
        events = (*events, events[2])
    work = item(task_id=task.id, repository_id=dispatch.repository_id, checkpoint_sequence=2)
    step = QueuedRoleStep(
        work_item=work,
        allocation_sha256=dispatch.dispatch_sha256,
        boundary=RoleRunBoundary(
            task.id, AgentRole.CODER, 1, 2, "f" * 40 if fault == "step_source" else task.base_ref
        ),
    )
    admission = RoleQueueAdmission(
        task_id=task.id,
        repository_id=dispatch.repository_id,
        allocation_sha256=dispatch.dispatch_sha256,
        legacy_artifacts=(receipt,),
    )

    def row(record: RoleQueueAdmission | QueuedRoleStep | AcceptedRoleArtifact) -> dict[str, str]:
        key = (
            record.task_id
            if isinstance(record, RoleQueueAdmission)
            else record.work_item.id
            if isinstance(record, QueuedRoleStep)
            else record.receipt.artifact_id
        )
        return {
            "id": key,
            "task_id": task.id,
            "payload_json": record.model_dump_json(),
            "sha256": record_digest(record),
        }

    admitted = row(admission)
    if fault == "bad_admission_digest":
        admitted["sha256"] = "0" * 64
    closed = work.model_copy(
        update={
            "status": (WorkItemStatus.RUNNING if fault == "item_running" else WorkItemStatus.CLOSED)
        }
    )
    item_row = {
        "id": "work_foreign_001" if fault == "item_row" else work.id,
        "task_id": task.id,
        "status": closed.status.value,
        "payload_json": closed.model_dump_json(),
    }
    accepted = AcceptedRoleArtifact(
        task_id=task.id,
        work_item_id=work.id,
        lease_id="lease_timeout_001",
        dispatch_sequence=0,
        checkpoint_sequence=2,
        run_id="run_timeout_001",
        context_manifest_id="ctx_" + "a" * 64,
        source_revision=task.base_ref,
        receipt=receipt,
    )
    cursor, connection = MagicMock(), MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.side_effect = [
        {"lease_id": "live"} if fault == "active_claim" else None,
        None if fault == "missing_admission" else admitted,
    ]
    cursor.fetchall.side_effect = [
        [row(step)] * (2 if fault == "extra_step" else 1),
        [item_row],
        [row(accepted)] if fault == "accepted_artifact" else [],
    ]
    monkeypatch.setattr(module, "open_mysql_connection", lambda _: connection)
    monkeypatch.setattr(ProductionConfig, "require_mysql_dsn", lambda *_: "offline-fixture")
    monkeypatch.setattr(module, "_read_task_facts", lambda *_: (task, 3, events))
    # A successor must not get another fresh allowance when it times out again.
    allocations = {dispatch.id: object() if fault == "successor" else dispatch}
    monkeypatch.setattr(module, "_read_allocations", lambda *_: allocations)
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    if fault in {None, "legacy"}:
        result = module.read_pre_execution_snapshot(config, {}, (cp,))
        assert result and result.bootstrap_plan_receipt == receipt
    elif fault in {"unknown_tail", "attempt", "retry", "extra_event", "different_plan"}:
        assert module.read_pre_execution_snapshot(config, {}, (cp,)) is None
    else:
        with pytest.raises((RecoveryRejected, QueueCorruption)):
            module.read_pre_execution_snapshot(config, {}, (cp,))
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()


@pytest.mark.parametrize("bad", [None, "receipt", "live-worker", "worktree", "context"])
def test_pre_agent_plan_receipt_and_worker_lock_are_verified(
    tmp_path: Path, bad: str | None
) -> None:
    _, _, dispatch, _, _ = _durable_facts(tmp_path)
    task = dispatch.task
    artifact = seal_artifact(
        make_plan_artifact().model_copy(
            update={
                "task_id": task.id,
                "source_revision": task.base_ref,
            }
        ),
        validated_at=task.updated_at,
    )
    root = tmp_path / "sidecar"
    FileArtifactStore(root / "artifacts").put(artifact)
    (root / "contexts").mkdir()
    events = (
        StateEvent(
            event_id="evt_pre_agent_plan",
            task_id=task.id,
            from_status=TaskStatus.PLANNING,
            to_status=TaskStatus.IMPLEMENTING,
            actor=AgentRole.ORCHESTRATOR,
            reason="plan_validated",
            artifact_ids=(artifact.artifact_id,),
            source_revision=task.base_ref,
            occurred_at=task.updated_at,
            attempt=1,
        ),
    )
    snapshot = module.CandidateRuntimeSnapshot(
        task,
        2,
        dispatch,
        dispatch,
        events,
        QueueArtifactReceipt(
            artifact_id=artifact.artifact_id,
            sha256="0" * 64 if bad == "receipt" else artifact.integrity.sha256,
        ),
    )
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="offline", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    if bad == "worktree":
        (Path(config.platform_root) / "worktrees" / dispatch.repository_id / task.id).mkdir(
            parents=True
        )
    if bad == "context":
        from ai_software_engineer.context import FileContextStore
        from ai_software_engineer.orchestration import FileRunContextBuilder
        from tests.domain.factories import make_agent

        context = FileRunContextBuilder(Path(task.repository)).build(
            task,
            make_agent(),
            attempt=2,
        )
        FileContextStore(root / "contexts").put(context)
    locks = root / "state/queue-worker-locks"
    locks.mkdir(parents=True)
    lock = locks / (hashlib.sha256(task.id.encode()).hexdigest() + ".lock")
    with lock.open("w") as stream:
        if bad == "live-worker":
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if bad is None:
            _require_no_execution(
                config, root, snapshot, allow_plan_artifact=True, allow_pre_agent_context=True
            )
        else:
            with pytest.raises(RecoveryRejected):
                _require_no_execution(
                    config, root, snapshot, allow_plan_artifact=True, allow_pre_agent_context=True
                )


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


def test_knowledge_restart_binds_both_bases_and_preserves_legacy_digest(tmp_path: Path) -> None:
    from pydantic import ValidationError

    from ai_software_engineer.recovery.models import digest

    legacy = restart_plan(tmp_path)
    old_shape = legacy.model_dump(
        mode="json",
        exclude={
            "plan_sha256",
            "restart_kind",
            "source_base_revision",
        },
    )
    assert legacy.recompute_sha256() == digest(old_shape)
    plan = legacy.model_copy(
        update={
            "restart_kind": "pre_agent_knowledge_timeout",
            "source_base_revision": "b" * 40,
        }
    )
    plan = plan.model_copy(update={"plan_sha256": plan.recompute_sha256()})
    plan.validate_integrity()
    schema = json.loads(Path("schemas/pre-execution-restart.schema.json").read_text())
    validator = Draft202012Validator(schema)
    validator.validate(plan.to_wire())
    missing = plan.to_wire()
    missing.pop("source_base_revision")
    assert tuple(validator.iter_errors(missing))
    with pytest.raises(ValidationError):
        PreExecutionRestartPlan.model_validate(missing)
    with pytest.raises(RecoveryRejected, match="digest"):
        plan.model_copy(update={"source_base_revision": "c" * 40}).validate_integrity()


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
