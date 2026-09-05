"""Responses-compatible AgentAdapter with a bounded, policy-checked tool loop."""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from ai_software_engineer.agents.json_schema import strict_output_schema
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
    AgentUsage,
)
from ai_software_engineer.agents.openai_compatible import (
    ContextResolver,
    HttpResponse,
    HttpTransport,
    PromptBuilder,
    RequestPromptBuilder,
    UrllibHttpTransport,
)
from ai_software_engineer.agents.ports import (
    AgentConfigurationError,
    AgentError,
    AgentRequestConflict,
)
from ai_software_engineer.domain import AgentDefinition, AgentRole
from ai_software_engineer.domain.agent import ROLE_OUTPUT
from ai_software_engineer.domain.artifact import (
    Artifact,
    ImplementationReportArtifact,
    PlanArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
    validate_artifact,
)
from ai_software_engineer.domain.model import JsonValue, WirePayload
from ai_software_engineer.git import WorkspacePolicy, WorkspacePolicyError
from ai_software_engineer.tools import (
    PolicyBoundToolRegistry,
    ReadFileRequest,
    RunCommandRequest,
    WriteFileRequest,
)


class ResponsesAgentError(AgentError):
    """Base error for Responses adapter configuration and local validation."""


class ResponsesAgentConfigurationError(AgentConfigurationError, ResponsesAgentError):
    """Raised when a Responses route or role workspace is unsafe."""


