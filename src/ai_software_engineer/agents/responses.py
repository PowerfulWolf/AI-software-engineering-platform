"""Responses-compatible AgentAdapter with a bounded, policy-checked tool loop."""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from pydantic import TypeAdapter

from ai_software_engineer.agents.continuation import (
    CoderInterruptionControl,
    ContinuationExecutionUncertain,
    InterruptionAdmissionRejected,
    InterruptionObservation,
)
from ai_software_engineer.agents.diagnostics import http_error_detail, safe_diagnostic
from ai_software_engineer.agents.execution import (
    ExecutionGuard,
    SynchronousToolLoopStop,
    execution_scope,
)
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
from ai_software_engineer.agents.workspace_admission import (
    InitialWorkspaceAdmission,
    workspace_admission_for_request,
)
from ai_software_engineer.domain import AgentDefinition, AgentRole
from ai_software_engineer.domain.agent import ROLE_OUTPUTS
from ai_software_engineer.domain.artifact import (
    Artifact,
    CoderProgressArtifact,
    ImplementationReportArtifact,
    PlanArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
    validate_artifact_payload,
)
from ai_software_engineer.domain.coder_work import validate_coder_slice_output
from ai_software_engineer.domain.continuation import ContinuationCause
from ai_software_engineer.domain.model import JsonValue, ReasoningEffort, WirePayload
from ai_software_engineer.execution import CommandResult, SubprocessCommandExecutor
from ai_software_engineer.git import (
    CandidateCommitError,
    CandidateCommitRequest,
    CandidateCommitSkill,
    GitCandidateCommitSkill,
    WorkspacePolicy,
    WorkspacePolicyError,
)
from ai_software_engineer.git.mutation import (
    MutationInventoryRejected,
    WorkspaceMutationInventory,
    capture_mutation_inventory,
)
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.tools import (
    PolicyBoundToolRegistry,
    ReadFileRequest,
    RunCommandRequest,
    WriteFileRequest,
)
from ai_software_engineer.tools.models import ToolRejectedResult


class ResponsesAgentError(AgentError):
    """Base error for Responses adapter configuration and local validation."""


class ResponsesAgentConfigurationError(AgentConfigurationError, ResponsesAgentError):
    """Raised when a Responses route or role workspace is unsafe."""


class _LocalExecutionLimit(RuntimeError):
    """The single monotonic execution window or bounded loop is exhausted."""


@dataclass
class _ExecutionWindow:
    deadline: float
    before: WorkspaceMutationInventory | None = None
    continuation_prompt: str | None = None
    output_present: bool = False
    policy_refused: bool = False
    completed_operations: list[str] = field(default_factory=list)

    def remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _LocalExecutionLimit("Responses execution window exhausted")
        return remaining


class _WindowBoundCommandExecutor:
    """Keep the real restricted executor within the invocation's remaining window."""

    def __init__(self, delegate: SubprocessCommandExecutor, window: _ExecutionWindow) -> None:
        self.delegate, self.window = delegate, window

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        remaining = self.window.remaining()
        return self.delegate.run(
            arguments,
            timeout_seconds=min(timeout_seconds or 600.0, remaining),
        )


