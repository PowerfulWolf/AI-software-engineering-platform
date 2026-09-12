"""Deterministic QA/Review remediation through a fresh serial delivery Task."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain import (
    AgentProfile,
    ExecutionPlan,
    ModelPolicy,
    ProjectRequest,
    Task,
    WorkItem,
    WorkItemStatus,
)
from ai_software_engineer.domain.project_delivery import derive_delivery_task
from ai_software_engineer.manager.dispatch import (
    ContinuationDispatchRecord,
    DispatchPhaseCommit,
    DispatchWorkforceSnapshot,
    _record_digest,
)
from ai_software_engineer.manager.mysql_dispatch_authority import MySqlDispatchAuthority
from ai_software_engineer.manager.preparation import PrepareProjectResult
from ai_software_engineer.manager.production_backend import (
    ProductionProjectDeliveryBackend,
    _clean_git_head,
    _maximum_risk,
)
from ai_software_engineer.planning import PlanningPreviewService
from ai_software_engineer.product import FileProductRecordStore
from ai_software_engineer.recovery.models import RecoveryRejected, digest
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.recovery.verification_entry import NativeVerificationFacts
from ai_software_engineer.recovery.verification_native import (
    NativeCandidateSource,
    NativeCandidateSourceReader,
)
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationCompletion,
    CandidateVerificationPlan,
)
from ai_software_engineer.redaction import redact_text
from ai_software_engineer.runtime_workspace import FileTeamWorkforceStore
from ai_software_engineer.scheduling import ModelRouter, PortfolioScheduler


@dataclass(frozen=True)
class CandidateRemediation:
    dispatch: ContinuationDispatchRecord
    preparation: PrepareProjectResult
    source: NativeCandidateSource
    context_sources: tuple[ContextSource, ...]


class CandidateRemediationService:
    """Route an independently rejected candidate back to Coder on current project facts."""

    def __init__(
        self,
        *,
        backend: ProductionProjectDeliveryBackend,
        config: ProductionConfig,
        environment: Mapping[str, str],
    ) -> None:
        # Keep this service behind TeamHost; callers never supply stores or authority.
        self._backend = backend
        self._config = config
        self._environment = dict(environment)

    def prepare(
        self,
        *,
        source: NativeCandidateSource,
        store: FileRecoveryStore,
        plan: CandidateVerificationPlan,
        completion: CandidateVerificationCompletion,
    ) -> CandidateRemediation:
        if completion.verified:
            raise RecoveryRejected("verified candidates do not require Coder remediation")
        self._validate_current(source, store, plan, completion)
        context_sources = remediation_context(
            repository_root=source.scope.repository_root,
            source_delivery_id=source.scope.delivery_id,
            source_base_revision=source.runtime.task.base_ref,
            candidate_revision=source.inputs.candidate_revision,
            plan=plan,
            completion=completion,
        )
        context_sha256 = digest([item.to_wire() for item in context_sources])
        preparation = self._backend.prepare(source.scope.repository_root)
        prepared = preparation.preparation
        if prepared is None:
            raise RecoveryRejected("project preparation needs human resolution before remediation")
        # The completion digest identifies this successor. Its sealed time keeps exact replay
        # deterministic even when the process stopped after allocation but before checkpointing.
        now = completion.completed_at
        original_request = source.stages.request
        rebound_request = ProjectRequest.create(
            request_id=original_request.id,
            repository_id=original_request.repository_id,
            preparation_sha256=prepared.preparation_sha256,
            title=original_request.title,
            original_request=original_request.original_request,
            status=original_request.status,
            created_at=original_request.created_at,
            updated_at=now,
        )
        task_id = f"task_continue_{completion.completion_sha256[:32]}"
        task = derive_delivery_task(
            prepared,
            rebound_request,
            source.stages.product,
            source.stages.approval,
            source.stages.design,
            source.stages.plan,
            task_id=task_id,
            repository=prepared.repository_root,
            base_ref=_clean_git_head(Path(prepared.repository_root)),
            max_attempts=source.runtime.task.max_attempts,
            created_at=now,
            constraints=source.runtime.task.constraints,
            owner=source.runtime.task.owner,
            labels=tuple(dict.fromkeys((*source.runtime.task.labels, "remediation"))),
        )
        source_dispatch_id = source.checkpoint.dispatch_commit_id
        if source_dispatch_id is None:
            raise RecoveryRejected("candidate source has no dispatch identity")
        task = Task.model_validate(
            {
                **task.to_wire(),
                "metadata": {
                    **task.metadata,
                    "continuation_kind": "verification_remediation",
                    "continuation_sha256": completion.completion_sha256,
                    "continuation_plan_sha256": plan.plan_sha256,
                    "continuation_context_sha256": context_sha256,
                    "continuation_target_preparation_sha256": (prepared.preparation_sha256),
                    "continuation_of_delivery_id": source.scope.delivery_id,
                    "continuation_of_task_id": source.inputs.task_id,
                    "continuation_source_base_revision": source.runtime.task.base_ref,
                    "continuation_source_revision": source.inputs.candidate_revision,
                    "continuation_source_dispatch_id": source_dispatch_id,
                },
            }
        )
        agents, policy = self._backend._workforce()
        workforce = FileTeamWorkforceStore(self._backend._organization)
        saved_agents = tuple(workforce.put_agent(agent) for agent in agents)
        saved_policy = workforce.put_policy(policy, versioned=True)
        sidecar = Path(prepared.repository_workspace_root)
        authority = MySqlDispatchAuthority(
            self._config.require_mysql_dsn(self._environment),
            request_revisions=FileProductRecordStore(sidecar / "state/product"),
            planner_records=self._backend._facts(preparation).planning,
        )
        snapshot = _snapshot(
            task,
            source.stages.plan,
            prepared.repository_id,
            saved_agents,
            (saved_policy,),
        )
        authority.seed_snapshot(snapshot)

        def validate(existing: ContinuationDispatchRecord | None) -> None:
            self._validate_current(source, store, plan, completion)
            if existing is not None and (
                existing.task != task
                or existing.continuation_sha256 != completion.completion_sha256
                or existing.continuation_plan_sha256 != plan.plan_sha256
                or existing.continuation_context_sha256 != context_sha256
                or existing.target_preparation_sha256 != prepared.preparation_sha256
                or existing.source_delivery_id != source.scope.delivery_id
                or existing.source_task_id != source.inputs.task_id
                or existing.source_base_revision != source.runtime.task.base_ref
                or existing.source_revision != source.inputs.candidate_revision
                or existing.source_dispatch_id != source_dispatch_id
            ):
                raise RecoveryRejected("remediation dispatch differs from current delivery facts")

        def build(current: DispatchWorkforceSnapshot) -> ContinuationDispatchRecord:
            preview = PlanningPreviewService(
                scheduler=PortfolioScheduler(),
                model_router=ModelRouter(
                    route_context_capacities={
                        (route.provider, route.model): 2_000_000
                        for model_policy in current.model_policies
                        for route in model_policy.routes
                    }
                ),
            ).preview(
                task=task,
                work_item=current.work_item,
                execution_plan=source.stages.plan,
                agents=current.agents,
                active_leases=current.active_leases,
                assignments=current.assignments,
                policies=current.model_policies,
                previewed_at=now,
            )
            phases: list[DispatchPhaseCommit] = []
            for phase in preview.phases:
                assignment = phase.assignment_decision
                routing = phase.model_routing_decision
                if (
                    assignment.agent_id is None
                    or assignment.assignment is None
                    or assignment.lease is None
                    or routing is None
                    or routing.selection is None
                ):
                    raise RecoveryRejected(
                        f"no current {phase.role.value} Agent/model for remediation"
                    )
                phases.append(
                    DispatchPhaseCommit(
                        phase_id=phase.phase_id,
                        role=phase.role,
                        agent_id=assignment.agent_id,
                        assignment=assignment.assignment,
                        lease=assignment.lease,
                        model_selection=routing.selection,
                    )
                )
            if len(phases) != 3 or len(source.stages.plan.phases) != 3:
                raise RecoveryRejected("remediation requires exactly three serial phases")
            phase_commits = (phases[0], phases[1], phases[2])
            plan_phases = source.stages.plan.phases
            phase_ids = (plan_phases[0].id, plan_phases[1].id, plan_phases[2].id)
            value = ContinuationDispatchRecord(
                id=f"dispatch_commit_{completion.completion_sha256}",
                repository_id=prepared.repository_id,
                task_id=task.id,
                project_request_id=rebound_request.id,
                execution_plan_id=source.stages.plan.id,
                execution_plan_sha256=source.stages.plan.execution_plan_sha256,
                execution_plan_phase_ids=phase_ids,
                continuation_kind="verification_remediation",
                continuation_sha256=completion.completion_sha256,
                continuation_plan_sha256=plan.plan_sha256,
                continuation_context_sha256=context_sha256,
                target_preparation_sha256=prepared.preparation_sha256,
                source_delivery_id=source.scope.delivery_id,
                source_task_id=source.inputs.task_id,
                source_base_revision=source.runtime.task.base_ref,
                source_revision=source.inputs.candidate_revision,
                source_dispatch_id=source_dispatch_id,
                workforce_snapshot_sha256=current.snapshot_sha256,
                task=task,
                phases=phase_commits,
                committed_at=now,
                dispatch_sha256="0" * 64,
            )
            return value.model_copy(update={"dispatch_sha256": _record_digest(value)})

        dispatch = authority.commit_continuation(
            repository_id=prepared.repository_id,
            task_id=task.id,
            continuation_sha256=completion.completion_sha256,
            validate_current=validate,
            build=build,
        )
        return CandidateRemediation(
            dispatch=dispatch,
            preparation=preparation,
            source=source,
            context_sources=context_sources,
        )

    def _validate_current(
        self,
        source: NativeCandidateSource,
        store: FileRecoveryStore,
        plan: CandidateVerificationPlan,
        completion: CandidateVerificationCompletion,
    ) -> None:
        current = NativeCandidateSourceReader(self._config, self._environment).inspect(source.scope)
        NativeVerificationFacts(self._config, self._environment, store=store).validate(plan)
        if (
            current != source
            or store.get_verification_completion(plan.plan_sha256) != completion
            or completion.plan_sha256 != plan.plan_sha256
        ):
            raise RecoveryRejected("candidate remediation facts changed")


def _snapshot(
    task: Task,
    plan: ExecutionPlan,
    repository_id: str,
    agents: tuple[AgentProfile, ...],
    policies: tuple[ModelPolicy, ...],
) -> DispatchWorkforceSnapshot:
    phases = plan.phases
    return DispatchWorkforceSnapshot.create(
        repository_id=repository_id,
        task_id=task.id,
        work_item=WorkItem(
            repository_id=repository_id,
            task_id=task.id,
            status=WorkItemStatus.READY,
            priority=500,
            risk=_maximum_risk(phase.risk for phase in phases),
            required_capabilities=tuple(
                sorted(
                    {capability for phase in phases for capability in phase.required_capabilities}
                )
            ),
            created_at=task.created_at,
            updated_at=task.created_at,
        ),
        agents=agents,
        model_policies=policies,
    )


def remediation_context(
    *,
    repository_root: str,
    source_delivery_id: str,
    source_base_revision: str,
    candidate_revision: str,
    plan: CandidateVerificationPlan,
    completion: CandidateVerificationCompletion,
) -> tuple[ContextSource, ...]:
    process = subprocess.run(
        (
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--unified=3",
            f"{source_base_revision}..{candidate_revision}",
            "--",
        ),
        cwd=repository_root,
        env={"PATH": os.defpath, "LANG": "C", "LC_ALL": "C"},
        capture_output=True,
        timeout=30,
        check=False,
    )
    if process.returncode != 0 or len(process.stdout) > 1_000_000:
        raise RecoveryRejected("candidate patch is unavailable or exceeds the remediation limit")
    try:
        patch = process.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RecoveryRejected("candidate remediation supports UTF-8 text changes only") from error
    if not patch:
        raise RecoveryRejected("candidate remediation has no candidate changes to preserve")
    if redact_text(patch).occurrences:
        raise RecoveryRejected("candidate patch contains sensitive content")
    report = json.dumps(completion.to_wire(), ensure_ascii=False, sort_keys=True)
    return (
        ContextSource(
            source_id="remediation.verification",
            uri=(f"candidate-verification://{source_delivery_id}/{completion.completion_sha256}"),
            content=report,
            priority=2,
            required=True,
        ),
        ContextSource(
            source_id="remediation.candidate_patch",
            uri=(
                f"candidate://{candidate_revision}/"
                f"{digest({'plan': plan.plan_sha256, 'patch': patch})}"
            ),
            content=patch,
            priority=3,
            required=True,
        ),
    )
