"""Bounded read-only Team comparison; print only counts, timing and digests.

Run sequentially in fresh processes. No Host, write endpoint, SQL initialization,
claim, approval or service restart is constructed. A real model may be running,
so snapshot wire digests can differ due to queue heartbeats and lease liveness.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import importlib.util
import json
import os
import signal
import subprocess
import sys
from collections.abc import Callable, Sequence
from importlib.machinery import ModuleSpec
from pathlib import Path
from time import perf_counter
from types import ModuleType
from typing import cast
from unittest.mock import patch


class _Sources(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, revision: str, repository: Path) -> None:
        self.sources: dict[str, tuple[Path, bytes]] = {}
        for suffix in ("reader", "engineering_history", "queue_reader"):
            name = "ai_software_engineer.team_view." + suffix
            path = Path("src") / Path(name.replace(".", "/") + ".py")
            body = subprocess.run(
                ["git", "show", f"{revision}:{path.as_posix()}"],
                cwd=repository,
                capture_output=True,
                check=True,
                timeout=10,
            ).stdout
            self.sources[name] = repository / path, body

    def find_spec(
        self, fullname: str, path: Sequence[str] | None = None, target: ModuleType | None = None
    ) -> ModuleSpec | None:
        return importlib.util.spec_from_loader(fullname, self) if fullname in self.sources else None

    def create_module(self, spec: ModuleSpec) -> None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        path, body = self.sources[module.__name__]
        module.__file__ = str(path)
        exec(compile(body, str(path), "exec"), module.__dict__)


def _inventory(project: Path) -> tuple[int, int, str]:
    paths = set((project / "requirements").glob("delivery_multi_*/*.json"))
    paths.update((project / "repositories").glob("repository_*/state/execution-baselines/*/*.json"))
    digest = hashlib.sha256()
    size = 0
    for path in sorted(paths):
        if any(item.is_symlink() for item in (path, *path.parents)):
            raise ValueError("probe cannot follow a source symlink")
        body = path.read_bytes()
        digest.update(path.relative_to(project).as_posix().encode())
        digest.update(hashlib.sha256(body).digest())
        size += len(body)
    return len(paths), size, digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--revision")
    parser.add_argument("--deadline", type=int, default=25, choices=range(1, 26))
    options = parser.parse_args()
    repository = Path(__file__).resolve().parents[3]
    if options.revision:
        sys.meta_path.insert(0, _Sources(options.revision, repository))

    from pymysql.cursors import Cursor
    from starlette.responses import JSONResponse

    from ai_software_engineer.config import LocalRuntimeEnvironmentStore, ProductionConfig
    from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
    from ai_software_engineer.team_view.reader import ProductionTeamReader

    config = ProductionConfig.from_file(options.config)
    environment = dict(os.environ)
    environment.update(LocalRuntimeEnvironmentStore(options.config.parent / "runtime.env").load())
    project = Path(config.platform_root) / "projects" / options.project
    before = _inventory(project)
    timings: dict[str, tuple[int, float]] = {}
    keys: dict[str, int] = {}
    queries: list[float] = []
    started = perf_counter()

    def report(status: str, **values: object) -> None:
        print(
            json.dumps(
                {
                    "revision": options.revision or "working-tree",
                    "status": status,
                    "elapsed_seconds": round(perf_counter() - started, 4),
                    "baseline_methods": {
                        name: {"calls": count, "seconds": round(seconds, 4)}
                        for name, (count, seconds) in timings.items()
                    },
                    "baseline_root_task_counts_by_sha256": keys,
                    "sql_calls": len(queries),
                    "sql_seconds": round(sum(queries), 4),
                    **values,
                },
                sort_keys=True,
            ),
            flush=True,
        )

    def deadline(signum: int, frame: object) -> None:
        report("deadline")
        os._exit(124)

    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(options.deadline)

    def instrument(name: str) -> None:
        original = getattr(FileExecutionBaselineStore, name)

        def read(store: FileExecutionBaselineStore, *args: object, **kwargs: object) -> object:
            count, seconds = timings.get(name, (0, 0.0))
            if name == "bindings_for_task":
                identity = hashlib.sha256(
                    (str(store.root) + "\0" + str(args[0])).encode()
                ).hexdigest()
                keys[identity] = keys.get(identity, 0) + 1
            entered = perf_counter()
            try:
                return cast(object, original(store, *args, **kwargs))
            finally:
                timings[name] = count + 1, seconds + perf_counter() - entered

        setattr(FileExecutionBaselineStore, name, read)

    for name in ("bindings_for_task", "plan", "start", "required_context"):
        instrument(name)
    original_execute = cast(Callable[[Cursor, str | bytes, object], int], Cursor.execute)

    def execute(cursor: Cursor, query: str | bytes, args: object = None) -> int:
        statement = query.decode() if isinstance(query, bytes) else query
        if not (
            statement.lstrip().upper().startswith("SELECT ")
            or statement
            in {
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ",
                "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY",
            }
        ):
            raise ValueError("probe rejected a non-read SQL statement")
        entered = perf_counter()
        try:
            return original_execute(cursor, query, args)
        finally:
            queries.append(perf_counter() - entered)

    entered = perf_counter()
    with patch.object(Cursor, "execute", execute):
        snapshot = ProductionTeamReader(config, environment).snapshot(options.project)
    snapshot_seconds = perf_counter() - entered
    entered = perf_counter()
    wire = snapshot.to_wire()
    wire_seconds = perf_counter() - entered
    wire["as_of"] = None
    wire_digest = hashlib.sha256(
        json.dumps(wire, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    entered = perf_counter()
    response = JSONResponse(wire)
    render_seconds = perf_counter() - entered
    after = _inventory(project)
    signal.alarm(0)
    report(
        "complete",
        snapshot_seconds=round(snapshot_seconds, 4),
        wire_seconds=round(wire_seconds, 4),
        render_seconds=round(render_seconds, 4),
        requests=len(snapshot.requests),
        tasks=len(snapshot.tasks),
        response_bytes=len(response.body),
        wire_sha256_excluding_as_of=wire_digest,
        sealed_inventory_records=before[0],
        sealed_inventory_bytes=before[1],
        sealed_inventory_sha256=before[2],
        sealed_inventory_unchanged=before == after,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never include provider, validation, source or configuration payloads.
        print(json.dumps({"status": "error", "error_type": type(error).__name__}), flush=True)
        raise SystemExit(1) from None
