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
from ai_software_engineer.multi_directory.service import JointDeliveryService
from tests.git.test_resource_release import git
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_requirement_cancellation import _Repository
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


def _persist_physical_delete_facts(
    service: JointDeliveryService, repository: _Repository, dsn: str, tmp_path: Path
) -> None:
    from ai_software_engineer.manager.mysql_dispatch_authority import MySqlDispatchAuthority
    from ai_software_engineer.multi_directory.deletion import ProductionRequirementDeletionGuard
    from ai_software_engineer.store.mysql_repository import MySqlTaskRepository
    from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
    from tests.manager.test_dispatch_authority import _durable_facts

    facts = tmp_path / "delete-sql-facts"
    facts.mkdir()
    _, _, _, plans, revisions = _durable_facts(facts)
    MySqlDispatchAuthority(dsn, request_revisions=revisions, planner_records=plans)
    MySqlRoleQueue(dsn)
    with MySqlTaskRepository(dsn) as store:
        for task in repository.tasks.values():
            store.create(task)
    assert isinstance(service.deletion_guard, ProductionRequirementDeletionGuard)
    service.deletion_guard._dsn = dsn


@pytest.mark.mysql
@pytest.mark.parametrize("failure", [False, True])
def test_public_close_preserves_drafts_releases_all_roles_and_baseline_then_delete(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch, failure: bool
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
    assert len(tuple(archives.glob("*/released.json"))) == 5
    _persist_physical_delete_facts(service, repository, mysql_dsn, tmp_path)
    _delete(service, closed)
    assert not archives.exists()
    assert (
        git(Path(source.repository), "for-each-ref", "--format=%(refname)", "refs/ase/retained")
        == ""
    )
    assert (
        git(
            Path(source.repository),
            "for-each-ref",
            "--format=%(refname)",
            "refs/heads/ai/" + source.id,
        )
        == ""
    )
    assert service.retirements.entry(checkpoint.delivery_id) is not None
    assert unrelated.path.exists()


@pytest.mark.mysql
def test_public_close_replays_removed_resource_missing_completion(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch
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
    _persist_physical_delete_facts(service, repository, mysql_dsn, tmp_path)
    _delete(service, closed)
    assert not folder.exists()


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


@pytest.mark.mysql
def test_clean_semantic_coder_removal_without_archive_is_physically_deleted(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.domain import Task

    service, checkpoint, repository, queue, _ = _waiting(tmp_path, monkeypatch)
    source = next(iter(repository.tasks.values()))
    revision = _initialize(Path(source.repository))
    source = Task.model_validate(
        {**source.to_wire(), "base_ref": revision, "branch_name": "ai/feature/exact-clean-removal"}
    )
    from tests.manager.test_waiting_requirement_close import _implementing, _waiting_item

    source, events = _implementing(source)
    repository.tasks[source.id] = source
    repository.events[source.id] = events

    item = _waiting_item(source, checkpoint.children[0].checkpoint.repository_id)
    queue.items[item.id] = item
    root = (
        Path(service.team.manifest.platform_root)
        / "worktrees"
        / checkpoint.children[0].checkpoint.repository_id
    )
    manager = GitWorktreeManager(
        source.repository, root, branch_names={source.id: source.branch_name}
    )
    spec = WorktreeSpec(
        task_id=source.id, role=AgentRole.CODER, attempt=1, source_revision=revision
    )
    ref = manager.create(spec)
    manager.remove(ref)
    assert ref.branch is not None and source.branch_name is not None
    marker = manager._removal_marker(spec, ref.branch)
    assert marker.exists() and not ref.path.exists()
    restored = manager.restore_clean_coder(spec)
    (restored.path / "code.txt").write_text("candidate revision\n")
    git(restored.path, "add", "code.txt")
    git(restored.path, "commit", "-m", "fixture candidate")
    candidate = git(restored.path, "rev-parse", "HEAD")
    manager.remove(restored)
    second_marker = manager._removal_marker(
        WorktreeSpec(task_id=source.id, role=AgentRole.CODER, attempt=1, source_revision=candidate),
        ref.branch,
    )
    assert second_marker.exists() and second_marker != marker
    closed = _close(service, checkpoint)
    _persist_physical_delete_facts(service, repository, mysql_dsn, tmp_path)
    _delete(service, closed)
    assert not marker.exists() and not second_marker.exists()
    assert not (root / source.id).exists()
    assert (
        git(
            Path(source.repository),
            "for-each-ref",
            "--format=%(objectname)",
            "refs/heads/" + source.branch_name,
        )
        == ""
    )
    assert git(Path(source.repository), "rev-parse", "HEAD") == revision


@pytest.mark.parametrize("state", ["locked", "unreleased", "cleaned"])
def test_public_close_holds_native_executor_fence_and_requires_typed_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    import fcntl
    import os
    from collections.abc import Iterator
    from contextlib import contextmanager
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from typing import cast

    from ai_software_engineer.manager.native_verification_store import NativeRoleVerificationStore
    from ai_software_engineer.recovery.store import RecoveryRecordMissing

    service, checkpoint, _repository, _queue, _ = _waiting(tmp_path, monkeypatch)
    lock = tmp_path / "native-execution.lock"
    owner = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    if state == "locked":
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
    observed: list[datetime] = []

    class Journal:
        @contextmanager
        def execution_lock(self) -> Iterator[None]:
            descriptor = os.open(lock, os.O_RDWR)
            try:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise ValueError("real executor owns the lock") from error
                yield
            finally:
                os.close(descriptor)

        def list_mysql_resource_intents(self) -> tuple[object, ...]:
            return (SimpleNamespace(intent=SimpleNamespace(resource_id="fixture-owned-resource")),)

        def get_mysql_resource(self, resource_id: str, record_state: str) -> object:
            assert resource_id == "fixture-owned-resource" and record_state == "CLEANED"
            if state != "cleaned":
                raise RecoveryRecordMissing("resource has no exact CLEANED receipt")
            return object()

    journal = cast(NativeRoleVerificationStore, Journal())
    monkeypatch.setattr(
        "ai_software_engineer.multi_directory.purge_resources.native_stores",
        lambda *args, **kwargs: (journal,),
    )

    def reconcile(records: object, *, clock: object) -> None:
        from collections.abc import Callable

        assert records is journal
        observed.append(cast(Callable[[], datetime], clock)())

    monkeypatch.setattr(
        "ai_software_engineer.manager.python_mysql_execution.reconcile_python_mysql_resources",
        reconcile,
    )
    try:
        if state == "cleaned":
            assert _close(service, checkpoint).stage is JointStage.CLOSED
            assert observed and abs((datetime.now(UTC) - observed[0]).total_seconds()) < 10
        else:
            with pytest.raises(RequirementDeletionRejected):
                _close(service, checkpoint)
            assert service.journal.current(checkpoint.delivery_id) == checkpoint
            assert (observed == []) is (state == "locked")
    finally:
        os.close(owner)


@pytest.mark.mysql
def test_task_requested_branch_collision_preserves_preexisting_foreign_ref(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.domain import Task
    from tests.manager.test_waiting_requirement_close import _waiting_item

    service, checkpoint, repository, queue, _ = _waiting(tmp_path, monkeypatch)
    source = next(iter(repository.tasks.values()))
    revision = _initialize(Path(source.repository))
    branch = "ai/feature/preexisting-foreign"
    git(Path(source.repository), "branch", branch, revision)
    task = Task.model_validate({**source.to_wire(), "branch_name": branch})
    repository.tasks[task.id] = task
    item = _waiting_item(task, checkpoint.children[0].checkpoint.repository_id)
    queue.items[item.id] = item
    closed = _close(service, checkpoint)
    _persist_physical_delete_facts(service, repository, mysql_dsn, tmp_path)
    _delete(service, closed)
    assert git(Path(source.repository), "rev-parse", "refs/heads/" + branch) == revision
    assert not service.journal.directory(checkpoint.delivery_id).exists()


@pytest.mark.mysql
def test_legacy_default_branch_without_removal_proof_refuses_complete_deletion(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, checkpoint, repository, _queue, _ = _waiting(tmp_path, monkeypatch)
    source = next(iter(repository.tasks.values()))
    revision = _initialize(Path(source.repository))
    root = (
        Path(service.team.manifest.platform_root)
        / "worktrees"
        / checkpoint.children[0].checkpoint.repository_id
    )
    manager = GitWorktreeManager(source.repository, root)
    spec = WorktreeSpec(
        task_id=source.id, role=AgentRole.CODER, attempt=1, source_revision=revision
    )
    ref = manager.create(spec)
    manager.remove(ref)
    closed = _close(service, checkpoint)
    _persist_physical_delete_facts(service, repository, mysql_dsn, tmp_path)
    with pytest.raises(ValueError, match="legacy Task branch"):
        _delete(service, closed)
    assert ref.branch is not None
    assert git(Path(source.repository), "rev-parse", "refs/heads/" + ref.branch) == revision
    assert service.journal.current(checkpoint.delivery_id) == closed
