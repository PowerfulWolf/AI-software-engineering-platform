"""Exact maintenance observation never loosens ordinary workspace admission."""

import hashlib
from pathlib import Path

import pytest

from ai_software_engineer.git import mutation
from ai_software_engineer.git.mutation import (
    MAX_INVENTORY_FILE_BYTES,
    MutationFile,
    MutationInventoryRejected,
    capture_mutation_inventory,
)


def known_file(root: Path) -> MutationFile:
    path = root / ".mypy_cache" / "cache.db"
    path.parent.mkdir()
    body = b"x" * (MAX_INVENTORY_FILE_BYTES + 1)
    path.write_bytes(body)
    return MutationFile(
        ".mypy_cache/cache.db", "file", hashlib.sha256(body).hexdigest(), 0o644, len(body)
    )


def test_exact_oversized_file_is_complete_but_default_still_rejects(tmp_path: Path) -> None:
    expected = known_file(tmp_path)
    with pytest.raises(MutationInventoryRejected, match="limit"):
        capture_mutation_inventory(tmp_path)
    observed = capture_mutation_inventory(tmp_path, known_oversized_file=expected)
    assert observed.files == (expected,)
    with pytest.raises(MutationInventoryRejected, match="limit"):
        capture_mutation_inventory(tmp_path)


@pytest.mark.parametrize("problem", ["hash", "mode", "missing", "symlink", "other_oversized"])
def test_any_exact_fingerprint_or_other_file_drift_rejects(tmp_path: Path, problem: str) -> None:
    expected = known_file(tmp_path)
    path = tmp_path / expected.path
    if problem == "hash":
        with path.open("r+b") as stream:
            stream.write(b"y")
    elif problem == "mode":
        path.chmod(0o600)
    elif problem == "missing":
        path.unlink()
    elif problem == "symlink":
        path.unlink()
        path.symlink_to(tmp_path / "missing")
    else:
        (tmp_path / "source.bin").write_bytes(b"x" * expected.size)
    with pytest.raises(MutationInventoryRejected):
        capture_mutation_inventory(tmp_path, known_oversized_file=expected)


@pytest.mark.parametrize("path", ["/absolute", "../escape", "a//b", "a/./b", "a\\b"])
def test_capability_requires_canonical_relative_path(tmp_path: Path, path: str) -> None:
    expected = MutationFile(path, "file", "a" * 64, 0o644, MAX_INVENTORY_FILE_BYTES + 1)
    with pytest.raises(MutationInventoryRejected):
        capture_mutation_inventory(tmp_path, known_oversized_file=expected)


@pytest.mark.parametrize("limit", ["files", "total_bytes"])
def test_exact_file_does_not_relax_total_inventory_bounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    expected = known_file(tmp_path)
    (tmp_path / "small.py").write_text("x")
    if limit == "files":
        monkeypatch.setattr(mutation, "MAX_INVENTORY_FILES", 1)
    else:
        monkeypatch.setattr(mutation, "MAX_INVENTORY_BYTES", expected.size)
    with pytest.raises(MutationInventoryRejected, match="limits"):
        capture_mutation_inventory(tmp_path, known_oversized_file=expected)
