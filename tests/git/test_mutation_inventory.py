"""Final-state checks must not lose ignored or aliased protected writes."""

from pathlib import Path

import pytest

from ai_software_engineer.git.mutation import (
    MutationInventoryRejected,
    capture_mutation_inventory,
    changed_mutation_paths,
    is_execution_cache_path,
)


def test_inventory_sees_ignored_rules_and_cache_without_following_links(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("hidden/\n.trellis/\n")
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    (outside / "secret.txt").write_text("external sentinel")
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    before = capture_mutation_inventory(tmp_path)
    (tmp_path / ".trellis").mkdir()
    (tmp_path / ".trellis" / "rule.md").write_text("changed")
    (tmp_path / "hidden").mkdir()
    (tmp_path / "hidden" / "draft.py").write_text("draft")
    after = capture_mutation_inventory(tmp_path)
    assert changed_mutation_paths(before, after) == (".trellis/rule.md", "hidden/draft.py")
    assert "link/secret.txt" not in {f.path for f in after.files}
    assert not is_execution_cache_path(".TRELLIS/.pytest_cache/evil.py")
    assert not is_execution_cache_path("src/.git/.ruff_cache/evil.py")
    assert is_execution_cache_path("src/__pycache__/module.cpython-312.pyc")
    assert not is_execution_cache_path("src/__pycache__/module.py")


def test_inventory_binds_content_modes_deletion_and_new_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("before")
    removed = tmp_path / "removed.txt"
    removed.write_text("removed")
    before = capture_mutation_inventory(tmp_path)
    source.chmod(0o755)
    removed.unlink()
    (tmp_path / "newlink").symlink_to("source.py")
    after = capture_mutation_inventory(tmp_path)
    assert before.sha256 != after.sha256
    assert changed_mutation_paths(before, after) == ("newlink", "removed.txt", "source.py")


def test_inventory_refuses_unbounded_file_and_symlink_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ai_software_engineer.git.mutation.MAX_INVENTORY_FILE_BYTES", 3)
    (tmp_path / "large").write_text("four")
    with pytest.raises(MutationInventoryRejected):
        capture_mutation_inventory(tmp_path)
    alias = tmp_path.parent / (tmp_path.name + "-alias")
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(MutationInventoryRejected):
        capture_mutation_inventory(alias)
