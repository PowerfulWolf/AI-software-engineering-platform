"""Production composition and executable entry point for the local Web Console."""

from __future__ import annotations

import os
from collections.abc import Mapping

import uvicorn
from fastapi import FastAPI

from ai_software_engineer.config import ProductionConfig, ProductionConfigError
from ai_software_engineer.project_manager.production_host import OrganizationTeamHost
from ai_software_engineer.store import StoreError
from ai_software_engineer.team_view.reader import ProductionTeamReader
from ai_software_engineer.work_queue import QueueError

from .core import ProjectConsole
from .project_manager import ProjectManagerConsoleAdapter
from .store import FileConsoleOperationStore
from .transport import create_console_app


def production_console_app(
    environment: Mapping[str, str] | None = None,
    *,
    port: int = 8765,
) -> FastAPI:
    _validate_port(port)
    variables = dict(environment if environment is not None else os.environ)
    config = ProductionConfig.from_environment(variables)
    host = OrganizationTeamHost(config=config, environment=variables)
    store = FileConsoleOperationStore(
        host.company_workspace.requests_root / "_console_operations",
        company_id=config.company_id,
    )
    console = ProjectConsole(
        store=store,
        executor=ProjectManagerConsoleAdapter(host),
    )
    reader = ProductionTeamReader(config, variables)
    return create_console_app(console, reader, company_id=config.company_id, port=port)


def main() -> None:
    try:
        raw_port = os.environ.get("ASE_CONSOLE_PORT", "8765")
        port = int(raw_port)
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
