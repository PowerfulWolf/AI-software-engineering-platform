"""Upstream roles see the exact pinned files a requirement names."""

import subprocess
from pathlib import Path

import pytest

from ai_software_engineer.multi_directory import source_excerpts as module
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit
from ai_software_engineer.multi_directory.source_excerpts import candidate_paths, source_excerpts


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(root), *args), check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "docs" / "guide.md").write_text("# Guide\nold\n")
    (root / "scripts" / "run.sh").write_text(
        "#!/bin/sh\nexport API_KEY=sk-abcdefghijklmnopqrstuvwxyz0123456789\n"
    )
    (root / "docs" / "image.json").write_bytes(b"\0binary")
    _git(tmp_path, "init", "-q", str(root))
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    revision = _git(root, "rev-parse", "HEAD")
    # Later working-tree edits must not leak into the pinned excerpt.
    (root / "docs" / "guide.md").write_text("# Guide\nnew uncommitted\n")
    return root, revision


def _scope(root: Path, revision: str, selected: tuple[str, ...] = (".",)) -> DirectoryScope:
    return DirectoryScope(
        units=(
            DirectoryUnit(
                id="unit_0123456789abcdef",
                root=str(root),
                selected_paths=selected,
                base_revision=revision,
            ),
        )
    )


def test_candidate_paths_keep_relative_files_once_and_reject_traversal() -> None:
    text = (
        "改 `docs/guide.md`，对照 ./scripts/run.sh 和 docs/guide.md；忽略 ../etc/x.md 与 /abs/y.md"  # noqa: RUF001
    )
    assert candidate_paths([text]) == ("docs/guide.md", "scripts/run.sh")


def test_excerpts_are_pinned_redacted_and_scoped(repo: tuple[Path, str]) -> None:
    root, revision = repo
    excerpts = source_excerpts(
        _scope(root, revision), ["docs/guide.md scripts/run.sh docs/image.json docs/missing.md"]
    )
    by_path = {item["path"]: item for item in excerpts if isinstance(item, dict)}
    assert set(by_path) == {"docs/guide.md", "scripts/run.sh"}
    assert by_path["docs/guide.md"]["content"] == "# Guide\nold\n"
    assert by_path["docs/guide.md"]["revision"] == revision
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in str(by_path["scripts/run.sh"]["content"])
    assert source_excerpts(_scope(root, revision, ("docs",)), ["scripts/run.sh"]) == []


def test_excerpts_respect_file_and_total_limits(
    repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, revision = repo
    monkeypatch.setattr(module, "MAX_EXCERPT_FILE_BYTES", 4)
    (excerpt,) = source_excerpts(_scope(root, revision), ["docs/guide.md"])
    assert isinstance(excerpt, dict)
    assert excerpt["content"] == "# Gu" and excerpt["truncated"] is True
    monkeypatch.setattr(module, "MAX_EXCERPT_FILES", 1)
    assert len(source_excerpts(_scope(root, revision), ["docs/guide.md scripts/run.sh"])) == 1
