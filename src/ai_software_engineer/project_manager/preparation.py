"""Project Manager Agent facade for task-free project preparation.

The Agent supplies only an absolute project root. Organization identity, sidecar
placement, rule compilation, durable records, and the clock are policy-bound
dependencies of this service rather than ambient Agent authority.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self

from pydantic import StringConstraints, ValidationError, field_validator, model_validator

from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.project_delivery import ProjectPreparation
from ai_software_engineer.project_manager.baseline import (
    ProjectBaselineCompilation,
    ProjectBaselineCompilationStatus,
    ProjectBaselineCompiler,
    ProjectBaselineIntegrityError,
    ProjectSpecConflict,
    ProjectWaitingHumanRoute,
)
from ai_software_engineer.project_manager.stages import (
    ProjectStageAdvancer,
    StageAdvanceAuthorization,
    StageAdvanceRequest,
)
from ai_software_engineer.project_profile import ProjectProfile
from ai_software_engineer.project_workspace import ProjectWorkspace, ProjectWorkspaceRegistry
from ai_software_engineer.runtime_workspace import OrganizationWorkspace, RuntimeWorkspaceBinder
from ai_software_engineer.spec_compiler import SpecRule

Clock = Callable[[], datetime]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class ProjectManagerSkillError(RuntimeError):
    """Base error for fail-closed Project Manager Skill behavior."""


class ProjectPreparationDrift(ProjectManagerSkillError):
    """Raised when current project facts disagree with a durable preparation."""


class ProjectPreparationCompositionError(ProjectManagerSkillError):
    """Raised when organization, target, and sidecar roots cannot compose safely."""


class ProjectBaselineRecordError(ProjectManagerSkillError):
    """Raised when a baseline recorder returns a different compilation identity."""


class ProductContextNotReady(ProjectManagerSkillError):
    """Raised when Product Agent context is requested before preparation."""


class PrepareProjectStatus(StrEnum):
    """Exclusive outcomes visible to the Project Manager Agent."""

    PREPARED = "PREPARED"
    WAITING_HUMAN = "WAITING_HUMAN"


class PrepareProjectRequest(DomainModel):
    """The complete public input to the ``prepare_project`` Skill."""

    kind: Literal["prepare_project_request"] = "prepare_project_request"
    schema_version: Literal["v0.1"] = "v0.1"
    project_root: NonEmptyStr

    @field_validator("project_root")
    @classmethod
    def require_absolute_project_root(cls, value: str) -> str:
        if any(ord(character) < 32 for character in value) or not Path(value).is_absolute():
            raise ValueError("project_root must be absolute and contain no controls")
        return value


class PrepareProjectResult(DomainModel):
    """Prepared checkpoint or an explicit project-level human wait route."""

    kind: Literal["prepare_project_result"] = "prepare_project_result"
    schema_version: Literal["v0.1"] = "v0.1"
    status: PrepareProjectStatus
    project_id: ProjectId
    baseline_compilation_sha256: Sha256
    preparation: ProjectPreparation | None = None
    conflicts: tuple[ProjectSpecConflict, ...] = ()
    route: ProjectWaitingHumanRoute | None = None

    @model_validator(mode="after")
    def validate_exclusive_result(self) -> Self:
        if self.status is PrepareProjectStatus.PREPARED:
            if self.preparation is None or self.conflicts or self.route is not None:
                raise ValueError("PREPARED result requires only preparation")
            if self.preparation.project_id != self.project_id:
                raise ValueError("preparation belongs to another project")
        elif self.preparation is not None or not self.conflicts or self.route is None:
            raise ValueError("WAITING_HUMAN result requires conflicts and route")
        else:
            if any(conflict.project_id != self.project_id for conflict in self.conflicts):
                raise ValueError("conflicts belong to another project")
            if self.route.conflict_ids != tuple(conflict.id for conflict in self.conflicts):
                raise ValueError("route conflict IDs do not match result conflicts")
        return self


class ProjectManagerSkill(Protocol):
    """Agent-visible, policy-bound Project Manager capability."""

    def prepare_project(self, request: PrepareProjectRequest) -> PrepareProjectResult: ...

    def require_product_context(self, result: PrepareProjectResult) -> ProjectPreparation: ...

    def advance_stage(self, request: StageAdvanceRequest) -> StageAdvanceAuthorization: ...


class ProjectRuleProvider(Protocol):
    """Resolve explicit rules authorized for the observed project profile."""

    def rules_for(self, profile: ProjectProfile) -> Sequence[SpecRule]: ...


class ProjectPreparationStore(Protocol):
    """Append-once port for the successful preparation checkpoint."""

    def put(self, preparation: ProjectPreparation) -> ProjectPreparation: ...

    def get(self, project_id: ProjectId | str) -> ProjectPreparation: ...

    def find(self, project_id: ProjectId | str) -> ProjectPreparation | None: ...


class ProjectBaselineCompilationRecorder(Protocol):
    """Durable recorder for both compiled and WAITING_HUMAN outcomes."""

    def record(
        self,
        workspace: ProjectWorkspace,
        compilation: ProjectBaselineCompilation,
    ) -> ProjectBaselineCompilation: ...


class ProjectManagerSkillService:
    """Deterministically compose registration, discovery, binding, and preparation."""

    def __init__(
        self,
        *,
        organization: OrganizationWorkspace,
        registry: ProjectWorkspaceRegistry,
        platform_rules: Sequence[SpecRule],
        rule_provider: ProjectRuleProvider,
        preparation_store_factory: Callable[[Path], ProjectPreparationStore],
        baseline_recorder: ProjectBaselineCompilationRecorder,
        baseline_compiler: ProjectBaselineCompiler | None = None,
        binder: RuntimeWorkspaceBinder | None = None,
        stage_advancer: ProjectStageAdvancer | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._organization = organization
        self._registry = registry
        self._platform_rules = tuple(platform_rules)
        self._rule_provider = rule_provider
        self._preparation_store_factory = preparation_store_factory
        self._baseline_recorder = baseline_recorder
        self._baseline_compiler = baseline_compiler or ProjectBaselineCompiler()
        self._binder = binder or RuntimeWorkspaceBinder()
        self._stage_advancer = stage_advancer or ProjectStageAdvancer()
        self._clock = clock or _utc_now

    def prepare_project(self, request: PrepareProjectRequest) -> PrepareProjectResult:
        """Prepare or safely replay one project without writing its code root."""
        observed_at = self._clock()
        _require_aware(observed_at)
        workspace = self._registry.register(request.project_root)
        store = self._preparation_store_factory(workspace.directory("policy"))
        existing = store.find(workspace.project_id)
        if existing is not None:
            existing.validate_integrity()

        profile = ProjectProfile.discover(
            workspace.project_root,
            project_id=workspace.project_id,
            observed_at=observed_at,
        )
        try:
            binding = self._binder.bind(
                self._organization,
                workspace,
                profile,
                bound_at=observed_at,
            )
        except ValidationError as error:
            raise ProjectPreparationCompositionError(
                "organization, project, and sidecar roots cannot overlap"
            ) from error
        rules = (*self._platform_rules, *tuple(self._rule_provider.rules_for(profile)))
        compilation = self._baseline_compiler.compile(
            profile,
            rules,
            compiled_at=observed_at,
        )
        compilation.validate_integrity()
        recorded = self._baseline_recorder.record(workspace, compilation)
        try:
            recorded.validate_integrity()
        except ProjectBaselineIntegrityError as error:
            raise ProjectBaselineRecordError(
                "baseline recorder returned an invalid compilation"
            ) from error
        if recorded.compilation_sha256 != compilation.compilation_sha256:
            raise ProjectBaselineRecordError(
                "baseline recorder returned a different compilation identity"
            )

        if recorded.status is ProjectBaselineCompilationStatus.CONFLICT:
            if existing is not None:
                raise ProjectPreparationDrift(
                    "current project baseline conflicts with its durable preparation"
                )
            if recorded.route is None:
                raise ProjectBaselineRecordError("conflict compilation has no human route")
            return PrepareProjectResult(
                status=PrepareProjectStatus.WAITING_HUMAN,
                project_id=workspace.project_id,
                baseline_compilation_sha256=recorded.compilation_sha256,
                conflicts=recorded.conflicts,
                route=recorded.route,
            )

        baseline = recorded.compiled_spec
        if baseline is None:
            raise ProjectBaselineRecordError("compiled baseline result has no compiled_spec")
        prepared_at = existing.prepared_at if existing is not None else observed_at
        candidate = ProjectPreparation.create(
            organization_id=self._organization.organization_id,
            project_id=workspace.project_id,
            project_root=str(workspace.project_root),
            project_workspace_root=str(workspace.root),
            organization_root=str(self._organization.root),
            project_profile_sha256=profile.profile_sha256,
            runtime_binding_sha256=binding.binding_sha256,
            baseline_spec_sha256=baseline.baseline_sha256,
            baseline_source_uris=baseline.source_uris,
            prepared_at=prepared_at,
        )
        if existing is not None and existing != candidate:
            raise ProjectPreparationDrift(
                "current project facts do not match the durable preparation"
            )
        persisted = store.put(candidate)
        persisted.validate_integrity()
        if persisted != candidate:
            raise ProjectPreparationDrift(
                "preparation store returned a different project checkpoint"
            )
        return PrepareProjectResult(
            status=PrepareProjectStatus.PREPARED,
            project_id=workspace.project_id,
            baseline_compilation_sha256=recorded.compilation_sha256,
            preparation=persisted,
        )

    def advance_stage(self, request: StageAdvanceRequest) -> StageAdvanceAuthorization:
        """Authorize a validated stage prefix without editing its documents."""
        authorized_at = self._clock()
        _require_aware(authorized_at)
        preparation = request.preparation
        if preparation is None:
            raise ProductContextNotReady("stage advancement requires a PREPARED project checkpoint")
        current = self.prepare_project(PrepareProjectRequest(project_root=preparation.project_root))
        if (
            current.status is not PrepareProjectStatus.PREPARED
            or current.preparation is None
            or current.preparation != preparation
        ):
            raise ProjectPreparationDrift(
                "stage advancement checkpoint does not match current project facts"
            )
        return self._stage_advancer.advance_stage(request, authorized_at=authorized_at)

    def require_product_context(self, result: PrepareProjectResult) -> ProjectPreparation:
        """Reopen current durable facts before exposing Product Agent context."""
        if result.status is not PrepareProjectStatus.PREPARED or result.preparation is None:
            raise ProductContextNotReady(
                "Product Agent context requires a PREPARED project checkpoint"
            )
        supplied = result.preparation
        supplied.validate_integrity()
        current = self.prepare_project(PrepareProjectRequest(project_root=supplied.project_root))
        if (
            current.status is not PrepareProjectStatus.PREPARED
            or current.preparation is None
            or current.preparation != supplied
            or current.baseline_compilation_sha256 != result.baseline_compilation_sha256
        ):
            raise ProjectPreparationDrift(
                "Product Agent checkpoint does not match current project facts"
            )
        current.preparation.validate_integrity()
        return current.preparation


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProjectManagerSkillError("Project Manager clock must be timezone-aware")


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "PrepareProjectRequest",
    "PrepareProjectResult",
    "PrepareProjectStatus",
    "ProductContextNotReady",
    "ProjectBaselineCompilationRecorder",
    "ProjectBaselineRecordError",
    "ProjectManagerSkill",
    "ProjectManagerSkillError",
    "ProjectManagerSkillService",
    "ProjectPreparationCompositionError",
    "ProjectPreparationDrift",
    "ProjectPreparationStore",
    "ProjectRuleProvider",
]
