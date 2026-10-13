"""Compare-and-delete exact Requirement-owned Git references."""

from __future__ import annotations

import hashlib
from contextlib import closing
from pathlib import Path
from typing import Literal

from pydantic import Field
from pymysql.cursors import DictCursor

from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git.ports import WorktreeSpec
from ai_software_engineer.git.release import WorktreeReleaseArchive
from ai_software_engineer.git.worktree import GitWorktreeManager
from ai_software_engineer.multi_directory.models import JointCheckpoint
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.safe_files import _read_regular, _reject_symlinks
from ai_software_engineer.store.mysql_repository import open_mysql_connection


class PurgeGitRef(DomainModel):
    repository_id: str
    ref_name: str
    expected_revision: str = Field(pattern=r"^[a-f0-9]{40}(?:[a-f0-9]{24})?$")
    kind: Literal["retained", "task-branch"]


def collect_git_resources(
    project: ProjectWorkspace,
    checkpoint: JointCheckpoint,
    task_roots: dict[str, str],
    dsn: str | None = None,
) -> tuple[tuple[PurgeGitRef, ...], tuple[Path, ...]]:
    archives = project.requirements_root / checkpoint.delivery_id / "resource-archives"
    owner = hashlib.sha256(
        (checkpoint.team_id + ":" + checkpoint.project_id + ":" + checkpoint.delivery_id).encode()
    ).hexdigest()
    repositories = {
        str(repo.repository_root): repo for repo in project.repository_registry().discover()
    }
    refs: dict[tuple[str, str], PurgeGitRef] = {}
    markers: list[Path] = []
    archived_heads: dict[tuple[str, str], set[str]] = {}
    for path in sorted(archives.glob("*/archive.json")):
        _reject_symlinks(path)
        archive = WorktreeReleaseArchive.model_validate_json(_read_regular(path, 32 * 1024 * 1024))
        if archive.owner_sha256 != owner or archive.repository_root not in repositories:
            raise ValueError("worktree archive owner differs")
        repo = repositories[archive.repository_root]
        worktree = Path(archive.worktree_path)
        expected_ref = (
            "refs/ase/retained/" + owner + "/" + hashlib.sha256(str(worktree).encode()).hexdigest()
        )
        platform = Path(project.team.manifest.platform_root) / "worktrees"
        root = platform / repo.repository_id
        if archive.task_id in task_roots:
            if task_roots[archive.task_id] != archive.repository_root:
                raise ValueError("worktree archive task repository differs")
        else:
            # Baseline and candidate read-only worktrees use the exact approved unit scope.
            unit = next(
                (
                    unit
                    for unit in checkpoint.scope.units
                    if worktree.is_relative_to(
                        platform / "requirements" / checkpoint.delivery_id / unit.id
                    )
                    and unit.root == archive.repository_root
                ),
                None,
            )
            if (
                unit is None
                or archive.role != "reviewer"
                or not archive.task_id.startswith(("task_baseline_", "task_candidate_"))
            ):
                raise ValueError("worktree archive has another requirement scope")
            root = platform / "requirements" / checkpoint.delivery_id / unit.id
        if archive.retained_ref != expected_ref:
            raise ValueError("worktree retained ref owner differs")
        for name in ("release-intent.json", "released.json"):
            if (
                _read_regular(path.parent / name, 32 * 1024 * 1024)
                != archive.model_dump_json().encode()
            ):
                raise ValueError("worktree release is not complete")
        manager = GitWorktreeManager(
            archive.repository_root,
            root,
            branch_names={archive.task_id: archive.branch}
            if archive.branch
            and archive.branch != f"ai/{archive.task_id}/attempt-{archive.attempt}"
            else None,
        )
        spec = WorktreeSpec(
            task_id=archive.task_id,
            role=AgentRole(archive.role),
            attempt=archive.attempt,
            source_revision=archive.head_revision,
        )
        if manager._target_path(spec) != worktree or worktree.exists():
            raise ValueError("worktree remains registered or has another path")
        refs[(repo.repository_id, archive.retained_ref)] = PurgeGitRef(
            repository_id=repo.repository_id,
            ref_name=archive.retained_ref,
            expected_revision=archive.head_revision,
            kind="retained",
        )
        if archive.branch is not None:
            if archive.role != "coder" or archive.branch in {"main", "master", "develop"}:
                raise ValueError("protected or foreign worktree branch")
            ref = "refs/heads/" + archive.branch
            archived_heads.setdefault((repo.repository_id, ref), set()).add(archive.head_revision)
            refs[(repo.repository_id, ref)] = PurgeGitRef(
                repository_id=repo.repository_id,
                ref_name=ref,
                expected_revision=archive.head_revision,
                kind="task-branch",
            )
            marker = manager._removal_marker(spec, archive.branch)
            if marker.exists():
                manager._require_removal_marker(marker)
                markers.append(marker)
    # Multiple releases of the same Coder branch retain different heads. The
    # current branch must match one verified archive, never the last filename.
    for (repository_id, name), heads in archived_heads.items():
        repo = next(repo for repo in repositories.values() if repo.repository_id == repository_id)
        manager = GitWorktreeManager(
            repo.repository_root,
            Path(project.team.manifest.platform_root) / "worktrees" / repository_id,
        )
        current = manager._run_git(
            ("for-each-ref", "--format=%(objectname)", name), cwd=repo.repository_root
        )
        if current and current not in heads:
            raise ValueError("archived Task branch changed")
        if current:
            refs[(repository_id, name)] = refs[(repository_id, name)].model_copy(
                update={"expected_revision": current}
            )
    # A cleanly removed worktree has no release archive. Its typed durable Task
    # still declares the branch's exact ownership. Freeze the current SHA for CAS.
    if dsn is not None and task_roots:
        with (
            closing(open_mysql_connection(dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute("SELECT id, payload_json FROM tasks")
            tasks = []
            for row in cursor.fetchall():
                task = Task.model_validate_json(row["payload_json"])
                if task.id != row["id"]:
                    raise ValueError("Task storage identity differs")
                tasks.append(task)
        for task in tasks:
            if task.id not in task_roots:
                continue
            if task.repository != task_roots[task.id] or task.status not in {
                TaskStatus.DONE,
                TaskStatus.BLOCKED,
                TaskStatus.FAILED,
            }:
                raise ValueError("Task branch owner is active or foreign")
            repo = repositories[task.repository]
            from ai_software_engineer.repository_profile import RepositoryProfile, VcsKind

            if (
                RepositoryProfile.discover(
                    repo.repository_root, repository_id=repo.repository_id
                ).vcs.kind
                is not VcsKind.GIT
            ):
                continue
            names = (
                (task.branch_name,)
                if task.branch_name is not None
                else tuple(
                    f"ai/{task.id}/attempt-{attempt}" for attempt in range(1, task.attempts + 1)
                )
            )
            manager = GitWorktreeManager(
                repo.repository_root,
                Path(project.team.manifest.platform_root) / "worktrees" / repo.repository_id,
                branch_names={task.id: task.branch_name},
            )
            for name in names:
                if name in {"main", "master", "develop"} or any(
                    other.id != task.id
                    and other.repository == task.repository
                    and other.branch_name == name
                    for other in tasks
                ):
                    raise ValueError("Task branch is protected or shared")
                ref = "refs/heads/" + name
                current = manager._run_git(
                    ("for-each-ref", "--format=%(objectname)", ref), cwd=repo.repository_root
                )
                if current:
                    marker_directory = (
                        Path(project.team.manifest.platform_root)
                        / "worktrees"
                        / repo.repository_id
                        / task.id
                    )
                    pending_markers = tuple(marker_directory.glob(".coder-attempt-*.removed-*"))
                    matched = []
                    if pending_markers:
                        revisions = {current, *archived_heads.get((repo.repository_id, ref), set())}
                        if len(task.base_ref) in (40, 64) and all(
                            char in "abcdef0123456789" for char in task.base_ref
                        ):
                            revisions.add(task.base_ref)
                        with (
                            closing(open_mysql_connection(dsn)) as history_connection,
                            history_connection.cursor(DictCursor) as history_cursor,
                        ):
                            history_cursor.execute(
                                "SELECT event_id, payload_json FROM state_events WHERE task_id=%s",
                                (task.id,),
                            )
                            for row in history_cursor.fetchall():
                                event = StateEvent.model_validate_json(row["payload_json"])
                                if event.task_id != task.id or event.event_id != row["event_id"]:
                                    raise ValueError("Task source history identity differs")
                                revisions.add(event.source_revision)
                        from ai_software_engineer.artifacts.store import FileArtifactStore

                        artifact_root = repo.root / "artifacts"
                        if artifact_root.exists():
                            artifacts = FileArtifactStore(artifact_root, read_only=True)
                            for path in sorted(artifact_root.glob("*.json")):
                                artifact = artifacts.get(path.stem)
                                if artifact.task_id == task.id:
                                    revisions.add(artifact.source_revision)
                        for revision in sorted(revisions):
                            for attempt in range(1, task.attempts + 1):
                                spec = WorktreeSpec(
                                    task_id=task.id,
                                    role=AgentRole.CODER,
                                    attempt=attempt,
                                    source_revision=revision,
                                )
                                marker = manager._removal_marker(spec, name)
                                if marker in pending_markers:
                                    manager._require_removal_marker(marker)
                                    matched.append(marker)
                        markers.extend(matched)
                    # A requested branch can collide with a pre-existing ref.
                    # The Task declaration alone never proves that it created it.
                    if not matched and (repo.repository_id, ref) not in archived_heads:
                        if task.branch_name is None:
                            raise ValueError(
                                "legacy Task branch has no verified removal provenance; "
                                "exact operator cleanup is required"
                            )
                        continue
                    refs[(repo.repository_id, ref)] = PurgeGitRef(
                        repository_id=repo.repository_id,
                        ref_name=ref,
                        expected_revision=current,
                        kind="task-branch",
                    )
    return tuple(refs[key] for key in sorted(refs)), tuple(markers)


def verify_git_refs(project: ProjectWorkspace, refs: tuple[PurgeGitRef, ...]) -> None:
    repositories = {repo.repository_id: repo for repo in project.repository_registry().discover()}
    for ref in refs:
        if (
            ref.repository_id not in repositories
            or (ref.kind == "retained" and not ref.ref_name.startswith("refs/ase/retained/"))
            or (
                ref.kind == "task-branch"
                and (
                    not ref.ref_name.startswith("refs/heads/")
                    or ref.ref_name
                    in {"refs/heads/main", "refs/heads/master", "refs/heads/develop"}
                )
            )
        ):
            raise ValueError("unauthorized physical-delete Git reference")
        repo = repositories[ref.repository_id]
        manager = GitWorktreeManager(
            repo.repository_root,
            Path(project.team.manifest.platform_root) / "worktrees" / repo.repository_id,
        )
        current = manager._run_git(
            ("for-each-ref", "--format=%(objectname)", ref.ref_name), cwd=repo.repository_root
        )
        if current and current != ref.expected_revision:
            raise ValueError("Requirement Git reference changed")
        registered = manager._run_git(("worktree", "list", "--porcelain"), cwd=repo.repository_root)
        if "branch " + ref.ref_name in registered.splitlines():
            raise ValueError("Requirement Git branch is still in use")


def delete_git_refs(project: ProjectWorkspace, refs: tuple[PurgeGitRef, ...]) -> None:
    verify_git_refs(project, refs)
    repositories = {repo.repository_id: repo for repo in project.repository_registry().discover()}
    for ref in refs:
        repo = repositories[ref.repository_id]
        manager = GitWorktreeManager(
            repo.repository_root,
            Path(project.team.manifest.platform_root) / "worktrees" / repo.repository_id,
        )
        current = manager._run_git(
            ("for-each-ref", "--format=%(objectname)", ref.ref_name), cwd=repo.repository_root
        )
        if current:
            manager._run_git(
                ("update-ref", "-d", ref.ref_name, ref.expected_revision), cwd=repo.repository_root
            )
