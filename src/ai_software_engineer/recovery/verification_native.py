"""Read authoritative candidate provenance without preparing or restarting delivery."""

from collections.abc import Mapping
from dataclasses import dataclass

from ai_software_engineer.agents import FileModelRouteAttemptStore
from ai_software_engineer.agents.fallback import model_route_root
from ai_software_engineer.artifacts import FileArtifactStore, artifact_digest
from ai_software_engineer.company_workspace import CompanyWorkspace, _read_regular, _reject_symlinks
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain.artifact import ImplementationReportArtifact, PlanArtifact
from ai_software_engineer.project_manager.delivery_checkpoint import (
    DeliveryStage,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.project_workspace import ProjectWorkspaceManifest
from ai_software_engineer.recovery.models import RecoveryRejected, RecoveryScope, digest
from ai_software_engineer.recovery.native import NativeApprovedStages, _parent, read_approved_stages
from ai_software_engineer.recovery.verification_records import CandidateVerificationInputs
from ai_software_engineer.recovery.verification_snapshot import (
    CandidateRuntimeSnapshot,
    read_candidate_snapshot,
)


@dataclass(frozen=True)
class NativeCandidateSource:
    scope: RecoveryScope
    checkpoint: ProjectDeliveryCheckpoint
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
        if scope.company_id != self.config.company_id:
            raise ValueError("company mismatch")
        company = CompanyWorkspace.initialize(
            self.config.platform_root,
            company_id=scope.company_id,
            name=self.config.company_name,
            read_only=True,
        )
        root = company.root / "projects" / scope.project_id
        _reject_symlinks(root)
        manifest = ProjectWorkspaceManifest.model_validate_json(
            _read_regular(root / "workspace.json", 64_000)
        )
        manifest.validate_binding(root)
        if manifest.project_id != scope.project_id or manifest.project_root != scope.project_root:
            raise ValueError("project binding mismatch")
        journal = FileProjectDeliveryCheckpointStore(
            root / "state/project-deliveries", read_only=True
        )
        history = journal.list(scope.delivery_id)
        cp = history[-1]
        intake = journal.get_intake(scope.delivery_id)
        if (
            cp.stage not in (DeliveryStage.BLOCKED, DeliveryStage.FAILED)
            or cp.project_id != scope.project_id
            or cp.project_root != scope.project_root
            or intake.project_id != scope.project_id
            or intake.project_root != scope.project_root
        ):
            raise ValueError("not a terminal scoped delivery")
        runtime = read_candidate_snapshot(self.config, self.environment, cp, history)
        stages = read_approved_stages(
            self.config,
            root,
            scope,
            cp,
            runtime.task,
            runtime.planner_dispatch,
            current_dispatch=runtime.dispatch,
        )
        parent_id, parent_sha = _parent(company, cp, stages.approval)
        artifacts = FileArtifactStore(root / "artifacts", read_only=True)
        implementation = artifacts.get(runtime.events[-2].artifact_ids[0])
        if (
            not isinstance(implementation, ImplementationReportArtifact)
            or len(implementation.parent_artifact_ids) != 1
        ):
            raise ValueError("missing original implementation lineage")
        plan = artifacts.get(implementation.parent_artifact_ids[0])
        candidate = runtime.events[-2].source_revision
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
        if (
            journal.list(scope.delivery_id) != history
            or read_candidate_snapshot(self.config, self.environment, cp, history) != runtime
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
            or _parent(company, cp, stages.approval) != (parent_id, parent_sha)
        ):
            raise ValueError("candidate source changed during inspection")
        return NativeCandidateSource(scope, cp, runtime, stages, inputs, parent_id, parent_sha)
