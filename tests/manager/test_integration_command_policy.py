"""Published planning constraints and enforced predicate cannot drift apart."""

import pytest

from ai_software_engineer.multi_directory.integration_commands import (
    FORBIDDEN_OPTIONS,
    TEST_PREFIXES,
    is_test_command,
    planner_command_policy,
)


@pytest.mark.parametrize("prefix", TEST_PREFIXES)
def test_exact_test_prefixes_are_supported(prefix: tuple[str, ...]) -> None:
    assert is_test_command(prefix)
    for option in FORBIDDEN_OPTIONS:
        assert not is_test_command((*prefix, option))
        assert not is_test_command((*prefix, option + "=true"))


def test_context_is_a_copy_not_authority() -> None:
    policy = planner_command_policy()
    prefixes = policy["test_prefixes"]
    assert isinstance(prefixes, list)
    prefixes.append(["ruff"])
    assert not is_test_command(("ruff", "check", "."))
    fresh_prefixes = planner_command_policy()["test_prefixes"]
    assert isinstance(fresh_prefixes, list)
    assert ["ruff"] not in fresh_prefixes
