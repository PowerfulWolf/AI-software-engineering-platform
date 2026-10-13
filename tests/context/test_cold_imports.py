"""Cold entrypoints cannot depend on another module having initialized Team first."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "modules",
    (
        ("team_workspace", "context"),
        ("context", "team_workspace"),
        ("git.release", "team_workspace"),
        ("team_workspace", "git.release"),
        ("web_console.host", "team_workspace"),
        ("team_workspace", "web_console.host"),
    ),
)
def test_entrypoints_import_in_fresh_process(modules: tuple[str, str]) -> None:
    root = Path(__file__).resolve().parents[2]
    source_root = root / "src"
    command = "\n".join(
        (
            "import importlib, pathlib, sys",
            f"source = pathlib.Path({str(source_root)!r})",
            "sys.path.insert(0, str(source))",
            f"for name in {modules!r}:",
            "    module = importlib.import_module('ai_software_engineer.' + name)",
            "    assert pathlib.Path(module.__file__).resolve().is_relative_to(source)",
        )
    )
    result = subprocess.run(
        (sys.executable, "-c", command),
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
