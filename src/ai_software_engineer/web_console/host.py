"""Production composition and executable entry point for the local Web Console."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from ai_software_engineer.config import ProductionConfig, ProductionConfigError
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.store import StoreError
from ai_software_engineer.team_view.models import ProjectView, TeamSnapshot
from ai_software_engineer.team_view.reader import ProductionTeamReader
from ai_software_engineer.team_workspace import discover_team_workspaces
from ai_software_engineer.work_queue import QueueError

from .administration import LocalConsoleAdministration
from .core import ConsoleCommandRejected, ProjectConsole
from .manager import ManagerConsoleAdapter
from .models import ConsoleIntent, ConsoleOperation
from .store import ConsoleOperationNotFound, FileConsoleOperationStore
from .transport import ConsoleApplication, TeamReader, create_console_app


class _SetupConsole:
    """Keep the configuration surface online while delivery dependencies are absent."""

    def start(self) -> None:
        return None

    def close(self, *, timeout: float = 5.0) -> None:
        return None

    def submit(self, intent: ConsoleIntent, *, idempotency_key: str) -> ConsoleOperation:
        raise ConsoleCommandRejected(
            "SETUP_REQUIRED",
            "Complete runtime settings and restart the Web Console before delivery.",
        )

    def get(self, operation_id: str) -> ConsoleOperation:
        raise ConsoleOperationNotFound("console operation not found")

    def list_operations(self) -> tuple[ConsoleOperation, ...]:
        return ()


class _SetupTeamReader:
    """Expose safe Team/Project identity without requiring MySQL."""

    def __init__(self, config: ProductionConfig) -> None:
        self._config = config

    def snapshot(self, project_id: str | None = None) -> TeamSnapshot:
        projects: tuple[ProjectView, ...] = ()
        try:
            teams = discover_team_workspaces(self._config.platform_root)
            team = next(item for item in teams if item.manifest.team_id == self._config.team_id)
            projects = tuple(
                ProjectView(
                    id=item.manifest.project_id,
                    name=item.manifest.name,
                    repository_count=len(item.repository_registry().discover()),
                    requirement_count=sum(
                        1
                        for path in item.requirements_root.iterdir()
                        if path.is_dir() and not path.is_symlink()
                    ),
                )
                for item in team.project_registry().discover()
            )
        except (OSError, StopIteration, ValueError):
            projects = ()
        selected = project_id or self._config.default_project_id
        if selected is not None and not any(item.id == selected for item in projects):
            selected = None
        return TeamSnapshot(
            as_of=datetime.now(UTC),
            team_id=self._config.team_id,
            team_name=self._config.team_name,
            selected_project_id=selected,
            projects=projects,
        )


def _load_console_config(environment: Mapping[str, str]) -> tuple[ProductionConfig, Path]:
    config_path = ProductionConfig.path_from_environment(environment).expanduser().absolute()
    config = (
        ProductionConfig.from_file(config_path)
        if config_path.exists() or config_path.is_symlink()
        else ProductionConfig.default()
    )
    return config, config_path


def production_console_app(
    environment: Mapping[str, str] | None = None,
    *,
    port: int | None = None,
) -> FastAPI:
    variables = dict(environment if environment is not None else os.environ)
    config, config_path = _load_console_config(variables)
    selected_port = config.console_port if port is None else port
    _validate_port(selected_port)
    console: ConsoleApplication
    reader: TeamReader
    delivery_runtime_ready = True
    try:
        # Avoid TeamHost's writer boundary when first-run delivery prerequisites are absent.
        config.require_mysql_dsn(variables)
        host = TeamHost(config=config, environment=variables)
        store = FileConsoleOperationStore(
            host.team_workspace.directory("work-items") / "console-operations",
            team_id=config.team_id,
        )
        console = ProjectConsole(
            store=store,
            executor=ManagerConsoleAdapter(host),
        )
        reader = ProductionTeamReader(config, variables)
    except (OSError, ProductionConfigError, QueueError, StoreError, ValueError):
        delivery_runtime_ready = False
        console = _SetupConsole()
        reader = _SetupTeamReader(config)
    administration = LocalConsoleAdministration(
        runtime_config=config,
        config_path=config_path,
        environment=variables,
        delivery_runtime_ready=delivery_runtime_ready,
    )
    return create_console_app(
        console,
        reader,
        team_id=config.team_id,
        port=selected_port,
        administration=administration,
        delivery_ready=delivery_runtime_ready,
    )


def main() -> None:
    try:
        config, _ = _load_console_config(os.environ)
        raw_port = os.environ.get("ASE_CONSOLE_PORT")
        port = int(raw_port) if raw_port is not None else config.console_port
        _validate_port(port)
        app = production_console_app(port=port)
    except (OSError, ProductionConfigError, QueueError, StoreError, ValueError) as error:
        summary = str(error).strip() or "cannot start the local Web Console"
        raise SystemExit(f"error: {summary}") from None
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        access_log=False,
        server_header=False,
    )


def _validate_port(port: int) -> None:
    if isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("ASE_CONSOLE_PORT must be between 1 and 65535")


__all__ = ["main", "production_console_app"]
