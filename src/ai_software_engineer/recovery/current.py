"""Concrete read-only recovery gate against native source and current target facts."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain import AgentRole, ProjectPreparation
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.knowledge_selection import (
    effective_project_knowledge_paths,
    effective_team_knowledge_paths,
)
from ai_software_engineer.manager.baseline import (
    ProjectBaselineCompiler,
    ProjectSpecBaseline,
)
from ai_software_engineer.manager.production_backend import (
    _delivery_role_permissions,
    _task_commands,
)
from ai_software_engineer.manager.production_rules import production_rules
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.read_record_scope import recovery_record_read_scope
from ai_software_engineer.recovery.contained_unknown import (
    ContainedUnknownRecoverySourceReader,
    require_contained_unknown_capture,
)
from ai_software_engineer.recovery.context_capacity import LegacyContextCapacitySourceReader
from ai_software_engineer.recovery.models import (
    CapturedChanges,
    RecoveryPlan,
    RecoveryRejected,
    RecoveryScopeSupplement,
)
from ai_software_engineer.recovery.native import (
    NativeRecoverySource,
    NativeRecoverySourceReader,
    _preparation,
)
from ai_software_engineer.recovery.scope import (
    expanded_recovery_permissions,
    inspect_recovery_scope_supplement,
)
from ai_software_engineer.recovery.stopped_unknown import (
    StoppedUnknownRecoverySourceReader,
    require_stopped_unknown_capture,
)
from ai_software_engineer.recovery.workspace_snapshot import (
    _terminal_workspace_window,
    read_terminal_workspace_snapshot,
)
from ai_software_engineer.redaction import source_inspection_scope
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


@dataclass(frozen=True)
class _RecoveryTargetPreflight:
    original: NativeRecoverySource
    team: TeamWorkspace
    project: ProjectWorkspace
    sidecar: Path
    target: ProjectPreparation
    profile: RepositoryProfile
    manager: GitWorktreeManager
    allowed_paths: tuple[str, ...]
    supplement: RecoveryScopeSupplement | None


class NativeRecoveryFactsVerifier:
    """No prepare, registry registration, store mutation, model or Task creation.

    Requires an already prepared, clean target and a stopped old executor. Exact
    human recovery approval remains a separate gate; semantic design compatibility
    with the new base is not inferred from matching hashes or ancestry.
    """

    def __init__(self, config: ProductionConfig, environment: Mapping[str, str]) -> None:
        self._config = config
        self._environment = dict(environment)
        self._source = NativeRecoverySourceReader(config, environment)

    def validate(self, plan: RecoveryPlan) -> None:
        self.inspect(plan)

    @source_inspection_scope()
    @recovery_record_read_scope()
    def inspect(self, plan: RecoveryPlan) -> NativeRecoveryFacts:
        try:
            plan.validate_integrity()
            if (
                _uses_standard_native_inspection(self)
                and plan.workspace_snapshot is not None
                and not plan.quarantined_paths
            ):
                return self._inspect_window(plan)
            first = self._inspect(plan)
            if first != self._inspect(plan):
                raise ValueError("recovery facts changed during inspection")
            return first
        except Exception as error:
            raise RecoveryRejected(
                "current recovery source or target facts do not match"
            ) from error

    @source_inspection_scope()
    @recovery_record_read_scope()
    def inspect_around_capture(
        self, plan: RecoveryPlan, verify_capture: Callable[[], None]
    ) -> NativeRecoveryFacts:
        """Observe a settled UNKNOWN source on both sides of exact capture validation.

        Each `_inspect` independently checks the complete source, target,
        current mutation inventory and retained draft. The caller invokes this
        only for the standard native verifier, within one synchronous gate.
        """
        try:
            plan.validate_integrity()
            plan.require_execution_supported()
            if (
                plan.source.stopped_unknown_settlement_sha256 is None
                and plan.source.contained_unknown_settlement_sha256 is None
            ) or not _uses_standard_native_inspection(self):
                raise ValueError("capture window requires standard settled UNKNOWN inspection")
            first = self._inspect(plan)
        except Exception as error:
            raise RecoveryRejected(
                "current recovery source or target facts do not match"
            ) from error
        verify_capture()
        try:
            second = self._inspect(plan)
            if first != second:
                raise ValueError("recovery facts changed during capture verification")
            return second
        except Exception as error:
            raise RecoveryRejected(
                "current recovery source or target facts do not match"
            ) from error

    def _inspect(self, plan: RecoveryPlan) -> NativeRecoveryFacts:
        original = self._read_source(plan)
        target = self._target_preflight(plan, original)
        if (
            plan.source.stopped_unknown_settlement_sha256 is not None
            or plan.source.contained_unknown_settlement_sha256 is not None
        ):
            current_capture = CapturedChanges.from_capture(
                target.manager.capture_legacy_changes(
                    plan.capture.to_capture().worktree,
                    plan.permissions,
                    denied_paths=original.denied_paths,
                )
            )
            if plan.source.contained_unknown_settlement_sha256 is not None:
                require_contained_unknown_capture(original, plan.capture, current_capture)
            else:
                require_stopped_unknown_capture(original, plan.capture, current_capture)
            facts = self._target_facts(plan, target)
            target.manager.verify_legacy_capture(
                current_capture.to_capture(),
                plan.permissions,
                denied_paths=original.denied_paths,
            )
            return facts
        if plan.context_capacity_input is not None:
            if original.capacity_input != plan.context_capacity_input:
                raise ValueError("capacity recovery lost its complete retained patch")
            return self._target_facts(plan, target)
        workspace_snapshot = read_terminal_workspace_snapshot(
            self._config,
            self._environment,
            original,
            plan.capture,
            approved_permissions=plan.permissions,
            scope_supplement=target.supplement,
        )
        if workspace_snapshot != plan.workspace_snapshot:
            raise ValueError("terminal workspace snapshot is missing or no longer current")
        return self._target_facts(plan, target)

    def _inspect_window(self, plan: RecoveryPlan) -> NativeRecoveryFacts:
        plan.require_execution_supported()
        with _terminal_workspace_window(self._config, self._environment, plan.source) as window:
            original = self._read_source(plan)
            target = self._target_preflight(plan, original)
            first = self._target_facts(plan, target)
            before = window.observe(
                original,
                plan.capture,
                permissions=plan.permissions,
                supplement=target.supplement,
            )
            original_after = self._read_source(plan)
            target_after = self._target_preflight(plan, original_after)
            second = self._target_facts(plan, target_after)
            # Fresh SQL, stop, capture and inventory follow the LAST source and
            # complete target pass; neither observation's stop object is reused.
            after = window.observe(
                original_after,
                plan.capture,
                permissions=plan.permissions,
                supplement=target_after.supplement,
            )
            if (
                first != second
                or before.facts != after.facts
                or before.observation.inventory_after != after.observation.inventory_after
                or before.observation.ignored_paths != after.observation.ignored_paths
                or before.observation.tracked_environment_paths
                != after.observation.tracked_environment_paths
                or before.snapshot != plan.workspace_snapshot
                or after.snapshot != plan.workspace_snapshot
            ):
                raise ValueError("recovery facts changed during inspection")
        return first

    def _read_source(self, plan: RecoveryPlan) -> NativeRecoverySource:
        plan.require_execution_supported()
        source = plan.source
        if source.contained_unknown_settlement_sha256 is not None:
            original = ContainedUnknownRecoverySourceReader(
                self._config, self._environment
            ).inspect(source.scope, source.contained_unknown_settlement_sha256)
        elif source.stopped_unknown_settlement_sha256 is not None:
            original = StoppedUnknownRecoverySourceReader(self._config, self._environment).inspect(
                source.scope, source.stopped_unknown_settlement_sha256
            )
        elif source.context_capacity_receipt_sha256 is not None:
            original = LegacyContextCapacitySourceReader(self._config, self._environment).inspect(
                source.scope, source.context_capacity_receipt_sha256
            )
        else:
            original = self._source.inspect(
                source.scope,
                failed_run_id=source.failed_run_id,
                failed_context_id=source.failed_context_id,
            )
        if original.source != source or original.denied_paths != plan.denied_paths:
            raise ValueError("original source or policy changed")
        from ai_software_engineer.recovery.inherited_input import read_inherited_reapply_inputs

        if (
            read_inherited_reapply_inputs(
                self._config, self._environment, original.source, original.task
            )
            != plan.inherited_reapply_inputs
        ):
            raise ValueError("recovery Plan lost or changed complete inherited inputs")
        return original

    def _target_preflight(
        self, plan: RecoveryPlan, original: NativeRecoverySource
    ) -> _RecoveryTargetPreflight:
        source = plan.source
        config = self._config
        team = TeamWorkspace.initialize(
            config.platform_root,
            team_id=config.team_id,
            name=config.team_name,
            read_only=True,
        )
        project, repository = team.project_registry().locate_repository(source.scope.repository_id)
        if plan.target_authorization is not None:
            plan.target_authorization.validate_current(
                source=source,
                task=original.task,
                scope=EngineeringScope(
                    team_id=team.manifest.team_id,
                    project_id=project.manifest.project_id,
                    repository_id=repository.manifest.repository_id,
                    repository_root=repository.manifest.repository_root,
                ),
            )
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
        manager = GitWorktreeManager(
            target.repository_root,
            Path(config.platform_root) / "worktrees" / target.repository_id,
            branch_names={original.task.id: original.task.branch_name},
        )
        if plan.capture.branch_name != original.task.branch_name:
            raise ValueError("captured branch differs from frozen source Task intent")
        old = plan.capture.to_capture().worktree
        supplement = inspect_recovery_scope_supplement(
            manager,
            old,
            original,
            request=plan.scope_supplement.request if plan.scope_supplement else None,
        )
        if (
            supplement != plan.scope_supplement
            or expanded_recovery_permissions(original.permissions, supplement) != plan.permissions
        ):
            raise ValueError("approved source Coder permissions are no longer current")
        return _RecoveryTargetPreflight(
            original, team, project, sidecar, target, profile, manager, allowed_paths, supplement
        )

    def _target_facts(
        self, plan: RecoveryPlan, preflight: _RecoveryTargetPreflight
    ) -> NativeRecoveryFacts:
        original = preflight.original
        team, project = preflight.team, preflight.project
        sidecar, target, profile = preflight.sidecar, preflight.target, preflight.profile
        manager, allowed_paths, supplement = (
            preflight.manager,
            preflight.allowed_paths,
            preflight.supplement,
        )
        source, config = plan.source, self._config
        if supplement is not None:
            allowed_paths = (*allowed_paths, *supplement.paths)
        allowed_paths = plan.rebound_write_paths(allowed_paths)
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
        project_fallback = (
            config.project_knowledge_paths
            if config.default_project_id == project.manifest.project_id
            else ()
        )
        knowledge = (
            *team.knowledge_sources(
                effective_team_knowledge_paths(team, config.team_knowledge_paths)
            ),
            *project.knowledge_sources(
                effective_project_knowledge_paths(project, project_fallback)
            ),
        )
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
            (
                "merge-base",
                "--is-ancestor",
                source.effective_base_revision,
                plan.target_base_revision,
            ),
            cwd=root,
        )
        verify_capture = (
            manager.verify_legacy_capture if plan.quarantined_paths else manager.verify_capture
        )
        verify_capture(
            plan.capture.to_capture(), plan.permissions, denied_paths=original.denied_paths
        )
        return NativeRecoveryFacts(original, target, profile, baseline)


# Capture the original delegate before trusted composition can extend validation.
_STANDARD_NATIVE_INSPECT = NativeRecoveryFactsVerifier._inspect
_STANDARD_NATIVE_PUBLIC_INSPECT = NativeRecoveryFactsVerifier.inspect
_STANDARD_NATIVE_CAPTURE_WINDOW = NativeRecoveryFactsVerifier.inspect_around_capture
_STANDARD_NATIVE_VALIDATE = NativeRecoveryFactsVerifier.validate


def _uses_standard_native_inspection(verifier: NativeRecoveryFactsVerifier) -> bool:
    inspect = verifier._inspect
    public_inspect = verifier.inspect
    return bool(
        type(verifier) is NativeRecoveryFactsVerifier
        and getattr(inspect, "__self__", None) is verifier
        and getattr(inspect, "__func__", None) is _STANDARD_NATIVE_INSPECT
        and getattr(public_inspect, "__self__", None) is verifier
        and getattr(public_inspect, "__func__", None) is _STANDARD_NATIVE_PUBLIC_INSPECT
    )


def _uses_standard_native_capture_window(verifier: NativeRecoveryFactsVerifier) -> bool:
    window = verifier.inspect_around_capture
    return bool(
        _uses_standard_native_inspection(verifier)
        and getattr(window, "__self__", None) is verifier
        and getattr(window, "__func__", None) is _STANDARD_NATIVE_CAPTURE_WINDOW
    )
