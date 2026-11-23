import subprocess
import sys
from pathlib import Path

import pytest

from ai_software_engineer.agents.python_tooling import project_python_path


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(("git", *arguments), cwd=root, check=True, capture_output=True)


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "src" / "pkg").mkdir(parents=True)
    (project / "src" / "pkg" / "__init__.py").write_text("VALUE = 'from-worktree'\n")
    (project / "pyproject.toml").write_text("[project]\nname='pkg'\nversion='0'\n")
    _git(project, "init", "-q", "-b", "main")
    _git(project, "add", ".")
    _git(project, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "init")
    subprocess.run(
        (sys.executable, "-m", "venv", "--without-pip", str(project / ".venv")), check=True
    )
    tree = tmp_path / "tree"
    _git(project, "worktree", "add", "-q", str(tree), "-b", "task")
    return tree


def test_role_python_imports_the_worktree_source_through_the_project_venv(worktree: Path) -> None:
    with project_python_path(worktree) as prefix:
        assert prefix is not None
        result = subprocess.run(
            ("python3", "-c", "import pkg, sys; print(pkg.VALUE, sys.version_info[:2])"),
            cwd=worktree,
            env={"PATH": prefix + ":/usr/bin:/bin"},
            capture_output=True,
            text=True,
        )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("from-worktree")
    assert str(tuple(sys.version_info[:2])) in result.stdout


def test_no_project_venv_leaves_the_path_unchanged(tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    with project_python_path(tmp_path / "x") as prefix:
        assert prefix is None
