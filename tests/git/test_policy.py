"""Behavior tests for machine-enforced workspace policy."""

from pathlib import Path, PurePosixPath

import pytest

from ai_software_engineer.domain import AgentPermissions, NetworkAccess
from ai_software_engineer.git import (
    CommandPolicyViolation,
    PathPolicyViolation,
    WorkspacePolicy,
)
from ai_software_engineer.swift_verification import SWIFT_VERIFICATION_COMMANDS


@pytest.mark.parametrize(
    "suffix",
    [
        ("--package-path", "/tmp/other"),
        ("--scratch-path", "/tmp/other"),
        ("--disable-sandbox",),
        ("--netrc-file", "/tmp/credentials"),
        ("-Xswiftc", "-DOVERRIDE"),
        ("--filter",),
        ("--filter=example",),
        ("-c", "debug", "--configuration", "release"),
        ("--filter", "First", "--filter", "Second"),
        ("--configuration", "invalid"),
        ("--filter", "x" * 257),
    ],
)
def test_swift_verification_rejects_permission_overrides(
    tmp_path: Path, suffix: tuple[str, ...]
) -> None:
    policy = WorkspacePolicy(
        tmp_path, _permissions().model_copy(update={"commands": SWIFT_VERIFICATION_COMMANDS})
    )
    prefix = ("swift", "test", "--disable-automatic-resolution", "--skip-update")
    with pytest.raises(CommandPolicyViolation):
        policy.authorize_command((*prefix, *suffix))


def test_swift_verification_allows_focused_candidate_checks(tmp_path: Path) -> None:
    policy = WorkspacePolicy(
        tmp_path, _permissions().model_copy(update={"commands": SWIFT_VERIFICATION_COMMANDS})
    )
    for argv in (
        ("swift", "--version"),
        (
            "swift",
            "test",
            "--disable-automatic-resolution",
            "--skip-update",
            "--filter",
            "HistorySelection",
        ),
        (
            "swift",
            "build",
            "--disable-automatic-resolution",
            "--skip-update",
            "--product",
            "Monitor",
            "-c",
            "release",
        ),
    ):
        assert policy.authorize_command(argv) == argv
    for rejected_argv in (
        ("swift", "package", "update"),
        ("swift", "run", "evil.swift"),
        ("swift", "--version", "evil.swift"),
    ):
        with pytest.raises(CommandPolicyViolation):
            policy.authorize_command(rejected_argv)


def _permissions() -> AgentPermissions:
    return AgentPermissions(
        read_paths=("README.md", "src/**", "tests/**"),
        write_paths=("src/**", "tests/unit/**"),
        commands=("pytest", "ruff", "git diff", "git status"),
        network=NetworkAccess.NONE,
    )


@pytest.mark.parametrize(
    "path",
    (
        ".trellis/spec/core/contracts.md",
        "nested/.trellis/tasks/x.md",
        ".TRELLIS/spec/core/contracts.md",
        "nested/.TreLLis/tasks/x.md",
    ),
)
@pytest.mark.parametrize(
    "write_paths",
    (
        ("**",),
        (
            "**/.trellis/**",
            ".trellis/**",
            ".TRELLIS/**",
            "nested/.TreLLis/**",
            "nested/.trellis/**",
        ),
    ),
)
def test_trellis_write_is_hard_denied_even_when_explicitly_allowed(
    tmp_path: Path, path: str, write_paths: tuple[str, ...]
) -> None:
    permissions = _permissions().model_copy(
        update={"read_paths": ("**",), "write_paths": write_paths}
    )
    policy = WorkspacePolicy(tmp_path, permissions)
    assert policy.authorize_read(path) == PurePosixPath(path)
    with pytest.raises(PathPolicyViolation, match="只读"):
        policy.authorize_write(path)


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


def test_trellis_write_cannot_escape_hard_deny_through_a_symlink(tmp_path: Path) -> None:
    protected = tmp_path / ".trellis/spec"
    protected.mkdir(parents=True)
    (tmp_path / "rules").symlink_to(protected, target_is_directory=True)
    permissions = _permissions().model_copy(update={"read_paths": ("**",), "write_paths": ("**",)})
    policy = WorkspacePolicy(tmp_path, permissions)
    policy.authorize_read("rules/contracts.md")
    with pytest.raises(PathPolicyViolation, match="只读"):
        policy.authorize_write("rules/contracts.md")


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


def test_verifier_command_policy_requires_focused_pytest_selectors(tmp_path: Path) -> None:
    permissions = _permissions().model_copy(update={"commands": ("pytest", "python")})
    policy = WorkspacePolicy(tmp_path, permissions, require_focused_tests=True)

    assert policy.authorize_command(("pytest", "tests/unit/test_service.py", "-q")) == (
        "pytest",
        "tests/unit/test_service.py",
        "-q",
    )
    assert policy.authorize_command(
        ("python", "-m", "pytest", "tests/unit/test_service.py::test_one")
    ) == ("python", "-m", "pytest", "tests/unit/test_service.py::test_one")

    for arguments in (
        ("pytest",),
        ("pytest", "tests/unit"),
        ("pytest", "-m", "not", "mysql"),
        ("python", "-c", "import pytest; pytest.main(['tests/unit/test_service.py'])"),
    ):
        with pytest.raises(CommandPolicyViolation, match="pytest"):
            policy.authorize_command(arguments)


def test_verifier_command_policy_handles_uv_pytest_wrapper(tmp_path: Path) -> None:
    permissions = _permissions().model_copy(update={"commands": ("uv",)})
    policy = WorkspacePolicy(tmp_path, permissions, require_focused_tests=True)

    assert policy.authorize_command(("uv", "run", "pytest", "tests/unit/test_service.py"))
    with pytest.raises(CommandPolicyViolation, match="pytest"):
        policy.authorize_command(("uv", "run", "pytest", "tests"))


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
