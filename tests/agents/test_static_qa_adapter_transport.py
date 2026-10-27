"""Static QA proof remains an internal, typed output gate across prompt adapters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai_software_engineer.agents import (
    AgentRunStatus,
    CodexCliAgentAdapter,
    ResponsesAgentAdapter,
)
from ai_software_engineer.agents.codex_cli import CodexInvocationResult
from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.agents.openai_compatible import PromptPayload
from ai_software_engineer.agents.ports import AgentConfigurationError
from ai_software_engineer.agents.verification_output import (
    TrustedStaticQaMissingEntryOutputContract,
    VerificationOutputRejected,
)
from ai_software_engineer.domain.enums import QaReportStatus
from ai_software_engineer.domain.native_verification import role_verification_digest
from ai_software_engineer.recovery.verification_execution import (
    ConditionalStaticQaEvidenceProvider,
    VerificationEvidence,
    VerificationEvidencePromptBuilder,
)
from tests.agents.test_codex_cli import _ArtifactOutputRunner
from tests.agents.test_openai_compatible import RecordingTransport, StaticPromptBuilder
from tests.agents.test_static_qa_missing_entry_output import _subject
from tests.domain.factories import make_agent
from tests.manager.test_native_verification import _fixture


class _StaticEvidenceProvider:
    def __init__(self, contract: TrustedStaticQaMissingEntryOutputContract) -> None:
        self.contract = contract

    def evidence_for(
        self, request: AgentRequest, workspace_root: Path, execution_guard: object = None
    ) -> VerificationEvidence:
        assert request.task_id == self.contract.task_id
        return VerificationEvidence(
            text="The trusted candidate tree lacks the frozen planned test entry.",
            output_contract=self.contract,
        )


def test_unselected_ordinary_qa_keeps_registered_verifier_provider(tmp_path: Path) -> None:
    request, _, _ = _subject()
    delegate = MagicMock()
    expected = VerificationEvidence(text="ordinary verifier receipt")
    delegate.evidence_for.return_value = expected
    provider = ConditionalStaticQaEvidenceProvider(delegate, lambda *_: None, lambda *_: None)
    assert provider.evidence_for(request, tmp_path, None) == expected
    delegate.evidence_for.assert_called_once_with(request, tmp_path, None)


def test_static_qa_contract_survives_internal_prompt_transport_without_wire_leak(
    tmp_path: Path,
) -> None:
    request, contract, _ = _subject()
    provider = _StaticEvidenceProvider(contract)
    builder = VerificationEvidencePromptBuilder(StaticPromptBuilder(), provider, tmp_path, None)

    prompt: PromptPayload = builder.build(request)

    assert prompt.verification_output_contract == contract
    assert "verification_output_contract" not in prompt.model_dump()
    assert "The trusted candidate tree lacks" in str(prompt.to_messages())


def test_static_qa_evidence_resolves_fresh_at_prompt_and_output(tmp_path: Path) -> None:
    request, contract, _ = _subject()
    active = [contract]
    calls: list[AgentRequest] = []

    def resolve(
        observed: AgentRequest, root: Path, guard: object
    ) -> TrustedStaticQaMissingEntryOutputContract | None:
        calls.append(observed)
        assert root == tmp_path
        return active[0]

    builder = VerificationEvidencePromptBuilder(
        StaticPromptBuilder(),
        ConditionalStaticQaEvidenceProvider(None, resolve, lambda *_: contract),
        tmp_path,
        None,
    )
    assert builder.build(request).verification_output_contract == contract
    builder.validate_output_current(request, tmp_path, None, contract)
    assert calls == [request, request]

    active[0] = contract.model_copy(update={"claim_sha256": "0" * 64})
    with pytest.raises(VerificationOutputRejected):
        builder.validate_output_current(request, tmp_path, None, contract)


@pytest.mark.parametrize("defect", ["none", "stale_claim", "pass"])
def test_codex_accepts_only_fresh_proof_bound_commandless_qa_fail(
    tmp_path: Path, defect: str
) -> None:
    fixture = _fixture(tmp_path)
    request = fixture.request
    _, template_contract, template_report = _subject()
    contract = template_contract.model_copy(
        update={
            "request_sha256": role_verification_digest(request.to_wire()),
            "task_id": request.task_id,
            "run_id": request.run_id,
            "attempt": request.attempt,
            "source_revision": request.source_revision,
            "context_manifest_id": request.context_manifest_id,
        }
    )
    report = template_report.model_copy(
        update={
            "task_id": request.task_id,
            "source_revision": request.source_revision,
            "context_manifest_id": request.context_manifest_id,
            "parent_artifact_ids": (contract.implementation_artifact_id,),
            "producer": template_report.producer.model_copy(update={"run_id": request.run_id}),
        }
    )
    if defect == "pass":
        report = report.model_copy(
            update={"content": report.content.model_copy(update={"status": QaReportStatus.PASS})}
        )
    active = [contract]

    def resolve(
        observed: AgentRequest, root: Path, guard: object
    ) -> TrustedStaticQaMissingEntryOutputContract | None:
        assert observed == request and root == fixture.root and guard is fixture.guard
        return active[0]

    provider = ConditionalStaticQaEvidenceProvider(None, resolve, lambda *_: contract)
    builder = VerificationEvidencePromptBuilder(
        StaticPromptBuilder(), provider, fixture.root, fixture.guard
    )
    runner = _ArtifactOutputRunner(json.loads(report.model_dump_json()))
    if defect == "stale_claim":
        original = runner.run

        def stale_run(
            argv: tuple[str, ...],
            *,
            cwd: Path,
            environment: Mapping[str, str],
            stdin: str,
            timeout_seconds: float,
        ) -> CodexInvocationResult:
            result = original(
                argv,
                cwd=cwd,
                environment=environment,
                stdin=stdin,
                timeout_seconds=timeout_seconds,
            )
            active[0] = contract.model_copy(update={"claim_sha256": "0" * 64})
            return result

        runner.run = stale_run  # type: ignore[method-assign]
    adapter = CodexCliAgentAdapter(
        workspace_root=fixture.root,
        model="fixture",
        agent_id=fixture.claim.assignment.agent_id,
        agent_version="v0.1",
        prompt_builder=builder,
        execution_guard=fixture.guard,
        runner=runner,
    )
    result = adapter.run(request)
    if defect == "none":
        assert result.status is AgentRunStatus.SUCCEEDED
        assert result.artifact is not None
        assert "Do not run tests or any planned verification command" in runner.prompt
        assert "If the acceptance mapping does not identify focused selectors" not in runner.prompt
        assert "ASE_PROJECT_PYTEST" not in runner.environment
    else:
        assert result.status is AgentRunStatus.FAILED
        assert result.artifact is None


def test_static_qa_changed_after_preparation_never_starts_codex(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    request = fixture.request
    _, template_contract, report = _subject()
    contract = template_contract.model_copy(
        update={
            "request_sha256": role_verification_digest(request.to_wire()),
            "task_id": request.task_id,
            "run_id": request.run_id,
            "attempt": request.attempt,
            "source_revision": request.source_revision,
            "context_manifest_id": request.context_manifest_id,
        }
    )
    active = [contract]

    def resolve(
        observed: AgentRequest, root: Path, guard: object
    ) -> TrustedStaticQaMissingEntryOutputContract | None:
        assert observed == request and root == fixture.root and guard is fixture.guard
        return active[0]

    builder = VerificationEvidencePromptBuilder(
        StaticPromptBuilder(),
        ConditionalStaticQaEvidenceProvider(None, resolve, lambda *_: contract),
        fixture.root,
        fixture.guard,
    )
    runner = _ArtifactOutputRunner(json.loads(report.model_dump_json()))
    adapter = CodexCliAgentAdapter(
        workspace_root=fixture.root,
        model="fixture",
        agent_id=fixture.claim.assignment.agent_id,
        agent_version="v0.1",
        prompt_builder=builder,
        execution_guard=fixture.guard,
        runner=runner,
    )
    adapter.prepare_input(request)
    active[0] = contract.model_copy(update={"claim_sha256": "0" * 64})
    result = adapter.run(request)
    assert result.status is AgentRunStatus.FAILED
    assert result.artifact is None
    assert runner.prompt == ""


def test_responses_rejects_static_contract_before_provider_call(tmp_path: Path) -> None:
    request, contract, _ = _subject()
    transport = RecordingTransport()
    adapter = ResponsesAgentAdapter(
        workspace_root=tmp_path,
        endpoint="https://example.invalid/v1/responses",
        api_key="fixture-key",
        model="fixture",
        agent=make_agent().model_copy(update={"role": request.role}),
        prompt_builder=StaticPromptBuilder(
            PromptPayload(
                messages=StaticPromptBuilder().payload.messages,
                verification_output_contract=contract,
            )
        ),
        transport=transport,
    )
    with pytest.raises(AgentConfigurationError, match="guarded native route"):
        adapter.prepare_input(request)
    assert not transport.calls
