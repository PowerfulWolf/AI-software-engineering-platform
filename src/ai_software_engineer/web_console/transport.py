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
from ai_software_engineer.knowledge_selection import KnowledgeSelectionError
from ai_software_engineer.learning import DecideLearningProposal, LearningError
from ai_software_engineer.multi_directory.attachments import (
    MAX_REQUIREMENT_SCREENSHOT_BYTES,
    RequirementAttachmentError,
)
from ai_software_engineer.spec_documents import CreateSpecDocument, SpecDocumentError
from ai_software_engineer.team_view.models import TeamReadError, TeamSnapshot
from ai_software_engineer.team_workspace import MAX_TEAM_KNOWLEDGE_SOURCE_BYTES

from .administration import (
    AdministrationError,
    ConsoleAdministration,
    CreateProjectRequest,
    MySqlConnectionRequest,
    UpdateKnowledgeSelectionRequest,
    UpdateSettingsRequest,
    UpdateSpecActivationRequest,
)
from .core import ConsoleCommandRejected
from .directories import DirectoryChooser, DirectorySelectionError
from .lifecycle import (
    ApplyConfigurationRequest,
    ConfigurationApplyError,
    ConfigurationApplyView,
    ConfigurationLifecycle,
)
from .models import ConsoleIntent, ConsoleOperation, IdempotencyKey
from .store import ConsoleOperationConflict, ConsoleOperationNotFound

