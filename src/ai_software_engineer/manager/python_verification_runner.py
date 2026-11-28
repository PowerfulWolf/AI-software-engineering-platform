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

# This standalone, hash-bound file owns the limit; platform code imports it here.
# The isolated interpreter must not import the platform before trusted dependencies.
MAX_PYTEST_SELECTIONS = 64

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
            or not 1 <= len(nodes) <= MAX_PYTEST_SELECTIONS
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
        self.counts = [[index, 0, 0, 0, 0, 0, 0] for index in range(len(nodes))]
        self.errors: list[list[str | int | None]] = []
        self.omitted_errors = 0
        self.collection_errors = 0
        self.report_overflow = False

    def _index(self, actual: str) -> int | None:
        return next((i for i, node in enumerate(self.nodes) if self._matches(actual, node)), None)

    def _error(self, index: int, phase: str, report: object) -> None:
        if len(self.errors) >= 16:
            self.omitted_errors += 1
            return
        # Only known class names and numeric codes are retained. Exception text,
        # paths, argv and repr can contain partial credentials; never echo them.
        crash = getattr(getattr(report, "longrepr", None), "reprcrash", None)
        message = getattr(crash, "message", "")
        if not isinstance(message, str):
            message = ""
        match = re.match(
            r"^(?:[A-Za-z_][A-Za-z0-9_]*\.)*"
            r"(AssertionError|PermissionError|FileNotFoundError|OperationalError|"
            r"ProgrammingError|IntegrityError|CalledProcessError|TimeoutExpired|"
            r"ValueError|TypeError|KeyError|RuntimeError|ImportError|ModuleNotFoundError)"
            r"(?=:|$)",
            message,
        )
        category = match.group(1) if match else "UNKNOWN"
        numeric = None
        if match and category in {"OperationalError", "ProgrammingError", "IntegrityError"}:
            code = re.match(r":\s*\((\d{1,5}),", message[match.end() : match.end() + 32])
            if code:
                numeric = int(code.group(1))
        elif match and category in {"PermissionError", "FileNotFoundError"}:
            code = re.match(r":\s*\[Errno (\d{1,5})\]", message[match.end() : match.end() + 32])
            if code:
                numeric = int(code.group(1))
        # Source-defined class name and source/test frames are attached later by
        # pytest_exception_interact, from the live exception rather than its text.
        self.errors.append([index, phase, category, numeric, None, None])

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
        for node in actual:
            index = self._index(node)
            assert index is not None
            self.counts[index][1] += 1

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.skipped = self.skipped or report.skipped
        index = self._index(report.nodeid)
        if index is None or report.when not in {"setup", "call", "teardown"}:
            self.report_overflow = True
            return
        column = (
            4
            if report.skipped
            else 2
            if report.passed and report.when == "call"
            else 3
            if report.failed and report.when == "call"
            else 5
            if report.failed and report.when == "setup"
            else 6
            if report.failed and report.when == "teardown"
            else None
        )
        if column is not None:
            self.counts[index][column] += 1
            if self.counts[index][column] > self.max_cases:
                self.counts[index][column] = self.max_cases
                self.report_overflow = True
        if report.failed:
            self._error(index, report.when, report)

    def pytest_exception_interact(
        self, node: object, call: pytest.CallInfo[object], report: object
    ) -> None:
        """Enrich the just-recorded sample with static source facts only.

        The candidate tree is mounted read-only, so a class name that literally appears
        as a class statement in its defining source file, and repo-relative frame
        positions, cannot carry runtime credentials. Messages are still never read.
        """
        del node
        excinfo = call.excinfo
        if excinfo is None or not self.errors:
            return
        sample = self.errors[-1]
        phase = getattr(report, "when", None) or "collection"
        if sample[1] != phase or sample[4] is not None or sample[5] is not None:
            return
        if sample[2] == "UNKNOWN":
            sample[2] = _source_class_name(excinfo.type)
        test_frame = source_frame = None
        for entry in excinfo.traceback:
            position = _source_position(Path(str(entry.path)), entry.lineno + 1)
            if position is None:
                continue
            if position.startswith("tests/"):
                test_frame = position
            else:
                source_frame = position
        sample[4], sample[5] = test_frame, source_frame

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            self.collection_errors += 1
            self._error(-1, "collection", report)

    def summary(self, exit_code: int) -> str:
        payload = {
            "version": 2,
            "error_columns": [
                "selector",
                "phase",
                "exception",
                "code",
                "test_frame",
                "source_frame",
            ],
            "pytest_exit": exit_code,
            "columns": [
                "selector",
                "collected",
                "passed",
                "failed",
                "skipped",
                "setup_error",
                "teardown_error",
            ],
            "counts": self.counts,
            "errors": self.errors,
            "omitted_errors": self.omitted_errors,
            "collection_errors": self.collection_errors,
            "report_overflow": self.report_overflow,
        }
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        # Frame positions are the optional part: drop them from the newest samples first.
        for sample in reversed(self.errors):
            if len(encoded.encode()) <= 3000:
                break
            sample[4] = sample[5] = None
            encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        if len(encoded.encode()) > 3000:
            raise ValueError("fixed pytest summary exceeds limit")
        return "ASE_PYTEST_SUMMARY=" + encoded


