"""Deleted delivery history is physically purged without breaking the public Team reader."""

from __future__ import annotations

import hashlib
from contextlib import closing
from datetime import UTC, datetime
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import TaskStatus
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    ReplyToProduct,
    StartProjectDelivery,
)
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
    ProjectDeliveryIntake,
)
from ai_software_engineer.manager.dispatch import VerificationReservation
from ai_software_engineer.manager.mysql_dispatch_authority import (
    MySqlDispatchAuthority,
    _decode_commit,
)
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.multi_directory.models import ChildDelivery, JointCheckpoint, JointStage
from ai_software_engineer.multi_directory.retirement import RequirementRetirementStore
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit
from ai_software_engineer.multi_directory.service import CreateRequirement, DeleteRequirement
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.planning.store import FileExecutionPlanStore
from ai_software_engineer.product.store import FileProductRecordStore
from ai_software_engineer.recovery.models import RecoveryScope
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationInputs,
    CandidateVerificationPlan,
)
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.team_view.models import TeamReadError, TeamSnapshot
from ai_software_engineer.team_view.reader import ProductionTeamReader
from ai_software_engineer.team_view.server import create_team_server
from ai_software_engineer.team_workspace import TeamWorkspace
from tests.e2e.test_joint_delivery import setup_host
from tests.manager.test_production_backend import _ScriptedClientFactory, _ScriptedDeliveryFactory
from tests.orchestration.test_runner import _definitions


def _completed(host: TeamHost, root: Path, name: str) -> ProjectDeliveryCheckpoint:
    service = host.project_entry()
    checkpoint = service.start(
        StartProjectDelivery(repository_root=str(root), requirement=name, title=name)
    ).checkpoint
    if checkpoint.stage == "WAITING_PRODUCT_REPLY":
        checkpoint = service.reply(
            ReplyToProduct(
                delivery_id=checkpoint.delivery_id,
                expected_checkpoint_sha256=checkpoint.checkpoint_sha256,
                message=name,
            )
        ).checkpoint
    checkpoint = service.approve(
        ApproveProductSpec(
            delivery_id=checkpoint.delivery_id,
            expected_checkpoint_sha256=checkpoint.checkpoint_sha256,
            approval_reference="human-deleted-verification-fixture",
        )
    ).checkpoint
    assert checkpoint.stage == "DONE"
    return checkpoint


def _reserve(dsn: str, checkpoint: ProjectDeliveryCheckpoint) -> VerificationReservation:
    with open_mysql_connection(dsn) as connection, connection.cursor(DictCursor) as cursor:
        cursor.execute("SELECT * FROM dispatch_commits WHERE task_id=%s", (checkpoint.task_id,))
        row = cursor.fetchone()
        assert row is not None
        dispatch = _decode_commit(row)
        suffix = hashlib.sha256(dispatch.task_id.encode()).hexdigest()[:16]
        task_id = f"task_verify_deleted_{suffix}"
        phases = []
        for index, phase in enumerate(dispatch.phases[1:]):
            assignment_id = f"assignment_verify_deleted_{suffix}_{index}"
            lease_id = f"lease_verify_deleted_{suffix}_{index}"
            phases.append(
                phase.model_copy(
                    update={
                        "assignment": phase.assignment.model_copy(
                            update={"id": assignment_id, "lease_id": lease_id, "task_id": task_id}
                        ),
                        "lease": phase.lease.model_copy(
                            update={
                                "id": lease_id,
                                "assignment_id": assignment_id,
                                "task_id": task_id,
                            }
                        ),
                    }
                )
            )
        reservation = VerificationReservation(
            plan_sha256=hashlib.sha256(task_id.encode()).hexdigest(),
            repository_id=dispatch.repository_id,
            source_task_id=dispatch.task_id,
            task_id=task_id,
            workforce_snapshot_sha256=dispatch.workforce_snapshot_sha256,
            phases=tuple(phases),
            committed_at=datetime.now(UTC),
        )
        cursor.execute(
            "INSERT INTO verification_reservations "
            "(plan_sha256,payload_json,completion_sha256) VALUES (%s,%s,NULL)",
            (reservation.plan_sha256, reservation.model_dump_json()),
        )
        connection.commit()
    return reservation


def _label_sha256(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode()).hexdigest()