_MAX_REQUEST_BYTES = 64_000
_MAX_SPEC_REQUEST_BYTES = 512_000
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
    configuration_lifecycle: ConfigurationLifecycle | None = None,
    configuration_port_override: int | None = None,
    directory_chooser: DirectoryChooser | None = None,
    delivery_ready: bool = True,
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
        return JSONResponse(
            {
                "schema_version": "v0.2",
                "team_id": command_team_id,
                "delivery_ready": delivery_ready,
            }
        )

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

    @app.post("/api/v1/admin/directories/select")
    async def select_directories() -> Response:
        if directory_chooser is None:
            return _error(404, "NOT_AVAILABLE", "Directory selection is not available.")
        try:
            values = await run_in_threadpool(directory_chooser.choose)
        except DirectorySelectionError:
            return _error(503, "CHOOSER_UNAVAILABLE", "Directory selection could not be opened.")
        return JSONResponse({"directories": list(values), "cancelled": not values})

    @app.post(
        "/api/v1/admin/projects/{project_id}/requirements/{delivery_id}/screenshots",
        status_code=201,
    )
    async def upload_requirement_screenshot(
        project_id: str,
        delivery_id: str,
        request: Request,
        filename: str = "",
        checkpoint: str = "",
    ) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        if not _valid_project_id(project_id):
            return _error(404, "NOT_FOUND", "Project was not found.")
        content = await _screenshot_body(request)
        if isinstance(content, Response):
            return content
        try:
            value = await run_in_threadpool(
                administration.upload_requirement_screenshot,
                project_id,
                delivery_id,
                checkpoint,
                filename=filename,
                content=content,
            )
        except (AdministrationError, RequirementAttachmentError, ValidationError):
            return _error(422, "SCREENSHOT_REJECTED", "Screenshot could not be stored safely.")
        return JSONResponse(value.to_wire(), status_code=201)

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
        content = await _knowledge_document_body(request)
        if isinstance(content, Response):
            return content
        try:
            value = await run_in_threadpool(
                administration.import_document,
                filename=filename,
                content=content,
            )
        except (
            AdministrationError,
            KnowledgeDocumentError,
            KnowledgeSelectionError,
            ValidationError,
        ):
            return _error(422, "DOCUMENT_REJECTED", "Document could not be imported safely.")
        return JSONResponse(value.to_wire(), status_code=201)

    @app.get("/api/v1/admin/team/knowledge/{document_id}/content")
    async def team_knowledge_content(document_id: str) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        try:
            value = await run_in_threadpool(administration.document_content, document_id)
        except (AdministrationError, KnowledgeDocumentError, ValidationError):
            return _error(404, "DOCUMENT_NOT_FOUND", "Document was not found.")
        return JSONResponse(value.to_wire())

    @app.put("/api/v1/admin/team/knowledge/selection")
    async def update_team_knowledge_selection(request: Request) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        payload = await _json_body(request)
        if isinstance(payload, Response):
            return payload
        try:
            command = UpdateKnowledgeSelectionRequest.model_validate_json(payload)
            values = await run_in_threadpool(
                administration.update_team_knowledge_selection, command
            )
        except ValidationError:
            return _error(422, "INVALID_REQUEST", "Knowledge selection is invalid.")
        except (AdministrationError, KnowledgeDocumentError):
            return _error(409, "KNOWLEDGE_REJECTED", "Knowledge selection was rejected.")
        return JSONResponse([value.to_wire() for value in values])

    @app.put("/api/v1/admin/team/knowledge/{document_id}")
    async def replace_knowledge(document_id: str, request: Request, filename: str = "") -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        content = await _knowledge_document_body(request)
        if isinstance(content, Response):
            return content
        try:
            value = await run_in_threadpool(
                administration.replace_document,
                document_id,
                filename=filename,
                content=content,
            )
        except (
            AdministrationError,
            KnowledgeDocumentError,
            KnowledgeSelectionError,
            ValidationError,
        ):
            return _error(422, "DOCUMENT_REJECTED", "Document could not be updated safely.")
        return JSONResponse(value.to_wire())

    @app.delete("/api/v1/admin/team/knowledge/{document_id}")
    async def delete_knowledge(document_id: str) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        try:
            values = await run_in_threadpool(administration.delete_document, document_id)
        except (
            AdministrationError,
            KnowledgeDocumentError,
            KnowledgeSelectionError,
            ValidationError,
        ):
            return _error(409, "DOCUMENT_REJECTED", "Document could not be deleted safely.")
        return JSONResponse([value.to_wire() for value in values])

    @app.get("/api/v1/admin/projects/{project_id}/knowledge")
    async def project_knowledge(project_id: str) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        if not _valid_project_id(project_id):
            return _error(404, "NOT_FOUND", "Project was not found.")
        try:
            values = await run_in_threadpool(administration.project_knowledge, project_id)
        except (AdministrationError, KnowledgeDocumentError):
            return _error(503, "KNOWLEDGE_UNAVAILABLE", "Project knowledge is unavailable.")
        return JSONResponse([value.to_wire() for value in values])

    @app.post("/api/v1/admin/projects/{project_id}/knowledge", status_code=201)
    async def import_project_knowledge(
        project_id: str, request: Request, filename: str = ""
    ) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        if not _valid_project_id(project_id):
            return _error(404, "NOT_FOUND", "Project was not found.")
        content = await _knowledge_document_body(request)
        if isinstance(content, Response):
            return content
        try:
            value = await run_in_threadpool(
                administration.import_project_document,
                project_id,
                filename=filename,
                content=content,
            )
        except (
            AdministrationError,
            KnowledgeDocumentError,
            KnowledgeSelectionError,
            ValidationError,
        ):
            return _error(422, "DOCUMENT_REJECTED", "Document could not be imported safely.")
        return JSONResponse(value.to_wire(), status_code=201)

    @app.get("/api/v1/admin/projects/{project_id}/knowledge/{document_id}/content")
    async def project_knowledge_content(project_id: str, document_id: str) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        if not _valid_project_id(project_id):
            return _error(404, "NOT_FOUND", "Project was not found.")
        try:
            value = await run_in_threadpool(
                administration.project_document_content,
                project_id,
                document_id,
            )
        except (AdministrationError, KnowledgeDocumentError, ValidationError):
            return _error(404, "DOCUMENT_NOT_FOUND", "Document was not found.")
        return JSONResponse(value.to_wire())

    @app.put("/api/v1/admin/projects/{project_id}/knowledge/selection")
    async def update_project_knowledge_selection(project_id: str, request: Request) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        if not _valid_project_id(project_id):
            return _error(404, "NOT_FOUND", "Project was not found.")
        payload = await _json_body(request)
        if isinstance(payload, Response):
            return payload
        try:
            command = UpdateKnowledgeSelectionRequest.model_validate_json(payload)
            values = await run_in_threadpool(
                administration.update_project_knowledge_selection,
                project_id,
                command,
            )
        except ValidationError:
            return _error(422, "INVALID_REQUEST", "Knowledge selection is invalid.")
        except (AdministrationError, KnowledgeDocumentError):
            return _error(409, "KNOWLEDGE_REJECTED", "Knowledge selection was rejected.")
        return JSONResponse([value.to_wire() for value in values])

    @app.put("/api/v1/admin/projects/{project_id}/knowledge/{document_id}")
    async def replace_project_knowledge(
        project_id: str,
        document_id: str,
        request: Request,
        filename: str = "",
    ) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        if not _valid_project_id(project_id):
            return _error(404, "NOT_FOUND", "Project was not found.")
        content = await _knowledge_document_body(request)
        if isinstance(content, Response):
            return content
        try:
            value = await run_in_threadpool(
                administration.replace_project_document,
                project_id,
                document_id,
                filename=filename,
                content=content,
            )
        except (
            AdministrationError,
            KnowledgeDocumentError,
            KnowledgeSelectionError,
            ValidationError,
        ):
            return _error(422, "DOCUMENT_REJECTED", "Document could not be updated safely.")
        return JSONResponse(value.to_wire())

    @app.delete("/api/v1/admin/projects/{project_id}/knowledge/{document_id}")
    async def delete_project_knowledge(project_id: str, document_id: str) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        if not _valid_project_id(project_id):
            return _error(404, "NOT_FOUND", "Project was not found.")
        try:
            values = await run_in_threadpool(
                administration.delete_project_document,
                project_id,
                document_id,
            )
        except (
            AdministrationError,
            KnowledgeDocumentError,
            KnowledgeSelectionError,
            ValidationError,
        ):
            return _error(409, "DOCUMENT_REJECTED", "Document could not be deleted safely.")
        return JSONResponse([value.to_wire() for value in values])

    @app.get("/api/v1/admin/team/specs")
    async def team_specs() -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        try:
            values = await run_in_threadpool(administration.team_specs)
        except (AdministrationError, SpecDocumentError):
            return _error(503, "SPEC_UNAVAILABLE", "Team Specs are unavailable.")
        return JSONResponse([value.to_wire() for value in values])

    @app.post("/api/v1/admin/team/specs", status_code=201)
    async def create_team_spec(request: Request) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        payload = await _json_body(request, maximum=_MAX_SPEC_REQUEST_BYTES)
        if isinstance(payload, Response):
            return payload
        try:
            command = CreateSpecDocument.model_validate_json(payload)
            value = await run_in_threadpool(administration.create_team_spec, command)
        except (ValidationError, AdministrationError, SpecDocumentError):
            return _error(422, "SPEC_REJECTED", "Team Spec could not be created safely.")
        return JSONResponse(value.to_wire(), status_code=201)

    @app.put("/api/v1/admin/team/specs/activation")
    async def activate_team_specs(request: Request) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        payload = await _json_body(request)
        if isinstance(payload, Response):
            return payload
        try:
            command = UpdateSpecActivationRequest.model_validate_json(payload)
            values = await run_in_threadpool(administration.update_team_spec_activation, command)
        except (ValidationError, AdministrationError, SpecDocumentError):
            return _error(409, "SPEC_REJECTED", "Team Spec activation was rejected.")
        return JSONResponse([value.to_wire() for value in values])

    @app.delete("/api/v1/admin/team/specs/{spec_key}")
    async def delete_team_spec(spec_key: str) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        try:
            values = await run_in_threadpool(administration.delete_team_spec, spec_key)
        except (ValidationError, AdministrationError, SpecDocumentError):
            return _error(409, "SPEC_REJECTED", "Team Spec could not be deleted safely.")
        return JSONResponse([value.to_wire() for value in values])

    @app.get("/api/v1/admin/projects/{project_id}/specs")
    async def project_specs(project_id: str) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        if not _valid_project_id(project_id):
            return _error(404, "NOT_FOUND", "Project was not found.")
        try:
            values = await run_in_threadpool(administration.project_specs, project_id)
        except (AdministrationError, SpecDocumentError):
            return _error(503, "SPEC_UNAVAILABLE", "Project Specs are unavailable.")
        return JSONResponse([value.to_wire() for value in values])

    @app.post("/api/v1/admin/projects/{project_id}/specs", status_code=201)
    async def create_project_spec(project_id: str, request: Request) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        if not _valid_project_id(project_id):
            return _error(404, "NOT_FOUND", "Project was not found.")
        payload = await _json_body(request, maximum=_MAX_SPEC_REQUEST_BYTES)
        if isinstance(payload, Response):
            return payload
        try:
            command = CreateSpecDocument.model_validate_json(payload)
            value = await run_in_threadpool(administration.create_project_spec, project_id, command)
        except (ValidationError, AdministrationError, SpecDocumentError):
            return _error(422, "SPEC_REJECTED", "Project Spec could not be created safely.")
        return JSONResponse(value.to_wire(), status_code=201)

    @app.put("/api/v1/admin/projects/{project_id}/specs/activation")
    async def activate_project_specs(project_id: str, request: Request) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        if not _valid_project_id(project_id):
            return _error(404, "NOT_FOUND", "Project was not found.")
        payload = await _json_body(request)
        if isinstance(payload, Response):
            return payload
        try:
            command = UpdateSpecActivationRequest.model_validate_json(payload)
            values = await run_in_threadpool(
                administration.update_project_spec_activation,
                project_id,
                command,
            )
        except (ValidationError, AdministrationError, SpecDocumentError):
            return _error(409, "SPEC_REJECTED", "Project Spec activation was rejected.")
        return JSONResponse([value.to_wire() for value in values])

    @app.delete("/api/v1/admin/projects/{project_id}/specs/{spec_key}")
    async def delete_project_spec(project_id: str, spec_key: str) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        if not _valid_project_id(project_id):
            return _error(404, "NOT_FOUND", "Project was not found.")
        try:
            values = await run_in_threadpool(
                administration.delete_project_spec,
                project_id,
                spec_key,
            )
        except (ValidationError, AdministrationError, SpecDocumentError):
            return _error(409, "SPEC_REJECTED", "Project Spec could not be deleted safely.")
        return JSONResponse([value.to_wire() for value in values])

    @app.get("/api/v1/admin/projects/{project_id}/learnings")
    async def project_learnings(project_id: str) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        if not _valid_project_id(project_id):
            return _error(404, "NOT_FOUND", "Project was not found.")
        try:
            values = await run_in_threadpool(administration.project_learnings, project_id)
        except (AdministrationError, LearningError):
            return _error(503, "LEARNING_UNAVAILABLE", "Learning proposals are unavailable.")
        return JSONResponse([value.to_wire() for value in values])

    @app.post("/api/v1/admin/projects/{project_id}/learnings/collect")
    async def collect_project_learnings(project_id: str) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        if not _valid_project_id(project_id):
            return _error(404, "NOT_FOUND", "Project was not found.")
        try:
            values = await run_in_threadpool(administration.collect_project_learnings, project_id)
        except (AdministrationError, LearningError):
            return _error(409, "LEARNING_REJECTED", "Learning collection was rejected.")
        return JSONResponse([value.to_wire() for value in values])

    @app.post("/api/v1/admin/projects/{project_id}/learnings/{proposal_id}/decision")
    async def decide_project_learning(
        project_id: str, proposal_id: str, request: Request
    ) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        if not _valid_project_id(project_id):
            return _error(404, "NOT_FOUND", "Project was not found.")
        payload = await _json_body(request)
        if isinstance(payload, Response):
            return payload
        try:
            command = DecideLearningProposal.model_validate_json(payload)
            value = await run_in_threadpool(
                administration.decide_project_learning,
                project_id,
                proposal_id,
                command,
            )
        except (ValidationError, AdministrationError, LearningError, SpecDocumentError):
            return _error(409, "LEARNING_REJECTED", "Learning decision was rejected.")
        return JSONResponse(value.to_wire())

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

    @app.get("/api/v1/admin/settings/apply")
    async def configuration_apply_status() -> Response:
        if configuration_lifecycle is None or administration is None:
            return _error(404, "NOT_AVAILABLE", "Configuration apply is not available.")
        try:
            value = await run_in_threadpool(configuration_lifecycle.current)
            settings_value = await run_in_threadpool(administration.settings)
        except (AdministrationError, ConfigurationApplyError):
            return _error(503, "APPLY_UNAVAILABLE", "Configuration apply status is unavailable.")
        if value is None:
            return _error(404, "NOT_FOUND", "No configuration apply request exists.")
        reconnect_port = configuration_port_override or settings_value.config.console_port
        return JSONResponse(
            ConfigurationApplyView.from_state(
                value, effective_console_port=reconnect_port
            ).to_wire()
        )

    @app.post("/api/v1/admin/settings/apply", status_code=202)
    async def apply_configuration(request: Request) -> Response:
        if administration is None or configuration_lifecycle is None:
            return _error(404, "NOT_AVAILABLE", "Configuration apply is not available.")
        payload = await _json_body(request)
        if isinstance(payload, Response):
            return payload
        try:
            ApplyConfigurationRequest.model_validate_json(payload)
            settings_value = await run_in_threadpool(administration.settings)
            if not settings_value.restart_required:
                return _error(409, "RESTART_NOT_REQUIRED", "Configuration is already applied.")
            apply_token = await run_in_threadpool(administration.configuration_apply_token)
            value = await run_in_threadpool(configuration_lifecycle.request, apply_token)
        except ValidationError:
            return _error(422, "INVALID_REQUEST", "Configuration apply input is invalid.")
        except AdministrationError:
            return _error(503, "ADMIN_UNAVAILABLE", "Configuration apply is unavailable.")
        except ConfigurationApplyError:
            return _error(
                503,
                "APPLY_UNAVAILABLE",
                "Configuration remains saved but could not be applied. "
                "Use the service script to retry safely.",
            )
        reconnect_port = configuration_port_override or settings_value.config.console_port
        return JSONResponse(
            ConfigurationApplyView.from_state(
                value, effective_console_port=reconnect_port
            ).to_wire(),
            status_code=202,
        )

    @app.post("/api/v1/admin/settings/test-mysql")
    async def test_mysql_connection(request: Request) -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        payload = await _json_body(request)
        if isinstance(payload, Response):
            return payload
        try:
            command = MySqlConnectionRequest.model_validate_json(payload)
            value = await run_in_threadpool(administration.test_mysql_connection, command)
        except ValidationError:
            return _error(422, "INVALID_REQUEST", "MySQL connection input is invalid.")
        except AdministrationError:
            return _error(503, "ADMIN_UNAVAILABLE", "MySQL connection test is unavailable.")
        return JSONResponse(value.to_wire())

    @app.get("/api/v1/admin/status")
    async def runtime_status() -> Response:
        if administration is None:
            return _error(404, "NOT_AVAILABLE", "Administration is not available.")
        try:
            value = await run_in_threadpool(administration.status)
        except AdministrationError:
            return _error(503, "ADMIN_UNAVAILABLE", "Runtime status is unavailable.")
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
        except ConsoleCommandRejected as error:
            return _error(503, error.code, error.safe_summary)
        except ConsoleOperationConflict as error:
            return _error(409, "OPERATION_CONFLICT", str(error))
        return JSONResponse(value.to_wire(), status_code=202)

    return app


