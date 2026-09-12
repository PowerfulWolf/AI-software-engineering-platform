"""Read authoritative candidate provenance without preparing or restarting delivery."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ai_software_engineer.agents import FileModelRouteAttemptStore
from ai_software_engineer.agents.fallback import model_route_root
from ai_software_engineer.artifacts import FileArtifactStore, artifact_digest
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.artifact import ImplementationReportArtifact, PlanArtifact
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryStage,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
    checkpoint_sha256_is_ancestor,
)
from ai_software_engineer.manager.dispatch import ContinuationDispatchRecord
from ai_software_engineer.recovery.models import RecoveryRejected, RecoveryScope, digest
from ai_software_engineer.recovery.native import NativeApprovedStages, _parent, read_approved_stages
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationDisposition,
    CandidateVerificationInputs,
    verification_inputs_are_current,
)
from ai_software_engineer.recovery.verification_snapshot import (
    CandidateRuntimeSnapshot,
    read_candidate_source_snapshot,
    terminal_candidate_event,
)
from ai_software_engineer.repository_workspace import RepositoryWorkspaceManifest
from ai_software_engineer.team_workspace import TeamWorkspace, _read_regular, _reject_symlinks


@dataclass(frozen=True)
class NativeCandidateSource:
    scope: RecoveryScope
    checkpoint: ProjectDeliveryCheckpoint
    terminal_checkpoint: ProjectDeliveryCheckpoint
    runtime: CandidateRuntimeSnapshot
    stages: NativeApprovedStages
    inputs: CandidateVerificationInputs
    parent_delivery_id: str | None
    parent_checkpoint_sha256: str | None


class NativeCandidateSourceReader:
    def __init__(self, config: ProductionConfig, environment: Mapping[str, str]) -> None:
        self.config, self.environment = config, dict(environment)

    def inspect(self, scope: RecoveryScope) -> NativeCandidateSource:
        try:
            return self._inspect(RecoveryScope.model_validate(scope.to_wire()))
        except Exception as error:
            raise RecoveryRejected(
                "candidate provenance is missing, unsafe or inconsistent"
            ) from error

    def _inspect(self, scope: RecoveryScope) -> NativeCandidateSource:
        if scope.team_id != self.config.team_id:
            raise ValueError("team mismatch")
        team = TeamWorkspace.initialize(
            self.config.platform_root,
            team_id=scope.team_id,
            name=self.config.team_name,
            read_only=True,
        )
        _, repository = team.project_registry().locate_repository(scope.repository_id)
        root = repository.root
        _reject_symlinks(root)
        manifest = RepositoryWorkspaceManifest.model_validate_json(
            _read_regular(root / "workspace.json", 64_000)
        )
        manifest.validate_binding(root)
        if (
            manifest.repository_id != scope.repository_id
            or manifest.repository_root != scope.repository_root
        ):
            raise ValueError("project binding mismatch")
        journal = FileProjectDeliveryCheckpointStore(
            root / "state/project-deliveries", read_only=True
        )
        history = journal.list(scope.delivery_id)
        current = history[-1]
        intake = journal.get_intake(scope.delivery_id)
        if (
            current.stage not in (DeliveryStage.BLOCKED, DeliveryStage.FAILED)
            or current.repository_id != scope.repository_id
            or current.repository_root != scope.repository_root
            or intake.repository_id != scope.repository_id
            or intake.repository_root != scope.repository_root
        ):
            raise ValueError("not a terminal scoped delivery")
        cp, terminal, runtime, continuation = read_candidate_source_snapshot(
            self.config, self.environment, history
        )
        stages = read_approved_stages(
            self.config,
            root,
            scope,
            cp,
            runtime.task,
            runtime.planner_dispatch,
            current_dispatch=runtime.dispatch,
        )
        parent_id, parent_sha = _parent(team, terminal, stages.approval)
        artifacts = FileArtifactStore(root / "artifacts", read_only=True)
        candidate_checkpoint = terminal_candidate_event(runtime.task, runtime.events)
        implementation = artifacts.get(candidate_checkpoint.artifact_ids[0])
        if (
            not isinstance(implementation, ImplementationReportArtifact)
            or len(implementation.parent_artifact_ids) != 1
        ):
            raise ValueError("missing original implementation lineage")
        plan = artifacts.get(implementation.parent_artifact_ids[0])
        candidate = candidate_checkpoint.source_revision
        if (
            not isinstance(plan, PlanArtifact)
            or plan.task_id != runtime.task.id
            or implementation.task_id != runtime.task.id
            or plan.parent_artifact_ids
            or plan.source_revision != runtime.task.base_ref
            or implementation.source_revision != candidate
            or implementation.content.commit_sha != candidate
            or implementation.supersedes is not None
        ):
            raise ValueError("candidate artifact provenance mismatch")
        expected = {criterion.id for criterion in runtime.task.acceptance_criteria}
        if {item.criterion_id for item in plan.content.acceptance_mapping} != expected or {
            item.criterion_id for item in implementation.content.acceptance_mapping
        } != expected:
            raise ValueError("candidate criteria mismatch")
        routes_root = model_route_root(root)
        _reject_symlinks(routes_root)
        routes = FileModelRouteAttemptStore(routes_root, read_only=True)
        run_ids = {a.producer.run_id for a in artifacts.list_for_task(runtime.task.id)}
        for directory in routes_root.glob("run_*"):
            _reject_symlinks(directory)
            for path in directory.glob("*.json"):
                _read_regular(path, 8_000_000)
            for route in routes.list_for_run(directory.name):
                if route.task_id == runtime.task.id:
                    run_ids.add(route.result.run_id)
        inputs = CandidateVerificationInputs(
            task_id=runtime.task.id,
            task_revision=runtime.revision,
            task_sha256=digest(runtime.task.to_wire()),
            plan_id=plan.artifact_id,
            plan_sha256=artifact_digest(plan),
            implementation_id=implementation.artifact_id,
            implementation_sha256=artifact_digest(implementation),
            candidate_revision=candidate,
            prior_run_ids=tuple(sorted(run_ids)),
        )
        if continuation is not None:
            _validate_inconclusive_continuation(
                root,
                scope,
                history,
                cp,
                runtime,
                inputs,
                continuation,
            )
        replay_cp, replay_terminal, replay_runtime, replay_continuation = (
            read_candidate_source_snapshot(self.config, self.environment, history)
        )
        if (
            journal.list(scope.delivery_id) != history
            or (replay_cp, replay_terminal, replay_runtime, replay_continuation)
            != (cp, terminal, runtime, continuation)
            or read_approved_stages(
                self.config,
                root,
                scope,
                cp,
                runtime.task,
                runtime.planner_dispatch,
                current_dispatch=runtime.dispatch,
            )
            != stages
            or _parent(team, terminal, stages.approval) != (parent_id, parent_sha)
        ):
            raise ValueError("candidate source changed during inspection")
        return NativeCandidateSource(
            scope,
            cp,
            terminal,
            runtime,
            stages,
            inputs,
            parent_id,
            parent_sha,
        )


def _validate_inconclusive_continuation(
    sidecar: Path,
    scope: RecoveryScope,
    history: tuple[ProjectDeliveryCheckpoint, ...],
    source_checkpoint: ProjectDeliveryCheckpoint,
    runtime: CandidateRuntimeSnapshot,
    inputs: CandidateVerificationInputs,
    continuation: ContinuationDispatchRecord,
) -> None:
    """Allow retained-candidate reuse only for a legacy environment-only QA remediation."""
    store = FileRecoveryStore(
        sidecar / "state" / f"candidate-verification-{scope.delivery_id}",
        scope=scope,
    )
    plan = store.get_verification_plan(continuation.continuation_plan_sha256)
    completion = store.get_verification_completion(plan.plan_sha256)
    qa_invocation = store.get_verification_invocation(plan.plan_sha256, AgentRole.QA)
    admitted_run_ids = {qa_invocation.request.run_id}
    if completion.review is not None:
        reviewer_invocation = store.get_verification_invocation(
            plan.plan_sha256, AgentRole.REVIEWER
        )
        admitted_run_ids.add(reviewer_invocation.request.run_id)
    if (
        continuation.source_delivery_id != scope.delivery_id
        or continuation.source_task_id != inputs.task_id
        or continuation.source_revision != inputs.candidate_revision
        or continuation.source_dispatch_id != source_checkpoint.dispatch_commit_id
        or continuation.continuation_plan_sha256 != plan.plan_sha256
        or continuation.continuation_sha256 != completion.completion_sha256
        or plan.scope != scope
        or not checkpoint_sha256_is_ancestor(history, plan.native_checkpoint_sha256)
        or plan.dispatch_sha256 != runtime.dispatch.dispatch_sha256
        or not verification_inputs_are_current(plan.inputs, inputs, admitted_run_ids)
        or completion.plan_sha256 != plan.plan_sha256
        or completion.qa_invocation_sha256 != qa_invocation.invocation_sha256
        or completion.disposition is not CandidateVerificationDisposition.RETRY_VERIFICATION
    ):
        raise RecoveryRejected("failed continuation does not retain an inconclusive candidate")
