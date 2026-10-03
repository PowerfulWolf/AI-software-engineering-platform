"""Semantic names are frozen intent, never inferred ownership or retry IDs."""

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.domain import AgentPermissions, AgentRole, NetworkAccess
from ai_software_engineer.domain.branch import BranchName, successor_branch
from ai_software_engineer.git import (
    GitWorktreeManager,
    UnmanagedWorktree,
    WorktreeAlreadyExists,
    WorktreeIdentityDrift,
    WorktreeSpec,
)
from ai_software_engineer.recovery.models import CapturedChanges
from tests.git.test_worktree import _create_fixture_repository, _git


@pytest.mark.parametrize("kind", ["feature", "bugfix"])
def test_semantic_branch_capture_restart_and_collision(tmp_path: Path, kind: str) -> None:
    repo = _create_fixture_repository(tmp_path)
    name = f"ai/{kind}/project-switch"
    names = {"task_semantic_one": name}
    manager = GitWorktreeManager(repo, tmp_path / "roles", branch_names=names)
    spec = WorktreeSpec(
        task_id="task_semantic_one",
        role=AgentRole.CODER,
        attempt=1,
        source_revision=_git(repo, "rev-parse", "HEAD"),
    )
    ref = manager.create(spec)
    assert ref.branch == name
    with pytest.raises(UnmanagedWorktree, match="no trusted branch binding"):
        manager.create(spec.model_copy(update={"task_id": "task_unbound"}))
    names["task_semantic_one"] = "ai/bugfix/forged"  # manager copies trusted intent
    permissions = AgentPermissions(
        read_paths=("src/**",), write_paths=("src/**",), commands=(), network=NetworkAccess.NONE
    )
    (ref.path / "src/app.py").write_text("VALUE = 2\n")
    capture = manager.capture_changes(ref, permissions)
    saved = CapturedChanges.from_capture(capture)
    assert saved.branch_name == name
    assert CapturedChanges.model_validate(saved.to_wire()).to_capture() == capture
    restarted = GitWorktreeManager(repo, tmp_path / "roles", branch_names={spec.task_id: name})
    assert restarted.recover(spec) == ref
    restarted.verify_capture(saved.to_capture(), permissions)
    with pytest.raises(UnmanagedWorktree):
        restarted.inspect(replace(ref, branch="ai/bugfix/forged"))
    other = GitWorktreeManager(repo, tmp_path / "roles", branch_names={"task_semantic_two": name})
    with pytest.raises(WorktreeAlreadyExists):
        other.create(spec.model_copy(update={"task_id": "task_semantic_two"}))
    assert (ref.path / "src/app.py").read_text() == "VALUE = 2\n"
    assert _git(repo, "status", "--porcelain") == ""
    for role in (AgentRole.QA, AgentRole.REVIEWER):
        verifier = manager.create(spec.model_copy(update={"role": role}))
        assert verifier.detached and verifier.branch is None


def test_clean_semantic_branch_can_be_restored(tmp_path: Path) -> None:
    repo = _create_fixture_repository(tmp_path)
    manager = GitWorktreeManager(
        repo, tmp_path / "roles", branch_names={"task_semantic_one": "ai/feature/history-trends"}
    )
    spec = WorktreeSpec(
        task_id="task_semantic_one",
        role=AgentRole.CODER,
        attempt=1,
        source_revision=_git(repo, "rev-parse", "HEAD"),
    )
    ref = manager.create(spec)
    manager.remove(ref)
    restarted = GitWorktreeManager(
        repo, tmp_path / "roles", branch_names={spec.task_id: ref.branch}
    )
    restored = restarted.restore_clean_coder(spec)
    assert restored == ref
    restarted.remove(restored)
    assert restarted.restore_clean_coder(spec) == ref