_SOURCE_POSITION = re.compile(
    r"^(?:src|tests)/(?:[A-Za-z0-9_][A-Za-z0-9_.-]*/)*[A-Za-z0-9_.-]+\.py$"
)
_CLASS_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _source_position(path: Path, line: int) -> str | None:
    """Repo-relative `src/` or `tests/` position of a frame, else None."""
    try:
        relative = path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except (OSError, ValueError):
        return None
    if not _SOURCE_POSITION.match(relative) or not 0 < line < 1_000_000:
        return None
    return f"{relative}:{line}"


def _source_class_name(error_type: type[BaseException]) -> str:
    """A class declared verbatim in a read-only candidate source file, else UNKNOWN."""
    name = getattr(error_type, "__name__", "")
    module = sys.modules.get(getattr(error_type, "__module__", "") or "")
    filename = getattr(module, "__file__", None)
    if not isinstance(name, str) or not _CLASS_NAME.match(name) or not isinstance(filename, str):
        return "UNKNOWN"
    if _source_position(Path(filename), 1) is None:
        return "UNKNOWN"
    try:
        text = Path(filename).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return "UNKNOWN"
    declared = re.search(rf"^[ \t]*class[ \t]+{re.escape(name)}[ \t]*[(:]", text, re.MULTILINE)
    return name if declared else "UNKNOWN"


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
    if sys.platform == "darwin":
        # Candidate code may still run the /usr/bin xcrun shims (os.defpath git).
        # Their lookup cache cannot be written in the sandbox's default places, so
        # every call would re-run xcodebuild (seconds each); keep it in scratch.
        os.environ["xcrun_db"] = str(scratch / "xcrun_db")  # noqa: SIM112 (xcrun reads it lower-case)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    import pytest

    _bind_mysql(config)
    sys.path[:0] = [str(source / "src"), str(source)]
    os.chdir(source)
    guard = _SelectionGuard(config.node_ids, 256)
    result = pytest.main(
        [
            "-q",
            "-r",
            "",
            "--tb=no",
            "--no-summary",
            "--show-capture=no",
            "--color=no",
            "--disable-warnings",
            "-p",
            "no:cacheprovider",
            "--override-ini=addopts=",
            "--override-ini=log_cli=false",
            "--override-ini=verbosity_test_cases=-1",
            f"--rootdir={source}",
            f"--confcutdir={source}",
            f"--basetemp={scratch / 'pytest'}",
            f"--ignore={source / '.git'}",
            *(f"--ignore={source / path}" for path in config.denied_paths),
            *config.node_ids,
        ],
        plugins=[guard],
    )
    print(guard.summary(int(result)))
    # Exit zero must not hide a skipped prerequisite. It still isn't QA PASS.
    return int(result) if result else (1 if guard.skipped or guard.report_overflow else 0)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
