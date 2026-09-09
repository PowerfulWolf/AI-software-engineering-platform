"""One-command candidate verification and remediation on real Git/MySQL."""

from __future__ import annotations

import os
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
from ai_software_engineer.orchestration import AgentRunFailed
from ai_software_engineer.project_manager.delivery import (
    ApproveProductSpec,
    ResumeProjectDelivery,
    StartProjectDelivery,
)
from ai_software_engineer.project_manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.project_manager.production_delivery import (
    DeliveryRouteAdapterFactory,
)
from ai_software_engineer.project_manager.production_host import OrganizationTeamHost
from ai_software_engineer.recovery.entry import NativeRecoveryExecution
from ai_software_engineer.recovery.resume import (
    DeliveryResumeController,
    DeliveryResumeOutcome,
    DeliveryResumeResult,
)
from ai_software_engineer.recovery.seed import RecoverySeedService
from ai_software_engineer.role_workspace import RoleWorktreeBinding
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.team_view.reader import ProductionTeamReader
from tests.project_manager.test_production_backend import (
    _git,
    _git_output,
    _ScriptedClientFactory,
    _ScriptedDeliveryAdapter,
)
from tests.project_manager.test_production_backend import mysql_dsn as mysql_dsn
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
        if request.role is AgentRole.QA and request.task_id == self._owner.source_task_id:
            self._owner.source_qa_calls += 1
            if self._owner.source_qa_calls <= 4:
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
    def __init__(self) -> None:
        self.requests: list[AgentRequest] = []
        self.source_task_id: str | None = None
        self.source_qa_calls = 0

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
    host = OrganizationTeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=interrupted,
    )
    entry = host.project_entry()
    started = entry.start(
        StartProjectDelivery(project_root=str(project), requirement="Change the greeting.")
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
        backend=host._recovery_backend,
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
    assert interrupted_recovery.outcome is DeliveryResumeOutcome.RECOVERED
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
    host = OrganizationTeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=routes,
    )
    entry = host.project_entry()
    started = entry.start(
        StartProjectDelivery(project_root=str(project), requirement="Change the greeting.")
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

    finish_continuation = entry.finish_continuation

    def interrupt_after_terminal_task(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("simulated process loss before Delivery checkpoint")

    monkeypatch.setattr(entry, "finish_continuation", interrupt_after_terminal_task)
    with pytest.raises(RuntimeError, match="simulated process loss"):
        host.resume_delivery(
            ResumeProjectDelivery(
                delivery_id=blocked.delivery_id,
                approved_plan_sha256=successor.verification_plan_sha256,
                approval_reference="resume-integration-test-successor",
            )
        )
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
