"""Each Requirement gets its own Coder branch when Product names collide."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_software_engineer.multi_directory.branch_allocation import (
    repository_branches,
    unique_branch_name,
)

NAME = "ai/feature/runtime-release-activation-faq"


def _repo(path: Path, *branches: str) -> Path:
    subprocess.run(("git", "init", "-q", "-b", "main", str(path)), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ),
        check=True,
    )
    for branch in branches:
        subprocess.run(("git", "-C", str(path), "branch", branch), check=True)
    return path


def test_free_name_is_kept() -> None:
    assert unique_branch_name(NAME, frozenset({"main"})) == NAME


def test_taken_name_gets_first_free_qualifier(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo", NAME, NAME + "-2")
    taken = repository_branches([str(root), str(tmp_path / "missing")])
    assert {"main", NAME, NAME + "-2"} <= taken
    assert unique_branch_name(NAME, taken) == NAME + "-3"


def test_exhausted_qualifiers_fail_closed() -> None:
    taken = frozenset({NAME, *(f"{NAME}-{n}" for n in range(2, 31))})
    with pytest.raises(ValueError, match="no free branch name"):
        unique_branch_name(NAME, taken)