def _finished_verification(
    dsn: str, sidecar: Path, parent: JointCheckpoint, child: ProjectDeliveryCheckpoint
) -> tuple[CandidateVerificationPlan, VerificationReservation]:
    """A sealed real plan plus a reservation released through the typed authority."""
    assert child.task_id is not None and child.task_revision is not None
    assert child.dispatch_commit_sha256 is not None
    with open_mysql_connection(dsn) as connection, connection.cursor(DictCursor) as cursor:
        cursor.execute("SELECT * FROM dispatch_commits WHERE task_id=%s", (child.task_id,))
        row = cursor.fetchone()
        assert row is not None
        dispatch = _decode_commit(row)
    assert dispatch.repository_id == child.repository_id
    suffix = hashlib.sha256(child.task_id.encode()).hexdigest()[:16]
    scope = RecoveryScope(
        team_id=parent.team_id,
        repository_id=child.repository_id,
        delivery_id=child.delivery_id,
        repository_root=child.repository_root,
    )
    plan = CandidateVerificationPlan.create(
        scope=scope,
        inputs=CandidateVerificationInputs(
            task_id=child.task_id,
            task_revision=child.task_revision,
            task_sha256=_label_sha256("task", child.task_id),
            plan_id=f"art_plan_deleted_{suffix}",
            plan_sha256=_label_sha256("plan", child.task_id),
            implementation_id=f"art_impl_deleted_{suffix}",
            implementation_sha256=_label_sha256("implementation", child.task_id),
            candidate_revision=hashlib.sha1(child.task_id.encode()).hexdigest(),
        ),
        execution_task_id=f"task_verify_deleted_{suffix}",
        native_checkpoint_sha256=child.checkpoint_sha256,
        dispatch_sha256=child.dispatch_commit_sha256,
        approved_stage_chain_sha256=_label_sha256("stages", child.task_id),
        current_policy_sha256=_label_sha256("policy", child.task_id),
        parent_delivery_id=parent.delivery_id,
        parent_checkpoint_sha256=parent.checkpoint_sha256,
        definitions=tuple(_definitions().values()),
        created_at=datetime.now(UTC),
    )
    FileRecoveryStore.initialize(
        sidecar / "state" / ("candidate-verification-" + child.delivery_id), scope=scope
    ).put_verification_plan(plan)
    phases = []
    for index, phase in enumerate(dispatch.phases[1:]):
        assignment_id = f"assignment_verify_deleted_{suffix}_{index}"
        lease_id = f"lease_verify_deleted_{suffix}_{index}"
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
        workforce_snapshot_sha256=dispatch.workforce_snapshot_sha256,
        phases=tuple(phases),
        committed_at=datetime.now(UTC),
    )
    with open_mysql_connection(dsn) as connection, connection.cursor(DictCursor) as cursor:
        cursor.execute(
            "INSERT INTO verification_reservations "
            "(plan_sha256,payload_json,completion_sha256,abandonment_sha256) "
            "VALUES (%s,%s,NULL,NULL)",
            (reservation.plan_sha256, reservation.model_dump_json()),
        )
        connection.commit()
    MySqlDispatchAuthority(
        dsn,
        request_revisions=FileProductRecordStore(sidecar / "state/product"),
        planner_records=FileExecutionPlanStore(sidecar / "state/planning"),
    ).abandon_verification(
        plan_sha256=plan.plan_sha256,
        abandonment_sha256=_label_sha256("abandoned", plan.plan_sha256),
    )
    return plan, reservation


def _reservation_row(dsn: str, plan_sha256: str) -> tuple[object, ...]:
    with open_mysql_connection(dsn) as connection, connection.cursor(DictCursor) as cursor:
        cursor.execute(
            "SELECT payload_json,completion_sha256,abandonment_sha256 "
            "FROM verification_reservations WHERE plan_sha256=%s",
            (plan_sha256,),
        )
        rows = cursor.fetchall()
    assert len(rows) == 1
    row = rows[0]
    return (row["payload_json"], row["completion_sha256"], row["abandonment_sha256"])


