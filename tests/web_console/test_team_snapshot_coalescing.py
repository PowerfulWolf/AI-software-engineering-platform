from __future__ import annotations

import asyncio
import gc
import weakref
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import cast

import httpx
import pytest
from starlette.responses import JSONResponse, Response

from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.team_view.models import TeamReadError, TeamSnapshot
from ai_software_engineer.web_console import create_console_app, transport
from tests.web_console.test_transport import _Console


class _HeldReader:
    def __init__(self, failure: type[Exception] | None = None) -> None:
        self.entered = Event()
        self.release = Event()
        self.projects: list[str | None] = []
        self.failure = failure
        self.snapshots: list[weakref.ReferenceType[TeamSnapshot]] = []

    def snapshot(self, project_id: str | None = None) -> TeamSnapshot:
        self.projects.append(project_id)
        sequence = len(self.projects)
        if sequence == 1:
            self.entered.set()
            assert self.release.wait(5), "test did not release Team reader"
            if self.failure is not None:
                raise self.failure("private read failure")
        snapshot = TeamSnapshot(
            as_of=datetime(2026, 10, 11, tzinfo=UTC) + timedelta(seconds=sequence),
            team_id="team_test",
            team_name=f"Read {sequence}",
            selected_project_id=project_id,
        )
        self.snapshots.append(weakref.ref(snapshot))
        return snapshot


async def _until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


def _current(reads: transport._TeamSnapshotReads) -> transport._TeamReadFlight | None:
    return reads._active


def test_public_same_project_shares_one_worker_with_two_waiters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire_calls = render_calls = admitted = 0
    original_wire = TeamSnapshot.to_wire
    original_render = JSONResponse.render
    original_team = transport._team_snapshot

    def wire(snapshot: TeamSnapshot) -> WirePayload:
        nonlocal wire_calls
        wire_calls += 1
        return original_wire(snapshot)

    def render(response: JSONResponse, content: object) -> bytes:
        nonlocal render_calls
        if isinstance(content, dict) and "as_of" in content:
            render_calls += 1
        return original_render(response, content)

    async def counted(
        reader: transport.TeamReader,
        project_id: str | None,
        gate: transport._TeamSnapshotReads,
    ) -> Response:
        nonlocal admitted
        admitted += 1
        return await original_team(reader, project_id, gate)

    monkeypatch.setattr(TeamSnapshot, "to_wire", wire)
    monkeypatch.setattr(JSONResponse, "render", render)
    monkeypatch.setattr(transport, "_team_snapshot", counted)

    async def exercise() -> None:
        reader = _HeldReader()
        app = create_console_app(_Console(), reader, team_id="team_test")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8765"
        ) as client:
            owner = asyncio.create_task(client.get("/api/v1/team?project_id=project_one"))
            pending: list[asyncio.Task[httpx.Response]] = [owner]
            try:
                assert await asyncio.to_thread(reader.entered.wait, 2)
                pending.extend(
                    asyncio.create_task(client.get("/api/v1/team?project_id=project_one"))
                    for _ in range(2)
                )
                await _until(lambda: admitted == 3)
                busy = await asyncio.wait_for(client.get("/api/v1/team?project_id=project_one"), 2)
                assert busy.status_code == 503
                assert busy.json()["error"]["code"] == "TEAM_READ_IN_PROGRESS"
                for path in ("/api/v1/team?project_id=project_other", "/api/v1/team"):
                    assert (await asyncio.wait_for(client.get(path), 2)).status_code == 503
                assert (await client.get("/api/v1/console")).status_code == 200
                assert (
                    await client.get(
                        "/api/v1/team?project_id=project_one",
                        headers={"Origin": "https://untrusted.test"},
                    )
                ).status_code == 403
                assert reader.projects == ["project_one"]
            finally:
                reader.release.set()
                responses = await asyncio.wait_for(asyncio.gather(*pending), 2)
            assert [response.status_code for response in responses] == [200, 200, 200]
            assert len({response.content for response in responses}) == 1
            assert wire_calls == render_calls == 1
            assert all(response.headers["cache-control"] == "no-store" for response in responses)
            fresh = await client.get("/api/v1/team?project_id=project_one")
            assert fresh.json()["as_of"] != responses[0].json()["as_of"]
            assert reader.projects == ["project_one", "project_one"]

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", [None, TeamReadError, RuntimeError])
def test_shared_results_are_independent_and_release_snapshot(
    failure: type[Exception] | None,
) -> None:
    async def exercise() -> None:
        reads = transport._TeamSnapshotReads()
        reader = _HeldReader(failure)
        owner = asyncio.create_task(reads.response(reader, "project_one"))
        joined: asyncio.Task[Response] | None = None
        try:
            assert await asyncio.to_thread(reader.entered.wait, 2)
            joined = asyncio.create_task(reads.response(reader, "project_one"))
            await _until(lambda: reads._active is not None and reads._active.waiters == 1)
        finally:
            reader.release.set()
        assert joined is not None
        first, second = await asyncio.wait_for(asyncio.gather(owner, joined), 2)
        assert first is not second
        assert first.body is second.body
        first.headers["X-Caller"] = "original"
        assert "X-Caller" not in second.headers
        expected = 200 if failure is None else 503 if failure is TeamReadError else 500
        assert first.status_code == expected
        assert b"private" not in first.body
        assert reads._active is None
        gc.collect()
        assert all(reference() is None for reference in reader.snapshots)
        fresh = await reads.response(reader, "project_one")
        assert fresh.status_code == 200
        assert reader.projects == ["project_one", "project_one"]

    asyncio.run(exercise())


