"""Retained candidates after a proved pre-provider knowledge failure, never lost edits."""

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from ai_software_engineer.agents import FileModelRouteAttemptStore
from ai_software_engineer.agents.fallback import RouteAttemptOutcome, model_route_root
from ai_software_engineer.artifacts import FileArtifactStore, artifact_digest
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import AgentRole, Task, TaskStatus
from ai_software_engineer.domain.artifact import (
    ImplementationReportArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
)
from ai_software_engineer.domain.enums import QaReportStatus, ReviewVerdict, TeamRole
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.knowledge.agents import KnowledgeConsultation, KnowledgeConsultationInput
from ai_software_engineer.knowledge.models import KnowledgeSnapshot
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.delivery_checkpoint import ProjectDeliveryCheckpoint
from ai_software_engineer.recovery.models import RecoveryRejected, canonical_bytes, digest
from ai_software_engineer.recovery.progress_source import CODER_KNOWLEDGE_FAILURE_REASONS
from ai_software_engineer.recovery.verification_snapshot import (
    CandidateRuntimeSnapshot,
    candidate_event,
)
from ai_software_engineer.redaction import redact_text
from ai_software_engineer.repository_workspace import RepositoryWorkspaceManifest
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.team_workspace import _read_regular, _reject_symlinks


def require_unchanged_pre_provider_candidate(
    config: ProductionConfig,
    environment: Mapping[str, str],
    sidecar: Path,
    checkpoint: ProjectDeliveryCheckpoint,
    runtime: CandidateRuntimeSnapshot,
    implementation: ImplementationReportArtifact,
) -> None:
    """A feedback transition alone cannot prove that a newer Coder executed."""
    task = runtime.task
    _, accepted = candidate_event(runtime.events)
    feedback, blocked = runtime.events[-2:]
    if (
        task.status is not TaskStatus.BLOCKED
        or blocked.reason not in CODER_KNOWLEDGE_FAILURE_REASONS
        or checkpoint.failure_summary != blocked.reason.split(": ", 1)[1]
        or blocked.attempt != task.attempts
        or blocked.attempt != feedback.attempt
        or feedback.attempt != accepted.attempt + 1
        or len(feedback.artifact_ids) != 1
        or feedback.artifact_ids[0] not in blocked.artifact_ids
        or accepted.artifact_ids != (implementation.artifact_id,)
        or implementation.artifact_id not in blocked.artifact_ids
        or implementation.producer.role is not AgentRole.CODER
    ):
        raise RecoveryRejected(
            "candidate has newer interrupted Coder work that must be recovered first"
        )
    report = FileArtifactStore(sidecar / "artifacts", read_only=True).get(feedback.artifact_ids[0])
    if (
        report.task_id != task.id
        or report.source_revision != implementation.content.commit_sha
        or report.supersedes is not None
        or not (
            (
                feedback.from_status is TaskStatus.QA
                and isinstance(report, QaReportArtifact)
                and report.content.status is QaReportStatus.FAIL
                and report.parent_artifact_ids == (implementation.artifact_id,)
            )
            or (
                feedback.from_status is TaskStatus.REVIEW
                and isinstance(report, ReviewReportArtifact)
                and report.content.verdict is ReviewVerdict.REJECT
                and report.parent_artifact_ids == runtime.events[-3].artifact_ids
            )
        )
    ):
        raise RecoveryRejected("retained candidate lost its sealed feedback report")
    _require_unfinished_coder_consultation(config, sidecar, runtime, report.artifact_id)
    root = model_route_root(sidecar)
    _reject_symlinks(root)
    routes = FileModelRouteAttemptStore(root, read_only=True)
    accepted_route = None
    for directory in root.iterdir():
        _reject_symlinks(directory)
        for path in directory.glob("*.json"):
            _read_regular(path, 8_000_000)
        for route in routes.list_for_run(directory.name):
            if route.task_id != task.id or route.role is not AgentRole.CODER:
                continue
            if route.result.attempt > accepted.attempt or route.completed_at > feedback.occurred_at:
                raise RecoveryRejected("retained candidate has a later Coder provider execution")
            if route.run_id == implementation.producer.run_id:
                accepted_route = route
    if (
        accepted_route is None
        or accepted_route.outcome is not RouteAttemptOutcome.SUCCEEDED
        or accepted_route.result.attempt != accepted.attempt
        or accepted_route.result.artifact is None
        or accepted_route.result.context_manifest_id != implementation.context_manifest_id
        or artifact_digest(accepted_route.result.artifact) != artifact_digest(implementation)
    ):
        raise RecoveryRejected("retained candidate lost its accepted Coder execution")
    connection = open_mysql_connection(config.require_mysql_dsn(environment))
    try:
        with connection.cursor() as cursor:
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            cursor.execute(
                "SELECT lease_id FROM work_queue_claims "
                "WHERE task_id=%s AND state='ACTIVE' AND expires_at > %s",
                (task.id, datetime.now(UTC).isoformat()),
            )
            if cursor.fetchone() is not None:
                raise RecoveryRejected("retained candidate still has an active claim")
            cursor.execute(
                "SELECT id FROM work_queue_items WHERE task_id=%s "
                "AND status IN ('LEASED','RUNNING')",
                (task.id,),
            )
            if cursor.fetchone() is not None:
                raise RecoveryRejected("retained candidate still has an active work item")
    finally:
        connection.rollback()
        connection.close()
    GitWorktreeManager(
        task.repository,
        Path(config.platform_root) / "worktrees" / checkpoint.repository_id,
        branch_names={task.id: task.branch_name},
    ).require_clean_coder(
        WorktreeSpec(
            task_id=task.id,
            role=AgentRole.CODER,
            attempt=1,
            source_revision=implementation.content.commit_sha,
        )
    )