def _files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize("cross_repository", [False, True])
def test_retired_and_visible_deliveries_cannot_share_a_global_task_id(
    tmp_path: Path, cross_repository: bool
) -> None:
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        default_project_id="project_test",
        default_project_name="Read-only overlap",
        model_routes=(
            ProviderRouteConfig(
                provider="codex",
                model="gpt-6.1-sol",
                kind=ModelProviderKind.CODEX_CLI,
            ),
        ),
    )
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name
    )
    project = team.project_registry().register(project_id="project_test", name="Read-only overlap")
    root = tmp_path / "repository"
    root.mkdir()
    old_repository = project.repository_registry().register(root)
    visible_repository = old_repository
    if cross_repository:
        other_root = tmp_path / "other-repository"
        other_root.mkdir()
        visible_repository = project.repository_registry().register(other_root)
    now = datetime.now(UTC)
    checkpoints = []
    for identity, repository in (("retired", old_repository), ("visible", visible_repository)):
        store = FileProjectDeliveryCheckpointStore(repository.root / "state/project-deliveries")
        delivery_id = f"delivery_overlap_{identity}"
        store.put_intake(
            ProjectDeliveryIntake.create(
                delivery_id=delivery_id,
                repository_id=repository.repository_id,
                repository_root=str(repository.repository_root),
                title="Duplicate global Task identity",
                requirement="Corrupt identity must fail before any SQL read.",
                submitted_at=now,
            )
        )
        checkpoints.append(
            store.put(
                ProjectDeliveryCheckpoint.create(
                    delivery_id=delivery_id,
                    sequence=1,
                    repository_id=repository.repository_id,
                    repository_root=str(repository.repository_root),
                    preparation_sha256="a" * 64,
                    request_id=f"request_{identity}",
                    request_revision=1,
                    product_checkpoint_sha256="a" * 64,
                    product_spec_id=f"product_{identity}",
                    product_spec_sha256="a" * 64,
                    approval_id=f"approval_{identity}",
                    approval_sha256="a" * 64,
                    technical_design_id=f"design_{identity}",
                    technical_design_sha256="a" * 64,
                    execution_plan_id=f"plan_{identity}",
                    execution_plan_sha256="a" * 64,
                    planning_preview_id=f"preview_{identity}",
                    planning_preview_sha256="a" * 64,
                    dispatch_commit_id=f"dispatch_{identity}",
                    dispatch_commit_sha256="a" * 64,
                    task_id="task_duplicated_global_identity",
                    task_revision=1,
                    task_status=TaskStatus.BLOCKED,
                    stage=DeliveryStage.BLOCKED,
                    stage_attempts=DeliveryStageAttempts(delivering=1),
                    next_action=DeliveryNextAction.REQUEST_HUMAN,
                    failure_code=DeliveryFailureCode.CHECKPOINT_DRIFT,
                    failure_summary="Duplicate fixture source.",
                    failed_stage=DeliveryStage.DELIVERING,
                    checkpointed_at=now,
                )
            )
        )
    unit_id = "unit_" + "a" * 16
    parent = JointCheckpoint.seal(
        {
            "delivery_id": "delivery_multi_" + "a" * 40,
            "team_id": team.manifest.team_id,
            "team_manifest_sha256": team.manifest.manifest_sha256,
            "project_id": project.manifest.project_id,
            "project_manifest_sha256": project.manifest.manifest_sha256,
            "sequence": 1,
            "stage": JointStage.BLOCKED,
            "scope": DirectoryScope(
                units=(
                    DirectoryUnit(
                        id=unit_id,
                        root=str(root),
                        selected_paths=(".",),
                        base_revision="b" * 40,
                    ),
                )
            ),
            "title": "Retired overlap",
            "submitted_at": now,
            "children": (ChildDelivery(unit_id=unit_id, checkpoint=checkpoints[0]),),
            "next_action": "用户已删除旧需求。",
        }
    )
    JointJournal(project.requirements_root).append(parent, expected=None)
    RequirementRetirementStore(
        project.requirements_root,
        team_id=parent.team_id,
        team_manifest_sha256=parent.team_manifest_sha256,
        project_id=parent.project_id,
        project_manifest_sha256=parent.project_manifest_sha256,
    ).retire(parent, reason="deleted", retired_at=now)
    before = _files(Path(config.platform_root))
    with pytest.raises(TeamReadError) as rejected:
        ProductionTeamReader(config, {}).snapshot(project.manifest.project_id)
    assert isinstance(rejected.value.__cause__, ValueError)
    assert str(rejected.value.__cause__) == "ambiguous native Task ownership"
    assert _files(Path(config.platform_root)) == before


