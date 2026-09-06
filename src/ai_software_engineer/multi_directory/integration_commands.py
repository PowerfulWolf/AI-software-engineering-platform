"""One immutable test-command policy for Planner context and execution preflight."""

from ai_software_engineer.domain.model import WirePayload

TEST_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("python", "-m", "unittest"),
    ("python3", "-m", "unittest"),
    ("uv", "run", "pytest"),
    ("npm", "test"),
    ("pnpm", "test"),
    ("yarn", "test"),
    ("bun", "test"),
    ("go", "test"),
    ("ctest",),
    ("mvn", "test"),
    ("./mvnw", "test"),
    ("gradle", "test"),
    ("./gradlew", "test"),
)
FORBIDDEN_OPTIONS: frozenset[str] = frozenset(
    {
        "-c",
        "--eval",
        "-e",
        "install",
        "publish",
        "deploy",
        "--help",
        "-h",
        "--version",
        "--collect-only",
        "--co",
        "--listTests",
        "--passWithNoTests",
        "--dry-run",
        "-DskipTests",
        "-Dmaven.test.skip",
        "-x",
        "--exclude-task",
    }
)


def is_test_command(argv: tuple[str, ...]) -> bool:
    if any(token.split("=", 1)[0] in FORBIDDEN_OPTIONS for token in argv):
        return False
    return any(argv[: len(prefix)] == prefix for prefix in TEST_PREFIXES)


def planner_command_policy() -> WirePayload:
    """Fresh context data cannot mutate the authoritative command predicate."""
    return {
        "test_prefixes": [list(prefix) for prefix in TEST_PREFIXES],
        "forbidden_options": [option for option in sorted(FORBIDDEN_OPTIONS)],
        "requires_project_command_allowlist": True,
        "inspection_build_lint_are_not_integration_tests": True,
    }
