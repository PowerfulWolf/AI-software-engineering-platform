"""Independent verifiers use released reservations, never synthetic Task records."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.git.ports import WorktreeSpec
from ai_software_engineer.git.worktree import GitWorktreeManager
from ai_software_engineer.manager.dispatch import VerificationReservation
from ai_software_engineer.multi_directory.deletion import (
    ProductionRequirementDeletionGuard,
    RequirementDeletionRejected,
)
from ai_software_engineer.multi_directory.models import JointCheckpoint
from ai_software_engineer.multi_directory.service import JointDeliveryService
from ai_software_engineer.recovery.models import RecoveryScope
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationInputs,
    CandidateVerificationPlan,
)
from tests.manager.test_dispatch_authority import _durable_facts
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_requirement_deletion import _delivery
from tests.manager.test_requirement_resource_release import _initialize
from tests.orchestration.test_runner import _definitions


def _reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[
    JointDeliveryService,
    JointCheckpoint,
    Path,
    ProductionRequirementDeletionGuard,
    CandidateVerificationPlan,
    VerificationReservation,
    dict[str, str | None],
]:
    service, checkpoint, sidecar, _, _ = _delivery(tmp_path, monkeypatch)
    child = checkpoint.children[0].checkpoint
    assert child.task_id is not None
    facts = tmp_path / "facts"
    facts.mkdir()
    _, _, record, _, _ = _durable_facts(facts)
    scope = RecoveryScope(
        team_id=checkpoint.team_id,
        repository_id=child.repository_id,
        delivery_id=child.delivery_id,
        repository_root=child.repository_root,
    )
    inputs = CandidateVerificationInputs(
        task_id=child.task_id,
        task_revision=1,
        task_sha256="1" * 64,
        plan_id="art_plan_001",
        plan_sha256="2" * 64,
        implementation_id="art_impl_001",
        implementation_sha256="3" * 64,
        candidate_revision="a" * 40,
        prior_run_ids=(),
    )
    plan = CandidateVerificationPlan.create(
        scope=scope,
        inputs=inputs,
        execution_task_id="task_verify_release",
        native_checkpoint_sha256=child.checkpoint_sha256,
        dispatch_sha256="4" * 64,
        approved_stage_chain_sha256="5" * 64,
        current_policy_sha256="6" * 64,
        parent_delivery_id=checkpoint.delivery_id,
        parent_checkpoint_sha256=checkpoint.checkpoint_sha256,
        definitions=tuple(_definitions().values()),
        created_at=checkpoint.submitted_at,
    )
    store = FileRecoveryStore.initialize(
        sidecar / "state" / ("candidate-verification-" + child.delivery_id), scope=scope
    )
    store.put_verification_plan(plan)
    phases = []
    for index, phase in enumerate(record.phases[1:]):
        assignment_id = f"assignment_verifier_{index}"
        lease_id = f"lease_verifier_{index}"
        phases.append(
            phase.model_copy(
                update={
                    "assignment": phase.assignment.model_copy(
                        update={
                            "id": assignment_id,
                            "lease_id": lease_id,
                            "task_id": plan.execution_task_id,
                            "repository_id": child.repository_id,
                            "repository_scopes": (child.repository_root,),
                        }
                    ),
                    "lease": phase.lease.model_copy(
                        update={
                            "id": lease_id,
                            "assignment_id": assignment_id,
                            "task_id": plan.execution_task_id,
                        }
                    ),
                }
            )
        )
    reservation = VerificationReservation(
        plan_sha256=plan.plan_sha256,
        repository_id=child.repository_id,
        source_task_id=child.task_id,
        task_id=plan.execution_task_id,
        workforce_snapshot_sha256="7" * 64,
        phases=tuple(phases),
        committed_at=checkpoint.submitted_at,
    )
    row = {
        "plan_sha256": plan.plan_sha256,
        "payload_json": reservation.model_dump_json(),
        "completion_sha256": None,
        "abandonment_sha256": "8" * 64,
    }
    guard = service.deletion_guard
    assert isinstance(guard, ProductionRequirementDeletionGuard)
    return service, checkpoint, sidecar, guard, plan, reservation, row


def test_released_verifier_has_exact_resource_owner_without_tasks_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, checkpoint, sidecar, guard, plan, _, row = _reservation(tmp_path, monkeypatch)
    targets = guard._targets(checkpoint)
    resources = guard._validated_verification_resources(checkpoint, targets, [row])
    assert resources == {plan.execution_task_id: (sidecar, plan.scope.repository_root)}
    revision = _initialize(Path(plan.scope.repository_root))
    manager = GitWorktreeManager(
        plan.scope.repository_root,
        Path(service.team.manifest.platform_root) / "worktrees" / plan.scope.repository_id,
    )
    refs = tuple(
        manager.create(
            WorktreeSpec(
                task_id=plan.execution_task_id, role=role, attempt=1, source_revision=revision
            )
        )
        for role in (AgentRole.QA, AgentRole.REVIEWER)
    )
    monkeypatch.setattr(guard, "_read_tasks", lambda _: {})
    guard._release_worktrees(checkpoint, targets, verification=resources)
    assert all(not ref.path.exists() for ref in refs)
    # No SQL Task snapshot was invented for the verifier execution identity.
    assert plan.execution_task_id not in targets


@pytest.mark.parametrize("fault", ["running", "both", "sha", "owner", "source", "path"])
def test_verifier_release_requires_complete_exact_stopped_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    _, checkpoint, _, guard, plan, reservation, row = _reservation(tmp_path, monkeypatch)
    targets = guard._targets(checkpoint)
    if fault == "running":
        row["abandonment_sha256"] = None
    if fault == "both":
        row["completion_sha256"] = "9" * 64
    if fault == "sha":
        row["abandonment_sha256"] = "invalid"
    if fault == "owner":
        reservation = reservation.model_copy(update={"repository_id": "repository_other"})
        row["payload_json"] = reservation.model_dump_json()
    if fault == "source":
        targets = {plan.inputs.task_id: (next(iter(targets.values()))[0], "/foreign")}
    if fault == "path":
        row["plan_sha256"] = "a" * 64
        reservation = reservation.model_copy(update={"plan_sha256": "a" * 64})
        row["payload_json"] = reservation.model_dump_json()
    with pytest.raises((RequirementDeletionRejected, ValueError)):
        guard._validated_verification_resources(checkpoint, targets, [row])


@pytest.mark.mysql
def test_verifier_admission_fence_stays_held_through_parent_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mysql_dsn: str
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import closing
    from threading import Event

    from ai_software_engineer.store.mysql_repository import open_mysql_connection

    service, checkpoint, _, _, _ = _delivery(tmp_path, monkeypatch, dsn=mysql_dsn)
    guard = service.deletion_guard
    assert isinstance(guard, ProductionRequirementDeletionGuard)
    started, acquired = Event(), Event()

    def competing_admission() -> None:
        with closing(open_mysql_connection(mysql_dsn)) as conn:
            conn.begin()
            with conn.cursor() as cursor:
                started.set()
                cursor.execute("SELECT id FROM dispatch_authority_lock WHERE id=1 FOR UPDATE")
                acquired.set()
            conn.rollback()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with guard._verification_resources(checkpoint, {}) as resources:
            assert resources == {}
            future = pool.submit(competing_admission)
            assert started.wait(2)
            assert not acquired.wait(0.15)
            # Parent journal publication occurs inside the same guard yield.
            closed = service._close_checkpoint(checkpoint).checkpoint
            assert closed.stage.value == "CLOSED"
            assert not acquired.is_set()
        future.result(timeout=3)
    assert acquired.is_set()
