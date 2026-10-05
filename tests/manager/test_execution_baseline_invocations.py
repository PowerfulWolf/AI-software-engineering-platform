"""A checkpoint's real claim and exact historical source prove its own invocation."""

from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentRole, Artifact, Task, WorkItemStatus
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.workforce import RoleAssignment
from ai_software_engineer.git import GitWorktreeManager, WorktreeNotFound, WorktreeSpec
from ai_software_engineer.git.ports import WorktreeRef
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_models import (
    BaselineExecutionFacts,
    BaselineExecutionReservation,
)
from ai_software_engineer.manager.baseline_production import ProductionBaselineFactCollector
from ai_software_engineer.manager.delivery_preflight import (
    DeliveryPreflightCheckpoint,
    DeliveryPreflightReceipt,
    DeliveryPreflightScope,
)
from ai_software_engineer.manager.dispatch import DispatchCommitRecord
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, QueuedRoleStep
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.worker import AcceptedArtifactStore
from tests.domain.factories import NOW, make_task
from tests.manager.test_execution_baseline_reservation import reservation_fixture
from tests.orchestration.test_native_continuation import claim as native_claim
from tests.work_queue.test_mysql_queue import queued_item


def _allocation(task: Task, sha256: str) -> DispatchCommitRecord:
    # These focused collector regressions only read the already trusted allocation
    # identity/digest. They do not exercise the public dispatch validation gate.
    return DispatchCommitRecord.model_construct(task=task, task_id=task.id, dispatch_sha256=sha256)


def _claim(item: QueuedWorkItem, lease_id: str) -> QueueClaim:
    template = native_claim(make_task().model_copy(update={"id": item.task_id}), item.attempt)
    assignment = template.assignment.model_copy(
        update={"repository_id": item.repository_id, "lease_id": lease_id, "role": item.role}
    )
    return QueueClaim(
        work_item=item.model_copy(update={"status": WorkItemStatus.LEASED}),
        assignment=assignment,
        lease=template.lease.model_copy(update={"id": lease_id}),
        model_selection=template.model_selection,
        worker_id=template.worker_id,
        claimed_at=template.claimed_at,
    )


def test_assignment_on_another_checkpoint_cannot_make_current_item_claimed(tmp_path: Path) -> None:
    item = queued_item(checkpoint_sequence=12)
    task = make_task().model_copy(update={"id": item.task_id})
    original_assignment = RoleAssignment(
        id="assignment_previous_checkpoint",
        repository_id=item.repository_id,
        task_id=item.task_id,
        agent_id="agent_previous_coder",
        role=AgentRole.CODER,
        attempt=item.attempt,
        lease_id="lease_previous_checkpoint",
        assigned_at=NOW,
    )
    step = QueuedRoleStep(
        work_item=item,
        boundary=RoleRunBoundary(
            task.id, AgentRole.CODER, item.attempt, item.checkpoint_sequence, "a" * 40
        ),
        allocation_sha256="b" * 64,
    )
    asked: list[str] = []

    class Queue(MySqlRoleQueue):
        def __init__(self) -> None:
            pass

        def step(self, identity: str) -> QueuedRoleStep:
            assert identity == item.id
            return step

        def claims_for_work_item(self, identity: str) -> tuple[QueueClaim, ...]:
            asked.append(identity)
            return ()

    collector = ProductionBaselineFactCollector.__new__(ProductionBaselineFactCollector)
    collector.state = tmp_path
    collector.allocation = _allocation(task, "b" * 64)
    collector.queue = Queue()
    (proof,) = collector._invocations(task, (item,), (), (original_assignment,))
    assert asked == [item.id]
    assert proof.proof_kind == "unclaimed"
    assert proof.start_sha256 is None and proof.preflight_checkpoint_sha256 is None
    assert proof.step_sha256 == digest(step.to_wire())


