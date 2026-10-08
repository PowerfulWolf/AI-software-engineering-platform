"""Production composition and executable entry point for the local Web Console."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import cast

import uvicorn
from fastapi import FastAPI

from ai_software_engineer.agents.model_diagnostics import ModelCallDiagnostic
from ai_software_engineer.config import ProductionConfig, ProductionConfigError
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.owned_processes import HostOwnedProcessRegistry
from ai_software_engineer.store import StoreError
from ai_software_engineer.team_view.models import ProjectView, TeamSnapshot
from ai_software_engineer.team_view.reader import ProductionTeamReader
from ai_software_engineer.team_workspace import discover_team_workspaces
from ai_software_engineer.work_queue import QueueError

from .administration import LocalConsoleAdministration
from .core import ConsoleCommandRejected, ProjectConsole
from .directories import NativeDirectoryChooser
from .lifecycle import ConfigurationApplyError, FileConfigurationLifecycle
from .manager import ManagerConsoleAdapter
from .models import ConsoleIntent, ConsoleOperation
from .service_lifecycle import (
    ConsoleShutdownCoordinator,
    ServiceInstance,
    ServiceLifecycleError,
    ServiceLifecycleStore,
    ServiceShutdownAction,
    ServiceShutdownRequest,
    ServiceShutdownResult,
    ServiceState,
)
from .shutdown import ShutdownResult, ShutdownState
from .store import ConsoleOperationNotFound, FileConsoleOperationStore
from .transport import ConsoleApplication, TeamReader, create_console_app


class _SetupConsole:
    """Keep the configuration surface online while delivery dependencies are absent."""

    def start(self) -> None:
        return None

    def begin_shutdown(self) -> ShutdownResult:
        return ShutdownResult(state=ShutdownState.DRAINING, safe_summary="设置服务正在安全收尾。")

    def await_shutdown(self, timeout: float) -> ShutdownResult:
        return ShutdownResult(state=ShutdownState.READY, safe_summary="设置服务已经安全收尾。")

    def cancel_shutdown(self, *, before_resume: Callable[[], None] | None = None) -> ShutdownResult:
        if before_resume is not None:
            before_resume()
        return ShutdownResult(state=ShutdownState.RUNNING, safe_summary="设置服务恢复接收操作。")

    def submit(self, intent: ConsoleIntent, *, idempotency_key: str) -> ConsoleOperation:
        raise ConsoleCommandRejected(
            "SETUP_REQUIRED",
            "Complete runtime settings and restart the Web Console before delivery.",
        )

    def get(self, operation_id: str) -> ConsoleOperation:
        raise ConsoleOperationNotFound("console operation not found")

    def list_operations(self) -> tuple[ConsoleOperation, ...]:
        return ()

    def model_calls(self, operation_id: str) -> tuple[ModelCallDiagnostic, ...]:
        raise ConsoleOperationNotFound("console operation not found")


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
    owned_processes = HostOwnedProcessRegistry()
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
            operation_scope=owned_processes.operation_scope,
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
    try:
        configuration_lifecycle = FileConfigurationLifecycle.from_environment(variables)
    except ConfigurationApplyError:
        configuration_lifecycle = None
    return create_console_app(
        console,
        reader,
        team_id=config.team_id,
        port=selected_port,
        administration=administration,
        configuration_lifecycle=configuration_lifecycle,
        configuration_port_override=(
            int(variables["ASE_CONSOLE_PORT"]) if "ASE_CONSOLE_PORT" in variables else None
        ),
        directory_chooser=NativeDirectoryChooser(),
        delivery_ready=delivery_runtime_ready,
        owned_processes=owned_processes,
    )


def main() -> None:
    try:
        config, _ = _load_console_config(os.environ)
        raw_port = os.environ.get("ASE_CONSOLE_PORT")
        port = int(raw_port) if raw_port is not None else config.console_port
        _validate_port(port)
        app = production_console_app(port=port)
        lifecycle = ServiceLifecycleStore.from_environment(os.environ)
    except ServiceLifecycleError:
        raise SystemExit("error: 服务生命周期记录不可用, 保留原服务并检查本机服务目录。") from None
    except (OSError, ProductionConfigError, QueueError, StoreError, ValueError) as error:
        summary = str(error).strip() or "cannot start the local Web Console"
        raise SystemExit(f"error: {summary}") from None
    server = ControlledConsoleServer(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            access_log=False,
            server_header=False,
        ),
        lifecycle=lifecycle,
        instance=ServiceInstance.new(pid=os.getpid(), at=datetime.now(UTC)),
        coordinator=cast(ConsoleShutdownCoordinator, app.state.console_shutdown),
    )
    try:
        server.run()
    except ServiceLifecycleError:
        raise SystemExit("error: 服务生命周期记录不可用, 无法安全启动 Console。") from None


_LOGGER = logging.getLogger(__name__)


class ControlledConsoleServer(uvicorn.Server):
    """Signals request a controlled drain; repeated signals cannot bypass completion."""

    def __init__(
        self,
        config: uvicorn.Config,
        *,
        lifecycle: ServiceLifecycleStore,
        instance: ServiceInstance,
        coordinator: ConsoleShutdownCoordinator,
        poll_seconds: float = 0.1,
    ) -> None:
        super().__init__(config)
        self._lifecycle = lifecycle
        self._instance = instance
        self._coordinator = coordinator
        self._poll_seconds = poll_seconds
        self._loop: asyncio.AbstractEventLoop | None = None
        self._draining: asyncio.Task[None] | None = None
        self._seen_request: str | None = None

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        # Persist identity before the lifespan starts any queue worker. A failure
        # here cannot strand a delivery behind an unpublished instance identity.
        self._instance = self._instance.with_state(ServiceState.STARTING, at=datetime.now(UTC))
        self._lifecycle.publish_instance(self._instance)
        failed_request = ServiceShutdownRequest.new(self._instance, at=datetime.now(UTC))
        observer = asyncio.create_task(self._watch_startup_drain(failed_request))
        try:
            await super().startup(sockets)
            if self.started:
                self._instance = self._instance.with_state(
                    ServiceState.RUNNING, at=datetime.now(UTC)
                )
                try:
                    self._lifecycle.publish_instance(self._instance)
                except ServiceLifecycleError:
                    # Work may already run. Do not tear down its daemon worker
                    # just because the running-identity write failed.
                    self._coordinator.begin_shutdown()
                    self._coordinator.record_failure()
                    _LOGGER.warning("服务启动状态未能保存, 保留本实例等待处理。")
                    self._seen_request = failed_request.request_id
                    with suppress(ServiceLifecycleError):
                        self._lifecycle.write_request(failed_request)
                        self._publish(failed_request, ServiceState.REFUSED)
            else:
                # Lifespan can fail after it started work. Its owned final drain
                # must complete before the failed instance is safe to replace.
                self._seen_request = failed_request.request_id
                self._lifecycle.write_request(failed_request)
                self._coordinator.begin_shutdown()
                result = await asyncio.to_thread(self._coordinator.await_shutdown, 0.0)
                self._publish(failed_request, ServiceState(result.state.value))
        finally:
            observer.cancel()
            with suppress(asyncio.CancelledError):
                await observer

    async def _watch_startup_drain(self, request: ServiceShutdownRequest) -> None:
        previous = ShutdownState.RUNNING
        while not self.started:
            state = self._coordinator.shutdown_status().state
            if state is not previous:
                self._seen_request = request.request_id
                try:
                    self._lifecycle.write_request(request)
                    self._publish(request, ServiceState(state.value))
                except ServiceLifecycleError:
                    self._coordinator.record_failure()
                previous = state
            await asyncio.sleep(self._poll_seconds)

    async def serve(self, sockets: list[socket.socket] | None = None) -> None:
        # Uvicorn normally binds after lifespan startup. Bind first, before any
        # queued Operation/index tick can start behind an unusable listener.
        bound: socket.socket | None = None
        if sockets is None:
            bound = self.config.bind_socket()
            sockets = [bound]
        self._loop = asyncio.get_running_loop()
        watcher = asyncio.create_task(self._watch_requests())
        try:
            await super().serve(sockets)
        finally:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
            if bound is not None:
                bound.close()

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        # No default should_exit/force_exit and no signal re-raise after graceful exit.
        # Deferring the work avoids re-entering a short admission lock from a signal.
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._signal_shutdown)

    def _signal_shutdown(self) -> None:
        if self.should_exit or (self._draining is not None and not self._draining.done()):
            return
        try:
            request = self._lifecycle.read_request()
            if (
                request is None
                or not request.matches(self._instance)
                or request.action is not ServiceShutdownAction.SHUTDOWN
                or request.request_id == self._seen_request
            ):
                request = ServiceShutdownRequest.new(self._instance, at=datetime.now(UTC))
                self._lifecycle.write_request(request)
            self._start_request(request)
        except ServiceLifecycleError:
            self._coordinator.begin_shutdown()
            self._coordinator.record_failure()
            _LOGGER.warning("服务停止请求未能安全保存, 保持原服务等待处理。")

    async def _watch_requests(self) -> None:
        while not self.should_exit:
            if self.started and (self._draining is None or self._draining.done()):
                try:
                    request = self._lifecycle.read_request()
                    if (
                        request is not None
                        and request.matches(self._instance)
                        and request.request_id != self._seen_request
                    ):
                        self._start_request(request)
                except ServiceLifecycleError:
                    # A malformed private request never authorizes exit or a signal.
                    pass
            await asyncio.sleep(self._poll_seconds)

    def _start_request(self, request: ServiceShutdownRequest) -> None:
        self._seen_request = request.request_id
        if request.action is ServiceShutdownAction.RESUME:
            try:
                result = self._coordinator.cancel_shutdown(
                    before_resume=lambda: self._publish(request, ServiceState.RUNNING)
                )
                if result.state is not ShutdownState.RUNNING:
                    self._publish(request, ServiceState.REFUSED)
            except Exception:
                self._coordinator.begin_shutdown()
                self._coordinator.record_failure()
            return
        result = self._coordinator.begin_shutdown()
        if result.state is ShutdownState.REFUSED:
            try:
                self._publish(request, ServiceState.REFUSED)
            except ServiceLifecycleError:
                self._coordinator.record_failure()
            return
        self._draining = asyncio.create_task(self._drain(request))

    def _publish(self, request: ServiceShutdownRequest, state: ServiceState) -> None:
        now = datetime.now(UTC)
        # READY is consumed only from this exact result. Publish it after instance state,
        # so any later durable failure cannot leave a consumable success marker.
        self._instance = self._instance.with_state(state, at=now)
        self._lifecycle.publish_instance(self._instance)
        self._lifecycle.write_result(
            ServiceShutdownResult.for_request(request, state=state, at=now)
        )

    async def _drain(self, request: ServiceShutdownRequest) -> None:
        try:
            self._publish(request, ServiceState.DRAINING)
            result = await asyncio.to_thread(
                self._coordinator.await_shutdown, request.timeout_seconds
            )
            state = ServiceState(result.state.value)
            self._publish(request, state)
            if state is ServiceState.READY:
                self.should_exit = True
        except Exception:
            self._coordinator.record_failure()
            _LOGGER.warning("服务安全收尾记录未能保存, 保留原服务, 不启动替代实例。")


def _validate_port(port: int) -> None:
    if isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("ASE_CONSOLE_PORT must be between 1 and 65535")


__all__ = ["main", "production_console_app"]
