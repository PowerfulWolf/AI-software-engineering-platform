"""Production bridge: joint approved artifacts → native deliveries → pinned integration."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path

from ai_software_engineer.agents import StructuredModelClient, StructuredModelResult
from ai_software_engineer.company_workspace import CompanyWorkspace
from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain import (
    AgentPermissions,
    AgentRole,
    NetworkAccess,
    ProductApprovalDecision,
)
from ai_software_engineer.execution import CommandResult, SubprocessCommandExecutor
from ai_software_engineer.git import (
    GitWorktreeManager,
    WorkspacePolicy,
    WorktreeAlreadyExists,
    WorktreeRef,
    WorktreeSpec,
)
from ai_software_engineer.multi_directory.models import (
    Candidate,
    ChildDelivery,
    IntegrationEvidence,
    JointCheckpoint,
    JointExecutionPlan,
    PreparedUnit,
    digest,
)
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit, git_read
from ai_software_engineer.product import (
    HumanProductDecisionCommand,
    HumanProductDecisionVerifier,
    VerifiedHumanProductDecision,
)
from ai_software_engineer.project_manager.delivery import (
    ApproveProductSpec,
    ProjectDeliveryCheckpointCatalog,
    ResumeProjectDelivery,
    StartProjectDelivery,
    UnifiedProjectEntryService,
)
from ai_software_engineer.project_manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.project_manager.preparation import PrepareProjectStatus
from ai_software_engineer.project_manager.production_agents import (
    ProductDraft,
    TechnicalDesignDraft,
)
from ai_software_engineer.project_manager.production_backend import (
    ProductionProjectDeliveryBackend,
    StructuredClientFactory,
    _task_commands,
)
from ai_software_engineer.project_profile import ProjectProfile
from ai_software_engineer.redaction import redact_text

BackendFactory = Callable[
    [StructuredClientFactory, tuple[ContextSource, ...], HumanProductDecisionVerifier],
    ProductionProjectDeliveryBackend,
]


class ProductionJointBackend:
    def __init__(
        self,
        *,
        native: ProductionProjectDeliveryBackend,
        factory: BackendFactory,
        clients: StructuredClientFactory,
        company: CompanyWorkspace,
        environment: Mapping[str, str],
    ) -> None:
        self.native = native
        self.factory = factory
        self.clients = clients
        self.company = company
        self.environment = dict(environment)

    def prepare(self, unit: DirectoryUnit) -> PreparedUnit:
        result = self.native.prepare(unit.root)
        if result.status is not PrepareProjectStatus.PREPARED:
            return PreparedUnit(unit_id=unit.id, result=result)
        profile = ProjectProfile.discover(unit.root, project_id=result.project_id)
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
        return PreparedUnit(
            unit_id=unit.id,
            result=result,
            context_sources=tuple(sources),
            commands=_task_commands(profile),
        )

    def client(self, scope: DirectoryScope) -> StructuredModelClient:
        return self.clients.for_project(Path(scope.units[0].root))

    def reconcile(self, checkpoint: JointCheckpoint) -> None:
        for unit in checkpoint.scope.units:
            self.company.validate_code_root(unit.root)
            if (
                git_read(Path(unit.root), "rev-parse", "--verify", "HEAD^{commit}")
                != unit.base_revision
            ):
                raise ValueError("source revision drift: use a new requirement project")
            if unit.base_revision and git_read(Path(unit.root), "status", "--porcelain"):
                raise ValueError("source checkout is dirty; preserve changes before continuing")
        for prepared in checkpoint.preparations:
            unit = next(u for u in checkpoint.scope.units if u.id == prepared.unit_id)
            current = self.prepare(unit)
            if current != prepared:
                raise ValueError("joint preparation or knowledge drift")
        for child in checkpoint.children:
            unit = next(u for u in checkpoint.scope.units if u.id == child.unit_id)
            if child.checkpoint.project_root != unit.root:
                raise ValueError("child checkpoint belongs to another repository")
            # Resolve native facts, not just a claimed joint child status.
            service = self._entry(checkpoint, child.unit_id)
            actual = service.status(child.checkpoint.delivery_id).checkpoint
            if actual.sequence < child.checkpoint.sequence:
                raise ValueError("native child checkpoint history moved backwards")
            if child.checkpoint.stage is DeliveryStage.DONE and actual != child.checkpoint:
                raise ValueError("completed candidate checkpoint drift")

    def _entry(self, checkpoint: JointCheckpoint, unit_id: str) -> UnifiedProjectEntryService:
        projection = DerivedStageInputs(checkpoint, unit_id)
        shared = {
            "requirement_project": checkpoint.delivery_id,
            "product": checkpoint.product_spec.to_wire() if checkpoint.product_spec else None,
            "design": checkpoint.design.to_wire() if checkpoint.design else None,
            "plan": checkpoint.plan.to_wire() if checkpoint.plan else None,
            "approval": checkpoint.approval.to_wire() if checkpoint.approval else None,
            "dependencies": [
                c.to_wire() for c in checkpoint.children if c.unit_id in projection.dependencies
            ],
        }
        content = json.dumps(shared, sort_keys=True, ensure_ascii=False)
        source = ContextSource(
            source_id="joint.approved_context",
            uri=f"joint://{checkpoint.delivery_id}/{hashlib.sha256(content.encode()).hexdigest()}",
            content=content,
            required=True,
            priority=5,
        )
        return UnifiedProjectEntryService(
            backend=self.factory(projection, (source,), projection),
            catalog=ProjectDeliveryCheckpointCatalog(self.company.root / "projects"),
            delivery_namespace=self.company.manifest.company_id,
        )

    def deliver(self, checkpoint: JointCheckpoint, unit_id: str) -> ChildDelivery:
        self.reconcile(checkpoint)
        projection = DerivedStageInputs(checkpoint, unit_id)
        service = self._entry(checkpoint, unit_id)
        result = service.start(
            StartProjectDelivery(
                project_root=projection.root,
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
        for check in plan.integration_checks:
            prepared = next(p for p in checkpoint.preparations if p.unit_id == check.unit_id)
            unit = next(u for u in checkpoint.scope.units if u.id == check.unit_id)
            permissions = _integration_permissions(prepared.commands)
            WorkspacePolicy(unit.root, permissions).authorize_command(check.argv)
            # Integration is testing, not a general shell/build/install escape hatch.
            if not _test_command(check.argv):
                raise ValueError(
                    "integration requires a supported test command, "
                    "not inspection/install/inline code"
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
                    self.company.requests_root / checkpoint.delivery_id / "integration" / unit.id,
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
                result = SubprocessCommandExecutor(
                    ref.path,
                    _integration_permissions(prepared.commands),
                    environment=environment,
                    environment_allowlist=tuple(environment),
                    max_output_bytes=100_000,
                ).run(check.argv, timeout_seconds=check.timeout_seconds)
                _require_nonempty_test_run(result)
                results.append(
                    result.model_copy(
                        update={
                            "stdout": redact_text(result.stdout).text,
                            "stderr": redact_text(result.stderr).text,
                        }
                    )
                )
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
        self.root = next(u.root for u in checkpoint.scope.units if u.id == unit_id)
        design = next(u for u in checkpoint.design.units if u.unit_id == unit_id)
        planned = next(p for p in checkpoint.plan.units if p.unit_id == unit_id)
        self.dependencies = planned.depends_on
        self.plan = planned.plan
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
        self.design = design.design.model_copy(
            update={
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

    def for_project(self, project_root: Path) -> StructuredModelClient:
        if str(project_root.resolve()) != self.root:
            raise ValueError("derived documents are bound to another repository")
        return self

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
    ) -> StructuredModelResult:
        del instructions, input_payload, timeout_seconds
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


def _test_command(argv: tuple[str, ...]) -> bool:
    denied = {
        "-c",
        "--eval",
        "-e",
        "install",
        "publish",
        "deploy",
        "--help",
        "-h",
        "--version",
        "--collect-only",
        "--co",
        "--listTests",
        "--passWithNoTests",
        "--dry-run",
        "-DskipTests",
        "-Dmaven.test.skip",
        "-x",
        "--exclude-task",
    }
    if any(token.split("=", 1)[0] in denied for token in argv):
        return False
    prefixes = (
        ("pytest",),
        ("python", "-m", "pytest"),
        ("python3", "-m", "pytest"),
        ("python", "-m", "unittest"),
        ("python3", "-m", "unittest"),
        ("uv", "run", "pytest"),
        ("npm", "test"),
        ("pnpm", "test"),
        ("yarn", "test"),
        ("bun", "test"),
        ("go", "test"),
        ("ctest",),
        ("mvn", "test"),
        ("./mvnw", "test"),
        ("gradle", "test"),
        ("./gradlew", "test"),
    )
    return any(argv[: len(prefix)] == prefix for prefix in prefixes)


def _require_nonempty_test_run(result: CommandResult) -> None:
    output = result.stdout + "\n" + result.stderr
    if result.returncode == 0 and re.search(
        r"Ran 0 tests?\b|Tests run: 0\b|No tests were found|\[no test files\]", output
    ):
        raise ValueError("integration reported no executed tests; cannot accept PASS")
