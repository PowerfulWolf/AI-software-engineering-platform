"""Local Git CLI adapter for isolated role worktrees."""

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.git.capture import (
    MAX_CAPTURE_BYTES,
    MAX_CAPTURE_FILES,
    WorktreeChangeCapture,
    read_capture_file,
    without_hunk_labels,
)
from ai_software_engineer.git.policy import PathPolicyViolation, WorkspacePolicy
from ai_software_engineer.git.ports import WorktreeRef, WorktreeSnapshot, WorktreeSpec
from ai_software_engineer.redaction import redact_text

_GIT_ENV: Final[dict[str, str]] = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": os.defpath,
}
_GIT_SAFETY_CONFIG: Final[tuple[str, ...]] = (
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
)


class GitWorkspaceError(RuntimeError):
    """Base class for stable Repository Plane failures."""


class InvalidRepository(GitWorkspaceError):
    """Raised when the configured repository is missing or not a Git root."""


class InvalidWorktreeRoot(GitWorkspaceError):
    """Raised when role worktrees would be created inside the main checkout."""


class UnsafeRepositoryConfiguration(GitWorkspaceError):
    """Raised when checkout could execute a repository-configured program."""


class RevisionNotFound(GitWorkspaceError):
    """Raised when a source ref cannot be resolved to a commit."""


class WorktreeAlreadyExists(GitWorkspaceError):
    """Raised when a target path or Coder branch is already present."""


class UnmanagedWorktree(GitWorkspaceError):
    """Raised when a reference does not identify a worktree owned by this manager."""


class WorktreeNotFound(GitWorkspaceError):
    """Raised when a recovery target is not present at its deterministic path."""


class WorktreeIdentityDrift(GitWorkspaceError):
    """Raised when a recovery target no longer has its expected role identity."""


class WorktreeRevisionDrift(GitWorkspaceError):
    """Raised when a recovery target HEAD differs from its durable revision."""


class DirtyWorktree(GitWorkspaceError):
    """Raised when cleanup would discard tracked or untracked evidence."""

    def __init__(self, changed_paths: tuple[str, ...]) -> None:
        super().__init__(f"worktree has unsaved changes: {', '.join(changed_paths)}")
        self.changed_paths = changed_paths


class WorktreeCaptureRejected(GitWorkspaceError):
    """The preserved work is unsupported, unsafe, or changed during inspection."""


class WorktreeSeedRejected(GitWorkspaceError):
    """A recovery seed cannot safely be applied; retain both worktrees."""


class GitCommandError(GitWorkspaceError):
    """Raised when an allowlisted Git command returns a non-zero status."""


class GitCommandTimeout(GitWorkspaceError):
    """Raised when an allowlisted Git command exceeds its fixed timeout."""


@runtime_checkable
class RecoverableGitWorkspace(Protocol):
    """Optional restart seam implemented by Git workspaces with durable identity checks."""

    def recover(self, spec: WorktreeSpec) -> WorktreeRef: ...


