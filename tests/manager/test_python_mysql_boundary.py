"""Explicitly enabled real SQL/proxy/OS boundary fixture, separate from business verdicts."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.manager.python_mysql_proxy import MysqlUnixProxy
from ai_software_engineer.manager.python_mysql_resources import (
    IsolatedMysqlResource,
    MysqlResourceUnavailable,
)
from ai_software_engineer.manager.python_verification import (
    PytestSelection,
    python_mysql_sandbox_command,
)
from ai_software_engineer.manager.python_verification_discovery import (
    discover_python_mysql_capability,
)
from ai_software_engineer.recovery.python_mysql_execution import safe_verification_output
from ai_software_engineer.recovery.python_mysql_records import MysqlResourceIntent


@pytest.mark.skipif(
    sys.platform != "darwin" or os.environ.get("ASE_RUN_MYSQL_BOUNDARY_TESTS") != "1",
    reason="explicit real macOS/Docker boundary fixture",
)
def test_isolated_mysql_principal_proxy_and_candidate_os_denials():
    codex = os.environ.get("ASE_TEST_CODEX_EXECUTABLE") or shutil.which("codex")
    assert codex
    with tempfile.TemporaryDirectory(prefix="ase-mysql-v-", dir="/private/tmp") as directory:
        root = Path(directory).resolve()
        source, scratch, private = (root / name for name in ("source", "scratch", "private"))
        for path in (source / "tests", scratch, private):
            path.mkdir(parents=True)
        denied = source / "denied.txt"
        denied.write_text("fixture-only Task denied data")
        (source / "tests/test_boundary.py").write_text(
            "import json, os, socket\nfrom pathlib import Path\nimport pymysql, pytest\n"
            "from urllib.parse import urlsplit\n"
            "def test_boundary():\n"
            "    dsn = urlsplit(os.environ['ASE_TEST_MYSQL_DSN'])\n"
            "    connection = pymysql.connect(host=dsn.hostname,user=dsn.username,\n"
            "        password=dsn.password,database=dsn.path[1:])\n"
            "    with connection.cursor() as cursor:\n"
            "        cursor.execute('CREATE TABLE isolated_fixture(id INT PRIMARY KEY)')\n"
            "        cursor.execute('INSERT INTO isolated_fixture VALUES (1)')\n"
            "        cursor.execute('SELECT COUNT(*) FROM isolated_fixture')\n"
            "        assert cursor.fetchone() == (1,)\n"
            "        with pytest.raises(pymysql.MySQLError):\n"
            "            cursor.execute('SELECT * FROM mysql.user')\n"
            "        with pytest.raises(pymysql.MySQLError):\n"
            "            cursor.execute('CREATE DATABASE forbidden_business')\n"
            "    connection.close()\n"
            f"    private = Path({str(private)!r})\n"
            "    from pymysql.connections import Connection\n"
            "    with pytest.raises(pymysql.MySQLError):\n"
            "        Connection(unix_socket=str(private/'mysql.sock'),user='root',\n"
            "            password='',connect_timeout=2)\n"
            "    for action in (\n"
            f"        lambda: Path({str(denied)!r}).read_text(),\n"
            f"        lambda: Path({str(source / 'modified.txt')!r}).write_text('denied'),\n"
            "        lambda: (private/'mysql.sock').unlink(),\n"
            "        lambda: socket.socket(socket.AF_UNIX).bind(str(private/'replacement.sock')),\n"
            "        lambda: socket.create_connection(('127.0.0.1',3306),timeout=1),\n"
            "        lambda: socket.create_connection(('1.1.1.1',80),timeout=1),\n"
            "    ):\n"
            "        with pytest.raises(OSError): action()\n"
        )
        environment = {"PATH": "/usr/bin:/bin", "LANG": "C", "GIT_CONFIG_GLOBAL": "/dev/null"}

        def git(*args):
            return subprocess.check_output(
                ("/usr/bin/git", "-c", "core.hooksPath=/dev/null", *args),
                cwd=source,
                env=environment,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
            ).strip()

        git("init", "-q")
        git("add", ".")
        git(
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "-qm",
            "fixture",
        )
        cap = discover_python_mysql_capability(
            source,
            git("rev-parse", "HEAD"),
            (
                PytestSelection(
                    node_id="tests/test_boundary.py::test_boundary", criterion_ids=("ac_sql",)
                ),
            ),
            codex_executable=codex,
            denied_patterns=("denied.txt",),
        )
        records = []
        intent = MysqlResourceIntent.create(
            plan_sha256="a" * 64,
            invocation_sha256="b" * 64,
            role="qa",
            capability=cap,
            recorded_at=datetime.now(UTC),
        )
        resource = IsolatedMysqlResource(
            intent, lambda r: records.append(r) or r, clock=lambda: datetime.now(UTC)
        )
        proxy = None
        try:
            resource.start(lambda: None)
            proxy = MysqlUnixProxy(resource, private / "mysql.sock")
            resource.verify_principal(private / "mysql.sock")
            start = time.monotonic()
            with pytest.raises(MysqlResourceUnavailable):
                resource.command(
                    "exec",
                    resource.container_id,
                    "/usr/bin/timeout",
                    "--kill-after=.2",
                    ".2",
                    "/usr/bin/bash",
                    "-c",
                    "trap '' TERM; while :; do sleep 1; done",
                    timeout=5,
                )
            assert time.monotonic() - start < 5
            config = private / "connection.json"
            config.write_text(
                json.dumps(
                    {
                        "socket": str(private / "mysql.sock"),
                        "user": "ase_verify",
                        "password": resource.password,
                        "database": "ase_verify_test",
                        "node_ids": ["tests/test_boundary.py::test_boundary"],
                        "denied_paths": list(cap.denied_relative_paths),
                    }
                )
            )
            config.chmod(0o600)
            private.chmod(0o500)
            result = subprocess.run(
                python_mysql_sandbox_command(cap, source, scratch, private),
                cwd=source,
                env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TMPDIR": str(scratch)},
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            safe = safe_verification_output(
                result.stdout + result.stderr, truncated=False, secrets=resource.secrets
            )
            assert result.returncode == 0, safe
            assert "1 passed" in safe
        finally:
            private.chmod(0o700)
            try:
                if proxy is not None:
                    proxy.close()
            finally:
                resource.close()
        assert records[-1].phase == "CLEANED"
        assert not (source / "modified.txt").exists()