def test_original_invocation_uses_its_exact_step_instead_of_latest_baseline_overlay(
    tmp_path: Path,
) -> None:
    collector, task, item, receipt = reservation_fixture(tmp_path)
    task = task.model_copy(update={"id": item.task_id})
    historical = QueuedRoleStep(
        work_item=item,
        boundary=RoleRunBoundary(
            task.id,
            AgentRole.CODER,
            item.attempt,
            item.checkpoint_sequence,
            receipt.request.source_revision,
        ),
        allocation_sha256="b" * 64,
    )
    looked_up: list[tuple[str, str | None]] = []

    original = _claim(item, receipt.claim_lease_id)

    class Queue(MySqlRoleQueue):
        def __init__(self) -> None:
            pass

        def step(self, identity: str) -> QueuedRoleStep:
            raise AssertionError("a current source overlay cannot reinterpret a past invocation")

        def step_for_invocation(self, identity: str, baseline: str | None) -> QueuedRoleStep:
            looked_up.append((identity, baseline))
            return historical

        def original_claim(self, identity: str) -> QueueClaim:
            assert identity == receipt.claim_lease_id
            return original

        def claims_for_work_item(self, identity: str) -> tuple[QueueClaim, ...]:
            assert identity == item.id
            return (original,)

    collector.allocation = _allocation(task, "b" * 64)
    collector.queue = Queue()
    (proof,) = collector._invocations(task, (item,), (receipt,), ())
    assert looked_up == [(item.id, receipt.request.execution_baseline_sha256)]
    assert proof.proof_kind == "owned_process_stopped"
    assert proof.interruption_receipt_sha256 == receipt.receipt_sha256
    assert proof.step_sha256 == digest(historical.to_wire())


@pytest.mark.parametrize("problem", [None, "missing_marker", "ready_without_start", "wrong_source"])
def test_every_repeated_preflight_claim_uses_its_historical_overlay_and_stop(
    tmp_path: Path,
    problem: str | None,
) -> None:
    item = queued_item(checkpoint_sequence=12)
    task = make_task().model_copy(update={"id": item.task_id})
    records = KnowledgeRecordStore(tmp_path / "delivery-preflight")
    scope = DeliveryPreflightScope(
        team_id="team_baseline",
        project_id="project_baseline",
        repository_id=item.repository_id,
        requirement_id="delivery_baseline",
    )
    claims = tuple(
        _claim(item.model_copy(update={"dispatch_sequence": ordinal}), f"lease_preflight_{ordinal}")
        for ordinal in range(2)
    )
    steps = tuple(
        QueuedRoleStep(
            work_item=claim.work_item,
            boundary=RoleRunBoundary(
                task.id,
                AgentRole.CODER,
                item.attempt,
                item.checkpoint_sequence,
                ("a" if ordinal == 0 else "b") * 40,
            ),
            allocation_sha256="c" * 64,
        )
        for ordinal, claim in enumerate(claims)
    )
    markers: list[DeliveryPreflightCheckpoint] = []
    for ordinal, claim in enumerate(claims):
        if problem == "missing_marker" and ordinal == 1:
            continue
        receipt = DeliveryPreflightReceipt(
            scope=scope,
            task_id=task.id,
            source_revision=steps[ordinal].boundary.source_revision,
            plan_sha256="d" * 64,
            frozen_policy_sha256="e" * 64,
            requirements_sha256="f" * 64,
            observations=(),
            status="READY"
            if problem == "ready_without_start" and ordinal == 1
            else "WAIT_ENGINEERING",
            checked_at=NOW,
            receipt_sha256="0" * 64,
        )
        receipt = receipt.model_copy(
            update={
                "receipt_sha256": digest(
                    receipt.model_dump(mode="json", exclude={"receipt_sha256"})
                ),
            }
        )
        marker = DeliveryPreflightCheckpoint(
            work_item_id=item.id,
            lease_id=claim.lease.id,
            task_id=task.id,
            task_snapshot_sha256=digest(task.to_wire()),
            checkpoint_sequence=item.checkpoint_sequence,
            source_revision="f" * 40
            if problem == "wrong_source" and ordinal == 0
            else receipt.source_revision,
            receipt_sha256=receipt.receipt_sha256,
            checked_at=NOW,
            checkpoint_sha256="0" * 64,
        )
        marker = marker.model_copy(
            update={
                "checkpoint_sha256": digest(
                    marker.model_dump(mode="json", exclude={"checkpoint_sha256"})
                ),
            }
        )
        records.put("preflight-receipts", receipt.receipt_sha256, receipt)
        records.put("preflight-checkpoints", marker.checkpoint_sha256, marker)
        markers.append(marker)
    looked_up: list[str] = []

    class Queue(MySqlRoleQueue):
        def __init__(self) -> None:
            pass

        def claims_for_work_item(self, identity: str) -> tuple[QueueClaim, ...]:
            assert identity == item.id
            return claims

        def step_for_claim(self, claim: QueueClaim) -> QueuedRoleStep:
            looked_up.append(claim.lease.id)
            return steps[claims.index(claim)]

        def step(self, identity: str) -> QueuedRoleStep:
            assert identity == item.id
            return steps[-1]

    collector = ProductionBaselineFactCollector.__new__(ProductionBaselineFactCollector)
    collector.state = tmp_path
    collector.queue = Queue()
    collector.scope = EngineeringScope(
        repository_id=scope.repository_id,
        team_id=scope.team_id,
        project_id=scope.project_id,
        repository_root="/workspace/example",
    )
    collector.requirement_id = scope.requirement_id
    collector.allocation = _allocation(task, "c" * 64)
    if problem is not None:
        with pytest.raises(ValueError, match=r"历史 claim|原 claim"):
            collector._invocations(task, (item,), (), ())
        return
    (proof,) = collector._invocations(task, (item,), (), ())
    assert proof.proof_kind == "claimed_preflight"
    assert proof.preflight_checkpoint_sha256 is None
    assert set(proof.preflight_checkpoint_sha256s) == {m.checkpoint_sha256 for m in markers}
    assert set(looked_up) == {claim.lease.id for claim in claims}
    assert proof.start_sha256 is None


