"""Approved draft seeds survive unchanged provider failures without hiding new writes."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentRequest,
    HttpResponse,
    ResponsesAgentAdapter,
)
from ai_software_engineer.git.mutation import capture_mutation_inventory
from tests.agents.test_openai_compatible import StaticPromptBuilder
from tests.agents.test_responses import _repository, _request


@pytest.mark.parametrize("mutation", ["none", "body", "mode", "ignored"])
def test_exact_seed_classifies_only_current_route_mutations(tmp_path: Path, mutation: str) -> None:
    root, base = _repository(tmp_path)
    request, definition = _request(base)
    seed = root / "src/approved.py"
    seed.write_text("approved = True\n")
    expected = capture_mutation_inventory(root)
    admitted: list[AgentRequest] = []

    class Admission:
        def authorize(self, value: AgentRequest, workspace_root: Path) -> None:
            assert value == request and workspace_root == root
            if capture_mutation_inventory(workspace_root) != expected:
                raise ValueError("approved seed drifted")
            admitted.append(value)

    class Provider:
        calls = 0

        def post(
            self,
            url: str,
            headers: Mapping[str, str],
            body: bytes,
            timeout_seconds: float,
        ) -> HttpResponse:
            self.calls += 1
            if mutation == "body":
                seed.write_text("new_write = True\n")
            elif mutation == "mode":
                seed.chmod(0o755)
            elif mutation == "ignored":
                (root / ".pytest_cache").mkdir()
                (root / ".pytest_cache/partial").write_text("changed\n")
            return HttpResponse(429, b'{"error":{"code":"insufficient_quota"}}')

    provider = Provider()
    adapter = ResponsesAgentAdapter(
        workspace_root=root,
        endpoint="https://example.invalid/v1/responses",
        api_key="test-key",
        model="fixture",
        agent=definition,
        transport=provider,
        prompt_builder=StaticPromptBuilder(),
        initial_workspace_admission=Admission(),
    )
    result = adapter.run(request)
    assert result.error is not None and provider.calls == 1 and admitted == [request]
    assert result.error.code is (
        AgentErrorCode.QUOTA_EXHAUSTED if mutation == "none" else AgentErrorCode.POLICY_VIOLATION
    )
    assert result.error.transient is (mutation == "none")
    assert adapter.run(request) == result and provider.calls == 1
    if mutation == "none":
        assert capture_mutation_inventory(root) == expected


def test_seed_drift_is_rejected_before_provider(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    request, definition = _request(base)
    seed = root / "src/approved.py"
    seed.write_text("approved = True\n")
    expected = capture_mutation_inventory(root)

    class Admission:
        def authorize(self, value: AgentRequest, workspace_root: Path) -> None:
            if value != request or capture_mutation_inventory(workspace_root) != expected:
                raise ValueError("approved seed drifted")

    class Provider:
        calls = 0

        def post(
            self,
            url: str,
            headers: Mapping[str, str],
            body: bytes,
            timeout_seconds: float,
        ) -> HttpResponse:
            self.calls += 1
            raise AssertionError("drifted seed must not call a provider")

    provider = Provider()
    adapter = ResponsesAgentAdapter(
        workspace_root=root,
        endpoint="https://example.invalid/v1/responses",
        api_key="test-key",
        model="fixture",
        agent=definition,
        transport=provider,
        initial_workspace_admission=Admission(),
    )
    seed.write_text("unapproved = True\n")
    result = adapter.run(request)
    assert result.error is not None and result.error.code is AgentErrorCode.POLICY_VIOLATION
    assert provider.calls == 0 and seed.read_text() == "unapproved = True\n"
