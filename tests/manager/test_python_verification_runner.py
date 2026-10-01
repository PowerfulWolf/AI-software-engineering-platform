"""Run the actual isolated-interpreter entry point against bounded disposable fixtures."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import sysconfig
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.manager.python_verification import (
    PytestSelection,
    PythonMysqlSandboxCapability,
    python_mysql_sandbox_command,
)

RUNNER = (
    Path(__file__).resolve().parents[2]
    / "src/ai_software_engineer/manager/python_verification_runner.py"
)


def run_fixture(
    tmp_path: Path, body: str, selections: list[str], *, max_cases: int = 256
) -> subprocess.CompletedProcess[str]:
    source, scratch, private = (tmp_path / name for name in ("source", "scratch", "private"))
    for directory in (source / "tests", source / "src", scratch, private):
        directory.mkdir(parents=True)
    (source / "tests/test_selected.py").write_text(body)
    (source / "src/candidate_identity.py").write_text("IDENTITY = 'approved candidate'\n")
    # Both parent discovery and configured addopts must be disabled by the trusted runner.
    (tmp_path / "conftest.py").write_text("raise RuntimeError('parent conftest executed')\n")
    (source / "pytest.ini").write_text("[pytest]\naddopts = --invalid-ambient-option\n")
    config = private / "connection.json"
    config.write_text(
        json.dumps(
            {
                "socket": str(private / "mysql.sock"),
                "user": "ase_verify",
                "password": "a" * 48,
                "database": "ase_verify_test",
                "node_ids": selections,
            }
        )
    )
    config.chmod(0o600)
    return subprocess.run(
        (
            str(Path(sys.executable).resolve()),
            "-I",
            "-S",
            "-B",
            str(RUNNER),
            sysconfig.get_path("purelib"),
            str(source),
            str(scratch),
            str(config),
            str(max_cases),
        ),
        cwd=source,
        env={"PATH": os.defpath, "LANG": "C", "PYTEST_ADDOPTS": "--ambient-denied"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_real_runner_loads_candidate_and_only_selected_case(tmp_path: Path) -> None:
    result = run_fixture(
        tmp_path,
        "def test_selected():\n"
        "    from candidate_identity import IDENTITY\n"
        "    assert IDENTITY == 'approved candidate'\n\n"
        "def test_not_selected():\n"
        "    raise AssertionError('unapproved test ran')\n",
        ["tests/test_selected.py::test_selected"],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
    assert not tuple((tmp_path / "source").rglob("__pycache__"))


@pytest.mark.parametrize("node", ["tests", "tests/test_selected.py", "../test.py::test_x"])
def test_runner_rejects_nonexact_selection_before_candidate_import(
    tmp_path: Path, node: str
) -> None:
    result = run_fixture(tmp_path, "raise RuntimeError('candidate imported')\n", [node])
    assert result.returncode == 4
    assert "candidate imported" not in result.stdout + result.stderr


def test_runner_rejects_collection_over_budget_before_tests_run(tmp_path: Path) -> None:
    result = run_fixture(
        tmp_path,
        "import pytest\n"
        "@pytest.mark.parametrize('n', range(257))\n"
        "def test_selected(n):\n"
        "    raise AssertionError('body must not run')\n",
        ["tests/test_selected.py::test_selected"],
    )
    assert result.returncode == 4
    assert "collection exceeds approved bounds" in result.stdout + result.stderr
    assert "body must not run" not in result.stdout + result.stderr


def test_runner_exposes_skipped_and_failed_cases_as_nonzero(tmp_path: Path) -> None:
    result = run_fixture(
        tmp_path,
        "import pytest\ndef test_selected():\n    pytest.skip('environment unavailable')\n",
        ["tests/test_selected.py::test_selected"],
    )
    assert result.returncode != 0
    assert "1 skipped" in result.stdout


def test_runner_refuses_other_database_destinations(tmp_path: Path) -> None:
    result = run_fixture(
        tmp_path,
        "def test_selected():\n"
        "    import pymysql, pytest\n"
        "    with pytest.raises(pymysql.OperationalError, match='unapproved MySQL destination'):\n"
        "        pymysql.connect(host='production.example', user='root', database='business')\n",
        ["tests/test_selected.py::test_selected"],
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(params=[None, "/private/tmp"], ids=["user-tmp", "public-tmp"])
def short_sandbox_root(request: pytest.FixtureRequest) -> Iterator[Path]:
    # macOS sockaddr_un.sun_path has a small fixed byte limit.
    with tempfile.TemporaryDirectory(
        prefix="ase-v-", dir=cast(str | None, request.param)
    ) as directory:
        yield Path(directory).resolve(strict=True)


@pytest.mark.skipif(
    sys.platform != "darwin" or os.environ.get("ASE_RUN_SANDBOX_TESTS") != "1",
    reason="requires explicitly enabled macOS sandbox boundary fixture",
)
def test_real_sandbox_denies_source_secret_other_sockets_and_tcp(short_sandbox_root: Path) -> None:
    tmp_path = short_sandbox_root
    executable = os.environ.get("ASE_TEST_CODEX_EXECUTABLE")
    if not executable:
        pytest.skip("ASE_TEST_CODEX_EXECUTABLE is not configured")
    source, scratch, private = (tmp_path / name for name in ("source", "scratch", "private"))
    for directory in (source / "tests", scratch, private):
        directory.mkdir(parents=True)
    secret = tmp_path / "unapproved-secret"
    secret.write_text("fixture-only-secret")
    public_temporary = tempfile.TemporaryDirectory(prefix="ase-public-", dir="/private/tmp")
    public_secret = Path(public_temporary.name) / "unapproved-secret"
    public_secret.write_text("public-temp-fixture-secret")
    approved, other, tcp = (
        socket.socket(socket.AF_UNIX),
        socket.socket(socket.AF_UNIX),
        socket.socket(),
    )
    try:
        approved.bind(str(private / "mysql.sock"))
        approved.listen()
        other.bind(str(tmp_path / "other.sock"))
        other.listen()
        tcp.bind(("127.0.0.1", 0))
        tcp.listen()
        port = tcp.getsockname()[1]
        (scratch / "external.sock").symlink_to(tmp_path / "other.sock")
        paths = list(map(str, (source, scratch, private)))
        test_file = source / "tests/test_boundary.py"
        test_file.write_text(
            "import socket\nfrom pathlib import Path\nimport pytest\n"
            "def test_boundaries():\n"
            f"    source, scratch, private = map(Path, {paths!r})\n"
            "    (scratch / 'allowed').write_text('allowed')\n"
            "    for index, action in enumerate((\n"
            "        lambda: (source / 'unapproved-write').write_text('denied'),\n"
            f"        lambda: Path({str(secret)!r}).read_text(),\n"
            f"        lambda: Path({str(public_secret)!r}).read_text(),\n"
            f"        lambda: Path({str(public_secret)!r}).write_text('denied'),\n"
            "        lambda: (private / 'mysql.sock').unlink(),\n"
            "        lambda: socket.socket(socket.AF_UNIX).bind(\n"
            "            str(private / 'replacement.sock')),\n"
            "        lambda: socket.socket(socket.AF_UNIX).connect(\n"
            "            str(scratch / 'external.sock')),\n"
            f"        lambda: socket.create_connection(('127.0.0.1', {port}), timeout=1),\n"
            "    )):\n"
            "        try:\n"
            "            action()\n"
            "        except OSError:\n"
            "            pass\n"
            "        else:\n"
            "            pytest.fail(f'sandbox allowed forbidden operation {index}')\n"
            "    with socket.socket(socket.AF_UNIX) as client:\n"
            "        client.connect(str(private / 'mysql.sock'))\n"
        )
        node = "tests/test_boundary.py::test_boundaries"
        config = private / "connection.json"
        config.write_text(
            json.dumps(
                {
                    "socket": str(private / "mysql.sock"),
                    "user": "ase_verify",
                    "password": "a" * 48,
                    "database": "ase_verify_test",
                    "node_ids": [node],
                }
            )
        )
        config.chmod(0o600)
        # Fixture invocation tests the actual OS policy, not production admission.
        cap = PythonMysqlSandboxCapability(
            sandbox_executable=str(Path(executable).resolve()),
            sandbox_executable_sha256="a" * 64,
            python_executable=str(Path(sys.executable).resolve()),
            python_executable_sha256="b" * 64,
            python_runtime_root=str(Path(sys.base_prefix).resolve()),
            python_runtime_sha256="c" * 64,
            dependency_root=sysconfig.get_path("purelib"),
            dependency_sha256="d" * 64,
            runner_path=str(RUNNER),
            runner_sha256="e" * 64,
            docker_executable="/fixture/docker",
            docker_executable_sha256="f" * 64,
            docker_socket="/fixture/docker.sock",
            docker_daemon_id="fixture",
            mysql_image_id="sha256:" + "0" * 64,
            selections=(PytestSelection(node_id=node, criterion_ids=("ac_boundary",)),),
        )
        result = subprocess.run(
            python_mysql_sandbox_command(cap, source, scratch, private),
            cwd=source,
            env={"PATH": os.defpath, "LANG": "C"},
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "1 passed" in result.stdout
        assert not (source / "unapproved-write").exists()
        assert secret.read_text() == "fixture-only-secret"
    finally:
        approved.close()
        other.close()
        tcp.close()
        public_temporary.cleanup()
