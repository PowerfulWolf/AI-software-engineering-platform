"""Production composition for approved QA/Reviewer continuation of one candidate."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping, Set
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from ai_software_engineer.agents import StoredContextResolver
from ai_software_engineer.agents.candidate_binding import candidate_read_scope
from ai_software_engineer.agents.candidate_source import candidate_review_snapshot
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context import ContextSource, FileContextStore
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentRole,
    TeamRole,
    WorkItem,
    WorkItemStatus,
)
from ai_software_engineer.domain.artifact import QaReportArtifact, classify_qa_failure
from ai_software_engineer.domain.enums import QaFailureDisposition, QaReportStatus
from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.knowledge.administration import list_gap_views
from ai_software_engineer.knowledge.gaps import KnowledgeResolution
from ai_software_engineer.manager.delivery_checkpoint import (
    FileProjectDeliveryCheckpointStore,
    checkpoint_sha256_is_ancestor,
)
from ai_software_engineer.manager.dispatch import (
    DispatchPhaseCommit,
    DispatchWorkforceSnapshot,
    VerificationReservation,
)
from ai_software_engineer.manager.model_execution import ManagerModelExecutor
from ai_software_engineer.manager.model_store import MySqlManagerRecordStore
from ai_software_engineer.manager.mysql_dispatch_authority import MySqlDispatchAuthority
from ai_software_engineer.manager.native_ui import (
    NativeUiScenario,
    NativeUiSessionPrerequisite,
    native_ui_capability,
    probe_native_ui_session,
)
from ai_software_engineer.manager.production_backend import (
    PRODUCTION_DELIVERY_CONTEXT_BUDGET,
    ProductionProjectDeliveryBackend,
    _agent_definitions,
    _delivery_role_permissions,
    _task_commands,
)
from ai_software_engineer.manager.production_delivery import (
    ConfiguredDeliveryRouteAdapterFactory,
    DeliveryRouteAdapterFactory,
    DispatchDeliveryAgentAdapter,
)
from ai_software_engineer.manager.team_roster import production_team_roster
from ai_software_engineer.manager.verification_coordination import (
    ManagerVerificationAdvice,
    VerificationFailureReference,
    coordinate_verification,
    coordination_digest,
)
from ai_software_engineer.manager.verification_environment import (
    SwiftSandboxCapability,
    discover_swift_sandbox_capability,
)
from ai_software_engineer.orchestration import FileRunContextBuilder
from ai_software_engineer.planning import FileExecutionPlanStore
from ai_software_engineer.planning.preview import derive_phase_demands
from ai_software_engineer.product import FileProductRecordStore
from ai_software_engineer.recovery.models import (
    RecoveryApprovalCommand,
    RecoveryRejected,
    RecoveryScope,
    digest,
)
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.verification import (
    CandidateVerificationRunner,
)
from ai_software_engineer.recovery.verification_admission import (
    CandidateVerificationAdmission,
    ExplicitVerificationHuman,
    VerificationFacts,
)
from ai_software_engineer.recovery.verification_native import (
    NativeCandidateSource,
    NativeCandidateSourceReader,
)
from ai_software_engineer.recovery.verification_qa import (
    select_retained_qa,
    validate_retained_qa_artifacts,
)
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationCompletion,
    CandidateVerificationDisposition,
    CandidateVerificationInputs,
    CandidateVerificationPlan,
    PriorVisualEvidence,
    VerificationExecutionRecord,
    verification_inputs_are_current,
)
from ai_software_engineer.redaction import redact_text
from ai_software_engineer.repository_profile import RepositoryProfile
from ai_software_engineer.runtime_workspace import load_repository_profile
from ai_software_engineer.scheduling import ModelRouter, PortfolioScheduler
from ai_software_engineer.scheduling.models import (
    AssignmentDecisionStatus,
    ModelRoutingDecisionStatus,
)
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.swift_verification import SWIFT_VERIFICATION_COMMANDS
from ai_software_engineer.team_workspace import TeamWorkspace, _read_regular, _reject_symlinks


def verification_store_root(source: NativeCandidateSource) -> Path:
    return (
        Path(source.stages.preparation.repository_workspace_root)
        / "state"
        / f"candidate-verification-{source.scope.delivery_id}"
    )


def _manager_executor(
    config: ProductionConfig,
    environment: Mapping[str, str],
    source: NativeCandidateSource,
) -> ManagerModelExecutor:
    from ai_software_engineer.manager.model_execution import (
        ManagerModelExecutor,
        ManagerRunScope,
        MySqlManagerClaimAuthority,
    )

    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name, read_only=True
    )
    project, _ = team.project_registry().locate_repository(source.scope.repository_id)
    return ManagerModelExecutor(
        root=team.directory("work-items") / "manager-model-runs",
        scope=ManagerRunScope(
            team_id=config.team_id,
            project_id=project.manifest.project_id,
            requirement_id=source.parent_delivery_id or source.scope.delivery_id,
            stage="VERIFICATION:" + source.scope.repository_id,
        ),
        authority=MySqlManagerClaimAuthority(config.require_mysql_dsn(environment)),
        retry_policy=config.execution_retry_policy.manager,
        time_policy=config.execution_retry_policy.execution_time.manager,
        store=MySqlManagerRecordStore(config.require_mysql_dsn(environment), config.team_id),
    )


def _manager_resolutions(
    config: ProductionConfig, source: NativeCandidateSource
) -> tuple[KnowledgeResolution, ...]:
    """Reuse approved Requirement decisions; never invent operator authority in prompts."""
    if source.parent_delivery_id is None:
        return ()
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name, read_only=True
    )
    project, _ = team.project_registry().locate_repository(source.scope.repository_id)
    views = list_gap_views(project, source.parent_delivery_id)
    return tuple(view.resolution for view in views if view.resolution is not None)


def open_candidate_verification_plan(
    config: ProductionConfig,
    environment: Mapping[str, str],
    path: Path,
) -> tuple[FileRecoveryStore, CandidateVerificationPlan]:
    """Open one exact verification plan without initializing the Team Host or database schema."""
    _reject_symlinks(path)
    envelope = json.loads(_read_regular(path, 8_000_000))
    plan = CandidateVerificationPlan.model_validate(envelope["record"])
    source = NativeCandidateSourceReader(config, environment).inspect(plan.scope)
    expected = verification_store_root(source) / f"verification-plan-{plan.plan_sha256}.json"
    if path != expected or plan.scope.team_id != config.team_id:
        raise RecoveryRejected("verification plan is outside its scoped store")
    store = FileRecoveryStore(path.parent, scope=plan.scope)
    return store, store.get_verification_plan(plan.plan_sha256)


def _policy_sha(definitions: Mapping[AgentRole, AgentDefinition], config: ProductionConfig) -> str:
    return digest(
        {
            "definitions": {
                role.value: value.to_wire()
                for role, value in sorted(definitions.items(), key=lambda x: x[0].value)
            },
            "enabled_routes": [route.to_wire() for route in config.enabled_routes()],
            "model_policy": production_team_roster(config)[1].to_wire(),
        }
    )


def _stage_sha(source: NativeCandidateSource) -> str:
    return digest(
        {
            "preparation": source.stages.preparation.to_wire(),
            "product": source.stages.product.to_wire(),
            "approval": source.stages.approval.to_wire(),
            "design": source.stages.design.to_wire(),
            "plan": source.stages.plan.to_wire(),
        }
    )


def _verification_inputs_are_current(
    approved: CandidateVerificationInputs,
    current: CandidateVerificationInputs,
    admitted_run_ids: Set[str],
) -> bool:
    """Compatibility seam for the verification-facts contract and its focused tests."""
    return verification_inputs_are_current(approved, current, admitted_run_ids)


def _verification_allocation(
    source: NativeCandidateSource,
    snapshot: DispatchWorkforceSnapshot,
    *,
    config: ProductionConfig,
    execution_task_id: str,
    plan_sha256: str,
    now: datetime,
) -> VerificationReservation:
    # The source Task snapshot retains its original policy even after Settings restart.
    # A newly approved run uses today's policy; occupancy and Agent history stay fenced.
    _, policy = production_team_roster(config)
    scheduler = PortfolioScheduler()
    router = ModelRouter(
        route_context_capacities={
            (route.provider, route.model): 2_000_000 for route in policy.routes
        }
    )
    demands = derive_phase_demands(source.runtime.task, source.stages.plan)
    phases = []
    leases, assignments = tuple(snapshot.active_leases), tuple(snapshot.assignments)
    profiles = {agent.id: agent for agent in snapshot.agents}
    for phase, demand in zip(source.stages.plan.phases[1:], demands[1:], strict=True):
        item = WorkItem(
            task_id=execution_task_id,
            repository_id=source.scope.repository_id,
            status=WorkItemStatus.READY,
            priority=500,
            risk=phase.risk,
            required_capabilities=phase.required_capabilities,
            created_at=now,
            updated_at=now,
        )
        decision = scheduler.match(
            item,
            phase.role,
            snapshot.agents,
            leases,
            assignments,
            now=now,
            attempt=1,
            work_items=(item,),
        )
        if decision.status is not AssignmentDecisionStatus.ASSIGNED:
            raise RecoveryRejected(f"no available {phase.role.value} Agent")
        assert decision.agent_id and decision.assignment and decision.lease
        profile = profiles[decision.agent_id]
        routing = router.route(
            demand.model_copy(update={"task_id": execution_task_id}),
            profile,
            policy,
            now=now,
        )
        if routing.status is not ModelRoutingDecisionStatus.SELECTED or routing.selection is None:
            raise RecoveryRejected(f"no approved {phase.role.value} model")
        phases.append(
            DispatchPhaseCommit(
                phase_id=phase.id,
                role=phase.role,
                agent_id=profile.id,
                assignment=decision.assignment,
                lease=decision.lease,
                model_selection=routing.selection,
            )
        )
        assignments = (*assignments, decision.assignment)
        leases = (*leases, decision.lease)
    return VerificationReservation(
        plan_sha256=plan_sha256,
        repository_id=source.scope.repository_id,
        source_task_id=source.inputs.task_id,
        task_id=execution_task_id,
        workforce_snapshot_sha256=snapshot.snapshot_sha256,
        phases=tuple(phases),
        committed_at=now,
    )


def _definitions(
    source: NativeCandidateSource, reservation: VerificationReservation
) -> dict[AgentRole, AgentDefinition]:
    profile = load_repository_profile(
        Path(source.stages.preparation.repository_workspace_root),
        source.stages.preparation.repository_profile_sha256,
    )
    commands = _task_commands(profile)
    verification_commands = _verification_task_commands(source, profile)
    result = _agent_definitions(source.runtime.dispatch, commands)
    allowed = (
        source.runtime.task.constraints.allowed_paths if source.runtime.task.constraints else ()
    )
    for phase in reservation.phases:
        previous = result[phase.role]
        result[phase.role] = previous.model_copy(
            update={
                "id": phase.agent_id,
                "provider": phase.model_selection.provider,
                "model": phase.model_selection.model,
                "reasoning_effort": phase.model_selection.reasoning_effort,
                "route_kind": phase.model_selection.route_kind,
                "connection_mode": phase.model_selection.connection_mode,
                "permissions": _delivery_role_permissions(
                    phase.role, allowed, verification_commands
                ),
            }
        )
    return result


def _verification_task_commands(
    source: NativeCandidateSource, profile: RepositoryProfile
) -> tuple[str, ...]:
    """Derive a candidate-bound verification capability without rewriting history.

    Existing Tasks keep their frozen RepositoryProfile and command policy.  A newly
    proposed verification plan may add a narrowly detected Swift Package capability
    when the approved candidate itself contains Package.swift; the exact expanded
    commands are then sealed in its AgentDefinitions and policy digest.
    """
    commands = set(_task_commands(profile))
    completed = subprocess.run(
        (
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "ls-tree",
            source.inputs.candidate_revision,
            "--",
            "Package.swift",
        ),
        cwd=source.scope.repository_root,
        env={
            "PATH": os.environ.get("PATH", os.defpath),
            "LANG": "C",
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise RecoveryRejected("cannot inspect candidate Swift package marker")
    # Git tree mode rejects symlinks/directories/submodules named Package.swift.
    if completed.stdout.startswith(("100644 blob ", "100755 blob ")) and completed.stdout.endswith(
        "\tPackage.swift\n"
    ):
        commands.update(SWIFT_VERIFICATION_COMMANDS)
    return tuple(sorted(commands))


def _verification_context(plan: CandidateVerificationPlan) -> ContextSource:
    return ContextSource(
        source_id="verification.approved_plan",
        uri=f"verification://{plan.plan_sha256}",
        roles=(AgentRole.QA, AgentRole.REVIEWER),
        priority=20,
        required=True,
        content=json.dumps(
            {
                "plan_sha256": plan.plan_sha256,
                "candidate_revision": plan.inputs.candidate_revision,
                "retained_qa": {
                    "plan_sha256": plan.retained_qa.plan_sha256,
                    "qa_invocation_sha256": plan.retained_qa.qa_invocation_sha256,
                    "reviewer_invocation_sha256": plan.retained_qa.reviewer_invocation_sha256,
                    "artifact_id": plan.retained_qa.qa.artifact_id,
                    "artifact_sha256": plan.retained_qa.qa.integrity.sha256,
                    "meaning": (
                        "Reuse sealed QA PASS; execute only a fresh independent Reviewer. "
                        "No Task event or prior Review verdict is inferred."
                    ),
                }
                if plan.retained_qa is not None
                else None,
                "executor_capability": plan.executor_capability.to_wire()
                if plan.executor_capability
                else None,
                "prerequisite_incident_sha256": plan.prerequisite_incident_sha256,
                "prior_visual_evidence": plan.prior_visual_evidence.to_wire()
                if plan.prior_visual_evidence
                else None,
                "manager_advice": plan.manager_advice.to_wire() if plan.manager_advice else None,
                "verification_commands": {
                    definition.role.value: definition.permissions.commands
                    for definition in plan.definitions
                    if definition.role in {AgentRole.QA, AgentRole.REVIEWER}
                },
                "scope": (
                    "This independently approved verification plan supplies the current run's "
                    "policy://permissions. The original Task and its old command list are "
                    "immutable historical facts. Candidate, acceptance criteria and denied paths "
                    "are unchanged. Execute only in the candidate worktree. Do not install "
                    "dependencies/toolchains, disable sandboxes, sign, publish or merge. "
                    "Build/static checks do not establish manual UI or accessibility acceptance. "
                    "If required tooling or UI test data is missing, report NOT_TESTED/ERROR "
                    "with evidence, never a fabricated PASS."
                    " If this plan includes codex_sandbox_swiftpm_v1, the trusted executor "
                    "will separately supply build/XCTest receipts under a retained readonly "
                    "outer sandbox and isolated writable scratch. Only that executor may "
                    "disable SwiftPM's inner sandbox. No model tool gains this option. "
                    "These receipts are not UI evidence or a verdict."
                ),
            },
            sort_keys=True,
        ),
    )


def _available_prior_visual_evidence(
    store: FileRecoveryStore,
    inputs: CandidateVerificationInputs,
    completion: CandidateVerificationCompletion | None,
) -> VerificationExecutionRecord | None:
    """Only the immediate inconclusive completion can supply inherited QA observations."""
    if completion is None or (
        completion.qa.task_id != inputs.task_id
        or completion.qa.source_revision != inputs.candidate_revision
        or completion.disposition is not CandidateVerificationDisposition.RETRY_VERIFICATION
        or completion.qa_invocation_sha256 is None
    ):
        return None
    source = store.get_verification_plan(completion.plan_sha256)
    if (
        source.inputs.model_copy(
            update={
                "prior_run_ids": inputs.prior_run_ids,
            }
        )
        != inputs
    ):
        return None
    try:
        receipt = store.get_verification_execution(
            completion.plan_sha256, AgentRole.QA, completed=True
        )
    except RecoveryRecordMissing:
        return None
    if (
        receipt.phase != "COMPLETED"
        or receipt.effective_failure_code is not None
        or receipt.invocation_sha256 != completion.qa_invocation_sha256
        or not any(result.output.capture is not None for result in receipt.ui_results or ())
    ):
        return None
    return receipt


class NativeVerificationFacts(VerificationFacts):
    def __init__(
        self,
        config: ProductionConfig,
        environment: Mapping[str, str],
        *,
        store: FileRecoveryStore | None = None,
    ) -> None:
        self.config, self.environment, self.store = config, dict(environment), store

    def _admitted_run_ids(self, plan: CandidateVerificationPlan) -> set[str]:
        if self.store is None:
            return set()
        result: set[str] = set()
        for role in (AgentRole.QA, AgentRole.REVIEWER):
            try:
                invocation = self.store.get_verification_invocation(plan.plan_sha256, role)
            except RecoveryRecordMissing:
                continue
            result.add(invocation.request.run_id)
        return result

    def validate(self, plan: CandidateVerificationPlan) -> None:
        source = NativeCandidateSourceReader(self.config, self.environment).inspect(plan.scope)
        if self.store is not None:
            validate_retained_qa_artifacts(
                self.store,
                plan,
                FileArtifactStore(
                    Path(source.stages.preparation.repository_workspace_root) / "artifacts",
                    read_only=True,
                ),
            )
        checkpoint_history = FileProjectDeliveryCheckpointStore(
            Path(source.stages.preparation.repository_workspace_root) / "state/project-deliveries",
            read_only=True,
        ).list(source.scope.delivery_id)
        if (
            not _verification_inputs_are_current(
                plan.inputs, source.inputs, self._admitted_run_ids(plan)
            )
            or not checkpoint_history
            or checkpoint_history[-1] != source.terminal_checkpoint
            or not checkpoint_sha256_is_ancestor(checkpoint_history, plan.native_checkpoint_sha256)
            or source.runtime.dispatch.dispatch_sha256 != plan.dispatch_sha256
            or _stage_sha(source) != plan.approved_stage_chain_sha256
            or source.parent_delivery_id != plan.parent_delivery_id
            or source.parent_checkpoint_sha256 != plan.parent_checkpoint_sha256
        ):
            raise RecoveryRejected("verification source changed after proposal")
        manager = GitWorktreeManager(
            source.scope.repository_root,
            Path(self.config.platform_root) / "worktrees" / source.scope.repository_id,
        )
        manager._validate_repository()
        if (
            manager._run_git(
                ("rev-parse", f"{source.inputs.candidate_revision}^{{commit}}"),
                cwd=Path(source.scope.repository_root),
            )
            != source.inputs.candidate_revision
        ):
            raise RecoveryRejected("approved candidate commit is unavailable")
        current = {d.role: d for d in plan.definitions}
        if _policy_sha(current, self.config) != plan.current_policy_sha256:
            raise RecoveryRejected("approved verifier policy digest changed")
        # Unstarted plans must reflect today's candidate-derived capabilities. An
        # already admitted run/completion remains a historical fact: changing the
        # policy must not invalidate its sealed QA/Review evidence or lineage.
        if not self._admitted_run_ids(plan):
            profile = load_repository_profile(
                Path(source.stages.preparation.repository_workspace_root),
                source.stages.preparation.repository_profile_sha256,
            )
            commands = _verification_task_commands(source, profile)
            if plan.executor_capability != _executor_capability(commands, self.config):
                raise RecoveryRejected("verification executor capability changed; repropose")
            if plan.native_ui is not None and plan.native_ui != native_ui_capability(
                plan.native_ui.scenario
            ):
                raise RecoveryRejected("native UI capability changed; repropose")
            allowed = (
                source.runtime.task.constraints.allowed_paths
                if source.runtime.task.constraints
                else ()
            )
            for role in (AgentRole.QA, AgentRole.REVIEWER):
                if current[role].permissions != _delivery_role_permissions(role, allowed, commands):
                    raise RecoveryRejected("candidate verification permissions changed; repropose")


def _executor_capability(
    commands: tuple[str, ...], config: ProductionConfig
) -> SwiftSandboxCapability | None:
    if not set(SWIFT_VERIFICATION_COMMANDS) <= set(commands):
        return None
    return discover_swift_sandbox_capability(config.codex_executable)


class CandidateVerificationEntry:
    def __init__(
        self,
        config: ProductionConfig,
        environment: Mapping[str, str],
        backend: ProductionProjectDeliveryBackend,
    ) -> None:
        self.config, self.environment, self.backend = config, dict(environment), backend
        self._route_factory = backend._delivery_route_adapters

    def open_plan(self, path: Path) -> tuple[FileRecoveryStore, CandidateVerificationPlan]:
        """Open one exact persisted verification-plan envelope through its scoped store."""
        return open_candidate_verification_plan(self.config, self.environment, path)

    def _authority(self, source: NativeCandidateSource) -> MySqlDispatchAuthority:
        sidecar = Path(source.stages.preparation.repository_workspace_root)
        return MySqlDispatchAuthority(
            self.config.require_mysql_dsn(self.environment),
            request_revisions=FileProductRecordStore(sidecar / "state/product"),
            planner_records=FileExecutionPlanStore(sidecar / "state/planning"),
        )

    def propose_project(
        self,
        *,
        repository_root: str,
        delivery_id: str,
        native_ui_scenario: NativeUiScenario | None = None,
        manager_advice: ManagerVerificationAdvice | None = None,
    ) -> tuple[CandidateVerificationPlan, Path]:
        """Resolve the registered project and propose verification without invoking a model."""
        prepared = self.backend.prepare(repository_root).preparation
        if prepared is None:
            raise RecoveryRejected("project preparation needs human resolution")
        return self.propose(
            RecoveryScope(
                team_id=self.config.team_id,
                repository_id=prepared.repository_id,
                repository_root=prepared.repository_root,
                delivery_id=delivery_id,
            ),
            native_ui_scenario=native_ui_scenario,
            manager_advice=manager_advice,
        )

    def latest_project(
        self, *, repository_root: str, delivery_id: str
    ) -> tuple[FileRecoveryStore, CandidateVerificationPlan, Path] | None:
        """Return the newest sealed plan for the current terminal candidate, if any."""
        prepared = self.backend.prepare(repository_root).preparation
        if prepared is None:
            raise RecoveryRejected("project preparation needs human resolution")
        scope = RecoveryScope(
            team_id=self.config.team_id,
            repository_id=prepared.repository_id,
            repository_root=prepared.repository_root,
            delivery_id=delivery_id,
        )
        source = NativeCandidateSourceReader(self.config, self.environment).inspect(scope)
        root = verification_store_root(source)
        if not root.exists():
            return None
        store = FileRecoveryStore(root, scope=scope)
        plans: list[tuple[CandidateVerificationPlan, Path]] = []
        for path in sorted(root.glob("verification-plan-*.json")):
            _reject_symlinks(path)
            prefix, suffix = "verification-plan-", ".json"
            plan_sha256 = path.name.removeprefix(prefix).removesuffix(suffix)
            if path.name != f"{prefix}{plan_sha256}{suffix}":
                raise RecoveryRejected("candidate verification plan path is malformed")
            plan = store.get_verification_plan(plan_sha256)
            if plan.scope != scope:
                raise RecoveryRejected("candidate verification plan scope drifted")
            try:
                NativeVerificationFacts(self.config, self.environment, store=store).validate(plan)
            except RecoveryRejected:
                continue
            plans.append((plan, path))
        if not plans:
            return None
        plan, path = max(plans, key=lambda item: (item[0].created_at, item[0].plan_sha256))
        return store, plan, path

    def coordinate(self, plan: CandidateVerificationPlan) -> ManagerVerificationAdvice | None:
        """Own missing verification prerequisites before requesting another approval.

        A cached exact-input decision is reused across process restarts. This does
        not run a candidate, approve a plan or mutate the failed QA artifact.
        """
        source = NativeCandidateSourceReader(self.config, self.environment).inspect(plan.scope)
        store = FileRecoveryStore(verification_store_root(source), scope=plan.scope)
        admitted = NativeVerificationFacts(
            self.config, self.environment, store=store
        )._admitted_run_ids(plan)
        if not _verification_inputs_are_current(plan.inputs, source.inputs, admitted):
            raise RecoveryRejected("Manager coordination source changed")
        artifacts = FileArtifactStore(
            Path(source.stages.preparation.repository_workspace_root) / "artifacts", read_only=True
        )
        reports: list[QaReportArtifact] = []
        for event in source.runtime.events:
            for artifact_id in event.artifact_ids:
                artifact = artifacts.get(artifact_id)
                if (
                    isinstance(artifact, QaReportArtifact)
                    and artifact.source_revision == plan.inputs.candidate_revision
                ):
                    reports.append(artifact)
        execution = store.latest_verification_execution(plan)
        failed_execution = (
            execution
            if execution is not None and execution.effective_failure_code is not None
            else None
        )
        if failed_execution is None and (
            (plan.native_ui is not None and plan.manager_advice is None)
            or plan.reused_qa is not None
        ):
            return None
        completion = store.latest_verification_completion()
        if (
            completion is not None
            and completion.qa.source_revision == plan.inputs.candidate_revision
        ):
            reports.append(completion.qa)
        # Native events are ordered by their durable revisions; independent verification
        # happens after that terminal history. A model-authored created_at is not a clock
        # for execution order and must not let an old report hide the new completion.
        qa = reports[-1] if reports else None
        if failed_execution is None and (
            qa is None
            or qa.content.status is not QaReportStatus.FAIL
            or classify_qa_failure(qa.content) is not QaFailureDisposition.RETRY_VERIFICATION
        ):
            return None
        qa_definition = next(value for value in plan.definitions if value.role is AgentRole.QA)
        snapshot = candidate_review_snapshot(
            Path(plan.scope.repository_root),
            candidate_read_scope(
                source.runtime.task,
                artifacts.get(plan.inputs.plan_id),
                artifacts.get(plan.inputs.implementation_id),
                plan.inputs.candidate_revision,
            ),
            qa_definition.permissions,
        )
        resolutions = _manager_resolutions(self.config, source)
        previous_ui = (
            store.get_verification_plan(completion.plan_sha256).native_ui
            if completion is not None
            and completion.qa.source_revision == plan.inputs.candidate_revision
            else None
        )
        failure_reference = None
        environment_prerequisite = None
        failure_details: dict[str, object] | None = None
        if failed_execution is not None:
            previous_ui = failed_execution.native_ui
            failure_reference = VerificationFailureReference(
                plan_sha256=failed_execution.plan_sha256,
                record_sha256=failed_execution.record_sha256,
                role=failed_execution.role,
            )
            last_ui = failed_execution.ui_results[-1] if failed_execution.ui_results else None
            session_status = (
                "SESSION_LOCKED"
                if failed_execution.effective_failure_code == "NATIVE_UI_SESSION_LOCKED"
                else last_ui.output.error
                if last_ui
                else None
            )
            if session_status in {"SESSION_LOCKED", "SESSION_UNAVAILABLE"}:
                environment_prerequisite = NativeUiSessionPrerequisite.model_validate(
                    {
                        "observed_status": session_status,
                        "current_session": probe_native_ui_session(plan.executor_capability),
                    }
                )
            failure_details = {
                "reference": failure_reference.to_wire(),
                "failure_code": failed_execution.effective_failure_code,
                "recorded_phase": failed_execution.phase,
                "recorded_failure_code": failed_execution.failure_code,
                "commands": [
                    {"returncode": result.returncode, "duration_ms": result.duration_ms}
                    for result in failed_execution.results
                ],
                "failed_ui_step": last_ui.step.to_wire() if last_ui else None,
                "ui_error": last_ui.output.error if last_ui else None,
                "ui_diagnostics": last_ui.output.diagnostics.to_wire()
                if last_ui and last_ui.output.diagnostics
                else None,
                "ui_diagnostic": redact_text(last_ui.output.diagnostic or "").text[:2000]
                if last_ui
                else None,
                "completed_ui_steps": max(0, len(failed_execution.ui_results or ()) - 1),
                "no_verdict": True,
                "observed_ui_controls": [
                    {
                        "path": node.path[:100],
                        "attributes": {
                            key: redact_text(value).text[:200]
                            for key, value in node.attributes.items()
                            if key
                            in {
                                "AXRole",
                                "AXIdentifier",
                                "AXTitle",
                                "AXDescription",
                                "AXValue",
                                "AXEnabled",
                            }
                        },
                    }
                    for node in (last_ui.output.nodes if last_ui else ())
                    if node.attributes.get("AXRole") in {"AXButton", "AXCheckBox", "AXLink"}
                ][:40],
                "observed_ui_controls_truncated": sum(
                    node.attributes.get("AXRole") in {"AXButton", "AXCheckBox", "AXLink"}
                    for node in (last_ui.output.nodes if last_ui else ())
                )
                > 40,
                "environment_prerequisite": {
                    **environment_prerequisite.to_wire(),
                    "next_action": environment_prerequisite.next_action,
                }
                if environment_prerequisite
                else None,
            }
        prior_visual = _available_prior_visual_evidence(store, plan.inputs, completion)
        payload: dict[str, object] = {
            "contract_version": "manager_verification_coordination_v9",
            "scope": plan.scope.to_wire(),
            "candidate": plan.inputs.candidate_revision,
            "source_inputs": source.inputs.to_wire(),
            "native_checkpoint": plan.native_checkpoint_sha256,
            "parent_checkpoint": plan.parent_checkpoint_sha256,
            "acceptance_criteria": [
                value.to_wire() for value in source.runtime.task.acceptance_criteria
            ],
            "qa": qa.to_wire() if qa else None,
            "available_prior_visual_evidence": {
                "plan_sha256": prior_visual.plan_sha256,
                "record_sha256": prior_visual.record_sha256,
                "role": "historical_qa",
                "delivery": "actual PNG attachments after fresh exact plan approval; no recapture",
                "captures": [
                    {"step": item.step.name, "sha256": item.output.capture.image.sha256}
                    for item in prior_visual.ui_results or ()
                    if item.output.capture is not None
                ],
            }
            if prior_visual
            else None,
            "latest_execution_failure": failure_details,
            "approved_knowledge_resolutions": [value.to_wire() for value in resolutions],
            "candidate_source": snapshot,
            "available_build_capability": plan.executor_capability.to_wire()
            if plan.executor_capability
            else None,
            "available_ui_capability": {
                "kind": "macos_mock_ax_v1",
                "evidence": ["AX tree", "AX values", "AX positions/sizes", "exact press results"],
                "screenshots": {
                    "action": "snapshot with capture_window=true",
                    "scope": "unique exact child PID/title window only; never desktop",
                    "max_per_scenario": 6,
                    "max_dimension_pixels": 1800,
                    "max_png_bytes": 400_000,
                    "requires_existing_screen_capture_permission": True,
                    "delivery": "sealed receipt and actual QA/Reviewer image attachments",
                },
                "real_login": False,
                "network": False,
                "actions": ["snapshot", "press", "scroll"],
                "scroll": {
                    "scroll_position": "finite number 0..1: 0=top, 1=bottom",
                    "target": "exactly one enabled settable vertical scrollbar in target window",
                    "selectors": "none; no role/attribute/value/index or global coordinates",
                    "evidence": "AXValue readback, then separate approved snapshot/capture",
                    "ambiguous_or_unconfirmed": "stop and return to Manager; never retry",
                },
                "diagnostics": [
                    "session",
                    "AX trust",
                    "child process status/argv",
                    "child native window count",
                    "child AX status/window count",
                ],
                "driver_sha256": native_ui_capability(previous_ui.scenario).driver_sha256
                if previous_ui
                else None,
                "policy_sha256": native_ui_capability(previous_ui.scenario).policy_sha256
                if previous_ui
                else None,
            }
            if plan.executor_capability
            else None,
            "ui_scenario_schema": NativeUiScenario.model_json_schema(),
            "source_prerequisite_repair": {
                "available": failed_execution is not None and failed_execution.phase == "BLOCKED",
                "requires_separate_exact_approval": True,
                "producer": "ASE Coder",
                "independent_qa_review_required": True,
            },
            "ui_launch_contract": (
                "The executor starts the exact binary directly with its approved mock argument. "
                "It does not send LaunchServices open/reopen events, activate the app, or open "
                "a named SwiftUI Window. The isolated mock entry must create its primary window."
            ),
            "previous_ui_scenario": previous_ui.scenario.to_wire() if previous_ui else None,
            "previous_ui_capability": previous_ui.to_wire() if previous_ui else None,
        }
        identity = coordination_digest(payload)
        if plan.manager_advice is not None and plan.manager_advice.input_sha256 == identity:
            return None
        with store.execution_lock():
            try:
                return store.get_verification_advice(identity)
            except RecoveryRecordMissing:
                pass
            advice = coordinate_verification(
                self.backend._structured_clients.for_project(
                    Path(plan.scope.repository_root), TeamRole.MANAGER
                ),
                payload=payload,
                criterion_ids=tuple(value.id for value in source.runtime.task.acceptance_criteria),
                scope_sha256=digest(plan.scope.to_wire()),
                candidate_revision=plan.inputs.candidate_revision,
                qa_artifact_id=qa.artifact_id if qa else None,
                qa_artifact_sha256=qa.integrity.sha256 if qa else None,
                knowledge_resolutions=resolutions,
                execution_failure=failure_reference,
                environment_prerequisite=environment_prerequisite,
                executor=_manager_executor(self.config, self.environment, source),
            )
            if advice.draft.native_ui_scenario is not None and plan.executor_capability is None:
                raise RecoveryRejected("Manager proposed an unavailable native UI capability")
            if advice.draft.prerequisite_repair is not None and (
                failed_execution is None or failed_execution.phase != "BLOCKED"
            ):
                raise RecoveryRejected(
                    "historical UI evidence does not grant pre-model source repair"
                )
            return store.put_verification_advice(advice)

    def propose(
        self,
        scope: RecoveryScope,
        *,
        native_ui_scenario: NativeUiScenario | None = None,
        manager_advice: ManagerVerificationAdvice | None = None,
    ) -> tuple[CandidateVerificationPlan, Path]:
        source = NativeCandidateSourceReader(self.config, self.environment).inspect(scope)
        now = datetime.now(UTC)
        execution_id = (
            f"task_verify_{digest({'task': source.inputs.task_id, 'time': now.isoformat()})[:32]}"
        )
        snapshot = self._authority(source).current_snapshot(
            repository_id=scope.repository_id, task_id=source.inputs.task_id
        )
        preview = _verification_allocation(
            source,
            snapshot,
            config=self.config,
            execution_task_id=execution_id,
            plan_sha256="0" * 64,
            now=now,
        )
        definitions = _definitions(source, preview)
        store = FileRecoveryStore.initialize(verification_store_root(source), scope=scope)
        retained = select_retained_qa(
            store,
            source.inputs,
            FileArtifactStore(
                Path(source.stages.preparation.repository_workspace_root) / "artifacts",
                read_only=True,
            ),
        )
        if retained is not None:
            previous_attempt, _ = retained
            if native_ui_scenario is not None and (
                previous_attempt.native_ui is None
                or native_ui_scenario != previous_attempt.native_ui.scenario
            ):
                raise RecoveryRejected(
                    "Reviewer-only continuation must retain the approved UI scope"
                )
            native_ui_scenario = (
                previous_attempt.native_ui.scenario if previous_attempt.native_ui else None
            )
            manager_advice = previous_attempt.manager_advice
        previous = store.latest_verification_completion()
        incident = None
        if (
            previous is not None
            and previous.qa.task_id == source.inputs.task_id
            and previous.qa.source_revision == source.inputs.candidate_revision
            and previous.disposition is CandidateVerificationDisposition.RETRY_VERIFICATION
        ):
            incident = store.record_verification_incident(previous)
        prior_visual = (
            _available_prior_visual_evidence(store, source.inputs, previous)
            if incident is not None and native_ui_scenario is not None
            else None
        )
        if retained is not None:
            previous_attempt = retained[0]
            incident = (
                store.get_verification_incident(previous_attempt.prerequisite_incident_sha256)
                if previous_attempt.prerequisite_incident_sha256 is not None
                else None
            )
            prior_visual = store.get_prior_visual_evidence(previous_attempt)
        plan = CandidateVerificationPlan.create(
            scope=scope,
            inputs=source.inputs,
            execution_task_id=execution_id,
            native_checkpoint_sha256=source.checkpoint.checkpoint_sha256,
            dispatch_sha256=source.runtime.dispatch.dispatch_sha256,
            approved_stage_chain_sha256=_stage_sha(source),
            current_policy_sha256=_policy_sha(definitions, self.config),
            parent_delivery_id=source.parent_delivery_id,
            parent_checkpoint_sha256=source.parent_checkpoint_sha256,
            definitions=tuple(definitions[role] for role in AgentRole),
            executor_capability=_executor_capability(
                definitions[AgentRole.QA].permissions.commands, self.config
            ),
            native_ui=native_ui_capability(native_ui_scenario)
            if native_ui_scenario is not None
            else None,
            prerequisite_incident_sha256=incident.incident_sha256 if incident else None,
            prior_visual_evidence=PriorVisualEvidence(
                plan_sha256=prior_visual.plan_sha256,
                record_sha256=prior_visual.record_sha256,
            )
            if prior_visual is not None
            else None,
            manager_advice=manager_advice,
            retained_qa=retained[1] if retained is not None else None,
            created_at=now,
        )
        CandidateVerificationAdmission(
            store=store,
            plan_sha256=plan.plan_sha256,
            facts=NativeVerificationFacts(self.config, self.environment, store=store),
            artifacts=FileArtifactStore(
                Path(source.stages.preparation.repository_workspace_root) / "artifacts"
            ),
            clock=lambda: datetime.now(UTC),
        ).propose(plan)
        path = verification_store_root(source) / f"verification-plan-{plan.plan_sha256}.json"
        return plan, path

    def open(self, path: Path) -> tuple[FileRecoveryStore, CandidateVerificationPlan]:
        return open_candidate_verification_plan(self.config, self.environment, path)

    def approve(self, path: Path, *, confirmed_plan: str, reference: str) -> None:
        store, plan = self.open(path)
        admission = self._admission(store, plan)
        command = RecoveryApprovalCommand(
            operation_id=f"op_verify_{plan.plan_sha256[:32]}",
            plan_sha256=plan.plan_sha256,
            approval_reference=reference,
            submitted_at=datetime.now(UTC),
        )
        try:
            previous = store.get_verification_authorization(plan.plan_sha256)
        except RecoveryRecordMissing:
            pass
        else:
            if (
                previous.command.approval_reference != reference
                or confirmed_plan != plan.plan_sha256
            ):
                raise RecoveryRejected("approval replay differs from original confirmation")
            command = previous.command
        admission.approve(
            command,
            human=ExplicitVerificationHuman(confirmed_plan),
        )

    def execute(
        self, path: Path, *, route_factory: DeliveryRouteAdapterFactory | None = None
    ) -> CandidateVerificationCompletion:
        if not self.config.live_model_execution:
            raise RecoveryRejected("live model execution is disabled")
        store, plan = self.open(path)
        try:
            completion = store.get_verification_completion(plan.plan_sha256)
        except RecoveryRecordMissing:
            pass
        else:
            NativeVerificationFacts(self.config, self.environment, store=store).validate(plan)
            return completion
        for role in (AgentRole.QA, AgentRole.REVIEWER):
            try:
                invocation = store.get_verification_invocation(plan.plan_sha256, role)
            except RecoveryRecordMissing:
                continue
            raise RecoveryRejected(
                f"{role.value} run {invocation.request.run_id} was already admitted without "
                "a sealed completion; this approved plan cannot be replayed. Run "
                "verify-propose for the same project and delivery, then approve the new plan; "
                "Coder will not run"
            )
        source = NativeCandidateSourceReader(self.config, self.environment).inspect(plan.scope)
        admission = self._admission(store, plan)
        authority = self._authority(source)
        definitions = {d.role: d for d in plan.definitions}
        selected_factory = (
            route_factory or self._route_factory or ConfiguredDeliveryRouteAdapterFactory()
        )
        if plan.executor_capability is not None and not isinstance(
            selected_factory, ConfiguredDeliveryRouteAdapterFactory
        ):
            raise RecoveryRejected(
                "selected adapter cannot enforce the approved verification capability"
            )

        def build(snapshot: DispatchWorkforceSnapshot) -> VerificationReservation:
            value = _verification_allocation(
                source,
                snapshot,
                config=self.config,
                execution_task_id=plan.execution_task_id,
                plan_sha256=plan.plan_sha256,
                now=datetime.now(UTC),
            )
            if _definitions(source, value) != definitions:
                raise RecoveryRejected("current Agent/model allocation differs from approved plan")
            return value

        reservation = authority.reserve_verification(
            repository_id=plan.scope.repository_id,
            source_task_id=plan.inputs.task_id,
            plan_sha256=plan.plan_sha256,
            validate_current=lambda _: NativeVerificationFacts(
                self.config, self.environment, store=store
            ).validate(plan),
            build=build,
        )
        sidecar = Path(source.stages.preparation.repository_workspace_root)
        artifacts, contexts = (
            FileArtifactStore(sidecar / "artifacts"),
            FileContextStore(sidecar / "contexts"),
        )
        if plan.executor_capability is not None:
            from ai_software_engineer.recovery.verification_execution import (
                BoundSwiftVerificationEvidence,
            )

            assert isinstance(selected_factory, ConfiguredDeliveryRouteAdapterFactory)
            selected_factory = selected_factory.with_verification_evidence(
                BoundSwiftVerificationEvidence(
                    store=store,
                    plan=plan,
                    facts=NativeVerificationFacts(self.config, self.environment, store=store),
                    worktree_root=Path(self.config.platform_root)
                    / "worktrees"
                    / plan.scope.repository_id,
                )
            )
        adapter = DispatchDeliveryAgentAdapter(
            dispatch=reservation,
            definitions=definitions,
            plan_adapter=None,
            config=self.config,
            repository_root=plan.scope.repository_root,
            repository_workspace_root=sidecar,
            context_resolver=StoredContextResolver(contexts, artifacts),
            environment=self.environment,
            route_adapters=selected_factory,
        )
        repository = MySqlTaskRepository(self.config.require_mysql_dsn(self.environment))
        try:
            runner = CandidateVerificationRunner(
                repository=repository,
                artifact_store=artifacts,
                context_builder=FileRunContextBuilder(
                    plan.scope.repository_root,
                    context_store=contexts,
                    sources=(_verification_context(plan),),
                    budget=PRODUCTION_DELIVERY_CONTEXT_BUDGET,
                ),
                agent_adapter=adapter,
                agent_definitions=definitions,
                admission=admission,
            )
            completion = admission.complete(runner.verify_candidate(plan.inputs))
            authority.complete_verification(
                plan_sha256=plan.plan_sha256,
                completion_sha256=completion.completion_sha256,
                validate_completion=lambda record, sha: self._validate_completion(
                    record, reservation, completion, sha
                ),
            )
            return completion
        except Exception as error:
            # Admission is deliberately at-most-once, so an interrupted plan must never be
            # replayed.  It must also stop consuming QA/Reviewer capacity after setup or the
            # provider fails.  The release digest records only stable, non-sensitive facts.
            with suppress(Exception):
                authority.abandon_verification(
                    plan_sha256=plan.plan_sha256,
                    abandonment_sha256=digest(
                        {
                            "kind": "candidate_verification_abandonment",
                            "plan_sha256": plan.plan_sha256,
                            "error_type": type(error).__name__,
                        }
                    ),
                )
            # Preserve the original execution failure. A later Manager reconciliation can still
            # repair a reservation whose release itself could not be persisted.
            raise
        finally:
            repository.close()
            adapter.close_clean_worktrees()

    def _admission(
        self, store: FileRecoveryStore, plan: CandidateVerificationPlan
    ) -> CandidateVerificationAdmission:
        source = NativeCandidateSourceReader(self.config, self.environment).inspect(plan.scope)
        return CandidateVerificationAdmission(
            store=store,
            plan_sha256=plan.plan_sha256,
            facts=NativeVerificationFacts(self.config, self.environment, store=store),
            artifacts=FileArtifactStore(
                Path(source.stages.preparation.repository_workspace_root) / "artifacts"
            ),
            clock=lambda: datetime.now(UTC),
        )

    @staticmethod
    def _validate_completion(
        record: VerificationReservation,
        expected: VerificationReservation,
        completion: CandidateVerificationCompletion,
        digest_value: str,
    ) -> None:
        if record != expected or digest_value != completion.completion_sha256:
            raise RecoveryRejected("completion does not match its verification reservation")
