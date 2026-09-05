"""Public-seam contract tests for the OpenAI-compatible AgentAdapter."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentRequest,
    AgentRequestConflict,
    AgentRunStatus,
    ContextPromptBuilder,
    HttpResponse,
    OpenAICompatibleAgentAdapter,
    OpenAICompatibleConfigurationError,
    PromptMessage,
    PromptPayload,
    StoredContextResolver,
)
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.context import (
    ContextBudget,
    ContextBundle,
    ContextSection,
    InMemoryContextStore,
)
from ai_software_engineer.domain import AgentPermissions, AgentRole, NetworkAccess
from ai_software_engineer.domain.artifact import Artifact, ImplementationReportArtifact
from ai_software_engineer.orchestration import FileRunContextBuilder
from tests.domain.factories import (
    NOW,
    make_agent,
    make_implementation_artifact,
    make_plan_artifact,
    make_task,
)

CONTEXT_ID = "ctx_" + "c" * 64
TASK_ID = "task_domain_001"


def _request(
    role: AgentRole,
    *,
    run_id: str = "run_real_001",
    attempt: int = 1,
    source_revision: str = "b" * 40,
    context_manifest_id: str = CONTEXT_ID,
) -> AgentRequest:
    output_schema = {
        AgentRole.ORCHESTRATOR: "schemas/plan.schema.json",
        AgentRole.CODER: "schemas/implementation-report.schema.json",
        AgentRole.QA: "schemas/qa-report.schema.json",
        AgentRole.REVIEWER: "schemas/review-report.schema.json",
    }[role]
    return AgentRequest(
        run_id=run_id,
        task_id=TASK_ID,
        role=role,
        attempt=attempt,
        source_revision=source_revision,
        context_manifest_id=context_manifest_id,
        input_artifact_ids=(),
        permissions=AgentPermissions(
            read_paths=("src/**", "tests/**"),
            write_paths=("src/**", "tests/**"),
            commands=("pytest",),
            network=NetworkAccess.NONE,
        ),
        output_schema=output_schema,
        timeout_seconds=60,
    )


def _align(artifact: Artifact, request: AgentRequest) -> Artifact:
    return artifact.model_copy(
        update={
            "task_id": request.task_id,
            "source_revision": request.source_revision,
            "context_manifest_id": request.context_manifest_id,
            "producer": artifact.producer.model_copy(update={"run_id": request.run_id}),
        }
    )


@dataclass
class RecordingTransport:
    response: HttpResponse | None = None
    error: BaseException | None = None

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, str], bytes, float]] = []

    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> HttpResponse:
        self.calls.append((url, headers, body, timeout_seconds))
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AssertionError("recording transport has no response")
        return self.response


class StaticPromptBuilder:
    def __init__(self, payload: PromptPayload | None = None) -> None:
        self.requests: list[AgentRequest] = []
        self.payload = payload or PromptPayload(
            messages=(
                PromptMessage(role="system", content="machine policy"),
                PromptMessage(role="user", content="return the artifact as JSON"),
            )
        )

    def build(self, request: AgentRequest) -> PromptPayload:
        self.requests.append(request)
        return self.payload


class RecordingContextResolver:
    def __init__(self, context: ContextBundle, artifact: Artifact) -> None:
        self.context = context
        self.artifact = artifact

    def get_context(self, context_manifest_id: str) -> ContextBundle:
        assert context_manifest_id == self.context.context_id
        return self.context

    def get_artifact(self, artifact_id: str) -> Artifact:
        assert artifact_id == self.artifact.artifact_id
        return self.artifact


def _coder_request(*, run_id: str = "run_real_001") -> AgentRequest:
    return _request(AgentRole.CODER, run_id=run_id)


def _provider_body(artifact: Artifact) -> bytes:
    response = {"choices": [{"message": {"content": json.dumps(artifact.to_wire())}}]}
    return json.dumps(response).encode("utf-8")


def _adapter(transport: RecordingTransport) -> OpenAICompatibleAgentAdapter:
    return OpenAICompatibleAgentAdapter(
        endpoint="https://model.example.invalid/v1",
        api_key="secret-provider-key",
        model="test-model",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        transport=transport,
    )


def test_real_adapter_posts_typed_prompt_and_returns_typed_artifact() -> None:
    request = _coder_request()
    artifact = _align(make_implementation_artifact(), request)
    transport = RecordingTransport(
        response=HttpResponse(status_code=200, body=_provider_body(artifact))
    )

    result = _adapter(transport).run(request)

    assert result.status is AgentRunStatus.SUCCEEDED
    assert isinstance(result.artifact, ImplementationReportArtifact)
    assert result.artifact == artifact
    assert result.error is None
    assert len(transport.calls) == 1
    url, headers, body, timeout = transport.calls[0]
    assert url == "https://model.example.invalid/v1/chat/completions"
    assert headers["Authorization"] == "Bearer secret-provider-key"
    assert headers["Content-Type"] == "application/json"
    assert timeout == request.timeout_seconds
    payload = json.loads(body)
    assert payload["model"] == "test-model"
    assert payload["temperature"] == 0
    assert payload["stream"] is False
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["messages"][0]["content"] == "machine policy"


def test_fenced_json_response_is_accepted() -> None:
    request = _coder_request()
    artifact = _align(make_implementation_artifact(), request)
    response = {
        "choices": [{"message": {"content": f"```json\n{json.dumps(artifact.to_wire())}\n```"}}]
    }
    transport = RecordingTransport(
        response=HttpResponse(status_code=200, body=json.dumps(response).encode("utf-8"))
    )

    result = _adapter(transport).run(request)

    assert result.status is AgentRunStatus.SUCCEEDED
    assert result.artifact == artifact


@pytest.mark.parametrize(
    ("status_code", "expected_status", "expected_code", "transient"),
    (
        (400, AgentRunStatus.FAILED, AgentErrorCode.PROVIDER_ERROR, False),
        (401, AgentRunStatus.FAILED, AgentErrorCode.AUTHENTICATION_ERROR, False),
        (408, AgentRunStatus.TIMED_OUT, AgentErrorCode.TIMEOUT, True),
        (429, AgentRunStatus.FAILED, AgentErrorCode.RATE_LIMITED, True),
        (500, AgentRunStatus.FAILED, AgentErrorCode.PROVIDER_UNAVAILABLE, True),
        (503, AgentRunStatus.FAILED, AgentErrorCode.PROVIDER_UNAVAILABLE, True),
    ),
)
def test_provider_http_errors_never_return_artifact_or_leak_response(
    status_code: int,
    expected_status: AgentRunStatus,
    expected_code: AgentErrorCode,
    transient: bool,
) -> None:
    transport = RecordingTransport(
        response=HttpResponse(
            status_code=status_code,
            body=b'{"error":{"message":"secret-provider-key should not escape"}}',
        )
    )

    result = _adapter(transport).run(_coder_request())

    assert result.status is expected_status
    assert result.artifact is None
    assert result.error is not None
    assert result.error.code is expected_code
    assert result.error.transient is transient
    assert "secret-provider-key" not in result.error.message


def test_quota_response_is_classified_without_leaking_provider_body() -> None:
    transport = RecordingTransport(
        response=HttpResponse(
            status_code=429,
            body=b'{"error":{"code":"insufficient_quota","message":"secret"}}',
        )
    )

    result = _adapter(transport).run(_coder_request())

    assert result.error is not None
    assert result.error.code is AgentErrorCode.QUOTA_EXHAUSTED
    assert "secret" not in result.error.message


def test_transport_timeout_maps_to_typed_timeout() -> None:
    transport = RecordingTransport(error=TimeoutError("socket timed out"))

    result = _adapter(transport).run(_coder_request())

    assert result.status is AgentRunStatus.TIMED_OUT
    assert result.artifact is None
    assert result.error is not None
    assert result.error.code is AgentErrorCode.TIMEOUT
    assert result.error.transient is True


def test_transport_connection_error_maps_to_transient_provider_error() -> None:
    transport = RecordingTransport(error=OSError("connection refused"))

    result = _adapter(transport).run(_coder_request())

    assert result.status is AgentRunStatus.FAILED
    assert result.artifact is None
    assert result.error is not None
    assert result.error.code is AgentErrorCode.PROVIDER_ERROR
    assert result.error.transient is True


def test_responses_output_text_is_accepted() -> None:
    request = _coder_request()
    artifact = _align(make_implementation_artifact(), request)
    response = {"output_text": json.dumps(artifact.to_wire())}
    transport = RecordingTransport(
        response=HttpResponse(status_code=200, body=json.dumps(response).encode("utf-8"))
    )

    result = _adapter(transport).run(request)

    assert result.status is AgentRunStatus.SUCCEEDED
    assert result.artifact == artifact


def test_invalid_provider_json_maps_to_invalid_output_without_verdict() -> None:
    transport = RecordingTransport(
        response=HttpResponse(status_code=200, body=b'{"choices":[{"message":{"content":"oops"}}]}')
    )

    result = _adapter(transport).run(_coder_request())

    assert result.status is AgentRunStatus.FAILED
    assert result.artifact is None
    assert result.error is not None
    assert result.error.code is AgentErrorCode.INVALID_OUTPUT
    assert result.error.transient is False


def test_artifact_identity_mismatch_is_invalid_output() -> None:
    request = _coder_request()
    artifact = _align(make_implementation_artifact(), request).model_copy(
        update={"context_manifest_id": "ctx_" + "d" * 64}
    )
    transport = RecordingTransport(
        response=HttpResponse(status_code=200, body=_provider_body(artifact))
    )

    result = _adapter(transport).run(request)

    assert result.status is AgentRunStatus.FAILED
    assert result.artifact is None
    assert result.error is not None
    assert result.error.code is AgentErrorCode.INVALID_OUTPUT


def test_same_run_replays_exact_result_and_conflict_does_not_call_provider_twice() -> None:
    request = _coder_request()
    artifact = _align(make_implementation_artifact(), request)
    transport = RecordingTransport(
        response=HttpResponse(status_code=200, body=_provider_body(artifact))
    )
    adapter = _adapter(transport)

    first = adapter.run(request)
    replay = adapter.run(request)

    assert replay == first
    assert len(transport.calls) == 1

    with pytest.raises(AgentRequestConflict):
        adapter.run(request.model_copy(update={"attempt": 2}))
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "endpoint",
    ("file:///tmp/provider", "https://user:secret@model.example.invalid/v1"),
)
def test_endpoint_must_be_safe_http_url(endpoint: str) -> None:
    with pytest.raises(OpenAICompatibleConfigurationError, match="endpoint"):
        OpenAICompatibleAgentAdapter(
            endpoint=endpoint,
            api_key=None,
            model="model",
            agent_id="agent_coder_001",
            agent_version="v0.1",
            prompt_builder=StaticPromptBuilder(),
            transport=RecordingTransport(),
        )


def test_context_prompt_builder_keeps_machine_policy_in_system_message() -> None:
    request = _coder_request()
    artifact = _align(make_implementation_artifact(), request)
    request = request.model_copy(update={"input_artifact_ids": (artifact.artifact_id,)})
    context = ContextBundle(
        context_id=request.context_manifest_id,
        task_id=request.task_id,
        role=request.role,
        attempt=request.attempt,
        source_revision=request.source_revision,
        sections=(
            ContextSection(
                name="policy",
                uri="policy://permissions",
                sha256="a" * 64,
                tokens=1,
                content='{"write_paths":["src/**"]}',
                priority=0,
            ),
            ContextSection(
                name="task",
                uri=f"task://{request.task_id}",
                sha256="b" * 64,
                tokens=1,
                content="untrusted task data",
                priority=30,
            ),
            ContextSection(
                name=f"source:artifact.{artifact.artifact_id}",
                uri=f"artifact://{artifact.artifact_id}",
                sha256="c" * 64,
                tokens=1,
                content=json.dumps(artifact.to_wire()),
                priority=60,
            ),
        ),
        budget=ContextBudget(max_input_tokens=10, reserved_output_tokens=2, used_input_tokens=3),
        built_at=NOW,
    )

    payload = ContextPromptBuilder(RecordingContextResolver(context, artifact)).build(request)

    assert payload.messages[0].role == "system"
    assert "MACHINE_POLICY" in payload.messages[0].content
    assert payload.messages[1].role == "user"
    assert request.context_manifest_id in payload.messages[1].content
    assert artifact.artifact_id in payload.messages[1].content


def test_context_prompt_builder_rejects_cross_task_input_artifact() -> None:
    request = _coder_request()
    context = ContextBundle(
        context_id=request.context_manifest_id,
        task_id=request.task_id,
        role=request.role,
        attempt=request.attempt,
        source_revision=request.source_revision,
        sections=(
            ContextSection(
                name="policy",
                uri="policy://permissions",
                sha256="a" * 64,
                tokens=1,
                content="policy",
                priority=0,
            ),
        ),
        budget=ContextBudget(max_input_tokens=10, reserved_output_tokens=2, used_input_tokens=1),
        built_at=NOW,
    )
    other_task_artifact = make_implementation_artifact().model_copy(
        update={"task_id": "task_other_001"}
    )

    with pytest.raises(OpenAICompatibleConfigurationError, match="another Task"):
        ContextPromptBuilder(RecordingContextResolver(context, other_task_artifact)).build(
            request.model_copy(update={"input_artifact_ids": (other_task_artifact.artifact_id,)})
        )


def test_stored_context_resolver_bridges_context_and_artifact_stores(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    task = make_task().model_copy(update={"repository": str(project)})
    context = FileRunContextBuilder(project).build(task, make_agent(), attempt=1)
    plan = make_plan_artifact().model_copy(update={"task_id": task.id})
    sealed_plan: Artifact = seal_artifact(plan, validated_at=NOW)
    contexts = InMemoryContextStore()
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    contexts.put(context)
    artifacts.put(sealed_plan)
    resolver = StoredContextResolver(contexts, artifacts)

    assert resolver.get_context(context.context_id) == context
    assert resolver.get_artifact(sealed_plan.artifact_id) == sealed_plan


def test_default_prompt_builder_does_not_invent_success_without_context() -> None:
    request = _coder_request()
    transport = RecordingTransport(response=HttpResponse(status_code=200, body=b"{}"))
    adapter = OpenAICompatibleAgentAdapter(
        endpoint="https://model.example.invalid/v1",
        api_key=None,
        model="model",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        transport=transport,
    )

    result = adapter.run(request)

    assert result.status is AgentRunStatus.FAILED
    assert result.error is not None
    assert result.error.code is AgentErrorCode.INVALID_OUTPUT
