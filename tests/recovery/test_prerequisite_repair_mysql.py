"""Real Git/MySQL: a human-authorized prerequisite goes through ASE's serial roles."""

import os
from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentAdapter,
    AgentRequest,
    AgentResult,
    StoredContextResolver,
)
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain import AgentDefinition, AgentRole, TaskStatus
from ai_software_engineer.domain.prerequisite_repair import (
    PrerequisiteRepairPlan,
    PrerequisiteRepairRequest,
)
from ai_software_engineer.execution import CommandTimedOut, SubprocessCommandExecutor
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    ResumeProjectDelivery,
    StartProjectDelivery,
)
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.production_backend import ProductionProjectDeliveryBackend
from ai_software_engineer.manager.production_delivery import ConfiguredDeliveryRouteAdapterFactory
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.recovery.resume import DeliveryResumeOutcome, DeliveryResumeResult
from ai_software_engineer.recovery.verification_entry import CandidateVerificationEntry
from ai_software_engineer.recovery.verification_records import CandidateVerificationCompletion
from ai_software_engineer.role_workspace import RoleWorktreeBinding
from ai_software_engineer.store import MySqlTaskRepository
from tests.manager.test_production_backend import _git, _ScriptedClientFactory
from tests.recovery.test_resume import _ResumeFactory
from tests.recovery.test_verification_environment import capability


