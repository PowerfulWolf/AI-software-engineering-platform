"""Production bridge: joint approved artifacts → native deliveries → pinned integration."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path

from ai_software_engineer.agents import StructuredModelClient, StructuredModelResult
from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain import (
    AgentPermissions,
    AgentRole,
    NetworkAccess,
    ProductApprovalDecision,
    TeamRole,
)
from ai_software_engineer.domain.project_delivery import DesignComplexityFacts
from ai_software_engineer.execution import (
    CommandExecutionError,
    CommandExecutor,
    CommandResult,
    CommandTimedOut,
    SubprocessCommandExecutor,
)
from ai_software_engineer.git import (
    GitWorkspaceError,
    GitWorktreeManager,
    WorkspacePolicy,
    WorktreeAlreadyExists,
    WorktreeRef,
    WorktreeSpec,
)
from ai_software_engineer.manager.baseline import FileProjectBaselineCompilationStore
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    ProjectDeliveryCheckpointCatalog,
    ResumeProjectDelivery,
    StartProjectDelivery,
    UnifiedProjectEntryService,
)
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryStage,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
    checkpoint_is_ancestor,
)
from ai_software_engineer.manager.preparation import PrepareProjectResult, PrepareProjectStatus
from ai_software_engineer.manager.production_agents import (
    ProductDraft,
    TechnicalDesignDraft,
)
from ai_software_engineer.manager.production_backend import (
    MultiRepositoryStructuredClientFactory,
    ProductionProjectDeliveryBackend,
    StructuredClientFactory,
    _task_commands,
)
from ai_software_engineer.manager.store import FileProjectPreparationStore
from ai_software_engineer.multi_directory.errors import RequirementSourceRevisionDrift
from ai_software_engineer.multi_directory.integration_commands import (
    TEST_PREFIXES,
)
from ai_software_engineer.multi_directory.integration_commands import (
    is_test_command as _test_command,
)
from ai_software_engineer.multi_directory.models import (
    Candidate,
    ChildDelivery,
    IntegrationCommandError,
    IntegrationEvidence,
    JointCheckpoint,
    JointExecutionPlan,
    JointStage,
    PreparedUnit,
    SingleRepositoryAcceptance,
    digest,
)
from ai_software_engineer.multi_directory.planning import design_work_graph
from ai_software_engineer.multi_directory.scope import DirectoryUnit, git_read
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.product import (
    HumanProductDecisionCommand,
    HumanProductDecisionVerifier,
    VerifiedHumanProductDecision,
)
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.redaction import redact_text
from ai_software_engineer.repository_profile import RepositoryProfile
from ai_software_engineer.repository_workspace import RepositoryWorkspace
from ai_software_engineer.runtime_workspace import load_repository_profile
from ai_software_engineer.team_workspace import TeamWorkspace


def approved_joint_context_source(checkpoint: JointCheckpoint, unit_id: str) -> ContextSource:
    """Build the canonical approved parent context for one repository unit."""
    projection = DerivedStageInputs(checkpoint, unit_id)
    shared = {
        "requirement_project": checkpoint.delivery_id,
        "product": checkpoint.product_spec.to_wire() if checkpoint.product_spec else None,
        "design": checkpoint.design.to_wire() if checkpoint.design else None,
        "plan": checkpoint.plan.to_wire() if checkpoint.plan else None,
        "approval": checkpoint.approval.to_wire() if checkpoint.approval else None,
        "dependencies": [
            child.to_wire()
            for child in checkpoint.children
            if child.unit_id in projection.dependencies
        ],
    }
    content = json.dumps(shared, sort_keys=True, ensure_ascii=False)
    return ContextSource(
        source_id="joint.approved_context",
        uri=f"joint://{checkpoint.delivery_id}/{hashlib.sha256(content.encode()).hexdigest()}",
        content=content,
        required=True,
        priority=5,
    )


BackendFactory = Callable[
    [
        StructuredClientFactory,
        tuple[ContextSource, ...],
        HumanProductDecisionVerifier,
        PrepareProjectResult,
        str,
    ],
    ProductionProjectDeliveryBackend,
]


class ProductionJointBackend:
    def __init__(
        self,
        *,
        native: ProductionProjectDeliveryBackend,
        factory: BackendFactory,
        clients: StructuredClientFactory,
        team: TeamWorkspace,
        project: ProjectWorkspace,
        environment: Mapping[str, str],
    ) -> None:
        self.native = native
        self.factory = factory
        self.clients = clients
        self.team = team
        self.project = project
        self.environment = dict(environment)

    def prepare(self, unit: DirectoryUnit) -> PreparedUnit:
        self._require_intake_source(unit)
        result = self.native.prepare(unit.root)
        if result.status is not PrepareProjectStatus.PREPARED:
            return PreparedUnit(unit_id=unit.id, result=result)
        profile = RepositoryProfile.discover(unit.root, repository_id=result.repository_id)
        sources = list(self.native.prepared_context(result))
        for index, source in enumerate(profile.native_rules):
            path = Path(unit.root) / source.relative_path
            if not path.resolve().is_relative_to(Path(unit.root)) or path.is_symlink():
                raise ValueError("native rule escapes the selected repository")
            if source.byte_length > 256_000:
                raise ValueError("native rule exceeds joint context budget")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != source.sha256:
                raise ValueError("native rule changed during preparation")
            sources.append(
                ContextSource(
                    source_id=f"native.rule.{index}",
                    uri=source.uri,
                    content=redact_text(data.decode("utf-8")).text,
                    required=True,
                )
            )
        if sum(len(s.content or "") for s in sources) > 1_000_000:
            raise ValueError("prepared joint context exceeds budget")
        self._require_intake_source(unit)
        return PreparedUnit(
            unit_id=unit.id,
            result=result,
            context_sources=tuple(sources),
            commands=_task_commands(profile),
        )

    def client(self, checkpoint: JointCheckpoint, role: TeamRole) -> StructuredModelClient:
        roots = (
            self._candidate_paths(checkpoint)
            if role is TeamRole.PLANNER and checkpoint.children
            else self._baseline_paths(checkpoint)
        )
        if isinstance(self.clients, MultiRepositoryStructuredClientFactory):
            client = self.clients.for_projects(roots, role)
        else:
            client = self.clients.for_project(roots[0], role)
        from ai_software_engineer.knowledge.agents import RepositoryInspection
        from ai_software_engineer.knowledge.index import retrieval_for_project
        from ai_software_engineer.knowledge.runtime import joint_knowledge_client

        return joint_knowledge_client(
            client,
            checkpoint,
            role,
            self.project.requirements_root / checkpoint.delivery_id / "knowledge",
            retrieval_for_project(self.project),
            repository_inspection=tuple(
                RepositoryInspection(
                    unit_id=unit.id,
                    repository_id=next(
                        p.result.repository_id
                        for p in checkpoint.preparations
                        if p.unit_id == unit.id
                    ),
                    read_root=str(root),
                    git_revision=(
                        next(
                            (
                                child.checkpoint.candidate_revision
                                for child in checkpoint.children
                                if child.unit_id == unit.id
                            ),
                            unit.base_revision,
                        )
                        if role is TeamRole.PLANNER and checkpoint.children
                        else unit.base_revision
                    )
                    or "",
                )
                for unit, root in zip(checkpoint.scope.units, roots, strict=True)
            ),
        )

    def reconcile(self, checkpoint: JointCheckpoint) -> None:
        prepared_unit_ids = {prepared.unit_id for prepared in checkpoint.preparations}
        for unit in checkpoint.scope.units:
            self.team.validate_code_root(unit.root)
            if checkpoint.stage is JointStage.PREPARING and unit.id not in prepared_unit_ids:
                self._require_intake_source(unit)
        if all(unit.base_revision is not None for unit in checkpoint.scope.units):
            self._baseline_paths(checkpoint)
        for prepared in checkpoint.preparations:
            expected = self.native.prepared_context(prepared.result)
            if prepared.context_sources[: len(expected)] != expected:
                raise ValueError("sealed Requirement preparation facts drifted")
        for child in checkpoint.children:
            unit = next(u for u in checkpoint.scope.units if u.id == child.unit_id)
            if child.checkpoint.repository_root != unit.root:
                raise ValueError("child checkpoint belongs to another repository")
            if checkpoint.plan is None and (
                checkpoint.stage is JointStage.PLANNING
                or checkpoint.single_repository_acceptance is not None
            ):
                # Integration recovery deliberately clears the current plan before Planner
                # runs.  Rebuilding a DerivedStageInputs projection here would reject that
                # valid checkpoint because it requires a plan.  The child journal is the
                # authoritative fact needed at this seam; validate its exact committed prefix
                # directly and defer plan-bound runtime reconstruction until a fresh plan exists.
                history = self._child_history(child)
                if (
                    not history
                    or history[-1] != child.checkpoint
                    or not checkpoint_is_ancestor(history, child.checkpoint)
                ):
                    raise ValueError("native child checkpoint is not a committed history prefix")
                continue
            # Resolve native facts, not just a claimed joint child status.
            _, service = self.delivery_runtime(checkpoint, child.unit_id)
            actual = service.status(child.checkpoint.delivery_id).checkpoint
            history = FileProjectDeliveryCheckpointStore(
                self.project.root
                / "repositories"
                / actual.repository_id
                / "state/project-deliveries",
                read_only=True,
            ).list(actual.delivery_id)
            if (
                not history
                or history[-1] != actual
                or not checkpoint_is_ancestor(history, child.checkpoint)
            ):
                raise ValueError("native child checkpoint is not a committed history prefix")
            if child.checkpoint.stage is DeliveryStage.DONE and actual != child.checkpoint:
                raise ValueError("completed candidate checkpoint drift")

    def _child_history(self, child: ChildDelivery) -> tuple[ProjectDeliveryCheckpoint, ...]:
        """Read a retained native journal without requiring a plan-bound projection."""

        store = FileProjectDeliveryCheckpointStore(
            self.project.root
            / "repositories"
            / child.checkpoint.repository_id
            / "state/project-deliveries",
            read_only=True,
        )
        return store.list(child.checkpoint.delivery_id)

    def delivery_runtime(
        self, checkpoint: JointCheckpoint, unit_id: str
    ) -> tuple[ProductionProjectDeliveryBackend, UnifiedProjectEntryService]:
        """Rebuild the exact native runtime owned by one Requirement unit."""

        projection = DerivedStageInputs(checkpoint, unit_id)
        child = next(item for item in checkpoint.children if item.unit_id == unit_id)
        backend = self._derived_backend(checkpoint, unit_id)
        catalog = ProjectDeliveryCheckpointCatalog(self.project.repository_registry().registry_root)
        history = catalog.for_delivery(child.checkpoint.delivery_id).list(
            child.checkpoint.delivery_id
        )
        if history:
            current = history[-1]
            prepared = projection.preparation.preparation
            assert prepared is not None
            current_preparation_sha256 = current.preparation_sha256
            if current_preparation_sha256 is None:
                raise ValueError("native child checkpoint has no preparation")
            if current_preparation_sha256 != prepared.preparation_sha256:
                workspace = self.project.repository_registry().register(
                    current.repository_root,
                    repository_id=current.repository_id,
                )
                historical = _load_preparation_result(
                    workspace,
                    current_preparation_sha256,
                )
                historical_preparation = historical.preparation
                assert historical_preparation is not None
                profile = load_repository_profile(
                    workspace.root,
                    historical_preparation.repository_profile_sha256,
                )
                backend = self._derived_backend(
                    checkpoint,
                    unit_id,
                    frozen_preparation=historical,
                    frozen_source_revision=profile.source_revision,
                )
        return backend, self._entry(checkpoint, unit_id, backend=backend)

    def accept_single_repository(self, checkpoint: JointCheckpoint) -> SingleRepositoryAcceptance:
        """Verify one retained native candidate as the complete Requirement result."""

        if len(checkpoint.scope.units) != 1 or len(checkpoint.children) != 1:
            raise ValueError("single-repository acceptance requires exactly one repository")
        child = checkpoint.children[0]
        if (
            child.unit_id != checkpoint.scope.units[0].id
            or child.checkpoint.stage is not DeliveryStage.DONE
            or child.checkpoint.candidate_revision is None
            or checkpoint.product_spec is None
        ):
            raise ValueError("single-repository child is not an accepted native candidate")
        runtime_checkpoint = self._single_repository_runtime_checkpoint(checkpoint)
        backend, service = self.delivery_runtime(runtime_checkpoint, child.unit_id)
        actual = service.status(child.checkpoint.delivery_id).checkpoint
        if actual != child.checkpoint:
            raise ValueError("single-repository native checkpoint drifted")
        evidence = backend.accepted_delivery_evidence(actual)
        return SingleRepositoryAcceptance(
            unit_id=child.unit_id,
            child_checkpoint_sha256=child.checkpoint.checkpoint_sha256,
            candidate_revision=child.checkpoint.candidate_revision,
            product_spec_sha256=digest(checkpoint.product_spec),
            acceptance_ids=checkpoint.product_spec.acceptance_ids(),
            native_evidence_references=evidence,
        )

    def _single_repository_runtime_checkpoint(self, checkpoint: JointCheckpoint) -> JointCheckpoint:
        if checkpoint.plan is not None:
            return checkpoint
        history = JointJournal(self.project.requirements_root, read_only=True).history(
            checkpoint.delivery_id
        )
        historical = next(
            (
                item
                for item in reversed(history)
                if item.plan is not None
                and item.product_spec == checkpoint.product_spec
                and item.design == checkpoint.design
            ),
            None,
        )
        if historical is None:
            raise ValueError("single-repository acceptance has no approved native plan")
        assert historical.plan is not None
        values: dict[str, object] = dict(checkpoint.to_wire())
        values["plan"] = historical.plan
        return JointCheckpoint.seal(values)

    def _derived_backend(
        self,
        checkpoint: JointCheckpoint,
        unit_id: str,
        *,
        frozen_preparation: PrepareProjectResult | None = None,
        frozen_source_revision: str | None = None,
    ) -> ProductionProjectDeliveryBackend:
        projection = DerivedStageInputs(checkpoint, unit_id)
        source = approved_joint_context_source(checkpoint, unit_id)
        prepared = next(item for item in checkpoint.preparations if item.unit_id == unit_id)
        return self.factory(
            projection,
            (
                source,
                *tuple(
                    item
                    for item in prepared.context_sources
                    if item.source_id.startswith("native.rule.")
                    or item.uri.startswith(("team://", "project://"))
                ),
            ),
            projection,
            frozen_preparation or projection.preparation,
            frozen_source_revision or projection.base_revision,
        )

    def _entry(
        self,
        checkpoint: JointCheckpoint,
        unit_id: str,
        *,
        backend: ProductionProjectDeliveryBackend | None = None,
    ) -> UnifiedProjectEntryService:
        return UnifiedProjectEntryService(
            backend=backend or self._derived_backend(checkpoint, unit_id),
            catalog=ProjectDeliveryCheckpointCatalog(self.project.root / "repositories"),
            delivery_namespace=self.project.manifest.project_id,
        )

    def _require_intake_source(self, unit: DirectoryUnit) -> None:
        if unit.base_revision is None:
            return
        root = Path(unit.root)
        if git_read(root, "rev-parse", "--verify", "HEAD^{commit}") != unit.base_revision:
            raise RequirementSourceRevisionDrift(
                "source changed while the Requirement baseline was being prepared"
            )
        if git_read(root, "status", "--porcelain"):
            raise ValueError("source checkout must be clean during Requirement intake")

    def _baseline_paths(self, checkpoint: JointCheckpoint) -> tuple[Path, ...]:
        return tuple(self._baseline(checkpoint, unit).path for unit in checkpoint.scope.units)

    def _candidate_paths(self, checkpoint: JointCheckpoint) -> tuple[Path, ...]:
        assert checkpoint.design is not None
        children = {child.unit_id: child.checkpoint for child in checkpoint.children}
        roots = []
        for unit in checkpoint.scope.units:
            child = children.get(unit.id)
            if child is not None:
                if child.stage is not DeliveryStage.DONE or child.candidate_revision is None:
                    raise ValueError("integration planning requires completed native candidates")
                roots.append(
                    self._baseline(
                        checkpoint, unit, candidate_revision=child.candidate_revision
                    ).path
                )
            else:
                if unit.id not in checkpoint.design.reference_only:
                    raise ValueError("integration planning requires every modified candidate")
                roots.append(self._baseline(checkpoint, unit).path)
        return tuple(roots)

    def _baseline(
        self,
        checkpoint: JointCheckpoint,
        unit: DirectoryUnit,
        *,
        candidate_revision: str | None = None,
    ) -> WorktreeRef:
        revision = candidate_revision or unit.base_revision
        if revision is None:
            raise RequirementSourceRevisionDrift(
                "Requirement source baseline requires a committed Git revision"
            )
        manager = GitWorktreeManager(
            unit.root,
            Path(self.team.manifest.platform_root)
            / "worktrees"
            / "requirements"
            / checkpoint.delivery_id
            / unit.id,
        )
        spec = WorktreeSpec(
            task_id=("task_candidate_" if candidate_revision else "task_baseline_")
            + hashlib.sha256(
                (f"{checkpoint.delivery_id}:{unit.id}" + (candidate_revision or "")).encode()
            ).hexdigest()[:32],
            role=AgentRole.REVIEWER,
            attempt=1,
            source_revision=revision,
        )
        try:
            try:
                worktree = manager.create(spec)
            except WorktreeAlreadyExists:
                worktree = manager.recover(spec)
            snapshot = manager.inspect(worktree)
            if snapshot.dirty or snapshot.head_revision != revision:
                raise RequirementSourceRevisionDrift(
                    "Requirement source baseline worktree changed; restore it before continuing"
                )
            return worktree
        except GitWorkspaceError as error:
            raise RequirementSourceRevisionDrift(
                "Requirement source baseline is unavailable; restore the recorded commit "
                "or baseline worktree before continuing"
            ) from error

    def deliver(self, checkpoint: JointCheckpoint, unit_id: str) -> ChildDelivery:
        self.reconcile(checkpoint)
        projection = DerivedStageInputs(checkpoint, unit_id)
        child = next((item for item in checkpoint.children if item.unit_id == unit_id), None)
        if child is not None:
            # Recovery may have approved a newer preparation than the parent intake.
            # Observe that exact runtime before deciding whether any work remains.
            _, service = self.delivery_runtime(checkpoint, unit_id)
            result = service.status(child.checkpoint.delivery_id)
        else:
            service = self._entry(checkpoint, unit_id)
            result = service.start(
                StartProjectDelivery(
                    repository_root=projection.root,
                    requirement=projection.requirement,
                    title=checkpoint.title,
                    submitted_at=checkpoint.submitted_at,
                )
            )
        if result.checkpoint.stage is DeliveryStage.WAITING_PRODUCT_APPROVAL:
            assert checkpoint.approval is not None
            result = service.approve(
                ApproveProductSpec(
                    delivery_id=result.checkpoint.delivery_id,
                    expected_checkpoint_sha256=result.checkpoint.checkpoint_sha256,
                    approval_reference=projection.approval_reference,
                    submitted_at=checkpoint.approval.approved_at,
                )
            )
        elif result.checkpoint.stage not in {
            DeliveryStage.DONE,
            DeliveryStage.BLOCKED,
            DeliveryStage.FAILED,
        }:
            result = service.resume(
                ResumeProjectDelivery(delivery_id=result.checkpoint.delivery_id)
            )
        return ChildDelivery(unit_id=unit_id, checkpoint=result.checkpoint)

    def validate_plan(self, checkpoint: JointCheckpoint, plan: JointExecutionPlan) -> None:
        if len(checkpoint.scope.units) == 1 and not plan.integration_checks:
            return
        for check_index, check in enumerate(plan.integration_checks, 1):
            prepared = next(p for p in checkpoint.preparations if p.unit_id == check.unit_id)
            unit = next(u for u in checkpoint.scope.units if u.id == check.unit_id)
            permissions = _integration_permissions(prepared.commands)
            WorkspacePolicy(unit.root, permissions).authorize_command(check.argv)
            # Integration is testing, not a general shell/build/install escape hatch.
            if not _test_command(check.argv):
                raise IntegrationCommandError(check_index=check_index, argv=check.argv)
            child = next((c.checkpoint for c in checkpoint.children if c.unit_id == unit.id), None)
            if child is not None and child.stage is DeliveryStage.DONE:
                assert child.candidate_revision is not None
                _validate_pytest_paths(
                    Path(unit.root), child.candidate_revision, check.argv, check_index
                )
        assert checkpoint.design is not None
        for interface in checkpoint.design.interfaces:
            participants = {interface.producer, *interface.consumers}
            if not any(
                interface.id in c.interface_ids and participants <= set(c.consumes)
                for c in plan.integration_checks
            ):
                raise ValueError(
                    "each interface needs a check consuming producer and consumers together"
                )

    def integrate(self, checkpoint: JointCheckpoint) -> IntegrationEvidence:
        self.reconcile(checkpoint)
        assert checkpoint.plan is not None
        self.validate_plan(checkpoint, checkpoint.plan)
        candidates = tuple(
            Candidate(
                unit_id=u.id,
                revision=next(
                    (
                        c.checkpoint.candidate_revision
                        for c in checkpoint.children
                        if c.unit_id == u.id
                    ),
                    u.base_revision,
                )
                or "missing",
            )
            for u in checkpoint.scope.units
        )
        opened: dict[str, tuple[GitWorktreeManager, WorktreeRef]] = {}
        try:
            for unit, candidate in zip(checkpoint.scope.units, candidates, strict=True):
                manager = GitWorktreeManager(
                    unit.root,
                    Path(self.team.manifest.platform_root)
                    / "worktrees"
                    / checkpoint.delivery_id
                    / "integration"
                    / unit.id,
                )
                spec = WorktreeSpec(
                    task_id="task_joint_"
                    + hashlib.sha256(checkpoint.delivery_id.encode()).hexdigest()[:32],
                    role=AgentRole.REVIEWER,
                    attempt=1,
                    source_revision=candidate.revision,
                )
                try:
                    worktree = manager.create(spec)
                except WorktreeAlreadyExists:
                    worktree = manager.recover(spec)
                opened[unit.id] = (manager, worktree)
                if manager.inspect(worktree).dirty:
                    raise ValueError(
                        "integration worktree is dirty; preserve evidence before retry"
                    )
            environment = {
                "PATH": self.environment.get("PATH", "/usr/bin:/bin"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            environment.update(
                {
                    "ASE_UNIT_" + unit_id.removeprefix("unit_").upper(): str(ref.path)
                    for unit_id, (_, ref) in opened.items()
                }
            )
            results: list[CommandResult] = []
            for check in checkpoint.plan.integration_checks:
                prepared = next(p for p in checkpoint.preparations if p.unit_id == check.unit_id)
                _, ref = opened[check.unit_id]
                command_environment = environment
                if check.argv[0] in {"pytest", "python", "python3"}:
                    unit = next(u for u in checkpoint.scope.units if u.id == check.unit_id)
                    command_environment = _python_integration_environment(
                        Path(unit.root), ref.path, environment
                    )
                executor = SubprocessCommandExecutor(
                    ref.path,
                    _integration_permissions(prepared.commands),
                    environment=command_environment,
                    environment_allowlist=tuple(command_environment),
                    max_output_bytes=100_000,
                )
                result = _execute_integration_command(
                    executor,
                    check.argv,
                    ref.path,
                    timeout_seconds=check.timeout_seconds,
                )
                results.append(result)
                if result.returncode != 0:
                    break
                for manager, worktree in opened.values():
                    snapshot = manager.inspect(worktree)
                    if snapshot.dirty or snapshot.head_revision != worktree.head_revision:
                        raise ValueError(
                            "integration mutated a candidate worktree; evidence preserved"
                        )
            return IntegrationEvidence(
                plan_sha256=digest(checkpoint.plan), candidates=candidates, checks=tuple(results)
            )
        finally:
            for manager, worktree in opened.values():
                snapshot = manager.inspect(worktree)
                if not snapshot.dirty and snapshot.head_revision == worktree.head_revision:
                    manager.remove(worktree)


def _validate_pytest_paths(
    repository_root: Path, revision: str, argv: tuple[str, ...], check_index: int
) -> None:
    """Explicit pytest file selectors must exist in the reviewed Git tree, not main."""

    if not any(argv[: len(prefix)] == prefix for prefix in TEST_PREFIXES if prefix[-1] == "pytest"):
        return
    for token in argv[1:]:
        path = token.split("::", 1)[0]
        if token.startswith("-") or not path.endswith(".py"):
            continue
        if Path(path).is_absolute() or ".." in Path(path).parts or "\\" in path:
            raise IntegrationCommandError(check_index=check_index, argv=argv, missing_test=True)
        if (
            git_read(repository_root, "cat-file", "-e", f"{revision}:{path.removeprefix('./')}")
            is None
        ):
            raise IntegrationCommandError(check_index=check_index, argv=argv, missing_test=True)


def _python_integration_environment(
    repository_root: Path,
    candidate_root: Path,
    base: Mapping[str, str],
) -> dict[str, str]:
    """Borrow existing project tooling, with imports pinned to the candidate checkout."""

    environment = dict(base)
    venv = repository_root / ".venv"
    binary = venv / "bin"
    if venv.is_symlink() or binary.is_symlink():
        raise ValueError("integration Python environment must be project-local")
    if binary.is_dir():
        environment["PATH"] = str(binary) + os.pathsep + base.get("PATH", "/usr/bin:/bin")
    sources = (candidate_root / "src", candidate_root)
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in sources if path.is_dir())
    return environment


def _load_preparation_result(
    workspace: RepositoryWorkspace,
    preparation_sha256: str,
) -> PrepareProjectResult:
    """Reopen the exact immutable preparation used by a recovered native child."""

    policy = workspace.directory("policy")
    preparations = []
    for directory in (policy, *sorted(policy.glob("preparations-*"))):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("native preparation directory is unsafe")
        prepared = FileProjectPreparationStore(directory, read_only=True).find(
            workspace.repository_id
        )
        if prepared is not None and prepared.preparation_sha256 == preparation_sha256:
            preparations.append(prepared)
    if len(preparations) != 1:
        raise ValueError("native child preparation is missing or ambiguous")
    preparation = preparations[0]

    compilation_store = FileProjectBaselineCompilationStore()
    compilation_root = policy / "project-baseline-compilations"
    if compilation_root.is_symlink() or not compilation_root.is_dir():
        raise ValueError("native baseline compilation directory is unsafe")
    compilations = []
    for path in sorted(compilation_root.glob("*.json")):
        compilation = compilation_store.get(workspace, path.stem)
        if (
            compilation.repository_profile_sha256 == preparation.repository_profile_sha256
            and compilation.compiled_spec is not None
            and compilation.compiled_spec.baseline_sha256 == preparation.baseline_spec_sha256
        ):
            compilations.append(compilation)
    if len(compilations) != 1:
        raise ValueError("native child baseline compilation is missing or ambiguous")
    return PrepareProjectResult(
        status=PrepareProjectStatus.PREPARED,
        repository_id=workspace.repository_id,
        baseline_compilation_sha256=compilations[0].compilation_sha256,
        preparation=preparation,
    )


class DerivedStageInputs(
    StructuredClientFactory, StructuredModelClient, HumanProductDecisionVerifier
):
    """Mechanically project approved joint documents; never run independent Product models."""

    def __init__(self, checkpoint: JointCheckpoint, unit_id: str) -> None:
        checkpoint.validate_integrity()
        if (
            checkpoint.approval is None
            or checkpoint.product_spec is None
            or checkpoint.design is None
            or checkpoint.plan is None
        ):
            raise ValueError("native projection requires the approved joint artifact chain")
        unit = next(u for u in checkpoint.scope.units if u.id == unit_id)
        prepared = next(
            (item for item in checkpoint.preparations if item.unit_id == unit_id),
            None,
        )
        if (
            prepared is None
            or prepared.result.preparation is None
            or unit.base_revision is None
            or prepared.result.status is not PrepareProjectStatus.PREPARED
        ):
            raise ValueError("native projection requires a prepared Git source baseline")
        self.root = unit.root
        self.preparation = prepared.result
        self.base_revision = unit.base_revision
        design = next(u for u in checkpoint.design.units if u.unit_id == unit_id)
        planned = next(p for p in checkpoint.plan.units if p.unit_id == unit_id)
        self.dependencies = planned.depends_on
        self.plan = planned.plan
        # Joint revision lineage belongs to the parent journal. The native child
        # receives a fresh projected plan, so carrying parent feedback would make
        # native validation treat it as a revision without a native predecessor.
        # Preserve the approved phases and work graph while omitting that
        # parent-only lineage at this boundary.
        if self.plan.revision_feedback is not None:
            self.plan = self.plan.model_copy(update={"revision_feedback": None})
        if checkpoint.planning_decision is None and self.plan.work_graph is None:
            # Historical approved plan: preserve it in the journal/context; only its
            # new native projection receives mechanically mapped design references.
            self.plan = self.plan.model_copy(
                update={
                    "work_graph": design_work_graph(
                        design.design,
                        package_id="legacy_" + unit_id,
                    )
                }
            )
        pairs = [
            (f"req_{i:03d}", r)
            for i, r in enumerate(checkpoint.product_spec.product.requirements, 1)
            if f"req_{i:03d}" in design.requirement_ids
        ]
        self.product = checkpoint.product_spec.product.model_copy(
            update={"requirements": tuple(r for _, r in pairs)}
        )
        req_map = {old: f"req_{i:03d}" for i, (old, _) in enumerate(pairs, 1)}
        ac_map = {
            f"ac_{old.removeprefix('req_')}_{j:03d}": f"ac_{i:03d}_{j:03d}"
            for i, (old, r) in enumerate(pairs, 1)
            for j, _ in enumerate(r.acceptance, 1)
        }
        if self.plan.work_graph is not None:
            graph = self.plan.work_graph
            self.plan = self.plan.model_copy(
                update={
                    "work_graph": graph.model_copy(
                        update={
                            "packages": tuple(
                                package.model_copy(
                                    update={
                                        "acceptance_criterion_ids": tuple(
                                            ac_map[item]
                                            for item in package.acceptance_criterion_ids
                                        ),
                                        "tests": tuple(
                                            test.model_copy(
                                                update={
                                                    "acceptance_criterion_ids": tuple(
                                                        ac_map[item]
                                                        for item in test.acceptance_criterion_ids
                                                    ),
                                                }
                                            )
                                            for test in package.tests
                                        ),
                                    }
                                )
                                for package in graph.packages
                            ),
                        }
                    )
                }
            )
        complexity = design.design.complexity_facts
        participates_in_interface = any(
            interface.producer == unit_id or unit_id in interface.consumers
            for interface in checkpoint.design.interfaces
        )
        if planned.depends_on or participates_in_interface:
            complexity = (complexity or DesignComplexityFacts()).model_copy(
                update={
                    "work_package_dependencies": bool(planned.depends_on)
                    or bool(complexity and complexity.work_package_dependencies),
                    "interface_compatibility": participates_in_interface
                    or bool(complexity and complexity.interface_compatibility),
                }
            )
        self.design = design.design.model_copy(
            update={
                "complexity_facts": complexity,
                "requirement_mappings": tuple(
                    m.model_copy(update={"requirement_id": req_map[m.requirement_id]})
                    for m in design.design.requirement_mappings
                ),
                "acceptance_mappings": tuple(
                    m.model_copy(
                        update={"acceptance_criterion_id": ac_map[m.acceptance_criterion_id]}
                    )
                    for m in design.design.acceptance_mappings
                ),
            }
        )
        self.requirement = (
            f"Derived unit {unit_id} of {checkpoint.delivery_id}; "
            f"approved product {digest(checkpoint.product_spec)}, "
            f"design {digest(checkpoint.design)}, plan {digest(checkpoint.plan)}."
        )
        self.approval_reference = (
            f"joint-approval:{checkpoint.delivery_id}:{digest(checkpoint.approval)}:{unit_id}"
        )

    def for_project(
        self,
        repository_root: Path,
        role: TeamRole = TeamRole.PRODUCT,
    ) -> StructuredModelClient:
        del role
        if str(repository_root.resolve()) != self.root:
            raise ValueError("derived documents are bound to another repository")
        return self

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        del instructions, input_payload, timeout_seconds, input_images
        title = output_schema.get("title")
        if title == ProductDraft.__name__:
            document = self.product.to_wire()
        elif title == TechnicalDesignDraft.__name__:
            document = self.design.to_wire()
        elif title == "ExecutionPlanDraft":
            document = self.plan.to_wire()
        else:
            raise ValueError("unsupported derived artifact schema")
        return StructuredModelResult(payload=document, duration_ms=0)

    def verify(self, command: HumanProductDecisionCommand) -> VerifiedHumanProductDecision:
        if command.approval_reference != self.approval_reference:
            raise ValueError("missing exact joint human approval delegation")
        return VerifiedHumanProductDecision(
            approval_reference=command.approval_reference,
            request_id=command.request_id,
            product_spec_id=command.product_spec_id,
            product_spec_sha256=command.product_spec_sha256,
            decision=ProductApprovalDecision.APPROVED,
            operator_id="joint-human-approval-delegation",
            rationale=self.approval_reference,
            decided_at=command.submitted_at,
        )


def _integration_permissions(commands: tuple[str, ...]) -> AgentPermissions:
    return AgentPermissions(
        read_paths=("**",),
        write_paths=(),
        commands=tuple(c for c in commands if not c.startswith("git ")),
        network=NetworkAccess.NONE,
    )


def _require_nonempty_test_run(result: CommandResult) -> None:
    output = result.stdout + "\n" + result.stderr
    if result.returncode == 0 and re.search(
        r"Ran 0 tests?\b|Tests run: 0\b|No tests were found|\[no test files\]", output
    ):
        raise ValueError("integration reported no executed tests; cannot accept PASS")


def _integration_failure_result(
    argv: tuple[str, ...],
    cwd: Path,
    *,
    returncode: int,
    duration_ms: int,
    stdout: str = "",
    stderr: str,
) -> CommandResult:
    """Build a redacted typed result for failures without a normal command result."""

    return CommandResult(
        argv=argv,
        cwd=str(cwd),
        returncode=returncode,
        stdout=redact_text(stdout).text,
        stderr=redact_text(stderr).text,
        duration_ms=duration_ms,
    )


def _execute_integration_command(
    executor: CommandExecutor,
    argv: tuple[str, ...],
    cwd: Path,
    *,
    timeout_seconds: int,
) -> CommandResult:
    """Turn every expected command outcome into redacted, durable evidence."""

    try:
        result = executor.run(argv, timeout_seconds=timeout_seconds)
    except CommandTimedOut as error:
        return _integration_failure_result(
            argv,
            cwd,
            returncode=124,
            duration_ms=error.duration_ms,
            stderr="command timed out",
        )
    except CommandExecutionError:
        # Never persist provider, OS, path, or environment details from the exception.
        return _integration_failure_result(
            argv,
            cwd,
            returncode=127,
            duration_ms=0,
            stderr="command could not start",
        )
    try:
        _require_nonempty_test_run(result)
    except ValueError:
        return _integration_failure_result(
            argv,
            cwd,
            returncode=1,
            duration_ms=result.duration_ms,
            stdout=result.stdout,
            stderr="integration reported no executed tests; cannot accept PASS",
        )
    return result.model_copy(
        update={
            "stdout": redact_text(result.stdout).text,
            "stderr": redact_text(result.stderr).text,
        }
    )
