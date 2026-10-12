"""New current/detail GETs keep exact reading scope and the original worker limit."""

from __future__ import annotations

import asyncio
import gc
import weakref
from datetime import UTC, datetime
from threading import Event

import httpx
import pytest

from ai_software_engineer.team_view.models import RequestView, ScopeView, TeamSnapshot
from ai_software_engineer.team_view.read_models import (
    RequestDetail,
    RequestSummary,
    TeamDetail,
    TeamDetailNotFound,
    TeamDetailQuery,
    TeamDetailStale,
    TeamSummary,
)
from ai_software_engineer.web_console import create_console_app
from tests.team_view.test_read_models import source
from tests.web_console.test_transport import _Console, _Reader


class _ReaderWithDetails:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.entered = Event()
        self.release = Event()
        self.hold = False
        self.failure: type[Exception] | None = None
        self.results: list[weakref.ReferenceType[TeamSummary | RequestDetail]] = []
        self.request = RequestView(
            id="delivery_multi_reads",
            project_id="project_reads",
            title="Complete reading",
            stage="DISCUSSING",
            scopes=(ScopeView(root="/workspace/source", selected_paths=(".",)),),
            next_action="继续讨论",
            checkpoint_sha256="a" * 64,
        )

    def snapshot(self, project_id: str | None = None) -> TeamSnapshot:
        self.calls.append(("full", project_id))
        return TeamSnapshot(
            as_of=datetime.now(UTC),
            team_id="team_reads",
            team_name="Reads",
            requests=(self.request,),
        )

    def summary(self, project_id: str | None = None) -> TeamSummary:
        self.calls.append(("summary", project_id))
        self.entered.set()
        if self.hold:
            assert self.release.wait(5)
        result = TeamSummary(
            as_of=datetime.now(UTC),
            team_id="team_reads",
            team_name="Reads",
            selected_project_id="project_reads",
            requests=(
                RequestSummary(
                    **self.request.model_dump(exclude={"dialogue", "documents"}),
                    detail_source=source(),
                ),
            ),
        )
        self.results.append(weakref.ref(result))
        return result

    def detail(self, query: TeamDetailQuery) -> TeamDetail:
        self.calls.append(query)
        self.entered.set()
        if self.hold:
            assert self.release.wait(5)
        if self.failure is not None:
            raise self.failure("private read failure")
        result = RequestDetail(as_of=datetime.now(UTC), scope=query.source(), resource=self.request)
        self.results.append(weakref.ref(result))
        return result


def _parameters(query: TeamDetailQuery) -> dict[str, str]:
    return {key: str(value) for key, value in query.to_wire().items() if value is not None}


def test_new_capability_and_exact_summary_detail_gets_preserve_legacy_full() -> None:
    async def exercise() -> None:
        reader = _ReaderWithDetails()
        app = create_console_app(_Console(), reader, team_id="team_reads")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8765"
        ) as client:
            capability = (await client.get("/api/v1/console")).json()
            assert capability["team_read_contract_version"] == "v0.1"
            summary = await client.get("/api/v1/team-summary?project_id=project_reads")
            assert summary.status_code == 200
            assert "documents" not in summary.json()["requests"][0]
            query = TeamDetailQuery.from_source(source())
            detail = await client.get("/api/v1/team-details", params=_parameters(query))
            assert detail.status_code == 200
            assert RequestDetail.model_validate(detail.json()).resource == reader.request
            assert reader.calls == [("summary", "project_reads"), query]
            full = await client.get("/api/v1/team")
            assert full.json()["schema_version"] == "v0.2"
            assert "documents" in full.json()["requests"][0]

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", [TeamDetailNotFound, TeamDetailStale, RuntimeError])
def test_detail_failures_have_safe_chinese_status_without_partial_body(
    failure: type[Exception],
) -> None:
    async def exercise() -> None:
        reader = _ReaderWithDetails()
        reader.failure = failure
        app = create_console_app(_Console(), reader, team_id="team_reads")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8765"
        ) as client:
            response = await client.get(
                "/api/v1/team-details", params=_parameters(TeamDetailQuery.from_source(source()))
            )
            expected = (
                404 if failure is TeamDetailNotFound else 409 if failure is TeamDetailStale else 503
            )
            assert response.status_code == expected
            assert "private" not in response.text and "resource" not in response.json()
            assert any("\u4e00" <= character <= "\u9fff" for character in response.text)

    asyncio.run(exercise())


