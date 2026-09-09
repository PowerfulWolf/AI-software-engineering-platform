"""Durable verifier admission and schema parity without live models or databases."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from ai_software_engineer.agents import AgentRequest, AgentResult
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.orchestration import FileRunContextBuilder
from ai_software_engineer.recovery.models import (
    RecoveryApprovalCommand,
    RecoveryRejected,
    RecoveryScope,
)
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.recovery.verification import CandidateVerificationRunner
from ai_software_engineer.recovery.verification_admission import (
    CandidateVerificationAdmission,
    ExplicitVerificationHuman,
)
from ai_software_engineer.recovery.verification_entry import _policy_sha
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationCompletion,
    CandidateVerificationInvocation,
    CandidateVerificationPlan,
)
from tests.orchestration.test_retry import ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions
from tests.recovery.test_candidate_verification import Admission, setup_verification


class Facts:
    def __init__(self) -> None:
        self.stale = False

    def validate(self, plan: CandidateVerificationPlan) -> None:
        plan.validate_integrity()
        if self.stale:
            raise RecoveryRejected("offline current facts changed")


def test_verification_policy_digest_binds_all_enabled_fallback_routes(tmp_path: Path) -> None:
    routes = (
        ProviderRouteConfig(provider="codex", model="primary", kind=ModelProviderKind.CODEX_CLI),
        ProviderRouteConfig(
            provider="fallback",
            model="secondary",
            kind=ModelProviderKind.RESPONSES,
            endpoint="https://models.example.test/v1/responses",
            api_key_env="TEST_MODEL_KEY",
        ),
    )
    original = ProductionConfig(platform_root=str(tmp_path / "platform"), model_routes=routes)
    changed = original.model_copy(
        update={
            "model_routes": (
                routes[0],
                routes[1].model_copy(update={"model": "different-secondary"}),
            )
        }
    )
    assert _policy_sha(_definitions(), original) != _policy_sha(_definitions(), changed)


class InterruptedAdapter(ScriptedAdapter):
    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        raise RuntimeError("process lost after durable admission")


@pytest.mark.parametrize(
    "case",
    ["success", "no_approval", "stale", "interrupted", "wrong_confirmation", "changed_model"],
)
def test_durable_admission_reopens_without_repeating_provider(tmp_path: Path, case: str) -> None:
    adapter = InterruptedAdapter() if case == "interrupted" else ScriptedAdapter()
    inputs, repository, _ = setup_verification(tmp_path, adapter, Admission())
    scope = RecoveryScope(
        company_id="company_test",
        project_id="project_test",
        delivery_id="delivery_test",
        project_root=str(tmp_path / "project"),
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
    root = tmp_path / "verification"
    store = FileRecoveryStore.initialize(root, scope=scope)
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    facts = Facts()
    admission = CandidateVerificationAdmission(
        store=store,
        plan_sha256=plan.plan_sha256,
        facts=facts,
        artifacts=artifacts,
        clock=_clock,
    )
    admission.propose(plan)
    command = RecoveryApprovalCommand(
        operation_id="op_verification_test",
        plan_sha256=plan.plan_sha256,
        approval_reference="offline-human-confirmation",
        submitted_at=_clock(),
    )
    human = ExplicitVerificationHuman(plan.plan_sha256)
    authorization = None
    if case == "wrong_confirmation":
        with pytest.raises(RecoveryRejected):
            admission.approve(command, human=ExplicitVerificationHuman("0" * 64))
    elif case != "no_approval":
        authorization = admission.approve(command, human=human)
        assert admission.approve(command, human=ExplicitVerificationHuman(None)) == authorization
    if case == "stale":
        facts.stale = True
    definitions = _definitions()
    if case == "changed_model":
        definitions[AgentRole.QA] = definitions[AgentRole.QA].model_copy(
            update={"model": "unapproved-model"}
        )
    verifier = CandidateVerificationRunner(
        repository=repository,
        artifact_store=artifacts,
        context_builder=FileRunContextBuilder(tmp_path / "project"),
        agent_adapter=adapter,
        agent_definitions=definitions,
        admission=admission,
        clock=_clock,
    )
    try:
        if case in ("no_approval", "stale", "wrong_confirmation", "changed_model"):
            with pytest.raises(RecoveryRejected):
                verifier.verify_candidate(inputs)
            assert not adapter.requests
            return
        if case == "interrupted":
            with pytest.raises(RuntimeError, match="process lost"):
                verifier.verify_candidate(inputs)
            assert len(adapter.requests) == 1
            reopened = FileRecoveryStore(root, scope=scope)
            new_admission = CandidateVerificationAdmission(
                store=reopened,
                plan_sha256=plan.plan_sha256,
                facts=facts,
                artifacts=artifacts,
                clock=_clock,
            )
            with pytest.raises(RecoveryRejected, match="already admitted"):
                new_admission.admit(inputs, adapter.requests[0])
            assert len(adapter.requests) == 1
            return
        result = verifier.verify_candidate(inputs)
        assert result.verified
        completion = admission.complete(result)
        assert completion.verified
        assert admission.complete(result) == completion
        with pytest.raises(ValueError, match="completion requires Review"):
            CandidateVerificationCompletion.create(
                **{**completion.to_wire(), "review": None, "reviewer_invocation_sha256": None}
            )
        assert len(adapter.requests) == 2
        reopened = FileRecoveryStore(root, scope=scope)
        assert reopened.get_verification_completion(plan.plan_sha256) == completion
        for changed in (
            {"authorization_sha256": "9" * 64},
            {"qa_invocation_sha256": "9" * 64},
            {"qa": completion.qa.model_copy(update={"source_revision": "f" * 40})},
        ):
            forged_completion = CandidateVerificationCompletion.create(
                **{**completion.to_wire(), **changed}
            )
            with pytest.raises(RecoveryRejected):
                reopened.put_verification_completion(forged_completion)
        new_admission = CandidateVerificationAdmission(
            store=reopened,
            plan_sha256=plan.plan_sha256,
            facts=facts,
            artifacts=artifacts,
            clock=_clock,
        )
        for request in adapter.requests:
            with pytest.raises(RecoveryRejected, match="already admitted"):
                new_admission.admit(inputs, request)
        qa_receipt = reopened.get_verification_invocation(plan.plan_sha256, AgentRole.QA)
        for changed_request in (
            qa_receipt.request.model_copy(
                update={
                    "input_artifact_ids": ("art_foreign_001",),
                    "expected_parent_artifact_ids": ("art_foreign_001",),
                }
            ),
            qa_receipt.request.model_copy(update={"expected_parent_artifact_ids": ()}),
        ):
            forged = CandidateVerificationInvocation.create(
                **{**qa_receipt.to_wire(), "request": changed_request}
            )
            with pytest.raises(RecoveryRejected):
                reopened.put_verification_invocation(forged)
        schema = json.loads(
            (Path(__file__).parents[2] / "schemas/candidate-verification.schema.json").read_text()
        )
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        for record in (
            reopened.get_verification_plan(plan.plan_sha256),
            authorization,
            reopened.get_verification_invocation(plan.plan_sha256, AgentRole.QA),
            reopened.get_verification_invocation(plan.plan_sha256, AgentRole.REVIEWER),
            reopened.get_verification_completion(plan.plan_sha256),
        ):
            assert record is not None
            record.validate_integrity()
            validator.validate(record.to_wire())
        assert len(adapter.requests) == 2
    finally:
        repository.close()
