"""Repository-only recovery seeding, with real Git and no live platform writes."""

from dataclasses import replace
from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentPermissions, AgentRole
from ai_software_engineer.git import GitWorktreeManager, WorktreeRef, WorktreeSpec
from ai_software_engineer.git.worktree import WorktreeSeedRejected
from tests.git.test_capture import git
from tests.git.test_capture import workspace as workspace


def index_bytes(ref: WorktreeRef) -> bytes:
    return Path(
        git(ref.path, "rev-parse", "--path-format=absolute", "--git-path", "index")
    ).read_bytes()


def prepare(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
    tmp_path: Path,
    *,
    conflict: bool = False,
) -> tuple[GitWorktreeManager, WorktreeRef, WorktreeRef, AgentPermissions]:
    manager, _, permissions = workspace
    repo = tmp_path / "repo"
    base = "VALUE = 1\n" + "\n".join(f"LINE_{i} = {i}" for i in range(20)) + "\nFOOTER = 1\n"
    (repo / "src/app.py").write_text(base)
    git(repo, "add", "src/app.py")
    git(repo, "commit", "-m", "multiline base")
    source = manager.create(
        WorktreeSpec(
            task_id="task_seed_source",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=git(repo, "rev-parse", "HEAD"),
        )
    )
    (source.path / "src/app.py").write_text(base.replace("VALUE = 1", "VALUE = 2"))
    git(source.path, "add", "src/app.py")
    (repo / "src/app.py").write_text(
        base.replace("VALUE = 1", "VALUE = 3")
        if conflict
        else base.replace("FOOTER = 1", "FOOTER = 2")
    )
    git(repo, "add", "src/app.py")
    git(repo, "commit", "-m", "platform fix")
    target = manager.create(
        WorktreeSpec(
            task_id="task_seed_target",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=git(repo, "rev-parse", "HEAD"),
        )
    )
    return manager, source, target, permissions


def test_seed_preserves_new_base_and_original_source(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions], tmp_path: Path
) -> None:
    manager, source, target, permissions = prepare(workspace, tmp_path)
    capture = manager.capture_changes(source, permissions)
    before = index_bytes(source), (source.path / "src/app.py").read_bytes()
    seeded = manager.seed_changes(capture, target, permissions, permissions)
    content = (target.path / "src/app.py").read_text()
    assert "VALUE = 2\n" in content and "FOOTER = 2\n" in content
    assert seeded.worktree == target
    assert seeded.changed_paths == ("src/app.py",)
    manager.verify_capture(seeded, permissions)
    manager.verify_capture(capture, permissions)
    assert (index_bytes(source), (source.path / "src/app.py").read_bytes()) == before
    assert git(target.path, "rev-parse", "HEAD") == target.head_revision
    assert git(source.path, "rev-parse", "HEAD") == source.head_revision
    assert git(tmp_path / "repo", "status", "--porcelain") == ""
    with pytest.raises(WorktreeSeedRejected):
        manager.seed_changes(capture, target, permissions, permissions)
    manager.verify_capture(seeded, permissions)


def test_conflict_preflight_leaves_target_unchanged(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions], tmp_path: Path
) -> None:
    manager, source, target, permissions = prepare(workspace, tmp_path, conflict=True)
    capture = manager.capture_changes(source, permissions)
    before = index_bytes(target), (target.path / "src/app.py").read_bytes()
    with pytest.raises(WorktreeSeedRejected):
        manager.seed_changes(capture, target, permissions, permissions)
    assert (index_bytes(target), (target.path / "src/app.py").read_bytes()) == before
    assert manager.inspect(target).changed_paths == ()
    manager.verify_capture(capture, permissions)


@pytest.mark.parametrize(
    "failure", ["source", "dirty", "role", "same_task", "path", "deny", "write", "driver"]
)
def test_seed_failures_never_write_destination(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
    tmp_path: Path,
    failure: str,
) -> None:
    manager, source, target, permissions = prepare(workspace, tmp_path)
    capture = manager.capture_changes(source, permissions)
    submitted = target
    target_permissions = permissions
    denies: tuple[str, ...] = ()
    if failure == "source":
        (source.path / "src/app.py").write_text("different source\n")
    elif failure == "dirty":
        (target.path / "src/app.py").write_text("unrelated work\n")
    elif failure == "role":
        submitted = replace(target, role=AgentRole.QA)
    elif failure == "same_task":
        submitted = source
    elif failure == "path":
        submitted = replace(target, path=tmp_path / "repo")
    elif failure == "deny":
        denies = ("src/**",)
    elif failure == "write":
        target_permissions = permissions.model_copy(update={"write_paths": ()})
    else:
        git(tmp_path / "repo", "config", "merge.unsafe.driver", "touch should-never-exist")
    before = index_bytes(target), (target.path / "src/app.py").read_bytes()
    with pytest.raises(WorktreeSeedRejected):
        manager.seed_changes(
            capture, submitted, permissions, target_permissions, target_denied_paths=denies
        )
    assert (index_bytes(target), (target.path / "src/app.py").read_bytes()) == before
    assert not (target.path / "should-never-exist").exists()


