"""Policy admission reaches real independent verification and public Host continuation."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentAdapter,
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
    StoredContextResolver,
)
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentDefinition, AgentRole
from ai_software_engineer.domain.engineering_authority import (
    EngineeringCapability,
    EngineeringPolicy,
    EngineeringScope,
    LocalOperatorPrincipal,
)
from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy, TransientRetryPolicy
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    ResumeProjectDelivery,
    StartProjectDelivery,
)
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.engineering_authority import EngineeringAuthority
from ai_software_engineer.manager.production_delivery import DeliveryRouteAdapterFactory
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.orchestration import FileRunContextBuilder
from ai_software_engineer.recovery.models import (
    RecoveryApprovalCommand,
    RecoveryRejected,
    RecoveryScope,
)
from ai_software_engineer.recovery.resume import DeliveryResumeOutcome, DeliveryResumeResult
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.verification import CandidateVerificationRunner
from ai_software_engineer.recovery.verification_admission import (
    CandidateVerificationAdmission,
    ExplicitVerificationHuman,
)
from ai_software_engineer.recovery.verification_records import CandidateVerificationPlan
from ai_software_engineer.role_workspace import RoleWorktreeBinding
from ai_software_engineer.store import MySqlTaskRepository
from tests.manager.test_production_backend import (
    _git,
    _ScriptedClientFactory,
    _ScriptedDeliveryAdapter,
)
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.orchestration import test_runner
from tests.orchestration.test_retry import ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions
from tests.recovery.test_candidate_verification import Admission, setup_verification
from tests.recovery.test_verification_admission import Facts, InterruptedAdapter


class _PolicyVerificationAdapter:
    def __init__(
        self, owner: _PolicyVerificationFactory, definition: AgentDefinition, path: Path
    ) -> None:
        self.owner = owner
        self.delegate = _ScriptedDeliveryAdapter(definition, path)

    def run(self, request: AgentRequest) -> AgentResult:
        self.owner.requests.append(request)
        if request.role is AgentRole.QA and not self.owner.original_qa_failed:
            self.owner.original_qa_failed = True
            return AgentResult(
                run_id=request.run_id,
                task_id=request.task_id,
                role=request.role,
                attempt=request.attempt,
                source_revision=request.source_revision,
                context_manifest_id=request.context_manifest_id,
                status=AgentRunStatus.FAILED,
                error=AgentFailure(
                    code=AgentErrorCode.RATE_LIMITED,
                    message="offline transient quota",
                    transient=True,
                ),
            )
        return self.delegate.run(request)


class _PolicyVerificationFactory(DeliveryRouteAdapterFactory):
    def __init__(self) -> None:
        self.requests: list[AgentRequest] = []
        self.original_qa_failed = False

    def create(
        self,
        *,
        route: ProviderRouteConfig,
        definition: AgentDefinition,
        binding: RoleWorktreeBinding,
        context_resolver: StoredContextResolver,
        config: ProductionConfig,
        environment: Mapping[str, str],
    ) -> AgentAdapter:
        del route, context_resolver, config, environment
        return _PolicyVerificationAdapter(self, definition, binding.worktree.path)


@pytest.mark.parametrize("interrupted", [False, True])
def test_policy_verification_has_independent_receipts_and_no_human_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupted: bool,
) -> None:
    original_factory = test_runner._task
    policy = EngineeringPolicy.bounded_local(
        scope=EngineeringScope(
            team_id="team_test",
            project_id="project_test",
            repository_id="repository_test",
            repository_root=str(tmp_path / "project"),
        ),
        principal=LocalOperatorPrincipal.trusted_local(),
    )
    monkeypatch.setattr(
        "tests.orchestration.test_retry._task",
        lambda root: original_factory(root).model_copy(update={"engineering_policy": policy}),
    )
    adapter = InterruptedAdapter() if interrupted else ScriptedAdapter()
    inputs, repository, _ = setup_verification(tmp_path, adapter, Admission())
    task = repository.get(inputs.task_id)
    before = task, repository.list_events(task.id)
    scope = RecoveryScope(
        team_id="team_test",
        repository_id="repository_test",
        delivery_id="delivery_test",
        repository_root=task.repository,
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
    ledger = tmp_path / "ledger"
    ledger.mkdir(mode=0o700)
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    facts = Facts()
    admission = CandidateVerificationAdmission(
        store=store, plan_sha256=plan.plan_sha256, facts=facts, artifacts=artifacts, clock=_clock
    )
    admission.propose(plan)
    receipt = admission.authorize_policy(
        task=task,
        authority=EngineeringAuthority(ledger),
        capabilities=(EngineeringCapability.VERIFICATION_REFRESH,),
    )
    assert store.get_verification_authority(plan.plan_sha256) == receipt
    with pytest.raises(RecoveryRecordMissing):
        store.get_verification_authorization(plan.plan_sha256)
    with pytest.raises(RecoveryRejected, match="not a human"):
        admission.approve(
            RecoveryApprovalCommand(
                operation_id="op_forbidden_human",
                plan_sha256=plan.plan_sha256,
                approval_reference="not-a-policy-receipt",
                submitted_at=_clock(),
            ),
            human=ExplicitVerificationHuman(plan.plan_sha256),
        )
    verifier = CandidateVerificationRunner(
        repository=repository,
        artifact_store=artifacts,
        context_builder=FileRunContextBuilder(tmp_path / "project"),
        agent_adapter=adapter,
        agent_definitions=_definitions(),
        admission=admission,
        clock=_clock,
    )
    try:
        if interrupted:
            with pytest.raises(RuntimeError, match="process lost"):
                verifier.verify_candidate(inputs)
            reopened = FileRecoveryStore(store._root, scope=scope)
            assert (
                reopened.get_verification_invocation(
                    plan.plan_sha256, AgentRole.QA
                ).authorization_sha256
                == receipt.admission_sha256
            )
            with pytest.raises(RecoveryRejected, match="already admitted"):
                admission.admit(inputs, adapter.requests[0])
            assert len(adapter.requests) == 1
        else:
            completion = admission.complete(verifier.verify_candidate(inputs))
            assert completion.verified
            assert completion.authorization_sha256 == receipt.admission_sha256
            assert [request.role for request in adapter.requests] == [
                AgentRole.QA,
                AgentRole.REVIEWER,
            ]
            assert len({request.run_id for request in adapter.requests}) == 2
            assert len({request.context_manifest_id for request in adapter.requests}) == 2
            assert {request.source_revision for request in adapter.requests} == {
                inputs.candidate_revision
            }
        assert (repository.get(task.id), repository.list_events(task.id)) == before
    finally:
        repository.close()


@pytest.mark.mysql
def test_public_host_policy_verifies_pinned_candidate_without_product_engineering_approval(
    tmp_path: Path,
    mysql_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_entry.discover_swift_sandbox_capability",
        lambda _: None,
    )
    project = tmp_path / "project"
    project.mkdir()
    (project / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=project)
    _git("add", "hello.txt", cwd=project)
    _git("commit", "-m", "base", cwd=project)
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        default_project_id="project_test",
        default_project_name="Test Project",
        live_model_execution=True,
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-fixture", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
        execution_retry_policy=ExecutionRetryPolicy(
            qa=TransientRetryPolicy(max_transient_failures=1)
        ),
    )
    environment = {"ASE_MYSQL_DSN": mysql_dsn}
    routes = _PolicyVerificationFactory()
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=routes,
    )
    entry = host.project_entry()
    started = entry.start(
        StartProjectDelivery(repository_root=str(project), requirement="Change the greeting.")
    )
    blocked = entry.approve(
        ApproveProductSpec(
            delivery_id=started.checkpoint.delivery_id,
            expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
            approval_reference="exact-product-spec-only",
        )
    ).checkpoint
    assert blocked.stage is DeliveryStage.BLOCKED
    assert blocked.task_id is not None and blocked.candidate_revision is not None
    with MySqlTaskRepository(mysql_dsn) as repository:
        task = repository.get(blocked.task_id)
        original_events = repository.list_events(task.id)
        assert task.engineering_policy is not None
    before_calls = len(routes.requests)
    # Reconstruct the production Host before consuming its exact policy admission.
    reopened = TeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=routes,
    )
    result = reopened.resume_delivery(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    assert isinstance(result, DeliveryResumeResult)
    assert result.outcome is DeliveryResumeOutcome.VERIFIED
    assert result.checkpoint.stage is DeliveryStage.DONE
    assert result.checkpoint.candidate_revision == blocked.candidate_revision
    new_requests = routes.requests[before_calls:]
    assert [request.role for request in new_requests] == [AgentRole.QA, AgentRole.REVIEWER]
    assert {request.source_revision for request in new_requests} == {blocked.candidate_revision}
    assert len({request.run_id for request in new_requests}) == 2
    scope = RecoveryScope(
        team_id=config.team_id,
        repository_id=blocked.repository_id,
        repository_root=blocked.repository_root,
        delivery_id=blocked.delivery_id,
    )
    # Source is terminal history, while final handoff belongs to the original Requirement.
    assert result.checkpoint.verification_plan_sha256 is not None
    root = (
        Path(config.platform_root)
        / "projects/project_test/repositories"
        / blocked.repository_id
        / "state"
        / f"candidate-verification-{blocked.delivery_id}"
    )
    store = FileRecoveryStore(root, scope=scope)
    receipt = store.get_engineering_admission(result.checkpoint.verification_plan_sha256)
    assert receipt.task_id == task.id
    with pytest.raises(RecoveryRecordMissing):
        store.get_verification_authorization(receipt.plan_sha256)
    assert store.get_verification_completion(receipt.plan_sha256).verified
    with MySqlTaskRepository(mysql_dsn) as repository:
        assert repository.get(task.id) == task
        assert repository.list_events(task.id) == original_events
    calls = len(routes.requests)
    assert (
        reopened.resume_delivery(ResumeProjectDelivery(delivery_id=blocked.delivery_id)).checkpoint
        == result.checkpoint
    )
    assert len(routes.requests) == calls
