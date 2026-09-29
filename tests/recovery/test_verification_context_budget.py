"""Production verification must use the same bounded context policy as delivery."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.context import ContextSource, FileContextStore
from ai_software_engineer.context.ports import ContextBudgetExceeded
from ai_software_engineer.domain import AgentRole, Artifact
from ai_software_engineer.domain.artifact import QaReportArtifact
from ai_software_engineer.manager.production_backend import PRODUCTION_DELIVERY_CONTEXT_BUDGET
from ai_software_engineer.recovery import verification_entry as entry_module
from ai_software_engineer.recovery.models import RecoveryApprovalCommand, RecoveryScope
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.verification_admission import (
    CandidateVerificationAdmission,
    ExplicitVerificationHuman,
)
from ai_software_engineer.recovery.verification_native import NativeCandidateSourceReader
from ai_software_engineer.recovery.verification_records import CandidateVerificationPlan
from tests.orchestration.test_retry import ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions
from tests.recovery.test_candidate_verification import Admission, setup_verification
from tests.recovery.test_verification_admission import Facts


class DetailedQaAdapter(ScriptedAdapter):
    def _artifact(self, request: AgentRequest) -> Artifact:
        artifact = super()._artifact(request)
        if isinstance(artifact, QaReportArtifact):
            return artifact.model_copy(
                update={
                    "content": artifact.content.model_copy(
                        update={"environment": {"fixture_observation": "x" * 16_000}}
                    )
                }
            )
        return artifact


@pytest.mark.parametrize("oversized", [False, True])
def test_production_entry_preserves_required_reviewer_context_and_bounded_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, oversized: bool
) -> None:
    adapter = DetailedQaAdapter()
    inputs, repository, _ = setup_verification(tmp_path, adapter, Admission())
    before = repository.get(inputs.task_id), repository.list_events(inputs.task_id)
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    scope = RecoveryScope(
        team_id="team_test",
        repository_id="repository_test",
        delivery_id="delivery_test",
        repository_root=str(tmp_path / "project"),
    )
    plan = CandidateVerificationPlan.create(
        scope=scope,
        inputs=inputs,
        native_checkpoint_sha256="1" * 64,
        dispatch_sha256="2" * 64,
        approved_stage_chain_sha256="3" * 64,
        current_policy_sha256="4" * 64,
        definitions=tuple(_definitions().values()),
        created_at=_clock(),
    )
    store = FileRecoveryStore.initialize(tmp_path / "verification", scope=scope)
    admission = CandidateVerificationAdmission(
        store=store, plan_sha256=plan.plan_sha256, facts=Facts(), artifacts=artifacts, clock=_clock
    )
    admission.propose(plan)
    admission.approve(
        RecoveryApprovalCommand(
            operation_id="op_context_budget_test",
            plan_sha256=plan.plan_sha256,
            approval_reference="offline-human-confirmation",
            submitted_at=_clock(),
        ),
        human=ExplicitVerificationHuman(plan.plan_sha256),
    )
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        live_model_execution=True,
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-test", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    entry = entry_module.CandidateVerificationEntry(config, {}, Mock())
    monkeypatch.setattr(entry, "open", lambda _: (store, plan))
    monkeypatch.setattr(entry, "_admission", lambda *_: admission)
    source = Mock()
    source.stages.preparation.repository_workspace_root = str(tmp_path)
    monkeypatch.setattr(NativeCandidateSourceReader, "inspect", lambda *_: source)
    authority = Mock()
    monkeypatch.setattr(entry, "_authority", lambda *_: authority)
    monkeypatch.setattr(ProductionConfig, "require_mysql_dsn", lambda *_: "offline-fixture")
    connection = Mock(wraps=repository)
    connection.close = Mock()  # Keep the fixture available for the unchanged-history assertion.
    monkeypatch.setattr(entry_module, "MySqlTaskRepository", lambda *_: connection)
    bound_adapter = Mock(run=adapter.run)
    monkeypatch.setattr(entry_module, "DispatchDeliveryAgentAdapter", lambda **_: bound_adapter)
    # The real production entry composes this required approved-plan source with all artifacts.
    # QA fits the old 12k limit; adding its detailed report for Reviewer does not.
    approved = ContextSource(
        source_id="verification.approved_plan",
        uri="verification://approved-fixture",
        content="p"
        * (PRODUCTION_DELIVERY_CONTEXT_BUDGET.max_input_tokens * 4 if oversized else 32_000),
        priority=20,
        required=True,
    )
    monkeypatch.setattr(entry_module, "_verification_context", lambda _: approved)
    try:
        if oversized:
            with pytest.raises(ContextBudgetExceeded):
                entry.execute(tmp_path / "plan.json")
            assert not adapter.requests
            authority.abandon_verification.assert_called_once()
            authority.complete_verification.assert_not_called()
            with pytest.raises(RecoveryRecordMissing):
                store.get_verification_completion(plan.plan_sha256)
        else:
            completion = entry.execute(tmp_path / "plan.json")
            assert completion.review is not None
            assert [request.role for request in adapter.requests] == [
                AgentRole.QA,
                AgentRole.REVIEWER,
            ]
            contexts = FileContextStore(tmp_path / "contexts")
            qa_context, review_context = tuple(
                contexts.get(request.context_manifest_id) for request in adapter.requests
            )
            assert qa_context.budget.used_input_tokens < 12_000
            assert review_context.budget.used_input_tokens > 12_000
            assert review_context.budget.max_input_tokens == (
                PRODUCTION_DELIVERY_CONTEXT_BUDGET.max_input_tokens
            )
            assert review_context.budget.reserved_output_tokens == 4_000
            assert all(not section.truncated for section in review_context.sections)
            qa_section = next(
                section
                for section in review_context.sections
                if section.uri == f"artifact://{completion.qa.artifact_id}"
            )
            assert json.loads(qa_section.content) == completion.qa.to_wire()
            authority.complete_verification.assert_called_once()
            authority.abandon_verification.assert_not_called()
        assert (repository.get(inputs.task_id), repository.list_events(inputs.task_id)) == before
        connection.close.assert_called_once()
        bound_adapter.close_clean_worktrees.assert_called_once()
    finally:
        repository.close()
