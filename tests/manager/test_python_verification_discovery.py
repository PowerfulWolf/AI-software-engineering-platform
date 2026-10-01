"""Fingerprint the actual trusted files; candidate selection discovery never imports tests."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_software_engineer.manager.python_verification import PytestSelection
from ai_software_engineer.manager.python_verification_discovery import (
    dependency_fingerprint,
    require_selected_candidate_files,
)


def test_dependency_fingerprint_binds_source_and_loadable_bytecode(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("VALUE = 1\n")
    first = dependency_fingerprint(tmp_path)
    assert dependency_fingerprint(tmp_path) == first
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__/module.pyc").write_bytes(b"mutable interpreter cache")
    second = dependency_fingerprint(tmp_path)
    assert second != first
    (tmp_path / "module.py").write_text("VALUE = 2\n")
    assert dependency_fingerprint(tmp_path) != second


def test_dependency_fingerprint_binds_relative_names_and_modes(tmp_path: Path) -> None:
    original = tmp_path / "module.py"
    original.write_text("VALUE = 1\n")
    first = dependency_fingerprint(tmp_path)
    original.chmod(0o755)
    assert dependency_fingerprint(tmp_path) != first
    second = dependency_fingerprint(tmp_path)
    original.rename(tmp_path / "other.py")
    assert dependency_fingerprint(tmp_path) != second


def test_dependency_symlink_and_file_budget_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "escape.py").symlink_to(Path(__file__).resolve())
    with pytest.raises(ValueError, match="symbolic"):
        dependency_fingerprint(tmp_path)
    (tmp_path / "escape.py").unlink()
    (tmp_path / "module.py").write_text("VALUE = 1\n")
    with pytest.raises(ValueError, match="budget"):
        dependency_fingerprint(tmp_path, max_files=0)


def test_internal_file_alias_binds_target_and_link(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("VALUE = 1\n")
    (tmp_path / "alias.py").symlink_to("module.py")
    first = dependency_fingerprint(tmp_path)
    (tmp_path / "module.py").write_text("VALUE = 2\n")
    assert dependency_fingerprint(tmp_path) != first


def test_external_link_hop_returning_inside_tree_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "dependencies"
    root.mkdir()
    (root / "module.py").write_text("VALUE = 1\n")
    (tmp_path / "external-link").symlink_to(root / "module.py")
    (root / "alias.py").symlink_to(tmp_path / "external-link")
    with pytest.raises(ValueError, match="symbolic link"):
        dependency_fingerprint(root)


def test_candidate_selection_uses_regular_sealed_git_files(tmp_path: Path) -> None:
    def git(*arguments: str) -> str:
        return subprocess.check_output(
            ("/usr/bin/git", "-c", "core.hooksPath=/dev/null", *arguments),
            cwd=tmp_path,
            env={"PATH": os.defpath, "GIT_CONFIG_GLOBAL": "/dev/null"},
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).strip()

    git("init", "-q")
    (tmp_path / "tests").mkdir()
    test_file = tmp_path / "tests/test_case.py"
    test_file.write_text("raise RuntimeError('must never import during discovery')\n")
    (tmp_path / "tests/test_alias.py").symlink_to("test_case.py")
    git("add", "tests")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.test",
        "commit",
        "-qm",
        "fixture",
    )
    revision = git("rev-parse", "HEAD")
    # A mutable checkout deletion must not replace the approved candidate's facts.
    test_file.unlink()
    selection = PytestSelection(node_id="tests/test_case.py::test_case", criterion_ids=("ac_01",))
    require_selected_candidate_files(tmp_path, revision, (selection,))
    for node in ("tests/test_alias.py::test_case", "tests/test_missing.py::test_case"):
        with pytest.raises(ValueError, match="tracked regular candidate"):
            require_selected_candidate_files(
                tmp_path, revision, (PytestSelection(node_id=node, criterion_ids=("ac_01",)),)
            )


def test_unreadable_directory_cannot_produce_a_partial_fingerprint(tmp_path: Path) -> None:
    with (
        patch("os.scandir", side_effect=PermissionError("fixture unreadable directory")),
        pytest.raises(ValueError, match="completely fingerprinted"),
    ):
        dependency_fingerprint(tmp_path)
