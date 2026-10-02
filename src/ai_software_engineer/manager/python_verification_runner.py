"""Hash-bound pytest entry point, launched with -I -S -B inside the OS sandbox.

This file deliberately has no platform imports: importing the candidate's platform
package to enforce the executor boundary would let candidate code enforce itself.
The executor validates the private config against the approved capability. This
runner is defense in depth; its output is command evidence, never a verdict.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest
    from pymysql.connections import Connection

PYTEST_NODE_PATTERN = (
    r"^tests/(?:[A-Za-z0-9_][A-Za-z0-9_.-]*/)*test_[A-Za-z0-9_.-]+\.py"
    r"::[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)?"
    r"(?:\[[A-Za-z0-9_.-]+\])?$"
)


@dataclass(frozen=True)
class _ConnectionConfig:
    socket: str
    user: str
    password: str
    database: str
    node_ids: tuple[str, ...]
    denied_paths: tuple[str, ...] = ()

    @classmethod
    def read(cls, path: Path, source: Path) -> _ConnectionConfig:
        if path.resolve(strict=True) != path or path.stat().st_mode & 0o077:
            raise ValueError("private connection config must be canonical and owner-only")
        if path.stat().st_size > 32000:
            raise ValueError("connection config exceeds limit")
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or set(value) not in (
            {
                "socket",
                "user",
                "password",
                "database",
                "node_ids",
            },
            {"socket", "user", "password", "database", "node_ids", "denied_paths"},
        ):
            raise ValueError("invalid connection config")
        nodes = value["node_ids"]
        denied = value.get("denied_paths", [])
        if (
            not isinstance(denied, list)
            or len(denied) > 4096
            or any(
                not isinstance(path, str)
                or not path
                or Path(path).is_absolute()
                or str(Path(path)) != path
                or ".." in Path(path).parts
                or any(c in path for c in "*?[]\0\n\r")
                for path in denied
            )
        ):
            raise ValueError("invalid fixed denied inventory")
        if (
            value["socket"] != str(path.parent / "mysql.sock")
            or value["user"] != "ase_verify"
            or value["database"] != "ase_verify_test"
            or not isinstance(value["password"], str)
            or re.fullmatch(r"[a-f0-9]{48}", value["password"]) is None
            or not isinstance(nodes, list)
            or not 1 <= len(nodes) <= 32
            or any(
                not isinstance(node, str)
                or len(node) > 512
                or re.fullmatch(PYTEST_NODE_PATTERN, node) is None
                for node in nodes
            )
            or len(set(nodes)) != len(nodes)
        ):
            raise ValueError("invalid connection or exact test selections")
        for node in nodes:
            test_file = source / node.split("::", 1)[0]
            if test_file.resolve(strict=True) != test_file or not test_file.is_file():
                raise ValueError("selected test must be a regular canonical candidate file")
        return cls(
            value["socket"],
            value["user"],
            value["password"],
            value["database"],
            tuple(nodes),
            tuple(denied),
        )


class _SelectionGuard:
    def __init__(self, nodes: tuple[str, ...], max_cases: int) -> None:
        self.nodes, self.max_cases = nodes, max_cases
        self.skipped = False

    @staticmethod
    def _matches(actual: str, approved: str) -> bool:
        return actual == approved or ("[" not in approved and actual.startswith(approved + "["))

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        import pytest

        actual = tuple(item.nodeid for item in items)
        if (
            not actual
            or len(actual) > self.max_cases
            or len(set(actual)) != len(actual)
            or any(
                not any(self._matches(node, expected) for expected in self.nodes) for node in actual
            )
            or any(
                not any(self._matches(node, expected) for node in actual) for expected in self.nodes
            )
        ):
            raise pytest.UsageError("collection exceeds approved bounds or exact selections")

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.skipped = self.skipped or report.skipped


def _bind_mysql(config: _ConnectionConfig) -> None:
    import pymysql

    original: Callable[..., Connection] = pymysql.connect

    def connect(*args: object, **kwargs: object) -> Connection:
        if (
            args
            or any(
                kwargs.get(key) != expected
                for key, expected in (
                    ("host", "ase-verify.invalid"),
                    ("user", config.user),
                    ("password", config.password),
                    ("database", config.database),
                )
            )
            or kwargs.get("port", 3306) != 3306
            or kwargs.get("unix_socket") is not None
        ):
            raise pymysql.OperationalError("unapproved MySQL destination")
        return original(**{**kwargs, "unix_socket": config.socket})

    # The only compatibility shim is this explicit PyMySQL entry point. Direct
    # socket/Connection bypasses still face the independently enforced OS policy.
    pymysql.connect = connect  # type: ignore[assignment]
    os.environ["ASE_TEST_MYSQL_DSN"] = (
        f"mysql://{config.user}:{config.password}@ase-verify.invalid:3306/{config.database}"
    )


def main(arguments: list[str]) -> int:
    try:
        if len(arguments) != 5 or arguments[-1] != "256":
            raise ValueError("invalid fixed runner arguments")
        dependencies, source, scratch, connection = map(Path, arguments[:4])
        for directory in (dependencies, source, scratch):
            if not directory.is_absolute() or directory.resolve(strict=True) != directory:
                raise ValueError("runner paths must be canonical absolute paths")
        config = _ConnectionConfig.read(connection, source)
    except (OSError, ValueError, TypeError):
        # Never echo config values (or JSON decoding input) into output.
        print("ASE verification runner rejected its private config", file=sys.stderr)
        return 4

    # -S prevents .pth execution, including editable installs pointing to a
    # different checkout. Import trusted dependencies before candidate source.
    sys.path.append(str(dependencies))
    os.environ.pop("PYTEST_ADDOPTS", None)
    os.environ.pop("PYTEST_PLUGINS", None)
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ["TMPDIR"] = str(scratch)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    import pytest

    _bind_mysql(config)
    sys.path[:0] = [str(source / "src"), str(source)]
    os.chdir(source)
    guard = _SelectionGuard(config.node_ids, 256)
    result = pytest.main(
        [
            "-q",
            "-rA",
            "-p",
            "no:cacheprovider",
            "--override-ini=addopts=",
            f"--rootdir={source}",
            f"--confcutdir={source}",
            f"--basetemp={scratch / 'pytest'}",
            f"--ignore={source / '.git'}",
            *(f"--ignore={source / path}" for path in config.denied_paths),
            *config.node_ids,
        ],
        plugins=[guard],
    )
    # Exit zero must not hide a skipped prerequisite. It still isn't QA PASS.
    return int(result) if result else (1 if guard.skipped else 0)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
