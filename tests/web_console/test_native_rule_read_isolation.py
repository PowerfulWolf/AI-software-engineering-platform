"""Blocking native-rule Operation reads must not own the HTTP event loop."""

from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Event

import httpx
import pytest

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.web_console import (
    ConsoleOperation,
    LocalConsoleAdministration,
    create_console_app,
)
from ai_software_engineer.web_console.store import (
    ConsoleOperationConflict,
    ConsoleOperationNotFound,
)
from tests.web_console.test_transport import _Console, _Reader


class _HeldConsole(_Console):
    def __init__(self, failure: type[Exception]) -> None:
        super().__init__()
        self.failure = failure
        self.entered = Event()
        self.release = Event()
        self.finished = Event()
        self.read_ids: list[str] = []

    def get(self, operation_id: str) -> ConsoleOperation:
        self.read_ids.append(operation_id)
        self.entered.set()
        try:
            # Only a deadlock watchdog: correctness is the Event ordering below,
            # not a wall-clock performance threshold.
            assert self.release.wait(5), "Console read blocked its own HTTP release path"
            raise self.failure("private operation record")
        finally:
            self.finished.set()


def _administration(tmp_path: Path) -> LocalConsoleAdministration:
    return LocalConsoleAdministration(
        runtime_config=ProductionConfig(
            platform_root=str(tmp_path / "platform"),
            team_id="team_test",
            team_name="Fixture",
            model_routes=(
                ProviderRouteConfig(
                    provider="codex", model="fixture", kind=ModelProviderKind.CODEX_CLI
                ),
            ),
        ),
        config_path=tmp_path / "config.json",
        environment={},
    )


@pytest.mark.parametrize("failure", [ConsoleOperationNotFound, ConsoleOperationConflict, OSError])
def test_native_rule_operation_lookup_keeps_console_responsive(
    tmp_path: Path, failure: type[Exception]
) -> None:
    async def exercise() -> None:
        console = _HeldConsole(failure)
        app = create_console_app(
            console, _Reader(), team_id="team_test", administration=_administration(tmp_path)
        )
        # ASGITransport does not enter lifespan: no workers, Host or model runs.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8765"
        ) as client:
            operation_id = "operation_" + "a" * 32
            pending = asyncio.create_task(
                client.get(
                    f"/api/v1/operations/{operation_id}/native-rules", params={"path": "README.md"}
                )
            )
            try:
                assert await asyncio.to_thread(console.entered.wait, 2)
                heartbeat = await asyncio.wait_for(client.get("/api/v1/console"), 2)
                assert heartbeat.status_code == 200
                assert heartbeat.json()["team_id"] == "team_test"
                assert not console.release.is_set()
                assert not console.finished.is_set()
                assert not pending.done()
            finally:
                console.release.set()
                response = await asyncio.wait_for(pending, 2)
            assert console.finished.is_set()
            assert console.read_ids == [operation_id]
            assert response.status_code == 409
            assert response.json() == {
                "error": {
                    "code": "NATIVE_RULE_REVIEW_UNAVAILABLE",
                    "message": "无法核验完整项目规范变更, 未授予继续权限。请重新准备当前基线方案。",
                }
            }
            assert response.headers["cache-control"] == "no-store"
            assert not console.started
            assert console.store.list_current() == ()

    asyncio.run(exercise())


@pytest.mark.parametrize("administration_available", [False, True])
def test_native_rule_invalid_identity_or_unavailable_administration_never_reads(
    tmp_path: Path, administration_available: bool
) -> None:
    async def exercise() -> None:
        console = _HeldConsole(ConsoleOperationNotFound)
        app = create_console_app(
            console,
            _Reader(),
            team_id="team_test",
            administration=_administration(tmp_path) if administration_available else None,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8765"
        ) as client:
            response = await client.get(
                "/api/v1/operations/invalid/native-rules", params={"path": "README.md"}
            )
        assert response.status_code == (409 if administration_available else 404)
        assert response.json()["error"]["code"] == (
            "NATIVE_RULE_REVIEW_UNAVAILABLE" if administration_available else "NOT_AVAILABLE"
        )
        assert console.read_ids == []
        assert not console.started
        assert console.store.list_current() == ()

    asyncio.run(exercise())
