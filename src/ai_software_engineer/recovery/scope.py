"""Read-only discovery and exact permission expansion for recovery scope approval."""

from pydantic import ValidationError

from ai_software_engineer.domain import AgentPermissions
from ai_software_engineer.git import (
    GitWorktreeManager,
    PathPolicyViolation,
    WorkspacePolicy,
    WorktreeRef,
)
from ai_software_engineer.recovery.models import (
    RecoveryRejected,
    RecoveryScopeSupplement,
    digest,
)
from ai_software_engineer.recovery.native import NativeRecoverySource


def inspect_recovery_scope_supplement(
    manager: GitWorktreeManager,
    worktree: WorktreeRef,
    original: NativeRecoverySource,
) -> RecoveryScopeSupplement | None:
    """Return exact changed paths omitted by policy without reading their contents."""
    policy = WorkspacePolicy(
        worktree.path,
        original.permissions,
        denied_paths=original.denied_paths,
    )
    missing: set[str] = set()
    for path in manager.inspect(worktree).changed_paths:
        for authorize in (policy.authorize_read, policy.authorize_write):
            try:
                authorize(path)
            except PathPolicyViolation as error:
                if str(error).endswith(f"path is not allowed: {path}"):
                    missing.add(path)
                    continue
                raise RecoveryRejected(
                    f"Coder recovery path cannot be approved: {error}"
                ) from error
    if not missing:
        return None
    source = original.source
    try:
        return RecoveryScopeSupplement.create(
            scope=source.scope,
            task_id=source.task_id,
            task_revision=source.task_revision,
            checkpoint_sha256=source.checkpoint_sha256,
            base_revision=source.base_revision,
            permissions_sha256=digest(original.permissions.to_wire()),
            denied_paths_sha256=digest(original.denied_paths),
            paths=tuple(sorted(missing)),
        )
    except ValidationError as error:
        raise RecoveryRejected("Coder recovery contains an unsafe changed path") from error


def expanded_recovery_permissions(
    original: AgentPermissions,
    supplement: RecoveryScopeSupplement | None,
) -> AgentPermissions:
    """Apply only the exact path set already bound by a scope supplement digest."""
    if supplement is None:
        return original
    supplement.validate_integrity()
    return original.model_copy(
        update={
            "read_paths": _append_exact_paths(original.read_paths, supplement.paths),
            "write_paths": _append_exact_paths(original.write_paths, supplement.paths),
        }
    )


def _append_exact_paths(current: tuple[str, ...], additions: tuple[str, ...]) -> tuple[str, ...]:
    return (*current, *(path for path in additions if path not in current))
