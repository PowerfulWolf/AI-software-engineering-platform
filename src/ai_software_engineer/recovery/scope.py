"""Read-only discovery and exact permission expansion for recovery scope approval."""

from pydantic import ValidationError

from ai_software_engineer.domain import AgentPermissions
from ai_software_engineer.git import (
    GitWorktreeManager,
    PathPolicyViolation,
    WorkspacePolicy,
    WorktreeRef,
)
from ai_software_engineer.git.policy import is_protected_rule_path
from ai_software_engineer.recovery.models import (
    RecoveryRejected,
    RecoveryRequestedFile,
    RecoveryScopeRequest,
    RecoveryScopeSupplement,
    digest,
)
from ai_software_engineer.recovery.native import NativeRecoverySource


def inspect_recovery_scope_supplement(
    manager: GitWorktreeManager,
    worktree: WorktreeRef,
    original: NativeRecoverySource,
    *,
    request: RecoveryScopeRequest | None = None,
) -> RecoveryScopeSupplement | None:
    """Return exact changed paths omitted by policy without reading their contents."""
    policy = WorkspacePolicy(
        worktree.path,
        original.permissions,
        denied_paths=original.denied_paths,
    )
    missing: set[str] = set()
    changed_paths = set(manager.inspect(worktree).changed_paths)
    # Include retained committed work, against the exact approved execution base.
    full_diff = manager._run_git_bytes(
        (
            "--no-optional-locks",
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--name-only",
            "-z",
            original.source.effective_base_revision,
            "--",
        ),
        cwd=worktree.path,
    )
    changed_paths.update(path.decode("utf-8") for path in full_diff.split(b"\0") if path)
    requested_files = None
    if request is not None:
        request = RecoveryScopeRequest.model_validate(request.to_wire())
        progress = original.accepted_progress
        if progress is None or (
            progress.artifact_id != request.progress_artifact_id
            or progress.integrity.sha256 != request.progress_sha256
        ):
            raise RecoveryRejected("requested scope does not bind the accepted Coder progress")
        requested_files = _requested_files(manager, worktree, original, request, changed_paths)
    for path in (*changed_paths, *(request.paths if request else ())):
        if is_protected_rule_path(path):
            # An old mistaken grant is auditable, never scope-expandable. New or
            # requested protected paths are rejected rather than offered for approval.
            if request is not None and path in request.paths:
                raise RecoveryRejected("Trellis 规范只读, 不能申请恢复写入范围")
            try:
                policy.authorize_historical_capture(path)
            except PathPolicyViolation as error:
                raise RecoveryRejected(f"Trellis 规范改动不能获得恢复授权: {error}") from error
            continue
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
        if request is not None and path in request.paths and path not in missing:
            raise RecoveryRejected("requested scope path is already allowed")
    if not missing:
        return None
    source = original.source
    try:
        return RecoveryScopeSupplement.create(
            scope=source.scope,
            task_id=source.task_id,
            task_revision=source.task_revision,
            checkpoint_sha256=source.checkpoint_sha256,
            base_revision=source.effective_base_revision,
            permissions_sha256=digest(original.permissions.to_wire()),
            denied_paths_sha256=digest(original.denied_paths),
            paths=tuple(sorted(missing)),
            request=request,
            requested_files=requested_files,
        )
    except ValidationError as error:
        raise RecoveryRejected("Coder recovery contains an unsafe changed path") from error


def _requested_files(
    manager: GitWorktreeManager,
    worktree: WorktreeRef,
    original: NativeRecoverySource,
    request: RecoveryScopeRequest,
    changed_paths: set[str],
) -> tuple[RecoveryRequestedFile, ...]:
    files = []
    for path in request.paths:
        target = worktree.path / path
        if path in changed_paths or target.resolve() != target or not target.is_file():
            raise RecoveryRejected("requested scope requires an unchanged regular tracked file")
        # ls-tree reads object metadata only; no file content is exposed before approval.
        entries = manager._run_git(
            ("ls-tree", "-z", original.source.effective_base_revision, "--", path),
            cwd=worktree.path,
        ).split("\0")
        if len(entries) != 2 or entries[1] or "\t" not in entries[0]:
            raise RecoveryRejected("requested scope file is not in the approved base")
        metadata, found = entries[0].split("\t", 1)
        parts = metadata.split()
        if found != path or len(parts) != 3 or parts[1] != "blob":
            raise RecoveryRejected("requested scope requires exact Git file metadata")
        try:
            files.append(
                RecoveryRequestedFile.model_validate(
                    {"path": path, "mode": parts[0], "blob_id": parts[2]}
                )
            )
        except ValidationError as error:
            raise RecoveryRejected("requested scope file is not a regular Git blob") from error
    return tuple(files)


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
