"""Legacy rescue keeps UNKNOWN honest and requires independently observed OS containment."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from subprocess import SubprocessError
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, ModelRouteAttempt
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.context import ContextSource, FileContextBuilder, FileContextStore
from ai_software_engineer.domain import AgentRole, Task, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.continuation import (
    InterruptionContinuationPolicy,
    task_intent_sha256,
)
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import DeliveryResolution
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.execution_baseline import BaselinePurpose
from ai_software_engineer.git.mutation import WorkspaceMutationInventory
from ai_software_engineer.git.ports import WorktreeRef
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_models import BaselineExecutionReservation
from ai_software_engineer.manager.baseline_production import (
    BaselineExecuteCommand,
    BaselineProposeCommand,
    ProductionBaselineFactCollector,
)
from ai_software_engineer.manager.capacity_input_reader import PriorInvocationFence
from ai_software_engineer.manager.delivery_preflight import (
    DeliveryPreflightReceipt,
    DeliveryPreflightScope,
)
from ai_software_engineer.manager.dispatch import RecoveryDispatchRecord, _record_digest
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.manager.legacy_containment import (
    LegacyExecutionContainment,
    LocalBootObservation,
    TrustedLocalBootObserver,
)
from ai_software_engineer.manager.legacy_local_execution import (
    LegacyLocalExecutionSurvey,
    LegacyRescuePrerequisiteError,
)
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationScope,
    ExecutionCaptureStart,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.recovery import CapturedChanges, FileRecoveryStore, RecoveryAuthorization
from ai_software_engineer.recovery.bounded_input import complete_reapply_source_refs
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.recovery.records import RecoverySeedRecord
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from tests.manager.test_execution_baseline import setup
from tests.manager.test_execution_baseline_invocations import _allocation, _claim
from tests.manager.test_execution_baseline_reservation import reservation_fixture
from tests.manager.test_recovery_input_schedule import _fixture as recovery_schedule_fixture
from tests.recovery.test_authorization import Human, approval
from tests.recovery.test_bounded_reapply_input import _plan as bounded_reapply_plan
from tests.recovery.test_execution_records import allocation as recovery_allocation
from tests.recovery.test_task_record import record_for
from tests.work_queue.test_mysql_queue import queued_item

STARTED = datetime(2026, 10, 6, 14, 30, tzinfo=UTC)
BOOT = LocalBootObservation(
    machine_sha256="a" * 64,
    boot_session_sha256="b" * 64,
    booted_at=STARTED + timedelta(days=1),
)


def legacy_fixture(
    tmp_path: Path,
) -> tuple[ProductionBaselineFactCollector, Task, QueuedWorkItem, LegacyExecutionContainment]:
    collector, task, item, receipt = reservation_fixture(tmp_path)
    task = task.model_copy(
        update={
            "id": receipt.request.task_id,
            "interruption_continuation_policy": InterruptionContinuationPolicy(),
        }
    )
    item = item.model_copy(
        update={"repository_scopes": (task.repository,), "checkpoint_sequence": 1}
    )
    # Use a separate temporary root rather than rewriting an immutable old start.
    collector.state = tmp_path / "legacy"
    records = KnowledgeRecordStore(collector.state / "invocations")
    start = DeliveryInvocationStart(
        work_item_id=item.id,
        checkpoint_sequence=item.checkpoint_sequence,
        request=receipt.request,
        lease_id=receipt.claim_lease_id,
        started_at=STARTED,
        start_sha256="0" * 64,
    )
    start = start.model_copy(
        update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
    )
    records.put("invocation-starts", item.id, start)
    claim = _claim(item, start.lease_id)
    claim = claim.model_copy(
        update={
            "model_selection": claim.model_selection.model_copy(update={"route_kind": "codex_cli"})
        }
    )
    collector.scope = EngineeringScope(
        team_id="team_baseline",
        project_id="project_baseline",
        repository_id=item.repository_id,
        repository_root=task.repository,
    )
    collector.requirement_id = "delivery_baseline"
    collector.allocation = _allocation(task, "d" * 64)
    collector.permissions = receipt.request.permissions
    collector.purpose = BaselinePurpose.LEGACY_WORKSPACE_RESCUE
    collector.route_root = None
    collector.inputs = StoredCoderExecutionInputResolver(None)
    collector.capacity_artifacts = FileArtifactStore(tmp_path / "artifacts")
    item = item.model_copy(
        update={
            "status": WorkItemStatus.WAITING_HUMAN,
            "wait_reason": "unknown original execution",
            "wait_disposition": decide_delivery_disposition(
                DeliveryFailureFacts(
                    task_id=task.id,
                    work_item_id=item.id,
                    role=AgentRole.CODER,
                    classification="EXECUTION_UNCERTAIN",
                    source_revision=start.request.source_revision,
                    task_intent_sha256=task_intent_sha256(task),
                    checkpoint_sequence=item.checkpoint_sequence,
                    budget_available=True,
                )
            ),
        }
    )
    step = QueuedRoleStep(
        work_item=item,
        boundary=RoleRunBoundary(
            task.id,
            AgentRole.CODER,
            item.attempt,
            item.checkpoint_sequence,
            start.request.source_revision,
        ),
        allocation_sha256=collector.allocation.dispatch_sha256,
    )

    class Queue(MySqlRoleQueue):
        def __init__(self) -> None:
            pass

        def original_claim(self, lease_id: str) -> QueueClaim:
            assert lease_id == claim.lease.id
            return claim

        def claims_for_work_item(self, identity: str) -> tuple[QueueClaim, ...]:
            assert identity == item.id
            return (claim,)

        def step_for_invocation(self, identity: str, baseline: str | None) -> QueuedRoleStep:
            assert identity == item.id and baseline is None
            return step

    class Observer:
        def observe(self) -> LocalBootObservation:
            return BOOT

    collector.queue, collector.observer = Queue(), Observer()
    collector.git = Mock(
        recover=Mock(
            return_value=WorktreeRef(
                task_id=task.id,
                role=AgentRole.CODER,
                attempt=1,
                path=tmp_path.resolve(),
                head_revision=start.request.source_revision,
                branch="ai/feature/legacy-fixture",
                detached=False,
            )
        )
    )
    containment = collector._legacy_containment(task, item)
    return collector, task, item, containment


def test_exact_new_observation_preserves_original_unknown_and_complete_claim(
    tmp_path: Path,
) -> None:
    collector, task, item, containment = legacy_fixture(tmp_path)
    containment.validate_integrity()
    assert containment.original_claim.lease.id == containment.original_start.lease_id
    assert "process_stop" not in containment.to_wire()
    before = {path: path.read_bytes() for path in collector.state.rglob("*.json")}
    (proof,) = collector._invocations(task, (item,), (), (), legacy=containment)
    assert proof.proof_kind == "legacy_execution_contained"
    assert proof.legacy_containment == containment
    assert proof.outcome_sha256 is None and proof.interruption_receipt_sha256 is None
    assert before == {path: path.read_bytes() for path in collector.state.rglob("*.json")}


@pytest.mark.parametrize("receipt_only", [False, True])
def test_legacy_rescue_covers_earlier_reclaimed_claim_without_model_start(
    tmp_path: Path,
    receipt_only: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector, task, item, original = legacy_fixture(tmp_path)
    later_at = original.original_claim.claimed_at + timedelta(hours=2)
    expired_at = original.original_claim.claimed_at + timedelta(hours=1)
    old = _claim(
        item.model_copy(
            update={"status": WorkItemStatus.READY, "wait_reason": None, "wait_disposition": None}
        ),
        "lease_uninvoked_before_reclaim",
    )
    old = QueueClaim(
        work_item=old.work_item,
        assignment=old.assignment.model_copy(update={"id": "assignment_uninvoked_before_reclaim"}),
        lease=old.lease.model_copy(update={"assignment_id": "assignment_uninvoked_before_reclaim"}),
        model_selection=old.model_selection,
        worker_id=old.worker_id,
        claimed_at=old.claimed_at,
    )
    next_claim = original.original_claim
    next_claim = QueueClaim(
        work_item=next_claim.work_item.model_copy(
            update={"dispatch_sequence": 1, "updated_at": later_at}
        ),
        assignment=next_claim.assignment.model_copy(update={"assigned_at": later_at}),
        lease=next_claim.lease.model_copy(
            update={"acquired_at": later_at, "expires_at": later_at + timedelta(hours=1)}
        ),
        model_selection=next_claim.model_selection.model_copy(update={"selected_at": later_at}),
        worker_id=next_claim.worker_id,
        claimed_at=later_at,
    )
    contained = LegacyExecutionContainment.create(
        scope=original.scope,
        requirement_id=original.requirement_id,
        dispatch_sha256=original.dispatch_sha256,
        task_intent_sha256=original.task_intent_sha256,
        original_start=original.original_start,
        original_claim=next_claim,
        boot=original.boot,
    )
    current = item.model_copy(update={"dispatch_sequence": 1})
    step = QueuedRoleStep(
        work_item=current,
        boundary=RoleRunBoundary(
            task.id,
            AgentRole.CODER,
            item.attempt,
            item.checkpoint_sequence,
            original.original_start.request.source_revision,
        ),
        allocation_sha256=collector.allocation.dispatch_sha256,
    )

    class Queue(MySqlRoleQueue):
        def __init__(self) -> None:
            pass

        def original_claim(self, lease_id: str) -> QueueClaim:
            return {old.lease.id: old, next_claim.lease.id: next_claim}[lease_id]

        def claims_for_work_item(self, identity: str) -> tuple[QueueClaim, ...]:
            assert identity == item.id
            return old, next_claim

        def step_for_claim(self, claim: QueueClaim) -> QueuedRoleStep:
            return step.model_copy(update={"work_item": claim.work_item})

        def step_for_invocation(self, identity: str, baseline: str | None) -> QueuedRoleStep:
            assert identity == item.id and baseline is None
            return step

    class Cursor:
        def __init__(self) -> None:
            self.rows: list[dict[str, object]] = []

        def execute(self, query: str, parameters: tuple[str, ...]) -> None:
            if "work_queue_claims" in query:
                assert parameters == (old.lease.id,)
                self.rows = [
                    {
                        "lease_id": old.lease.id,
                        "work_item_id": item.id,
                        "task_id": task.id,
                        "state": "EXPIRED",
                        "expires_at": old.lease.expires_at.isoformat(),
                        "ended_at": expired_at.isoformat(),
                    }
                ]
            elif "event_type='CLAIMED'" in query:
                assert parameters == (next_claim.lease.id,)
                self.rows = [{"sequence": 101}]
            else:
                assert parameters == (old.lease.id,)
                requeued = old.work_item.model_copy(
                    update={
                        "status": WorkItemStatus.RETRY_SCHEDULED,
                        "dispatch_sequence": 1,
                        "wait_reason": f"lease_expired:{old.lease.id}",
                        "available_at": expired_at + timedelta(minutes=1),
                        "updated_at": expired_at,
                    }
                )
                self.rows = [
                    {
                        "sequence": 100,
                        "event_type": "LEASE_EXPIRED",
                        "work_item_id": item.id,
                        "lease_id": old.lease.id,
                        "from_status": "RUNNING",
                        "to_status": "RETRY_SCHEDULED",
                        "occurred_at": expired_at.isoformat(),
                        "payload_json": json.dumps({"work_item": requeued.to_wire(), "detail": {}}),
                    }
                ]

        def fetchall(self) -> list[dict[str, object]]:
            return self.rows

    collector.queue = Queue()
    collector.route_root = tmp_path / "model-routes"
    (tmp_path / "knowledge" / "runs").mkdir(parents=True)
    collector._scope_held = True
    collector._idle_cursor = Cursor()  # type: ignore[assignment]
    if receipt_only:
        receipt = DeliveryPreflightReceipt(
            scope=DeliveryPreflightScope(
                team_id=collector.scope.team_id,
                project_id=collector.scope.project_id,
                repository_id=collector.scope.repository_id,
                requirement_id=collector.requirement_id,
            ),
            task_id=task.id,
            source_revision=original.original_start.request.source_revision,
            plan_sha256="d" * 64,
            frozen_policy_sha256="e" * 64,
            requirements_sha256="f" * 64,
            observations=(),
            status="WAIT_ENGINEERING",
            checked_at=old.claimed_at + timedelta(minutes=30),
            receipt_sha256="0" * 64,
        )
        receipt = receipt.model_copy(
            update={
                "receipt_sha256": digest(
                    receipt.model_dump(mode="json", exclude={"receipt_sha256"})
                )
            }
        )
        KnowledgeRecordStore(collector.state / "delivery-preflight").put(
            "preflight-receipts", receipt.receipt_sha256, receipt
        )
        with pytest.raises(ValueError, match="执行前检查收据"):
            collector._invocations(task, (current,), (), (), legacy=contained)
        return
    (proof,) = collector._invocations(task, (current,), (), (), legacy=contained)
    assert proof.proof_kind == "legacy_execution_contained"
    assert len(proof.reclaimed_uninvoked_claims) == 1
    assert proof.reclaimed_uninvoked_claims[0].lease_id == old.lease.id
    monkeypatch.setattr(
        collector,
        "_historical_legacy",
        lambda *_: (contained, Mock(binding_sha256="e" * 64)),
    )
    monkeypatch.setattr(
        collector,
        "_prior_invocation_fence",
        lambda *_: PriorInvocationFence(contained.original_start),
    )
    (replayed,) = collector._invocations(task, (current,), (), (), legacy=None)
    assert replayed.reclaimed_uninvoked_claims == proof.reclaimed_uninvoked_claims
    assert replayed.legacy_binding_sha256 == "e" * 64


@pytest.mark.parametrize(
    "tamper",
    [
        None,
        "wrong_resolution",
        "missing_wait",
        "not_released",
        "expired_release",
        "partial_preflight",
        "isolated_context",
    ],
)
def test_legacy_rescue_covers_consumed_pre_context_claim_before_real_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str | None,
) -> None:
    """A real later call must not make the earlier approved no-Context claim unknown."""
    collector, task, item, original = legacy_fixture(tmp_path)
    current_start = original.original_start
    later_at = current_start.started_at - timedelta(minutes=1)
    first_at = later_at - timedelta(hours=2)
    first = _claim(
        item.model_copy(
            update={"status": WorkItemStatus.READY, "wait_reason": None, "wait_disposition": None}
        ),
        "lease_pre_context_wait",
    )
    first = QueueClaim(
        work_item=first.work_item.model_copy(
            update={"dispatch_sequence": 0, "updated_at": first_at}
        ),
        assignment=first.assignment.model_copy(
            update={"id": "assignment_pre_context_wait", "assigned_at": first_at}
        ),
        lease=first.lease.model_copy(
            update={
                "assignment_id": "assignment_pre_context_wait",
                "acquired_at": first_at,
                "expires_at": first_at + timedelta(hours=1),
            }
        ),
        model_selection=first.model_selection.model_copy(update={"selected_at": first_at}),
        worker_id=first.worker_id,
        claimed_at=first_at,
    )
    second = QueueClaim(
        work_item=original.original_claim.work_item.model_copy(
            update={"dispatch_sequence": 1, "updated_at": later_at}
        ),
        assignment=original.original_claim.assignment.model_copy(update={"assigned_at": later_at}),
        lease=original.original_claim.lease.model_copy(
            update={"acquired_at": later_at, "expires_at": later_at + timedelta(hours=1)}
        ),
        model_selection=original.original_claim.model_selection.model_copy(
            update={"selected_at": later_at}
        ),
        worker_id=original.original_claim.worker_id,
        claimed_at=later_at,
    )
    contained = LegacyExecutionContainment.create(
        scope=original.scope,
        requirement_id=original.requirement_id,
        dispatch_sha256=original.dispatch_sha256,
        task_intent_sha256=original.task_intent_sha256,
        original_start=current_start,
        original_claim=second,
        boot=original.boot,
    )
    current = item.model_copy(update={"dispatch_sequence": 1})
    step = QueuedRoleStep(
        work_item=current,
        boundary=RoleRunBoundary(
            task.id,
            AgentRole.CODER,
            item.attempt,
            item.checkpoint_sequence,
            current_start.request.source_revision,
        ),
        allocation_sha256=collector.allocation.dispatch_sha256,
    )

    class Queue(MySqlRoleQueue):
        def __init__(self) -> None:
            pass

        def original_claim(self, lease_id: str) -> QueueClaim:
            return {first.lease.id: first, second.lease.id: second}[lease_id]

        def claims_for_work_item(self, identity: str) -> tuple[QueueClaim, ...]:
            assert identity == current.id
            return first, second

        def step_for_claim(self, claim: QueueClaim) -> QueuedRoleStep:
            return step.model_copy(update={"work_item": claim.work_item})

        def step_for_invocation(self, identity: str, baseline: str | None) -> QueuedRoleStep:
            assert identity == current.id and baseline is None
            return step

    collector.queue = Queue()
    collector.route_root = tmp_path / "model-routes"
    (tmp_path / "knowledge" / "runs").mkdir(parents=True)
    collector._scope_held = True

    waited_at = first_at + timedelta(minutes=30)
    resolved_at = first_at + timedelta(minutes=45)
    waited_item = first.work_item.model_copy(
        update={
            "status": WorkItemStatus.WAITING_DEPENDENCY,
            "wait_reason": "Context input capacity",
            "wait_disposition": decide_delivery_disposition(
                DeliveryFailureFacts(
                    task_id=task.id,
                    work_item_id=item.id,
                    role=AgentRole.CODER,
                    classification="CONTEXT_CAPACITY",
                    source_revision=current_start.request.source_revision,
                    task_intent_sha256=task_intent_sha256(task),
                    checkpoint_sequence=item.checkpoint_sequence,
                    budget_available=True,
                )
            ),
            "updated_at": waited_at,
        }
    )
    resolved_item = waited_item.model_copy(
        update={
            "status": WorkItemStatus.READY,
            "wait_reason": None,
            "wait_disposition": None,
            "dispatch_sequence": 1,
            "updated_at": resolved_at,
        }
    )
    _, _, prior_decision = recovery_schedule_fixture()
    original_input = prior_decision.pre_context_recovery_input
    assert original_input is not None
    original_input = original_input.model_copy(
        update={
            "original_claim_sha256": digest(first.to_wire()),
            "original_lease_id": first.lease.id,
            "worktree_head_revision": current_start.request.source_revision,
        }
    )
    decision = prior_decision.model_copy(
        update={
            "task_id": task.id,
            "work_item_id": item.id,
            "expected_disposition_sha256": waited_item.wait_disposition.disposition_sha256,
            "expected_task_intent_sha256": task_intent_sha256(task),
            "expected_source_revision": current_start.request.source_revision,
            "expected_checkpoint_sequence": item.checkpoint_sequence,
            "task_revision": item.checkpoint_sequence,
            "pre_context_recovery_input": original_input,
        }
    )
    decision = decision.model_copy(update={"resolution_sha256": decision.recompute_sha256()})
    decision.validate_integrity()
    schedule = SimpleNamespace(
        validate_integrity=lambda: None,
        work_item_id=item.id,
        original_lease_id=first.lease.id,
        original_claim_sha256=digest(first.to_wire()),
        target_base_revision=current_start.request.source_revision,
        disposition_sha256=waited_item.wait_disposition.disposition_sha256,
        task_id=task.id,
        schedule_sha256=decision.recovery_input_schedule_sha256,
    )
    monkeypatch.setattr(collector, "_consumed_recovery_schedule", lambda *_: (schedule, decision))
    if tamper == "partial_preflight":
        receipt = DeliveryPreflightReceipt(
            scope=DeliveryPreflightScope(
                team_id=collector.scope.team_id,
                project_id=collector.scope.project_id,
                repository_id=collector.scope.repository_id,
                requirement_id=collector.requirement_id,
            ),
            task_id=task.id,
            source_revision=current_start.request.source_revision,
            plan_sha256="d" * 64,
            frozen_policy_sha256="e" * 64,
            requirements_sha256="f" * 64,
            observations=(),
            status="WAIT_ENGINEERING",
            checked_at=first_at + timedelta(minutes=10),
            receipt_sha256="0" * 64,
        )
        receipt = receipt.model_copy(
            update={
                "receipt_sha256": digest(
                    receipt.model_dump(mode="json", exclude={"receipt_sha256"})
                )
            }
        )
        KnowledgeRecordStore(collector.state / "delivery-preflight").put(
            "preflight-receipts", receipt.receipt_sha256, receipt
        )
    if tamper == "isolated_context":
        context = FileContextBuilder(
            tmp_path,
            current_start.request.permissions,
            sources=(
                ContextSource(
                    source_id="execution.claim",
                    uri=f"claim://{first.lease.id}",
                    content=json.dumps({"lease_id": first.lease.id}),
                    roles=(AgentRole.CODER,),
                    required=True,
                ),
            ),
        ).build(task, AgentRole.CODER, attempt=item.attempt)
        FileContextStore(collector.state.parent / "contexts").put(context)

    class Cursor:
        rows: list[dict[str, object]]

        def execute(self, query: str, parameters: tuple[str, ...]) -> None:
            if "work_queue_claims" in query:
                assert parameters == (first.lease.id,)
                self.rows = [
                    {
                        "lease_id": first.lease.id,
                        "work_item_id": current.id,
                        "task_id": task.id,
                        "state": "EXPIRED" if tamper == "not_released" else "RELEASED",
                        "expires_at": (
                            first_at + timedelta(minutes=20)
                            if tamper == "expired_release"
                            else first.lease.expires_at
                        ).isoformat(),
                        "ended_at": waited_at.isoformat(),
                    }
                ]
            else:
                assert parameters == (current.id,)
                self.rows = [
                    {
                        "sequence": 1,
                        "event_type": "CLAIMED",
                        "work_item_id": item.id,
                        "lease_id": first.lease.id,
                        "from_status": "READY",
                        "to_status": "LEASED",
                        "occurred_at": first_at.isoformat(),
                        "payload_json": json.dumps(
                            {
                                "work_item": first.work_item.to_wire(),
                                "detail": {"queue_claim": first.to_wire()},
                            }
                        ),
                    },
                    {
                        "sequence": 2,
                        "event_type": "STARTED",
                        "work_item_id": item.id,
                        "lease_id": first.lease.id,
                        "from_status": "LEASED",
                        "to_status": "RUNNING",
                        "occurred_at": (first_at + timedelta(minutes=1)).isoformat(),
                        "payload_json": json.dumps(
                            {
                                "work_item": first.work_item.model_copy(
                                    update={
                                        "status": WorkItemStatus.RUNNING,
                                        "updated_at": first_at + timedelta(minutes=1),
                                    }
                                ).to_wire(),
                                "detail": {},
                            }
                        ),
                    },
                    {
                        "sequence": 3,
                        "event_type": "WAITING",
                        "work_item_id": item.id,
                        "lease_id": first.lease.id,
                        "from_status": "RUNNING",
                        "to_status": "WAITING_DEPENDENCY",
                        "occurred_at": waited_at.isoformat(),
                        "payload_json": json.dumps(
                            {"work_item": waited_item.to_wire(), "detail": {}}
                        ),
                    },
                    {
                        "sequence": 4,
                        "event_type": "WAIT_RESOLVED",
                        "work_item_id": item.id,
                        "lease_id": None,
                        "from_status": "WAITING_DEPENDENCY",
                        "to_status": "READY",
                        "occurred_at": resolved_at.isoformat(),
                        "payload_json": json.dumps(
                            {
                                "work_item": resolved_item.to_wire(),
                                "detail": {
                                    "resolution_sha256": decision.resolution_sha256,
                                    "next_work_item_id": item.id,
                                    "resolution": decision.to_wire(),
                                    "budget_refund": False,
                                },
                            }
                        ),
                    },
                    {
                        "sequence": 5,
                        "event_type": "CLAIMED",
                        "work_item_id": item.id,
                        "lease_id": second.lease.id,
                        "from_status": "READY",
                        "to_status": "LEASED",
                        "occurred_at": later_at.isoformat(),
                        "payload_json": json.dumps(
                            {
                                "work_item": second.work_item.to_wire(),
                                "detail": {"queue_claim": second.to_wire()},
                            }
                        ),
                    },
                ]
                if tamper == "missing_wait":
                    self.rows = [row for row in self.rows if row["event_type"] != "WAITING"]
                elif tamper == "wrong_resolution":
                    resolved_event = self.rows[3]
                    payload = json.loads(str(resolved_event["payload_json"]))
                    payload["detail"]["resolution_sha256"] = "f" * 64
                    resolved_event["payload_json"] = json.dumps(payload)

        def fetchall(self) -> list[dict[str, object]]:
            return self.rows

    collector._idle_cursor = Cursor()  # type: ignore[assignment]
    if tamper is not None:
        with pytest.raises(ValueError, match="预 Context"):
            collector._invocations(task, (current,), (), (), legacy=contained)
        return
    (proof,) = collector._invocations(task, (current,), (), (), legacy=contained)
    assert proof.consumed_pre_context_claims[0].lease_id == first.lease.id


def test_consumed_pre_context_schedule_reopens_sealed_recovery_lineage(
    tmp_path: Path,
) -> None:
    """The collector reads real immutable Plan/authorization/Task/seed and SQL decision."""
    plan = bounded_reapply_plan(tmp_path / "project")
    authorization = RecoveryAuthorization.create(approval(plan), Human().verify(approval(plan)))
    native_root = tmp_path / "native"
    native_root.mkdir()
    native = recovery_allocation(native_root)
    sealed = record_for(plan, authorization)
    sealed_task = sealed.task.model_copy(
        update={"metadata": {**sealed.task.metadata, "execution_plan_id": native.execution_plan_id}}
    )
    sealed = sealed.model_copy(update={"task": sealed_task})
    sealed = sealed.model_copy(update={"record_sha256": sealed.recompute_sha256()})
    current = sealed_task.model_copy(update={"status": TaskStatus.IMPLEMENTING, "attempts": 1})
    phases = tuple(
        phase.model_copy(
            update={
                "assignment": phase.assignment.model_copy(
                    update={
                        "task_id": current.id,
                        "repository_id": plan.source.scope.repository_id,
                    }
                ),
                "lease": phase.lease.model_copy(update={"task_id": current.id}),
            }
        )
        for phase in native.phases
    )
    dispatch = RecoveryDispatchRecord(
        id=f"dispatch_commit_{plan.plan_sha256}",
        repository_id=plan.source.scope.repository_id,
        task_id=current.id,
        project_request_id=sealed.rebound_request.id,
        execution_plan_id=native.execution_plan_id,
        execution_plan_sha256=plan.source.execution_plan_sha256,
        execution_plan_phase_ids=native.execution_plan_phase_ids,
        recovery_plan_sha256=plan.plan_sha256,
        recovery_task_record_sha256=sealed.record_sha256,
        workforce_snapshot_sha256=native.workforce_snapshot_sha256,
        task=sealed_task,
        phases=phases,
        committed_at=native.committed_at,
        dispatch_sha256="0" * 64,
    )
    dispatch = dispatch.model_copy(update={"dispatch_sha256": _record_digest(dispatch)})
    dispatch.validate_integrity()
    capture = plan.capture.to_capture()
    target = replace(
        capture.worktree,
        task_id=current.id,
        head_revision=plan.target_base_revision,
        path=tmp_path / "target",
        branch=f"ai/{current.id}/attempt-1",
    )
    seed = RecoverySeedRecord.create(
        plan_sha256=plan.plan_sha256,
        dispatch_sha256=dispatch.dispatch_sha256,
        capture=CapturedChanges.from_capture(
            replace(
                capture,
                worktree=target,
                patch=b"",
                file_sha256s=(),
            )
        ),
    )
    state = tmp_path / "sidecar" / "state"
    state.mkdir(parents=True)
    store = FileRecoveryStore.initialize(
        state / f"recovery-{plan.source.scope.delivery_id}", scope=plan.source.scope
    )
    store.put_plan(plan)
    store.put_authorization(authorization)
    store.put_task_record(sealed)
    store.put_seed(seed)
    item = queued_item(checkpoint_sequence=2).model_copy(
        update={
            "task_id": current.id,
            "repository_id": plan.source.scope.repository_id,
            "attempt": 1,
        }
    )
    original = _claim(item, "lease_sealed_pre_context")
    source_task, source_schedule, source_decision = recovery_schedule_fixture()
    del source_task
    sources = complete_reapply_source_refs(plan)
    schedule = source_schedule.model_copy(
        update={
            "plan_sha256": plan.plan_sha256,
            "task_id": current.id,
            "task_intent_sha256": task_intent_sha256(current),
            "target_base_revision": plan.target_base_revision,
            "authorization_sha256": authorization.authorization_sha256,
            "task_record_sha256": sealed.record_sha256,
            "dispatch_sha256": dispatch.dispatch_sha256,
            "seed_record_sha256": seed.record_sha256,
            "work_item_id": item.id,
            "task_revision": 2,
            "task_snapshot_sha256": digest(current.to_wire()),
            "original_claim_sha256": digest(original.to_wire()),
            "original_lease_id": original.lease.id,
            "sources": sources,
        }
    )
    schedule = schedule.model_copy(update={"schedule_sha256": schedule.recompute_sha256()})
    schedule.validate_integrity()
    original_input = source_decision.pre_context_recovery_input
    assert original_input is not None
    original_input = original_input.model_copy(
        update={
            "plan_sha256": plan.plan_sha256,
            "authorization_sha256": authorization.authorization_sha256,
            "task_record_sha256": sealed.record_sha256,
            "dispatch_sha256": dispatch.dispatch_sha256,
            "seed_record_sha256": seed.record_sha256,
            "source_inventory_sha256": digest(tuple(source.to_wire() for source in sources)),
            "original_claim_sha256": digest(original.to_wire()),
            "original_lease_id": original.lease.id,
            "worktree_head_revision": plan.target_base_revision,
        }
    )
    decision = source_decision.model_copy(
        update={
            "task_id": current.id,
            "work_item_id": item.id,
            "expected_disposition_sha256": schedule.disposition_sha256,
            "expected_task_intent_sha256": task_intent_sha256(current),
            "expected_source_revision": plan.target_base_revision,
            "expected_checkpoint_sequence": 2,
            "task_revision": 2,
            "task_snapshot_sha256": digest(current.to_wire()),
            "step_sha256": schedule.step_sha256,
            "recovery_input_schedule_sha256": schedule.schedule_sha256,
            "pre_context_recovery_input": original_input,
        }
    )
    decision = decision.model_copy(update={"resolution_sha256": decision.recompute_sha256()})
    decision.validate_integrity()
    records = KnowledgeRecordStore(state / "delivery-waits")
    records.put("recovery-input-schedules", plan.plan_sha256, schedule)

    class Queue(MySqlRoleQueue):
        def __init__(self) -> None:
            self.consumed: DeliveryResolution | None = decision

        def consumed_recovery_input_resolution(self, task_id: str) -> DeliveryResolution | None:
            assert task_id == current.id
            return self.consumed

        def original_claim(self, lease_id: str) -> QueueClaim:
            assert lease_id == original.lease.id
            return original

    collector = ProductionBaselineFactCollector.__new__(ProductionBaselineFactCollector)
    collector.allocation = dispatch
    collector.state = state
    collector.scope = EngineeringScope(
        team_id=plan.source.scope.team_id,
        project_id="project_sealed",
        repository_id=plan.source.scope.repository_id,
        repository_root=plan.source.scope.repository_root,
    )
    collector.requirement_id = plan.source.scope.delivery_id
    collector.queue = Queue()
    assert collector._consumed_recovery_schedule(current) == (schedule, decision)
    collector.queue.consumed = None
    assert collector._consumed_recovery_schedule(current) is None
    collector.queue.consumed = decision.model_copy(
        update={"recovery_input_schedule_sha256": "9" * 64}
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        collector._consumed_recovery_schedule(current)


def test_legacy_unknown_consumes_next_work_and_cannot_refund_or_infer_already_reserved(
    tmp_path: Path,
) -> None:
    collector, task, item, containment = legacy_fixture(tmp_path)
    reservation = collector._reservation(task, item, (), legacy=containment)
    assert reservation.retry_cause == "legacy_execution_abandoned"
    assert reservation.next_execution_attempt == task.attempts + 1
    assert reservation.retry_failure is None and not reservation.reservation_already_applied
    assert reservation.current_invocation_outcome_sha256 is None
    assert reservation.interruption_receipt_sha256 is None
    with pytest.raises(ValueError, match="工作额度"):
        collector._reservation(
            task.model_copy(update={"attempts": 2}), item, (), legacy=containment
        )
    with pytest.raises(ValueError, match="consume new work"):
        BaselineExecutionReservation.model_validate(
            {**reservation.to_wire(), "reservation_already_applied": True}
        )


@pytest.mark.parametrize("booted_at", [STARTED, STARTED - timedelta(seconds=1)])
def test_service_restart_expired_lease_and_old_boot_cannot_contain_legacy_run(
    tmp_path: Path, booted_at: datetime
) -> None:
    _, _, _, containment = legacy_fixture(tmp_path)
    values = containment.to_wire()
    values["boot"] = BOOT.model_copy(update={"booted_at": booted_at}).to_wire()
    with pytest.raises(ValueError, match="整台电脑"):
        LegacyExecutionContainment.model_validate(values)


@pytest.mark.parametrize("route", [None, "responses"])
def test_non_native_or_unrecorded_route_cannot_use_boot_containment(
    tmp_path: Path, route: str | None
) -> None:
    _, _, _, containment = legacy_fixture(tmp_path)
    claim = containment.original_claim
    claim = claim.model_copy(
        update={"model_selection": claim.model_selection.model_copy(update={"route_kind": route})}
    )
    with pytest.raises(ValueError, match="本机 Coder"):
        LegacyExecutionContainment.create(
            **containment.model_dump(
                mode="python", exclude={"original_claim", "containment_sha256"}
            ),
            original_claim=claim,
        )


def test_mac_observer_uses_stable_hashed_identity_without_raw_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ai_software_engineer.manager.legacy_containment.sys.platform", "darwin")
    machine = "00000000-0000-4000-8000-000000000001"
    session = "00000000-0000-4000-8000-000000000002"
    calls: list[tuple[str, ...]] = []

    class Observer(TrustedLocalBootObserver):
        def _command(self, argv: tuple[str, ...]) -> str:
            calls.append(argv)
            if argv[-1] == "kern.bootsessionuuid":
                return session
            if argv[-1] == "kern.boottime":
                return "{ sec = 1750000000, usec = 0 }"
            return f'"IOPlatformUUID" = "{machine}"'

    observer = Observer()
    first, second = observer.observe(), observer.observe()
    assert first.same_boot(second) and first == second
    assert machine not in first.model_dump_json() and session not in first.model_dump_json()
    assert calls[0] == ("/usr/sbin/sysctl", "-n", "kern.bootsessionuuid")
    assert first.booted_at == datetime.fromtimestamp(1750000000, UTC)
    assert not first.same_boot(first.model_copy(update={"boot_session_sha256": "c" * 64}))


def test_unreadable_or_ambiguous_os_identity_returns_clear_prerequisite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ai_software_engineer.manager.legacy_containment.sys.platform", "darwin")

    class Observer(TrustedLocalBootObserver):
        def _command(self, argv: tuple[str, ...]) -> str:
            return "invalid OS identity, no user-controlled fallback"

    with pytest.raises(ValueError, match="仅重启 ASE 服务不能"):
        Observer().observe()


def test_linux_observer_reads_only_bounded_fixed_os_identity_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ai_software_engineer.manager.legacy_containment.sys.platform", "linux")
    paths: list[str] = []

    class Observer(TrustedLocalBootObserver):
        def _file(self, path: str) -> str:
            paths.append(path)
            return {
                "/etc/machine-id": "0" * 32,
                "/proc/sys/kernel/random/boot_id": "00000000-0000-4000-8000-000000000002",
                "/proc/stat": "cpu 1 2 3\nbtime 1750000000\nprocesses 12",
            }[path]

        def _command(self, argv: tuple[str, ...]) -> str:
            raise AssertionError("Linux uses its bounded native OS files")

    observation = Observer().observe()
    assert observation.booted_at == datetime.fromtimestamp(1750000000, UTC)
    assert paths == ["/etc/machine-id", "/proc/sys/kernel/random/boot_id", "/proc/stat"]
    assert "0" * 32 not in observation.model_dump_json()


@pytest.mark.parametrize("problem", ["start_digest", "claim_identity", "claim_route"])
def test_containment_rejects_altered_original_run_claim_or_digest(
    tmp_path: Path,
    problem: str,
) -> None:
    _, _, _, containment = legacy_fixture(tmp_path)
    values = containment.model_dump(mode="python", exclude={"containment_sha256"})
    if problem == "start_digest":
        values["original_start"] = containment.original_start.model_copy(
            update={"start_sha256": "f" * 64}
        )
    else:
        claim = containment.original_claim
        if problem == "claim_identity":
            values["original_claim"] = claim.model_copy(
                update={
                    "work_item": claim.work_item.model_copy(update={"id": "work_other_original"})
                }
            )
        else:
            values["original_claim"] = claim.model_copy(
                update={
                    "model_selection": claim.model_selection.model_copy(update={"route_kind": None})
                }
            )
    with pytest.raises(ValueError):
        LegacyExecutionContainment.create(**values)


def test_default_source_purpose_and_confirmation_keep_old_command_wire_bytes(
    tmp_path: Path,
) -> None:
    f = setup(tmp_path)
    plan = f.service.propose(f.target)
    assert "purpose" not in plan.to_wire()
    assert "legacy_containment" not in plan.facts.to_wire()
    assert plan.plan_sha256 == digest(plan.model_dump(mode="json", exclude={"plan_sha256"}))
    command = BaselineProposeCommand(
        delivery_id="delivery_legacy_fixture",
        task_id=plan.facts.task.id,
        expected_task_intent_sha256=task_intent_sha256(plan.facts.task),
        expected_task_revision=plan.facts.task_revision,
        expected_work_item_id=plan.facts.work_item_id,
        expected_source_revision=plan.dirty_capture.source_revision,
        target_base_ref=plan.target_base_ref,
    )
    command.require_plan(plan)
    assert "purpose" not in command.to_wire()
    execute = BaselineExecuteCommand(
        delivery_id=command.delivery_id,
        task_id=command.task_id,
        expected_plan_sha256=plan.plan_sha256,
        reference="fixture legacy wire preservation",
    )
    execute.require_plan(plan)
    assert "confirm_legacy_containment" not in execute.to_wire()
    with pytest.raises(ValueError, match="旧执行救援"):
        execute.model_copy(update={"confirm_legacy_containment": True}).require_plan(plan)


@pytest.mark.parametrize("fallback", [False, True])
def test_saved_final_or_unknown_successor_route_refuses_legacy_abandonment(
    tmp_path: Path,
    fallback: bool,
) -> None:
    collector, task, item, containment = legacy_fixture(tmp_path)
    start = containment.original_start
    result = AgentResult(
        run_id=start.request.run_id,
        task_id=task.id,
        role=AgentRole.CODER,
        attempt=start.request.attempt,
        source_revision=start.request.source_revision,
        context_manifest_id=start.request.context_manifest_id,
        status=AgentRunStatus.FAILED,
        error=AgentFailure(
            code=AgentErrorCode.PROVIDER_UNAVAILABLE, message="fixture failure", transient=True
        ),
    )
    collector.route_root = tmp_path / "model-routes"
    route = ModelRouteAttempt.create(
        request=start.request,
        route_index=1,
        provider="codex",
        model="fixture native",
        route_kind="codex_cli",
        started_at=start.started_at,
        completed_at=start.started_at + timedelta(seconds=1),
        result=result,
        fallback=fallback,
    )
    FileModelRouteAttemptStore(collector.route_root).append(route)
    before = {path: path.read_bytes() for path in collector.state.rglob("*.json")}
    with pytest.raises(ValueError, match="模型切换" if fallback else "封存最终结果"):
        collector._legacy_containment(task, item)
    assert before == {path: path.read_bytes() for path in collector.state.rglob("*.json")}


@pytest.mark.parametrize("kind", ["capture-stop", "receipt"])
def test_existing_original_runner_record_keeps_native_fact_handling_path(
    tmp_path: Path,
    kind: str,
) -> None:
    collector, task, item, containment = legacy_fixture(tmp_path)
    root = collector.state / "continuations" / task.id
    root.mkdir(parents=True)
    marker = root / f"{kind}-{containment.original_start.request.run_id}.json"
    marker.write_text("existing original record must not be overwritten")
    with pytest.raises(ValueError, match="已有现场或停止记录"):
        collector._legacy_containment(task, item)
    assert marker.read_text() == "existing original record must not be overwritten"


def test_start_only_capture_is_validated_and_does_not_block_legacy_rescue(
    tmp_path: Path,
) -> None:
    collector, task, item, containment = legacy_fixture(tmp_path)
    continuation_parent = collector.state / "continuations"
    continuation_parent.mkdir(parents=True, mode=0o700)
    ledger = FileContinuationStore.initialize(continuation_parent / task.id, task_id=task.id)
    policy = task.interruption_continuation_policy
    assert policy is not None
    capture_start = ExecutionCaptureStart.create(
        scope=ContinuationScope(
            team_id=collector.scope.team_id,
            project_id=collector.scope.project_id,
            repository_id=collector.scope.repository_id,
            requirement_id=collector.requirement_id,
            dispatch_sha256=collector.allocation.dispatch_sha256,
        ),
        request=containment.original_start.request,
        claim=containment.original_claim,
        task_intent_sha256=task_intent_sha256(task),
        task_revision=item.checkpoint_sequence,
        policy_sha256=policy.policy_sha256,
        worktree_path=str(tmp_path.resolve()),
        inventory_before=WorkspaceMutationInventory(files=()),
        started_at=containment.original_start.started_at,
    )
    ledger.put_capture_start(capture_start)
    marker = (
        collector.state
        / "continuations"
        / task.id
        / (f"capture-start-{capture_start.request.run_id}.json")
    )
    before = marker.read_bytes()

    recovered = collector._legacy_containment(task, item)

    assert recovered.original_start == containment.original_start
    assert recovered.original_claim == containment.original_claim
    assert "process_stop" not in recovered.to_wire()
    assert marker.read_bytes() == before
    assert (
        ledger.capture_start(capture_start.request.run_id).start_sha256
        == capture_start.start_sha256
    )
    (proof,) = collector._invocations(task, (item,), (), (), legacy=recovered)
    assert proof.outcome_sha256 is None and proof.interruption_receipt_sha256 is None


@pytest.mark.parametrize(
    "field",
    [
        "scope",
        "claim",
        "request",
        "task_intent_sha256",
        "task_revision",
        "policy_sha256",
        "worktree_path",
    ],
)
def test_start_only_capture_must_bind_current_legacy_facts(tmp_path: Path, field: str) -> None:
    collector, task, item, containment = legacy_fixture(tmp_path)
    continuation_parent = collector.state / "continuations"
    continuation_parent.mkdir(parents=True, mode=0o700)
    ledger = FileContinuationStore.initialize(continuation_parent / task.id, task_id=task.id)
    policy = task.interruption_continuation_policy
    assert policy is not None
    scope = ContinuationScope(
        team_id=collector.scope.team_id,
        project_id=collector.scope.project_id,
        repository_id=collector.scope.repository_id,
        requirement_id=collector.requirement_id,
        dispatch_sha256=collector.allocation.dispatch_sha256,
    )
    values: dict[str, object] = {
        "scope": scope,
        "request": containment.original_start.request,
        "claim": containment.original_claim,
        "task_intent_sha256": task_intent_sha256(task),
        "task_revision": item.checkpoint_sequence,
        "policy_sha256": policy.policy_sha256,
        "worktree_path": str(tmp_path.resolve()),
        "inventory_before": WorkspaceMutationInventory(files=()),
        "started_at": containment.original_start.started_at,
    }
    if field == "scope":
        values[field] = scope.model_copy(update={"requirement_id": "delivery_other"})
    elif field == "claim":
        values[field] = containment.original_claim.model_copy(
            update={
                "work_item": containment.original_claim.work_item.model_copy(
                    update={"id": "work_other"}
                )
            }
        )
    elif field == "request":
        values[field] = containment.original_start.request.model_copy(
            update={"source_revision": "f" * 40}
        )
    elif field in {"task_intent_sha256", "policy_sha256"}:
        values[field] = "f" * 64
    elif field == "worktree_path":
        values[field] = str(tmp_path.resolve() / "other")
    else:
        values[field] = item.checkpoint_sequence + 1
    capture_start = ExecutionCaptureStart.create(**values)
    ledger.put_capture_start(capture_start)

    with pytest.raises(ValueError, match="启动现场记录与当前需求事实不一致"):
        collector._legacy_containment(task, item)


def test_local_operator_prerequisite_can_use_the_existing_boot_without_faking_old_stop(
    tmp_path: Path,
) -> None:
    _, _, _, original = legacy_fixture(tmp_path)
    boot = BOOT.model_copy(update={"booted_at": STARTED - timedelta(days=1)})
    survey = LegacyLocalExecutionSurvey.create(
        worktree_path=str(tmp_path.resolve()),
        machine_sha256=boot.machine_sha256,
        boot_session_sha256=boot.boot_session_sha256,
        account_sha256="c" * 64,
        observed_at=STARTED + timedelta(days=1),
        scanner_version="local-execution-v1",
        blockers=(),
    )
    value = LegacyExecutionContainment.create(
        **original.model_dump(mode="python", exclude={"boot", "containment_sha256"}),
        boot=boot,
        method="operator_confirmed_local_stop",
        local_execution_survey=survey,
    )
    value.validate_integrity()
    assert value.method == "operator_confirmed_local_stop"
    assert value.original_start == original.original_start
    assert "process_stop" not in value.to_wire()
    assert "outcome" not in value.to_wire()


@pytest.mark.parametrize("drift", ["missing", "machine", "boot", "observed_before", "digest"])
def test_local_operator_prerequisite_rejects_missing_or_drifted_current_survey(
    tmp_path: Path, drift: str
) -> None:
    _, _, _, original = legacy_fixture(tmp_path)
    values: dict[str, object] = {
        "worktree_path": str(tmp_path.resolve()),
        "machine_sha256": BOOT.machine_sha256,
        "boot_session_sha256": BOOT.boot_session_sha256,
        "account_sha256": "c" * 64,
        "observed_at": STARTED + timedelta(days=1),
        "scanner_version": "local-execution-v1",
        "blockers": (),
    }
    if drift in {"machine", "boot"}:
        values["machine_sha256" if drift == "machine" else "boot_session_sha256"] = "d" * 64
    elif drift == "observed_before":
        values["observed_at"] = STARTED - timedelta(seconds=1)
    survey = LegacyLocalExecutionSurvey.create(**values)
    if drift == "digest":
        survey = survey.model_copy(update={"survey_sha256": "e" * 64})
    with pytest.raises(ValueError):
        LegacyExecutionContainment.create(
            **original.model_dump(mode="python", exclude={"containment_sha256"}),
            method="operator_confirmed_local_stop",
            local_execution_survey=None if drift == "missing" else survey,
        )


def test_os_reboot_default_keeps_exact_old_wire_digest(tmp_path: Path) -> None:
    _, _, _, original = legacy_fixture(tmp_path)
    wire = original.to_wire()
    assert "method" not in wire and "local_execution_survey" not in wire
    assert original.containment_sha256 == digest(
        original.model_dump(mode="json", exclude={"containment_sha256"})
    )
    assert LegacyExecutionContainment.model_validate(wire) == original


@pytest.mark.parametrize("error_type", [ValueError, OSError, SubprocessError])
@pytest.mark.parametrize("failure_read", [0, 1, 2, 3])
def test_os_observation_failure_preserves_initial_and_sealed_recovery_scene(
    tmp_path: Path, error_type: type[Exception], failure_read: int
) -> None:
    collector, task, item, containment = legacy_fixture(tmp_path)
    # Zero represents preparation before any observation is sealed. Later
    # reads exercise both preflight and final rechecks of the same sealed plan.
    if failure_read == 0:
        collector._sealed_legacy_observation = None
    else:
        collector.bind_legacy_observation(containment)
    original_sealed = collector._sealed_legacy_observation
    draft = collector.state / "preserved-draft.txt"
    draft.write_bytes(b"complete retained progress\nno destructive fallback\n")
    before = {path: path.read_bytes() for path in collector.state.rglob("*") if path.is_file()}
    original_task, original_item = task.to_wire(), item.to_wire()

    class Observer:
        calls = 0

        def observe(self) -> LocalBootObservation:
            self.calls += 1
            if self.calls == max(1, failure_read):
                raise error_type("private OS query payload must not be published")
            return BOOT

    observer = Observer()
    collector.observer = observer
    with pytest.raises(LegacyRescuePrerequisiteError) as failure:
        collector._legacy_containment(task, item)
    assert failure.value.code == "LEGACY_LOCAL_OBSERVATION_UNAVAILABLE"
    assert failure.value.safe_message == (
        "平台暂时无法读取可靠的本机身份和启动记录，不能准备旧执行恢复。"  # noqa: RUF001
    )
    assert failure.value.next_action == (
        "请让平台维护者检查当前系统的只读查询能力和权限，修复后重新检查恢复前提；"  # noqa: RUF001
        "不要清空工作区。"
    )
    assert "private OS query payload" not in str(failure.value)
    assert "整机重启" not in failure.value.next_action
    assert "整台电脑" not in failure.value.next_action
    assert observer.calls == max(1, failure_read)
    assert collector._sealed_legacy_observation == original_sealed
    assert task.to_wire() == original_task and item.to_wire() == original_item
    assert before == {
        path: path.read_bytes() for path in collector.state.rglob("*") if path.is_file()
    }
    assert draft.read_bytes() == b"complete retained progress\nno destructive fallback\n"
    assert not (collector.state / "invocations" / "invocation-outcomes").exists()
    assert "process_stop" not in containment.to_wire()
    assert "outcome" not in containment.to_wire()
