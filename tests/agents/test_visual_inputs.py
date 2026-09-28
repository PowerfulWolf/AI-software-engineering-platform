"""Visual evidence crosses actual provider seams without enabling model tools."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.agents import (
    AgentRunStatus,
    CodexCliAgentAdapter,
    CodexInvocationResult,
    HttpResponse,
    ResponsesAgentAdapter,
)
from ai_software_engineer.agents.openai_compatible import PromptPayload
from ai_software_engineer.domain import AgentRole
from tests.agents.test_codex_cli import _git, _QaRunner, _repository
from tests.agents.test_openai_compatible import StaticPromptBuilder, _request
from tests.domain.test_visual_evidence import prompt_image
from tests.orchestration.test_runner import _definitions


def visual_prompt(count: int = 1) -> StaticPromptBuilder:
    prompt = StaticPromptBuilder()
    prompt.payload = PromptPayload(
        messages=prompt.payload.messages, images=(prompt_image(),) * count
    )
    return prompt


@pytest.mark.parametrize("count", [1, 12])
def test_responses_sends_actual_image_with_receipt_label(tmp_path: Path, count: int) -> None:
    root, base = _repository(tmp_path)
    request = _request(AgentRole.QA, source_revision=base)
    definition = _definitions()[AgentRole.QA].model_copy(
        update={"permissions": request.permissions}
    )
    bodies: list[bytes] = []

    class Transport:
        def post(
            self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
        ) -> HttpResponse:
            bodies.append(body)
            return HttpResponse(status_code=503, body=b"{}")

    ResponsesAgentAdapter(
        workspace_root=root,
        endpoint="https://example.invalid/v1",
        api_key="fixture",
        model="fixture",
        agent=definition,
        prompt_builder=visual_prompt(count),
        transport=Transport(),
    ).run(request)
    assert len(bodies) == 1
    assert (
        len(
            [
                item
                for item in json.loads(bodies[0])["input"]
                if isinstance(item.get("content"), list)
                and any(part["type"] == "input_image" for part in item["content"])
            ]
        )
        == count
    )
    attachment = json.loads(bodies[0])["input"][-1]
    assert attachment["content"] == [
        {"type": "input_text", "text": prompt_image().label},
        {"type": "input_image", "image_url": prompt_image().image.data_url(), "detail": "high"},
    ]
    chat_image = visual_prompt().payload.to_messages()[-1]
    assert chat_image["content"] == [
        {"type": "text", "text": prompt_image().label},
        {
            "type": "image_url",
            "image_url": {"url": prompt_image().image.data_url(), "detail": "high"},
        },
    ]


@pytest.mark.parametrize("count", [1, 12])
def test_cli_attaches_private_pixels_and_cleans_them_without_text_base64(
    tmp_path: Path, count: int
) -> None:
    root, base = _repository(tmp_path)
    request = _request(AgentRole.QA, source_revision=base)
    paths: list[Path] = []

    class Runner(_QaRunner):
        def run(
            self,
            argv: tuple[str, ...],
            *,
            cwd: Path,
            environment: Mapping[str, str],
            stdin: str,
            timeout_seconds: float,
        ) -> CodexInvocationResult:
            for index, arg in enumerate(argv):
                if arg == "--image":
                    path = Path(argv[index + 1])
                    paths.append(path)
                    assert path.read_bytes() == prompt_image().image.bytes()
                    assert path.stat().st_mode & 0o777 == 0o600
                    assert not path.is_relative_to(cwd)
            assert prompt_image().label in stdin
            assert prompt_image().image.data_base64 not in stdin
            assert argv[argv.index("--sandbox") + 1] == "read-only"
            assert "shell_tool" in argv
            return super().run(
                argv, cwd=cwd, environment=environment, stdin=stdin, timeout_seconds=timeout_seconds
            )

    result = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_qa_001",
        agent_version="v0.1",
        prompt_builder=visual_prompt(count),
        runner=Runner(request),
    ).run(request)
    assert result.status is AgentRunStatus.SUCCEEDED
    assert len(paths) == count and all(not path.exists() for path in paths)
    assert _git(root, "status", "--porcelain") == ""


def test_combined_visual_prompt_remains_bounded() -> None:
    with pytest.raises(ValidationError):
        visual_prompt(13)