class ResponsesAgentAdapter:
    """Run one role through Responses function calls without exposing a shell."""

    def __init__(
        self,
        *,
        workspace_root: str | Path,
        endpoint: str,
        api_key: str,
        model: str,
        reasoning_effort: ReasoningEffort = "medium",
        agent: AgentDefinition,
        prompt_builder: PromptBuilder | None = None,
        context_resolver: ContextResolver | None = None,
        transport: HttpTransport | None = None,
        max_turns: int = 40,
        max_tool_calls: int = 100,
        candidate_commit_skill: CandidateCommitSkill | None = None,
        execution_guard: ExecutionGuard | None = None,
        initial_workspace_admission: InitialWorkspaceAdmission | None = None,
        interruption_control: CoderInterruptionControl | None = None,
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
        if reasoning_effort not in {"low", "medium", "high", "xhigh"}:
            raise ResponsesAgentConfigurationError("Responses reasoning effort is invalid")
        if not 1 <= max_turns <= 100 or not 1 <= max_tool_calls <= 500:
            raise ResponsesAgentConfigurationError("Responses loop bounds are invalid")
        self._execution_guard = execution_guard
        self._initial_admission = initial_workspace_admission
        if interruption_control is not None and agent.role is not AgentRole.CODER:
            raise ResponsesAgentConfigurationError("interruption control is Coder-only")
        self._interruption_control = interruption_control
        self._workspace_root = root
        self._endpoint = _normalize_endpoint(endpoint)
        self._api_key = api_key
        self._model = model
        self._reasoning_effort = reasoning_effort
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
        self._candidate_commit = candidate_commit_skill or GitCandidateCommitSkill(root)
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
        window = _ExecutionWindow(deadline=started + request.timeout_seconds)
        initial_head = _git(self._workspace_root, "rev-parse", "HEAD")
        initial_inventory: WorkspaceMutationInventory | None = None
        try:
            if self._execution_guard is not None:
                self._execution_guard.check()
            window.continuation_prompt = (
                self._interruption_control.prepare(request, self._workspace_root)
                if self._interruption_control is not None
                else None
            )
            _validate_request_binding(
                request,
                self._agent,
                self._workspace_root,
                initial_head,
                self._candidate_commit,
                self._initial_admission if window.continuation_prompt is None else None,
                continuation_admitted=window.continuation_prompt is not None,
            )
            initial_inventory = capture_mutation_inventory(self._workspace_root)
            result = self._execute(request, started, initial_head, initial_inventory, window)
        except ContinuationExecutionUncertain:
            raise
        except InterruptionAdmissionRejected:
            result = _failed(
                request,
                AgentErrorCode.WORK_INTERRUPTED,
                "工程续跑准入校验未通过。未调用后续模型。现场已保留。需要工程处理。",
                duration_ms=_elapsed_ms(started),
            )
        except _LocalExecutionLimit:
            result = self._failure_result(
                request,
                window,
                initial_head,
                initial_inventory,
                started,
                AgentErrorCode.TIMEOUT,
                "本轮执行时间窗口或工具循环额度已耗尽。现场已保留。",
                transient=False,
                cause="local_execution_limit",
                timed_out=True,
            )
        except TimeoutError:
            local_limit = time.monotonic() >= window.deadline
            result = self._failure_result(
                request,
                window,
                initial_head,
                initial_inventory,
                started,
                AgentErrorCode.TIMEOUT,
                "本轮执行时间窗口已耗尽。现场已保留。"
                if local_limit
                else "Responses provider timed out",
                transient=not local_limit,
                timed_out=True,
                cause="local_execution_limit" if local_limit else "provider_transient",
            )
        except OSError:
            local_limit = time.monotonic() >= window.deadline
            result = self._failure_result(
                request,
                window,
                initial_head,
                initial_inventory,
                started,
                AgentErrorCode.TIMEOUT if local_limit else AgentErrorCode.PROVIDER_UNAVAILABLE,
                "本轮执行时间窗口已耗尽。现场已保留。"
                if local_limit
                else "Responses provider is unavailable",
                transient=not local_limit,
                cause="local_execution_limit" if local_limit else "provider_transient",
                timed_out=local_limit,
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
                initial_inventory=initial_inventory,
            )
        except (
            CandidateCommitError,
            ResponsesAgentError,
            WorkspacePolicyError,
            MutationInventoryRejected,
        ):
            result = _safe_failure(
                request,
                self._workspace_root,
                initial_head,
                AgentErrorCode.POLICY_VIOLATION,
                "Responses execution violated its machine boundary",
                transient=False,
                duration_ms=_elapsed_ms(started),
                initial_inventory=initial_inventory,
            )
        self._requests[request.run_id] = request
        self._results[request.run_id] = result
        return result

    def _failure_result(
        self,
        request: AgentRequest,
        window: _ExecutionWindow,
        initial_head: str,
        initial_inventory: WorkspaceMutationInventory | None,
        started: float,
        code: AgentErrorCode,
        message: str,
        *,
        transient: bool,
        cause: ContinuationCause,
        timed_out: bool = False,
    ) -> AgentResult:
        control = self._interruption_control
        if control is not None and cause == "local_execution_limit" and window.output_present:
            raise ContinuationExecutionUncertain(
                "角色模型已返回最终输出, 但本轮执行窗口在产物收尾前已耗尽。完整草稿已保留。"
                "工程负责人需核验已返回产物与当前候选事实; 不得重新调用原执行或跳过独立验收。"
            )
        if (
            control is not None
            and window.before is not None
            and request.role is AgentRole.CODER
            and not window.policy_refused
        ):
            if self._execution_guard is not None:
                self._execution_guard.check()
            stop = SynchronousToolLoopStop.create(
                task_id=request.task_id,
                run_id=request.run_id,
                request_sha256=digest(request.to_wire()),
                completed_operation_ids=tuple(window.completed_operations),
                kind="local_execution_limit" if cause == "local_execution_limit" else "failed",
                stopped_at=datetime.now(UTC),
            )
            try:
                observation = control.interrupted(
                    request,
                    self._workspace_root,
                    before=window.before,
                    cause=cause,
                    original_error_code=code,
                    process_stop=stop,
                    output_present=window.output_present,
                )
            except ContinuationExecutionUncertain:
                raise
            except (InterruptionAdmissionRejected, MutationInventoryRejected):
                return _failed(
                    request,
                    AgentErrorCode.WORK_INTERRUPTED,
                    "工程执行现场无法安全核验。草稿已保留。需要工程处理。",
                    duration_ms=_elapsed_ms(started),
                )
            except WorkspacePolicyError:
                return _safe_failure(
                    request,
                    self._workspace_root,
                    initial_head,
                    AgentErrorCode.POLICY_VIOLATION,
                    "Responses execution violated its machine boundary",
                    transient=False,
                    duration_ms=_elapsed_ms(started),
                    initial_inventory=initial_inventory,
                )
            if observation is not InterruptionObservation.UNCHANGED:
                return _failed(
                    request,
                    AgentErrorCode.WORK_INTERRUPTED,
                    "工程执行已中断。草稿已保留。"
                    + (
                        "平台已核验同步工具均已返回。将通过新的执行记录继续。"
                        if observation is InterruptionObservation.CAPTURED
                        else "现场不满足自动继续条件。需要工程处理。"
                    ),
                    duration_ms=_elapsed_ms(started),
                )
        return _safe_failure(
            request,
            self._workspace_root,
            initial_head,
            code,
            message,
            transient=transient,
            duration_ms=_elapsed_ms(started),
            timed_out=timed_out,
            initial_inventory=initial_inventory,
        )

    def _execute(
        self,
        request: AgentRequest,
        started: float,
        initial_head: str,
        initial_inventory: WorkspaceMutationInventory,
        window: _ExecutionWindow,
    ) -> AgentResult:
        registry = PolicyBoundToolRegistry(
            self._workspace_root,
            self._agent,
            run_id=request.run_id,
            command_executor=_WindowBoundCommandExecutor(
                SubprocessCommandExecutor(
                    self._workspace_root,
                    self._agent.permissions,
                    execution_guard=self._execution_guard,
                    require_focused_tests=request.role in {AgentRole.QA, AgentRole.REVIEWER},
                ),
                window,
            ),
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
        if window.continuation_prompt is not None:
            input_items.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": window.continuation_prompt,
                        }
                    ],
                }
            )
        for attachment in prompt.images:
            input_items.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": attachment.label},
                        {
                            "type": "input_image",
                            "image_url": attachment.image.data_url(),
                            "detail": "high",
                        },
                    ],
                }
            )
        tool_calls = 0
        latest_usage: AgentUsage | None = None
        if self._interruption_control is not None:
            window.before = self._interruption_control.started(request, self._workspace_root)
        window.remaining()
        for turn in range(1, self._max_turns + 1):
            if self._execution_guard is not None:
                self._execution_guard.check()
            body = _request_body(
                self._model,
                input_items,
                request.role,
                reasoning_effort=self._reasoning_effort,
            )
            response = self._transport.post(
                self._endpoint,
                {
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                body,
                window.remaining(),
            )
            if self._execution_guard is not None:
                self._execution_guard.check()
            if not 200 <= response.status_code < 300:
                window.remaining()
                status, code, transient = _http_failure(response)
                message = (
                    f"Responses provider returned HTTP {response.status_code}; "
                    + http_error_detail(response.body, self._api_key)
                )
                if transient:
                    return self._failure_result(
                        request,
                        window,
                        initial_head,
                        initial_inventory,
                        started,
                        code,
                        message,
                        transient=True,
                        cause="provider_transient",
                        timed_out=status is AgentRunStatus.TIMED_OUT,
                    )
                return _safe_failure(
                    request,
                    self._workspace_root,
                    initial_head,
                    code,
                    message,
                    transient=False,
                    duration_ms=_elapsed_ms(started),
                    initial_inventory=initial_inventory,
                )
            # A returned 2xx body may already contain the final artifact. Resolve
            # that fact before the deadline check can seal an absent-output stop.
            # Parsing is bounded by the transport response byte limit; no tool
            # or candidate action is authorized merely by receiving this body.
            window.output_present = True
            payload = _response_payload(response)
            latest_usage = _usage(payload) or latest_usage
            calls = _function_calls(payload)
            if calls:
                try:
                    returned_artifact = _decode_artifact_output(_output_text(payload))
                except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                    window.output_present = False
                else:
                    window.output_present = returned_artifact.kind in ROLE_OUTPUTS[request.role]
                window.remaining()
                response_items = _conversation_output(payload)
                outputs: list[WirePayload] = []
                for call_id, name, arguments in calls:
                    tool_calls += 1
                    if tool_calls > self._max_tool_calls:
                        raise _LocalExecutionLimit("Responses tool-call budget exceeded")
                    window.remaining()
                    tool_request = _tool_request(
                        request,
                        name,
                        arguments,
                        operation_id=f"tool.responses.{turn:02d}.{tool_calls:03d}",
                    )
                    if self._execution_guard is not None:
                        self._execution_guard.check()
                    if name == "write_file":
                        with execution_scope(self._execution_guard):
                            tool_result = registry.execute(tool_request)
                    else:
                        tool_result = registry.execute(tool_request)
                    window.completed_operations.append(tool_request.operation_id)
                    if self._execution_guard is not None:
                        self._execution_guard.check()
                    if isinstance(
                        tool_result, ToolRejectedResult
                    ) and tool_result.error_code not in {
                        "COMMAND_TIMED_OUT",
                        "COMMAND_FAILED_TO_START",
                    }:
                        window.policy_refused = True
                        raise WorkspacePolicyError("Responses tool request was rejected")
                    window.remaining()
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
                # Compatible gateways need not retain response IDs. Carry exact
                # assistant output (including reasoning) and tool receipts within
                # this bounded invocation instead of relying on server storage.
                input_items = [*input_items, *response_items, *outputs]
                continue
            content = _output_text(payload)
            window.output_present = True
            window.remaining()
            artifact = _decode_artifact_output(content)
            if artifact.kind not in ROLE_OUTPUTS[request.role]:
                raise ValueError("provider Artifact is outside the role contract")
            artifact = _normalize_producer(artifact, request, self._agent)
            window.remaining()
            if self._interruption_control is not None and window.before is not None:
                self._interruption_control.finished(
                    request, self._workspace_root, before=window.before
                )
            window.remaining()
            with execution_scope(self._execution_guard):
                artifact = _finalize_coder_candidate(
                    request,
                    initial_head,
                    artifact,
                    self._candidate_commit,
                )
                _validate_git_result(
                    self._workspace_root,
                    request,
                    initial_head,
                    artifact,
                    self._candidate_commit,
                )
            window.remaining()
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
        raise _LocalExecutionLimit("Responses turn budget exceeded")


def _request_body(
    model: str,
    input_items: list[WirePayload],
    role: AgentRole,
    *,
    reasoning_effort: ReasoningEffort,
) -> bytes:
    payload: WirePayload = {
        "model": model,
        "reasoning": {"effort": reasoning_effort},
        "store": False,
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
    return [cast(WirePayload, strict_output_schema(definition)) for definition in definitions]


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


def _conversation_output(payload: Mapping[str, object]) -> list[WirePayload]:
    output = payload.get("output")
    if not isinstance(output, list) or not output:
        raise ValueError("Responses tool turn has no replayable output")
    items: list[WirePayload] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") not in {
            "function_call",
            "reasoning",
            "message",
        }:
            raise ValueError("Responses output item is not supported")
        if item["type"] == "message" and item.get("role") != "assistant":
            raise ValueError("Responses output cannot change instruction roles")
        items.append(cast(WirePayload, item))
    return items


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
        schema = TypeAdapter(CoderProgressArtifact | ImplementationReportArtifact).json_schema()
    elif role is AgentRole.QA:
        schema = QaReportArtifact.model_json_schema()
    else:
        schema = ReviewReportArtifact.model_json_schema()
    normalized = strict_output_schema(cast(dict[str, object], schema))
    definitions = cast(dict[str, object], normalized.pop("$defs", {}))
    if role is AgentRole.QA:
        # Domain environment metadata is a free-form JSON object. Strict output
        # cannot express arbitrary object keys; encode this optional metadata as
        # JSON text on the provider wire, then decode before domain validation.
        qa_content = cast(dict[str, object], definitions["QaReportContent"])
        properties = cast(dict[str, object], qa_content["properties"])
        properties["environment"] = {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "Optional environment metadata as a JSON-encoded object string.",
        }
        definitions.pop("JsonValue", None)
    # A Coder may return progress or implementation. Keep the union below an
    # object root, as required by Responses strict structured outputs.
    return {
        "type": "object",
        "properties": {"artifact": normalized},
        "required": ["artifact"],
        "additionalProperties": False,
        "$defs": definitions,
    }


def _decode_artifact_output(content: str) -> Artifact:
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("Responses artifact output must be an object")
    if "artifact" in payload:
        if set(payload) != {"artifact"} or not isinstance(payload["artifact"], dict):
            raise ValueError("Responses artifact envelope is invalid")
        payload = payload["artifact"]
    # Bare artifacts from older compatible providers remain domain-validated.
    body = payload.get("content")
    if payload.get("kind") == "qa-report" and isinstance(body, dict):
        environment = body.get("environment")
        if isinstance(environment, str):
            decoded = json.loads(environment)
            if not isinstance(decoded, dict):
                raise ValueError("QA environment metadata must decode to an object")
            body["environment"] = decoded
    return validate_artifact_payload(payload)


def _validate_request_binding(
    request: AgentRequest,
    agent: AgentDefinition,
    root: Path,
    initial_head: str,
    candidate_commit: CandidateCommitSkill,
    initial_admission: InitialWorkspaceAdmission | None = None,
    *,
    continuation_admitted: bool = False,
) -> None:
    if request.role is not agent.role or request.permissions != agent.permissions:
        raise ResponsesAgentConfigurationError("AgentRequest does not match bound AgentDefinition")
    source = _git(root, "rev-parse", "--verify", f"{request.source_revision}^{{commit}}")
    if initial_head != source:
        raise ResponsesAgentConfigurationError(
            "Responses worktree is not at the requested source revision"
        )
    if continuation_admitted:
        # Only the trusted control's exact one-use admission can reach this seam.
        return
    if (admission := workspace_admission_for_request(initial_admission, request)) is not None:
        if request.role is not AgentRole.CODER:
            raise ResponsesAgentConfigurationError("workspace seed admission is Coder-only")
        admission.authorize(request, root)
        return
    observed = candidate_commit.changed_paths()
    if request.continuation_checkpoint_id is None:
        if observed:
            raise ResponsesAgentConfigurationError("Responses worktree must be clean")
    elif observed != request.continuation_changed_paths:
        raise ResponsesAgentConfigurationError(
            "Responses continuation worktree does not match the checkpoint"
        )
    else:
        policy = WorkspacePolicy(root, request.permissions)
        for path in observed:
            policy.authorize_write(path)


def _finalize_coder_candidate(
    request: AgentRequest,
    initial_head: str,
    artifact: Artifact,
    skill: CandidateCommitSkill,
) -> Artifact:
    if request.work_slice is not None:
        validate_coder_slice_output(request.work_slice, artifact)
    if request.role is not AgentRole.CODER or isinstance(artifact, CoderProgressArtifact):
        return artifact
    if not isinstance(artifact, ImplementationReportArtifact):
        raise ValueError("Coder did not return a supported output")
    observed = skill.changed_paths()
    if not observed:
        return artifact
    if artifact.source_revision != initial_head or artifact.content.commit_sha != initial_head:
        raise ValueError("Coder draft does not bind the immutable source revision")
    reported = tuple(sorted(item.path for item in artifact.content.changed_files))
    result = skill.finalize(
        CandidateCommitRequest(
            task_id=request.task_id,
            source_revision=initial_head,
            reported_paths=reported,
            permissions=request.permissions,
        )
    )
    return artifact.model_copy(
        update={
            "source_revision": result.candidate_revision,
            "content": artifact.content.model_copy(
                update={"commit_sha": result.candidate_revision}
            ),
        }
    )


def _validate_git_result(
    root: Path,
    request: AgentRequest,
    initial_head: str,
    artifact: Artifact,
    skill: CandidateCommitSkill,
) -> None:
    final_head = _git(root, "rev-parse", "HEAD")
    if request.role is not AgentRole.CODER:
        if _git(root, "status", "--porcelain"):
            raise WorkspacePolicyError("role left uncommitted worktree changes")
        if final_head != initial_head:
            raise WorkspacePolicyError("read-only role changed worktree revision")
        return
    if isinstance(artifact, CoderProgressArtifact):
        if final_head != initial_head or artifact.source_revision != initial_head:
            raise WorkspacePolicyError("Coder progress cannot create a candidate revision")
        changed = skill.changed_paths()
        reported = tuple(sorted(item.path for item in artifact.content.changed_files))
        if changed != reported:
            raise WorkspacePolicyError("Coder progress does not match the dirty worktree")
        policy = WorkspacePolicy(root, request.permissions)
        for path in changed:
            policy.authorize_write(path)
        return
    if _git(root, "status", "--porcelain"):
        raise WorkspacePolicyError("role left uncommitted worktree changes")
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
    initial_inventory: WorkspaceMutationInventory | None = None,
) -> AgentResult:
    if not _workspace_unchanged(root, initial_head, initial_inventory):
        code = AgentErrorCode.POLICY_VIOLATION
        # A dirty provider failure is never eligible for fallback or automatic
        # retry, but discarding the already classified provider error makes
        # recovery needlessly opaque.  The caller's message is already bounded
        # for HTTP failures; sanitize and bound it again here because this is
        # the common safety boundary for transport, decoding and policy errors.
        detail = safe_diagnostic(message, limit=240)
        message = f"failed provider route left repository changes; provider_diagnostic={detail}"
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


def _failed(
    request: AgentRequest,
    code: AgentErrorCode,
    message: str,
    *,
    duration_ms: int,
) -> AgentResult:
    return AgentResult(
        run_id=request.run_id,
        task_id=request.task_id,
        role=request.role,
        attempt=request.attempt,
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        status=AgentRunStatus.FAILED,
        error=AgentFailure(code=code, message=message, transient=False),
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


def _workspace_unchanged(
    root: Path, initial_head: str, initial_inventory: WorkspaceMutationInventory | None = None
) -> bool:
    try:
        if _git(root, "rev-parse", "HEAD") != initial_head:
            return False
        if initial_inventory is not None:
            return capture_mutation_inventory(root) == initial_inventory
        return not _git(root, "status", "--porcelain")
    except (ResponsesAgentError, MutationInventoryRejected):
        return False


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


__all__ = [
    "ResponsesAgentAdapter",
    "ResponsesAgentConfigurationError",
    "ResponsesAgentError",
]
