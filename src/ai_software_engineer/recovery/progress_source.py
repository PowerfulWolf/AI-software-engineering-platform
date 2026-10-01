"""Prove an accepted Coder checkpoint survived a pre-provider continuation failure."""

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from ai_software_engineer.agents import FileModelRouteAttemptStore, ModelRouteAttempt
from ai_software_engineer.agents.fallback import RouteAttemptOutcome, model_route_root
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.artifacts.store import artifact_digest
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import AgentRole, CoderProgressArtifact, Task, TaskStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.manager.delivery_checkpoint import ProjectDeliveryCheckpoint
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.team_workspace import _read_regular, _reject_symlinks


def accepted_scope_progress(
    sidecar: Path, task: Task, events: tuple[StateEvent, ...], source_revision: str
) -> CoderProgressArtifact | None:
    """Latest accepted report is scope evidence, never a replacement failed source."""
    accepted = [
        event
        for event in events
        if event.from_status is TaskStatus.IMPLEMENTING
        and event.to_status is TaskStatus.CONTINUE_REQUIRED
        and event.reason in {"coder_requested_continuation", "coder_progress_recovered"}
    ]
    if not accepted:
        return None
    event = accepted[-1]
    # QA/Review may have routed Coder to a newer candidate since this report.
    # An old-base progress cannot justify scope there, but must not block ordinary
    # recovery of the newer failed execution when no scope request is supplied.
    if event.source_revision != source_revision:
        return None
    try:
        if (
            task.status is not TaskStatus.BLOCKED
            or event.task_id != task.id
            or event.attempt > task.attempts
            or len(event.artifact_ids) != 1
        ):
            raise ValueError("scope progress event is outside the terminal Task")
        artifact_id = event.artifact_ids[0]
        artifact_path = sidecar / "artifacts" / f"{artifact_id}.json"
        _reject_symlinks(artifact_path)
        _read_regular(artifact_path, 8_000_000)
        progress = FileArtifactStore(sidecar / "artifacts", read_only=True).get(artifact_id)
        if not isinstance(progress, CoderProgressArtifact):
            raise ValueError("accepted scope report is not Coder progress")
        route_root = model_route_root(sidecar)
        directory = route_root / progress.producer.run_id
        _reject_symlinks(directory)
        for path in directory.glob("*.json"):
            _read_regular(path, 8_000_000)
        routes = FileModelRouteAttemptStore(route_root, read_only=True).list_for_run(
            progress.producer.run_id
        )
        if not routes or tuple(route.route_index for route in routes) != tuple(
            range(1, len(routes) + 1)
        ):
            raise ValueError("accepted scope route history is incomplete")
        final = routes[-1]
        if (
            not has_accepted_progress(final, (event,))
            or final.result.artifact is None
            or artifact_digest(final.result.artifact) != artifact_digest(progress)
        ):
            raise ValueError("scope progress differs from its accepted route")
        for route in routes:
            if (
                route.task_id != task.id
                or route.role is not AgentRole.CODER
                or route.result.attempt != event.attempt
                or route.result.source_revision != source_revision
                or route.result.context_manifest_id != progress.context_manifest_id
                or (route is not final and route.outcome is not RouteAttemptOutcome.FALLBACK)
            ):
                raise ValueError("scope progress route identity differs")
        context_path = sidecar / "contexts" / f"{progress.context_manifest_id}.json"
        _reject_symlinks(context_path)
        _read_regular(context_path, 8_000_000)
        context = FileContextStore(sidecar / "contexts", read_only=True).get(
            progress.context_manifest_id
        )
        if (
            context.task_id != task.id
            or context.role is not AgentRole.CODER
            or context.attempt != event.attempt
            or context.source_revision != source_revision
        ):
            raise ValueError("scope progress Context differs")
        return progress
    except Exception as error:
        raise ValueError("latest accepted scope progress is missing or inconsistent") from error


