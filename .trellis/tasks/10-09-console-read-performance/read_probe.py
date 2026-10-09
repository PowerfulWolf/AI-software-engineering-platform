"""Read-only, sequential performance probe; never construct a Host or claim work.

Run in a fresh process for each revision. Only count/hash/timing facts are printed;
the snapshot, credentials and complete source bodies never leave this process.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from importlib.machinery import ModuleSpec
from pathlib import Path
from time import perf_counter
from types import ModuleType
from typing import cast
from unittest.mock import patch


class _RevisionSources(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Load only the four repaired modules from a trusted local Git revision."""

    def __init__(self, revision: str, repository: Path) -> None:
        self.sources: dict[str, bytes] = {}
        self.paths: dict[str, Path] = {}
        for suffix in (
            "redaction",
            "team_view.engineering_history",
            "team_view.reader",
            "web_console.store",
        ):
            name = "ai_software_engineer." + suffix
            relative = "src/" + name.replace(".", "/") + ".py"
            self.sources[name] = subprocess.run(
                ["git", "show", f"{revision}:{relative}"],
                cwd=repository,
                check=True,
                capture_output=True,
                timeout=10,
            ).stdout
            self.paths[name] = repository / relative

    def find_spec(
        self, fullname: str, path: Sequence[str] | None = None, target: ModuleType | None = None
    ) -> ModuleSpec | None:
        if fullname in self.sources:
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec: ModuleSpec) -> None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        module.__file__ = str(self.paths[module.__name__])
        exec(compile(self.sources[module.__name__], module.__file__, "exec"), module.__dict__)


def _inventory(root: Path) -> tuple[int, int, str]:
    result = hashlib.sha256()
    count = size = 0
    for path in sorted(root.rglob("*.json")):
        if any(value.is_symlink() for value in (path, *path.parents)):
            raise ValueError("probe source contains a symlink")
        body = path.read_bytes()
        name = path.relative_to(root).as_posix().encode("utf-8")
        result.update(len(name).to_bytes(8, "big"))
        result.update(name)
        result.update(hashlib.sha256(body).digest())
        count += 1
        size += len(body)
    return count, size, result.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument(
        "--revision", help="Trusted baseline revision; omitted uses the current files"
    )
    options = parser.parse_args()
    repository = Path(__file__).resolve().parents[3]
    if options.revision:
        sys.meta_path.insert(0, _RevisionSources(options.revision, repository))

    from pymysql.cursors import Cursor

    from ai_software_engineer import redaction

    scans = [0]
    function_name = (
        "_inspect_source" if hasattr(redaction, "_inspect_source") else "source_secret_occurrences"
    )
    original_scan = getattr(redaction, function_name)

    def inspect(content: str, *, source_path: str | None = None) -> object:
        scans[0] += 1
        return cast(object, original_scan(content, source_path=source_path))

    setattr(redaction, function_name, inspect)

    from ai_software_engineer.config import LocalRuntimeEnvironmentStore, ProductionConfig
    from ai_software_engineer.team_view.reader import ProductionTeamReader
    from ai_software_engineer.web_console.store import FileConsoleOperationStore

    config = ProductionConfig.from_file(options.config)
    platform = Path(config.platform_root)
    environment = dict(os.environ)
    environment.update(LocalRuntimeEnvironmentStore(options.config.parent / "runtime.env").load())
    before = _inventory(platform)
    queries: list[float] = []
    original_execute = cast(Callable[[Cursor, str | bytes, object], int], Cursor.execute)

    def execute(cursor: Cursor, query: str | bytes, args: object = None) -> int:
        started = perf_counter()
        try:
            return original_execute(cursor, query, args)
        finally:
            queries.append(perf_counter() - started)

    scans[0] = 0
    started = perf_counter()
    with patch.object(Cursor, "execute", execute):
        snapshot = ProductionTeamReader(config, environment).snapshot(options.project)
    wire = snapshot.to_wire()
    seconds = perf_counter() - started
    snapshot_scans = scans[0]
    wire["as_of"] = None
    wire_sha = hashlib.sha256(
        json.dumps(wire, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    # These two methods are pure reads. Constructor/claim/lock/publish are never called.
    store = object.__new__(FileConsoleOperationStore)
    store.root = platform / "team" / "work-items" / "console-operations"
    store.team_id = config.team_id
    store._idle_inventory_sha256 = None
    started = perf_counter()
    operations = store._list_current()
    replay_seconds = perf_counter() - started
    inventory_seconds = None
    if hasattr(store, "_operation_inventory_sha256"):
        started = perf_counter()
        store._operation_inventory_sha256()
        inventory_seconds = perf_counter() - started
    after = _inventory(platform)
    print(
        json.dumps(
            {
                "revision": options.revision or "working-tree",
                "snapshot_seconds": round(seconds, 4),
                "sql_calls": len(queries),
                "sql_seconds": round(sum(queries), 4),
                "snapshot_source_scans": snapshot_scans,
                "operation_source_scans": scans[0] - snapshot_scans,
                "requests": len(snapshot.requests),
                "tasks": len(snapshot.tasks),
                "wire_sha256_excluding_as_of": wire_sha,
                "operation_count": len(operations),
                "operation_replay_seconds": round(replay_seconds, 4),
                "idle_inventory_seconds": round(inventory_seconds, 4)
                if inventory_seconds
                else None,
                "source_json_count": before[0],
                "source_json_bytes": before[1],
                "source_inventory_sha256": before[2],
                "source_files_unchanged": before == after,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Diagnostic failures must not print provider/SQL/validation inputs.
        print("Read-only probe failed: " + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None
