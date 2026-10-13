"""Real Git preservation and cleanup cannot lose drafts or remove a different resource."""

from __future__ import annotations

import hashlib
import subprocess
import tarfile
from pathlib import Path

import pytest

from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.git.ports import WorktreeSpec
from ai_software_engineer.git.release import WorktreeReleaseRejected
from ai_software_engineer.git.worktree import GitWorktreeManager


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-c", "core.hooksPath=/dev/null", *args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def worktree(tmp_path: Path) -> tuple[GitWorktreeManager, WorktreeSpec]:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    (root / "code.txt").write_text("base\n")
    (root / ".gitignore").write_text("cache/\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "fixture")
    manager = GitWorktreeManager(root, tmp_path / "worktrees")
    spec = WorktreeSpec(
        task_id="task_resource",
        role=AgentRole.CODER,
        attempt=1,
        source_revision=git(root, "rev-parse", "HEAD"),
    )
    return manager, spec


def test_release_saves_staged_untracked_ignored_and_symlink_without_losing_branch(
    tmp_path: Path,
) -> None:
    manager, spec = worktree(tmp_path)
    ref = manager.create(spec)
    (ref.path / "code.txt").write_text("staged draft\n")
    git(ref.path, "add", "code.txt")
    staged_oid = git(ref.path, "rev-parse", ":code.txt")
    (ref.path / "code.txt").write_text("unstaged draft\n")
    (ref.path / "new.txt").write_text("untracked\n")
    (ref.path / "cache").mkdir()
    (ref.path / "cache/output").write_bytes(b"\xff\x00")
    (ref.path / "link").symlink_to("new.txt")
    manifest = manager.archive_and_remove(
        ref, archive_root=tmp_path / "archives", owner_sha256="a" * 64
    )
    assert not ref.path.exists()
    assert git(manager._repository, "rev-parse", ref.branch or "") == spec.source_revision
    folder = tmp_path / "archives" / hashlib.sha256(str(ref.path).encode()).hexdigest()
    with tarfile.open(folder / "worktree.tar.gz") as archive:
        for name, body in (
            ("code.txt", b"unstaged draft\n"),
            ("new.txt", b"untracked\n"),
            ("cache/output", b"\xff\x00"),
        ):
            stream = archive.extractfile(name)
            assert stream is not None and stream.read() == body
        assert archive.getmember("link").issym()
        assert archive.getmember("saved-git-index").size > 0
        staged = archive.extractfile("saved-index-objects/" + staged_oid)
        assert staged is not None and staged.read() == b"staged draft\n"
    git(manager._repository, "reflog", "expire", "--expire=now", "--all")
    git(manager._repository, "gc", "--prune=now")
    # Rehydrate the exact staged blob from the saved bytes after Git drops it.
    with tarfile.open(folder / "worktree.tar.gz") as archive:
        staged = archive.extractfile("saved-index-objects/" + staged_oid)
        assert staged is not None
        restored = (
            subprocess.run(
                ("git", "hash-object", "-w", "--stdin"),
                cwd=manager._repository,
                input=staged.read(),
                check=True,
                capture_output=True,
            )
            .stdout.decode()
            .strip()
        )
        assert restored == staged_oid
    saved = (folder / "archive.json").read_bytes()
    assert (
        manager.archive_and_remove(ref, archive_root=tmp_path / "archives", owner_sha256="a" * 64)
        == manifest
    )
    assert (folder / "archive.json").read_bytes() == saved
    assert (manager._repository / "code.txt").read_text() == "base\n"


def test_tampered_archive_or_scope_replay_cannot_delete_resource(tmp_path: Path) -> None:
    manager, spec = worktree(tmp_path)
    ref = manager.create(spec)
    manager.archive_and_remove(ref, archive_root=tmp_path / "archives", owner_sha256="a" * 64)
    with pytest.raises(WorktreeReleaseRejected):
        manager.archive_and_remove(ref, archive_root=tmp_path / "archives", owner_sha256="b" * 64)
    folder = tmp_path / "archives" / hashlib.sha256(str(ref.path).encode()).hexdigest()
    (folder / "worktree.tar.gz").write_bytes(b"invalid archive")
    with pytest.raises(WorktreeReleaseRejected):
        manager.archive_and_remove(ref, archive_root=tmp_path / "archives", owner_sha256="a" * 64)


def test_archive_failure_keeps_dirty_worktree_and_branch(tmp_path: Path) -> None:
    manager, spec = worktree(tmp_path)
    ref = manager.create(spec)
    (ref.path / "code.txt").write_text("draft\n")
    (ref.path / "nested").mkdir()
    (ref.path / "nested/.git").write_text("nested git evidence")
    with pytest.raises(WorktreeReleaseRejected):
        manager.archive_and_remove(ref, archive_root=tmp_path / "archives", owner_sha256="a" * 64)
    assert (ref.path / "code.txt").read_text() == "draft\n"
    assert ref.path.exists()


def test_saved_draft_cleanup_replays_after_clean_reset_before_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, spec = worktree(tmp_path)
    ref = manager.create(spec)
    (ref.path / "code.txt").write_text("draft\n")
    (ref.path / "cache").mkdir()
    (ref.path / "cache/output").write_text("saved ignored\n")
    remove = manager.remove
    monkeypatch.setattr(
        manager, "remove", lambda ref: (_ for _ in ()).throw(OSError("interrupted"))
    )
    with pytest.raises(OSError):
        manager.archive_and_remove(ref, archive_root=tmp_path / "archives", owner_sha256="a" * 64)
    assert ref.path.exists() and not manager.inspect(ref).dirty
    monkeypatch.setattr(manager, "remove", remove)
    manager.archive_and_remove(ref, archive_root=tmp_path / "archives", owner_sha256="a" * 64)
    assert not ref.path.exists()


def test_index_only_drift_after_intent_never_discards_new_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, spec = worktree(tmp_path)
    ref = manager.create(spec)
    (ref.path / "code.txt").write_text("draft\n")
    original = manager._run_git

    def fail_reset(args: tuple[str, ...], *, cwd: Path) -> str:
        if args[:2] == ("reset", "--hard"):
            raise OSError("interrupted before reset")
        return original(args, cwd=cwd)

    monkeypatch.setattr(manager, "_run_git", fail_reset)
    with pytest.raises(OSError):
        manager.archive_and_remove(ref, archive_root=tmp_path / "archives", owner_sha256="a" * 64)
    git(ref.path, "add", "code.txt")
    monkeypatch.setattr(manager, "_run_git", original)
    with pytest.raises(WorktreeReleaseRejected):
        manager.archive_and_remove(ref, archive_root=tmp_path / "archives", owner_sha256="a" * 64)
    assert ref.path.exists()
    assert git(ref.path, "show", ":code.txt") == "draft"


def test_unsealed_archive_failure_safely_retries_from_unchanged_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.git import release

    manager, spec = worktree(tmp_path)
    ref = manager.create(spec)
    (ref.path / "code.txt").write_text("draft\n")
    publish = release._publish

    def fail_manifest(path: Path, body: bytes) -> None:
        if path.name == "archive.json":
            raise OSError("interrupted after archive link")
        publish(path, body)

    monkeypatch.setattr(release, "_publish", fail_manifest)
    with pytest.raises(OSError):
        manager.archive_and_remove(ref, archive_root=tmp_path / "archives", owner_sha256="a" * 64)
    assert (ref.path / "code.txt").read_text() == "draft\n"
    monkeypatch.setattr(release, "_publish", publish)
    manager.archive_and_remove(ref, archive_root=tmp_path / "archives", owner_sha256="a" * 64)
    assert not ref.path.exists()
    assert tuple((tmp_path / "archives").glob("*/unsealed-*.tar.gz"))


def test_split_index_refuses_cleanup_and_preserves_shared_index(tmp_path: Path) -> None:
    manager, spec = worktree(tmp_path)
    ref = manager.create(spec)
    (ref.path / "code.txt").write_text("staged draft\n")
    git(ref.path, "add", "code.txt")
    git(ref.path, "update-index", "--split-index")
    shared = git(ref.path, "rev-parse", "--shared-index-path")
    assert shared
    with pytest.raises(WorktreeReleaseRejected, match="split-index"):
        manager.archive_and_remove(ref, archive_root=tmp_path / "archives", owner_sha256="a" * 64)
    assert ref.path.exists()
    assert git(ref.path, "show", ":code.txt") == "staged draft"


def test_staged_only_reset_image_replays_after_remove_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, spec = worktree(tmp_path)
    ref = manager.create(spec)
    (ref.path / "code.txt").write_text("staged only\n")
    git(ref.path, "add", "code.txt")
    (ref.path / "code.txt").write_text("base\n")
    remove = manager.remove
    monkeypatch.setattr(
        manager, "remove", lambda ref: (_ for _ in ()).throw(OSError("interrupted"))
    )
    with pytest.raises(OSError):
        manager.archive_and_remove(ref, archive_root=tmp_path / "archives", owner_sha256="a" * 64)
    monkeypatch.setattr(manager, "remove", remove)
    manager.archive_and_remove(ref, archive_root=tmp_path / "archives", owner_sha256="a" * 64)
    assert not ref.path.exists()


@pytest.mark.parametrize("hidden", [False, True])
def test_reset_replay_never_discards_new_tracked_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hidden: bool
) -> None:
    manager, spec = worktree(tmp_path)
    ref = manager.create(spec)
    (ref.path / "code.txt").write_text("saved draft\n")
    remove = manager.remove
    monkeypatch.setattr(
        manager, "remove", lambda ref: (_ for _ in ()).throw(OSError("interrupted"))
    )
    with pytest.raises(OSError):
        manager.archive_and_remove(ref, archive_root=tmp_path / "archives", owner_sha256="a" * 64)
    if hidden:
        git(ref.path, "update-index", "--assume-unchanged", "code.txt")
    (ref.path / "code.txt").write_text("new unsealed draft\n")
    monkeypatch.setattr(manager, "remove", remove)
    with pytest.raises(WorktreeReleaseRejected):
        manager.archive_and_remove(ref, archive_root=tmp_path / "archives", owner_sha256="a" * 64)
    assert (ref.path / "code.txt").read_text() == "new unsealed draft\n"