@pytest.mark.parametrize("cancel_master", [False, True])
def test_cancellation_before_worker_entry_never_runs_a_retired_flight(
    monkeypatch: pytest.MonkeyPatch, cancel_master: bool
) -> None:
    async def exercise() -> None:
        reads = transport._TeamSnapshotReads()
        reader = _HeldReader()
        queued, proceed = asyncio.Event(), asyncio.Event()
        original_pool = transport.run_in_threadpool
        delayed_worker: Callable[[], transport._RenderedTeamResponse] | None = None

        async def delayed[ResultT](
            function: Callable[..., ResultT], *arguments: object, **keywords: object
        ) -> ResultT:
            nonlocal delayed_worker
            delayed_worker = cast(
                Callable[[], transport._RenderedTeamResponse],
                lambda: function(*arguments, **keywords),
            )
            queued.set()
            await proceed.wait()
            return await original_pool(function, *arguments, **keywords)

        monkeypatch.setattr(transport, "run_in_threadpool", delayed)
        owner = asyncio.create_task(reads.response(reader, None))
        await asyncio.wait_for(queued.wait(), 2)
        assert reads._active is not None and reads._active.task is not None
        flight = reads._active
        assert flight.task is not None
        if cancel_master:
            flight.task.cancel()
        else:
            owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(owner, 2)
        assert not reader.projects
        if cancel_master:
            await _until(lambda: reads._active is None)
            assert delayed_worker is not None
            assert delayed_worker().status_code == 500
            assert not reader.projects
        else:
            assert reads._active is flight
            assert (await reads.response(reader, "project_other")).status_code == 503
        reader.release.set()
        proceed.set()
        await _until(lambda: reads._active is None)
        fresh = await reads.response(reader, None)
        assert fresh.status_code == 200
        assert reader.projects == ([None] if cancel_master else [None, None])

    asyncio.run(exercise())


def test_master_cancelled_before_coroutine_start_retires_its_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        reads, reader = transport._TeamSnapshotReads(), _HeldReader()
        loop = asyncio.get_running_loop()

        def cancel_new(
            coroutine: Coroutine[object, object, transport._RenderedTeamResponse],
        ) -> asyncio.Task[transport._RenderedTeamResponse]:
            task = loop.create_task(coroutine)
            task.cancel()
            return task

        with monkeypatch.context() as patch:
            patch.setattr(asyncio, "create_task", cancel_new)
            with pytest.raises(asyncio.CancelledError):
                await reads.response(reader, None)
            await _until(lambda: reads._active is None)
        assert not reader.projects
        reader.release.set()
        assert (await reads.response(reader, None)).status_code == 200
        assert reader.projects == [None]

    asyncio.run(exercise())


def test_cancelled_master_after_worker_entry_keeps_actual_worker_admission() -> None:
    async def exercise() -> None:
        reads, reader = transport._TeamSnapshotReads(), _HeldReader()
        owner = asyncio.create_task(reads.response(reader, "project_one"))
        try:
            assert await asyncio.to_thread(reader.entered.wait, 2)
            assert reads._active is not None and reads._active.task is not None
            flight = reads._active
            assert flight.task is not None
            flight.task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(owner, 2)
            assert reads._active is flight and flight.started and not flight.retired
            for project in ("project_one", "project_other", None):
                assert (await reads.response(reader, project)).status_code == 503
            assert reader.projects == ["project_one"]
        finally:
            reader.release.set()
            await _until(lambda: reads._active is None)
        assert (await reads.response(reader, "project_other")).status_code == 200
        assert reader.projects == ["project_one", "project_other"]

    asyncio.run(exercise())