@pytest.mark.mysql
def test_public_team_read_after_delete_filters_all_history_and_its_verifications(
    tmp_path: Path,
) -> None:
    config, environment, _, roots = setup_host(tmp_path)
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=_ScriptedDeliveryFactory(),
    )
    old = _completed(host, roots[0], "Old deleted child")
    current = _completed(host, roots[0], "Current deleted child")
    kept = _completed(host, roots[0], "Unrelated kept child")
    dsn = config.require_mysql_dsn(environment)
    # The unrelated Requirement keeps an in-progress verifier reservation.
    kept_reservation = _reserve(dsn, kept)
    service = host.requirement_entry()
    parent = service.create(
        CreateRequirement(repository_roots=(str(roots[0]),), name="Deleted parent history")
    ).checkpoint
    unit = parent.scope.units[0]
    for child in (old, current):
        successor = JointCheckpoint.seal(
            {
                **parent.model_dump(mode="json", exclude={"checkpoint_sha256"}),
                "sequence": parent.sequence + 1,
                "previous_checkpoint_sha256": parent.checkpoint_sha256,
                "stage": JointStage.BLOCKED,
                "children": (ChildDelivery(unit_id=unit.id, checkpoint=child),),
                "next_action": "用户决定删除保留的旧需求。",
            }
        )
        parent = service.journal.append(successor, expected=parent.checkpoint_sha256)
    sidecar = next(
        repo.root
        for repo in service.project.repository_registry().discover()
        if repo.repository_id == current.repository_id
    ).resolve(strict=True)
    # Recovery stores walk every path component with O_NOFOLLOW from "/", so a sidecar
    # reached through a symlinked ancestor (e.g. macOS /tmp or /var) is rejected.
    # Use the canonical sidecar path and require its existing private state directory.
    assert (sidecar / "state").is_dir() and not (sidecar / "state").is_symlink()
    # Deleted children carry released verifications bound to the final parent checkpoint.
    finished = tuple(
        _finished_verification(dsn, sidecar, parent, child) for child in (old, current)
    )
    native_root = sidecar / "state/project-deliveries"
    kept_intake = native_root / "intakes" / (kept.delivery_id + ".json")
    kept_native_before = _files(native_root / kept.delivery_id)
    kept_intake_before = kept_intake.read_bytes()
    kept_row_before = _reservation_row(dsn, kept_reservation.plan_sha256)
    assert kept_native_before
    for child in (old, current):
        assert (native_root / child.delivery_id).is_dir()
        assert (sidecar / "state" / ("candidate-verification-" + child.delivery_id)).is_dir()
    service.delete_requirement(
        DeleteRequirement(
            delivery_id=parent.delivery_id,
            expected_checkpoint_sha256=parent.checkpoint_sha256,
            submitted_at=datetime.now(UTC),
        )
    )
    # Explicit deletion physically removes the deleted children's owned resources.
    for child in (old, current):
        assert not (native_root / child.delivery_id).exists()
        assert not (native_root / "intakes" / (child.delivery_id + ".json")).exists()
        assert not (sidecar / "state" / ("candidate-verification-" + child.delivery_id)).exists()
    with open_mysql_connection(dsn) as connection, connection.cursor(DictCursor) as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS remaining FROM verification_reservations "
            "WHERE plan_sha256 IN (%s,%s)",
            tuple(plan.plan_sha256 for plan, _ in finished),
        )
        counted = cursor.fetchone()
    assert counted is not None and counted["remaining"] == 0
    # The unrelated Requirement is untouched.
    assert _files(native_root / kept.delivery_id) == kept_native_before
    assert kept_intake.read_bytes() == kept_intake_before
    assert _reservation_row(dsn, kept_reservation.plan_sha256) == kept_row_before
    files_before = _files(Path(config.platform_root))
    reader = ProductionTeamReader(config, environment)
    with create_team_server(reader, port=0) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with closing(HTTPConnection("127.0.0.1", server.server_port, timeout=5)) as client:
                client.request("GET", f"/api/v1/team?project_id={parent.project_id}")
                response = client.getresponse()
                payload = response.read()
                assert response.status == 200, payload
            snapshot = TeamSnapshot.model_validate_json(payload)
            assert {request.id for request in snapshot.requests} == {kept.delivery_id}
            assert {task.task_id for task in snapshot.tasks} == {
                kept.task_id,
                kept_reservation.task_id,
            }
            assert snapshot.projects[0].requirement_count == 0
            hidden = {
                old.delivery_id,
                current.delivery_id,
                parent.delivery_id,
                *[f"verification_{plan.plan_sha256[:32]}" for plan, _ in finished],
            }
            assert all(
                not hidden.intersection(
                    (
                        *agent.assigned_delivery_ids,
                        *agent.current_stage_delivery_ids,
                        *agent.history_delivery_ids,
                    )
                )
                for agent in snapshot.agents
            )
            assert _files(Path(config.platform_root)) == files_before
            # A non-retired missing source is still corruption, even in this same repository.
            bad = kept_reservation.model_copy(
                update={"source_task_id": "task_missing_active_source"}
            )
            with open_mysql_connection(dsn) as connection, connection.cursor(DictCursor) as cursor:
                cursor.execute(
                    "UPDATE verification_reservations SET payload_json=%s WHERE plan_sha256=%s",
                    (bad.model_dump_json(), bad.plan_sha256),
                )
                connection.commit()
            with closing(HTTPConnection("127.0.0.1", server.server_port, timeout=5)) as client:
                client.request("GET", f"/api/v1/team?project_id={parent.project_id}")
                response = client.getresponse()
                assert response.status == 503
                assert b"source_task_id" not in response.read()
        finally:
            server.shutdown()
            thread.join(timeout=5)
