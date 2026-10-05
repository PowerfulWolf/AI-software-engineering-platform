"""Policy-bound original-branch baseline movement with separately retained dirty drafts."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.execution_baseline import BaselineInputMode
from ai_software_engineer.git.capture import MAX_CAPTURE_BYTES, without_hunk_labels
from ai_software_engineer.git.mutation import (
    WorkspaceMutationInventory,
    capture_mutation_inventory,
    changed_mutation_paths,
)
from ai_software_engineer.git.mutation_capture import WorktreeMutationCapture
from ai_software_engineer.git.ports import WorktreeRef, WorktreeSpec
from ai_software_engineer.git.worktree import (
    _GIT_ENV,
    _GIT_SAFETY_CONFIG,
    GitCommandError,
    GitWorkspaceError,
    GitWorktreeManager,
)
from ai_software_engineer.redaction import redact_text

_EMPTY = hashlib.sha256(b"").hexdigest()
_DIFF = (
    "--no-optional-locks",
    "-c",
    "core.fileMode=true",
    "diff",
    "--no-ext-diff",
    "--no-textconv",
    "--no-renames",
)


class BaselineGitRejected(GitWorkspaceError):
    """Preserve the sealed source/target state; never force-reset unknown files."""


class BaselineGitConflict(BaselineGitRejected):
    """A new exact coder_reapply plan is required; the source worktree is untouched."""


@dataclass(frozen=True, slots=True)
class BaselineGitPreview:
    source_revision: str
    dirty_tree: str
    dirty_patch: str


class GitExecutionBaselineAdapter:
    """Trusted Git seam. A caller must hold Task/store locks and exact authority.

    Only preview writes unreachable Git objects. Existing branch/index/files are
    changed by apply after its exact captures and operation start are persisted.
    """

    def __init__(self, manager: GitWorktreeManager) -> None:
        self.manager = manager

    def preview(
        self,
        *,
        dirty: WorktreeMutationCapture,
        complete: WorktreeMutationCapture,
        target_base: str,
        permissions: AgentPermissions,
        denied_paths: tuple[str, ...],
        input_mode: BaselineInputMode,
    ) -> BaselineGitPreview:
        manager, root = self.manager, dirty.worktree.path
        manager.verify_mutations(dirty, permissions, denied_paths=denied_paths)
        manager.verify_mutations(complete, permissions, denied_paths=denied_paths)
        if dirty.index_diff_sha256 != _EMPTY:
            raise BaselineGitRejected("baseline update requires the exact unstaged Coder draft")
        manager._validate_repository_filters()
        if manager._resolve_revision(target_base) != target_base:
            raise BaselineGitRejected("baseline target must be a full immutable commit SHA")
        manager._run_git(
            ("merge-base", "--is-ancestor", complete.effective_base_revision, target_base), cwd=root
        )
        manager._validate_seed_configuration(dirty.worktree, complete.changed_paths)
        for revision in (target_base, dirty.worktree.head_revision):
            if complete.changed_paths:
                attributes = manager._run_git_bytes(
                    (
                        "check-attr",
                        f"--source={revision}",
                        "-z",
                        "merge",
                        "filter",
                        "--",
                        *complete.changed_paths,
                    ),
                    cwd=root,
                ).split(b"\0")[:-1]
                if len(attributes) != len(complete.changed_paths) * 6 or any(
                    value != b"unspecified" for value in attributes[2::3]
                ):
                    raise BaselineGitRejected(
                        "baseline replay does not admit custom merge/filter attributes"
                    )
        if input_mode is BaselineInputMode.CODER_REAPPLY:
            tree = manager._run_git(("rev-parse", f"{target_base}^{{tree}}"), cwd=root)
            return BaselineGitPreview(target_base, tree, "")
        merge = manager._invoke_git(
            (
                "-c",
                "merge.default=text",
                "merge-tree",
                "--write-tree",
                f"--merge-base={complete.effective_base_revision}",
                target_base,
                dirty.worktree.head_revision,
            ),
            cwd=root,
        )
        if merge.returncode != 0:
            raise BaselineGitConflict(
                "old committed work conflicts with the new execution baseline"
            )
        tree = merge.stdout.splitlines()[0]
        target_tree = manager._run_git(("rev-parse", f"{target_base}^{{tree}}"), cwd=root)
        source = (
            target_base
            if tree == target_tree
            else self._commit_tree(tree, target_base, dirty.worktree.head_revision, root)
        )
        with tempfile.TemporaryDirectory(prefix="ase-baseline-index-") as temporary:
            index = Path(temporary) / "index"
            manager._run_git_bytes(("read-tree", source), cwd=root, index_file=index)
            if dirty.patch:
                try:
                    manager._run_git_bytes(
                        (
                            "-c",
                            "merge.default=text",
                            "apply",
                            "--3way",
                            "--cached",
                            "--unidiff-zero",
                            "--whitespace=nowarn",
                            "-",
                        ),
                        cwd=root,
                        input=dirty.patch,
                        index_file=index,
                    )
                except GitCommandError as error:
                    raise BaselineGitConflict(
                        "retained dirty draft conflicts with the new execution input"
                    ) from error
            dirty_tree = (
                manager._run_git_bytes(("write-tree",), cwd=root, index_file=index)
                .decode("ascii")
                .strip()
            )
        patch = without_hunk_labels(
            manager._run_git_bytes(
                (
                    *_DIFF,
                    "--binary",
                    "--full-index",
                    "--no-color",
                    "--unified=0",
                    "--src-prefix=a/",
                    "--dst-prefix=b/",
                    source,
                    dirty_tree,
                    "--",
                ),
                cwd=root,
            )
        )
        paths = (
            manager._run_git_bytes(
                (*_DIFF, "--name-only", "-z", source, dirty_tree, "--"), cwd=root
            )
            .decode("utf-8")
            .split("\0")
        )
        if not set(filter(None, paths)).issubset(dirty.changed_paths):
            raise BaselineGitRejected(
                "baseline draft replay changed paths outside the retained draft"
            )
        text = patch.decode("utf-8")
        if (
            len(patch) > MAX_CAPTURE_BYTES
            or b"GIT binary patch" in patch
            or redact_text(text).occurrences
        ):
            raise BaselineGitRejected("replayed draft must remain bounded nonsensitive text")
        manager.verify_mutations(dirty, permissions, denied_paths=denied_paths)
        manager.verify_mutations(complete, permissions, denied_paths=denied_paths)
        return BaselineGitPreview(source, dirty_tree, text)

    def _commit_tree(self, tree: str, parent: str, original: str, root: Path) -> str:
        manager = self.manager
        if manager._git is None:
            raise BaselineGitRejected("Git is unavailable")
        environment = {
            **_GIT_ENV,
            "GIT_AUTHOR_NAME": "ASE Baseline",
            "GIT_AUTHOR_EMAIL": "baseline@ase.invalid",
            "GIT_COMMITTER_NAME": "ASE Baseline",
            "GIT_COMMITTER_EMAIL": "baseline@ase.invalid",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+0000",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+0000",
        }
        message = (
            "Retain approved Task work on execution baseline\n\n"
            f"Original source: {original}\nExecution base: {parent}\n"
        )
        try:
            result = subprocess.run(
                (
                    manager._git,
                    *_GIT_SAFETY_CONFIG,
                    "-c",
                    "commit.gpgSign=false",
                    "commit-tree",
                    tree,
                    "-p",
                    parent,
                ),
                cwd=root,
                env=environment,
                input=message.encode(),
                capture_output=True,
                shell=False,
                timeout=manager._command_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BaselineGitRejected("baseline source object could not be prepared") from error
        if result.returncode != 0:
            raise BaselineGitRejected("baseline source object could not be prepared")
        return result.stdout.decode("ascii").strip()

    def _tree_for_worktree(
        self,
        source: str,
        root: Path,
        permissions: AgentPermissions,
        denied_paths: tuple[str, ...],
        old: WorktreeRef,
    ) -> str:
        manager = self.manager
        reference = replace(old, head_revision=source)
        capture = manager.capture_mutations(reference, permissions, denied_paths=denied_paths)
        if capture.index_diff_sha256 != _EMPTY:
            raise BaselineGitRejected("unknown staged baseline state must be preserved")
        with tempfile.TemporaryDirectory(prefix="ase-baseline-observe-") as temporary:
            index = Path(temporary) / "index"
            manager._run_git_bytes(("read-tree", source), cwd=root, index_file=index)
            if capture.patch:
                manager._run_git_bytes(
                    ("apply", "--cached", "--unidiff-zero", "--whitespace=nowarn", "-"),
                    cwd=root,
                    input=capture.patch,
                    index_file=index,
                )
            return (
                manager._run_git_bytes(("write-tree",), cwd=root, index_file=index)
                .decode("ascii")
                .strip()
            )

    def apply(
        self,
        *,
        dirty: WorktreeMutationCapture,
        complete: WorktreeMutationCapture,
        preview: BaselineGitPreview,
        plan_sha256: str,
        permissions: AgentPermissions,
        denied_paths: tuple[str, ...],
        original_inventory: WorkspaceMutationInventory,
    ) -> tuple[WorktreeRef, str]:
        """Replay only four exact planned states after a durable admitted start.

        Source objects and full before/after bodies are preserved before the
        caller enters this method. Any fifth state is retained for engineering.
        """
        manager, old = self.manager, dirty.worktree
        root, source = old.path, preview.source_revision
        manager._validate_repository_filters()
        manager._validate_owned_worktree(old)
        head = manager._run_git(("rev-parse", "HEAD"), cwd=root)
        old_tree = manager._run_git(("rev-parse", f"{old.head_revision}^{{tree}}"), cwd=root)
        new_tree = manager._run_git(("rev-parse", f"{source}^{{tree}}"), cwd=root)
        if head not in (old.head_revision, source):
            raise BaselineGitRejected("baseline source HEAD is outside the sealed operation")
        # Preserve original candidate ancestry under a private manager ref; no
        # successor branch or new public candidate is introduced.
        backup = f"refs/ase/baselines/{old.task_id}/{plan_sha256}/source"
        found = manager._invoke_git(("rev-parse", "--verify", backup), cwd=root)
        if found.returncode == 0:
            if found.stdout.strip() != old.head_revision:
                raise BaselineGitRejected("baseline retained source ref has drifted")
        else:
            manager._run_git(
                ("update-ref", backup, old.head_revision, "0" * len(old.head_revision)), cwd=root
            )
        index_tree = manager._run_git(("write-tree",), cwd=root)
        if head == old.head_revision:
            original = manager.capture_mutations(old, permissions, denied_paths=denied_paths)
            if original == dirty:
                if capture_mutation_inventory(root) != original_inventory:
                    raise BaselineGitRejected(
                        "baseline source inventory changed before draft retention"
                    )
                manager.verify_mutations(complete, permissions, denied_paths=denied_paths)
                if dirty.patch:
                    manager._run_git_bytes(
                        ("apply", "--reverse", "--unidiff-zero", "--whitespace=nowarn", "-"),
                        cwd=root,
                        input=dirty.patch,
                    )
            elif original.patch or index_tree != old_tree:
                raise BaselineGitRejected(
                    "baseline operation found an unknown partially changed draft"
                )
            clean = manager.capture_mutations(old, permissions, denied_paths=denied_paths)
            if clean.patch or clean.index_diff_sha256 != _EMPTY:
                raise BaselineGitRejected(
                    "sealed draft reversal did not leave exact original clean source"
                )
            if source != old.head_revision:
                manager._run_git(
                    ("update-ref", f"refs/heads/{old.branch}", source, old.head_revision), cwd=root
                )
            head = source
            index_tree = old_tree
        if index_tree == old_tree and old_tree != new_tree:
            # CAS ref publication may beat checkout during a crash. read-tree -m
            # refuses dirty/untracked collisions; it never force-cleans them.
            unstaged = manager._run_git_bytes((*_DIFF, "--name-only", "-z", "--"), cwd=root)
            if unstaged:
                raise BaselineGitRejected(
                    "baseline checkout has unknown writes after ref publication"
                )
            manager._run_git(("read-tree", "-m", "-u", old.head_revision, source), cwd=root)
            index_tree = new_tree
        if index_tree != new_tree:
            raise BaselineGitRejected("baseline index is outside exact old/new source states")
        allowed_inventory_paths = set(complete.changed_paths)
        moved_paths = (
            manager._run_git_bytes(
                (*_DIFF, "--name-only", "-z", old.head_revision, source, "--"), cwd=root
            )
            .decode("utf-8")
            .split("\0")
        )
        allowed_inventory_paths.update(filter(None, moved_paths))
        if not set(
            changed_mutation_paths(original_inventory, capture_mutation_inventory(root))
        ).issubset(allowed_inventory_paths):
            raise BaselineGitRejected(
                "baseline operation found unrelated ignored/protected inventory writes"
            )
        current = replace(old, head_revision=source)
        observed_tree = self._tree_for_worktree(source, root, permissions, denied_paths, old)
        if observed_tree == new_tree and preview.dirty_patch:
            manager._run_git_bytes(
                ("apply", "--unidiff-zero", "--whitespace=nowarn", "-"),
                cwd=root,
                input=preview.dirty_patch.encode("utf-8"),
            )
            observed_tree = self._tree_for_worktree(source, root, permissions, denied_paths, old)
        if observed_tree != preview.dirty_tree:
            raise BaselineGitRejected("baseline output does not match the exact preflighted draft")
        manager.recover(
            WorktreeSpec(task_id=old.task_id, role=old.role, attempt=1, source_revision=source)
        )
        return current, capture_mutation_inventory(root).sha256
