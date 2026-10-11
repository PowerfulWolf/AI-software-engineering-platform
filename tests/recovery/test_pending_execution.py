"""Recovery keeps typed queue waits attached to the original delivery cursor."""

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.manager.delivery import (
    DeliveryBackendPending,
    DeliveryCommandRejected,
    DeliveryFailureSnapshot,
    ProjectDeliveryCheckpointCatalog,
    ResumeProjectDelivery,
    UnifiedProjectEntryService,
)
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.dispatch import RecoveryDispatchRecord, _record_digest
from ai_software_engineer.recovery.entry import NativeRecoveryEntry, NativeRecoveryPending
from ai_software_engineer.recovery.models import RecoveryPlan, RecoveryRejected
from ai_software_engineer.recovery.resume import DeliveryResumeController, DeliveryResumeOutcome
from ai_software_engineer.recovery.service import RecoveryAuthorizationService
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.work_queue.ports import DeliveryQueuePending
from ai_software_engineer.work_queue.worker import DeliveryWaiting
from tests.e2e.test_delivery_checkpoint import NOW, _checkpoint, _full_fields
from tests.recovery.test_authorization import Captures, Facts, Human, approval, make_plan
from tests.recovery.test_execution_records import allocation


@dataclass
class PendingFixture:
    recovery: NativeRecoveryEntry
    controller: DeliveryResumeController
    service: UnifiedProjectEntryService
    journal: FileProjectDeliveryCheckpointStore
    current: ProjectDeliveryCheckpoint
    snapshot: DeliveryFailureSnapshot
    dispatch: RecoveryDispatchRecord
    plan: RecoveryPlan
    path: Path
    execution: Mock
    backend: Mock


def fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PendingFixture:
    original = allocation(tmp_path)
    root = Path(original.task.repository)
    current = _checkpoint(
        root,
        **{
            **_full_fields(),
            "repository_id": original.repository_id,
            "task_id": "task_original",
            "task_status": TaskStatus.BLOCKED,
            "candidate_revision": None,
        },
        stage=DeliveryStage.BLOCKED,
        next_action=DeliveryNextAction.REQUEST_HUMAN,
        failure_code=DeliveryFailureCode.INVALID_AGENT_OUTPUT,
        failure_summary="旧开发结果不完整, 原现场保留。",
        failed_stage=DeliveryStage.DELIVERING,
    )
    prototype = make_plan(root, repository_id=current.repository_id)
    plan = RecoveryPlan.create(
        **{
            **prototype.to_wire(),
            "source": prototype.source.model_copy(
                update={
                    "task_id": current.task_id,
                    "checkpoint_sha256": current.checkpoint_sha256,
                    "scope": prototype.source.scope.model_copy(
                        update={"delivery_id": current.delivery_id}
                    ),
                }
            ),
        }
    )
    task = original.task.model_copy(
        update={
            "id": plan.new_task_id,
            "base_ref": plan.target_base_revision,
            "metadata": {
                **original.task.metadata,
                "recovery_plan_sha256": plan.plan_sha256,
                "recovery_of_task_id": plan.source.task_id,
                "recovery_of_delivery_id": plan.source.scope.delivery_id,
                "recovery_source_checkpoint_sha256": plan.source.checkpoint_sha256,
                "recovery_target_preparation_sha256": plan.target_preparation_sha256,
            },
        }
    )
    dispatch = original.model_copy(
        update={
            "id": "dispatch_commit_" + plan.plan_sha256,
            "task_id": task.id,
            "task": task,
            "recovery_plan_sha256": plan.plan_sha256,
            "phases": tuple(
                phase.model_copy(
                    update={
                        "assignment": phase.assignment.model_copy(update={"task_id": task.id}),
                        "lease": phase.lease.model_copy(update={"task_id": task.id}),
                    }
                )
                for phase in original.phases
            ),
        }
    )
    dispatch = dispatch.model_copy(update={"dispatch_sha256": _record_digest(dispatch)})
    registry = tmp_path / "registry"
    journal = FileProjectDeliveryCheckpointStore(
        registry / current.repository_id / "state/project-deliveries"
    )
    journal.put(current)
    store = FileRecoveryStore.initialize(tmp_path / "recovery", scope=plan.source.scope)
    authorization = RecoveryAuthorizationService(
        store, facts=Facts(), captures=Captures(), human=Human()
    )
    authorization.propose(plan)
    authorization.authorize(approval(plan))
    config = ProductionConfig(
        live_model_execution=True,
        model_routes=(
            ProviderRouteConfig(
                provider="codex",
                model="offline",
                kind=ModelProviderKind.CODEX_CLI,
            ),
        ),
    )
    backend = Mock()
    snapshot = DeliveryFailureSnapshot(
        task=task.model_copy(
            update={
                "status": TaskStatus.IMPLEMENTING,
                "attempts": 1,
                "updated_at": max(NOW, task.created_at) + timedelta(hours=1),
            }
        ),
        task_revision=3,
    )
    backend._delivery_snapshot.return_value = snapshot
    recovery = NativeRecoveryEntry(config, {}, backend)
    path = tmp_path / "recovery-plan.json"
    execution = Mock()
    monkeypatch.setattr(recovery, "open_plan", lambda _: (store, plan))
    monkeypatch.setattr(recovery, "_execute", execution)
    monkeypatch.setattr(recovery, "_dispatch_for", lambda *_: dispatch)
    monkeypatch.setattr(recovery, "latest_delivery", lambda _: (store, plan, path))
    monkeypatch.setattr(recovery, "require_current_plan", lambda _: plan)
    monkeypatch.setattr(recovery, "pending_knowledge_wait", lambda _: None)
    monkeypatch.setattr("ai_software_engineer.recovery.resume.read_recovery_task", lambda *_: None)
    service = UnifiedProjectEntryService(
        backend=backend, catalog=ProjectDeliveryCheckpointCatalog(registry)
    )
    controller = DeliveryResumeController(
        config=config,
        environment={},
        backend=backend,
        entry=service,
        recovery=recovery,
        verification=Mock(),
    )
    return PendingFixture(
        recovery,
        controller,
        service,
        journal,
        current,
        snapshot,
        dispatch,
        plan,
        path,
        execution,
        backend,
    )