async def _json_body(request: Request, *, maximum: int = _MAX_REQUEST_BYTES) -> bytes | Response:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _error(415, "JSON_REQUIRED", "Use application/json.")
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > maximum:
                return _error(413, "REQUEST_TOO_LARGE", "Request is too large.")
        except ValueError:
            return _error(400, "INVALID_REQUEST", "Invalid request metadata.")
    body = await request.body()
    if len(body) > maximum:
        return _error(413, "REQUEST_TOO_LARGE", "Request is too large.")
    return body


async def _knowledge_document_body(request: Request) -> bytes | Response:
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
    return content


async def _screenshot_body(request: Request) -> bytes | Response:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type != "application/octet-stream":
        return _error(415, "BINARY_REQUIRED", "Use application/octet-stream.")
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_REQUIREMENT_SCREENSHOT_BYTES:
                return _error(413, "SCREENSHOT_TOO_LARGE", "Screenshot exceeds the upload limit.")
        except ValueError:
            return _error(400, "INVALID_REQUEST", "Invalid request metadata.")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_REQUIREMENT_SCREENSHOT_BYTES:
            return _error(413, "SCREENSHOT_TOO_LARGE", "Screenshot exceeds the upload limit.")
        content.extend(chunk)
    return bytes(content)


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
        "img-src 'self' blob: data:; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    )


__all__ = ["ConsoleApplication", "SubmitOperation", "TeamReader", "create_console_app"]
