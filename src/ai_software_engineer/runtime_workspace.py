"""Organization/project workspace binding and run-scoped workforce resolution."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Annotated, Final, Literal, Self, cast

from pydantic import (
    AwareDatetime,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from ai_software_engineer.context import ContextStoreError, FileContextStore
from ai_software_engineer.domain import AgentDefinition, WorkItemStatus
from ai_software_engineer.domain.agent import AgentId
from ai_software_engineer.domain.identity import ContextId, ProjectId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, WirePayload
from ai_software_engineer.domain.workforce import (
    AgentProfile,
    AgentRunAllocation,
    ModelPolicy,
    ModelPolicyId,
    ModelSelection,
    RoleAssignment,
    TaskLease,
    WorkItem,
    is_waiting,
    lease_is_active,
)
from ai_software_engineer.project_profile import ProjectProfile, Sha256
from ai_software_engineer.project_workspace import (
    ProjectWorkspace,
    ProjectWorkspaceError,
    ProjectWorkspaceManifest,
)
from ai_software_engineer.runtime import RuntimeConfig, RuntimePaths
from ai_software_engineer.spec_compiler import CompiledSpec

OrganizationId = Annotated[
    str, StringConstraints(pattern=r"^organization_[a-z0-9][a-z0-9_-]{2,63}$")
]

ORGANIZATION_MANIFEST_NAME: Final = "organization.json"
ORGANIZATION_DIRECTORIES: Final[tuple[str, ...]] = (
    "agents",
    "model-policies",
    "work-items",
    "leases",
    "metrics",
)
PROJECT_PROFILE_NAME: Final = "project-profile.json"
RUNTIME_BINDING_NAME: Final = "runtime-workspace-binding.json"


class RuntimeWorkspaceError(RuntimeError):
    """Base error for organization/project composition failures."""


class OrganizationWorkspaceError(RuntimeWorkspaceError):
    """Raised when the organization workspace is missing or untrusted."""


class RuntimeWorkspaceConflict(RuntimeWorkspaceError):
    """Raised when an immutable binding or workforce record conflicts."""


class RuntimeWorkspaceCorruption(RuntimeWorkspaceError):
    """Raised when a durable workspace record fails validation or integrity."""


class RuntimeAllocationError(RuntimeWorkspaceError):
    """Raised when workforce facts cannot safely authorize an Agent Run."""


class OrganizationLayout(DomainModel):
    """Fixed organization-owned facts, separate from every project sidecar."""

    agents: Literal["agents"] = "agents"
    model_policies: Literal["model-policies"] = "model-policies"
    work_items: Literal["work-items"] = "work-items"
    leases: Literal["leases"] = "leases"
    metrics: Literal["metrics"] = "metrics"

    def values(self) -> tuple[str, ...]:
        return (
            self.agents,
            self.model_policies,
            self.work_items,
            self.leases,
            self.metrics,
        )


class OrganizationWorkspaceManifest(DomainModel):
    """Durable identity and layout for the organization-owned team workspace."""

    kind: Literal["organization_workspace"] = "organization_workspace"
    schema_version: Literal["v0.1"] = "v0.1"
    organization_id: OrganizationId
    root: NonEmptyStr
    layout: OrganizationLayout = Field(default_factory=OrganizationLayout)
    created_at: AwareDatetime
    manifest_sha256: Sha256

    @field_validator("root")
    @classmethod
    def validate_root(cls, value: str) -> str:
        if not Path(value).is_absolute() or any(ord(character) < 32 for character in value):
            raise ValueError("organization root must be absolute and contain no controls")
        return value

    def validate_integrity(self) -> None:
        if self.manifest_sha256 != _organization_digest(self):
            raise RuntimeWorkspaceCorruption("organization manifest digest does not match content")


class OrganizationWorkspace:
    """Validated handle for long-lived AgentProfile and ModelPolicy facts."""

    def __init__(self, manifest: OrganizationWorkspaceManifest) -> None:
        self.manifest = manifest

    @classmethod
    def initialize(
        cls,
        root: str | Path,
        *,
        organization_id: OrganizationId | str,
        created_at: datetime,
    ) -> OrganizationWorkspace:
        """Atomically initialize or reopen one organization workspace."""
        _require_aware(created_at, "organization created_at")
        configured = Path(root).expanduser()
        if configured.is_symlink():
            raise OrganizationWorkspaceError("organization root cannot be a symlink")
        resolved = configured.resolve(strict=False)
        if resolved.exists():
            return cls.open(resolved, organization_id=organization_id)
        validated_id = TypeAdapter(OrganizationId).validate_python(organization_id)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{resolved.name}.", dir=resolved.parent))
        pending: Path | None = staging
        try:
            for directory in ORGANIZATION_DIRECTORIES:
                (staging / directory).mkdir()
            provisional = OrganizationWorkspaceManifest(
                organization_id=validated_id,
                root=str(resolved),
                created_at=created_at,
                manifest_sha256="0" * 64,
            )
            manifest = provisional.model_copy(
                update={"manifest_sha256": _organization_digest(provisional)}
            )
            _atomic_json_write(staging / ORGANIZATION_MANIFEST_NAME, manifest.to_wire())
            staging.rename(resolved)
            pending = None
        except OSError as error:
            raise OrganizationWorkspaceError(
                f"cannot initialize organization workspace: {resolved}"
            ) from error
        finally:
            if pending is not None:
                _remove_staging(pending)
        return cls.open(resolved, organization_id=validated_id)

    @classmethod
    def open(
        cls,
        root: str | Path,
        *,
        organization_id: OrganizationId | str | None = None,
    ) -> OrganizationWorkspace:
        configured = Path(root).expanduser()
        if configured.is_symlink():
            raise OrganizationWorkspaceError("organization root cannot be a symlink")
        resolved = configured.resolve(strict=False)
        manifest_path = resolved / ORGANIZATION_MANIFEST_NAME
        try:
            manifest = OrganizationWorkspaceManifest.model_validate(
                json.loads(manifest_path.read_text(encoding="utf-8"))
            )
            manifest.validate_integrity()
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as error:
            raise RuntimeWorkspaceCorruption(
                f"organization manifest is invalid: {manifest_path}"
            ) from error
        if Path(manifest.root) != resolved:
            raise RuntimeWorkspaceCorruption("organization manifest root does not match its path")
        if organization_id is not None:
            expected = TypeAdapter(OrganizationId).validate_python(organization_id)
            if manifest.organization_id != expected:
                raise RuntimeWorkspaceConflict("organization ID does not match existing workspace")
        for directory in manifest.layout.values():
            path = resolved / directory
            if path.is_symlink() or not path.is_dir():
                raise RuntimeWorkspaceCorruption(
                    f"organization layout is missing or unsafe: {directory}"
                )
        return cls(manifest)

    @property
    def root(self) -> Path:
        return Path(self.manifest.root)

    @property
    def organization_id(self) -> OrganizationId:
        return self.manifest.organization_id

    def directory(
        self, name: Literal["agents", "model-policies", "work-items", "leases", "metrics"]
    ) -> Path:
        if name not in self.manifest.layout.values():
            raise OrganizationWorkspaceError(f"unknown organization directory: {name}")
        return self.root / name


class RuntimeWorkspaceBinding(DomainModel):
    """Immutable binding between organization facts, project code, and sidecar stores."""

    kind: Literal["runtime_workspace_binding"] = "runtime_workspace_binding"
    schema_version: Literal["v0.1"] = "v0.1"
    organization_id: OrganizationId
    organization_root: NonEmptyStr
    organization_manifest_sha256: Sha256
    project_id: ProjectId
    project_root: NonEmptyStr
    project_workspace_root: NonEmptyStr
    project_manifest_sha256: Sha256
    project_profile_sha256: Sha256
    paths: RuntimePaths
    bound_at: AwareDatetime
    binding_sha256: Sha256

    @field_validator("organization_root", "project_root", "project_workspace_root")
    @classmethod
    def validate_absolute_path(cls, value: str) -> str:
        if not Path(value).is_absolute() or any(ord(character) < 32 for character in value):
            raise ValueError("runtime workspace roots must be absolute and contain no controls")
        return value

    @model_validator(mode="after")
    def validate_bound_paths(self) -> Self:
        project = Path(self.project_root)
        sidecar = Path(self.project_workspace_root)
        organization = Path(self.organization_root)
        if _paths_overlap(project, sidecar):
            raise ValueError("project root and sidecar must not overlap")
        if _paths_overlap(project, organization) or _paths_overlap(sidecar, organization):
            raise ValueError("organization root must not overlap project or sidecar")
        expected = _runtime_paths(sidecar)
        if self.paths != expected:
            raise ValueError("RuntimePaths do not match the fixed project sidecar layout")
        return self

    def validate_integrity(self) -> None:
        if self.binding_sha256 != _binding_digest(self):
            raise RuntimeWorkspaceCorruption("runtime binding digest does not match content")

    def validate_environment(self) -> None:
        """Reopen every durable boundary and reject stale or tampered bindings."""
        self.validate_integrity()
        organization = OrganizationWorkspace.open(
            self.organization_root,
            organization_id=self.organization_id,
        )
        if organization.manifest.manifest_sha256 != self.organization_manifest_sha256:
            raise RuntimeWorkspaceConflict("organization manifest changed after binding")
        sidecar = Path(self.project_workspace_root)
        manifest_path = sidecar / "workspace.json"
        try:
            manifest = ProjectWorkspaceManifest.model_validate(
                json.loads(manifest_path.read_text(encoding="utf-8"))
            )
            manifest.validate_binding(sidecar)
            profile = ProjectProfile.model_validate(
                json.loads((sidecar / "profile" / PROJECT_PROFILE_NAME).read_text(encoding="utf-8"))
            )
            profile.validate_integrity()
            persisted = RuntimeWorkspaceBinding.model_validate(
                json.loads((sidecar / "policy" / RUNTIME_BINDING_NAME).read_text(encoding="utf-8"))
            )
            persisted.validate_integrity()
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValidationError,
            ProjectWorkspaceError,
        ) as error:
            raise RuntimeWorkspaceCorruption("runtime workspace records are invalid") from error
        if (
            manifest.project_id != self.project_id
            or manifest.project_root != self.project_root
            or manifest.ai_workspace_root != self.project_workspace_root
            or manifest.manifest_sha256 != self.project_manifest_sha256
        ):
            raise RuntimeWorkspaceConflict("project manifest changed after binding")
        if (
            profile.project_id != self.project_id
            or profile.profile_sha256 != self.project_profile_sha256
        ):
            raise RuntimeWorkspaceConflict("ProjectProfile changed after binding")
        if persisted != self:
            raise RuntimeWorkspaceConflict("persisted RuntimeWorkspaceBinding does not match")
        observed = ProjectProfile.discover(
            self.project_root,
            project_id=self.project_id,
            observed_at=self.bound_at,
        )
        if observed.profile_sha256 != self.project_profile_sha256:
            raise RuntimeWorkspaceConflict("target project facts changed after binding")

    def validate_task_repository(self, repository: str | Path) -> Path:
        resolved = Path(repository).expanduser().resolve(strict=False)
        if resolved != Path(self.project_root) or not resolved.is_dir():
            raise RuntimeWorkspaceConflict("Task repository does not match bound project root")
        return resolved

    def compose_runtime_config(
        self,
        config: RuntimeConfig,
        compiled_spec: CompiledSpec,
    ) -> RuntimeConfig:
        """Replace legacy relative stores and inject the exact compiled spec source."""
        self.validate_environment()
        compiled_spec.validate_integrity()
        if compiled_spec.project_id != self.project_id:
            raise RuntimeWorkspaceConflict("CompiledSpec belongs to another project")
        source = compiled_spec.to_context_source()
        if any(item.source_id == source.source_id for item in config.context_sources):
            raise RuntimeWorkspaceConflict("runtime config already declares compiled.spec source")
        payload = config.to_wire()
        payload["paths"] = self.paths.to_wire()
        payload["context_sources"] = [
            *(item.to_wire() for item in config.context_sources),
            source.to_wire(),
        ]
        payload["spec_version"] = f"compiled-{compiled_spec.compiled_sha256}"
        return RuntimeConfig.model_validate(payload)


class RuntimeWorkspaceBinder:
    """Validate and persist one organization/project RuntimeWorkspaceBinding."""

    def bind(
        self,
        organization: OrganizationWorkspace,
        project: ProjectWorkspace,
        profile: ProjectProfile,
        *,
        bound_at: datetime,
    ) -> RuntimeWorkspaceBinding:
        _require_aware(bound_at, "binding time")
        organization = OrganizationWorkspace.open(
            organization.root,
            organization_id=organization.organization_id,
        )
        try:
            disk_manifest = ProjectWorkspaceManifest.model_validate(
                json.loads(project.manifest_path.read_text(encoding="utf-8"))
            )
            disk_manifest.validate_binding(project.root)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValidationError,
            ProjectWorkspaceError,
        ) as error:
            raise RuntimeWorkspaceCorruption("project workspace manifest is invalid") from error
        if disk_manifest != project.manifest:
            raise RuntimeWorkspaceConflict("project workspace handle does not match disk manifest")
        profile.validate_integrity()
        if profile.project_id != project.project_id:
            raise RuntimeWorkspaceConflict("ProjectProfile belongs to another project")
        observed = ProjectProfile.discover(
            project.project_root,
            project_id=project.project_id,
            observed_at=bound_at,
        )
        if observed.profile_sha256 != profile.profile_sha256:
            raise RuntimeWorkspaceConflict("ProjectProfile does not match current project facts")
        provisional = RuntimeWorkspaceBinding(
            organization_id=organization.organization_id,
            organization_root=str(organization.root),
            organization_manifest_sha256=organization.manifest.manifest_sha256,
            project_id=project.project_id,
            project_root=str(project.project_root),
            project_workspace_root=str(project.root),
            project_manifest_sha256=project.manifest.manifest_sha256,
            project_profile_sha256=profile.profile_sha256,
            paths=_runtime_paths(project.root),
            bound_at=bound_at,
            binding_sha256="0" * 64,
        )
        binding = provisional.model_copy(update={"binding_sha256": _binding_digest(provisional)})
        binding.validate_integrity()
        _put_immutable_model(
            project.directory("profile") / PROJECT_PROFILE_NAME,
            profile,
            timestamp_field="observed_at",
        )
        persisted = _put_immutable_model(
            project.directory("policy") / RUNTIME_BINDING_NAME,
            binding,
            timestamp_field="bound_at",
        )
        resolved = cast(RuntimeWorkspaceBinding, persisted)
        resolved.validate_environment()
        return resolved


class FileOrganizationWorkforceStore:
    """Organization-owned, integrity-wrapped AgentProfile and ModelPolicy records."""

    def __init__(self, workspace: OrganizationWorkspace) -> None:
        self._workspace = OrganizationWorkspace.open(
            workspace.root,
            organization_id=workspace.organization_id,
        )

    def put_agent(self, profile: AgentProfile) -> AgentProfile:
        return self._put("agent_profile", profile.id, profile, self._workspace.directory("agents"))

    def get_agent(self, agent_id: AgentId | str) -> AgentProfile:
        validated = TypeAdapter(AgentId).validate_python(agent_id)
        payload = self._get("agent_profile", validated, self._workspace.directory("agents"))
        try:
            return AgentProfile.model_validate(payload)
        except ValidationError as error:
            raise RuntimeWorkspaceCorruption(f"AgentProfile is invalid: {validated}") from error

    def put_policy(self, policy: ModelPolicy) -> ModelPolicy:
        return self._put(
            "model_policy",
            policy.id,
            policy,
            self._workspace.directory("model-policies"),
        )

    def get_policy(self, policy_id: ModelPolicyId | str) -> ModelPolicy:
        validated = TypeAdapter(ModelPolicyId).validate_python(policy_id)
        payload = self._get(
            "model_policy",
            validated,
            self._workspace.directory("model-policies"),
        )
        try:
            return ModelPolicy.model_validate(payload)
        except ValidationError as error:
            raise RuntimeWorkspaceCorruption(f"ModelPolicy is invalid: {validated}") from error

    @staticmethod
    def _put[ModelT: AgentProfile | ModelPolicy](
        kind: str,
        object_id: str,
        model: ModelT,
        root: Path,
    ) -> ModelT:
        payload = model.to_wire()
        envelope: WirePayload = {
            "kind": kind,
            "object_id": object_id,
            "payload": payload,
            "sha256": _sha256(_canonical_json(payload)),
        }
        path = root / f"{object_id}.json"
        if path.exists():
            existing = FileOrganizationWorkforceStore._get(kind, object_id, root)
            if existing != payload:
                raise RuntimeWorkspaceConflict(
                    f"organization workforce record already exists: {object_id}"
                )
            return model
        _atomic_json_write(path, envelope)
        return model

    @staticmethod
    def _get(kind: str, object_id: str, root: Path) -> WirePayload:
        path = root / f"{object_id}.json"
        if not path.is_file():
            raise RuntimeWorkspaceCorruption(
                f"organization workforce record is missing: {object_id}"
            )
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise RuntimeWorkspaceCorruption(
                f"organization workforce record is invalid: {object_id}"
            ) from error
        if not isinstance(envelope, dict):
            raise RuntimeWorkspaceCorruption(
                f"organization workforce record is invalid: {object_id}"
            )
        payload = envelope.get("payload")
        if (
            envelope.get("kind") != kind
            or envelope.get("object_id") != object_id
            or not isinstance(payload, dict)
            or envelope.get("sha256") != _sha256(_canonical_json(payload))
        ):
            raise RuntimeWorkspaceCorruption(
                f"organization workforce record integrity failed: {object_id}"
            )
        return cast(WirePayload, payload)


class RuntimeAgentRun(DomainModel):
    """Resolved existing AgentDefinition plus its auditable organization allocation."""

    kind: Literal["runtime_agent_run"] = "runtime_agent_run"
    allocation: AgentRunAllocation
    agent_definition: AgentDefinition
    code_root: NonEmptyStr

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if (
            self.agent_definition.id != self.allocation.agent_id
            or self.agent_definition.role is not self.allocation.role
            or self.agent_definition.model != self.allocation.model_selection.model
            or self.agent_definition.provider != self.allocation.model_selection.provider
        ):
            raise ValueError("AgentDefinition does not match AgentRunAllocation")
        if not Path(self.code_root).is_absolute():
            raise ValueError("runtime Agent code_root must be absolute")
        return self


class RuntimeWorkforceResolver:
    """Resolve persisted organization facts into one existing runtime AgentDefinition."""

    def __init__(
        self,
        binding: RuntimeWorkspaceBinding,
        workforce: FileOrganizationWorkforceStore,
        config: RuntimeConfig,
    ) -> None:
        binding.validate_environment()
        self._binding = binding
        self._workforce = workforce
        self._config = config

    def resolve(
        self,
        *,
        work_item: WorkItem,
        assignment: RoleAssignment,
        lease: TaskLease,
        selection: ModelSelection,
        context_manifest_id: ContextId,
        compiled_spec: CompiledSpec,
        allocated_at: datetime,
    ) -> RuntimeAgentRun:
        """Validate Lease/model/context/spec facts and create an AgentRunAllocation."""
        _require_aware(allocated_at, "allocation time")
        self._validate_scheduling(work_item, assignment, lease, allocated_at)
        agent = self._workforce.get_agent(assignment.agent_id)
        policy = self._workforce.get_policy(selection.policy_id)
        self._validate_workforce(agent, policy, work_item, assignment, selection, allocated_at)
        compiled_spec.validate_integrity()
        if (
            compiled_spec.project_id != self._binding.project_id
            or compiled_spec.task_id != assignment.task_id
        ):
            raise RuntimeAllocationError("CompiledSpec does not match allocation project/Task")
        try:
            context = FileContextStore(self._binding.paths.contexts).get(context_manifest_id)
        except ContextStoreError as error:
            raise RuntimeAllocationError("Context manifest is missing or invalid") from error
        if (
            context.task_id != assignment.task_id
            or context.role is not assignment.role
            or context.attempt != assignment.attempt
        ):
            raise RuntimeAllocationError("Context manifest does not match assignment")
        expected_source = compiled_spec.to_context_source()
        expected_hash = _sha256(cast(str, expected_source.content))
        if not any(
            section.uri == expected_source.uri and section.sha256 == expected_hash
            for section in context.sections
        ):
            raise RuntimeAllocationError("Context manifest does not contain the exact CompiledSpec")
        base_definition = self._config.agent_definitions()[assignment.role]
        definition = base_definition.model_copy(
            update={
                "id": agent.id,
                "version": agent.version,
                "model": selection.model,
                "provider": selection.provider,
                "metadata": {
                    **base_definition.metadata,
                    "organization_id": self._binding.organization_id,
                    "agent_profile_version": agent.version,
                    "model_policy_id": policy.id,
                    "model_policy_version": policy.version,
                },
            }
        )
        policy_payload = definition.permissions.to_wire()
        tool_policy_ref = (
            f"policy://{self._binding.project_id}/{assignment.role.value}/"
            f"{_sha256(_canonical_json(policy_payload))}"
        )
        run_seed = {
            "assignment_id": assignment.id,
            "context_manifest_id": context.context_id,
            "model": selection.to_wire(),
            "prompt_version": self._config.prompt_version,
            "spec_version": compiled_spec.compiled_sha256,
            "tool_policy_ref": tool_policy_ref,
        }
        allocation = AgentRunAllocation(
            run_id=f"run_{_sha256(_canonical_json(run_seed))[:32]}",
            assignment_id=assignment.id,
            project_id=assignment.project_id,
            task_id=assignment.task_id,
            agent_id=assignment.agent_id,
            role=assignment.role,
            attempt=assignment.attempt,
            model_selection=selection,
            context_manifest_id=context.context_id,
            prompt_version=self._config.prompt_version,
            spec_version=compiled_spec.compiled_sha256,
            tool_policy_ref=tool_policy_ref,
            allocated_at=allocated_at,
        )
        return RuntimeAgentRun(
            allocation=allocation,
            agent_definition=definition,
            code_root=self._binding.project_root,
        )

    def _validate_scheduling(
        self,
        item: WorkItem,
        assignment: RoleAssignment,
        lease: TaskLease,
        allocated_at: datetime,
    ) -> None:
        if item.project_id != self._binding.project_id or assignment.project_id != item.project_id:
            raise RuntimeAllocationError("WorkItem/Assignment belongs to another project")
        if item.task_id != assignment.task_id:
            raise RuntimeAllocationError("WorkItem and Assignment Task IDs do not match")
        if is_waiting(item.status) or item.status is WorkItemStatus.CLOSED:
            raise RuntimeAllocationError("waiting or closed WorkItem cannot allocate an Agent Run")
        if assignment.assigned_at > allocated_at:
            raise RuntimeAllocationError("Assignment occurs after allocation time")
        if (
            assignment.lease_id != lease.id
            or lease.assignment_id != assignment.id
            or lease.task_id != assignment.task_id
            or lease.agent_id != assignment.agent_id
            or lease.capacity_units != assignment.capacity_units
        ):
            raise RuntimeAllocationError("TaskLease does not match RoleAssignment")
        if lease.acquired_at < assignment.assigned_at:
            raise RuntimeAllocationError("TaskLease predates its RoleAssignment")
        if not lease_is_active(lease, at=allocated_at):
            raise RuntimeAllocationError("TaskLease is not active at allocation time")

    @staticmethod
    def _validate_workforce(
        agent: AgentProfile,
        policy: ModelPolicy,
        item: WorkItem,
        assignment: RoleAssignment,
        selection: ModelSelection,
        allocated_at: datetime,
    ) -> None:
        if not agent.active or agent.id != assignment.agent_id:
            raise RuntimeAllocationError("AgentProfile is inactive or identity-mismatched")
        if assignment.role not in agent.eligible_roles:
            raise RuntimeAllocationError("AgentProfile is not eligible for assignment role")
        missing = set(item.required_capabilities) - set(agent.capabilities)
        if missing:
            raise RuntimeAllocationError(
                "AgentProfile lacks WorkItem capabilities: " + ", ".join(sorted(missing))
            )
        if agent.default_model_policy_id != policy.id:
            raise RuntimeAllocationError("AgentProfile and ModelPolicy do not match")
        if selection.policy_id != policy.id or selection.policy_version != policy.version:
            raise RuntimeAllocationError("ModelSelection does not match ModelPolicy version")
        if selection.selected_at > allocated_at:
            raise RuntimeAllocationError("ModelSelection occurs after allocation time")
        if not any(
            route.provider == selection.provider
            and route.model == selection.model
            and route.tier is selection.tier
            for route in policy.routes
        ):
            raise RuntimeAllocationError("ModelSelection route is absent from ModelPolicy")


def _runtime_paths(sidecar: Path) -> RuntimePaths:
    root = sidecar.resolve(strict=False)
    return RuntimePaths(
        database=str(root / "state" / "state.sqlite3"),
        artifacts=str(root / "artifacts"),
        contexts=str(root / "contexts"),
        evaluation_events=str(root / "evaluations"),
        handoffs=str(root / "handoffs"),
        evidence=str(root / "evidence"),
        runs=str(root / "runs"),
    )


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _organization_digest(manifest: OrganizationWorkspaceManifest) -> Sha256:
    payload = manifest.model_dump(mode="json", exclude={"created_at", "manifest_sha256"})
    return _sha256(_canonical_json(payload))


def _binding_digest(binding: RuntimeWorkspaceBinding) -> Sha256:
    payload = binding.model_dump(mode="json", exclude={"bound_at", "binding_sha256"})
    return _sha256(_canonical_json(payload))


def _put_immutable_model(
    path: Path,
    model: DomainModel,
    *,
    timestamp_field: str,
) -> DomainModel:
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            existing = type(model).model_validate(payload)
            validator = getattr(existing, "validate_integrity", None)
            if callable(validator):
                validator()
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as error:
            raise RuntimeWorkspaceCorruption(f"workspace record is invalid: {path.name}") from error
        left = existing.model_dump(mode="python", exclude={timestamp_field})
        right = model.model_dump(mode="python", exclude={timestamp_field})
        if left != right:
            raise RuntimeWorkspaceConflict(f"workspace record already exists: {path.name}")
        return existing
    _atomic_json_write(path, model.to_wire())
    return model


def _atomic_json_write(path: Path, payload: WirePayload) -> None:
    encoded = _canonical_json(payload).encode("utf-8")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    except OSError as error:
        raise RuntimeWorkspaceError(f"cannot persist workspace record: {path}") from error
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)


def _remove_staging(path: Path) -> None:
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_dir():
            child.rmdir()
        else:
            child.unlink()
    path.rmdir()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(value: str) -> Sha256:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


__all__ = [
    "ORGANIZATION_DIRECTORIES",
    "ORGANIZATION_MANIFEST_NAME",
    "FileOrganizationWorkforceStore",
    "OrganizationId",
    "OrganizationLayout",
    "OrganizationWorkspace",
    "OrganizationWorkspaceError",
    "OrganizationWorkspaceManifest",
    "RuntimeAgentRun",
    "RuntimeAllocationError",
    "RuntimeWorkforceResolver",
    "RuntimeWorkspaceBinder",
    "RuntimeWorkspaceBinding",
    "RuntimeWorkspaceConflict",
    "RuntimeWorkspaceCorruption",
    "RuntimeWorkspaceError",
]