@pytest.mark.parametrize("failure_at", ["task", "threadpool"])
def test_scheduling_failure_retires_exact_flight(
    monkeypatch: pytest.MonkeyPatch, failure_at: str
) -> None:
    async def exercise() -> None:
        reads = transport._TeamSnapshotReads()
        reader = _HeldReader()
        with monkeypatch.context() as patch:
            if failure_at == "task":

                def refuse_task(*arguments: object, **keywords: object) -> None:
                    raise RuntimeError("private task scheduler failure")

                patch.setattr(asyncio, "create_task", refuse_task)
            else:

                async def refuse_pool(*arguments: object, **keywords: object) -> None:
                    raise RuntimeError("private threadpool failure")

                patch.setattr(transport, "run_in_threadpool", refuse_pool)
            failed = await reads.response(reader, None)
            assert failed.status_code == 500 and b"private" not in failed.body
            assert reads._active is None and not reader.projects
        reader.release.set()
        assert (await reads.response(reader, None)).status_code == 200
        assert reader.projects == [None]

    asyncio.run(exercise())


def test_worker_completion_starts_fresh_read_before_old_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        class SecondHeldReader(_HeldReader):
            def __init__(self) -> None:
                super().__init__()
                self.second_entered, self.second_release = Event(), Event()

            def snapshot(self, project_id: str | None = None) -> TeamSnapshot:
                snapshot = super().snapshot(project_id)
                if len(self.projects) == 2:
                    self.second_entered.set()
                    assert self.second_release.wait(5)
                return snapshot

        reads = transport._TeamSnapshotReads()
        reader = SecondHeldReader()
        completed, notify = asyncio.Event(), asyncio.Event()
        original_pool = transport.run_in_threadpool
        calls = 0

        async def delayed_notification[ResultT](
            function: Callable[..., ResultT], *arguments: object, **keywords: object
        ) -> ResultT:
            nonlocal calls
            calls += 1
            first = calls == 1
            result = await original_pool(function, *arguments, **keywords)
            if first:
                completed.set()
                await notify.wait()
            return result

        monkeypatch.setattr(transport, "run_in_threadpool", delayed_notification)
        owner = asyncio.create_task(reads.response(reader, "project_one"))
        successor: asyncio.Task[Response] | None = None
        try:
            assert await asyncio.to_thread(reader.entered.wait, 2)
            assert reads._active is not None
            original = reads._active
            original_reference = weakref.ref(original)
            reader.release.set()
            await asyncio.wait_for(completed.wait(), 2)
            assert _current(reads) is None and not owner.done()
            successor = asyncio.create_task(reads.response(reader, "project_one"))
            assert await asyncio.to_thread(reader.second_entered.wait, 2)
            assert reads._active is not None and reads._active is not original
            current = reads._active
            notify.set()
            first = await asyncio.wait_for(owner, 2)
            await asyncio.sleep(0)
            assert reads._active is current
            assert (await reads.response(reader, "project_other")).status_code == 503
            del original
            gc.collect()
            assert original_reference() is None
        finally:
            reader.release.set()
            reader.second_release.set()
            notify.set()
        assert successor is not None
        second = await asyncio.wait_for(successor, 2)
        assert first.body != second.body
        assert reader.projects == ["project_one", "project_one"]

    asyncio.run(exercise())


