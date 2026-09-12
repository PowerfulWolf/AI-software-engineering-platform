"""Concrete read-only recovery gate against native source and current target facts."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain import AgentRole, ProjectPreparation
from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.manager.baseline import (
    ProjectBaselineCompiler,
    ProjectSpecBaseline,
)
from ai_software_engineer.manager.production_backend import (
    _delivery_role_permissions,
    _task_commands,
)
from ai_software_engineer.manager.production_rules import production_rules
from ai_software_engineer.recovery.models import RecoveryPlan, RecoveryRejected
from ai_software_engineer.recovery.native import (
    NativeRecoverySource,
    NativeRecoverySourceReader,
    _preparation,
)
from ai_software_engineer.repository_profile import RepositoryProfile
from ai_software_engineer.runtime_workspace import (
    REPOSITORY_PROFILE_NAME,
    RUNTIME_BINDING_NAME,
    RuntimeWorkspaceBinding,
    _record_read_path,
)
from ai_software_engineer.team_workspace import TeamWorkspace, _read_regular, _reject_symlinks


@dataclass(frozen=True)
class NativeRecoveryFacts:
    original: NativeRecoverySource
    target: ProjectPreparation
    profile: RepositoryProfile
    baseline: ProjectSpecBaseline


class NativeRecoveryFactsVerifier:
    """No prepare, registry registration, store mutation, model or Task creation.

    Requires an already prepared, clean target and a stopped old executor. Exact
    human recovery approval remains a separate gate; semantic design compatibility
    with the new base is not inferred from matching hashes or ancestry.
    """

    def __init__(self, config: ProductionConfig, environment: Mapping[str, str]) -> None:
        self._config = config
        self._source = NativeRecoverySourceReader(config, environment)

    def validate(self, plan: RecoveryPlan) -> None:
        self.inspect(plan)

    def inspect(self, plan: RecoveryPlan) -> NativeRecoveryFacts:
        try:
            plan.validate_integrity()
            first = self._inspect(plan)
            if first != self._inspect(plan):
                raise ValueError("recovery facts changed during inspection")
            return first
        except Exception as error:
            raise RecoveryRejected(
                "current recovery source or target facts do not match"
            ) from error

    def _inspect(self, plan: RecoveryPlan) -> NativeRecoveryFacts:
        source = plan.source
        original = self._source.inspect(
            source.scope,
            failed_run_id=source.failed_run_id,
            failed_context_id=source.failed_context_id,
        )
        if (
            original.source != source
            or original.permissions != plan.permissions
            or original.denied_paths != plan.denied_paths
        ):
            raise ValueError("original source or policy changed")
        config = self._config
        team = TeamWorkspace.initialize(
            config.platform_root,
            team_id=config.team_id,
            name=config.team_name,
            read_only=True,
        )
        _, repository = team.project_registry().locate_repository(source.scope.repository_id)
        sidecar = repository.root
        target = _preparation(sidecar, source.scope.repository_id, plan.target_preparation_sha256)
        previous = original.preparation
        for field in (
            "team_id",
            "team_root",
            "repository_id",
            "repository_root",
            "repository_workspace_root",
        ):
            if getattr(target, field) != getattr(previous, field):
                raise ValueError("recovery cannot move organization/project ownership")
        profile_path = _record_read_path(
            sidecar / "profile", REPOSITORY_PROFILE_NAME, target.repository_profile_sha256
        )
        _reject_symlinks(profile_path)
        profile = RepositoryProfile.model_validate_json(_read_regular(profile_path, 8_000_000))
        profile.validate_integrity()
        if (
            profile.profile_sha256 != target.repository_profile_sha256
            or profile.source_revision != plan.target_base_revision
        ):
            raise ValueError("target profile mismatch")
        constraints = original.task.constraints
        allowed_paths = constraints.allowed_paths if constraints is not None else ()
        expected_target_permissions = _delivery_role_permissions(
            AgentRole.CODER, allowed_paths, _task_commands(profile)
        )
        if plan.effective_target_permissions != expected_target_permissions:
            raise ValueError("approved target Coder permissions are no longer current")
        binding_path = _record_read_path(
            sidecar / "policy", RUNTIME_BINDING_NAME, target.runtime_binding_sha256
        )
        _reject_symlinks(binding_path)
        binding = RuntimeWorkspaceBinding.model_validate_json(
            _read_regular(binding_path, 1_000_000)
        )
        if (
            binding.binding_sha256 != target.runtime_binding_sha256
            or binding.repository_profile_sha256 != profile.profile_sha256
            or binding.repository_root != target.repository_root
            or binding.repository_workspace_root != str(sidecar)
            or binding.team_root != target.team_root
            or binding.team_id != target.team_id
            or binding.repository_id != target.repository_id
        ):
            raise ValueError("target runtime binding mismatch")
        # Establish scope before the binding validator follows any embedded path.
        _reject_symlinks(Path(target.team_root))
        _read_regular(Path(target.team_root) / "team.json", 1_000_000)
        binding.validate_environment()
        knowledge = team.knowledge_sources(config.team_knowledge_paths)
        compiled = ProjectBaselineCompiler().compile(
            profile, production_rules(team, knowledge), compiled_at=target.prepared_at
        )
        compiled.validate_integrity()
        baseline = compiled.compiled_spec
        if (
            baseline is None
            or baseline.baseline_sha256 != target.baseline_spec_sha256
            or baseline.source_uris != target.baseline_source_uris
        ):
            raise ValueError("current rules or team knowledge changed")
        manager = GitWorktreeManager(
            target.repository_root, Path(config.platform_root) / "worktrees" / target.repository_id
        )
        # Reuse the fixed-environment/no-hooks Git boundary. No user-supplied argv.
        manager._validate_repository()
        manager._validate_repository_filters()
        root = Path(target.repository_root)
        if manager._run_git(("rev-parse", "HEAD"), cwd=root) != plan.target_base_revision:
            raise ValueError("target HEAD changed")
        if manager._run_git(
            ("--no-optional-locks", "status", "--porcelain", "--untracked-files=all"), cwd=root
        ):
            raise ValueError("logical target checkout must be clean")
        manager._run_git(
            ("merge-base", "--is-ancestor", source.base_revision, plan.target_base_revision),
            cwd=root,
        )
        manager.verify_capture(
            plan.capture.to_capture(), original.permissions, denied_paths=original.denied_paths
        )
        return NativeRecoveryFacts(original, target, profile, baseline)
