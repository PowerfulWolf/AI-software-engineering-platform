"""Native directory selection stays local, canonical and non-textual."""

from pathlib import Path
from subprocess import CompletedProcess

import pytest

from ai_software_engineer.web_console.directories import (
    DirectorySelectionError,
    NativeDirectoryChooser,
    _validated_directories,
)


def test_selected_directories_are_canonical_unique_absolute_paths(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    assert _validated_directories([str(first), str(first), str(second)]) == (
        str(first.resolve()),
        str(second.resolve()),
    )


def test_directory_selection_rejects_relative_missing_and_symlink_paths(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)

    for value in ("relative", str(tmp_path / "missing"), str(alias)):
        with pytest.raises(DirectorySelectionError, match="invalid directory"):
            _validated_directories([value])


def test_macos_cancel_is_not_confused_with_chooser_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ai_software_engineer.web_console.directories.sys.platform", "darwin")
    monkeypatch.setattr(
        "ai_software_engineer.web_console.directories.shutil.which",
        lambda _name: "/usr/bin/osascript",
    )

    monkeypatch.setattr(
        "ai_software_engineer.web_console.directories.subprocess.run",
        lambda *_args, **_kwargs: CompletedProcess((), 1, "", "User canceled. (-128)"),
    )
    assert NativeDirectoryChooser().choose() == ()

    monkeypatch.setattr(
        "ai_software_engineer.web_console.directories.subprocess.run",
        lambda *_args, **_kwargs: CompletedProcess((), 1, "", "syntax error"),
    )
    with pytest.raises(DirectorySelectionError, match="chooser failed"):
        NativeDirectoryChooser().choose()