class ResponsesAgentAdapter:
    """Run one role through Responses function calls without exposing a shell."""

    def __init__(
        self,
        *,
        workspace_root: str | Path,
        endpoint: str,
        api_key: str,
        model: str,
        agent: AgentDefinition,
        prompt_builder: PromptBuilder | None = None,
        context_resolver: ContextResolver | None = None,
        transport: HttpTransport | None = None,
        max_turns: int = 40,
        max_tool_calls: int = 100,
    ) -> None:
        root = Path(workspace_root).expanduser().resolve(strict=False)
        if not root.is_dir() or root.is_symlink():
            raise ResponsesAgentConfigurationError(
                "Responses workspace must be an existing real directory"
            )
        if not api_key or any(ord(character) < 32 for character in api_key):
            raise ResponsesAgentConfigurationError("Responses API key is missing or invalid")
        if not model.strip() or any(ord(character) < 32 for character in model):
            raise ResponsesAgentConfigurationError("Responses model is invalid")
        if not 1 <= max_turns <= 100 or not 1 <= max_tool_calls <= 500:
            raise ResponsesAgentConfigurationError("Responses loop bounds are invalid")
        self._workspace_root = root
        self._endpoint = _normalize_endpoint(endpoint)
        self._api_key = api_key
        self._model = model
        self._agent = agent
        self._prompt_builder = prompt_builder or RequestPromptBuilder()
        if context_resolver is not None and prompt_builder is not None:
            raise ResponsesAgentConfigurationError(
                "configure prompt_builder or context_resolver, not both"
            )
        if context_resolver is not None:
            from ai_software_engineer.agents.openai_compatible import ContextPromptBuilder

            self._prompt_builder = ContextPromptBuilder(context_resolver)
        self._transport = transport or UrllibHttpTransport()
        self._max_turns = max_turns
        self._max_tool_calls = max_tool_calls
        self._requests: dict[str, AgentRequest] = {}
        self._results: dict[str, AgentResult] = {}

    def run(self, request: AgentRequest) -> AgentResult:
        prior = self._requests.get(request.run_id)
        if prior is not None:
            if prior != request:
                raise AgentRequestConflict(
                    f"run ID already used with a different request: {request.run_id}"
                )
            return self._results[request.run_id]
        started = time.monotonic()
        initial_head = _git(self._workspace_root, "rev-parse", "HEAD")
        try:
            _validate_request_binding(request, self._agent, self._workspace_root, initial_head)
            result = self._execute(request, started, initial_head)
        except TimeoutError:
            result = _safe_failure(
                request,
                self._workspace_root,
                initial_head,
                AgentErrorCode.TIMEOUT,
                "Responses provider timed out",
                transient=True,
                duration_ms=_elapsed_ms(started),
                timed_out=True,
            )
        except OSError:
            result = _safe_failure(
                request,
                self._workspace_root,
                initial_head,
                AgentErrorCode.PROVIDER_UNAVAILABLE,
                "Responses provider is unavailable",
                transient=True,
                duration_ms=_elapsed_ms(started),
            )
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            result = _safe_failure(
                request,
                self._workspace_root,
                initial_head,
                AgentErrorCode.INVALID_OUTPUT,
                "Responses provider returned invalid structured output",
                transient=False,
                duration_ms=_elapsed_ms(started),
            )
        except (ResponsesAgentError, WorkspacePolicyError):
            result = _safe_failure(
                request,
                self._workspace_root,
                initial_head,
                AgentErrorCode.POLICY_VIOLATION,
                "Responses execution violated its machine boundary",
                transient=False,
                duration_ms=_elapsed_ms(started),
            )
        self._requests[request.run_id] = request
        self._results[request.run_id] = result
        return result

    def _execute(
        self,
        request: AgentRequest,
        started: float,
        initial_head: str,
    ) -> AgentResult:
        registry = PolicyBoundToolRegistry(
            self._workspace_root,
            self._agent,
            run_id=request.run_id,
        )
        prompt = self._prompt_builder.build(request)
        input_items: list[WirePayload] = [
            {
                "role": message.role,
                "content": cast(
                    JsonValue,
                    [{"type": "input_text", "text": message.content}],
                ),
            }
            for message in prompt.messages
        ]
        previous_response_id: str | None = None
        tool_calls = 0
        latest_usage: AgentUsage | None = None
        for turn in range(1, self._max_turns + 1):
            body = _request_body(
                self._model,
                input_items,
                request.role,
                previous_response_id=previous_response_id,
            )
            response = self._transport.post(
                self._endpoint,
                {
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                body,
                float(request.timeout_seconds),
            )
            if not 200 <= response.status_code < 300:
                status, code, transient = _http_failure(response)
                return _safe_failure(
                    request,
                    self._workspace_root,
                    initial_head,
                    code,
                    f"Responses provider returned HTTP {response.status_code}",
                    transient=transient,
                    duration_ms=_elapsed_ms(started),
                    timed_out=status is AgentRunStatus.TIMED_OUT,
                )
            payload = _response_payload(response)
            latest_usage = _usage(payload) or latest_usage
            calls = _function_calls(payload)
            if calls:
                previous_response_id = _response_id(payload)
                outputs: list[WirePayload] = []
                for call_id, name, arguments in calls:
                    tool_calls += 1
                    if tool_calls > self._max_tool_calls:
                        raise ResponsesAgentError("Responses tool-call budget exceeded")
                    tool_request = _tool_request(
                        request,
                        name,
                        arguments,
                        operation_id=f"tool.responses.{turn:02d}.{tool_calls:03d}",
                    )
                    tool_result = registry.execute(tool_request)
                    outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": json.dumps(
                                tool_result.to_wire(),
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        }
                    )
                input_items = outputs
                continue
            content = _output_text(payload)
            artifact = validate_artifact(json.loads(content), ROLE_OUTPUT[request.role])
            artifact = _normalize_producer(artifact, request, self._agent)
            _validate_git_result(
                self._workspace_root,
                request,
                initial_head,
                artifact,
            )
            return AgentResult(
                run_id=request.run_id,
                task_id=request.task_id,
                role=request.role,
                attempt=request.attempt,
                source_revision=request.source_revision,
                context_manifest_id=request.context_manifest_id,
                status=AgentRunStatus.SUCCEEDED,
                artifact=artifact,
                usage=latest_usage,
                duration_ms=_elapsed_ms(started),
            )
        raise ResponsesAgentError("Responses turn budget exceeded")


def _request_body(
    model: str,
    input_items: list[WirePayload],
    role: AgentRole,
    *,
    previous_response_id: str | None,
) -> bytes:
    payload: WirePayload = {
        "model": model,
        "input": cast(JsonValue, input_items),
        "tools": cast(JsonValue, _tool_definitions(role)),
        "text": {
            "format": {
                "type": "json_schema",
                "name": role.value.replace("-", "_") + "_artifact",
                "strict": True,
                "schema": cast(JsonValue, _artifact_schema(role)),
            }
        },
    }
    if previous_response_id is not None:
        payload["previous_response_id"] = previous_response_id
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _tool_definitions(role: AgentRole) -> list[WirePayload]:
    definitions: list[WirePayload] = [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read one UTF-8 repository-relative file.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_bytes": {"type": "integer", "minimum": 1, "maximum": 1000000},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "run_command",
            "description": "Run one tokenized, allowlisted command without a shell.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 64,
                    },
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600},
                },
                "required": ["argv"],
                "additionalProperties": False,
            },
        },
    ]
    if role in {AgentRole.CODER, AgentRole.QA}:
        definitions.append(
            {
                "type": "function",
                "name": "write_file",
                "description": "Atomically write one authorized repository-relative UTF-8 file.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
            }
        )
    return definitions


