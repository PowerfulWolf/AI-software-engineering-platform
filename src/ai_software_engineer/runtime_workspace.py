"""Team workforce/repository binding and run-scoped workforce resolution."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Final, Literal, Self, cast

from pydantic import (
    AwareDatetime,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from ai_software_engineer.context import ContextStoreError, FileContextStore
from ai_software_engineer.domain import AgentDefinition, TeamRole, WorkItemStatus
from ai_software_engineer.domain.agent import AgentId
from ai_software_engineer.domain.identity import ContextId, ProjectId, RepositoryId, TeamId
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
from ai_software_engineer.project_workspace import ProjectManifest
from ai_software_engineer.repository_profile import RepositoryProfile, Sha256
from ai_software_engineer.repository_workspace import (
    RepositoryWorkspace,
    RepositoryWorkspaceError,
    RepositoryWorkspaceManifest,
)
from ai_software_engineer.runtime import RuntimeConfig, RuntimePaths
from ai_software_engineer.spec_compiler import CompiledSpec
from ai_software_engineer.team_workspace import TeamManifest, TeamWorkspace

# Team workforce records live directly in the single Team workspace.  These names
# remain exported while v0.2 callers migrate from the former nested workforce root.
TEAM_WORKFORCE_MANIFEST_NAME: Final = "team.json"
TEAM_WORKFORCE_DIRECTORIES: Final[tuple[str, ...]] = (
    "agents",
    "model-policies",
    "work-items",
    "leases",
    "metrics",
)
REPOSITORY_PROFILE_NAME: Final = "repository-profile.json"
RUNTIME_BINDING_NAME: Final = "runtime-workspace-binding.json"


def _versioned_record_path(directory: Path, name: str, sha256: str) -> Path:
    validated = TypeAdapter(Sha256).validate_python(sha256)
    if directory.is_symlink():
        raise RuntimeWorkspaceCorruption("workspace record directory cannot be a symlink")
    return directory / f"{Path(name).stem}-{validated}.json"


def _record_read_path(directory: Path, name: str, sha256: str) -> Path:
    versioned = _versioned_record_path(directory, name, sha256)
    target = versioned if versioned.exists() or versioned.is_symlink() else directory / name
    if target.is_symlink():
        raise RuntimeWorkspaceCorruption("workspace record cannot be a symlink")
    return target


def load_repository_profile(sidecar: Path, profile_sha256: str) -> RepositoryProfile:
    """Read the exact profile snapshot; legacy fallback must match the requested digest."""
    path = _record_read_path(sidecar / "profile", REPOSITORY_PROFILE_NAME, profile_sha256)
    try:
        profile = RepositoryProfile.model_validate_json(path.read_text(encoding="utf-8"))
        profile.validate_integrity()
    except (OSError, UnicodeError, ValueError) as error:
        raise RuntimeWorkspaceCorruption("repository profile record is invalid") from error
    if profile.profile_sha256 != profile_sha256:
        raise RuntimeWorkspaceConflict("RepositoryProfile snapshot digest does not match")
    return profile


class RuntimeWorkspaceError(RuntimeError):
    """Base error for Team workforce/repository composition failures."""


class TeamWorkforceWorkspaceError(RuntimeWorkspaceError):
    """Raised when the Team workforce workspace is missing or untrusted."""


class RuntimeWorkspaceConflict(RuntimeWorkspaceError):
    """Raised when an immutable binding or workforce record conflicts."""


class RuntimeWorkspaceCorruption(RuntimeWorkspaceError):
    """Raised when a durable workspace record fails validation or integrity."""


class RuntimeAllocationError(RuntimeWorkspaceError):
    """Raised when workforce facts cannot safely authorize an Agent Run."""


class TeamWorkforceWorkspace:
    """Compatibility facade exposing workforce stores from the single Team root.

    This is deliberately not another aggregate or filesystem layer.  New code should
    pass :class:`TeamWorkspace` directly where possible.
    """

    def __init__(self, workspace: TeamWorkspace) -> None:
        self._workspace = workspace
        self.manifest = workspace.manifest

    @classmethod
    def from_team(cls, workspace: TeamWorkspace) -> TeamWorkforceWorkspace:
        workspace.validate_current()
        return cls(workspace)

    @classmethod
    def initialize(
        cls,
        root: str | Path,
        *,
        team_id: TeamId | str,
        created_at: datetime,
    ) -> TeamWorkforceWorkspace:
        """Open the Team at ``root``; retained for source compatibility only."""
        _require_aware(created_at, "Team workforce created_at")
        resolved = Path(root).expanduser().resolve(strict=False)
        if resolved.name != "team":
            raise TeamWorkforceWorkspaceError("Team workforce root must be the Team root")
        manifest_path = resolved / TEAM_WORKFORCE_MANIFEST_NAME
        if not manifest_path.is_file():
            raise TeamWorkforceWorkspaceError(
                "initialize the TeamWorkspace before opening its workforce stores"
            )
        return cls.open(resolved, team_id=team_id)

    @classmethod
    def open(
        cls,
        root: str | Path,
        *,
        team_id: TeamId | str | None = None,
    ) -> TeamWorkforceWorkspace:
        resolved = Path(root).expanduser().resolve(strict=False)
        manifest_path = resolved / TEAM_WORKFORCE_MANIFEST_NAME
        try:
            manifest = TeamManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            manifest.validate_integrity()
            workspace = TeamWorkspace.initialize(
                manifest.platform_root,
                team_id=manifest.team_id,
                name=manifest.name,
                read_only=True,
            )
        except (OSError, UnicodeError, ValueError, ValidationError) as error:
            raise RuntimeWorkspaceCorruption(
                f"Team workforce manifest is invalid: {manifest_path}"
            ) from error
        if workspace.root != resolved:
            raise RuntimeWorkspaceCorruption("Team workforce manifest root does not match its path")
        if team_id is not None:
            expected = TypeAdapter(TeamId).validate_python(team_id)
            if manifest.team_id != expected:
                raise RuntimeWorkspaceConflict(
                    "Team ID does not match existing workforce workspace"
                )
        for directory in TEAM_WORKFORCE_DIRECTORIES:
            path = resolved / directory
            if path.is_symlink() or not path.is_dir():
                raise RuntimeWorkspaceCorruption(
                    f"Team workforce layout is missing or unsafe: {directory}"
                )
        return cls(workspace)

    @property
    def root(self) -> Path:
        return self._workspace.root

    @property
    def team_id(self) -> TeamId:
        return self.manifest.team_id

    def directory(
        self, name: Literal["agents", "model-policies", "work-items", "leases", "metrics"]
    ) -> Path:
        if name not in TEAM_WORKFORCE_DIRECTORIES:
            raise TeamWorkforceWorkspaceError(f"unknown Team workforce directory: {name}")
        return self._workspace.directory(name)


class RuntimeWorkspaceBinding(DomainModel):
    """Immutable binding between Team facts, repository code and sidecar stores."""

    kind: Literal["runtime_workspace_binding"] = "runtime_workspace_binding"
    schema_version: Literal["v0.2"] = "v0.2"
    team_id: TeamId
    team_root: NonEmptyStr
    team_manifest_sha256: Sha256
    project_id: ProjectId
    project_root: NonEmptyStr
    project_manifest_sha256: Sha256
    repository_id: RepositoryId
    repository_root: NonEmptyStr
    repository_workspace_root: NonEmptyStr
    repository_manifest_sha256: Sha256
    repository_profile_sha256: Sha256
    paths: RuntimePaths
    bound_at: AwareDatetime
    binding_sha256: Sha256

    @field_validator("team_root", "project_root", "repository_root", "repository_workspace_root")
    @classmethod
    def validate_absolute_path(cls, value: str) -> str:
        if not Path(value).is_absolute() or any(ord(character) < 32 for character in value):
            raise ValueError("runtime workspace roots must be absolute and contain no controls")
        return value

    @model_validator(mode="after")
    def validate_bound_paths(self) -> Self:
        project = Path(self.project_root)
        repository = Path(self.repository_root)
        sidecar = Path(self.repository_workspace_root)
        workforce = Path(self.team_root)
        if sidecar.parent.parent != project:
            raise ValueError("Repository sidecar must belong to the bound Project")
        if _paths_overlap(repository, sidecar):
            raise ValueError("repository root and sidecar must not overlap")
        if _paths_overlap(repository, workforce) or _paths_overlap(sidecar, workforce):
            raise ValueError("Team root must not overlap repository or sidecar")
        expected = _runtime_paths(sidecar)
        if self.paths != expected:
            raise ValueError("RuntimePaths do not match the fixed repository sidecar layout")
        return self

    def validate_integrity(self) -> None:
        if self.binding_sha256 != _binding_digest(self):
            raise RuntimeWorkspaceCorruption("runtime binding digest does not match content")

    def validate_environment(self) -> None:
        """Reopen every durable boundary and reject stale or tampered bindings."""
        self.validate_integrity()
        workforce = TeamWorkforceWorkspace.open(
            self.team_root,
            team_id=self.team_id,
        )
        if workforce.manifest.manifest_sha256 != self.team_manifest_sha256:
            raise RuntimeWorkspaceConflict("Team manifest changed after binding")
        project_root = Path(self.project_root)
        try:
            project_manifest = ProjectManifest.model_validate_json(
                (project_root / "project.json").read_text(encoding="utf-8")
            )
            project_manifest.validate_integrity()
        except (OSError, UnicodeError, ValueError, ValidationError) as error:
            raise RuntimeWorkspaceCorruption("Project workspace record is invalid") from error
        if (
            project_manifest.team_id != self.team_id
            or project_manifest.team_manifest_sha256 != self.team_manifest_sha256
            or project_manifest.project_id != self.project_id
            or project_manifest.project_root != self.project_root
            or project_manifest.manifest_sha256 != self.project_manifest_sha256
        ):
            raise RuntimeWorkspaceConflict("Project manifest changed after binding")
        sidecar = Path(self.repository_workspace_root)
        manifest_path = sidecar / "workspace.json"
        try:
            manifest = RepositoryWorkspaceManifest.model_validate(
                json.loads(manifest_path.read_text(encoding="utf-8"))
            )
            manifest.validate_binding(sidecar)
            profile = load_repository_profile(sidecar, self.repository_profile_sha256)
            persisted = RuntimeWorkspaceBinding.model_validate(
                json.loads(
                    _record_read_path(
                        sidecar / "policy", RUNTIME_BINDING_NAME, self.binding_sha256
                    ).read_text(encoding="utf-8")
                )
            )
            persisted.validate_integrity()
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValidationError,
            RepositoryWorkspaceError,
        ) as error:
            raise RuntimeWorkspaceCorruption("runtime workspace records are invalid") from error
        if (
            manifest.repository_id != self.repository_id
            or manifest.project_id != self.project_id
            or manifest.project_manifest_sha256 != self.project_manifest_sha256
            or manifest.repository_root != self.repository_root
            or manifest.ai_workspace_root != self.repository_workspace_root
            or manifest.manifest_sha256 != self.repository_manifest_sha256
        ):
            raise RuntimeWorkspaceConflict("project manifest changed after binding")
        if (
            profile.repository_id != self.repository_id
            or profile.profile_sha256 != self.repository_profile_sha256
        ):
            raise RuntimeWorkspaceConflict("RepositoryProfile changed after binding")
        if persisted != self:
            raise RuntimeWorkspaceConflict("persisted RuntimeWorkspaceBinding does not match")
        observed = RepositoryProfile.discover(
            self.repository_root,
            repository_id=self.repository_id,
            observed_at=self.bound_at,
        )
        if observed.profile_sha256 != self.repository_profile_sha256:
            raise RuntimeWorkspaceConflict("target repository facts changed after binding")

    def validate_task_repository(self, repository: str | Path) -> Path:
        resolved = Path(repository).expanduser().resolve(strict=False)
        if resolved != Path(self.repository_root) or not resolved.is_dir():
            raise RuntimeWorkspaceConflict("Task repository does not match bound repository root")
        return resolved

    def compose_runtime_config(
        self,
        config: RuntimeConfig,
        compiled_spec: CompiledSpec,
    ) -> RuntimeConfig:
        """Bind configured stores to the sidecar and inject the exact compiled spec source."""
        self.validate_environment()
        compiled_spec.validate_integrity()
        if compiled_spec.repository_id != self.repository_id:
            raise RuntimeWorkspaceConflict("CompiledSpec belongs to another repository")
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
    """Validate and persist one Team workforce/repository RuntimeWorkspaceBinding."""

    def __init__(self, *, versioned: bool = False) -> None:
        self._versioned = versioned

    def bind(
        self,
        workforce: TeamWorkforceWorkspace,
        repository: RepositoryWorkspace,
        profile: RepositoryProfile,
        *,
        bound_at: datetime,
    ) -> RuntimeWorkspaceBinding:
        _require_aware(bound_at, "binding time")
        workforce = TeamWorkforceWorkspace.open(
            workforce.root,
            team_id=workforce.team_id,
        )
        try:
            disk_manifest = RepositoryWorkspaceManifest.model_validate(
                json.loads(repository.manifest_path.read_text(encoding="utf-8"))
            )
            disk_manifest.validate_binding(repository.root)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValidationError,
            RepositoryWorkspaceError,
        ) as error:
            raise RuntimeWorkspaceCorruption("project workspace manifest is invalid") from error
        if disk_manifest != repository.manifest:
            raise RuntimeWorkspaceConflict(
                "repository workspace handle does not match disk manifest"
            )
        profile.validate_integrity()
        if profile.repository_id != repository.repository_id:
            raise RuntimeWorkspaceConflict("RepositoryProfile belongs to another repository")
        observed = RepositoryProfile.discover(
            repository.repository_root,
            repository_id=repository.repository_id,
            observed_at=bound_at,
        )
        if observed.profile_sha256 != profile.profile_sha256:
            raise RuntimeWorkspaceConflict(
                "RepositoryProfile does not match current repository facts"
            )
        provisional = RuntimeWorkspaceBinding(
            team_id=workforce.team_id,
            team_root=str(workforce.root),
            team_manifest_sha256=workforce.manifest.manifest_sha256,
            project_id=repository.manifest.project_id,
            project_root=str(repository.root.parent.parent),
            project_manifest_sha256=repository.manifest.project_manifest_sha256,
            repository_id=repository.repository_id,
            repository_root=str(repository.repository_root),
            repository_workspace_root=str(repository.root),
            repository_manifest_sha256=repository.manifest.manifest_sha256,
            repository_profile_sha256=profile.profile_sha256,
            paths=_runtime_paths(repository.root),
            bound_at=bound_at,
            binding_sha256="0" * 64,
        )
        binding = provisional.model_copy(update={"binding_sha256": _binding_digest(provisional)})
        binding.validate_integrity()
        profile_path = repository.directory("profile") / REPOSITORY_PROFILE_NAME
        binding_path = repository.directory("policy") / RUNTIME_BINDING_NAME
        if self._versioned:
            if profile_path.is_symlink():
                raise RuntimeWorkspaceCorruption("legacy profile cannot be a symlink")
            legacy = None
            if profile_path.exists():
                try:
                    legacy = RepositoryProfile.model_validate_json(
                        profile_path.read_text(encoding="utf-8")
                    )
                    legacy.validate_integrity()
                except (OSError, UnicodeError, ValueError) as error:
                    raise RuntimeWorkspaceCorruption("legacy profile record is invalid") from error
            if legacy is None or legacy.profile_sha256 != profile.profile_sha256:
                profile_path = _versioned_record_path(
                    repository.directory("profile"), REPOSITORY_PROFILE_NAME, profile.profile_sha256
                )
                binding_path = _versioned_record_path(
                    repository.directory("policy"), RUNTIME_BINDING_NAME, binding.binding_sha256
                )
        _put_immutable_model(
            profile_path,
            profile,
            timestamp_field="observed_at",
        )
        persisted = _put_immutable_model(
            binding_path,
            binding,
            timestamp_field="bound_at",
        )
        resolved = cast(RuntimeWorkspaceBinding, persisted)
        resolved.validate_environment()
        return resolved


class FileTeamWorkforceStore:
    """Team-owned, integrity-wrapped AgentProfile and ModelPolicy records."""

    def __init__(self, workspace: TeamWorkforceWorkspace) -> None:
        self._workspace = TeamWorkforceWorkspace.open(
            workspace.root,
            team_id=workspace.team_id,
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

    def put_policy(self, policy: ModelPolicy, *, versioned: bool = False) -> ModelPolicy:
        return self._put(
            "model_policy",
            self._policy_key(policy.id, policy.version) if versioned else policy.id,
            policy,
            self._workspace.directory("model-policies"),
        )

    def get_policy(
        self, policy_id: ModelPolicyId | str, *, version: str | None = None
    ) -> ModelPolicy:
        validated = TypeAdapter(ModelPolicyId).validate_python(policy_id)
        root = self._workspace.directory("model-policies")
        key = validated
        if version is not None:
            revision_key = self._policy_key(validated, version)
            path = root / f"{revision_key}.json"
            if path.exists() or path.is_symlink():
                key = revision_key
        payload = self._get(
            "model_policy",
            key,
            root,
        )
        try:
            policy = ModelPolicy.model_validate(payload)
        except ValidationError as error:
            raise RuntimeWorkspaceCorruption(f"ModelPolicy is invalid: {validated}") from error
        if policy.id != validated or (version is not None and policy.version != version):
            raise RuntimeWorkspaceCorruption("ModelPolicy identity/version mismatch")
        return policy

    @staticmethod
    def _policy_key(policy_id: str, version: str) -> str:
        return f"{policy_id}__{_sha256(version)}"

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
        if path.is_symlink():
            raise RuntimeWorkspaceCorruption("workforce record cannot be a symlink")
        if path.exists():
            existing = FileTeamWorkforceStore._get(kind, object_id, root)
            if existing != payload:
                raise RuntimeWorkspaceConflict(f"Team workforce record already exists: {object_id}")
            return model
        if not _atomic_json_write(path, envelope, overwrite=False):
            return FileTeamWorkforceStore._put(kind, object_id, model, root)
        return model

    @staticmethod
    def _get(kind: str, object_id: str, root: Path) -> WirePayload:
        path = root / f"{object_id}.json"
        if path.is_symlink():
            raise RuntimeWorkspaceCorruption("workforce record cannot be a symlink")
        if not path.is_file():
            raise RuntimeWorkspaceCorruption(f"Team workforce record is missing: {object_id}")
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise RuntimeWorkspaceCorruption(
                f"Team workforce record is invalid: {object_id}"
            ) from error
        if not isinstance(envelope, dict):
            raise RuntimeWorkspaceCorruption(f"Team workforce record is invalid: {object_id}")
        payload = envelope.get("payload")
        if (
            envelope.get("kind") != kind
            or envelope.get("object_id") != object_id
            or not isinstance(payload, dict)
            or envelope.get("sha256") != _sha256(_canonical_json(payload))
        ):
            raise RuntimeWorkspaceCorruption(f"Team workforce record integrity failed: {object_id}")
        return cast(WirePayload, payload)


class RuntimeAgentRun(DomainModel):
    """Resolved existing AgentDefinition plus its auditable Team allocation."""

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
    """Resolve persisted Team facts into one existing runtime AgentDefinition."""

    def __init__(
        self,
        binding: RuntimeWorkspaceBinding,
        workforce: FileTeamWorkforceStore,
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
        policy = self._workforce.get_policy(selection.policy_id, version=selection.policy_version)
        self._validate_workforce(agent, policy, work_item, assignment, selection, allocated_at)
        compiled_spec.validate_integrity()
        if (
            compiled_spec.repository_id != self._binding.repository_id
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
                    "team_id": self._binding.team_id,
                    "agent_profile_version": agent.version,
                    "model_policy_id": policy.id,
                    "model_policy_version": policy.version,
                },
            }
        )
        policy_payload = definition.permissions.to_wire()
        tool_policy_ref = (
            f"policy://{self._binding.repository_id}/{assignment.role.value}/"
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
            repository_id=assignment.repository_id,
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
            code_root=self._binding.repository_root,
        )

    def _validate_scheduling(
        self,
        item: WorkItem,
        assignment: RoleAssignment,
        lease: TaskLease,
        allocated_at: datetime,
    ) -> None:
        if (
            item.repository_id != self._binding.repository_id
            or assignment.repository_id != item.repository_id
        ):
            raise RuntimeAllocationError("WorkItem/Assignment belongs to another repository")
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
        if TeamRole(assignment.role.value) not in agent.eligible_roles:
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


def _binding_digest(binding: RuntimeWorkspaceBinding) -> Sha256:
    payload = binding.model_dump(mode="json", exclude={"bound_at", "binding_sha256"})
    return _sha256(_canonical_json(payload))


def _put_immutable_model(
    path: Path,
    model: DomainModel,
    *,
    timestamp_field: str,
) -> DomainModel:
    if path.is_symlink() or path.parent.is_symlink():
        raise RuntimeWorkspaceCorruption("workspace record cannot be a symlink")
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
    if not _atomic_json_write(path, model.to_wire(), overwrite=False):
        return _put_immutable_model(path, model, timestamp_field=timestamp_field)
    return model


def _atomic_json_write(path: Path, payload: WirePayload, *, overwrite: bool = True) -> bool:
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
        if overwrite:
            os.replace(temporary_path, path)
        else:
            try:
                os.link(temporary_path, path)
            except FileExistsError:
                return False
            temporary_path.unlink()
        temporary_path = None
        return True
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
    "TEAM_WORKFORCE_DIRECTORIES",
    "TEAM_WORKFORCE_MANIFEST_NAME",
    "FileTeamWorkforceStore",
    "RuntimeAgentRun",
    "RuntimeAllocationError",
    "RuntimeWorkforceResolver",
    "RuntimeWorkspaceBinder",
    "RuntimeWorkspaceBinding",
    "RuntimeWorkspaceConflict",
    "RuntimeWorkspaceCorruption",
    "RuntimeWorkspaceError",
    "TeamId",
    "TeamWorkforceWorkspace",
    "TeamWorkforceWorkspaceError",
]
