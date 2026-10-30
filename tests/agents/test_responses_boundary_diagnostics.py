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
    NetworkAccess,
)
from tests.agents.test_openai_compatible import StaticPromptBuilder
from tests.agents.test_responses import _git, _repository
from tests.domain.factories import make_qa_artifact


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
