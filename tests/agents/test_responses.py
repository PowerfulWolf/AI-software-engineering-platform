"""Responses-compatible tool loop tests with real Git and a scripted provider."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentRequest,
    AgentRunStatus,
    HttpResponse,
    ResponsesAgentAdapter,
)
from ai_software_engineer.agents.responses import (
    _artifact_schema,
    _decode_artifact_output,
    _request_body,
)
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentPermissions,
    AgentRole,
    ArtifactKind,
    ChangedFile,
    ChangeType,
    NetworkAccess,
    QaReportArtifact,
)
from ai_software_engineer.tools import PolicyBoundToolRegistry, ToolRequest, ToolResult
from tests.agents.test_openai_compatible import StaticPromptBuilder, _coder_request
from tests.domain.factories import make_implementation_artifact, make_qa_artifact


@pytest.mark.parametrize("role", list(AgentRole))
def test_all_strict_function_parameters_are_required(role: AgentRole) -> None:
    payload = json.loads(_request_body("model", [], role, reasoning_effort="high"))
    for tool in payload["tools"]:
        schema = tool["parameters"]
        assert tool["strict"] is True
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["additionalProperties"] is False


@pytest.mark.parametrize("role", list(AgentRole))
def test_artifact_transport_schema_has_closed_objects_and_object_root(role: AgentRole) -> None:
    payload = json.loads(_request_body("model", [], role, reasoning_effort="high"))
    schema = payload["text"]["format"]["schema"]
    assert schema.get("type") == "object"
    assert "anyOf" not in schema

    def require_closed_objects(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value.get("additionalProperties") is False
            for child in value.values():
                require_closed_objects(child)
        elif isinstance(value, list):
            for child in value:
                require_closed_objects(child)

    require_closed_objects(schema)


def test_qa_transport_preserves_environment_and_domain_validation() -> None:
    artifact = make_qa_artifact()
    payload = artifact.model_dump(mode="json")
    environment = {"compiler": "swift", "checks": {"count": 2, "passed": True}}
    payload["content"]["environment"] = json.dumps(environment)
    # New strict outputs carry every field; persisted legacy reports omit empty observations.
    payload["content"]["project_observations"] = []
    wire = {"artifact": payload}
    Draft202012Validator(_artifact_schema(AgentRole.QA)).validate(wire)
    decoded = _decode_artifact_output(json.dumps(wire))
    assert isinstance(decoded, QaReportArtifact)
    assert decoded.content.environment == environment
    assert _decode_artifact_output(json.dumps(artifact.to_wire())) == artifact
    payload["content"]["criteria_results"][0]["status"] = "NOT_TESTED"
    with pytest.raises(ValueError):
        _decode_artifact_output(json.dumps(wire))


@pytest.mark.parametrize("environment", ["[]", "null", "invalid json"])
def test_qa_transport_rejects_non_object_environment(environment: str) -> None:
    payload = make_qa_artifact().model_dump(mode="json")
    payload["content"]["environment"] = environment
    with pytest.raises(ValueError):
        _decode_artifact_output(json.dumps({"artifact": payload}))


def test_artifact_transport_rejects_extra_envelope_fields() -> None:
    with pytest.raises(ValueError, match="envelope"):
        _decode_artifact_output(
            json.dumps({"artifact": make_qa_artifact().to_wire(), "override": True})
        )


def test_http_error_detail_is_bounded_and_redacts_the_configured_key(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    request, definition = _request(base)

    class InvalidSchema:
        def post(
            self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
        ) -> HttpResponse:
            return HttpResponse(
                status_code=400,
                body=json.dumps(
                    {"error": {"message": "Missing required max_bytes test-key " + "x" * 600}}
                ).encode(),
            )

    result = ResponsesAgentAdapter(
        workspace_root=root,
        endpoint="https://example.invalid/v1",
        api_key="test-key",
        model="model",
        agent=definition,
        prompt_builder=StaticPromptBuilder(),
        transport=InvalidSchema(),
    ).run(request)
    assert result.error is not None
    assert result.error.code is AgentErrorCode.PROVIDER_ERROR
    assert "Missing required max_bytes" in result.error.message
    assert "test-key" not in result.error.message
    assert len(result.error.message) <= 500


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "target"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "agent@example.invalid")
    _git(root, "config", "user.name", "Agent Test")
    (root / "src").mkdir()
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "initial")
    return root, _git(root, "rev-parse", "HEAD")


def _request(base: str) -> tuple[AgentRequest, AgentDefinition]:
    permissions = AgentPermissions(
        read_paths=("**",),
        write_paths=("src/**", "tests/**"),
        commands=("git status", "git diff", "git add", "git commit", "pytest"),
        network=NetworkAccess.MODEL_ENDPOINT_ONLY,
    )
    request = _coder_request().model_copy(
        update={"source_revision": base, "permissions": permissions}
    )
    definition = AgentDefinition(
        id="agent_coder_responses",
        role=AgentRole.CODER,
        version="v0.1",
        provider="qwen",
        model="qwen3.8-max",
        permissions=permissions,
        input_artifacts=(ArtifactKind.PLAN, ArtifactKind.QA_REPORT, ArtifactKind.REVIEW_REPORT),
        output_artifacts=(ArtifactKind.CODER_PROGRESS, ArtifactKind.IMPLEMENTATION_REPORT),
        max_retries=0,
        timeout_seconds=60,
    )
    return request, definition


class _CoderTransport:
    def __init__(self, root: Path, request: AgentRequest, *, extra_tool_turn: bool = False) -> None:
        self.root = root
        self.request = request
        self.extra_tool_turn = extra_tool_turn
        self.calls: list[Mapping[str, object]] = []

    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> HttpResponse:
        del timeout_seconds
        assert url.endswith("/responses")
        assert headers["Authorization"] == "Bearer test-key"
        payload = json.loads(body)
        self.calls.append(payload)
        if len(self.calls) == 1:
            return HttpResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "id": "resp_tool_001",
                        "output": [
                            {
                                "type": "reasoning",
                                "id": "rs_test",
                                "summary": [],
                                "encrypted_content": "opaque-reasoning",
                            },
                            {
                                "type": "function_call",
                                "call_id": "call_write",
                                "name": "write_file",
                                "arguments": json.dumps(
                                    {"path": "src/change.py", "content": "VALUE = 1\n"}
                                ),
                            },
                            {
                                "type": "function_call",
                                "call_id": "call_add",
                                "name": "run_command",
                                "arguments": json.dumps({"argv": ["git", "add", "src/change.py"]}),
                            },
                            {
                                "type": "function_call",
                                "call_id": "call_commit",
                                "name": "run_command",
                                "arguments": json.dumps(
                                    {"argv": ["git", "commit", "-m", "candidate"]}
                                ),
                            },
                        ],
                    }
                ).encode(),
            )
        candidate = _git(self.root, "rev-parse", "HEAD")
        if "previous_response_id" in payload:
            return HttpResponse(
                status_code=400,
                body=b'{"error":{"message":"Previous response not found."}}',
            )
        if self.extra_tool_turn and len(self.calls) == 2:
            return HttpResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "output": [
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": "Verify candidate."}],
                            },
                            {
                                "type": "function_call",
                                "call_id": "call_status",
                                "name": "run_command",
                                "arguments": json.dumps({"argv": ["git", "status", "--porcelain"]}),
                            },
                        ]
                    }
                ).encode(),
            )
        template = make_implementation_artifact()
        artifact = template.model_copy(
            update={
                "task_id": self.request.task_id,
                "source_revision": candidate,
                "context_manifest_id": self.request.context_manifest_id,
                "parent_artifact_ids": self.request.input_artifact_ids,
                "producer": template.producer.model_copy(update={"run_id": self.request.run_id}),
                "content": template.content.model_copy(
                    update={
                        "commit_sha": candidate,
                        "changed_files": (
                            ChangedFile(
                                path="src/change.py",
                                change=ChangeType.ADDED,
                                lines_added=1,
                                lines_deleted=0,
                            ),
                        ),
                    }
                ),
            }
        )
        return HttpResponse(
            status_code=200,
            body=json.dumps(
                {
                    "id": "resp_final_001",
                    "output_text": json.dumps({"artifact": artifact.to_wire()}),
                    "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
                }
            ).encode(),
        )


class _DirtyFailureTransport:
    def __init__(self, root: Path) -> None:
        self.root = root

    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> HttpResponse:
        del url, headers, body, timeout_seconds
        target = self.root / "src" / "partial.py"
        target.parent.mkdir(exist_ok=True)
        target.write_text("partial = True\n", encoding="utf-8")
        return HttpResponse(status_code=429, body=b'{"error":{"code":"quota_exceeded"}}')


@pytest.mark.parametrize("extra_tool_turn", [False, True])
def test_responses_tool_loop_creates_and_validates_coder_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra_tool_turn: bool
) -> None:
    root, base = _repository(tmp_path)
    request, definition = _request(base)
    transport = _CoderTransport(root, request, extra_tool_turn=extra_tool_turn)
    executed: list[ToolRequest] = []
    original_execute = PolicyBoundToolRegistry.execute

    def record_execute(registry: PolicyBoundToolRegistry, tool: ToolRequest) -> ToolResult:
        executed.append(tool)
        return original_execute(registry, tool)

    monkeypatch.setattr(PolicyBoundToolRegistry, "execute", record_execute)
    adapter = ResponsesAgentAdapter(
        workspace_root=root,
        endpoint="https://example.invalid/v1/responses",
        api_key="test-key",
        model="qwen3.8-max",
        reasoning_effort="high",
        agent=definition,
        prompt_builder=StaticPromptBuilder(),
        transport=transport,
    )

    result = adapter.run(request)

    assert result.status is AgentRunStatus.SUCCEEDED
    assert result.artifact is not None
    assert result.artifact.source_revision == _git(root, "rev-parse", "HEAD")
    assert result.usage is not None and result.usage.total_tokens == 30
    assert transport.calls[0]["reasoning"] == {"effort": "high"}
    assert all("previous_response_id" not in call for call in transport.calls)
    assert all(call["store"] is False for call in transport.calls)
    history = transport.calls[1]["input"]
    assert isinstance(history, list)
    initial = transport.calls[0]["input"]
    assert isinstance(initial, list)
    assert history[: len(initial)] == initial
    outputs = history[len(initial) :]
    assert len(outputs) == 7
    assert outputs[0]["encrypted_content"] == "opaque-reasoning"
    assert [item["type"] for item in outputs] == [
        "reasoning",
        "function_call",
        "function_call",
        "function_call",
        "function_call_output",
        "function_call_output",
        "function_call_output",
    ]
    assert [item["call_id"] for item in outputs[1:4]] == [item["call_id"] for item in outputs[4:]]
    assert len(executed) == (4 if extra_tool_turn else 3)
    assert len({tool.operation_id for tool in executed}) == len(executed)
    if extra_tool_turn:
        third_history = transport.calls[2]["input"]
        assert isinstance(third_history, list)
        assert third_history[: len(history)] == history
        latest = third_history[len(history) :]
        assert [item["type"] for item in latest] == [
            "message",
            "function_call",
            "function_call_output",
        ]
        assert latest[1]["call_id"] == latest[2]["call_id"] == "call_status"
    # Exact in-memory replay must not dispatch any tools or HTTP requests again.
    calls_before_replay, executions_before_replay = len(transport.calls), len(executed)
    assert adapter.run(request) == result
    assert (len(transport.calls), len(executed)) == (calls_before_replay, executions_before_replay)
    assert _git(root, "status", "--porcelain") == ""


def test_quota_failure_with_partial_changes_is_not_fallback_eligible(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    request, definition = _request(base)
    adapter = ResponsesAgentAdapter(
        workspace_root=root,
        endpoint="https://example.invalid/v1/responses",
        api_key="test-key",
        model="deepseek-v4-pro",
        agent=definition,
        prompt_builder=StaticPromptBuilder(),
        transport=_DirtyFailureTransport(root),
    )

    result = adapter.run(request)

    assert result.status is AgentRunStatus.FAILED
    assert result.error is not None
    assert result.error.code is AgentErrorCode.POLICY_VIOLATION
    assert result.error.transient is False
    assert "failed provider route left repository changes" in result.error.message
    assert "provider_diagnostic=Responses provider returned HTTP 429" in result.error.message


def test_dirty_provider_failure_keeps_safe_transport_diagnostic(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    request, definition = _request(base)
    secret = "private-task-and-provider-secret"

    class TransportFailure:
        def post(
            self,
            url: str,
            headers: Mapping[str, str],
            body: bytes,
            timeout_seconds: float,
        ) -> HttpResponse:
            del url, headers, body, timeout_seconds
            (root / "src" / "partial.py").write_text(secret, encoding="utf-8")
            raise OSError("provider socket failed " + secret)

    result = ResponsesAgentAdapter(
        workspace_root=root,
        endpoint="https://example.invalid/v1/responses",
        api_key="test-key",
        model="deepseek-v4-pro",
        agent=definition,
        prompt_builder=StaticPromptBuilder(),
        transport=TransportFailure(),
    ).run(request)

    assert result.error is not None
    assert result.error.code is AgentErrorCode.POLICY_VIOLATION
    assert result.error.transient is False
    assert "provider_diagnostic=Responses provider is unavailable" in result.error.message
    assert secret not in result.model_dump_json()
    assert (root / "src" / "partial.py").read_text(encoding="utf-8") == secret


def test_authentication_error_is_typed_and_safe(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    request, definition = _request(base)

    class AuthFailure:
        def post(
            self,
            url: str,
            headers: Mapping[str, str],
            body: bytes,
            timeout_seconds: float,
        ) -> HttpResponse:
            del url, headers, body, timeout_seconds
            return HttpResponse(status_code=401, body=b'{"secret":"must-not-leak"}')

    result = ResponsesAgentAdapter(
        workspace_root=root,
        endpoint="https://example.invalid/v1/responses",
        api_key="test-key",
        model="deepseek-v4-pro",
        agent=definition,
        prompt_builder=StaticPromptBuilder(),
        transport=AuthFailure(),
    ).run(request)

    assert result.error is not None
    assert result.error.code is AgentErrorCode.AUTHENTICATION_ERROR
    assert "secret" not in result.error.message
