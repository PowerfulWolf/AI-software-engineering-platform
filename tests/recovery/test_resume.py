"""One-command candidate verification and remediation on real Git/MySQL."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import timedelta
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
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentRole,
    ImplementationReportArtifact,
    QaCriterionStatus,
    QaReportArtifact,
    QaReportStatus,
    TaskStatus,
)
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    ResumeProjectDelivery,
    StartProjectDelivery,
)
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryStage,
    FileProjectDeliveryCheckpointStore,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.production_delivery import (
    DeliveryRouteAdapterFactory,
)
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.orchestration import AgentRunFailed
from ai_software_engineer.recovery.entry import NativeRecoveryExecution
from ai_software_engineer.recovery.models import RecoveryScope
from ai_software_engineer.recovery.remediation import CandidateRemediationService
from ai_software_engineer.recovery.resume import (
    DeliveryResumeController,
    DeliveryResumeOutcome,
    DeliveryResumeResult,
)
from ai_software_engineer.recovery.seed import RecoverySeedService
from ai_software_engineer.recovery.verification_native import NativeCandidateSourceReader
from ai_software_engineer.role_workspace import RoleWorktreeBinding
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.team_view.reader import ProductionTeamReader
from tests.manager.test_production_backend import (
    _git,
    _git_output,
    _ScriptedClientFactory,
    _ScriptedDeliveryAdapter,
)
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.recovery.test_execution import OfflineFactory
from tests.recovery.test_native import InterruptedFactory


class _ResumeAdapter(AgentAdapter):
    def __init__(
        self,
        owner: _ResumeFactory,
        definition: AgentDefinition,
        workspace: Path,
    ) -> None:
        self._owner = owner
        self._delegate = _ScriptedDeliveryAdapter(definition, workspace)
        self._workspace = workspace

    def run(self, request: AgentRequest) -> AgentResult:
        self._owner.requests.append(request)
        if request.role is AgentRole.CODER and self._owner.source_task_id is None:
            self._owner.source_task_id = request.task_id
        if (
            request.role is AgentRole.CODER
            and request.task_id.startswith("task_continue_")
            and self._owner.remediation_no_candidate
        ):
            return AgentResult(
                run_id=request.run_id,
                task_id=request.task_id,
                role=request.role,
                attempt=request.attempt,
                source_revision=request.source_revision,
                context_manifest_id=request.context_manifest_id,
                status=AgentRunStatus.FAILED,
                error=AgentFailure(
                    code=AgentErrorCode.INVALID_OUTPUT,
                    message="offline Coder produced no candidate",
                    transient=False,
                ),
            )
        if request.role is AgentRole.QA and request.task_id == self._owner.source_task_id:
            self._owner.source_qa_calls += 1
            if self._owner.source_qa_calls <= self._owner.transient_qa_failures:
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
                        message="offline verifier quota exhausted",
                        transient=True,
                    ),
                )
            result = self._delegate.run(request)
            artifact = result.artifact
            assert isinstance(artifact, QaReportArtifact)
            if self._owner.verification_inconclusive:
                criterion = artifact.content.criteria_results[0].model_copy(
                    update={"status": QaCriterionStatus.NOT_TESTED}
                )
                return result.model_copy(
                    update={
                        "artifact": artifact.model_copy(
                            update={
                                "content": artifact.content.model_copy(
                                    update={
                                        "status": QaReportStatus.FAIL,
                                        "criteria_results": (criterion,),
                                    }
                                )
                            }
                        )
                    }
                )
            if self._owner.verification_fails:
                failed = artifact.content.criteria_results[0].model_copy(
                    update={"status": QaCriterionStatus.FAIL}
                )
                return result.model_copy(
                    update={
                        "artifact": artifact.model_copy(
                            update={
                                "content": artifact.content.model_copy(
                                    update={
                                        "status": QaReportStatus.FAIL,
                                        "criteria_results": (failed,),
                                    }
                                )
                            }
                        )
                    }
                )
        result = self._delegate.run(request)
        if request.role is AgentRole.CODER and request.task_id.startswith("task_continue_"):
            artifact = result.artifact
            assert isinstance(artifact, ImplementationReportArtifact)
            _git("commit", "--amend", "-m", "Remediate rejected candidate", cwd=self._workspace)
            candidate = _git_output("rev-parse", "HEAD", cwd=self._workspace)
            result = result.model_copy(
                update={
                    "artifact": artifact.model_copy(
                        update={
                            "source_revision": candidate,
                            "content": artifact.content.model_copy(
                                update={"commit_sha": candidate}
                            ),
                        }
                    )
                }
            )
        return result


class _ResumeFactory(DeliveryRouteAdapterFactory):
    def __init__(
        self,
        *,
        transient_qa_failures: int = 4,
        verification_fails: bool = True,
        verification_inconclusive: bool = False,
        remediation_no_candidate: bool = False,
    ) -> None:
        self.requests: list[AgentRequest] = []
        self.source_task_id: str | None = None
        self.source_qa_calls = 0
        self.transient_qa_failures = transient_qa_failures
        self.verification_fails = verification_fails
        self.verification_inconclusive = verification_inconclusive
        self.remediation_no_candidate = remediation_no_candidate

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
        return _ResumeAdapter(self, definition, binding.worktree.path)


class _SeededInterruptedRecoveryAdapter(AgentAdapter):
    def __init__(self, seed: RecoverySeedService, workspace: Path) -> None:
        self._seed = seed
        self._workspace = workspace

    def run(self, request: AgentRequest) -> AgentResult:
        assert request.role is AgentRole.CODER
        self._seed.authorize(request, self._workspace)
        (self._workspace / "hello.txt").write_text("partially implemented\n", encoding="utf-8")
        return AgentResult(
            run_id=request.run_id,
            task_id=request.task_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=AgentRunStatus.FAILED,
            error=AgentFailure(
                code=AgentErrorCode.POLICY_VIOLATION,
                message="offline recovery Coder interrupted",
                transient=False,
            ),
        )


class _SeededInterruptedRecoveryFactory(DeliveryRouteAdapterFactory):
    def __init__(self, seed: RecoverySeedService) -> None:
        self._seed = seed

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
        del route, definition, context_resolver, config, environment
        return _SeededInterruptedRecoveryAdapter(self._seed, binding.worktree.path)


def _append_equivalent_delivery_checkpoint(
    config: ProductionConfig, checkpoint: ProjectDeliveryCheckpoint
) -> ProjectDeliveryCheckpoint:
    if config.default_project_id is None:
        raise AssertionError("test fixture requires a default Project")
    root = (
        Path(config.platform_root)
        / "projects"
        / config.default_project_id
        / "repositories"
        / checkpoint.repository_id
        / "state/project-deliveries"
    )
    store = FileProjectDeliveryCheckpointStore(root)
    values = checkpoint.to_wire()
    values.pop("checkpoint_sha256")
    return store.put(
        ProjectDeliveryCheckpoint.create(
            **{
                **values,
                "sequence": checkpoint.sequence + 1,
                "previous_checkpoint_sha256": checkpoint.checkpoint_sha256,
                "checkpointed_at": checkpoint.checkpointed_at + timedelta(microseconds=1),
            }
        )
    )


@pytest.mark.mysql
def test_resume_discovers_approves_and_attaches_pre_candidate_coder_recovery(
    tmp_path: Path,
    mysql_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "hello.txt").write_text("hello\n", encoding="utf-8")
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
                provider="codex",
                model="gpt-5.6-terra",
                kind=ModelProviderKind.CODEX_CLI,
            ),
        ),
    )
    environment = {"ASE_MYSQL_DSN": mysql_dsn, "PATH": os.environ.get("PATH", "")}
    interrupted = InterruptedFactory()
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=interrupted,
    )
    entry = host.project_entry()
    started = entry.start(
        StartProjectDelivery(repository_root=str(project), requirement="Change the greeting.")
    )
    blocked = entry.approve(
        ApproveProductSpec(
            delivery_id=started.checkpoint.delivery_id,
            expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
            approval_reference="resume-pre-candidate-test",
        )
    ).checkpoint
    assert blocked.stage is DeliveryStage.BLOCKED
    assert blocked.candidate_revision is None

    recovery = host.recovery_entry()
    controller = DeliveryResumeController(
        config=config,
        environment=environment,
        backend=recovery.backend,
        entry=entry,
        recovery=recovery,
        verification=host.verification_entry(),
    )
    proposed = controller.resume(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    assert proposed.outcome is DeliveryResumeOutcome.RECOVERY_APPROVAL_REQUIRED
    assert proposed.recovery_plan_sha256 is not None

    def execute_interrupted(path: Path) -> NativeRecoveryExecution:
        store, plan = recovery.open_plan(path)
        delivery = recovery.execute(path, route_factory=_SeededInterruptedRecoveryFactory)
        return NativeRecoveryExecution(plan, recovery._dispatch_for(store, plan), delivery)

    monkeypatch.setattr(recovery, "resume_execution", execute_interrupted)
    interrupted_recovery = controller.resume(
        ResumeProjectDelivery(
            delivery_id=blocked.delivery_id,
            approved_plan_sha256=proposed.recovery_plan_sha256,
            approval_reference="resume-pre-candidate-approved",
        )
    )
    assert interrupted_recovery.outcome is DeliveryResumeOutcome.WAITING_HUMAN
    assert interrupted_recovery.checkpoint.stage is DeliveryStage.BLOCKED
    assert interrupted_recovery.checkpoint.candidate_revision is None
    first_recovery_task = interrupted_recovery.checkpoint.task_id
    assert first_recovery_task is not None and first_recovery_task.startswith("task_recovery_")

    reproposed = controller.resume(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    assert reproposed.outcome is DeliveryResumeOutcome.RECOVERY_APPROVAL_REQUIRED
    assert reproposed.recovery_plan_sha256 is not None
    assert reproposed.recovery_plan_sha256 != proposed.recovery_plan_sha256

    def execute_offline(path: Path) -> NativeRecoveryExecution:
        store, plan = recovery.open_plan(path)
        delivery = recovery.execute(path, route_factory=OfflineFactory)
        return NativeRecoveryExecution(plan, recovery._dispatch_for(store, plan), delivery)

    monkeypatch.setattr(recovery, "resume_execution", execute_offline)
    completed = controller.resume(
        ResumeProjectDelivery(
            delivery_id=blocked.delivery_id,
            approved_plan_sha256=reproposed.recovery_plan_sha256,
            approval_reference="resume-second-recovery-approved",
        )
    )
    assert completed.outcome is DeliveryResumeOutcome.RECOVERED
    assert completed.checkpoint.stage is DeliveryStage.DONE
    assert completed.checkpoint.task_id is not None
    assert completed.checkpoint.task_id.startswith("task_recovery_")
    assert completed.checkpoint.candidate_revision is not None
    assert entry.status(blocked.delivery_id).checkpoint == completed.checkpoint

    repository = MySqlTaskRepository(mysql_dsn)
    try:
        assert blocked.task_id is not None
        assert repository.get(blocked.task_id).status is TaskStatus.BLOCKED
        assert repository.get(first_recovery_task).status is TaskStatus.BLOCKED
        assert repository.get(completed.checkpoint.task_id).status is TaskStatus.DONE
    finally:
        repository.close()


@pytest.mark.mysql
def test_resume_verifies_failed_candidate_and_delivers_remediation(
    tmp_path: Path,
    mysql_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "hello.txt").write_text("hello\n", encoding="utf-8")
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
                provider="codex",
                model="gpt-5.6-terra",
                kind=ModelProviderKind.CODEX_CLI,
            ),
        ),
    )
    environment = {"ASE_MYSQL_DSN": mysql_dsn, "PATH": os.environ.get("PATH", "")}
    routes = _ResumeFactory()
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
            approval_reference="resume-integration-test",
        )
    ).checkpoint
    assert blocked.stage is DeliveryStage.BLOCKED
    assert blocked.task_status is TaskStatus.BLOCKED
    assert blocked.candidate_revision is not None
    assert routes.source_task_id == blocked.task_id

    proposed = host.resume_delivery(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    assert isinstance(proposed, DeliveryResumeResult)
    assert proposed.outcome is DeliveryResumeOutcome.VERIFICATION_APPROVAL_REQUIRED
    assert proposed.verification_plan_sha256 is not None
    before_candidate = blocked.candidate_revision

    with pytest.raises(AgentRunFailed, match="offline verifier quota exhausted"):
        host.resume_delivery(
            ResumeProjectDelivery(
                delivery_id=blocked.delivery_id,
                approved_plan_sha256=proposed.verification_plan_sha256,
                approval_reference="resume-integration-test-verification",
            )
        )
    live = ProductionTeamReader(config, environment).snapshot()
    verification_work = next(
        task
        for task in live.tasks
        if task.work_kind == "candidate_verification"
        and task.plan_sha256 == proposed.verification_plan_sha256
    )
    assert verification_work.status == "VERIFY_QA"
    assert len(verification_work.runs) == 1
    assert verification_work.runs[0].role is AgentRole.QA
    calls_after_uncertain_result = len(routes.requests)
    successor = host.resume_delivery(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    assert isinstance(successor, DeliveryResumeResult)
    assert successor.outcome is DeliveryResumeOutcome.VERIFICATION_APPROVAL_REQUIRED
    assert successor.verification_plan_sha256 is not None
    assert successor.verification_plan_sha256 != proposed.verification_plan_sha256
    assert len(routes.requests) == calls_after_uncertain_result
    advanced = _append_equivalent_delivery_checkpoint(config, blocked)
    assert entry.status(blocked.delivery_id).checkpoint == advanced

    finish_continuation = entry.finish_continuation

    def interrupt_after_terminal_task(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("simulated process loss before Delivery checkpoint")

    observed_remediation: list[str] = []
    original_adapter_run = _ResumeAdapter.run

    def observe_remediation(adapter: _ResumeAdapter, request: AgentRequest) -> AgentResult:
        if request.role is AgentRole.CODER and request.task_id.startswith("task_continue_"):
            live = ProductionTeamReader(config, environment).snapshot()
            remediation = next(task for task in live.tasks if task.task_id == request.task_id)
            assert remediation.work_kind == "remediation"
            assert remediation.source_task_id == blocked.task_id
            superseded = next(
                task for task in live.tasks if task.plan_sha256 == proposed.verification_plan_sha256
            )
            assert superseded.status == "VERIFICATION_SUPERSEDED"
            assert superseded.terminal
            assert not any(item.current_stage for item in superseded.assignments)
            observed_remediation.append(request.task_id)
        return original_adapter_run(adapter, request)

    monkeypatch.setattr(_ResumeAdapter, "run", observe_remediation)
    monkeypatch.setattr(entry, "finish_continuation", interrupt_after_terminal_task)
    with pytest.raises(RuntimeError, match="simulated process loss"):
        host.resume_delivery(
            ResumeProjectDelivery(
                delivery_id=blocked.delivery_id,
                approved_plan_sha256=successor.verification_plan_sha256,
                approval_reference="resume-integration-test-successor",
            )
        )
    assert len(observed_remediation) == 1
    interrupted = entry.status(blocked.delivery_id).checkpoint
    assert interrupted.stage is DeliveryStage.DELIVERING
    assert interrupted.task_id is not None
    repository = MySqlTaskRepository(mysql_dsn)
    try:
        assert repository.get(interrupted.task_id).status is TaskStatus.DONE
    finally:
        repository.close()

    monkeypatch.setattr(entry, "finish_continuation", finish_continuation)
    call_count = len(routes.requests)
    delivered = host.resume_delivery(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    assert isinstance(delivered, DeliveryResumeResult)
    assert delivered.outcome is DeliveryResumeOutcome.CONTINUED
    assert delivered.checkpoint.stage is DeliveryStage.DONE
    assert delivered.checkpoint.task_status is TaskStatus.DONE
    assert delivered.checkpoint.candidate_revision != before_candidate
    assert delivered.checkpoint.task_id is not None
    assert delivered.checkpoint.task_id.startswith("task_continue_")

    repository = MySqlTaskRepository(mysql_dsn)
    try:
        assert blocked.task_id is not None
        assert repository.get(blocked.task_id).status is TaskStatus.BLOCKED
        assert repository.get(delivered.checkpoint.task_id).status is TaskStatus.DONE
    finally:
        repository.close()
    assert [request.role for request in routes.requests] == [
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.QA,
        AgentRole.QA,
        AgentRole.QA,
        AgentRole.QA,
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]
    assert len(routes.requests) == call_count
    replay = host.resume_delivery(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    assert isinstance(replay, DeliveryResumeResult)
    assert replay.checkpoint == delivered.checkpoint
    assert len(routes.requests) == call_count


@pytest.mark.mysql
def test_resume_accepts_verified_candidate_after_delivery_checkpoint_append(
    tmp_path: Path,
    mysql_dsn: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "hello.txt").write_text("hello\n", encoding="utf-8")
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
                provider="codex",
                model="gpt-5.6-terra",
                kind=ModelProviderKind.CODEX_CLI,
            ),
        ),
    )
    environment = {"ASE_MYSQL_DSN": mysql_dsn, "PATH": os.environ.get("PATH", "")}
    routes = _ResumeFactory(transient_qa_failures=3, verification_fails=False)
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
            approval_reference="resume-verified-prefix",
        )
    ).checkpoint
    assert blocked.stage is DeliveryStage.BLOCKED
    proposed = host.resume_delivery(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    assert isinstance(proposed, DeliveryResumeResult)
    assert proposed.outcome is DeliveryResumeOutcome.VERIFICATION_APPROVAL_REQUIRED
    assert proposed.verification_plan_sha256 is not None
    advanced = _append_equivalent_delivery_checkpoint(config, blocked)

    verified = host.resume_delivery(
        ResumeProjectDelivery(
            delivery_id=blocked.delivery_id,
            approved_plan_sha256=proposed.verification_plan_sha256,
            approval_reference="resume-verified-prefix-approval",
        )
    )

    assert isinstance(verified, DeliveryResumeResult)
    assert verified.outcome is DeliveryResumeOutcome.VERIFIED
    assert verified.checkpoint.stage is DeliveryStage.DONE
    assert verified.checkpoint.previous_checkpoint_sha256 == advanced.checkpoint_sha256
    assert entry.status(blocked.delivery_id).checkpoint == verified.checkpoint


@pytest.mark.mysql
def test_resume_reuses_retained_candidate_after_legacy_inconclusive_remediation(
    tmp_path: Path,
    mysql_dsn: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "hello.txt").write_text("hello\n", encoding="utf-8")
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
                provider="codex",
                model="gpt-5.6-terra",
                kind=ModelProviderKind.CODEX_CLI,
            ),
        ),
    )
    environment = {"ASE_MYSQL_DSN": mysql_dsn, "PATH": os.environ.get("PATH", "")}
    routes = _ResumeFactory(
        transient_qa_failures=3,
        verification_fails=False,
        verification_inconclusive=True,
        remediation_no_candidate=True,
    )
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
            approval_reference="resume-inconclusive-source",
        )
    ).checkpoint
    proposed = host.resume_delivery(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    assert isinstance(proposed, DeliveryResumeResult)
    assert proposed.verification_plan_sha256 is not None
    assert proposed.verification_plan_file is not None
    verification = host.verification_entry()
    verification.approve(
        Path(proposed.verification_plan_file),
        confirmed_plan=proposed.verification_plan_sha256,
        reference="resume-inconclusive-verification",
    )
    completion = verification.execute(Path(proposed.verification_plan_file))
    assert not completion.verified

    store, plan = verification.open(Path(proposed.verification_plan_file))
    assert store.get_verification_completion(plan.plan_sha256) == completion
    source = NativeCandidateSourceReader(config, environment).inspect(
        RecoveryScope(
            team_id=config.team_id,
            repository_id=blocked.repository_id,
            repository_root=blocked.repository_root,
            delivery_id=blocked.delivery_id,
        )
    )
    backend = host.recovery_entry().backend
    remediation = CandidateRemediationService(
        backend=backend,
        config=config,
        environment=environment,
    ).prepare(source=source, store=store, plan=plan, completion=completion)
    entry.begin_continuation(
        remediation.dispatch,
        plan,
        completion,
        at=completion.completed_at,
    )
    delivery = backend.run_prepared_allocation(
        remediation.dispatch,
        remediation.preparation,
        remediation.source.stages.product,
        remediation.source.stages.design,
        remediation.source.stages.plan,
        extra_context=remediation.context_sources,
    )
    terminal = entry.finish_continuation(
        remediation.dispatch,
        delivery,
        at=delivery.task.updated_at,
    ).checkpoint
    assert terminal.stage is DeliveryStage.BLOCKED
    assert terminal.candidate_revision is None

    calls = len(routes.requests)
    resumed = host.resume_delivery(ResumeProjectDelivery(delivery_id=blocked.delivery_id))

    assert isinstance(resumed, DeliveryResumeResult)
    assert resumed.outcome is DeliveryResumeOutcome.VERIFICATION_APPROVAL_REQUIRED
    assert resumed.verification_plan_sha256 is not None
    assert resumed.verification_plan_sha256 != proposed.verification_plan_sha256
    assert len(routes.requests) == calls