def _tool_request(
    request: AgentRequest,
    name: str,
    arguments: str,
    *,
    operation_id: str,
) -> ReadFileRequest | WriteFileRequest | RunCommandRequest:
    payload = json.loads(arguments)
    if not isinstance(payload, Mapping):
        raise ValueError("function arguments must be an object")
    common = {
        "run_id": request.run_id,
        "role": request.role,
        "operation_id": operation_id,
    }
    if name == "read_file":
        return ReadFileRequest.model_validate({**common, **payload})
    if name == "write_file":
        return WriteFileRequest.model_validate({**common, **payload})
    if name == "run_command":
        return RunCommandRequest.model_validate({**common, **payload})
    raise ValueError("provider requested an unknown function")


def _response_payload(response: HttpResponse) -> Mapping[str, object]:
    payload = json.loads(response.body.decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Responses payload must be an object")
    return payload


def _response_id(payload: Mapping[str, object]) -> str:
    value = payload.get("id")
    if not isinstance(value, str) or not value:
        raise ValueError("Responses function call has no response ID")
    return value


def _function_calls(payload: Mapping[str, object]) -> tuple[tuple[str, str, str], ...]:
    output = payload.get("output")
    if not isinstance(output, Sequence) or isinstance(output, (str, bytes)):
        return ()
    calls: list[tuple[str, str, str]] = []
    for item in output:
        if not isinstance(item, Mapping) or item.get("type") != "function_call":
            continue
        call_id = item.get("call_id")
        name = item.get("name")
        arguments = item.get("arguments")
        if not all(isinstance(value, str) and value for value in (call_id, name, arguments)):
            raise ValueError("Responses function call is incomplete")
        calls.append((cast(str, call_id), cast(str, name), cast(str, arguments)))
    return tuple(calls)


def _output_text(payload: Mapping[str, object]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    output = payload.get("output")
    if isinstance(output, Sequence) and not isinstance(output, (str, bytes)):
        texts: list[str] = []
        for item in output:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
                continue
            for part in content:
                if isinstance(part, Mapping) and part.get("type") in {
                    "output_text",
                    "text",
                }:
                    text = part.get("text")
                    if isinstance(text, str):
                        texts.append(text)
        if texts:
            return "\n".join(texts)
    raise ValueError("Responses payload has no final output text")


def _usage(payload: Mapping[str, object]) -> AgentUsage | None:
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        return None
    inputs = usage.get("input_tokens", usage.get("prompt_tokens"))
    outputs = usage.get("output_tokens", usage.get("completion_tokens"))
    total = usage.get("total_tokens")
    if type(inputs) is not int or type(outputs) is not int:
        return None
    if type(total) is not int:
        total = inputs + outputs
    return AgentUsage(input_tokens=inputs, output_tokens=outputs, total_tokens=total)


def _normalize_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or any(ord(character) < 32 for character in endpoint)
    ):
        raise ResponsesAgentConfigurationError("Responses endpoint must be a safe HTTP(S) URL")
    path = parsed.path.rstrip("/")
    if not path.endswith("/responses"):
        path = f"{path}/responses" if path else "/v1/responses"
    return parsed._replace(path=path, query="", fragment="").geturl()


def _artifact_schema(role: AgentRole) -> dict[str, object]:
    if role is AgentRole.ORCHESTRATOR:
        schema = PlanArtifact.model_json_schema()
    elif role is AgentRole.CODER:
        schema = ImplementationReportArtifact.model_json_schema()
    elif role is AgentRole.QA:
        schema = QaReportArtifact.model_json_schema()
    else:
        schema = ReviewReportArtifact.model_json_schema()
    return strict_output_schema(cast(dict[str, object], schema))


def _validate_request_binding(
    request: AgentRequest,
    agent: AgentDefinition,
    root: Path,
    initial_head: str,
) -> None:
    if request.role is not agent.role or request.permissions != agent.permissions:
        raise ResponsesAgentConfigurationError("AgentRequest does not match bound AgentDefinition")
    source = _git(root, "rev-parse", "--verify", f"{request.source_revision}^{{commit}}")
    if initial_head != source or _git(root, "status", "--porcelain"):
        raise ResponsesAgentConfigurationError(
            "Responses worktree is not clean at the requested source revision"
        )


def _validate_git_result(
    root: Path,
    request: AgentRequest,
    initial_head: str,
    artifact: Artifact,
) -> None:
    final_head = _git(root, "rev-parse", "HEAD")
    if _git(root, "status", "--porcelain"):
        raise WorkspacePolicyError("role left uncommitted worktree changes")
    if request.role is not AgentRole.CODER:
        if final_head != initial_head:
            raise WorkspacePolicyError("read-only role changed worktree revision")
        return
    if final_head == initial_head or not isinstance(artifact, ImplementationReportArtifact):
        raise ValueError("Coder did not produce a candidate commit and implementation report")
    if artifact.source_revision != final_head or artifact.content.commit_sha != final_head:
        raise ValueError("implementation report does not bind the candidate commit")
    changed = _git_lines(root, "diff", "--name-only", f"{initial_head}..{final_head}")
    reported = tuple(sorted(item.path for item in artifact.content.changed_files))
    if not changed or tuple(sorted(changed)) != reported:
        raise ValueError("implementation report changed_files do not match Git diff")
    policy = WorkspacePolicy(root, request.permissions)
    for path in changed:
        policy.authorize_write(path)


def _normalize_producer(
    artifact: Artifact,
    request: AgentRequest,
    agent: AgentDefinition,
) -> Artifact:
    return artifact.model_copy(
        update={
            "producer": artifact.producer.model_copy(
                update={
                    "role": request.role,
                    "agent_id": agent.id,
                    "agent_version": agent.version,
                    "run_id": request.run_id,
                }
            )
        }
    )


def _safe_failure(
    request: AgentRequest,
    root: Path,
    initial_head: str,
    code: AgentErrorCode,
    message: str,
    *,
    transient: bool,
    duration_ms: int,
    timed_out: bool = False,
) -> AgentResult:
    if not _workspace_unchanged(root, initial_head):
        code = AgentErrorCode.POLICY_VIOLATION
        message = "failed provider route left repository changes"
        transient = False
        timed_out = False
    return AgentResult(
        run_id=request.run_id,
        task_id=request.task_id,
        role=request.role,
        attempt=request.attempt,
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        status=AgentRunStatus.TIMED_OUT if timed_out else AgentRunStatus.FAILED,
        error=AgentFailure(code=code, message=message, transient=transient),
        duration_ms=max(0, duration_ms),
    )


def _http_failure(response: HttpResponse) -> tuple[AgentRunStatus, AgentErrorCode, bool]:
    if response.status_code == 408:
        return AgentRunStatus.TIMED_OUT, AgentErrorCode.TIMEOUT, True
    if response.status_code in {401, 403}:
        return AgentRunStatus.FAILED, AgentErrorCode.AUTHENTICATION_ERROR, False
    if response.status_code == 429:
        code = (
            AgentErrorCode.QUOTA_EXHAUSTED
            if _provider_error_code(response.body)
            in {"billing_hard_limit_reached", "insufficient_quota", "quota_exceeded"}
            else AgentErrorCode.RATE_LIMITED
        )
        return AgentRunStatus.FAILED, code, True
    if response.status_code >= 500:
        return AgentRunStatus.FAILED, AgentErrorCode.PROVIDER_UNAVAILABLE, True
    return AgentRunStatus.FAILED, AgentErrorCode.PROVIDER_ERROR, False


def _provider_error_code(body: bytes) -> str | None:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping) or not isinstance(payload.get("error"), Mapping):
        return None
    value = cast(Mapping[str, object], payload["error"]).get("code")
    return value if isinstance(value, str) else None


def _git(root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ResponsesAgentError("Git worktree inspection failed") from error
    if completed.returncode != 0:
        raise ResponsesAgentError("Git worktree inspection failed")
    return completed.stdout.strip()


def _git_lines(root: Path, *arguments: str) -> tuple[str, ...]:
    return tuple(line for line in _git(root, *arguments).splitlines() if line)


def _workspace_unchanged(root: Path, initial_head: str) -> bool:
    try:
        return _git(root, "rev-parse", "HEAD") == initial_head and not _git(
            root, "status", "--porcelain"
        )
    except ResponsesAgentError:
        return False


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


__all__ = [
    "ResponsesAgentAdapter",
    "ResponsesAgentConfigurationError",
    "ResponsesAgentError",
]
