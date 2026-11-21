"""Pinned runtime releases are isolated clones switched by the controlled restart."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "ase-release.sh"

FAKE_SERVICE = """#!/bin/sh
echo "$(cd "$(dirname "$0")/.." && pwd -P) $1" >> "$ASE_TEST_RESTART_LOG"
"""

FAKE_UV = """#!/bin/sh
[ "$1 $2 $3" = "sync --frozen --no-dev" ] || exit 9
mkdir -p .venv/bin
printf '#!/bin/sh\\n' > .venv/bin/ase-console
chmod +x .venv/bin/ase-console
ln -s "$(command -v python3)" .venv/bin/python
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repo), *args), check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "dev"
    (repo / "scripts").mkdir(parents=True)
    (repo / "src" / "pkg").mkdir(parents=True)
    (repo / "src" / "pkg" / "__init__.py").write_text("VALUE = 1\n")
    service = repo / "scripts" / "ase-console-service.sh"
    service.write_text(FAKE_SERVICE)
    service.chmod(0o755)
    shutil.copy2(SCRIPT, repo / "scripts" / "ase-release.sh")
    _git(tmp_path, "init", "-q", str(repo))
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(FAKE_UV)
    uv.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "ASE_RUNTIME_HOME": str(tmp_path / "runtime"),
        "ASE_DEV_REPO": str(repo),
        "ASE_TEST_RESTART_LOG": str(tmp_path / "restarts.log"),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    return repo, environment


def _run(environment: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("sh", str(SCRIPT), *args), env=environment, capture_output=True, text=True
    )


def test_release_lifecycle_switches_through_controlled_restart_and_rolls_back(
    setup: tuple[Path, dict[str, str]], tmp_path: Path
) -> None:
    repo, environment = setup
    assert _run(environment, "tag", "v0.2.0").returncode == 0
    installed = _run(environment, "install", "v0.2.0")
    assert installed.returncode == 0, installed.stderr
    release = tmp_path / "runtime" / "releases" / "v0.2.0"
    assert (release / ".venv" / "bin" / "ase-console").exists()
    assert not os.stat(release / "src" / "pkg" / "__init__.py").st_mode & stat.S_IWUSR
    # The release is an independent clone, not a worktree of the dev repository.
    assert "runtime" not in _git(repo, "worktree", "list")

    (repo / "src" / "pkg" / "__init__.py").write_text("VALUE = 2\n")
    _git(repo, "commit", "-qam", "next")
    assert _run(environment, "tag", "v0.3.0").returncode == 0
    assert _run(environment, "install", "v0.3.0").returncode == 0
    # Developing after a release never changes the installed engine.
    assert (release / "src" / "pkg" / "__init__.py").read_text() == "VALUE = 1\n"

    assert _run(environment, "activate", "v0.2.0").returncode == 0
    assert _run(environment, "activate", "v0.3.0").returncode == 0
    current = tmp_path / "runtime" / "current"
    assert current.resolve() == (tmp_path / "runtime" / "releases" / "v0.3.0").resolve()
    rolled_back = _run(environment, "rollback")
    assert rolled_back.returncode == 0, rolled_back.stderr
    assert current.resolve() == release.resolve()
    restarts = (tmp_path / "restarts.log").read_text().splitlines()
    assert [line.rsplit("/", 1)[-1] for line in restarts] == [
        "v0.2.0 restart",
        "v0.3.0 restart",
        "v0.2.0 restart",
    ]
    status = _run(environment, "status")
    assert "active release: v0.2.0" in status.stdout
    assert "previous release: v0.3.0" in status.stdout


def test_release_refuses_dirty_tree_bad_names_duplicates_and_missing_installs(
    setup: tuple[Path, dict[str, str]],
) -> None:
    repo, environment = setup
    (repo / "src" / "pkg" / "__init__.py").write_text("VALUE = 3\n")
    dirty = _run(environment, "tag", "v1.0.0")
    assert dirty.returncode != 0 and "uncommitted" in dirty.stderr
    _git(repo, "checkout", "-q", "--", ".")
    assert _run(environment, "tag", "release-1").returncode != 0
    assert _run(environment, "tag", "v1.0.0").returncode == 0
    assert _run(environment, "tag", "v1.0.0").returncode != 0
    assert _run(environment, "install", "v9.9.9").returncode != 0
    assert _run(environment, "activate", "v1.0.0").returncode != 0
    assert _run(environment, "install", "v1.0.0").returncode == 0
    assert _run(environment, "install", "v1.0.0").returncode != 0
    assert _run(environment, "rollback").returncode != 0
