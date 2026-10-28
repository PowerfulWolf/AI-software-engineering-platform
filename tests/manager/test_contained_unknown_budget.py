"""An exact operator declaration can close exhausted start-only Coder work."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from shutil import copytree
from typing import cast

import pytest
from pydantic import ValidationError

from ai_software_engineer.domain import TaskStatus, WorkItemStatus
from ai_software_engineer.domain.contained_unknown_budget import ContainedUnknownBudgetSettlement
from ai_software_engineer.domain.delivery_resolution import HandleDeliveryWait, InspectDeliveryWait
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.evaluation import FileEvaluationEventStore, HumanAction, HumanActionEvent
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.contained_unknown_budget import (
    ContainedUnknownBudgetSettlementService,
    verify_settled_contained_unknown,
)
from ai_software_engineer.manager.legacy_containment import LocalBootObservation
from ai_software_engineer.manager.legacy_local_execution import (
    LegacyLocalExecutionSurvey,
    LegacyRescuePrerequisiteError,
    TrustedLegacyLocalExecutionObserver,
)
from ai_software_engineer.manager.local_survey_observation import (
    IsolatedLegacyLocalExecutionObserver,
)
from ai_software_engineer.orchestration.continuation_models import ContinuationRejected
from ai_software_engineer.runtime import _default_case_id
from ai_software_engineer.team_view.engineering_history import engineering_history
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.manager.test_completed_output_checkpoint import CompletedFixture
from tests.manager.test_completed_output_checkpoint import completed as completed_fixture
from tests.manager.test_stopped_unknown_budget import UnknownQueue, service_for

completed = completed_fixture


class FakeBootObserver:
    def __init__(self, f: CompletedFixture) -> None:
        self.boot = LocalBootObservation(
            machine_sha256="a" * 64,
            boot_session_sha256="b" * 64,
            booted_at=f.start.started_at - timedelta(days=1),
        )

    def observe(self) -> LocalBootObservation:
        return self.boot


class FakeLocalObserver:
    def observe(
        self, *, worktree_root: Path, boot: LocalBootObservation
    ) -> LegacyLocalExecutionSurvey:
        return LegacyLocalExecutionSurvey.create(
            worktree_path=str(worktree_root),
            machine_sha256=boot.machine_sha256,
            boot_session_sha256=boot.boot_session_sha256,
            account_sha256="c" * 64,
            observed_at=datetime.now(UTC),
            scanner_version="local-execution-v1",
            blockers=(),
        )


def contained_service_for(f: CompletedFixture):
    service = service_for(f)
    unknown = service.unknown_budget_settlement
    assert unknown is not None
    service.contained_unknown_budget_settlement = ContainedUnknownBudgetSettlementService(
        repository=f.native.repository,
        queue=cast(MySqlRoleQueue, f.queue),
        records=KnowledgeRecordStore(f.root / "delivery-preflight"),
        collector=unknown.collector,
        git=f.native.git,
        artifacts=f.native.artifacts,
        principal=LocalOperatorPrincipal.trusted_local(),
        boot_observer=FakeBootObserver(f),
        local_execution_observer=FakeLocalObserver(),
        evaluation_root=f.root / "evaluations",
        clock=lambda: datetime.now(UTC),
        idle_scope=lambda: f.queue.idle_task_scope(f.task.id),
    )
    return service


@pytest.mark.parametrize("completed", ["start_only_unknown_exhausted"], indirect=True)
def test_local_stop_reference_is_a_bounded_audit_id(completed: CompletedFixture) -> None:
    base = completed.queue.command().to_wire()
    for reference in ("free text", "x" * 257, "secret=value", "short"):
        with pytest.raises(ValidationError):
            HandleDeliveryWait.model_validate(
                {
                    **base,
                    "confirm_local_execution_stopped": True,
                    "local_stop_reference": reference,
                }
            )


@pytest.mark.parametrize("completed", ["start_only_unknown_exhausted"], indirect=True)
def test_public_handle_contains_exhausted_start_only_coder_with_exact_human_stop(
    completed: CompletedFixture,
) -> None:
    f = completed
    # This is the persisted historical shape: invocation-start and capture-start
    # exist, but no process-stop, invocation-outcome or continuation receipt was
    # sealed. The original simulated process has already exited.
    assert not (
        f.root / "continuations" / f.task.id / f"capture-stop-{f.start.request.run_id}.json"
    ).exists()
    service = contained_service_for(f)
    before = f.task
    old_events = f.native.repository.list_events(f.task.id)
    command = HandleDeliveryWait.model_validate(
        {
            **f.queue.command().to_wire(),
            "confirm_local_execution_stopped": True,
            "local_stop_reference": "call_a7e4ebe2aed34bad899f8cc3588da3b5",
        }
    )

    assert service.inspect(
        InspectDeliveryWait.model_validate(f.queue.command().to_wire())
    ).local_stop_confirmation_available

    result = service.handle(command)

    assert result.status == "BUDGET_EXHAUSTED"
    assert result.budget_settlement_sha256 is not None
    assert f.task.status is TaskStatus.BLOCKED
    assert f.task.attempts == before.attempts
    assert f.task.retry_failures == before.retry_failures
    assert f.queue.item.status is WorkItemStatus.CLOSED
    assert f.native.repository.list_events(f.task.id)[:-1] == old_events
    assert (
        KnowledgeRecordStore(f.root / "invocations", read_only=True).find(
            "invocation-outcomes", f.queue.item.id, DeliveryInvocationOutcome
        )
        is None
    )
    assert service.handle(command) == result
    sidecar = f.root / "history-sidecar"
    copytree(f.root / "delivery-waits", sidecar / "state/delivery-waits")
    history = engineering_history(sidecar, f.task, f.collector.scope, f.native.scope.requirement_id)
    assert any(entry.source_sha256 == result.handling_sha256 for entry in history)
    assert isinstance(f.queue, UnknownQueue) and f.queue.commits == 1
    published = FileEvaluationEventStore(f.root / "evaluations").list_for_case(
        _default_case_id(f.task.id)
    )
    assert len(published) == 1 and isinstance(published[0], HumanActionEvent)
    assert published[0].action is HumanAction.SUPPLY_EVIDENCE
    assert "call_a7e4ebe2aed34bad899f8cc3588da3b5" in (published[0].note or "")


@pytest.mark.parametrize("completed", ["start_only_unknown_exhausted"], indirect=True)
def test_settled_unknown_source_uses_complete_isolated_survey_by_default(
    completed: CompletedFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = completed
    service = contained_service_for(f)
    command = HandleDeliveryWait.model_validate(
        {
            **f.queue.command().to_wire(),
            "confirm_local_execution_stopped": True,
            "local_stop_reference": "call_a7e4ebe2aed34bad899f8cc3588da3b5",
        }
    )
    result = service.handle(command)
    assert result.budget_settlement_sha256 is not None
    record = KnowledgeRecordStore(f.root / "delivery-preflight", read_only=True).get(
        "contained-unknown-budget-settlements",
        result.budget_settlement_sha256,
        ContainedUnknownBudgetSettlement,
    )

    def forbid_in_process(
        _observer: TrustedLegacyLocalExecutionObserver,
        *,
        worktree_root: Path,
        boot: LocalBootObservation,
    ) -> LegacyLocalExecutionSurvey:
        raise AssertionError("settled source must not run the Host in-process survey")

    calls: list[Path] = []

    def isolated(
        _observer: IsolatedLegacyLocalExecutionObserver,
        *,
        worktree_root: Path,
        boot: LocalBootObservation,
    ) -> LegacyLocalExecutionSurvey:
        calls.append(worktree_root)
        return FakeLocalObserver().observe(worktree_root=worktree_root, boot=boot)

    monkeypatch.setattr(TrustedLegacyLocalExecutionObserver, "observe", forbid_in_process)
    monkeypatch.setattr(IsolatedLegacyLocalExecutionObserver, "observe", isolated)
    guard = WorkerExecutionGuard()
    with guard.task_scope(f.root / "queue-worker-locks", f.task.id):
        capture = verify_settled_contained_unknown(
            record,
            repository=f.native.repository,
            queue=cast(MySqlRoleQueue, f.queue),
            state=f.root,
            route_root=f.root / "model-routes",
            artifacts=f.native.artifacts,
            git=f.native.git,
            guard=guard,
            boot_observer=FakeBootObserver(f),
        )
    assert capture.capture_sha256 == record.retained_capture_sha256
    assert calls == [Path(record.capture_start.worktree_path)]

    def incomplete(
        _observer: IsolatedLegacyLocalExecutionObserver,
        *,
        worktree_root: Path,
        boot: LocalBootObservation,
    ) -> LegacyLocalExecutionSurvey:
        return LegacyLocalExecutionSurvey.create(
            worktree_path=str(worktree_root),
            machine_sha256=boot.machine_sha256,
            boot_session_sha256=boot.boot_session_sha256,
            account_sha256="c" * 64,
            observed_at=datetime.now(UTC),
            scanner_version="local-execution-v1",
            blockers=("PROCESS_SCAN_INCOMPLETE",),
        )

    monkeypatch.setattr(IsolatedLegacyLocalExecutionObserver, "observe", incomplete)
    original_task = f.task
    original_events = f.native.repository.list_events(original_task.id)
    with (
        guard.task_scope(f.root / "queue-worker-locks", original_task.id),
        pytest.raises(LegacyRescuePrerequisiteError) as blocked,
    ):
        verify_settled_contained_unknown(
            record,
            repository=f.native.repository,
            queue=cast(MySqlRoleQueue, f.queue),
            state=f.root,
            route_root=f.root / "model-routes",
            artifacts=f.native.artifacts,
            git=f.native.git,
            guard=guard,
            boot_observer=FakeBootObserver(f),
        )
    assert blocked.value.code == "LEGACY_LOCAL_SURVEY_INCOMPLETE"
    assert f.task == original_task
    assert f.native.repository.list_events(original_task.id) == original_events


@pytest.mark.parametrize("completed", ["start_only_unknown_exhausted"], indirect=True)
def test_start_only_without_exact_human_stop_keeps_task_and_queue_waiting(
    completed: CompletedFixture,
) -> None:
    f = completed
    assert not (
        f.root / "continuations" / f.task.id / f"capture-stop-{f.start.request.run_id}.json"
    ).exists()
    service = contained_service_for(f)
    before_task, before_item = f.task, f.queue.item

    result = service.handle(HandleDeliveryWait.model_validate(f.queue.command().to_wire()))

    assert result.budget_settlement_sha256 is None
    assert f.task == before_task
    assert f.queue.item == before_item


@pytest.mark.parametrize("completed", ["start_only_unknown_exhausted"], indirect=True)
@pytest.mark.parametrize("late_fact", ["capture_stop", "invocation_outcome"])
def test_start_only_confirmation_refuses_new_original_final_fact(
    completed: CompletedFixture, late_fact: str
) -> None:
    f = completed
    service = contained_service_for(f)
    observed = service.inspect(InspectDeliveryWait.model_validate(f.queue.command().to_wire()))
    assert observed.local_stop_confirmation_available
    if late_fact == "capture_stop":
        f.ledger.put_capture_stop(f.capture_stop)
    else:
        KnowledgeRecordStore(f.root / "invocations").put(
            "invocation-outcomes", f.queue.item.id, f.outcome
        )
    before_task, before_item = f.task, f.queue.item
    command = HandleDeliveryWait.model_validate(
        {
            **f.queue.command().to_wire(),
            "confirm_local_execution_stopped": True,
            "local_stop_reference": "call_a7e4ebe2aed34bad899f8cc3588da3b5",
        }
    )
    with pytest.raises(ContinuationRejected, match=r"start-only|start.only"):
        service.handle(command)
    assert f.task == before_task
    assert f.queue.item == before_item
    assert not KnowledgeRecordStore(f.root / "delivery-preflight").list(
        "contained-unknown-budget-settlements", ContainedUnknownBudgetSettlement
    )


@pytest.mark.parametrize("completed", ["start_only_unknown_exhausted"], indirect=True)
def test_start_only_replay_repairs_audit_after_sql_commit(
    completed: CompletedFixture,
) -> None:
    f = completed
    service = contained_service_for(f)
    command = HandleDeliveryWait.model_validate(
        {
            **f.queue.command().to_wire(),
            "confirm_local_execution_stopped": True,
            "local_stop_reference": "call_a7e4ebe2aed34bad899f8cc3588da3b5",
        }
    )
    queue = cast(UnknownQueue, f.queue)
    queue.fail_after = True
    with pytest.raises(RuntimeError, match="test crash after commit"):
        service.handle(command)
    audit = FileEvaluationEventStore(f.root / "evaluations")
    assert audit.list_for_case(_default_case_id(f.task.id)) == ()
    assert f.task.status is TaskStatus.BLOCKED

    result = service.handle(command)

    assert result.status == "BUDGET_EXHAUSTED"
    assert queue.commits == 1
    actions = audit.list_for_case(_default_case_id(f.task.id))
    assert len(actions) == 1 and isinstance(actions[0], HumanActionEvent)
    assert actions[0].action is HumanAction.SUPPLY_EVIDENCE
    assert service.handle(command) == result
    assert audit.list_for_case(_default_case_id(f.task.id)) == actions