def _require_unfinished_coder_consultation(
    config: ProductionConfig, sidecar: Path, runtime: CandidateRuntimeSnapshot, feedback_id: str
) -> None:
    """Absence of a completed route is insufficient: prove knowledge never admitted work."""
    contexts = FileContextStore(sidecar / "contexts", read_only=True)
    records = KnowledgeRecordStore(sidecar / "knowledge/runs", read_only=True)
    manifest = RepositoryWorkspaceManifest.model_validate_json(
        _read_regular(sidecar / "workspace.json", 64_000)
    )
    matches: list[KnowledgeConsultationInput] = []
    for receipt in records.list("consultation-inputs", KnowledgeConsultationInput):
        binding = receipt.binding
        if binding.task_id != runtime.task.id or binding.role is not TeamRole.CODER:
            continue
        context = contexts.get(binding.context_manifest_id)
        if context.attempt != runtime.task.attempts:
            continue
        expected_task = runtime.task.model_copy(
            update={
                "status": TaskStatus.IMPLEMENTING,
                "updated_at": runtime.events[-2].occurred_at,
            }
        )
        tasks = tuple(s for s in context.sections if s.name == "task")
        feedback = tuple(s for s in context.sections if s.name == f"source:artifact.{feedback_id}")
        report = FileArtifactStore(sidecar / "artifacts", read_only=True).get(feedback_id)
        snapshot = records.get("snapshots", binding.snapshot_sha256, KnowledgeSnapshot)
        snapshot.validate_integrity()
        if (
            len(tasks) != 1
            or tasks[0].truncated
            or Task.model_validate_json(tasks[0].content) != expected_task
            or context.task_id != runtime.task.id
            or context.role is not AgentRole.CODER
            or context.source_revision != runtime.events[-2].source_revision
            or binding.source_revision != context.source_revision
            or binding.team_id != config.team_id
            or binding.project_id != manifest.project_id
            or binding.repository_ids != (manifest.repository_id,)
            or snapshot.team_id != binding.team_id
            or snapshot.project_id != binding.project_id
            or snapshot.requirement_id != binding.requirement_id
            or snapshot.repository_ids != binding.repository_ids
            or binding.run_id
            != "run_knowledge_" + digest((context.context_id, snapshot.snapshot_sha256))[:32]
            or receipt.input_sha256
            != digest({"task": expected_task.to_wire(), "context": context.to_wire()})
            or len(feedback) != 1
            or feedback[0].truncated
            or feedback[0].uri != f"artifact://{feedback_id}"
            or feedback[0].content != redact_text(canonical_bytes(report.to_wire()).decode()).text
            or any(s.name == "knowledge.consultation" for s in context.sections)
            or records.find("consultations", binding.run_id, KnowledgeConsultation) is not None
        ):
            raise RecoveryRejected("Coder knowledge preparation is not proved incomplete")
        matches.append(receipt)
    if len(matches) != 1:
        raise RecoveryRejected("Coder pre-provider consultation input is missing or ambiguous")