def test_detached_commit_remains_reachable_after_release_and_gc(tmp_path: Path) -> None:
    manager, source = worktree(tmp_path)
    ref = manager.create(source.model_copy(update={"role": AgentRole.REVIEWER}))
    (ref.path / "code.txt").write_text("candidate\n")
    git(ref.path, "add", "code.txt")
    git(ref.path, "commit", "-m", "detached candidate")
    candidate = git(ref.path, "rev-parse", "HEAD")
    ref = manager.recover(
        source.model_copy(update={"role": AgentRole.REVIEWER, "source_revision": candidate})
    )
    manifest = manager.archive_and_remove(
        ref, archive_root=tmp_path / "archives", owner_sha256="a" * 64
    )
    git(manager._repository, "reflog", "expire", "--expire=now", "--all")
    git(manager._repository, "gc", "--prune=now")
    assert git(manager._repository, "rev-parse", manifest.retained_ref) == candidate
    assert git(manager._repository, "show", candidate + ":code.txt") == "candidate"


def test_oversized_release_record_refuses_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.git import release

    monkeypatch.setattr(release, "_MAX_RECORD_BYTES", 4)
    with pytest.raises(WorktreeReleaseRejected, match="大小限制"):
        release._publish(tmp_path / "archive.json", b"oversized")
    assert not (tmp_path / "archive.json").exists()


def test_release_schema_matches_model_and_validates_real_archive(tmp_path: Path) -> None:
    import json

    from jsonschema import Draft202012Validator

    from ai_software_engineer.git.release import WorktreeReleaseArchive

    schema = json.loads(Path("schemas/worktree-release-archive.schema.json").read_text())
    model_schema = {k: v for k, v in schema.items() if k not in {"$id", "$schema"}}
    assert model_schema == WorktreeReleaseArchive.model_json_schema()
    manager, spec = worktree(tmp_path)
    result = manager.archive_and_remove(
        manager.create(spec), archive_root=tmp_path / "archives", owner_sha256="a" * 64
    )
    Draft202012Validator(schema).validate(result.model_dump(mode="json"))