@pytest.mark.parametrize("structured", [False, True])
def test_approved_recovery_attaches_real_checkpoint_on_typed_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    structured: bool,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    disposition = decide_delivery_disposition(
        DeliveryFailureFacts(
            task_id=f.snapshot.task.id,
            work_item_id="work_pending_recovery",
            role=AgentRole.CODER,
            classification="KNOWLEDGE_PREPARATION_LIMIT",
            source_revision=f.snapshot.task.base_ref,
            task_intent_sha256=task_intent_sha256(f.snapshot.task),
            checkpoint_sequence=3,
            budget_available=True,
        )
    )
    f.execution.side_effect = (
        DeliveryWaiting(disposition)
        if structured
        else DeliveryQueuePending("private-provider-details must never become public next_action")
    )
    result = f.controller._continue_coder_recovery(
        f.current, ResumeProjectDelivery(delivery_id=f.current.delivery_id)
    )
    assert result.checkpoint.stage is DeliveryStage.DELIVERING
    assert result.checkpoint.task_id == f.snapshot.task.id
    assert result.checkpoint.task_status is TaskStatus.IMPLEMENTING
    assert result.checkpoint.task_revision == 3
    assert result.checkpoint.candidate_revision is None
    assert result.checkpoint.next_action is DeliveryNextAction.RUN_DELIVERY
    assert f.journal.list(f.current.delivery_id)[0] == f.current
    assert f.journal.current(f.current.delivery_id) == result.checkpoint
    assert f.execution.call_count == 1
    f.backend.run_delivery.assert_not_called()
    if structured:
        assert result.outcome is DeliveryResumeOutcome.WAITING_HUMAN
        assert disposition.reason in result.next_action
        assert disposition.next_action in result.next_action
    else:
        assert result.outcome is DeliveryResumeOutcome.CONTINUED
        assert "调度" in result.next_action
        assert "private-provider-details" not in result.next_action

    # Subsequent Continue uses the ordinary delivery path, retaining the exact Task.
    f.backend.run_delivery.side_effect = DeliveryBackendPending(f.snapshot)
    continued = f.controller.resume(ResumeProjectDelivery(delivery_id=f.current.delivery_id))
    assert continued.checkpoint == result.checkpoint
    assert f.execution.call_count == 1
    assert f.backend.run_delivery.call_args.args[0] == result.checkpoint
    assert len(f.journal.list(f.current.delivery_id)) == 3


def test_unknown_recovery_failure_is_not_converted_to_a_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    failure = RuntimeError("unknown implementation defect")
    f.execution.side_effect = failure
    with pytest.raises(RuntimeError) as caught:
        f.controller._continue_coder_recovery(
            f.current, ResumeProjectDelivery(delivery_id=f.current.delivery_id)
        )
    assert caught.value is failure
    assert f.journal.current(f.current.delivery_id) == f.current
    f.backend._delivery_snapshot.assert_not_called()


