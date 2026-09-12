"""Typed loopback Web transport for the Manager console."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files
from typing import Protocol

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import TypeAdapter, ValidationError
from starlette.middleware.base import RequestResponseEndpoint

from ai_software_engineer.domain.identity import ProjectId, TeamId
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge_documents import KnowledgeDocumentError
from ai_software_engineer.team_view.models import TeamReadError, TeamSnapshot
from ai_software_engineer.team_workspace import MAX_TEAM_KNOWLEDGE_SOURCE_BYTES

from .administration import (
    AdministrationError,
    ConsoleAdministration,
    CreateProjectRequest,
    UpdateSettingsRequest,
)
from .models import ConsoleIntent, ConsoleOperation, IdempotencyKey
from .store import ConsoleOperationConflict, ConsoleOperationNotFound

_MAX_REQUEST_BYTES = 64_000
_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


class TeamReader(Protocol):
    def snapshot(self, project_id: str | None = None) -> TeamSnapshot: ...


class ConsoleApplication(Protocol):
    def start(self) -> None: ...
    def close(self, *, timeout: float = 5.0) -> None: ...
    def submit(self, intent: ConsoleIntent, *, idempotency_key: str) -> ConsoleOperation: ...
    def get(self, operation_id: str) -> ConsoleOperation: ...
    def list_operations(self) -> tuple[ConsoleOperation, ...]: ...


class SubmitOperation(DomainModel):
    idempotency_key: IdempotencyKey
    intent: ConsoleIntent


def create_console_app(
    console: ConsoleApplication,
    reader: TeamReader,
    *,
    team_id: str,
    port: int = 8765,
    administration: ConsoleAdministration | None = None,
) -> FastAPI:
    if isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("invalid console server port")
    expected_host = f"127.0.0.1:{port}"
    expected_origin = f"http://{expected_host}"
    command_team_id = TypeAdapter(TeamId).validate_python(team_id)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        console.start()
        try:
            yield
        finally:
            console.close()

    app = FastAPI(
        title="AI Software Engineer Console",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def protect_loopback(request: Request, call_next: RequestResponseEndpoint) -> Response:
        hosts = _header_values(request, b"host")
        origins = _header_values(request, b"origin")
        if hosts != [expected_host] or (origins and origins != [expected_origin]):
            response: Response = _error(403, "FORBIDDEN", "Forbidden origin or host.")
        else:
            response = await call_next(request)
        _security_headers(response)
        return response

    @app.get("/")
    @app.get("/app.js")
    @app.get("/style.css")
    async def asset(request: Request) -> Response:
        name, content_type = _ASSETS[request.url.path]
        return Response(
            files("ai_software_engineer.team_view").joinpath(name).read_bytes(),
            media_type=content_type,
        )

    @app.get("/api/v1/team")
    async def team(project_id: str | None = None) -> Response:
        if project_id is not None and not _valid_project_id(project_id):
            return _error(404, "NOT_FOUND", "Project was not found.")
        return await _team_snapshot(reader, project_id)

    @app.get("/api/v1/operations")
    async def operations() -> Response:
        values = await run_in_threadpool(console.list_operations)
        return JSONResponse([value.to_wire() for value in values])

    @app.get("/api/v1/console")
    async def console_info() -> Response:
        return JSONResponse({"schema_version": "v0.2", "team_id": command_team_id})

    @app.get("/api/v1/admin/team")
    async def configured_team() -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        try:
            value = await run_in_threadpool(administration.team)
        except AdministrationError:
            return _error(503, "ADMIN_UNAVAILABLE", "Team administration is unavailable.")
        return JSONResponse(value.to_wire())

    @app.get("/api/v1/admin/projects")
    async def projects() -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        try:
            values = await run_in_threadpool(administration.projects)
        except AdministrationError:
            return _error(503, "ADMIN_UNAVAILABLE", "Project administration is unavailable.")
        return JSONResponse([value.to_wire() for value in values])

    @app.post("/api/v1/admin/projects", status_code=201)
    async def create_project(request: Request) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        payload = await _json_body(request)
        if isinstance(payload, Response):
            return payload
        try:
            command = CreateProjectRequest.model_validate_json(payload)
            value = await run_in_threadpool(administration.create_project, command)
        except ValidationError:
            return _error(422, "INVALID_REQUEST", "Project input is invalid.")
        except AdministrationError:
            return _error(409, "PROJECT_REJECTED", "Project could not be created safely.")
        return JSONResponse(value.to_wire(), status_code=201)

    @app.get("/api/v1/admin/team/knowledge")
    async def knowledge() -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        try:
            values = await run_in_threadpool(administration.knowledge)
        except (AdministrationError, KnowledgeDocumentError):
            return _error(503, "KNOWLEDGE_UNAVAILABLE", "Team knowledge is unavailable.")
        return JSONResponse([value.to_wire() for value in values])

    @app.post("/api/v1/admin/team/knowledge", status_code=201)
    async def import_knowledge(request: Request, filename: str = "") -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type != "application/octet-stream":
            return _error(415, "BINARY_REQUIRED", "Use application/octet-stream.")
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > MAX_TEAM_KNOWLEDGE_SOURCE_BYTES:
                    return _error(413, "DOCUMENT_TOO_LARGE", "Document exceeds the upload limit.")
            except ValueError:
                return _error(400, "INVALID_REQUEST", "Invalid request metadata.")
        content = await request.body()
        if len(content) > MAX_TEAM_KNOWLEDGE_SOURCE_BYTES:
            return _error(413, "DOCUMENT_TOO_LARGE", "Document exceeds the upload limit.")
        try:
            value = await run_in_threadpool(
                administration.import_document,
                filename=filename,
                content=content,
            )
        except (AdministrationError, KnowledgeDocumentError, ValidationError):
            return _error(422, "DOCUMENT_REJECTED", "Document could not be imported safely.")
        return JSONResponse(value.to_wire(), status_code=201)

    @app.get("/api/v1/admin/settings")
    async def settings() -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        try:
            value = await run_in_threadpool(administration.settings)
        except AdministrationError:
            return _error(503, "ADMIN_UNAVAILABLE", "Settings are unavailable.")
        return JSONResponse(value.to_wire())

    @app.put("/api/v1/admin/settings")
    async def update_settings(request: Request) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        payload = await _json_body(request)
        if isinstance(payload, Response):
            return payload
        try:
            command = UpdateSettingsRequest.model_validate_json(payload)
            value = await run_in_threadpool(administration.update_settings, command)
        except ValidationError:
            return _error(422, "INVALID_REQUEST", "Settings input is invalid.")
        except AdministrationError:
            return _error(409, "SETTINGS_REJECTED", "Settings could not be saved safely.")
        return JSONResponse(value.to_wire())

    @app.get("/api/v1/operations/{operation_id}")
    async def operation(operation_id: str) -> Response:
        try:
            value = await run_in_threadpool(console.get, operation_id)
        except (ConsoleOperationNotFound, ValidationError):
            return _error(404, "NOT_FOUND", "Operation not found.")
        return JSONResponse(value.to_wire())

    @app.post("/api/v1/operations", status_code=202)
    async def submit(request: Request) -> Response:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return _error(415, "JSON_REQUIRED", "Use application/json.")
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > _MAX_REQUEST_BYTES:
                    return _error(413, "REQUEST_TOO_LARGE", "Request is too large.")
            except ValueError:
                return _error(400, "INVALID_REQUEST", "Invalid request metadata.")
        body = await request.body()
        if len(body) > _MAX_REQUEST_BYTES:
            return _error(413, "REQUEST_TOO_LARGE", "Request is too large.")
        try:
            command = SubmitOperation.model_validate_json(body)
            value = await run_in_threadpool(
                console.submit,
                command.intent,
                idempotency_key=command.idempotency_key,
            )
        except ValidationError:
            return _error(422, "INVALID_REQUEST", "Operation input is invalid.")
        except ConsoleOperationConflict as error:
            return _error(409, "OPERATION_CONFLICT", str(error))
        return JSONResponse(value.to_wire(), status_code=202)

    return app


async def _json_body(request: Request) -> bytes | Response:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _error(415, "JSON_REQUIRED", "Use application/json.")
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > _MAX_REQUEST_BYTES:
                return _error(413, "REQUEST_TOO_LARGE", "Request is too large.")
        except ValueError:
            return _error(400, "INVALID_REQUEST", "Invalid request metadata.")
    body = await request.body()
    if len(body) > _MAX_REQUEST_BYTES:
        return _error(413, "REQUEST_TOO_LARGE", "Request is too large.")
    return body


def _valid_project_id(project_id: str) -> bool:
    try:
        TypeAdapter(ProjectId).validate_python(project_id)
    except ValidationError:
        return False
    return True


async def _team_snapshot(reader: TeamReader, project_id: str | None) -> Response:
    try:
        snapshot = await run_in_threadpool(reader.snapshot, project_id)
    except TeamReadError:
        return _error(503, "TEAM_UNAVAILABLE", "Team data is temporarily unavailable.")
    return JSONResponse(snapshot.to_wire())


def _header_values(request: Request, name: bytes) -> list[str]:
    return [
        value.decode("latin-1")
        for key, value in request.scope.get("headers", [])
        if key.lower() == name
    ]


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _security_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    )


__all__ = ["ConsoleApplication", "SubmitOperation", "TeamReader", "create_console_app"]