@pytest.mark.parametrize("phase", ["read", "wire", "render"])
def test_unexpected_failure_does_not_publish_traceback_owned_scope(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    class FailureScope:
        pass

    references: list[weakref.ReferenceType[FailureScope]] = []

    def fail() -> None:
        scope = FailureScope()
        references.append(weakref.ref(scope))
        raise RuntimeError("private large snapshot scope")

    class FailingReader(_HeldReader):
        def snapshot(self, project_id: str | None = None) -> TeamSnapshot:
            snapshot = super().snapshot(project_id)
            if phase == "read" and len(self.projects) == 1:
                fail()
            return snapshot

    original_wire, original_render = TeamSnapshot.to_wire, JSONResponse.render

    def wire(snapshot: TeamSnapshot) -> WirePayload:
        if snapshot.team_name == "Read 1":
            fail()
        return original_wire(snapshot)

    def render(response: JSONResponse, content: object) -> bytes:
        if isinstance(content, dict) and content.get("team_name") == "Read 1":
            fail()
        return original_render(response, content)

    if phase == "wire":
        monkeypatch.setattr(TeamSnapshot, "to_wire", wire)
    elif phase == "render":
        monkeypatch.setattr(JSONResponse, "render", render)

    async def exercise() -> None:
        reads, reader = transport._TeamSnapshotReads(), FailingReader()
        owner = asyncio.create_task(reads.response(reader, None))
        try:
            assert await asyncio.to_thread(reader.entered.wait, 2)
            assert reads._active is not None and reads._active.task is not None
            task = reads._active.task
        finally:
            reader.release.set()
        response = await asyncio.wait_for(owner, 2)
        assert response.status_code == 500 and b"private" not in response.body
        assert task.exception() is None
        gc.collect()
        assert references and all(reference() is None for reference in references)
        assert all(reference() is None for reference in reader.snapshots)
        assert (await reads.response(reader, None)).status_code == 200

    asyncio.run(exercise())


@pytest.mark.parametrize("phase", ["wire", "render"])
def test_waiter_timeout_keeps_worker_through_serialization(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    entered, release = Event(), Event()
    original_wire, original_render = TeamSnapshot.to_wire, JSONResponse.render

    def hold() -> None:
        entered.set()
        assert release.wait(5), "test did not release serialization"

    def wire(snapshot: TeamSnapshot) -> WirePayload:
        if not release.is_set():
            hold()
        return original_wire(snapshot)

    def render(response: JSONResponse, content: object) -> bytes:
        if isinstance(content, dict) and "team_id" in content and not release.is_set():
            hold()
        return original_render(response, content)

    if phase == "wire":
        monkeypatch.setattr(TeamSnapshot, "to_wire", wire)
    else:
        monkeypatch.setattr(JSONResponse, "render", render)

    async def exercise() -> None:
        reads = transport._TeamSnapshotReads()
        reader = _HeldReader()
        reader.release.set()
        owner = asyncio.create_task(reads.response(reader, "project_one"))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(reads.response(reader, "project_one"), 0.02)
            assert reads._active is not None and reads._active.waiters == 0
            assert (await reads.response(reader, "project_other")).status_code == 503
            assert reader.projects == ["project_one"]
        finally:
            release.set()
            assert (await asyncio.wait_for(owner, 2)).status_code == 200

    asyncio.run(exercise())


def test_all_cancelled_consumers_keep_worker_and_detach_callbacks() -> None:
    class ScopeSentinel:
        pass

    async def exercise() -> None:
        reads = transport._TeamSnapshotReads()
        reader = _HeldReader()
        owner = asyncio.create_task(reads.response(reader, None))
        try:
            assert await asyncio.to_thread(reader.entered.wait, 2)
            owner.cancel()
            with pytest.raises(asyncio.CancelledError):
                await owner
            assert reads._active is not None and reads._active.task is not None
            flight = reads._active
            assert flight.task is not None
            callbacks = len(flight.task._callbacks or ())
            sentinels: list[weakref.ReferenceType[ScopeSentinel]] = []

            async def consumer() -> None:
                sentinel = ScopeSentinel()
                sentinels.append(weakref.ref(sentinel))
                await reads.response(reader, None)

            for _ in range(30):
                joined = asyncio.create_task(consumer())
                await _until(lambda: flight.waiters == 1)
                joined.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await joined
                del joined
                await asyncio.sleep(0)
                assert flight.waiters == 0
                assert len(flight.task._callbacks or ()) <= callbacks
                gc.collect()
                assert all(reference() is None for reference in sentinels)
            # Cancellation of the original caller does not make its reserved
            # ownership a third recyclable joined-consumer slot.
            replacements = [asyncio.create_task(reads.response(reader, None)) for _ in range(2)]
            await _until(lambda: flight.waiters == 2)
            assert (await reads.response(reader, None)).status_code == 503
            for replacement in replacements:
                replacement.cancel()
            results = await asyncio.gather(*replacements, return_exceptions=True)
            assert all(isinstance(result, asyncio.CancelledError) for result in results)
            assert flight.waiters == 0 and reads._active is flight
            assert (await reads.response(reader, "project_one")).status_code == 503
            assert reader.projects == [None]
        finally:
            reader.release.set()
            await _until(lambda: reads._active is None)
        fresh = await reads.response(reader, None)
        assert fresh.status_code == 200
        assert reader.projects == [None, None]

    asyncio.run(exercise())