@pytest.mark.parametrize("started", [False, True])
def test_missing_checkout_can_only_be_the_initial_uninvoked_preflight_checkout(
    tmp_path: Path,
    started: bool,
) -> None:
    collector, task, _, receipt = reservation_fixture(tmp_path)
    task = task.model_copy(
        update={
            "id": receipt.request.task_id,
            "base_ref": receipt.request.source_revision,
            "branch_name": "ai/feature/original-preflight",
        }
    )
    if not started:
        collector.state = tmp_path / "pristine-state"
    collector._scope_held = True
    collector.allocation = _allocation(task, "a" * 64)

    class EmptyArtifacts(AcceptedArtifactStore):
        def __init__(self) -> None:
            pass

        def list_for_task(self, identity: str) -> tuple[Artifact, ...]:
            assert identity == task.id
            return ()

    collector.artifacts = EmptyArtifacts()
    collector.inputs = StoredCoderExecutionInputResolver(None)
    created: list[WorktreeSpec] = []

    class Git(GitWorktreeManager):
        def __init__(self) -> None:
            pass

        def recover(self, spec: WorktreeSpec) -> WorktreeRef:
            raise WorktreeNotFound("no checkout")

        def create(self, spec: WorktreeSpec) -> WorktreeRef:
            created.append(spec)
            return WorktreeRef(
                task_id=spec.task_id,
                role=spec.role,
                attempt=spec.attempt,
                path=tmp_path / "coder-attempt-01",
                head_revision=spec.source_revision,
                branch=task.branch_name,
                detached=False,
            )

    collector.git = Git()
    facts = BaselineExecutionFacts.model_construct(
        task=task,
        continuation=BaselineExecutionReservation(
            current_attempt=1,
            next_execution_attempt=1,
            retry_cause="uninvoked",
        ),
    )
    if started:
        with pytest.raises(ValueError, match="已开始执行的 Coder 工作区缺失"):
            collector.source_worktree(facts)
        assert not created
    else:
        checkout = collector.source_worktree(facts)
        assert checkout.head_revision == task.base_ref
        assert checkout.branch == task.branch_name
        assert checkout.attempt == 1 and len(created) == 1
