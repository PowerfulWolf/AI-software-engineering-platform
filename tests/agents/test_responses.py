"""Responses-compatible tool loop tests with real Git and a scripted provider."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentRequest,
    AgentRunStatus,
    HttpResponse,
    ResponsesAgentAdapter,
)
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentPermissions,
    AgentRole,
    ArtifactKind,
    ChangedFile,
    ChangeType,
    NetworkAccess,
)
from tests.agents.test_openai_compatible import StaticPromptBuilder, _coder_request
from tests.domain.factories import make_implementation_artifact


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
        output_artifacts=(ArtifactKind.IMPLEMENTATION_REPORT,),
        max_retries=0,
        timeout_seconds=60,
    )
    return request, definition


class _CoderTransport:
    def __init__(self, root: Path, request: AgentRequest) -> None:
        self.root = root
        self.request = request
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
                    "output_text": json.dumps(artifact.to_wire()),
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


def test_responses_tool_loop_creates_and_validates_coder_commit(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    request, definition = _request(base)
    transport = _CoderTransport(root, request)
    adapter = ResponsesAgentAdapter(
        workspace_root=root,
        endpoint="https://example.invalid/v1/responses",
        api_key="test-key",
        model="qwen3.8-max",
        agent=definition,
        prompt_builder=StaticPromptBuilder(),
        transport=transport,
    )

    result = adapter.run(request)

    assert result.status is AgentRunStatus.SUCCEEDED
    assert result.artifact is not None
    assert result.artifact.source_revision == _git(root, "rev-parse", "HEAD")
    assert result.usage is not None and result.usage.total_tokens == 30
    assert transport.calls[1]["previous_response_id"] == "resp_tool_001"
    outputs = transport.calls[1]["input"]
    assert isinstance(outputs, list) and len(outputs) == 3
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
