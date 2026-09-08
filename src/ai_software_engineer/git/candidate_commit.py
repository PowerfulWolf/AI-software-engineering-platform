"""Policy-bound platform Skill for turning a Coder draft into a Git candidate."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.artifact import CommitSha
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.git.policy import WorkspacePolicy, WorkspacePolicyError


class CandidateCommitError(RuntimeError):
    """Base error for deterministic candidate finalization failures."""


class CandidateCommitRejected(CandidateCommitError, WorkspacePolicyError):
    """Raised when observed Git facts do not match the authorized request."""


class CandidateCommitRequest(DomainModel):
    """Exact authority granted to one platform-owned candidate commit operation."""

    task_id: TaskId
    source_revision: CommitSha
    reported_paths: tuple[NonEmptyStr, ...]
    permissions: AgentPermissions

    def model_post_init(self, __context: object) -> None:
        del __context
        ensure_unique(self.reported_paths, "CandidateCommit reported paths")
        if tuple(sorted(self.reported_paths)) != self.reported_paths:
            raise ValueError("CandidateCommit reported paths must be sorted")
        if not self.reported_paths:
            raise ValueError("CandidateCommit requires at least one reported path")


class CandidateCommitResult(DomainModel):
    """Observed immutable output of one successful candidate commit."""

    task_id: TaskId
    source_revision: CommitSha
    candidate_revision: CommitSha
    changed_paths: tuple[NonEmptyStr, ...]

    def model_post_init(self, __context: object) -> None:
        del __context
        ensure_unique(self.changed_paths, "CandidateCommit changed paths")
        if tuple(sorted(self.changed_paths)) != self.changed_paths:
            raise ValueError("CandidateCommit changed paths must be sorted")
        if self.candidate_revision == self.source_revision:
            raise ValueError("CandidateCommit must create a new revision")


class CandidateCommitSkill(Protocol):
    """Least-authority Project Manager Skill for one role worktree."""

    def changed_paths(self) -> tuple[str, ...]: ...

    def finalize(self, request: CandidateCommitRequest) -> CandidateCommitResult: ...


class GitCandidateCommitSkill:
    """Validate a complete Coder draft and create one hook-free candidate commit."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        root = Path(workspace_root).expanduser().resolve(strict=False)
        if not root.is_dir() or root.is_symlink():
            raise CandidateCommitError("candidate workspace must be an existing real directory")
        self._root = root
        source = environment if environment is not None else os.environ
        self._environment = {
            "PATH": source.get("PATH", os.defpath),
            "LANG": "C",
            "LC_ALL": "C",
            "GIT_TERMINAL_PROMPT": "0",
        }

    def finalize(self, request: CandidateCommitRequest) -> CandidateCommitResult:
        """Create a candidate only after exact Git and path-policy validation."""
        initial_head = self._git("rev-parse", "HEAD")
        if initial_head != request.source_revision:
            raise CandidateCommitRejected("candidate source revision drifted")
        observed = self.changed_paths()
        if not observed:
            raise CandidateCommitRejected("candidate draft contains no changes")
        if observed != request.reported_paths:
            raise CandidateCommitRejected(
                "candidate reported paths do not match the dirty worktree"
            )
        policy = WorkspacePolicy(self._root, request.permissions)
        try:
            for path in observed:
                policy.authorize_write(path)
        except WorkspacePolicyError as error:
            raise CandidateCommitRejected("candidate path is outside Coder authority") from error

        self._git(
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "add",
            "--all",
            "--",
            *observed,
        )
        if self.changed_paths() != observed:
            raise CandidateCommitRejected("candidate worktree changed during finalization")
        self._git(
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "commit.gpgSign=false",
            "-c",
            "user.name=AI Software Engineer",
            "-c",
            "user.email=ai-software-engineer@localhost",
            "commit",
            "--no-gpg-sign",
            "--no-verify",
            "-m",
            f"ai: {request.task_id}",
        )
        candidate = self._git("rev-parse", "HEAD")
        if self._git("status", "--porcelain"):
            raise CandidateCommitRejected("candidate commit did not leave a clean worktree")
        committed = tuple(
            sorted(
                line
                for line in self._git(
                    "diff",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--no-renames",
                    "--name-only",
                    f"{request.source_revision}..{candidate}",
                    "--",
                ).splitlines()
                if line
            )
        )
        if committed != observed:
            raise CandidateCommitRejected("candidate commit path inventory changed")
        return CandidateCommitResult(
            task_id=request.task_id,
            source_revision=request.source_revision,
            candidate_revision=candidate,
            changed_paths=committed,
        )

    def changed_paths(self) -> tuple[str, ...]:
        """Return tracked and untracked nonignored paths relative to the worktree."""
        tracked = self._git_nul(
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--name-only",
            "-z",
            "HEAD",
            "--",
        )
        untracked = self._git_nul("ls-files", "--others", "--exclude-standard", "-z")
        return tuple(sorted(set((*tracked, *untracked))))

    def _git(self, *arguments: str) -> str:
        try:
            completed = subprocess.run(
                ("git", *arguments),
                cwd=self._root,
                env=self._environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CandidateCommitError("candidate Git operation failed") from error
        if completed.returncode != 0:
            raise CandidateCommitError("candidate Git operation failed")
        return completed.stdout.strip()

    def _git_nul(self, *arguments: str) -> tuple[str, ...]:
        try:
            completed = subprocess.run(
                ("git", *arguments),
                cwd=self._root,
                env=self._environment,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CandidateCommitError("candidate Git inspection failed") from error
        if completed.returncode != 0:
            raise CandidateCommitError("candidate Git inspection failed")
        try:
            return tuple(value.decode("utf-8") for value in completed.stdout.split(b"\0") if value)
        except UnicodeDecodeError as error:
            raise CandidateCommitRejected("candidate worktree contains a non-UTF-8 path") from error


__all__ = [
    "CandidateCommitError",
    "CandidateCommitRejected",
    "CandidateCommitRequest",
    "CandidateCommitResult",
    "CandidateCommitSkill",
    "GitCandidateCommitSkill",
]