@pytest.mark.parametrize("changed", ["id", "repository", "base_ref", "metadata", "terminal"])
def test_pending_recovery_rejects_foreign_or_terminal_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    changes: dict[str, object] = {
        "id": "task_foreign",
        "repository": str(tmp_path / "another-repository"),
        "base_ref": "f" * 40,
        "metadata": {**f.snapshot.task.metadata, "foreign-intent": True},
        "terminal": TaskStatus.BLOCKED,
    }
    task = f.snapshot.task.model_copy(
        update={"status" if changed == "terminal" else changed: changes[changed]}
    )
    f.backend._delivery_snapshot.return_value = f.snapshot.model_copy(update={"task": task})
    f.execution.side_effect = DeliveryQueuePending()
    with pytest.raises(RecoveryRejected, match="任务记录与已批准的任务不一致"):
        f.recovery.resume_execution(f.path)
    assert f.journal.current(f.current.delivery_id) == f.current
    assert f.execution.call_count == 1
    f.backend.run_delivery.assert_not_called()


@pytest.mark.parametrize("changed", ["task", "intent", "role", "source", "future", "no_work_item"])
def test_pending_recovery_rejects_disposition_not_bound_to_its_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    facts = DeliveryFailureFacts(
        task_id="task_foreign" if changed == "task" else f.snapshot.task.id,
        work_item_id=None if changed == "no_work_item" else "work_pending_recovery",
        role=AgentRole.QA if changed == "role" else AgentRole.CODER,
        classification="KNOWLEDGE_PREPARATION_LIMIT",
        source_revision="f" * 40 if changed == "source" else f.snapshot.task.base_ref,
        task_intent_sha256="f" * 64 if changed == "intent" else task_intent_sha256(f.snapshot.task),
        checkpoint_sequence=4 if changed == "future" else 3,
        budget_available=True,
    )
    f.execution.side_effect = DeliveryWaiting(decide_delivery_disposition(facts))
    with pytest.raises(RecoveryRejected, match="原因记录与当前任务阶段或代码版本不一致"):
        f.recovery.resume_execution(f.path)
    assert f.journal.current(f.current.delivery_id) == f.current
    assert f.execution.call_count == 1


def test_pending_recovery_cannot_be_adopted_without_exact_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    store, _ = f.recovery.open_plan(f.path)
    approved = store.get_authorization(f.plan.plan_sha256)
    monkeypatch.setattr(
        store,
        "get_authorization",
        lambda _: approved.model_copy(
            update={
                "decision": approved.decision.model_copy(update={"approved": False}),
            }
        ),
    )
    f.execution.side_effect = DeliveryQueuePending()
    with pytest.raises(RecoveryRejected, match="当前精确计划的批准"):
        f.recovery.resume_execution(f.path)
    f.backend._delivery_snapshot.assert_not_called()
    assert f.journal.current(f.current.delivery_id) == f.current


def test_pending_adoption_is_idempotent_and_rejects_backward_or_foreign_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    f.execution.side_effect = DeliveryQueuePending()
    result = f.controller._continue_coder_recovery(
        f.current, ResumeProjectDelivery(delivery_id=f.current.delivery_id)
    )
    assert (
        f.service.adopt_recovery_pending(
            f.plan,
            f.dispatch,
            f.snapshot,
            at=f.snapshot.task.updated_at,
        ).checkpoint
        == result.checkpoint
    )
    with pytest.raises(DeliveryCommandRejected, match="moved backwards"):
        f.service.adopt_recovery_pending(
            f.plan,
            f.dispatch,
            f.snapshot.model_copy(update={"task_revision": 2}),
            at=f.snapshot.task.updated_at,
        )
    other_task = f.snapshot.task.model_copy(update={"id": "task_foreign"})
    with pytest.raises(DeliveryCommandRejected, match="does not match"):
        f.service.adopt_recovery_pending(
            f.plan,
            f.dispatch,
            f.snapshot.model_copy(update={"task": other_task}),
            at=f.snapshot.task.updated_at,
        )
    assert f.journal.current(f.current.delivery_id) == result.checkpoint
    assert len(f.journal.list(f.current.delivery_id)) == 3
    f.backend.run_delivery.assert_not_called()


