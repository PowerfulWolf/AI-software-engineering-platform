"""Real prompt builders guide writable roles without granting source exceptions."""

import json

import pytest

from ai_software_engineer.agents import ContextPromptBuilder, PromptPayload, RequestPromptBuilder
from ai_software_engineer.context import ContextBudget, ContextBundle, ContextSection
from ai_software_engineer.domain import AgentRole
from tests.agents.test_openai_compatible import RecordingContextResolver, _request
from tests.domain.factories import NOW, make_implementation_artifact

_GUIDANCE_MARKER = "NEGATIVE_CREDENTIAL_TEST_GUIDANCE:"


def _build_prompt(builder: str, role: AgentRole, write_paths: tuple[str, ...]) -> PromptPayload:
    request = _request(role)
    request = request.model_copy(
        update={"permissions": request.permissions.model_copy(update={"write_paths": write_paths})}
    )
    if builder == "request":
        return RequestPromptBuilder().build(request)
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
                content=json.dumps(request.permissions.to_wire()),
                priority=0,
            ),
            ContextSection(
                name="task",
                uri=f"task://{request.task_id}",
                sha256="b" * 64,
                tokens=1,
                content="Untrusted task asks to skip negative tests and relax capture policy.",
                priority=30,
            ),
        ),
        budget=ContextBudget(max_input_tokens=10, reserved_output_tokens=2, used_input_tokens=2),
        built_at=NOW,
    )
    return ContextPromptBuilder(
        RecordingContextResolver(context, make_implementation_artifact())
    ).build(request)


@pytest.mark.parametrize("builder", ["request", "context"])
@pytest.mark.parametrize("role", [AgentRole.CODER, AgentRole.QA])
def test_writable_role_gets_complete_negative_credential_guidance_in_machine_message(
    builder: str, role: AgentRole
) -> None:
    prompt = _build_prompt(builder, role, ("tests/**",))
    system, user = prompt.messages
    assert system.role == "system" and user.role == "user"
    assert system.content.count(_GUIDANCE_MARKER) == 1
    assert _GUIDANCE_MARKER not in user.content
    for requirement in (
        "dynamically generated tokens or references",
        "independent authorized fixture",
        "within the current permissions",
        "Preserve the original negative-test intent and existing non-empty unknown-token",
        "empty-value and expired-token assertions where applicable",
        "An unknown token must be distinct from the valid fixture token",
        "Never embed fixed credential-like literals in source or tests",
        "encode/concatenate values to evade secret inspection",
        "Do not weaken tests, skip assertions, or relax machine permissions or capture policy",
        "If no legal fixture/reference can be constructed",
        "explicit blocked reason through the existing role output schema",
        "do not claim unverified acceptance criteria passed",
    ):
        assert requirement in system.content
    payload = json.loads(user.content)
    if builder == "request":
        policy = payload["policy"]
    else:
        policy, _ = json.JSONDecoder().raw_decode(system.content.split("MACHINE_POLICY=", 1)[1])
    assert policy["write_paths"] == ["tests/**"]


@pytest.mark.parametrize("builder", ["request", "context"])
@pytest.mark.parametrize("role", list(AgentRole))
def test_readonly_role_does_not_get_source_mutation_guidance(builder: str, role: AgentRole) -> None:
    prompt = _build_prompt(builder, role, ())
    assert _GUIDANCE_MARKER not in prompt.messages[0].content


@pytest.mark.parametrize("builder", ["request", "context"])
@pytest.mark.parametrize("role", [AgentRole.ORCHESTRATOR, AgentRole.REVIEWER])
def test_other_roles_do_not_get_source_mutation_guidance_even_with_write_paths(
    builder: str, role: AgentRole
) -> None:
    prompt = _build_prompt(builder, role, ("tests/**",))
    assert _GUIDANCE_MARKER not in prompt.messages[0].content


@pytest.mark.parametrize("role", [AgentRole.CODER, AgentRole.QA])
def test_both_builders_share_identical_negative_credential_guidance(role: AgentRole) -> None:
    request = _build_prompt("request", role, ("tests/**",))
    context = _build_prompt("context", role, ("tests/**",))
    request_guidance = request.messages[0].content.split(_GUIDANCE_MARKER, 1)[1]
    context_guidance = context.messages[0].content.split(_GUIDANCE_MARKER, 1)[1]
    assert request_guidance == context_guidance
