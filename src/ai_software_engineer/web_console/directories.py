"""Trusted local directory chooser for the loopback Web Console."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Protocol


class DirectorySelectionError(RuntimeError):
    """Safe failure raised when the native chooser cannot return directories."""


class DirectoryChooser(Protocol):
    def choose(self) -> tuple[str, ...]: ...


class NativeDirectoryChooser:
    """Open a fixed native folder dialog without accepting browser-side commands."""

    def choose(self) -> tuple[str, ...]:
        if sys.platform == "darwin":
            executable = shutil.which("osascript")
            if executable is None:
                raise DirectorySelectionError("The macOS directory chooser is unavailable.")
            command = (
                executable,
                "-e",
                'set chosenFolders to choose folder with prompt "选择需求涉及的代码目录" '
                "with multiple selections allowed",
                "-e",
                "set AppleScript's text item delimiters to linefeed",
                "-e",
                "set chosenPaths to {}",
                "-e",
                "repeat with chosenFolder in chosenFolders",
                "-e",
                "set end of chosenPaths to POSIX path of chosenFolder",
                "-e",
                "end repeat",
                "-e",
                "return chosenPaths as text",
            )
        elif sys.platform.startswith("linux"):
            if executable := shutil.which("zenity"):
                command = (
                    executable,
                    "--file-selection",
                    "--directory",
                    "--multiple",
                    "--separator=\n",
                    "--title=选择需求涉及的代码目录",
                )
            elif executable := shutil.which("kdialog"):
                command = (
                    executable,
                    "--getexistingdirectory",
                    ".",
                    "--title",
                    "选择需求涉及的代码目录",
                )
            else:
                raise DirectorySelectionError("No supported Linux directory chooser is installed.")
        else:
            raise DirectorySelectionError("Directory selection is unsupported on this platform.")
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DirectorySelectionError(
                "The native directory chooser could not complete."
            ) from error
        if result.returncode == 1 and (
            sys.platform.startswith("linux")
            or "User canceled" in result.stderr
            or "(-128)" in result.stderr
        ):
            return ()
        if result.returncode != 0:
            raise DirectorySelectionError("The native directory chooser failed.")
        return _validated_directories(result.stdout.splitlines())


def _validated_directories(values: list[str]) -> tuple[str, ...]:
    selected: list[str] = []
    for value in values:
        candidate = Path(value.strip()).expanduser()
        if not value.strip():
            continue
        if not candidate.is_absolute() or candidate.is_symlink() or not candidate.is_dir():
            raise DirectorySelectionError("The directory chooser returned an invalid directory.")
        resolved = str(candidate.resolve())
        if resolved not in selected:
            selected.append(resolved)
    return tuple(selected)


__all__ = ["DirectoryChooser", "DirectorySelectionError", "NativeDirectoryChooser"]
