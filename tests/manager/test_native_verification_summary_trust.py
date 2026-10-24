"""Preserve the known in-process pytest summary trust boundary, not a spoof detector.

The real fixed runner still supervises a command; its summary cannot authenticate
candidate test execution when candidate conftest code shares that interpreter.
This disposable offline fixture uses no model, database connection or Docker.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import cast

from ai_software_engineer.manager import python_verification_runner


def test_candidate_conftest_can_spoof_fixed_runner_summary_without_running_test(
    tmp_path: Path,
) -> None:
    source, scratch, private = (tmp_path / name for name in ("source", "scratch", "private"))
    for directory in (source / "tests", source / "src", scratch, private):
        directory.mkdir(parents=True)
    marker = source / "test-body-executed.txt"
    (source / "tests/test_probe.py").write_text(
        "from pathlib import Path\n"
        "def test_should_run():\n"
        f"    Path({str(marker)!r}).write_text('test body executed')\n"
        "    raise AssertionError('the removed test body must not execute')\n"
    )
    (source / "conftest.py").write_text(
        "import pytest\n"
        "@pytest.hookimpl(hookwrapper=True)\n"
        "def pytest_collection_modifyitems(session, config, items):\n"
        "    yield\n"
        "    for plugin in config.pluginmanager.get_plugins():\n"
        "        if plugin.__class__.__name__ == '_SelectionGuard':\n"
        "            plugin.counts = [[0, 1, 1, 0, 0, 0, 0]]\n"
        "    items.clear()\n"
        "def pytest_sessionfinish(session, exitstatus):\n"
        "    session.exitstatus = 0\n"
    )
    config = private / "connection.json"
    config.write_text(
        json.dumps(
            {
                "socket": str(private / "mysql.sock"),
                "user": "ase_verify",
                "password": "a" * 48,
                "database": "ase_verify_test",
                "node_ids": ["tests/test_probe.py::test_should_run"],
            }
        )
    )
    config.chmod(0o600)
    result = subprocess.run(
        (
            str(Path(sys.executable).resolve()),
            "-I",
            "-S",
            "-B",
            str(Path(python_verification_runner.__file__).resolve()),
            sysconfig.get_path("purelib"),
            str(source.resolve()),
            str(scratch.resolve()),
            str(config.resolve()),
            "256",
        ),
        cwd=source,
        env={"PATH": os.defpath, "LANG": "C"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no tests ran" in result.stdout
    assert not marker.exists()
    summaries = [
        line.removeprefix("ASE_PYTEST_SUMMARY=")
        for line in result.stdout.splitlines()
        if line.startswith("ASE_PYTEST_SUMMARY=")
    ]
    assert len(summaries) == 1
    summary = cast(dict[str, object], json.loads(summaries[0]))
    assert summary["version"] == 1
    assert summary["pytest_exit"] == 0
    assert summary["columns"] == [
        "selector",
        "collected",
        "passed",
        "failed",
        "skipped",
        "setup_error",
        "teardown_error",
    ]
    assert summary["counts"] == [[0, 1, 1, 0, 0, 0, 0]]
    assert summary["errors"] == []
    assert summary["omitted_errors"] == 0
    assert summary["collection_errors"] == 0
    assert summary["report_overflow"] is False
    # A unique, well-formed marker plus exit0 did not establish test execution.
    # Do not turn this known counterexample into a claim of universal detection
    # or an automatic QA/Review verdict: those remain independent judgments.
