"""Production composition and executable entry point for the local Web Console."""

from __future__ import annotations

import os
from collections.abc import Mapping

import uvicorn
from fastapi import FastAPI

from ai_software_engineer.config import ProductionConfig, ProductionConfigError
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.store import StoreError
from ai_software_engineer.team_view.reader import ProductionTeamReader
from ai_software_engineer.work_queue import QueueError

from .administration import LocalConsoleAdministration
from .core import ProjectConsole
from .manager import ManagerConsoleAdapter
from .store import FileConsoleOperationStore
from .transport import create_console_app


def production_console_app(
    environment: Mapping[str, str] | None = None,
    *,
    port: int | None = None,
) -> FastAPI:
    variables = dict(environment if environment is not None else os.environ)
    config = ProductionConfig.from_environment(variables)
    selected_port = config.console_port if port is None else port
    _validate_port(selected_port)
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
    administration = LocalConsoleAdministration(
        runtime_config=config,
        config_path=ProductionConfig.path_from_environment(variables),
        environment=variables,
    )
    return create_console_app(
        console,
        reader,
        team_id=config.team_id,
        port=selected_port,
        administration=administration,
    )


def main() -> None:
    try:
        config = ProductionConfig.from_environment(os.environ)
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
