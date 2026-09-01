"""Behavior tests for machine-enforced workspace policy."""

from pathlib import Path, PurePosixPath

import pytest

from ai_software_engineer.domain import AgentPermissions, NetworkAccess
from ai_software_engineer.git import (
    CommandPolicyViolation,
    PathPolicyViolation,
    WorkspacePolicy,
)


def _permissions() -> AgentPermissions:
    return AgentPermissions(
        read_paths=("README.md", "src/**", "tests/**"),
        write_paths=("src/**", "tests/unit/**"),
        commands=("pytest", "ruff", "git diff", "git status"),
        network=NetworkAccess.NONE,
    )


def test_path_policy_enforces_separate_allowlists_and_deny_precedence(
    tmp_path: Path,
) -> None:
    policy = WorkspacePolicy(tmp_path, _permissions(), denied_paths=("src/generated/**",))

    assert policy.authorize_read("README.md") == PurePosixPath("README.md")
    assert policy.authorize_read("tests/integration/test_api.py") == PurePosixPath(
        "tests/integration/test_api.py"
    )
    assert policy.authorize_write("src/package/service.py") == PurePosixPath(
        "src/package/service.py"
    )
    assert policy.authorize_write("tests/unit/test_service.py") == PurePosixPath(
        "tests/unit/test_service.py"
    )

    with pytest.raises(PathPolicyViolation):
        policy.authorize_write("tests/integration/test_api.py")
    with pytest.raises(PathPolicyViolation):
        policy.authorize_write("src/generated/client.py")
    with pytest.raises(PathPolicyViolation):
        policy.authorize_read("docs/architecture.md")


@pytest.mark.parametrize(
    "path",
    (
        "../secrets.env",
        "/etc/passwd",
        ".git/config",
        "src/../../secrets.env",
        "src\\package\\service.py",
        "src//package/service.py",
    ),
)
def test_path_policy_rejects_non_canonical_or_repository_control_paths(
    path: str, tmp_path: Path
) -> None:
    policy = WorkspacePolicy(tmp_path, _permissions())

    with pytest.raises(PathPolicyViolation):
        policy.authorize_read(path)


def test_command_policy_matches_complete_token_prefixes(tmp_path: Path) -> None:
    policy = WorkspacePolicy(tmp_path, _permissions())

    assert policy.authorize_command(("pytest", "tests/unit", "-q")) == (
        "pytest",
        "tests/unit",
        "-q",
    )
    assert policy.authorize_command(("git", "diff", "--check")) == (
        "git",
        "diff",
        "--check",
    )
    assert policy.authorize_command(("git", "status", "--short")) == (
        "git",
        "status",
        "--short",
    )

    with pytest.raises(CommandPolicyViolation):
        policy.authorize_command(("git", "push"))
    with pytest.raises(CommandPolicyViolation):
        policy.authorize_command(("git",))
    with pytest.raises(CommandPolicyViolation):
        policy.authorize_command(())


@pytest.mark.parametrize(
    "arguments",
    (
        ("pytest", ";", "git", "push"),
        ("pytest", "&&", "git", "push"),
        ("pytest", "$(git", "push)"),
        ("pytest", "`git", "push`"),
        ("pytest", "tests/unit\nwhoami"),
    ),
)
def test_command_policy_rejects_shell_like_tokens(
    arguments: tuple[str, ...], tmp_path: Path
) -> None:
    with pytest.raises(CommandPolicyViolation):
        WorkspacePolicy(tmp_path, _permissions()).authorize_command(arguments)


def test_command_policy_rejects_unsafe_allowlist_definition(tmp_path: Path) -> None:
    permissions = _permissions().model_copy(update={"commands": ("pytest && git push",)})

    with pytest.raises(CommandPolicyViolation):
        WorkspacePolicy(tmp_path, permissions)


def test_empty_reviewer_write_allowlist_fails_closed(tmp_path: Path) -> None:
    permissions = _permissions().model_copy(update={"write_paths": ()})

    with pytest.raises(PathPolicyViolation):
        WorkspacePolicy(tmp_path, permissions).authorize_write("README.md")


def test_path_policy_rejects_symlink_escape_from_bound_worktree(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    source_directory = worktree / "src"
    outside = tmp_path / "outside"
    source_directory.mkdir(parents=True)
    outside.mkdir()
    (source_directory / "escape").symlink_to(outside, target_is_directory=True)
    policy = WorkspacePolicy(worktree, _permissions())

    with pytest.raises(PathPolicyViolation):
        policy.authorize_write("src/escape/secret.py")
