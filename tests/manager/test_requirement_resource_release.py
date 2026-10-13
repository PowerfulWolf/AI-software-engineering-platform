"""Public close/delete release exact real Git resources after typed execution stop."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.git.ports import WorktreeRef, WorktreeSpec
from ai_software_engineer.git.release import WorktreeReleaseArchive
from ai_software_engineer.git.worktree import GitWorktreeManager
from ai_software_engineer.multi_directory.deletion import (
    RequirementDeletionRejected,
)
from ai_software_engineer.multi_directory.models import JointStage
from tests.git.test_resource_release import git
from tests.manager.test_requirement_deletion import _delete
from tests.manager.test_waiting_requirement_close import _close, _waiting


def _initialize(root: Path) -> str:
    git(root, "init")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    (root / "code.txt").write_text("base\n")
    (root / ".gitignore").write_text("cache/\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "fixture")
    return git(root, "rev-parse", "HEAD")


@pytest.mark.parametrize("failure", [False, True])
def test_public_close_preserves_drafts_releases_all_roles_and_baseline_then_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: bool
) -> None:
    service, checkpoint, repository, _queue, _ = _waiting(tmp_path, monkeypatch)
    source = next(iter(repository.tasks.values()))
    revision = _initialize(Path(source.repository))
    root = (
        Path(service.team.manifest.platform_root)
        / "worktrees"
        / checkpoint.children[0].checkpoint.repository_id
    )
    manager = GitWorktreeManager(
        source.repository, root, branch_names={source.id: source.branch_name}
    )
    refs = []
    for role in (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER):
        ref = manager.create(
            WorktreeSpec(task_id=source.id, role=role, attempt=1, source_revision=revision)
        )
        (ref.path / "code.txt").write_text("saved " + role.value)
        (ref.path / "cache").mkdir()
        (ref.path / "cache/output").write_text("ignored")
        refs.append(ref)
    unit = checkpoint.scope.units[0]
    baseline_root = (
        Path(service.team.manifest.platform_root)
        / "worktrees/requirements"
        / checkpoint.delivery_id
        / unit.id
    )
    baseline_manager = GitWorktreeManager(source.repository, baseline_root)
    baseline_id = (
        "task_baseline_"
        + hashlib.sha256(f"{checkpoint.delivery_id}:{unit.id}".encode()).hexdigest()[:32]
    )
    baseline = baseline_manager.create(
        WorktreeSpec(
            task_id=baseline_id, role=AgentRole.REVIEWER, attempt=1, source_revision=revision
        )
    )
    other = manager.create(
        WorktreeSpec(task_id=source.id, role=AgentRole.QA, attempt=2, source_revision=revision)
    )
    # This registered Task's second attempt also belongs to its complete history.
    refs.append(other)
    unrelated_manager = GitWorktreeManager(
        source.repository, Path(service.team.manifest.platform_root) / "unrelated"
    )
    unrelated = unrelated_manager.create(
        WorktreeSpec(
            task_id="task_unrelated", role=AgentRole.REVIEWER, attempt=1, source_revision=revision
        )
    )
    original = GitWorktreeManager.archive_and_remove
    once = failure

    def release(
        self: GitWorktreeManager, ref: WorktreeRef, *, archive_root: Path, owner_sha256: str
    ) -> WorktreeReleaseArchive:
        nonlocal once
        if once:
            once = False
            raise OSError("injected archive failure")
        return original(self, ref, archive_root=archive_root, owner_sha256=owner_sha256)

    monkeypatch.setattr(GitWorktreeManager, "archive_and_remove", release)
    if failure:
        with pytest.raises(RequirementDeletionRejected, match="资源尚未完全释放"):
            _close(service, checkpoint)
        assert service.journal.current(checkpoint.delivery_id) == checkpoint
        assert repository.get(source.id).status is TaskStatus.BLOCKED
        assert all(ref.path.exists() for ref in refs)
    closed = _close(service, checkpoint)
    assert closed.stage is JointStage.CLOSED
    assert all(not ref.path.exists() for ref in (*refs, baseline))
    assert unrelated.path.exists()
    archives = service.project.requirements_root / checkpoint.delivery_id / "resource-archives"
    before = {str(p.relative_to(archives)): p.read_bytes() for p in archives.glob("*/*")}
    assert len(tuple(archives.glob("*/released.json"))) == 5
    _delete(service, closed)
    assert {str(p.relative_to(archives)): p.read_bytes() for p in archives.glob("*/*")} == before
    assert service.retirements.entry(checkpoint.delivery_id) is not None
    assert unrelated.path.exists()


def test_public_close_replays_removed_resource_missing_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.git import release

    service, checkpoint, repository, _queue, _ = _waiting(tmp_path, monkeypatch)
    source = next(iter(repository.tasks.values()))
    revision = _initialize(Path(source.repository))
    manager = GitWorktreeManager(
        source.repository,
        Path(service.team.manifest.platform_root)
        / "worktrees"
        / checkpoint.children[0].checkpoint.repository_id,
        branch_names={source.id: source.branch_name},
    )
    ref = manager.create(
        WorktreeSpec(task_id=source.id, role=AgentRole.CODER, attempt=1, source_revision=revision)
    )
    (ref.path / "code.txt").write_text("saved draft")
    original = release._publish
    once = True

    def publish(path: Path, body: bytes) -> None:
        nonlocal once
        if path.name == "released.json" and once:
            once = False
            raise OSError("crash after Git remove")
        original(path, body)

    monkeypatch.setattr(release, "_publish", publish)
    with pytest.raises(RequirementDeletionRejected, match="资源尚未完全释放"):
        _close(service, checkpoint)
    assert not ref.path.exists()
    assert service.journal.current(checkpoint.delivery_id) == checkpoint
    folder = (
        service.project.requirements_root
        / checkpoint.delivery_id
        / "resource-archives"
        / hashlib.sha256(str(ref.path).encode()).hexdigest()
    )
    assert not (folder / "released.json").exists()
    closed = _close(service, checkpoint)
    assert closed.stage is JointStage.CLOSED
    assert (folder / "released.json").read_bytes() == (folder / "archive.json").read_bytes()
    _delete(service, closed)


def test_close_then_tampered_saved_archive_refuses_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, checkpoint, repository, _queue, _ = _waiting(tmp_path, monkeypatch)
    source = next(iter(repository.tasks.values()))
    revision = _initialize(Path(source.repository))
    manager = GitWorktreeManager(
        source.repository,
        Path(service.team.manifest.platform_root)
        / "worktrees"
        / checkpoint.children[0].checkpoint.repository_id,
        branch_names={source.id: source.branch_name},
    )
    ref = manager.create(
        WorktreeSpec(task_id=source.id, role=AgentRole.CODER, attempt=1, source_revision=revision)
    )
    closed = _close(service, checkpoint)
    assert not ref.path.exists()
    folder = (
        service.project.requirements_root
        / checkpoint.delivery_id
        / "resource-archives"
        / hashlib.sha256(str(ref.path).encode()).hexdigest()
    )
    (folder / "worktree.tar.gz").write_bytes(b"tampered")
    with pytest.raises(RequirementDeletionRejected, match="资源尚未完全释放"):
        _delete(service, closed)
    assert service.retirements.entry(closed.delivery_id) is None
