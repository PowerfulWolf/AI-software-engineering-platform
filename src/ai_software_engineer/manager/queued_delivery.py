"""Bind approved native delivery inputs to the existing T046 dispatcher."""

import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from ai_software_engineer.config import ProviderRouteConfig
from ai_software_engineer.domain import AgentRole, ModelPolicy, ModelSelection, WorkItemStatus
from ai_software_engineer.domain.project_delivery import ExecutionPlan
from ai_software_engineer.manager.dispatch import DeliveryAllocation
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.planning.preview import derive_phase_demands
from ai_software_engineer.runtime_workspace import FileTeamWorkforceStore
from ai_software_engineer.scheduling import ModelRouter, PortfolioScheduler
from ai_software_engineer.work_queue.dispatcher import DispatcherLoop
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, QueuedRoleStep
from ai_software_engineer.work_queue.models import QueuedWorkItem
from ai_software_engineer.work_queue.ports import QueueConflict


class ApprovedRoleDispatch:
    """Recompute execution capacity while retaining the approved actor/model binding.

    This first production integration does not silently reassign a frozen dispatch.
    Any route mismatch is refused before a Worker can construct its role Context.
    """

    def __init__(
        self,
        queue: MySqlRoleQueue,
        dispatch: DeliveryAllocation,
        plan: ExecutionPlan,
        workforce: FileTeamWorkforceStore,
        repository_root: Path,
        proxy_base_url: str | None = None,
    ) -> None:
        self.queue, self.dispatch, self.workforce = queue, dispatch, workforce
        self.root = repository_root
        self.proxy_base_url = proxy_base_url
        self.phases = {phase.role: phase for phase in dispatch.phases}
        self.demands = {demand.role: demand for demand in derive_phase_demands(dispatch.task, plan)}
        self.worker_id = "worker_delivery_" + uuid4().hex

    def build_step(
        self, boundary: RoleRunBoundary, parent: str | None, now: datetime
    ) -> QueuedRoleStep:
        if boundary.task_id != self.dispatch.task_id:
            raise QueueConflict("boundary belongs to another allocation")
        demand = self.demands[boundary.role]
        identity = hashlib.sha256(
            f"{boundary.task_id}:{boundary.role}:{boundary.attempt}:{boundary.checkpoint_sequence}".encode()
        ).hexdigest()
        return QueuedRoleStep(
            boundary=boundary,
            allocation_sha256=self.dispatch.dispatch_sha256,
            work_item=QueuedWorkItem(
                id="work_" + identity,
                task_id=boundary.task_id,
                repository_id=self.dispatch.repository_id,
                role=boundary.role,
                attempt=boundary.attempt,
                checkpoint_sequence=boundary.checkpoint_sequence,
                repository_scopes=(str(self.root),),
                parent_work_item_id=parent,
                status=WorkItemStatus.READY,
                priority=500,
                risk=demand.risk,
                required_capabilities=demand.required_capabilities,
                preferred_agent_id=self.phases[boundary.role].agent_id,
                created_at=now,
                updated_at=now,
            ),
        )

    def dispatcher(self, step: QueuedRoleStep) -> DispatcherLoop:
        if step.allocation_sha256 != self.dispatch.dispatch_sha256:
            raise QueueConflict("queue step allocation changed")
        phase = self.phases[step.boundary.role]
        profile = self.workforce.get_agent(phase.agent_id)
        policy = self.workforce.get_policy(
            phase.model_selection.policy_id, version=phase.model_selection.policy_version
        )
        demand = self.demands[phase.role]
        router = ModelRouter(
            route_context_capacities={
                (route.provider, route.model): 2_000_000 for route in policy.routes
            }
        )
        # Check the deterministic selected model before publishing a claim. The
        # original dispatch remains the authority for allowed model/actor scope.
        routing = router.route(demand, profile, policy, now=step.work_item.created_at)
        selected = routing.selection
        expected = phase.model_selection
        if selected is None or (
            selected.provider,
            selected.model,
            selected.reasoning_effort,
            selected.route_kind,
            selected.connection_mode,
        ) != (
            expected.provider,
            expected.model,
            expected.reasoning_effort,
            expected.route_kind,
            expected.connection_mode,
        ):
            raise QueueConflict("Worker routing no longer matches approved dispatch")
        return DispatcherLoop(
            queue=self.queue,
            scheduler=PortfolioScheduler(lease_duration=timedelta(seconds=60)),
            model_router=router,
            agents=(profile,),
            policies=(policy,),
            demand_builder=lambda item: self.demands[item.role],
            worker_id=self.worker_id,
            expired_lease_retry_delay=timedelta(seconds=1),
        )

    def validate_routes(self, role: AgentRole, routes: tuple[ProviderRouteConfig, ...]) -> None:
        selection = self.phases[role].model_selection
        policy = self.workforce.get_policy(selection.policy_id, version=selection.policy_version)
        validate_frozen_routes(role, selection, policy, routes, proxy_base_url=self.proxy_base_url)


def validate_frozen_routes(
    role: AgentRole,
    selection: ModelSelection,
    policy: ModelPolicy,
    routes: tuple[ProviderRouteConfig, ...],
    *,
    proxy_base_url: str | None = None,
) -> None:
    """A claim selects the primary; only its exact policy can authorize fallback.

    An explicitly approved recovery scope may narrow the policy's routes. Settings
    changes may not silently add, reorder or change reasoning effort for a retained Run.
    Actual provider attempts remain in the existing immutable ModelRouteAttempt ledger.
    """
    if (selection.policy_id, selection.policy_version) != (policy.id, policy.version):
        raise QueueConflict("Worker route policy changed")
    role_policy = next((item for item in policy.role_routes if item.role is role), None)
    allowed = (
        tuple(policy.resolve_route_reference(reference) for reference in role_policy.routes)
        if role_policy is not None
        else policy.routes
    )
    actual = tuple(
        (
            item.provider,
            item.model,
            item.reasoning_effort,
            item.kind.value,
            (item.connection_mode or ("proxy" if proxy_base_url else "direct"))
            if item.kind.value == "codex_cli"
            else None,
        )
        for item in routes
    )
    keys = []
    for item in allowed:
        matches = tuple(
            candidate
            for candidate in actual
            if candidate[:2] == (item.provider, item.model)
            and (item.reasoning_effort is None or candidate[2] == item.reasoning_effort)
            and (item.route_kind is None or candidate[3] == item.route_kind)
            and (item.connection_mode is None or candidate[4] == item.connection_mode)
        )
        if len(matches) > 1:
            raise QueueConflict("Worker legacy route is ambiguous")
        if matches:
            keys.append(matches[0])
    primary = tuple(
        key
        for key in keys
        if key[:2] == (selection.provider, selection.model)
        and (selection.reasoning_effort is None or key[2] == selection.reasoning_effort)
        and (selection.route_kind is None or key[3] == selection.route_kind)
        and (selection.connection_mode is None or key[4] == selection.connection_mode)
    )
    if len(primary) != 1 or not actual or actual[0] != primary[0]:
        raise QueueConflict("Worker primary route does not match its claim")
    ordered = (primary[0], *(key for key in keys if key != primary[0]))
    if tuple(key for key in ordered if key in actual) != actual:
        raise QueueConflict("Worker fallback routes differ from the frozen policy")