@pytest.mark.mysql
@pytest.mark.parametrize("legacy_context", [False, True])
@pytest.mark.parametrize("native_rules", [False, True])
@pytest.mark.parametrize("changed_native_rules", [False, True])
def test_joint_repair_qa_gap_returns_to_manager_and_resumes_without_coder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    legacy_context: bool,
    native_rules: bool,
    changed_native_rules: bool,
) -> None:
    from ai_software_engineer.agents import StructuredModelResult
    from ai_software_engineer.knowledge.administration import (
        ApproveKnowledgeResolution,
        approve_resolution,
        list_gap_views,
    )
    from ai_software_engineer.knowledge.gaps import KnowledgeResolutionSource
    from ai_software_engineer.knowledge.models import text_digest
    from ai_software_engineer.manager.delivery import ReplyToProduct
    from ai_software_engineer.multi_directory.models import JointDeliveryResult
    from ai_software_engineer.multi_directory.service import CreateRequirement
    from ai_software_engineer.recovery.resume import JointDeliveryResumeResult
    from ai_software_engineer.team_workspace import TeamWorkspace
    from tests.e2e.test_joint_delivery import setup_host
    from tests.recovery.test_resume import _KnowledgeFixtureFactory

    monkeypatch.setattr(CandidateVerificationEntry, "coordinate", lambda *_: None)
    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_entry.discover_swift_sandbox_capability",
        lambda _: None,
    )
    config, environment, models, projects = setup_host(tmp_path)
    if native_rules:
        for repository_root in projects:
            (repository_root / "README.md").write_text("# Fixture\nPreserve greeting behavior.\n")
            rules = repository_root / ".trellis/spec/backend"
            rules.mkdir(parents=True)
            (rules / "index.md").write_text("Use the project contract.\n")
            (rules / "contract.md").write_text("QA and Reviewer verify the same candidate.\n")
            _git("add", ".", cwd=repository_root)
            _git("commit", "-m", "Add project-native rules", cwd=repository_root)
    config = config.model_copy(update={"live_model_execution": True})
    routes = _ResumeFactory(transient_qa_failures=0, verification_inconclusive=True)
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=models,
        delivery_route_adapters=routes,
    )
    entry = host.requirement_entry()
    created = entry.create(
        CreateRequirement(
            name="Repair prerequisite then resolve verifier gap",
            repository_roots=tuple(map(str, projects)),
        )
    ).checkpoint
    product = entry.reply(
        ReplyToProduct(
            delivery_id=created.delivery_id,
            expected_checkpoint_sha256=created.checkpoint_sha256,
            message="Update both greetings.",
        )
    ).checkpoint
    blocked = entry.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="fixture-product",
        )
    ).checkpoint
    proposal = host.resume_delivery(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    assert isinstance(proposal, JointDeliveryResumeResult)
    host.resume_delivery(
        ResumeProjectDelivery(
            delivery_id=blocked.delivery_id,
            approved_plan_sha256=proposal.continuation.verification_plan_sha256,
            approval_reference="fixture-verify",
        )
    )
    if native_rules and changed_native_rules:
        for repository_root in projects:
            (repository_root / "README.md").write_text(
                "# Fixture\nPreserve greeting behavior and verify isolated UI prerequisites.\n"
            )
            _git("add", "README.md", cwd=repository_root)
            _git("commit", "-m", "Clarify native prerequisite contract", cwd=repository_root)
    proposal = host.resume_delivery(
        ResumeProjectDelivery(
            delivery_id=blocked.delivery_id,
            prerequisite_repair=PrerequisiteRepairRequest(
                objective="Repair the isolated prerequisite without altering original criteria.",
                write_paths=("hello.txt", "tests/**"),
            ),
        )
    )
    assert isinstance(proposal, JointDeliveryResumeResult)
    repair = proposal.continuation.prerequisite_repair_plan
    assert repair is not None
    original_complete = models.complete
    gap_enabled = True

    def complete(**kwargs: object) -> StructuredModelResult:
        payload, schema = kwargs["input_payload"], kwargs["output_schema"]
        assert isinstance(payload, Mapping) and isinstance(schema, Mapping)
        binding = payload.get("binding", {})
        if (
            gap_enabled
            and isinstance(binding, Mapping)
            and str(binding.get("task_id", "")).startswith("task_continue_")
            and binding.get("role") == "qa"
        ):
            if schema["title"] == "KnowledgeIntent":
                return StructuredModelResult(payload={"queries": ["验收前提"]}, duration_ms=0)
            if schema["title"] == "KnowledgeAssessment":
                return StructuredModelResult(
                    payload={"status": "GAP", "gap_question": "确认验收前提。"}, duration_ms=0
                )
        return original_complete(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(models, "complete", complete)
    monkeypatch.setattr(
        "ai_software_engineer.manager.production_backend.ConfiguredStructuredClientFactory.for_project",
        lambda *args, **kwargs: models,
    )
    remaining = _ResumeFactory(transient_qa_failures=0, verification_fails=False)
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=models,
        delivery_route_adapters=_KnowledgeFixtureFactory(remaining),
    )
    with monkeypatch.context() as old_platform:
        if legacy_context:
            from ai_software_engineer.recovery.context import prerequisite_repair_context

            def legacy_repair_context(plan: PrerequisiteRepairPlan) -> ContextSource:
                source = prerequisite_repair_context(plan)
                assert source.content is not None
                return source.model_copy(
                    update={
                        "content": source.content.replace(
                            "Its source is an inconclusive QA or executor observation, "
                            "not a business defect verdict.",
                            "The previous QA is INCONCLUSIVE, not a business defect.",
                        )
                    }
                )

            old_platform.setattr(
                "ai_software_engineer.recovery.resume.approved_parent_context", lambda *args: ()
            )
            old_platform.setattr(
                "ai_software_engineer.recovery.remediation.prerequisite_repair_context",
                legacy_repair_context,
            )
        result = host.resume_delivery(
            ResumeProjectDelivery(
                delivery_id=blocked.delivery_id,
                approved_repair_sha256=repair.plan_sha256,
                approval_reference="fixture-exact-repair",
            )
        )
    assert isinstance(result, JointDeliveryResult)
    waiting = result.checkpoint
    assert waiting.stage.value == "WAITING_HUMAN" and waiting.knowledge_gap_id is not None
    assert [request.role for request in remaining.requests] == [AgentRole.CODER]
    native_wait = host.project_entry().status(repair.delivery_id).checkpoint
    assert native_wait.stage is DeliveryStage.DELIVERING
    assert native_wait.task_id is not None
    if native_rules and not legacy_context:
        from ai_software_engineer.context import FileContextStore

        context = FileContextStore(
            Path(config.platform_root)
            / "projects"
            / waiting.project_id
            / "repositories"
            / native_wait.repository_id
            / "contexts"
        ).get(remaining.requests[0].context_manifest_id)
        assert len([s for s in context.sections if s.name.startswith("source:native.rule.")]) == 3
        if changed_native_rules:
            assert any(
                s.uri.endswith("/README.md") and "isolated UI prerequisites" in s.content
                for s in context.sections
            )
    with MySqlTaskRepository(environment["ASE_MYSQL_DSN"]) as repository:
        assert repository.get(native_wait.task_id).status is TaskStatus.QA
    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name
    )
    project = team.project_registry().open(waiting.project_id)
    views = list_gap_views(project, waiting.delivery_id)
    assert any(view.is_current for view in views)
    if legacy_context:
        from ai_software_engineer.knowledge.administration import (
            _gap_belongs_to_requirement,
            find_gap_records,
        )
        from ai_software_engineer.knowledge.gaps import KnowledgeGap

        records = find_gap_records(project, waiting.delivery_id, waiting.knowledge_gap_id)
        gap = records.get("gaps", waiting.knowledge_gap_id, KnowledgeGap)
        assert gap.binding.requirement_id == native_wait.task_id
        for changes in (
            {"source_revision": "e" * 40},
            {"task_id": "task_continue_other", "requirement_id": "task_continue_other"},
            {"repository_ids": ("repository_other",)},
            {"project_id": "project_other"},
        ):
            other = gap.model_copy(update={"binding": gap.binding.model_copy(update=changes)})
            assert not _gap_belongs_to_requirement(project, waiting.delivery_id, other)
    answer = "隔离测试前提已确认, 仍由 QA 独立执行; 不提供验收结论。"
    approve_resolution(
        project,
        waiting.delivery_id,
        ApproveKnowledgeResolution(
            gap_id=waiting.knowledge_gap_id,
            answer=answer,
            sources=(
                KnowledgeResolutionSource(
                    uri="human://fixture", content=answer, sha256=text_digest(answer)
                ),
            ),
            approval_reference="fixture-resolution",
        ),
    )
    gap_enabled = False
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=models,
        delivery_route_adapters=_KnowledgeFixtureFactory(remaining),
    )
    if legacy_context:
        # Reproduce the live pre-model context failure through the application,
        # not by editing a checkpoint or resetting the still-QA Task.
        def reject_context(*args: object) -> tuple[ContextSource, ...]:
            raise ValueError("fixture historical context mismatch")

        with monkeypatch.context() as broken_reader:
            broken_reader.setattr(
                "ai_software_engineer.manager.production_backend._continuation_context",
                reject_context,
            )
            stopped = host.resume_delivery(ResumeProjectDelivery(delivery_id=waiting.delivery_id))
        assert isinstance(stopped, JointDeliveryResult)
        assert stopped.checkpoint.stage.value == "BLOCKED"
        native_stop = host.project_entry().status(repair.delivery_id).checkpoint
        assert native_stop.task_status is TaskStatus.QA
        assert native_stop.failure_code is not None
        assert native_stop.failure_code.value == "INVARIANT_VIOLATION"
        assert [request.role for request in remaining.requests] == [AgentRole.CODER]
    done = host.resume_delivery(ResumeProjectDelivery(delivery_id=waiting.delivery_id))
    assert isinstance(done, JointDeliveryResult) and done.checkpoint.stage.value == "DONE"
    assert [request.role for request in remaining.requests] == [
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]  # One Coder per repository, never a duplicate for the repaired candidate.


