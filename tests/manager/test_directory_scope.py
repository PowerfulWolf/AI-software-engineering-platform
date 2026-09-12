"""Directory inputs define authorization, not a required project hierarchy."""

import subprocess
from pathlib import Path

import pytest

from ai_software_engineer.multi_directory.scope import discover_scope


def repository(root: Path) -> Path:
    root.mkdir(parents=True)
    subprocess.run(("git", "init", "-q", str(root)), check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-qm",
            "initial",
        ),
        cwd=root,
        check=True,
    )
    return root


def test_nonadjacent_roots_and_module_selections(tmp_path: Path) -> None:
    backend = repository(tmp_path / "backend")
    frontend = repository(tmp_path / "elsewhere" / "frontend")
    (backend / "api").mkdir()
    (backend / "service").mkdir()
    scope = discover_scope((str(backend / "api"), str(frontend), str(backend / "service")))
    assert len(scope.units) == 2
    unit = next(unit for unit in scope.units if unit.root == str(backend))
    assert unit.selected_paths == ("api", "service")
    assert unit.permits("api/src/**")
    assert not unit.permits("api2/**")
    assert not unit.permits("**")
    assert not unit.permits("api/../secret")


def test_alias_duplicate_and_parent_scope_have_stable_identity(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    (repo / "module").mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(repo, target_is_directory=True)
    first = discover_scope((str(repo),))
    second = discover_scope((str(alias), str(repo / "module"), str(repo)))
    assert first == second


def test_unsupported_vcs_is_observed_not_written(tmp_path: Path) -> None:
    scope = discover_scope((str(tmp_path),))
    assert scope.units[0].base_revision is None
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("paths", [(), ("relative",), ("/missing/ase-directory",)])
def test_invalid_roots_fail_closed(paths: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        discover_scope(paths)
