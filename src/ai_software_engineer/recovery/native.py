"""Read original production delivery facts without preparing or restarting anything.

This is source inspection, NOT a complete recovery authorization/fresh-target verifier.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter
from pymysql.cursors import DictCursor

from ai_software_engineer.agents import FileModelRouteAttemptStore
from ai_software_engineer.agents.fallback import RouteAttemptOutcome, model_route_root
from ai_software_engineer.company_workspace import CompanyWorkspace, _read_regular, _reject_symlinks
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.design import FileDesignRecordStore
from ai_software_engineer.domain import (
    AgentPermissions,
    AgentRole,
    ExecutionPlan,
    ProductSpec,
    ProductSpecApproval,
    ProjectPreparation,
    Task,
    TaskStatus,
    TechnicalDesign,
)
from ai_software_engineer.domain.identity import ContextId, RunId
from ai_software_engineer.domain.project_delivery import validate_stage_chain
from ai_software_engineer.multi_directory.production import DerivedStageInputs
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.planning import FileExecutionPlanStore
from ai_software_engineer.product import FileProductRecordStore
from ai_software_engineer.project_manager.delivery import _delivery_id
from ai_software_engineer.project_manager.delivery_checkpoint import (
    DeliveryStage,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.project_manager.dispatch import DispatchCommitRecord
from ai_software_engineer.project_manager.mysql_dispatch_authority import _decode_commit
from ai_software_engineer.project_manager.production_backend import _designer_run_id
from ai_software_engineer.project_manager.store import FileProjectPreparationStore
from ai_software_engineer.project_workspace import ProjectWorkspaceManifest
from ai_software_engineer.recovery.models import (
    RecoveryRejected,
    RecoveryScope,
    RecoverySource,
    digest,
)
from ai_software_engineer.store.mysql_repository import (
    _decode_event,
    _decode_task,
    _non_negative_int,
    _text,
    open_mysql_connection,
)


@dataclass(frozen=True)
class NativeRecoverySource:
    source: RecoverySource
    permissions: AgentPermissions
    denied_paths: tuple[str, ...]
    preparation: ProjectPreparation
    product: ProductSpec
    approval: ProductSpecApproval
    design: TechnicalDesign
    plan: ExecutionPlan


class NativeRecoverySourceReader:
    def __init__(self, config: ProductionConfig, environment: Mapping[str, str]) -> None:
        self._config = config
        self._environment = dict(environment)

    def inspect(
        self, scope: RecoveryScope, *, failed_run_id: str, failed_context_id: str
    ) -> NativeRecoverySource:
        try:
            scope = RecoveryScope.model_validate(scope.to_wire())
            TypeAdapter(RunId).validate_python(failed_run_id)
            TypeAdapter(ContextId).validate_python(failed_context_id)
            return self._inspect(scope, failed_run_id, failed_context_id)
        except Exception as error:
            # Public diagnostic never includes native prose, provider output, or a DSN.
            raise RecoveryRejected(
                "original delivery facts are missing, unsafe or inconsistent"
            ) from error

    def _inspect(self, scope: RecoveryScope, run_id: str, context_id: str) -> NativeRecoverySource:
        if scope.company_id != self._config.company_id:
            raise ValueError("company mismatch")
        company = CompanyWorkspace.initialize(
            self._config.platform_root,
            company_id=scope.company_id,
            name=self._config.company_name,
            read_only=True,
        )
        root = company.root / "projects" / scope.project_id
        for relative in (
            "state/product",
            "state/design",
            "state/planning",
            "contexts",
            "runs",
            "policy",
        ):
            _reject_symlinks(root / relative)
        manifest = ProjectWorkspaceManifest.model_validate_json(
            _read_regular(root / "workspace.json", 64_000)
        )
        manifest.validate_binding(root)
        if manifest.project_id != scope.project_id or manifest.project_root != scope.project_root:
            raise ValueError("project scope mismatch")
        journal = FileProjectDeliveryCheckpointStore(
            root / "state/project-deliveries", read_only=True
        )
        cp = journal.current(scope.delivery_id)
        intake = journal.get_intake(scope.delivery_id)
        if (
            cp.project_id != scope.project_id
            or cp.project_root != scope.project_root
            or intake.project_id != scope.project_id
            or intake.project_root != scope.project_root
            or cp.stage is not DeliveryStage.BLOCKED
            or cp.task_status is not TaskStatus.BLOCKED
            or cp.candidate_revision is not None
        ):
            raise ValueError("not a failed pre-candidate delivery")
        task, revision, dispatch = self._sql(cp)
        product_store = FileProductRecordStore(root / "state/product", read_only=True)
        design_store = FileDesignRecordStore(root / "state/design", read_only=True)
        planner_store = FileExecutionPlanStore(root / "state/planning", read_only=True)
        if cp.product_spec_id is None or cp.approval_id is None:
            raise ValueError("missing approved product")
        product = product_store.find_product_spec(cp.product_spec_id)
        approval = product_store.find_approval(cp.approval_id)
        if product is None or approval is None:
            raise ValueError("missing native product approval")
        design_run = design_store.get_run(_designer_run_id(cp.delivery_id))
        design_cp = design_store.get_checkpoint(design_run.run_id)
        design = design_run.technical_design
        planner_run = planner_store.get_run(dispatch.planner_run_id)
        planner_cp = planner_store.get_checkpoint(dispatch.planner_run_id)
        plan = planner_store.get_execution_plan(dispatch.execution_plan_id)
        ready = product_store.current_request_revision(dispatch.project_request_id)
        if design is None or design_run.planning_authorization is None:
            raise ValueError("missing completed design")
        if (
            design_store.get_design(design.id) != design
            or design_cp.run_record_sha256 != design_run.run_record_sha256
            or design_cp.technical_design_sha256 != design.technical_design_sha256
            or design_cp.checkpoint_sha256 != dispatch.design_checkpoint_sha256
            or planner_run.design_checkpoint_sha256 != design_cp.checkpoint_sha256
            or planner_run.input_request_revision_sha256 != design_cp.request_revision_sha256
            or planner_run.planning_authorization_sha256
            != design_run.planning_authorization.authorization_sha256
            or planner_run.run_record_sha256 != dispatch.planner_run_record_sha256
            or planner_run.ready_request_revision != ready
            or planner_run.execution_plan != plan
            or planner_cp.run_record_sha256 != planner_run.run_record_sha256
            or planner_cp.checkpoint_sha256 != dispatch.planner_checkpoint_sha256
            or planner_cp.ready_request_revision_sha256 != ready.request_revision_sha256
            or dispatch.ready_request_revision_sha256 != ready.request_revision_sha256
            or dispatch.ready_request_revision != ready.revision
        ):
            raise ValueError("upstream commit chain mismatch")
        preparation = _preparation(root, scope.project_id, ready.request.preparation_sha256)
        validate_stage_chain(preparation, ready.request, product, approval, design, plan)
        if (
            preparation.project_root != scope.project_root
            or preparation.project_workspace_root != str(root)
            or preparation.organization_root
            != str(Path(self._config.platform_root) / "organization")
            or preparation.preparation_sha256 != cp.preparation_sha256
            or product.product_spec_sha256 != cp.product_spec_sha256
            or approval.approval_sha256 != cp.approval_sha256
            or design.technical_design_sha256 != cp.technical_design_sha256
            or plan.execution_plan_sha256 != cp.execution_plan_sha256
            or cp.request_id != ready.request.id
            or task.acceptance_criteria != product.acceptance_criteria
        ):
            raise ValueError("checkpoint stage references mismatch")
        parent_id, parent_sha = _parent(company, cp, approval)
        _reject_symlinks(root / "contexts" / f"{context_id}.json")
        # Bounded regular-file preflight prevents a FIFO/oversized Context read.
        _read_regular(root / "contexts" / f"{context_id}.json", 8_000_000)
        context = FileContextStore(root / "contexts", read_only=True).get(context_id)
        route_directory = model_route_root(root) / run_id
        _reject_symlinks(route_directory)
        for path in route_directory.glob("*.json"):
            _read_regular(path, 8_000_000)
        routes = FileModelRouteAttemptStore(model_route_root(root), read_only=True).list_for_run(
            run_id
        )
        if not routes:
            raise ValueError("missing failed route")
        if tuple(route.route_index for route in routes) != tuple(range(1, len(routes) + 1)):
            raise ValueError("failed route history has gaps")
        for route in routes:
            route.validate_integrity()
            result = route.result
            if (
                route.role is not AgentRole.CODER
                or route.task_id != task.id
                or route.outcome is RouteAttemptOutcome.SUCCEEDED
                or result.context_manifest_id != context_id
                or result.source_revision != task.base_ref
                or result.attempt != task.attempts
            ):
                raise ValueError("route does not belong to failed Coder")
        if (
            context.task_id != task.id
            or context.role is not AgentRole.CODER
            or context.source_revision != task.base_ref
            or context.attempt != task.attempts
        ):
            raise ValueError("failed context mismatch")
        policy_sections = [s for s in context.sections if s.name == "policy"]
        if len(policy_sections) != 1:
            raise ValueError("missing exact policy section")
        policy = json.loads(policy_sections[0].content)
        denied = TypeAdapter(tuple[str, ...]).validate_python(policy.pop("denied_paths"))
        permissions = AgentPermissions.model_validate(policy)
        if (
            permissions.can_merge
            or permissions.can_change_state
            or task.constraints is None
            or permissions.write_paths != task.constraints.allowed_paths
        ):
            raise ValueError("Coder permissions differ from dispatch")
        source = RecoverySource(
            scope=scope,
            task_id=task.id,
            task_revision=revision,
            task_sha256=digest(task.to_wire()),
            checkpoint_sha256=cp.checkpoint_sha256,
            dispatch_sha256=dispatch.dispatch_sha256,
            preparation_sha256=preparation.preparation_sha256,
            product_spec_sha256=product.product_spec_sha256,
            approval_sha256=approval.approval_sha256,
            technical_design_sha256=design.technical_design_sha256,
            execution_plan_sha256=plan.execution_plan_sha256,
            failed_run_id=run_id,
            failed_context_id=context_id,
            base_revision=task.base_ref,
            parent_delivery_id=parent_id,
            parent_checkpoint_sha256=parent_sha,
        )
        if journal.current(scope.delivery_id) != cp or self._sql(cp) != (task, revision, dispatch):
            raise ValueError("source changed during inspection")
        if product_store.current_request_revision(ready.request.id) != ready:
            raise ValueError("approved request changed during inspection")
        if _parent(company, cp, approval) != (parent_id, parent_sha):
            raise ValueError("parent changed during inspection")
        return NativeRecoverySource(
            source, permissions, denied, preparation, product, approval, design, plan
        )

    def _sql(self, cp: ProjectDeliveryCheckpoint) -> tuple[Task, int, DispatchCommitRecord]:
        if cp.task_id is None or cp.dispatch_commit_id is None:
            raise ValueError("missing materialized Task")
        connection = open_mysql_connection(self._config.require_mysql_dsn(self._environment))
        try:
            with connection.cursor(DictCursor) as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                cursor.execute(
                    "SELECT * FROM dispatch_commits WHERE id = %s", (cp.dispatch_commit_id,)
                )
                row = cursor.fetchone()
                if row is None:
                    raise ValueError("missing dispatch")
                dispatch = _decode_commit(row)
                cursor.execute("SELECT * FROM tasks WHERE id = %s", (cp.task_id,))
                row = cursor.fetchone()
                if row is None:
                    raise ValueError("missing Task")
                task = _decode_task(cp.task_id, _text(row, "payload_json"))
                revision = _non_negative_int(row, "revision")
                normalized = task.model_copy(
                    update={
                        "status": TaskStatus.NEW,
                        "attempts": 0,
                        "updated_at": dispatch.task.updated_at,
                    }
                )
                if (
                    task.status is not TaskStatus.BLOCKED
                    or _text(row, "status") != task.status.value
                    or task.attempts != 1
                    or revision != cp.task_revision
                    or normalized != dispatch.task
                    or dispatch.task_id != cp.task_id
                    or dispatch.project_id != cp.project_id
                    or dispatch.task.repository != cp.project_root
                    or dispatch.dispatch_sha256 != cp.dispatch_commit_sha256
                ):
                    raise ValueError("Task dispatch mismatch")
                cursor.execute(
                    "SELECT * FROM state_events WHERE task_id = %s ORDER BY revision", (cp.task_id,)
                )
                rows = cursor.fetchall()
                if [r["revision"] for r in rows] != list(range(1, revision + 1)):
                    raise ValueError("event revision gap")
                previous = TaskStatus.NEW
                for event_row in rows:
                    event = _decode_event(_text(event_row, "payload_json"))
                    if (
                        event.task_id != task.id
                        or event.event_id != event_row["event_id"]
                        or event.from_status is not previous
                        or event.attempt != task.attempts
                        or event.source_revision != task.base_ref
                    ):
                        raise ValueError("event chain mismatch")
                    previous = event.to_status
                if (
                    not rows
                    or previous is not TaskStatus.BLOCKED
                    or event.from_status is not TaskStatus.IMPLEMENTING
                ):
                    raise ValueError("not an interrupted Coder")
                return task, revision, dispatch
        finally:
            connection.rollback()
            connection.close()


def _preparation(root: Path, project_id: str, expected: str) -> ProjectPreparation:
    policy = root / "policy"
    _reject_symlinks(policy)
    directories = (policy, *sorted(policy.glob("preparations-*")))
    matches: list[ProjectPreparation] = []
    for directory in directories:
        _reject_symlinks(directory)
        path = directory / f"project-preparation-{project_id}.json"
        if not path.exists() and not path.is_symlink():
            continue
        _read_regular(path, 1_000_000)
        record = FileProjectPreparationStore(directory, read_only=True).get(project_id)
        if record.preparation_sha256 == expected:
            matches.append(record)
    if len(matches) != 1:
        raise ValueError("missing or ambiguous original preparation")
    return matches[0]


def _parent(
    company: CompanyWorkspace, cp: ProjectDeliveryCheckpoint, approval: ProductSpecApproval
) -> tuple[str | None, str | None]:
    journal = JointJournal(company.requests_root, read_only=True)
    matches: list[tuple[str, str]] = []
    for directory in sorted(company.requests_root.glob("delivery_multi_*")):
        _reject_symlinks(directory)
        for path in directory.glob("*.json"):
            _read_regular(path, 8_000_000)
        parent = journal.current(directory.name)
        if parent is None:
            continue
        if (
            parent.company_id != company.manifest.company_id
            or parent.company_manifest_sha256 != company.manifest.manifest_sha256
        ):
            raise ValueError("joint company mismatch")
        if parent.plan is None or parent.design is None:
            continue
        for unit in parent.plan.units:
            derived = DerivedStageInputs(parent, unit.unit_id)
            if (
                _delivery_id(derived.root, derived.requirement, namespace=parent.company_id)
                != cp.delivery_id
            ):
                continue
            children = [
                child for child in parent.children if child.checkpoint.delivery_id == cp.delivery_id
            ]
            if (
                parent.stage != "BLOCKED"
                or len(children) != 1
                or children[0].checkpoint != cp
                or approval.operator_id != "joint-human-approval-delegation"
                or approval.rationale != derived.approval_reference
            ):
                raise ValueError("joint approval delegation mismatch")
            matches.append((parent.delivery_id, parent.checkpoint_sha256))
    if len(matches) > 1 or (
        not matches and approval.operator_id == "joint-human-approval-delegation"
    ):
        raise ValueError("missing or ambiguous parent")
    return matches[0] if matches else (None, None)