def test_query_rejects_unknown_duplicate_and_path_inputs_before_reading() -> None:
    async def exercise() -> None:
        reader = _ReaderWithDetails()
        app = create_console_app(_Console(), reader, team_id="team_reads")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8765"
        ) as client:
            valid = list(_parameters(TeamDetailQuery.from_source(source())).items())
            for parameters in (
                [*valid, ("path", "/etc/passwd")],
                [*valid, ("id", "delivery_foreign")],
                [(key, "../outside" if key == "id" else value) for key, value in valid],
            ):
                response = await client.get(
                    "/api/v1/team-details", params=httpx.QueryParams(tuple(parameters))
                )
                assert response.status_code == 409
            assert not reader.calls

    asyncio.run(exercise())


def test_legacy_reader_has_no_capability_and_cannot_fake_empty_current_reads() -> None:
    async def exercise() -> None:
        app = create_console_app(_Console(), _Reader(), team_id="team_reads")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8765"
        ) as client:
            assert "team_read_contract_version" not in (await client.get("/api/v1/console")).json()
            assert (await client.get("/api/v1/team-summary")).status_code == 404

    asyncio.run(exercise())


@pytest.mark.parametrize("mode", ["summary", "detail"])
@pytest.mark.parametrize("cancel", [False, True])
def test_all_team_read_modes_share_worker_and_join_only_complete_query(
    mode: str, cancel: bool
) -> None:
    async def exercise() -> None:
        reader = _ReaderWithDetails()
        reader.hold = True
        app = create_console_app(_Console(), reader, team_id="team_reads")
        query = _parameters(TeamDetailQuery.from_source(source()))
        path = "/api/v1/team-summary" if mode == "summary" else "/api/v1/team-details"
        parameters = {"project_id": "project_reads"} if mode == "summary" else query
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8765"
        ) as client:
            owner = asyncio.create_task(client.get(path, params=parameters))
            assert await asyncio.to_thread(reader.entered.wait, 2)
            joined = asyncio.create_task(client.get(path, params=parameters))
            # The unchanged full mode and foreign mode/resource/source may not
            # borrow a current worker, even when Project matches exactly.
            other = "/api/v1/team-details" if mode == "summary" else "/api/v1/team-summary"
            other_params = query if mode == "summary" else {"project_id": "project_reads"}
            assert (await client.get(other, params=other_params)).status_code == 503
            assert (await client.get("/api/v1/team?project_id=project_reads")).status_code == 503
            if mode == "detail":
                for changes in (
                    {"id": "delivery_multi_other", "request_id": "delivery_multi_other"},
                    {
                        "expected_requirement_checkpoint_sha256": "f" * 64,
                        "expected_resource_checkpoint_sha256": "f" * 64,
                    },
                ):
                    assert (await client.get(path, params={**query, **changes})).status_code == 503
            if cancel:
                owner.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await owner
                assert (await client.get(other, params=other_params)).status_code == 503
            assert len(reader.calls) == 1
            reader.release.set()
            response = await asyncio.wait_for(joined, 2)
            assert response.status_code == 200
            if not cancel:
                assert (await owner).content == response.content
            reader.hold = False
            assert (await client.get(path, params=parameters)).status_code == 200
            assert len(reader.calls) == 2
            gc.collect()
            assert all(reference() is None for reference in reader.results)

    asyncio.run(exercise())
