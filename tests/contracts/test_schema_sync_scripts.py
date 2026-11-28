"""Every schema generator runs on a clean copy and leaves published schemas unchanged."""

import os
import subprocess
import sys
from pathlib import Path
from shutil import copytree

ROOT = Path(__file__).resolve().parents[2]


def test_all_sync_scripts_reproduce_the_published_schemas(tmp_path: Path) -> None:
    copytree(ROOT / "schemas", tmp_path / "schemas")
    copytree(ROOT / "scripts", tmp_path / "scripts")
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    for script in sorted((tmp_path / "scripts").glob("sync-*.py")):
        completed = subprocess.run(
            (sys.executable, str(script)), capture_output=True, text=True, env=environment
        )
        assert completed.returncode == 0, f"{script.name}: {completed.stderr[-400:]}"
    changed = sorted(
        path.name
        for path in (ROOT / "schemas").glob("*.json")
        if (tmp_path / "schemas" / path.name).read_bytes() != path.read_bytes()
    )
    assert changed == [], f"regenerate with scripts/sync-*.py: {changed}"
