"""Current queue ownership, not a historical gap file, admits a recovery wait."""

from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict, cast
from unittest.mock import MagicMock

import pytest

from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import AgentRole, TaskStatus, TeamRole, WorkItemStatus
from ai_software_engineer.knowledge.gaps import KnowledgeGap
from ai_software_engineer.knowledge.models import (
    KnowledgeRunBinding,
    KnowledgeRunManifest,
    KnowledgeSnapshot,
    digest,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.dispatch import RecoveryDispatchRecord
from ai_software_engineer.orchestration import FileRunContextBuilder
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.recovery.knowledge_wait import pending_recovery_knowledge_wait
from ai_software_engineer.recovery.models import RecoveryPlan, RecoveryRejected
from ai_software_engineer.work_queue.execution_store import (
    QueuedRoleStep,
    RoleQueueAdmission,
    record_digest,
)
from tests.domain.factories import make_agent, make_task
from tests.knowledge.test_queue import route
from tests.work_queue.test_dispatcher import item


class WaitArguments(TypedDict):
    dsn: str
    sidecar: Path
    project_id: str
    plan: RecoveryPlan
    dispatch: RecoveryDispatchRecord


def setup_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str = ""
) -> tuple[WaitArguments, KnowledgeGap, MagicMock, MagicMock]:
    project = tmp_path / "project"
    project.mkdir()
    task = make_task().model_copy(
        update={
            "repository": str(project),
            "base_ref": "a" * 40,
            "status": TaskStatus.IMPLEMENTING,
            "attempts": 2,
        }
    )
    context = FileRunContextBuilder(project).build(
        task,
        make_agent(),
        attempt=1 if fault == "context" else 2,
    )
    FileContextStore(tmp_path / "contexts").put(context)
    binding = KnowledgeRunBinding(
        run_id="run_knowledge_wait_test",
        task_id=task.id,
        role=TeamRole.CODER,
        team_id="team_knowledge",
        project_id="project_knowledge",
        requirement_id="requirement_knowledge",
        repository_ids=("repository_platform_001",),
        source_revision=task.base_ref,
        context_manifest_id=context.context_id,
        snapshot_sha256="a" * 64,
    )
    if fault in {"project", "role", "revision"}:
        field, value = {
            "project": ("project_id", "project_foreign"),
            "role": ("role", TeamRole.QA),
            "revision": ("source_revision", "b" * 40),
        }[fault]
        binding = binding.model_copy(update={field: value})
    snapshot = KnowledgeSnapshot.create(
        team_id=binding.team_id,
        project_id=binding.project_id,
        requirement_id=binding.requirement_id,
        repository_ids=binding.repository_ids,
        documents=(),
    )
    binding = binding.model_copy(update={"snapshot_sha256": snapshot.snapshot_sha256})
    records = KnowledgeRecordStore(tmp_path / "knowledge/runs")
    routed = route(records, binding)
    gap = records.get("gaps", routed.gap_id, KnowledgeGap)
    manifest = records.get("manifests", gap.manifest_sha256, KnowledgeRunManifest)
    if fault == "manifest_key":
        alias = "f" * 64
        records.put("manifests", alias, manifest)
        gap = gap.model_copy(update={"manifest_sha256": alias})
        gap = gap.model_copy(
            update={"gap_id": digest(gap.model_dump(mode="json", exclude={"gap_id"}))}
        )
        records.put("gaps", gap.gap_id, gap)
        routed = routed.model_copy(update={"gap_id": gap.gap_id})
        routed = routed.model_copy(
            update={
                "routing_sha256": digest(routed.model_dump(mode="json", exclude={"routing_sha256"}))
            }
        )
        records.put("gap-routes", gap.gap_id, routed)
    gap_key = gap.gap_id
    if fault == "gap_key":
        gap_key = "e" * 64
        records.put("gaps", gap_key, gap)
        records.put("gap-routes", gap_key, routed)
    work = item(
        task_id=task.id,
        attempt=2,
        checkpoint_sequence=4,
        status=WorkItemStatus.WAITING_HUMAN,
        wait_reason=f"KNOWLEDGE_GAP:{gap_key}:{routed.routing_sha256}",
    )
    if fault in {"closed", "running"}:
        work = work.model_copy(
            update={
                "status": WorkItemStatus.CLOSED if fault == "closed" else WorkItemStatus.RUNNING,
                "wait_reason": None,
            }
        )
    step = QueuedRoleStep(
        work_item=work,
        allocation_sha256="b" * 64,
        boundary=RoleRunBoundary(
            task.id, AgentRole.CODER, 2, 4, "c" * 40 if fault == "step_revision" else task.base_ref
        ),
    )
    if fault == "allocation":
        step = step.model_copy(update={"allocation_sha256": "c" * 64})
    admission = RoleQueueAdmission(
        task_id=task.id,
        repository_id=work.repository_id,
        allocation_sha256="b" * 64,
        legacy_artifacts=(),
    )

    def row(value: RoleQueueAdmission | QueuedRoleStep) -> dict[str, str]:
        return {
            "id": task.id if isinstance(value, RoleQueueAdmission) else work.id,
            "task_id": task.id,
            "payload_json": value.model_dump_json(),
            "sha256": record_digest(value),
        }

    queue_row = {
        "id": work.id,
        "task_id": task.id,
        "status": work.status.value,
        "payload_json": work.model_dump_json(),
    }
    if fault.startswith("row_"):
        key = fault.removeprefix("row_")
        queue_row[key] = {"id": "work_foreign", "task_id": "task_foreign", "status": "CLOSED"}[key]
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchone.side_effect = [
        {"payload_json": task.model_dump_json(), "revision": 4, "status": task.status.value},
        row(admission),
        row(step),
    ]
    cursor.fetchall.side_effect = [
        [queue_row],
        [{"state": "ACTIVE" if fault == "claim" else "RELEASED"}],
    ]
    connection = MagicMock()
    connection.cursor.return_value = cursor
    monkeypatch.setattr(
        "ai_software_engineer.recovery.knowledge_wait.open_mysql_connection", lambda _: connection
    )
    dispatch = SimpleNamespace(
        task=task, repository_id=work.repository_id, dispatch_sha256="b" * 64
    )
    plan = SimpleNamespace(
        new_task_id=task.id,
        source=SimpleNamespace(
            scope=SimpleNamespace(team_id=binding.team_id),
            parent_delivery_id=binding.requirement_id,
        ),
    )
    # This read-side unit fixture supplies only the immutable plan/dispatch fields
    # consumed by the reader; native tests validate complete approved records.
    arguments = WaitArguments(
        dsn="unused",
        sidecar=tmp_path,
        project_id="project_knowledge",
        plan=cast(RecoveryPlan, plan),
        dispatch=cast(RecoveryDispatchRecord, dispatch),
    )
    return arguments, gap, connection, cursor


def test_current_coder_wait_reads_exact_sealed_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arguments, gap, connection, cursor = setup_wait(tmp_path, monkeypatch)
    assert pending_recovery_knowledge_wait(**arguments) == gap
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()
    assert all(
        call.args[0].startswith(("SELECT", "START TRANSACTION"))
        for call in cursor.execute.call_args_list
    )


@pytest.mark.parametrize("fault", ["closed", "running"])
def test_historical_gap_is_not_a_current_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    arguments, _, connection, cursor = setup_wait(tmp_path, monkeypatch, fault)
    assert pending_recovery_knowledge_wait(**arguments) is None
    assert cursor.fetchall.call_count == 1
    assert cursor.fetchone.call_count == 1
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()


@pytest.mark.parametrize(
    "fault",
    [
        "row_id",
        "row_task_id",
        "row_status",
        "gap_key",
        "manifest_key",
        "project",
        "role",
        "revision",
        "context",
        "step_revision",
        "allocation",
        "claim",
    ],
)
def test_changed_wait_proof_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    arguments, _, connection, _ = setup_wait(tmp_path, monkeypatch, fault)
    with pytest.raises(RecoveryRejected):
        pending_recovery_knowledge_wait(**arguments)
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()