@pytest.mark.parametrize("changed", [False, True])
def test_same_base_and_empty_seed(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions], changed: bool
) -> None:
    manager, source, permissions = workspace
    if changed:
        (source.path / "src/app.py").write_text("VALUE = 2\n")
    capture = manager.capture_changes(source, permissions)
    target = manager.create(
        WorktreeSpec(
            task_id="task_same_base",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=source.head_revision,
        )
    )
    seeded = manager.seed_changes(capture, target, permissions, permissions)
    assert seeded.file_sha256s == capture.file_sha256s
    assert (target.path / "src/app.py").read_bytes() == (source.path / "src/app.py").read_bytes()
    manager.verify_capture(capture, permissions)


def test_merge_attribute_rejected_without_writes(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions], tmp_path: Path
) -> None:
    manager, source, target, permissions = prepare(workspace, tmp_path)
    capture = manager.capture_changes(source, permissions)
    attributes = tmp_path / "repo/.git/info/attributes"
    attributes.write_text("src/app.py merge=union\n")
    before = index_bytes(target), (target.path / "src/app.py").read_bytes()
    with pytest.raises(WorktreeSeedRejected):
        manager.seed_changes(capture, target, permissions, permissions)
    assert (index_bytes(target), (target.path / "src/app.py").read_bytes()) == before


def test_seed_cannot_modify_its_own_attributes(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions], tmp_path: Path
) -> None:
    manager, _, permissions = workspace
    repo = tmp_path / "repo"
    (repo / "src/.gitattributes").write_text("*.py text\n")
    git(repo, "add", "src/.gitattributes")
    git(repo, "commit", "-m", "attributes baseline")
    base = git(repo, "rev-parse", "HEAD")
    source, target = (
        manager.create(
            WorktreeSpec(task_id=name, role=AgentRole.CODER, attempt=1, source_revision=base)
        )
        for name in ("task_attr_source", "task_attr_target")
    )
    (source.path / "src/.gitattributes").write_text("*.py merge=union\n")
    capture = manager.capture_changes(source, permissions)
    before = index_bytes(target), (target.path / "src/.gitattributes").read_bytes()
    with pytest.raises(WorktreeSeedRejected):
        manager.seed_changes(capture, target, permissions, permissions)
    assert (index_bytes(target), (target.path / "src/.gitattributes").read_bytes()) == before


def test_older_target_base_is_rejected(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions], tmp_path: Path
) -> None:
    manager, initial, permissions = workspace
    _, source, _, _ = prepare(workspace, tmp_path)
    target = manager.create(
        WorktreeSpec(
            task_id="task_older_target",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=initial.head_revision,
        )
    )
    capture = manager.capture_changes(source, permissions)
    before = index_bytes(target), (target.path / "src/app.py").read_bytes()
    with pytest.raises(WorktreeSeedRejected):
        manager.seed_changes(capture, target, permissions, permissions)
    assert (index_bytes(target), (target.path / "src/app.py").read_bytes()) == before


def test_already_in_new_base_produces_empty_capture(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions], tmp_path: Path
) -> None:
    manager, source, permissions = workspace
    (source.path / "src/app.py").write_text("VALUE = 2\n")
    capture = manager.capture_changes(source, permissions)
    repo = tmp_path / "repo"
    (repo / "src/app.py").write_text("VALUE = 2\n")
    git(repo, "add", "src/app.py")
    git(repo, "commit", "-m", "already integrated independently")
    target = manager.create(
        WorktreeSpec(
            task_id="task_already_applied",
            role=AgentRole.CODER,
            attempt=1,
            source_revision=git(repo, "rev-parse", "HEAD"),
        )
    )
    result = manager.seed_changes(capture, target, permissions, permissions)
    assert not result.patch
    manager.verify_capture(capture, permissions)


@pytest.mark.parametrize("phase", ["preflight", "applied"])
def test_interruption_preserves_original_and_target_evidence(
    workspace: tuple[GitWorktreeManager, WorktreeRef, AgentPermissions],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    from ai_software_engineer.git.worktree import GitCommandError

    manager, source, target, permissions = prepare(workspace, tmp_path)
    capture = manager.capture_changes(source, permissions)
    before = index_bytes(target), (target.path / "src/app.py").read_bytes()
    original = manager._run_git_bytes

    def interrupted(
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        input: bytes | None = None,
        index_file: Path | None = None,
    ) -> bytes:
        result = original(arguments, cwd=cwd, input=input, index_file=index_file)
        if "apply" in arguments and ((index_file is not None) == (phase == "preflight")):
            raise GitCommandError("injected process loss")
        return result

    monkeypatch.setattr(manager, "_run_git_bytes", interrupted)
    with pytest.raises(WorktreeSeedRejected):
        manager.seed_changes(capture, target, permissions, permissions)
    manager.verify_capture(capture, permissions)
    if phase == "preflight":
        assert (index_bytes(target), (target.path / "src/app.py").read_bytes()) == before
    else:
        assert "VALUE = 2\n" in (target.path / "src/app.py").read_text()
        assert manager.capture_changes(target, permissions).changed_paths == ("src/app.py",)
    assert git(target.path, "rev-parse", "HEAD") == target.head_revision