class GitWorktreeManager:
    """Create role worktrees without using the main checkout as an Agent workspace."""

    def __init__(
        self,
        repository: str | Path,
        worktree_root: str | Path,
        *,
        command_timeout_seconds: float = 30.0,
    ) -> None:
        self._repository = Path(repository).resolve()
        self._worktree_root = Path(worktree_root).resolve()
        self._command_timeout_seconds = command_timeout_seconds
        self._git = shutil.which("git", path=os.defpath)

    def create(self, spec: WorktreeSpec) -> WorktreeRef:
        """Create one new role worktree at a fully resolved commit."""
        self._validate_repository()
        self._validate_repository_filters()
        self._validate_worktree_root()
        source_revision = self._resolve_revision(spec.source_revision)
        target = self._target_path(spec)
        self._validate_target_containment(target)
        self._validate_target_has_no_symlinks(target)
        branch = self._branch_name(spec) if spec.role is AgentRole.CODER else None

        if target.exists() or (branch is not None and self._branch_exists(branch)):
            raise WorktreeAlreadyExists(str(target if target.exists() else branch))

        target.parent.mkdir(parents=True, exist_ok=True)
        arguments = ["worktree", "add"]
        if branch is None:
            arguments.append("--detach")
        else:
            arguments.extend(("-b", branch))
        arguments.extend((str(target), source_revision))
        self._run_git(tuple(arguments), cwd=self._repository)

        return WorktreeRef(
            task_id=spec.task_id,
            role=spec.role,
            attempt=spec.attempt,
            path=target,
            head_revision=source_revision,
            branch=branch,
            detached=branch is None,
        )

    def recover(self, spec: WorktreeSpec) -> WorktreeRef:
        """Reopen an existing role worktree after verifying its complete durable identity.

        Recovery is deliberately read-only. It never checks out a revision, changes a branch,
        cleans files, or removes a mismatched target. Any drift is left in place as evidence.
        """
        self._validate_repository()
        self._validate_repository_filters()
        self._validate_worktree_root()
        expected_revision = self._resolve_revision(spec.source_revision)
        if spec.source_revision != expected_revision:
            raise WorktreeRevisionDrift(
                "worktree recovery requires a durable full commit SHA, "
                f"not a movable ref: {spec.source_revision}"
            )
        target = self._target_path(spec)
        self._validate_target_containment(target)
        self._validate_target_has_no_symlinks(target)
        if not target.exists():
            raise WorktreeNotFound(str(target))
        if not target.is_dir():
            raise WorktreeIdentityDrift(f"recovery target is not a directory: {target}")

        self._validate_registered_worktree(target)
        expected_branch = self._branch_name(spec) if spec.role is AgentRole.CODER else None
        self._validate_role_git_state(target, expected_branch=expected_branch)
        actual_revision = self._run_git(("rev-parse", "HEAD"), cwd=target)
        if actual_revision != expected_revision:
            raise WorktreeRevisionDrift(
                f"worktree HEAD drift for {target}: "
                f"expected {expected_revision}, observed {actual_revision}"
            )

        return WorktreeRef(
            task_id=spec.task_id,
            role=spec.role,
            attempt=spec.attempt,
            path=target,
            head_revision=expected_revision,
            branch=expected_branch,
            detached=expected_branch is None,
        )

    def restore_clean_coder(self, spec: WorktreeSpec) -> WorktreeRef:
        """Restore a cleaned Coder worktree only when its branch still proves a clean base.

        Normal recovery never mutates repository state. This narrower Manager repair exists for
        terminal provider failures whose clean worktree was removed by normal cleanup. It will
        not recreate a missing branch, move a branch, discard edits, or accept a branch that has
        advanced beyond the Task's immutable source revision.
        """
        if spec.role is not AgentRole.CODER:
            raise WorktreeIdentityDrift("only a Coder worktree can be restored from its branch")
        self._validate_repository()
        self._validate_repository_filters()
        self._validate_worktree_root()
        expected_revision = self._resolve_revision(spec.source_revision)
        if spec.source_revision != expected_revision:
            raise WorktreeRevisionDrift(
                "clean Coder restoration requires a durable full commit SHA"
            )
        target = self._target_path(spec)
        self._validate_target_containment(target)
        self._validate_target_has_no_symlinks(target)
        if target.exists():
            return self.recover(spec)
        branch = self._branch_name(spec)
        if not self._branch_exists(branch):
            raise WorktreeNotFound(str(target))
        branch_revision = self._resolve_revision(f"refs/heads/{branch}")
        if branch_revision != expected_revision:
            raise WorktreeRevisionDrift(
                "missing Coder worktree branch does not match its immutable source revision"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        self._run_git(("worktree", "add", str(target), branch), cwd=self._repository)
        restored = self.recover(spec)
        if self.inspect(restored).dirty:
            raise WorktreeIdentityDrift("restored Coder worktree is not clean")
        return restored

    def inspect(self, worktree: WorktreeRef) -> WorktreeSnapshot:
        """Return the exact HEAD and changed repository paths for a managed worktree."""
        self._validate_repository()
        self._validate_repository_filters()
        path = self._validate_owned_worktree(worktree)
        head_revision = self._run_git(("rev-parse", "HEAD"), cwd=path)
        tracked = self._run_git_bytes(
            ("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z", "HEAD", "--"),
            cwd=path,
        )
        untracked = self._run_git_bytes(
            ("ls-files", "--others", "--exclude-standard", "-z"), cwd=path
        )
        changed_paths = tuple(sorted(_decode_nul_paths(tracked + untracked)))
        return WorktreeSnapshot(head_revision=head_revision, changed_paths=changed_paths)

    def remove(self, worktree: WorktreeRef) -> None:
        """Remove one clean managed worktree while retaining its Git branch and commits."""
        snapshot = self.inspect(worktree)
        if snapshot.dirty:
            raise DirtyWorktree(snapshot.changed_paths)
        self._run_git(("worktree", "remove", str(worktree.path.resolve())), cwd=self._repository)

    def capture_changes(
        self,
        worktree: WorktreeRef,
        permissions: AgentPermissions,
        *,
        denied_paths: tuple[str, ...] = (),
        base_revision: str | None = None,
    ) -> WorktreeChangeCapture:
        """Observe preserved Coder modifications without changing files, index or refs.

        v1 accepts modifications and additions of bounded regular UTF-8 text files;
        deleted/renamed files, mode changes and partial commits need a later explicit
        recovery contract. A capture is not authorization to resume.
        The caller must ensure the old executor has stopped before taking this fact.
        """
        if worktree.role is not AgentRole.CODER:
            raise WorktreeCaptureRejected("only Coder work can be captured for recovery")
        first = self._capture_changes_once(
            worktree, permissions, denied_paths, base_revision=base_revision
        )
        second = self._capture_changes_once(
            worktree, permissions, denied_paths, base_revision=base_revision
        )
        if first != second:
            raise WorktreeCaptureRejected("worktree changed during capture")
        return first

    def verify_capture(
        self,
        capture: WorktreeChangeCapture,
        permissions: AgentPermissions,
        *,
        denied_paths: tuple[str, ...] = (),
    ) -> None:
        """Re-read the exact source; stale/tampered captures never authorize recovery."""
        observed = self.capture_changes(
            capture.worktree,
            permissions,
            denied_paths=denied_paths,
            base_revision=capture.base_revision,
        )
        if observed != capture:
            raise WorktreeCaptureRejected("preserved work no longer matches capture")

    def seed_changes(
        self,
        capture: WorktreeChangeCapture,
        target: WorktreeRef,
        source_permissions: AgentPermissions,
        target_permissions: AgentPermissions,
        *,
        source_denied_paths: tuple[str, ...] = (),
        target_denied_paths: tuple[str, ...] = (),
    ) -> WorktreeChangeCapture:
        """Seed an exclusively held fresh checkout, not an authorization or candidate.

        The application must separately authorize the exact recovery plan and stop
        other writers. No old files, index, refs, Task or approval records are edited.
        Failures after application retain the target for diagnosis, never reset it.
        """
        try:
            if (
                target.role is not AgentRole.CODER
                or target.attempt != 1
                or target.task_id == capture.worktree.task_id
            ):
                raise WorktreeSeedRejected("seed requires a fresh Coder Task")
            self.verify_capture(capture, source_permissions, denied_paths=source_denied_paths)
            clean = self.capture_changes(
                target, target_permissions, denied_paths=target_denied_paths
            )
            if clean.patch:
                raise WorktreeSeedRejected("seed target must be clean")
            self._run_git(
                (
                    "merge-base",
                    "--is-ancestor",
                    capture.effective_base_revision,
                    target.head_revision,
                ),
                cwd=target.path,
            )
            policy = WorkspacePolicy(
                target.path, target_permissions, denied_paths=target_denied_paths
            )
            for path in capture.changed_paths:
                policy.authorize_read(path)
                policy.authorize_write(path)
                if Path(path).name == ".gitattributes":
                    raise WorktreeSeedRejected("seed cannot change its own merge attributes")
                target_path = target.path / path
                if target_path.exists() or target_path.is_symlink():
                    read_capture_file(
                        target.path,
                        path,
                        executable=bool(target_path.lstat().st_mode & 0o100),
                    )
                elif self._path_exists_at_revision(
                    capture.worktree.path, capture.effective_base_revision, path
                ):
                    raise WorktreeSeedRejected("seed target is missing a captured base file")
            self._validate_seed_configuration(target, capture.changed_paths)
            arguments = (
                "-c",
                "merge.default=text",
                "-c",
                "apply.ignoreWhitespace=no",
                "apply",
                "--3way",
                "--index",
                "--unidiff-zero",
                "--whitespace=nowarn",
            )
            if capture.patch:
                # --check can report success even when the three-way merge conflicts.
                # Actually merge into a disposable index, never the target index/files.
                with tempfile.TemporaryDirectory(prefix="ase-seed-") as temporary:
                    temporary_index = Path(temporary) / "index"
                    index = Path(
                        self._run_git(
                            ("rev-parse", "--path-format=absolute", "--git-path", "index"),
                            cwd=target.path,
                        )
                    )
                    shutil.copyfile(index, temporary_index)
                    self._run_git_bytes(
                        (*arguments, "--cached", "-"),
                        cwd=target.path,
                        input=capture.patch,
                        index_file=temporary_index,
                    )
                # Preflight is not a lock. Detect observed drift immediately before writing.
                self.verify_capture(capture, source_permissions, denied_paths=source_denied_paths)
                self.verify_capture(clean, target_permissions, denied_paths=target_denied_paths)
                self._validate_seed_configuration(target, capture.changed_paths)
                self._run_git_bytes((*arguments, "-"), cwd=target.path, input=capture.patch)
            seeded = self.capture_changes(
                target, target_permissions, denied_paths=target_denied_paths
            )
            if not set(seeded.changed_paths).issubset(capture.changed_paths):
                raise WorktreeSeedRejected("seed changed unexpected paths")
            self.verify_capture(capture, source_permissions, denied_paths=source_denied_paths)
            return seeded
        except (GitWorkspaceError, PathPolicyViolation, OSError, ValueError) as error:
            raise WorktreeSeedRejected(
                "recovery seed rejected; preserve source and target"
            ) from error

    def _validate_seed_configuration(self, target: WorktreeRef, paths: tuple[str, ...]) -> None:
        configured = self._invoke_git(
            (
                "config",
                "--name-only",
                "--get-regexp",
                r"^(merge\..*\.driver|filter\..*\.(clean|smudge|process))$",
            ),
            cwd=target.path,
        )
        if configured.returncode != 1:
            raise WorktreeSeedRejected("seed requires no external merge drivers or filters")
        if paths:
            attributes = self._run_git_bytes(
                ("check-attr", "-z", "merge", "--", *paths), cwd=target.path
            )
            fields = attributes.split(b"\0")[:-1]
            if len(fields) != len(paths) * 3 or any(
                value != b"unspecified" for value in fields[2::3]
            ):
                raise WorktreeSeedRejected("seed does not support merge attributes")

    def _capture_changes_once(
        self,
        worktree: WorktreeRef,
        permissions: AgentPermissions,
        denied_paths: tuple[str, ...],
        *,
        base_revision: str | None = None,
    ) -> WorktreeChangeCapture:
        # recover validates full SHA, registered ownership, exact branch and HEAD;
        # validate the supplied ref as well, not merely its derived Task/attempt.
        self._validate_owned_worktree(worktree)
        self.recover(
            WorktreeSpec(
                task_id=worktree.task_id,
                role=worktree.role,
                attempt=worktree.attempt,
                source_revision=worktree.head_revision,
            )
        )
        root = worktree.path
        diff_base = worktree.head_revision
        if base_revision is not None:
            diff_base = self._resolve_revision(base_revision)
            if diff_base != base_revision:
                raise WorktreeCaptureRejected("capture base must be a durable full commit SHA")
            self._run_git(
                ("merge-base", "--is-ancestor", diff_base, worktree.head_revision), cwd=root
            )
        policy = WorkspacePolicy(root, permissions, denied_paths=denied_paths)
        untracked_paths = _decode_nul_paths(
            self._run_git_bytes(("ls-files", "--others", "--exclude-standard", "-z"), cwd=root)
        )
        flags = self._run_git_bytes(("ls-files", "-v", "-z"), cwd=root)
        if any(entry and entry[:1] != b"H" for entry in flags.split(b"\0")):
            raise WorktreeCaptureRejected("nonstandard index flags are not supported")
        arguments = (
            "--no-optional-locks",
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
        )
        raw = self._run_git_bytes(
            (*arguments, "--raw", "--no-abbrev", "-z", diff_base, "--"), cwd=root
        )
        entries = raw.split(b"\0")[:-1]
        if len(entries) % 2 or len(entries) // 2 + len(untracked_paths) > MAX_CAPTURE_FILES:
            raise WorktreeCaptureRejected("unsupported capture file inventory")
        files: dict[str, str] = {}
        total_bytes = 0
        for header, raw_path in zip(entries[::2], entries[1::2], strict=True):
            fields = header.split()
            if len(fields) != 5:
                raise WorktreeCaptureRejected("unsupported capture file inventory")
            modified = (
                fields[4] == b"M"
                and fields[0] in (b":100644", b":100755")
                and fields[0][1:] == fields[1]
            )
            added = (
                fields[4] == b"A"
                and fields[0] == b":000000"
                and fields[1] in (b"100644", b"100755")
            )
            if not modified and not added:
                raise WorktreeCaptureRejected(
                    "capture supports regular-file modifications and additions only"
                )
            try:
                path = raw_path.decode("utf-8")
                policy.authorize_read(path)
                policy.authorize_write(path)
                content = read_capture_file(root, path, executable=fields[1] == b"100755")
                # Bound the untrusted working-tree snapshot that recovery actually
                # captures.  The committed base blob is already trusted repository
                # data and is not embedded in the capture; counting it again made a
                # small edit to a large tracked text file fail even when both the
                # resulting snapshot and generated patch were within their limits.
                total_bytes += len(content)
                if total_bytes > MAX_CAPTURE_BYTES:
                    raise WorktreeCaptureRejected("capture content exceeds byte limit")
            except (OSError, UnicodeError, ValueError) as error:
                raise WorktreeCaptureRejected("capture cannot read a regular UTF-8 file") from error
            files[path] = hashlib.sha256(content).hexdigest()
        for path in sorted(untracked_paths):
            if path in files:
                raise WorktreeCaptureRejected("duplicate capture path")
            try:
                policy.authorize_read(path)
                policy.authorize_write(path)
                candidate = root / path
                content = read_capture_file(
                    root, path, executable=bool(candidate.lstat().st_mode & 0o100)
                )
                total_bytes += len(content)
                if total_bytes > MAX_CAPTURE_BYTES:
                    raise WorktreeCaptureRejected("capture content exceeds byte limit")
            except (OSError, UnicodeError, ValueError) as error:
                raise WorktreeCaptureRejected("capture cannot read a regular UTF-8 file") from error
            files[path] = hashlib.sha256(content).hexdigest()
        staged_paths = _decode_nul_paths(
            self._run_git_bytes(
                (*arguments, "--cached", "--name-only", "-z", diff_base, "--"), cwd=root
            )
        )
        if not staged_paths.issubset(files):
            raise WorktreeCaptureRejected("index-only changes require a separate recovery contract")
        patch_arguments = (
            *arguments,
            "--binary",
            "--full-index",
            "--no-color",
            "--unified=0",
            "--inter-hunk-context=0",
            "--src-prefix=a/",
            "--dst-prefix=b/",
        )
        patch = without_hunk_labels(
            self._run_git_bytes((*patch_arguments, diff_base, "--"), cwd=root)
        )
        for path in sorted(untracked_paths):
            patch += without_hunk_labels(
                self._run_git_diff_bytes(
                    (*patch_arguments, "--no-index", "--", "/dev/null", path), cwd=root
                )
            )
        staged = without_hunk_labels(
            self._run_git_bytes((*patch_arguments, "--cached", diff_base, "--"), cwd=root)
        )
        for payload in (patch, staged):
            if len(payload) > MAX_CAPTURE_BYTES:
                raise WorktreeCaptureRejected("capture diff exceeds byte limit")
            try:
                text = payload.decode("utf-8")
            except UnicodeError as error:
                raise WorktreeCaptureRejected("capture diff is not UTF-8") from error
            if b"GIT binary patch" in payload or redact_text(text).occurrences:
                # Redacting a reusable patch would silently change code. Refuse it;
                # never print/persist the original content or a transformed patch.
                raise WorktreeCaptureRejected("capture contains binary or sensitive content")
        return WorktreeChangeCapture(
            worktree=worktree,
            patch=patch,
            index_diff_sha256=hashlib.sha256(staged).hexdigest(),
            file_sha256s=tuple(sorted(files.items())),
            base_revision=base_revision,
        )

    def _path_exists_at_revision(self, root: Path, revision: str, path: str) -> bool:
        observed = _decode_nul_paths(
            self._run_git_bytes(("ls-tree", "-z", "--name-only", revision, "--", path), cwd=root)
        )
        if observed not in (set(), {path}):
            raise GitCommandError("Git returned an unexpected tree path")
        return observed == {path}

    def _validate_repository(self) -> None:
        if self._git is None or not self._repository.is_dir():
            raise InvalidRepository(str(self._repository))
        try:
            top_level = self._run_git(("rev-parse", "--show-toplevel"), cwd=self._repository)
        except GitWorkspaceError as error:
            raise InvalidRepository(str(self._repository)) from error
        if Path(top_level).resolve() != self._repository:
            raise InvalidRepository(f"repository must be a Git root: {self._repository}")

    def _resolve_revision(self, revision: str) -> str:
        try:
            return self._run_git(
                ("rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"),
                cwd=self._repository,
            )
        except GitWorkspaceError as error:
            raise RevisionNotFound(revision) from error

    def _validate_repository_filters(self) -> None:
        completed = self._invoke_git(
            (
                "config",
                "--local",
                "--name-only",
                "--get-regexp",
                r"^filter\..*\.(clean|smudge|process)$",
            ),
            cwd=self._repository,
        )
        if completed.returncode == 0:
            keys = ", ".join(completed.stdout.splitlines())
            raise UnsafeRepositoryConfiguration(
                f"external checkout filters require a stronger sandbox: {keys}"
            )
        if completed.returncode != 1:
            message = completed.stderr.strip() or "cannot inspect repository filter config"
            raise GitCommandError(message)

    def _validate_worktree_root(self) -> None:
        if (
            self._worktree_root == self._repository
            or self._repository in self._worktree_root.parents
        ):
            raise InvalidWorktreeRoot(
                f"worktree root must be outside main checkout: {self._worktree_root}"
            )

    def _validate_target_containment(self, target: Path) -> None:
        try:
            resolved_target = target.resolve(strict=False)
        except (OSError, RuntimeError) as error:
            raise InvalidWorktreeRoot(f"cannot resolve worktree target: {target}") from error
        if not resolved_target.is_relative_to(self._worktree_root):
            raise InvalidWorktreeRoot(f"worktree target escapes configured root: {target}")

    def _validate_target_has_no_symlinks(self, target: Path) -> None:
        try:
            relative_target = target.relative_to(self._worktree_root)
        except ValueError as error:
            raise InvalidWorktreeRoot(
                f"worktree target escapes configured root: {target}"
            ) from error
        current = self._worktree_root
        for part in relative_target.parts:
            current /= part
            if current.is_symlink():
                raise InvalidWorktreeRoot(
                    f"worktree target contains a symlink component: {current}"
                )

    def _branch_exists(self, branch: str) -> bool:
        completed = self._invoke_git(
            ("show-ref", "--verify", "--quiet", f"refs/heads/{branch}"),
            cwd=self._repository,
        )
        return completed.returncode == 0

    def _target_path(self, spec: WorktreeSpec) -> Path:
        return self._worktree_root / spec.task_id / f"{spec.role.value}-attempt-{spec.attempt:02d}"

    @staticmethod
    def _branch_name(spec: WorktreeSpec) -> str:
        return f"ai/{spec.task_id}/attempt-{spec.attempt}"

    def _validate_owned_worktree(self, worktree: WorktreeRef) -> Path:
        try:
            spec = WorktreeSpec(
                task_id=worktree.task_id,
                role=worktree.role,
                attempt=worktree.attempt,
                source_revision=worktree.head_revision,
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise UnmanagedWorktree(str(worktree.path)) from error
        expected = self._target_path(spec)
        expected_branch = self._branch_name(spec) if spec.role is AgentRole.CODER else None
        if worktree.path != expected or not expected.is_dir():
            raise UnmanagedWorktree(str(worktree.path))
        if worktree.branch != expected_branch or worktree.detached != (expected_branch is None):
            raise UnmanagedWorktree(str(worktree.path))
        try:
            ref_revision = self._resolve_revision(worktree.head_revision)
        except RevisionNotFound as error:
            raise UnmanagedWorktree(str(worktree.path)) from error
        if ref_revision != worktree.head_revision:
            raise UnmanagedWorktree(str(worktree.path))
        self._validate_target_containment(expected)
        self._validate_target_has_no_symlinks(expected)
        self._validate_registered_worktree(expected)
        self._validate_role_git_state(expected, expected_branch=expected_branch)
        return expected

    def _validate_registered_worktree(self, path: Path) -> None:
        try:
            top_level = self._run_git(("rev-parse", "--show-toplevel"), cwd=path)
            common_directory = self._run_git(
                ("rev-parse", "--path-format=absolute", "--git-common-dir"), cwd=path
            )
            manager_common_directory = self._run_git(
                ("rev-parse", "--path-format=absolute", "--git-common-dir"),
                cwd=self._repository,
            )
        except GitWorkspaceError as error:
            raise UnmanagedWorktree(str(path)) from error
        if Path(top_level).resolve() != path.resolve():
            raise UnmanagedWorktree(str(path))
        if Path(common_directory).resolve() != Path(manager_common_directory).resolve():
            raise UnmanagedWorktree(str(path))
        if path.resolve() not in self._registered_worktree_paths():
            raise UnmanagedWorktree(str(path))

    def _registered_worktree_paths(self) -> set[Path]:
        payload = self._run_git_bytes(
            ("worktree", "list", "--porcelain", "-z"), cwd=self._repository
        )
        try:
            fields = payload.decode("utf-8").split("\0")
        except UnicodeDecodeError as error:
            raise GitCommandError("Git returned a non-UTF-8 worktree path") from error
        paths: set[Path] = set()
        for field in fields:
            if field.startswith("worktree "):
                paths.add(Path(field.removeprefix("worktree ")).resolve())
        return paths

    def _validate_role_git_state(self, path: Path, *, expected_branch: str | None) -> None:
        actual_branch = self._current_branch(path)
        if actual_branch != expected_branch:
            expected = expected_branch if expected_branch is not None else "detached HEAD"
            observed = actual_branch if actual_branch is not None else "detached HEAD"
            raise WorktreeIdentityDrift(
                f"worktree role identity drift for {path}: expected {expected}, observed {observed}"
            )

    def _current_branch(self, path: Path) -> str | None:
        completed = self._invoke_git(("symbolic-ref", "--quiet", "--short", "HEAD"), cwd=path)
        if completed.returncode == 0:
            branch = completed.stdout.strip()
            if not branch:
                raise GitCommandError("Git returned an empty symbolic branch")
            return branch
        if completed.returncode == 1:
            return None
        message = completed.stderr.strip() or "cannot inspect worktree branch"
        raise GitCommandError(message)

    def _run_git(self, arguments: tuple[str, ...], *, cwd: Path) -> str:
        completed = self._invoke_git(arguments, cwd=cwd)
        if completed.returncode != 0:
            command = " ".join(("git", *arguments))
            message = completed.stderr.strip() or "Git command failed"
            raise GitCommandError(f"{command}: {message}")
        return completed.stdout.strip()

    def _run_git_bytes(
        self,
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        input: bytes | None = None,
        index_file: Path | None = None,
    ) -> bytes:
        if self._git is None:
            raise InvalidRepository("Git executable is unavailable")
        try:
            completed = subprocess.run(
                (self._git, *_GIT_SAFETY_CONFIG, *arguments),
                cwd=cwd,
                env=_GIT_ENV
                if index_file is None
                else {**_GIT_ENV, "GIT_INDEX_FILE": str(index_file)},
                check=False,
                capture_output=True,
                text=False,
                input=input,
                timeout=self._command_timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as error:
            raise GitCommandTimeout("Git command timed out") from error
        except OSError as error:
            raise GitCommandError("Git command could not start") from error
        if completed.returncode != 0:
            message = completed.stderr.decode("utf-8", errors="replace").strip()
            raise GitCommandError(message or "Git command failed")
        return completed.stdout

    def _run_git_diff_bytes(self, arguments: tuple[str, ...], *, cwd: Path) -> bytes:
        """Run a read-only diff command where Git uses status 1 to mean differences."""
        if self._git is None:
            raise InvalidRepository("Git executable is unavailable")
        try:
            completed = subprocess.run(
                (self._git, *_GIT_SAFETY_CONFIG, *arguments),
                cwd=cwd,
                env=_GIT_ENV,
                check=False,
                capture_output=True,
                text=False,
                timeout=self._command_timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as error:
            raise GitCommandTimeout("Git diff command timed out") from error
        except OSError as error:
            raise GitCommandError("Git diff command could not start") from error
        if completed.returncode not in (0, 1):
            message = completed.stderr.decode("utf-8", errors="replace").strip()
            raise GitCommandError(message or "Git diff command failed")
        return completed.stdout

    def _invoke_git(
        self, arguments: tuple[str, ...], *, cwd: Path
    ) -> subprocess.CompletedProcess[str]:
        if self._git is None:
            raise InvalidRepository("Git executable is unavailable")
        try:
            return subprocess.run(
                (self._git, *_GIT_SAFETY_CONFIG, *arguments),
                cwd=cwd,
                env=_GIT_ENV,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._command_timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as error:
            raise GitCommandTimeout("Git command timed out") from error
        except OSError as error:
            raise GitCommandError("Git command could not start") from error


def _decode_nul_paths(payload: bytes) -> set[str]:
    try:
        return {raw_path.decode("utf-8") for raw_path in payload.split(b"\0") if raw_path}
    except UnicodeDecodeError as error:
        raise GitCommandError("Git returned a non-UTF-8 repository path") from error
