"""Safe, actionable categories for Responses role policy failures."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentRequest,
    AgentRunStatus,
    HttpResponse,
    ResponsesAgentAdapter,
)
from ai_software_engineer.agents.openai_compatible import HttpTransport
from ai_software_engineer.agents.responses import _policy_failure_message, _ToolRequestRejected
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentPermissions,
    AgentRole,
    ArtifactKind,
    ChangedFile,
    ChangeType,
    NetworkAccess,
)
from tests.agents.test_openai_compatible import StaticPromptBuilder
from tests.agents.test_responses import _git, _repository, _request
from tests.domain.factories import make_coder_progress_artifact, make_qa_artifact


def _qa(base: str) -> tuple[AgentRequest, AgentDefinition]:
    permissions = AgentPermissions(
        read_paths=("**",),
        write_paths=(),
        commands=("pytest",),
        network=NetworkAccess.MODEL_ENDPOINT_ONLY,
    )
    request = AgentRequest(
        run_id="run_qa_boundary_001",
        task_id="task_domain_001",
        role=AgentRole.QA,
        attempt=1,
        source_revision=base,
        context_manifest_id="ctx_" + "a" * 64,
        input_artifact_ids=("art_impl_001",),
        permissions=permissions,
        output_schema="schemas/qa-report.schema.json",
        timeout_seconds=60,
    )
    definition = AgentDefinition(
        id="agent_qa_boundary_001",
        role=AgentRole.QA,
        version="v0.1",
        provider="fixture",
        model="fixture",
        permissions=permissions,
        input_artifacts=(ArtifactKind.PLAN, ArtifactKind.IMPLEMENTATION_REPORT),
        output_artifacts=(ArtifactKind.QA_REPORT,),
        max_retries=0,
        timeout_seconds=60,
    )
    return request, definition


def _adapter(
    root: Path, definition: AgentDefinition, transport: HttpTransport
) -> ResponsesAgentAdapter:
    return ResponsesAgentAdapter(
        workspace_root=root,
        endpoint="https://example.invalid/v1/responses",
        api_key="private-provider-key",
        model="fixture",
        agent=definition,
        prompt_builder=StaticPromptBuilder(),
        transport=transport,
    )


@pytest.mark.parametrize(
    ("tool", "arguments", "reason"),
    [
        ("run_command", {"argv": ["pytest", "tests"]}, "COMMAND_DENIED"),
        (
            "write_file",
            {"path": "src/private-provider-key.py", "content": "private-provider-key"},
            "PATH_DENIED",
        ),
    ],
)
def test_qa_tool_denial_reports_only_tool_and_typed_reason(
    tmp_path: Path, tool: str, arguments: dict[str, object], reason: str
) -> None:
    root, base = _repository(tmp_path)
    request, definition = _qa(base)

    class ForbiddenSelector:
        calls = 0

        def post(
            self,
            url: str,
            headers: Mapping[str, str],
            body: bytes,
            timeout_seconds: float,
        ) -> HttpResponse:
            del url, headers, body, timeout_seconds
            self.calls += 1
            return HttpResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "output": [
                            {
                                "type": "function_call",
                                "call_id": "call_rejected",
                                "name": tool,
                                "arguments": json.dumps(arguments),
                            }
                        ]
                    }
                ).encode(),
            )

    provider = ForbiddenSelector()
    result = _adapter(root, definition, provider).run(request)

    assert result.status is AgentRunStatus.FAILED
    assert result.error is not None and result.error.code is AgentErrorCode.POLICY_VIOLATION
    assert result.error.message == f"Responses tool request rejected: {tool}/{reason}"
    assert result.error.transient is False
    assert "pytest" not in result.error.message
    assert "src/" not in result.error.message
    assert "private-provider-key" not in result.model_dump_json()
    assert provider.calls == 1
    assert _git(root, "status", "--porcelain") == ""


def test_unknown_tool_rejection_code_never_enters_failure_result() -> None:
    message = _policy_failure_message(
        _ToolRequestRejected("read_file", "PRIVATE_PROVIDER_KEY_VALUE")
    )
    assert message == "Responses tool request rejected: read_file/UNCLASSIFIED"


def test_missing_allowed_file_is_returned_to_coder_without_policy_failure(
    tmp_path: Path,
) -> None:
    root, base = _repository(tmp_path)
    request, definition = _request(base)

    class MissingThenStop:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def post(
            self,
            url: str,
            headers: Mapping[str, str],
            body: bytes,
            timeout_seconds: float,
        ) -> HttpResponse:
            del url, headers, timeout_seconds
            payload = json.loads(body)
            self.calls.append(payload)
            if len(self.calls) == 1:
                return HttpResponse(
                    status_code=200,
                    body=json.dumps(
                        {
                            "output": [
                                {
                                    "type": "function_call",
                                    "call_id": "call_missing",
                                    "name": "read_file",
                                    "arguments": json.dumps(
                                        {"path": "src/not-yet-created.py", "max_bytes": 100}
                                    ),
                                }
                            ]
                        }
                    ).encode(),
                )
            return HttpResponse(status_code=503, body=b"{}")

    provider = MissingThenStop()
    result = _adapter(root, definition, provider).run(request)

    assert len(provider.calls) == 2
    second_input = provider.calls[1]["input"]
    assert isinstance(second_input, list)
    output = next(
        item
        for item in second_input
        if isinstance(item, dict)
        and item.get("type") == "function_call_output"
        and item.get("call_id") == "call_missing"
    )
    assert json.loads(output["output"])["error_code"] == "FILE_NOT_FOUND"
    assert result.error is not None
    assert result.error.code is not AgentErrorCode.POLICY_VIOLATION
    assert _git(root, "status", "--porcelain") == ""


def test_responses_coder_creates_allowed_nested_module_and_returns_receipt(
    tmp_path: Path,
) -> None:
    root, base = _repository(tmp_path)
    request, definition = _request(base)
    module = "src/ai_software_engineer/learning_collection/models.py"
    template = make_coder_progress_artifact()
    artifact = template.model_copy(
        update={
            "task_id": request.task_id,
            "source_revision": base,
            "context_manifest_id": request.context_manifest_id,
            "parent_artifact_ids": request.input_artifact_ids,
            "producer": template.producer.model_copy(update={"run_id": request.run_id}),
            "content": template.content.model_copy(
                update={
                    "checkpoint_sequence": request.attempt,
                    "changed_files": (
                        ChangedFile(
                            path=module,
                            change=ChangeType.ADDED,
                            lines_added=1,
                            lines_deleted=0,
                        ),
                    ),
                }
            ),
        }
    )

    class NewModule:
        calls = 0

        def post(
            self,
            url: str,
            headers: Mapping[str, str],
            body: bytes,
            timeout_seconds: float,
        ) -> HttpResponse:
            del url, headers, timeout_seconds
            self.calls += 1
            if self.calls == 1:
                return HttpResponse(
                    status_code=200,
                    body=json.dumps(
                        {
                            "output": [
                                {
                                    "type": "function_call",
                                    "call_id": "call_nested_write",
                                    "name": "write_file",
                                    "arguments": json.dumps(
                                        {"path": module, "content": "VALUE = 1\n"}
                                    ),
                                }
                            ]
                        }
                    ).encode(),
                )
            payload = json.loads(body)
            outputs = [
                item
                for item in payload["input"]
                if isinstance(item, dict) and item.get("type") == "function_call_output"
            ]
            assert len(outputs) == 1
            receipt = json.loads(outputs[0]["output"])
            assert receipt["path"] == module and receipt["bytes_written"] == 10
            return HttpResponse(
                status_code=200,
                body=json.dumps(
                    {"output_text": json.dumps({"artifact": artifact.to_wire()})}
                ).encode(),
            )

    provider = NewModule()
    result = _adapter(root, definition, provider).run(request)
    assert result.status is AgentRunStatus.SUCCEEDED
    assert provider.calls == 2
    assert (root / module).read_text() == "VALUE = 1\n"


def test_qa_preflight_binding_failure_is_distinct_from_tool_denial(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    request, definition = _qa(base)
    request = request.model_copy(
        update={
            "permissions": request.permissions.model_copy(update={"commands": ()}),
        }
    )

    class Uncalled:
        calls = 0

        def post(
            self,
            url: str,
            headers: Mapping[str, str],
            body: bytes,
            timeout_seconds: float,
        ) -> HttpResponse:
            self.calls += 1
            raise AssertionError("preflight must reject before provider")

    provider = Uncalled()
    result = _adapter(root, definition, provider).run(request)

    assert result.error is not None and result.error.code is AgentErrorCode.POLICY_VIOLATION
    assert result.error.message == "Responses request or worktree binding rejected"
    assert provider.calls == 0


def test_qa_final_workspace_mutation_is_distinct_from_tool_denial(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    request, definition = _qa(base)
    template = make_qa_artifact()
    artifact = template.model_copy(
        update={
            "task_id": request.task_id,
            "source_revision": request.source_revision,
            "context_manifest_id": request.context_manifest_id,
            "producer": template.producer.model_copy(update={"run_id": request.run_id}),
        }
    )

    class DirtyProvider:
        def post(
            self,
            url: str,
            headers: Mapping[str, str],
            body: bytes,
            timeout_seconds: float,
        ) -> HttpResponse:
            del url, headers, body, timeout_seconds
            (root / "src" / "unexpected.py").write_text("VALUE = 1\n", encoding="utf-8")
            return HttpResponse(
                status_code=200,
                body=json.dumps(
                    {"output_text": json.dumps({"artifact": artifact.to_wire()})}
                ).encode(),
            )

    result = _adapter(root, definition, DirtyProvider()).run(request)

    assert result.error is not None and result.error.code is AgentErrorCode.POLICY_VIOLATION
    assert "Responses final workspace validation rejected" in result.error.message
    assert "unexpected.py" not in result.error.message
    assert (root / "src" / "unexpected.py").is_file()