@pytest.mark.mysql
@pytest.mark.parametrize("restart_before_coder", [False, True])
@pytest.mark.parametrize("executor_block", [False, True])
def test_explicit_prerequisite_repair_dispatches_coder_then_independent_verifiers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restart_before_coder: bool,
    executor_block: bool,
) -> None:
    # This fixture tests explicit repair authority and dispatch/restart, not Manager
    # inference. The upstream scripted client only implements Product/Design/Plan.
    monkeypatch.setattr(CandidateVerificationEntry, "coordinate", lambda *_: None)
    dsn = os.environ["ASE_TEST_MYSQL_DSN"]
    project = tmp_path / "project"
    project.mkdir()
    (project / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=project)
    _git("add", "hello.txt", cwd=project)
    _git("commit", "-m", "initial", cwd=project)
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        default_project_id="project_test",
        default_project_name="Test Project",
        live_model_execution=True,
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.6-terra", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    routes = _ResumeFactory(transient_qa_failures=0, verification_inconclusive=True)
    host = TeamHost(
        config=config,
        environment={"ASE_MYSQL_DSN": dsn, "PATH": os.environ.get("PATH", "")},
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=routes,
    )
    entry = host.project_entry()
    started = entry.start(
        StartProjectDelivery(repository_root=str(project), requirement="Change greeting.")
    )
    blocked = entry.approve(
        ApproveProductSpec(
            delivery_id=started.checkpoint.delivery_id,
            expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
            approval_reference="fixture-user",
        )
    ).checkpoint
    assert blocked.stage is DeliveryStage.BLOCKED
    if executor_block:
        monkeypatch.setattr(
            "ai_software_engineer.recovery.verification_entry._executor_capability",
            lambda *_: capability(),
        )
    proposal = host.resume_delivery(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    assert isinstance(proposal, DeliveryResumeResult)
    verify = ResumeProjectDelivery(
        delivery_id=blocked.delivery_id,
        approved_plan_sha256=proposal.verification_plan_sha256,
        approval_reference="fixture-verification",
    )
    if executor_block:
        original_execute = CandidateVerificationEntry.execute

        def execute(
            self: CandidateVerificationEntry, path: Path
        ) -> CandidateVerificationCompletion:
            return original_execute(
                self, path, route_factory=ConfiguredDeliveryRouteAdapterFactory()
            )

        def create(
            self: ConfiguredDeliveryRouteAdapterFactory,
            *,
            route: ProviderRouteConfig,
            definition: AgentDefinition,
            binding: RoleWorktreeBinding,
            context_resolver: StoredContextResolver,
            config: ProductionConfig,
            environment: Mapping[str, str],
        ) -> AgentAdapter:
            provider = self._verification_evidence
            assert provider is not None

            class BeforeModel:
                def run(self, request: AgentRequest) -> AgentResult:
                    assert provider is not None
                    provider.evidence_for(request, binding.worktree.path)
                    raise AssertionError("timed-out executor must not invoke a QA model")

            return BeforeModel()

        def timeout(*args: object, **kwargs: object) -> None:
            raise CommandTimedOut(("fixture",), 1)

        with monkeypatch.context() as failure:
            failure.setattr(CandidateVerificationEntry, "execute", execute)
            failure.setattr(CandidateVerificationEntry, "coordinate", lambda *_: None)
            failure.setattr(ConfiguredDeliveryRouteAdapterFactory, "create", create)
            failure.setattr(SubprocessCommandExecutor, "run", timeout)
            failure.setattr(
                "ai_software_engineer.recovery.verification_execution.discover_swift_sandbox_capability",
                lambda _: capability(),
            )
            after_qa = host.resume_delivery(verify)
    else:
        after_qa = host.resume_delivery(verify)
    assert isinstance(after_qa, DeliveryResumeResult)
    assert after_qa.outcome is (
        DeliveryResumeOutcome.WAITING_HUMAN
        if executor_block
        else DeliveryResumeOutcome.VERIFICATION_APPROVAL_REQUIRED
    )
    before = len(routes.requests)
    repair = host.resume_delivery(
        ResumeProjectDelivery(
            delivery_id=blocked.delivery_id,
            prerequisite_repair=PrerequisiteRepairRequest(
                objective="Implement an isolated prerequisite fixture; preserve original greeting.",
                write_paths=("hello.txt", "tests/**"),
            ),
        )
    )
    assert isinstance(repair, DeliveryResumeResult)
    assert repair.outcome is DeliveryResumeOutcome.REPAIR_APPROVAL_REQUIRED
    assert repair.prerequisite_repair_plan is not None
    if executor_block:
        assert repair.prerequisite_repair_plan.executor_prerequisite_sha256 is not None
        assert repair.prerequisite_repair_plan.completion_sha256 is None
    assert len(routes.requests) == before
    approval = ResumeProjectDelivery(
        delivery_id=blocked.delivery_id,
        approved_repair_sha256=repair.prerequisite_repair_plan.plan_sha256,
        approval_reference="fixture-delegated-approval",
    )
    if restart_before_coder:

        class SimulatedProcessExit(BaseException):
            pass

        def crash(*args: object, **kwargs: object) -> None:
            raise SimulatedProcessExit()

        with monkeypatch.context() as interruption:
            interruption.setattr(ProductionProjectDeliveryBackend, "run_prepared_allocation", crash)
            with pytest.raises(SimulatedProcessExit):
                host.resume_delivery(approval)
        assert len(routes.requests) == before
        host = TeamHost(
            config=config,
            environment={"ASE_MYSQL_DSN": dsn, "PATH": os.environ.get("PATH", "")},
            structured_clients=_ScriptedClientFactory(),
            delivery_route_adapters=routes,
        )
        delivered = host.resume_delivery(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    else:
        delivered = host.resume_delivery(approval)
    assert isinstance(delivered, DeliveryResumeResult)
    assert delivered.checkpoint.stage is DeliveryStage.DONE
    assert delivered.checkpoint.candidate_revision != blocked.candidate_revision
    assert [request.role for request in routes.requests[before:]] == [
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]
    repository = MySqlTaskRepository(dsn)
    try:
        assert blocked.task_id is not None
        assert delivered.checkpoint.task_id is not None
        assert repository.get(blocked.task_id).status is TaskStatus.BLOCKED
        successor = repository.get(delivered.checkpoint.task_id)
        assert successor.metadata["continuation_kind"] == "prerequisite_repair"
        assert (
            successor.metadata["prerequisite_repair_sha256"]
            == repair.prerequisite_repair_plan.plan_sha256
        )
        assert successor.constraints is not None
        assert "tests/**" in successor.constraints.allowed_paths
    finally:
        repository.close()
    calls = len(routes.requests)
    replay = host.resume_delivery(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    assert isinstance(replay, DeliveryResumeResult)
    assert replay.checkpoint == delivered.checkpoint
    assert len(routes.requests) == calls
