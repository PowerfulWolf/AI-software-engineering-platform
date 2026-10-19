"""Reconstruct complete inherited inputs from approved immutable recovery lineage."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from pydantic import TypeAdapter
from pymysql.cursors import DictCursor

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context import ContextBundle, FileContextStore
from ai_software_engineer.domain import AgentRole, Task
from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.domain.task import task_matches_dispatch
from ai_software_engineer.git.capture import MAX_CAPTURE_BYTES
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.dispatch import RecoveryDispatchRecord
from ai_software_engineer.manager.mysql_dispatch_authority import _decode_allocation
from ai_software_engineer.read_record_scope import recovery_record_read_scope
from ai_software_engineer.recovery.context import recovery_context_sources, validate_reapply_context
from ai_software_engineer.recovery.inherited_queue import (
    _inherited_read_boundary,
    read_inherited_invocation_queue,
)
from ai_software_engineer.recovery.models import (
    MAX_INHERITED_REAPPLY_INPUTS,
    InheritedReapplyInput,
    RecoveryPlan,
    RecoveryRejected,
    RecoveryScope,
    RecoverySource,
    digest,
)
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.store.mysql_repository import (
    _decode_task,
    _non_negative_int,
    _text,
    open_mysql_connection,
)
from ai_software_engineer.team_workspace import TeamWorkspace
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart


class InheritedInputRecords(Protocol):
    """Trusted read ports; no agent-provided context or host URI resolution."""

    @property
    def recoveries(self) -> FileRecoveryStore: ...

    def task(self, task_id: str) -> tuple[Task, int]: ...

    def dispatch(self, plan_sha256: str) -> RecoveryDispatchRecord: ...

    def context(self, context_id: str) -> ContextBundle: ...

    def invocation(
        self, run_id: str, *, dispatch: RecoveryDispatchRecord, task: Task, first: bool = False
    ) -> DeliveryInvocationStart: ...


def reconstruct_inherited_reapply_inputs(
    records: InheritedInputRecords, source: RecoverySource, task: Task
) -> tuple[InheritedReapplyInput, ...] | None:
    """Old Plans may omit the field; actual ancestry still has to be reconstructed."""
    seen: set[str] = set()

    def visit(current: Task, origin: RecoverySource) -> tuple[InheritedReapplyInput, ...]:
        if current.id != origin.task_id or digest(current.to_wire()) != origin.task_sha256:
            raise RecoveryRejected("inherited recovery source Task changed")
        plan_sha = current.metadata.get("recovery_plan_sha256")
        if plan_sha is None:
            if current.id.startswith("task_recovery_"):
                raise RecoveryRejected("inherited recovery Task has no approved origin")
            return ()
        plan_sha = TypeAdapter(StageSha256).validate_python(plan_sha)
        if plan_sha in seen or len(seen) >= MAX_INHERITED_REAPPLY_INPUTS:
            raise RecoveryRejected("inherited recovery lineage is cyclic or exceeds its bound")
        seen.add(plan_sha)
        plan = records.recoveries.get_plan(plan_sha)
        authorization = records.recoveries.get_authorization(plan_sha)
        sealed = records.recoveries.get_task_record(plan_sha)
        seed = records.recoveries.get_seed(plan_sha)
        admitted = records.recoveries.get_invocation(plan_sha)
        dispatch = records.dispatch(plan_sha)
        dispatch.validate_integrity()
        if (
            plan.source.scope != source.scope
            or plan.new_task_id != current.id
            or not authorization.decision.approved
            or not task_matches_dispatch(current, sealed.task)
            or dispatch.task != sealed.task
            or dispatch.recovery_task_record_sha256 != sealed.record_sha256
            or dispatch.dispatch_sha256 != origin.dispatch_sha256
            or seed.dispatch_sha256 != dispatch.dispatch_sha256
            or admitted.seed_record_sha256 != seed.record_sha256
        ):
            raise RecoveryRejected("inherited recovery approval, Task or dispatch does not match")
        first = records.invocation(admitted.run_id, dispatch=dispatch, task=current, first=True)
        initial = records.context(admitted.context_manifest_id)
        _require_context(first, initial, current)
        if (
            first.request.context_manifest_id != admitted.context_manifest_id
            or first.request.source_revision != sealed.task.base_ref
            or first.request.permissions != plan.effective_target_permissions
        ):
            raise RecoveryRejected("inherited recovery invocation differs from its approved seed")
        validate_reapply_context(plan, initial)
        if origin.failed_run_id is None:
            raise RecoveryRejected("inherited recovery requires its actual failed main invocation")
        failed = records.invocation(origin.failed_run_id, dispatch=dispatch, task=current)
        failed_context = records.context(origin.failed_context_id)
        _require_context(failed, failed_context, current)
        if (
            failed.request.context_manifest_id != origin.failed_context_id
            or failed.request.execution_baseline_sha256 != origin.execution_baseline_sha256
            or (
                origin.execution_baseline_sha256 is None
                and failed.request.source_revision != origin.base_revision
            )
            or (
                origin.execution_baseline_sha256 is not None
                and failed.request.execution_base_ref != origin.effective_base_revision
            )
            or failed.request.permissions != plan.effective_target_permissions
        ):
            raise RecoveryRejected("inherited recovery failed request or source epoch changed")
        validate_reapply_context(plan, failed_context)
        previous, revision = records.task(plan.source.task_id)
        if revision != plan.source.task_revision:
            raise RecoveryRejected("inherited recovery predecessor revision changed")
        inherited = visit(previous, plan.source)
        # An old Plan with None may predate inheritance support. It still cannot
        # erase the trusted ancestry when the new successor is proposed.
        if plan.inherited_reapply_inputs is not None and plan.inherited_reapply_inputs != inherited:
            raise RecoveryRejected("inherited recovery Plan lost or changed its frozen ancestors")
        if plan.input_mode == "coder_reapply":
            patch = next(
                s for s in recovery_context_sources(plan) if s.source_id == "recovery.patch"
            )
            assert patch.content is not None
            section = next(s for s in initial.sections if s.name == "source:recovery.patch")
            value = InheritedReapplyInput(
                origin_plan_sha256=plan_sha,
                origin_task_id=current.id,
                origin_context_manifest_id=initial.context_id,
                patch_uri=section.uri,
                patch_sha256=section.sha256,
                patch_bytes=len(patch.content.encode("utf-8")),
                patch=patch.content,
            )
            inherited = (*inherited, value)
        if (
            len(inherited) > MAX_INHERITED_REAPPLY_INPUTS
            or len({(v.origin_plan_sha256, v.patch_sha256) for v in inherited}) != len(inherited)
            or sum(v.patch_bytes for v in inherited) > MAX_CAPTURE_BYTES
        ):
            raise RecoveryRejected(
                "inherited recovery input exceeds its complete bounded inventory"
            )
        return inherited

    return visit(task, source) or None


def _require_context(start: DeliveryInvocationStart, context: ContextBundle, task: Task) -> None:
    start.validate_integrity()
    request = start.request
    if (
        request.task_id,
        request.role,
        request.context_manifest_id,
        request.source_revision,
        request.attempt,
    ) != (
        context.task_id,
        context.role,
        context.context_id,
        context.source_revision,
        context.attempt,
    ):
        raise RecoveryRejected("inherited recovery Context differs from its actual invocation")
    if request.task_id != task.id or request.role is not AgentRole.CODER:
        raise RecoveryRejected("inherited recovery Context belongs to another Task or role")


@dataclass
class _NativeRecords:
    recoveries: FileRecoveryStore
    contexts: FileContextStore
    starts: tuple[DeliveryInvocationStart, ...]
    dsn: str
    invocations: KnowledgeRecordStore
    scope: RecoveryScope
    project_id: ProjectId

    def task(self, task_id: str) -> tuple[Task, int]:
        connection = open_mysql_connection(self.dsn)
        try:
            with connection.cursor(DictCursor) as cursor:
                cursor.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
                row = cursor.fetchone()
                if row is None:
                    raise RecoveryRejected("inherited recovery predecessor Task is missing")
                return _decode_task(task_id, _text(row, "payload_json")), _non_negative_int(
                    row, "revision"
                )
        finally:
            connection.rollback()
            connection.close()

    def dispatch(self, plan_sha256: str) -> RecoveryDispatchRecord:
        connection = open_mysql_connection(self.dsn)
        try:
            with connection.cursor(DictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM dispatch_commits WHERE id = %s",
                    ("dispatch_commit_" + plan_sha256,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RecoveryRejected("inherited recovery dispatch is missing")
                value = _decode_allocation(row)
                if not isinstance(value, RecoveryDispatchRecord):
                    raise RecoveryRejected("inherited recovery dispatch has the wrong type")
                return value
        finally:
            connection.rollback()
            connection.close()

    def context(self, context_id: str) -> ContextBundle:
        return self.contexts.get(context_id)

    def invocation(
        self, run_id: str, *, dispatch: RecoveryDispatchRecord, task: Task, first: bool = False
    ) -> DeliveryInvocationStart:
        matching = tuple(start for start in self.starts if start.request.run_id == run_id)
        if len(matching) != 1:
            raise RecoveryRejected("inherited recovery has no unique actual invocation")
        start = matching[0]
        if first and any(
            other.request.task_id == task.id
            and other.request.role is AgentRole.CODER
            and other.request.run_id != run_id
            and other.started_at <= start.started_at
            for other in self.starts
        ):
            raise RecoveryRejected(
                "inherited recovery seed is not its first actual main invocation"
            )
        if (
            self.invocations.get("invocation-starts", start.work_item_id, DeliveryInvocationStart)
            != start
        ):
            raise RecoveryRejected("inherited recovery invocation changed its durable store key")
        read_inherited_invocation_queue(
            self.dsn, start, dispatch, task, self.scope, self.project_id
        )
        return start


@_inherited_read_boundary
@recovery_record_read_scope()
def read_inherited_reapply_inputs(
    config: ProductionConfig,
    environment: Mapping[str, str],
    source: RecoverySource,
    task: Task,
) -> tuple[InheritedReapplyInput, ...] | None:
    if task.metadata.get("recovery_plan_sha256") is None and not task.id.startswith(
        "task_recovery_"
    ):
        return None
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name, read_only=True
    )
    project, repository = team.project_registry().locate_repository(source.scope.repository_id)
    if (
        config.team_id != source.scope.team_id
        or str(repository.repository_root) != source.scope.repository_root
    ):
        raise RecoveryRejected("inherited recovery repository scope changed")
    sidecar = repository.root
    invocations = KnowledgeRecordStore(sidecar / "state/invocations", read_only=True)
    records = _NativeRecords(
        FileRecoveryStore(
            sidecar / "state" / f"recovery-{source.scope.delivery_id}", scope=source.scope
        ),
        FileContextStore(sidecar / "contexts", read_only=True),
        invocations.list("invocation-starts", DeliveryInvocationStart),
        config.require_mysql_dsn(environment),
        invocations,
        source.scope,
        project.manifest.project_id,
    )
    return reconstruct_inherited_reapply_inputs(records, source, task)


@_inherited_read_boundary
def require_plan_inherited_inputs(
    config: ProductionConfig, environment: Mapping[str, str], plan: RecoveryPlan
) -> None:
    """Re-read ancestry; omission on a new executable Plan never waives old inputs."""
    if not plan.source.task_id.startswith("task_recovery_") and not plan.inherited_reapply_inputs:
        return
    dsn = config.require_mysql_dsn(environment)
    connection = open_mysql_connection(dsn)
    try:
        with connection.cursor(DictCursor) as cursor:
            cursor.execute("SELECT * FROM tasks WHERE id = %s", (plan.source.task_id,))
            row = cursor.fetchone()
            if row is None or _non_negative_int(row, "revision") != plan.source.task_revision:
                raise RecoveryRejected("inherited recovery source revision changed")
            task = _decode_task(plan.source.task_id, _text(row, "payload_json"))
    finally:
        connection.rollback()
        connection.close()
    if (
        read_inherited_reapply_inputs(config, environment, plan.source, task)
        != plan.inherited_reapply_inputs
    ):
        raise RecoveryRejected(
            "recovery Plan does not preserve its exact complete inherited inputs"
        )