@pytest.mark.parametrize("damage", [None, "dirty", "missing-marker", "branch-drift"])
def test_clean_candidate_inspection_is_readonly_and_requires_owned_cleanup(
    tmp_path: Path, damage: str | None
) -> None:
    repo = _create_fixture_repository(tmp_path)
    manager = GitWorktreeManager(
        repo, tmp_path / "roles", branch_names={"task_preflight": "ai/feature/preflight"}
    )
    spec = WorktreeSpec(
        task_id="task_preflight",
        role=AgentRole.CODER,
        attempt=1,
        source_revision=_git(repo, "rev-parse", "HEAD"),
    )
    ref = manager.create(spec)
    if damage == "dirty":
        (ref.path / "src/app.py").write_text("VALUE = 9\n")
        with pytest.raises(WorktreeIdentityDrift):
            manager.require_clean_coder(spec)
        assert (ref.path / "src/app.py").read_text() == "VALUE = 9\n"
        return
    manager.require_clean_coder(spec)
    manager.remove(ref)
    if damage == "missing-marker":
        next(ref.path.parent.glob(".*.removed-*")).unlink()
    elif damage == "branch-drift":
        (repo / "src/app.py").write_text("VALUE = 2\n")
        _git(repo, "add", "src/app.py")
        _git(repo, "commit", "-m", "new base")
        _git(repo, "branch", "-f", ref.branch or "", "HEAD")
    if damage is None:
        manager.require_clean_coder(spec)
    else:
        with pytest.raises(WorktreeIdentityDrift):
            manager.require_clean_coder(spec)
    assert not ref.path.exists()


def test_clean_restoration_cannot_adopt_another_tasks_semantic_branch(tmp_path: Path) -> None:
    repo = _create_fixture_repository(tmp_path)
    name = "ai/feature/history-trends"
    manager = GitWorktreeManager(repo, tmp_path / "roles", branch_names={"task_original": name})
    spec = WorktreeSpec(
        task_id="task_original",
        role=AgentRole.CODER,
        attempt=1,
        source_revision=_git(repo, "rev-parse", "HEAD"),
    )
    ref = manager.create(spec)
    manager.remove(ref)
    other_spec = spec.model_copy(update={"task_id": "task_unrelated"})
    other = GitWorktreeManager(repo, tmp_path / "roles", branch_names={other_spec.task_id: name})
    with pytest.raises(WorktreeAlreadyExists):
        other.create(other_spec)
    with pytest.raises(WorktreeIdentityDrift, match="removal"):
        other.restore_clean_coder(other_spec)
    other_parent = tmp_path / "roles" / other_spec.task_id
    assert not other_parent.exists()
    marker = next(ref.path.parent.glob(".*.removed-*"))
    other_parent.mkdir()
    (other_parent / marker.name).write_bytes(marker.read_bytes())
    with pytest.raises(WorktreeIdentityDrift, match="removal"):
        other.restore_clean_coder(other_spec)
    assert not (other_parent / ref.path.name).exists()
    assert _git(repo, "rev-parse", name) == spec.source_revision
    assert manager.restore_clean_coder(spec) == ref


def test_failed_removal_marker_preserves_the_semantic_worktree(tmp_path: Path) -> None:
    repo = _create_fixture_repository(tmp_path)
    spec = WorktreeSpec(
        task_id="task_removed",
        role=AgentRole.CODER,
        attempt=1,
        source_revision=_git(repo, "rev-parse", "HEAD"),
    )
    manager = GitWorktreeManager(
        repo, tmp_path / "roles", branch_names={spec.task_id: "ai/feature/history-trends"}
    )
    ref = manager.create(spec)
    manager.remove(ref)
    restored = manager.restore_clean_coder(spec)
    marker = next(ref.path.parent.glob(".*.removed-*"))
    marker.write_text("corrupt")
    with pytest.raises(WorktreeIdentityDrift, match="removal"):
        manager.remove(restored)
    assert ref.path.is_dir()
    assert manager.inspect(ref).head_revision == spec.source_revision
    assert manager.restore_clean_coder(spec) == ref


@pytest.mark.parametrize("damage", ["missing", "nonempty", "symlink", "other-root"])
def test_clean_semantic_restoration_requires_its_exact_removal_marker(
    tmp_path: Path, damage: str
) -> None:
    repo = _create_fixture_repository(tmp_path)
    name = "ai/bugfix/project-switch"
    spec = WorktreeSpec(
        task_id="task_removed",
        role=AgentRole.CODER,
        attempt=1,
        source_revision=_git(repo, "rev-parse", "HEAD"),
    )
    manager = GitWorktreeManager(repo, tmp_path / "roles", branch_names={spec.task_id: name})
    ref = manager.create(spec)
    manager.remove(ref)
    marker = next(ref.path.parent.glob(".*.removed-*"))
    if damage == "other-root":
        # Copying the receipt does not grant ownership in another manager's layout.
        other_root = tmp_path / "other-roles"
        other_parent = other_root / spec.task_id
        other_parent.mkdir(parents=True)
        (other_parent / marker.name).write_bytes(marker.read_bytes())
        manager = GitWorktreeManager(repo, other_root, branch_names={spec.task_id: name})
    elif damage == "nonempty":
        marker.write_text("corrupt")
    else:
        marker.unlink()
        if damage == "symlink":
            target = tmp_path / "external"
            target.touch()
            marker.symlink_to(target)
    with pytest.raises(WorktreeIdentityDrift, match="removal"):
        manager.restore_clean_coder(spec)
    assert not ref.path.exists()
    assert _git(repo, "rev-parse", name) == spec.source_revision


