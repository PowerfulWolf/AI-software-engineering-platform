"""Compose manager-owned role worktrees with the policy-bound command executor."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_software_engineer.domain import AgentDefinition, AgentRole
from ai_software_engineer.execution import (
    CommandExecutor,
    CommandExecutorSettings,
    SubprocessCommandExecutor,
)
from ai_software_engineer.git import (
    GitWorkspace,
    RecoverableGitWorkspace,
    WorktreeRef,
    WorktreeSnapshot,
    WorktreeSpec,
)

if TYPE_CHECKING:
    from ai_software_engineer.project_manager.dispatch import DispatchCommitRecord


class RoleWorktreeError(RuntimeError):
    """Base class for role worktree composition failures."""


class RoleWorktreeAgentMismatch(RoleWorktreeError):
    """Raised when a worktree spec and AgentDefinition belong to different roles."""


class RoleWorktreeRecoveryUnsupported(RoleWorktreeError):
    """Raised when the injected Git workspace has no restart recovery seam."""


class DispatchRoleBindingMismatch(RoleWorktreeError):
    """Dispatch allocation and executable AgentDefinition disagree."""


@dataclass(frozen=True, slots=True)
class RoleWorktreeBinding:
    """Immutable manager-issued worktree and its role-bound command port."""

    worktree: WorktreeRef
    executor: CommandExecutor


@dataclass(frozen=True, slots=True)
class VerificationWorktreeBindings:
    """Independent QA and Reviewer checkouts frozen at one candidate commit."""

    qa: RoleWorktreeBinding
    reviewer: RoleWorktreeBinding


class RoleWorktreeSession:
    """Open and close one role worktree while preserving Git and executor guards."""

    def __init__(
        self,
        git_workspace: GitWorkspace,
        *,
        environment: Mapping[str, str] | None = None,
        environment_allowlist: tuple[str, ...] = ("PATH", "LANG", "LC_ALL"),
        default_timeout_seconds: float = 600.0,
        max_output_bytes: int = 1_000_000,
    ) -> None:
        self._git_workspace = git_workspace
        self._environment = environment
        self._settings = CommandExecutorSettings(
            environment_allowlist=environment_allowlist,
            default_timeout_seconds=default_timeout_seconds,
            max_output_bytes=max_output_bytes,
        )

    def open(
        self,
        spec: WorktreeSpec,
        agent: AgentDefinition,
        *,
        denied_paths: tuple[str, ...] = (),
    ) -> RoleWorktreeBinding:
        """Create a role worktree and bind its Agent permissions to the command executor."""
        self._validate_role(spec, agent)
        worktree = self._git_workspace.create(spec)
        return self._bind(
            worktree,
            agent,
            denied_paths=denied_paths,
            remove_on_failure=True,
        )

    def recover(
        self,
        spec: WorktreeSpec,
        agent: AgentDefinition,
        *,
        denied_paths: tuple[str, ...] = (),
    ) -> RoleWorktreeBinding:
        """Rebind a validated existing worktree without changing or cleaning its contents."""
        self._validate_role(spec, agent)
        if not isinstance(self._git_workspace, RecoverableGitWorkspace):
            raise RoleWorktreeRecoveryUnsupported(
                "configured Git workspace does not support restart recovery"
            )
        worktree = self._git_workspace.recover(spec)
        return self._bind(
            worktree,
            agent,
            denied_paths=denied_paths,
            remove_on_failure=False,
        )

    def _bind(
        self,
        worktree: WorktreeRef,
        agent: AgentDefinition,
        *,
        denied_paths: tuple[str, ...],
        remove_on_failure: bool,
    ) -> RoleWorktreeBinding:
        try:
            executor = SubprocessCommandExecutor(
                worktree.path,
                agent.permissions,
                denied_paths=denied_paths,
                environment=self._environment,
                environment_allowlist=self._settings.environment_allowlist,
                default_timeout_seconds=self._settings.default_timeout_seconds,
                max_output_bytes=self._settings.max_output_bytes,
            )
        except Exception as error:
            if remove_on_failure:
                try:
                    self._git_workspace.remove(worktree)
                except Exception as cleanup_error:
                    error.add_note(f"role worktree cleanup failed: {cleanup_error}")
            raise
        return RoleWorktreeBinding(worktree=worktree, executor=executor)

    @staticmethod
    def _validate_role(spec: WorktreeSpec, agent: AgentDefinition) -> None:
        if spec.role is not agent.role:
            raise RoleWorktreeAgentMismatch(
                f"worktree role {spec.role.value} does not match agent role {agent.role.value}"
            )

    def inspect(self, binding: RoleWorktreeBinding) -> WorktreeSnapshot:
        """Return current Git evidence for a manager-issued binding."""
        return self._git_workspace.inspect(binding.worktree)

    def close(self, binding: RoleWorktreeBinding) -> None:
        """Remove only a clean manager-owned worktree; dirty evidence is preserved."""
        self._git_workspace.remove(binding.worktree)


class DispatchRoleWorktreeCoordinator:
    """Enforce dispatch Agent/model facts while opening serial role worktrees."""

    def __init__(self, session: RoleWorktreeSession) -> None:
        self._session = session

    def open_coder(
        self,
        dispatch: DispatchCommitRecord,
        definitions: Mapping[AgentRole, AgentDefinition],
        *,
        recover: bool = False,
    ) -> RoleWorktreeBinding:
        """Open the assigned Coder on the Dispatch Task's frozen base commit."""
        dispatch.validate_integrity()
        definition = self._definition(dispatch, AgentRole.CODER, definitions, attempt=1)
        spec = self._spec(dispatch, AgentRole.CODER, dispatch.task.base_ref, attempt=1)
        return self._open(spec, definition, recover=recover)

    def open_verifiers(
        self,
        dispatch: DispatchCommitRecord,
        candidate_revision: str,
        definitions: Mapping[AgentRole, AgentDefinition],
        *,
        recover: bool = False,
    ) -> VerificationWorktreeBindings:
        """Open independent detached QA/Reviewer checkouts at the exact candidate."""
        dispatch.validate_integrity()
        if not _is_full_revision(candidate_revision):
            raise DispatchRoleBindingMismatch(
                "verification worktrees require a durable full candidate commit SHA"
            )
        qa_definition = self._definition(dispatch, AgentRole.QA, definitions, attempt=1)
        reviewer_definition = self._definition(
            dispatch,
            AgentRole.REVIEWER,
            definitions,
            attempt=1,
        )
        qa = self._open(
            self._spec(dispatch, AgentRole.QA, candidate_revision, attempt=1),
            qa_definition,
            recover=recover,
        )
        try:
            reviewer = self._open(
                self._spec(dispatch, AgentRole.REVIEWER, candidate_revision, attempt=1),
                reviewer_definition,
                recover=recover,
            )
        except Exception:
            if not recover:
                self._session.close(qa)
            raise
        if qa.worktree.head_revision != reviewer.worktree.head_revision:
            raise DispatchRoleBindingMismatch(
                "QA and Reviewer worktrees do not share the exact candidate revision"
            )
        return VerificationWorktreeBindings(qa=qa, reviewer=reviewer)

    def inspect(self, binding: RoleWorktreeBinding) -> WorktreeSnapshot:
        return self._session.inspect(binding)

    def close(self, binding: RoleWorktreeBinding) -> None:
        self._session.close(binding)

    def _open(
        self,
        spec: WorktreeSpec,
        definition: AgentDefinition,
        *,
        recover: bool,
    ) -> RoleWorktreeBinding:
        method = self._session.recover if recover else self._session.open
        return method(spec, definition)

    @staticmethod
    def _definition(
        dispatch: DispatchCommitRecord,
        role: AgentRole,
        definitions: Mapping[AgentRole, AgentDefinition],
        *,
        attempt: int,
    ) -> AgentDefinition:
        phases = tuple(phase for phase in dispatch.phases if phase.role is role)
        definition = definitions.get(role)
        if len(phases) != 1 or definition is None:
            raise DispatchRoleBindingMismatch(f"dispatch has no unique {role.value} binding")
        phase = phases[0]
        if (
            definition.role is not role
            or definition.id != phase.agent_id
            or definition.provider != phase.model_selection.provider
            or definition.model != phase.model_selection.model
            or phase.assignment.attempt != attempt
            or phase.assignment.task_id != dispatch.task_id
            or phase.lease.task_id != dispatch.task_id
        ):
            raise DispatchRoleBindingMismatch(
                f"{role.value} AgentDefinition does not match its dispatch allocation"
            )
        return definition

    @staticmethod
    def _spec(
        dispatch: DispatchCommitRecord,
        role: AgentRole,
        revision: str,
        *,
        attempt: int,
    ) -> WorktreeSpec:
        if not _is_full_revision(revision):
            raise DispatchRoleBindingMismatch("role worktree requires a durable full commit SHA")
        return WorktreeSpec(
            task_id=dispatch.task_id,
            role=role,
            attempt=attempt,
            source_revision=revision,
        )


def _is_full_revision(value: str) -> bool:
    return 40 <= len(value) <= 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "DispatchRoleBindingMismatch",
    "DispatchRoleWorktreeCoordinator",
    "RoleWorktreeAgentMismatch",
    "RoleWorktreeBinding",
    "RoleWorktreeError",
    "RoleWorktreeRecoveryUnsupported",
    "RoleWorktreeSession",
    "VerificationWorktreeBindings",
]