def has_accepted_progress(route: ModelRouteAttempt, events: tuple[StateEvent, ...]) -> bool:
    """A terminal reference alone is not the orchestrator's progress acceptance."""
    progress = route.result.artifact
    if (
        route.role is not AgentRole.CODER
        or route.outcome is not RouteAttemptOutcome.SUCCEEDED
        or not isinstance(progress, CoderProgressArtifact)
        or progress.task_id != route.task_id
        or progress.producer.run_id != route.run_id
        or progress.context_manifest_id != route.result.context_manifest_id
        or progress.source_revision != route.result.source_revision
        or progress.content.checkpoint_sequence != route.result.attempt
    ):
        return False
    return any(
        event.from_status is TaskStatus.IMPLEMENTING
        and event.to_status is TaskStatus.CONTINUE_REQUIRED
        and event.reason in {"coder_requested_continuation", "coder_progress_recovered"}
        and event.task_id == progress.task_id
        and event.attempt == progress.content.checkpoint_sequence
        and event.source_revision == progress.source_revision
        and event.artifact_ids == (progress.artifact_id,)
        for event in events
    )


def is_prior_progress_source(
    route: ModelRouteAttempt,
    task: Task,
    checkpoint: ProjectDeliveryCheckpoint,
    events: tuple[StateEvent, ...],
) -> bool:
    progress = route.result.artifact
    reasons = {
        "TRANSIENT_INFRA: coder knowledge preparation failed: AUTHENTICATION_ERROR",
        "TRANSIENT_INFRA: coder knowledge preparation failed: TIMEOUT",
    }
    if (
        route.task_id != task.id
        or route.role is not AgentRole.CODER
        or route.outcome is not RouteAttemptOutcome.SUCCEEDED
        or not isinstance(progress, CoderProgressArtifact)
        or route.result.attempt + 1 != task.attempts
        or progress.content.checkpoint_sequence != route.result.attempt
        or progress.producer.run_id != route.run_id
        or progress.task_id != task.id
        or progress.context_manifest_id != route.result.context_manifest_id
        or progress.source_revision != task.base_ref
        or checkpoint.candidate_revision is not None
        or len(events) < 4
    ):
        return False
    accepted, queued, resumed, blocked = events[-4:]
    if (
        blocked.reason not in reasons
        or checkpoint.failure_summary != blocked.reason.split(": ", 1)[1]
        or progress.artifact_id not in blocked.artifact_ids
    ):
        return False
    expected = (
        (
            TaskStatus.IMPLEMENTING,
            TaskStatus.CONTINUE_REQUIRED,
            "coder_requested_continuation",
            task.attempts - 1,
        ),
        (
            TaskStatus.CONTINUE_REQUIRED,
            TaskStatus.QUEUED,
            "coder_continuation_queued",
            task.attempts - 1,
        ),
        (TaskStatus.QUEUED, TaskStatus.IMPLEMENTING, "coder_continuation_resumed", task.attempts),
        (TaskStatus.IMPLEMENTING, TaskStatus.BLOCKED, blocked.reason, task.attempts),
    )
    return all(
        (event.from_status, event.to_status, event.reason, event.attempt) == identity
        and event.task_id == task.id
        and event.source_revision == task.base_ref
        and (event is blocked or event.artifact_ids == (progress.artifact_id,))
        for event, identity in zip((accepted, queued, resumed, blocked), expected, strict=True)
    ) and not any(event.reason in {"candidate_ready", "candidate_recovered"} for event in events)


def require_stopped_progress(
    config: ProductionConfig,
    environment: Mapping[str, str],
    sidecar: Path,
    task: Task,
    route: ModelRouteAttempt,
) -> None:
    """A later provider execution or still-owned worker invalidates the prior source."""
    root = model_route_root(sidecar)
    _reject_symlinks(root)
    store = FileModelRouteAttemptStore(root, read_only=True)
    for directory in root.iterdir():
        _reject_symlinks(directory)
        for other in store.list_for_run(directory.name):
            if other.task_id == task.id and (
                other.result.attempt > route.result.attempt
                or (other.result.attempt == route.result.attempt and other.run_id != route.run_id)
            ):
                raise ValueError("later or ambiguous provider execution exists")
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
                raise ValueError("prior progress still has an active claim")
            cursor.execute(
                "SELECT id FROM work_queue_items WHERE task_id=%s "
                "AND status IN ('LEASED','RUNNING')",
                (task.id,),
            )
            if cursor.fetchone() is not None:
                raise ValueError("prior progress still has an active work item")
    finally:
        connection.rollback()
        connection.close()