@pytest.mark.parametrize(
    "name",
    [
        "ai/task_abc/attempt-1",
        "feature/project-switch",
        "ai/fix/x",
        "ai/feature/../main",
        "ai/feature/UPPER",
        "ai/feature/topic/extra",
        "ai/feature/x.lock",
        "ai/feature/topic-attempt-2",
        "ai/bugfix/123456abcdef123456abcdef123456abcd",
    ],
)
def test_invalid_names_are_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(BranchName).validate_python(name)


@pytest.mark.parametrize("kind", ["feature", "bugfix"])
@pytest.mark.parametrize("slug", ["ui", "api"])
def test_short_business_names_use_the_same_rule_for_both_kinds(kind: str, slug: str) -> None:
    name = f"ai/{kind}/{slug}"
    assert TypeAdapter(BranchName).validate_python(name) == name


def test_successors_keep_original_kind_and_bound_generated_suffixes() -> None:
    assert successor_branch("ai/feature/trends", "review-fixes") == "ai/feature/trends-review-fixes"
    assert successor_branch("ai/bugfix/switch", "recovery") == "ai/bugfix/switch-recovery"
    assert (
        successor_branch("ai/feature/trends-recovery", "recovery") == "ai/feature/trends-recovery"
    )
    assert (
        successor_branch(
            "ai/feature/trends-recovery-recovery-review-fixes-prerequisite-repair",
            "review-fixes",
        )
        == "ai/feature/trends-review-fixes"
    )
    assert successor_branch("ai/feature/recovery", "recovery") == "ai/feature/recovery-recovery"
    assert successor_branch(None, "recovery") is None  # historical unclassified Task


def test_semantic_seed_validates_both_source_and_target_bindings(tmp_path: Path) -> None:
    repo = _create_fixture_repository(tmp_path)
    manager = GitWorktreeManager(
        repo,
        tmp_path / "roles",
        branch_names={
            "task_source": "ai/feature/trends",
            "task_recovery": "ai/feature/trends-recovery",
        },
    )
    base = _git(repo, "rev-parse", "HEAD")
    source = manager.create(
        WorktreeSpec(task_id="task_source", role=AgentRole.CODER, attempt=1, source_revision=base)
    )
    target = manager.create(
        WorktreeSpec(task_id="task_recovery", role=AgentRole.CODER, attempt=1, source_revision=base)
    )
    permissions = AgentPermissions(
        read_paths=("src/**",), write_paths=("src/**",), commands=(), network=NetworkAccess.NONE
    )
    (source.path / "src/app.py").write_text("VALUE = 9\n")
    captured = manager.capture_changes(source, permissions)
    seeded = manager.seed_changes(captured, target, permissions, permissions)
    saved = CapturedChanges.from_capture(seeded)
    assert saved.branch_name == target.branch
    assert saved.to_capture() == seeded
    assert (target.path / "src/app.py").read_text() == "VALUE = 9\n"
    manager.verify_capture(captured, permissions)


def test_candidate_display_uses_only_exact_frozen_semantic_name(tmp_path: Path) -> None:
    from ai_software_engineer.team_view.reader import _candidate_branch

    repo = _create_fixture_repository(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    name = "ai/bugfix/project-switch"
    _git(repo, "branch", name)
    _git(repo, "branch", "ai/feature/unrelated")
    assert _candidate_branch(str(repo), "task_owner", base, branch_name=name) == name
    assert _candidate_branch(str(repo), "task_owner", base, branch_name=name + "-absent") is None
    assert _candidate_branch(str(repo), "task_owner", "f" * 40, branch_name=name) is None
    assert _candidate_branch(str(repo), "task_other", base) is None