def test_interruption_execution_adopts_pending_without_repeating_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    store, _ = f.recovery.open_plan(f.path)
    authorization = store.get_authorization(f.plan.plan_sha256)
    monkeypatch.setattr(store, "get_interruption_authorization", lambda _: authorization)
    interruption = Mock()
    interruption.propose.return_value = Mock(plan_sha256="a" * 64)
    monkeypatch.setattr(
        "ai_software_engineer.recovery.interruption.RecoveryInterruptionService",
        lambda *_: interruption,
    )
    queue = Mock()
    monkeypatch.setattr(
        "ai_software_engineer.manager.queue_capacity.production_role_queue",
        lambda _: queue,
    )
    f.recovery.environment[f.recovery.config.database.dsn_env] = "offline"
    f.execution.side_effect = DeliveryQueuePending()
    result = f.recovery.execute_interruption(
        f.path,
        confirmed_plan="a" * 64,
        reference="original exact approval",
        route_factory=lambda _: Mock(),
    )
    assert isinstance(result.delivery, NativeRecoveryPending)
    assert result.delivery.snapshot == f.snapshot
    assert result.plan == f.plan and result.dispatch == f.dispatch
    assert f.execution.call_count == 1
    queue.reclaim_expired.assert_called_once()
    f.backend.run_delivery.assert_not_called()


@pytest.mark.parametrize("role", [AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER])
def test_pending_disposition_binds_current_candidate_instead_of_original_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    role: AgentRole,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    status = {
        AgentRole.CODER: TaskStatus.IMPLEMENTING,
        AgentRole.QA: TaskStatus.QA,
        AgentRole.REVIEWER: TaskStatus.REVIEW,
    }[role]
    snapshot = f.snapshot.model_copy(
        update={
            "task": f.snapshot.task.model_copy(update={"status": status}),
            "candidate_revision": "e" * 40,
        }
    )
    f.backend._delivery_snapshot.return_value = snapshot
    disposition = decide_delivery_disposition(
        DeliveryFailureFacts(
            task_id=snapshot.task.id,
            work_item_id="work_pending_recovery",
            role=role,
            classification="INVALID_OUTPUT",
            source_revision="e" * 40,
            task_intent_sha256=task_intent_sha256(snapshot.task),
            checkpoint_sequence=3,
            budget_available=True,
        )
    ).model_copy(
        update={
            "detail": (
                "缺少必填字段; api_key=sk-secret-example-token "
                "https://provider.example/private?token=unsafe " + "x" * 600
            )
        }
    )
    f.execution.side_effect = DeliveryWaiting(disposition)
    result = f.controller._continue_coder_recovery(
        f.current, ResumeProjectDelivery(delivery_id=f.current.delivery_id)
    )
    assert result.checkpoint.candidate_revision == "e" * 40
    assert result.checkpoint.task_status is status
    assert result.outcome is DeliveryResumeOutcome.WAITING_HUMAN
    assert "缺少必填字段" in result.next_action
    assert "sk-secret-example-token" not in result.next_action
    assert "provider.example" not in result.next_action
    assert len(result.next_action) < 1000


@pytest.mark.parametrize("changed", ["plan", "dispatch", "cursor"])
def test_pending_adoption_rejects_plan_dispatch_or_current_cursor_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    f = fixture(tmp_path, monkeypatch)
    f.service.begin_recovery(f.plan, f.dispatch, at=f.dispatch.committed_at)
    plan = f.plan
    dispatch = f.dispatch
    if changed == "plan":
        plan = RecoveryPlan.create(**{**f.plan.to_wire(), "target_preparation_sha256": "d" * 64})
    elif changed == "dispatch":
        dispatch = f.dispatch.model_copy(update={"workforce_snapshot_sha256": "d" * 64})
        dispatch = dispatch.model_copy(update={"dispatch_sha256": _record_digest(dispatch)})
    else:
        current = f.journal.current(f.current.delivery_id)
        altered = ProjectDeliveryCheckpoint.create(
            **{
                **current.to_wire(),
                "sequence": current.sequence + 1,
                "previous_checkpoint_sha256": current.checkpoint_sha256,
                "task_id": "task_foreign",
            }
        )
        f.journal.put(altered)
    before = f.journal.current(f.current.delivery_id)
    with pytest.raises(DeliveryCommandRejected, match="does not match"):
        f.service.adopt_recovery_pending(
            plan,
            dispatch,
            f.snapshot,
            at=f.snapshot.task.updated_at,
        )
    assert f.journal.current(f.current.delivery_id) == before
    f.execution.assert_not_called()
    f.backend.run_delivery.assert_not_called()
