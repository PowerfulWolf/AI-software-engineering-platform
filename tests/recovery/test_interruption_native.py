"""Real queue/Git recovery after a lost lease, without a provider or fabricated verdict."""

import os
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentAdapter,
    AgentRequest,
    AgentResult,
    CodexCliAgentAdapter,
    ContextPromptBuilder,
    StoredContextResolver,
)
from ai_software_engineer.agents.codex_cli import InitialWorkspaceAdmission
from ai_software_engineer.agents.execution import current_execution_guard
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentDefinition, AgentRole, TaskStatus
from ai_software_engineer.git import WorktreeCaptureRejected
from ai_software_engineer.manager.delivery import ApproveProductSpec, StartProjectDelivery
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.manager.queue_capacity import production_role_queue
from ai_software_engineer.recovery import RecoveryRejected
from ai_software_engineer.recovery.entry import read_recovery_task
from ai_software_engineer.recovery.interruption import RecoveryInterruptionService
from ai_software_engineer.recovery.seed import RecoverySeedService
from ai_software_engineer.role_workspace import RoleWorktreeBinding
from ai_software_engineer.team_view.reader import ProductionTeamReader
from ai_software_engineer.work_queue.ports import QueueLeaseLost
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.manager.test_production_backend import _git, _ScriptedClientFactory
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.recovery.test_execution import OfflineRunner
from tests.recovery.test_native import InterruptedFactory


class LossAdapter:
    def __init__(self, admission: InitialWorkspaceAdmission, root: Path) -> None:
        self.admission, self.root = admission, root

    def run(self, request: AgentRequest) -> AgentResult:
        self.admission.authorize(request, self.root)
        guard = current_execution_guard()
        assert isinstance(guard, WorkerExecutionGuard) and guard.lease is not None
        lease = guard.lease
        lease.stop()
        now = datetime.now(UTC)
        expiry = now + timedelta(milliseconds=50)
        lease.queue.renew(
            lease.claim.work_item.id,
            lease_id=lease.claim.lease.id,
            owner_token=lease._token,
            now=now,
            expires_at=expiry,
        )
        lease._expires_at = expiry
        time.sleep(0.06)
        guard.check()
        raise AssertionError("expired Worker must not continue")


class CompleteAdapter:
    def __init__(self, delegate: CodexCliAgentAdapter, runner: OfflineRunner) -> None:
        self.delegate, self.runner = delegate, runner

    def run(self, request: AgentRequest) -> AgentResult:
        self.runner.request = request
        return self.delegate.run(request)


class Factory:
    def __init__(self, admission: InitialWorkspaceAdmission, *, lose: bool = False) -> None:
        self.admission, self.lose = admission, lose
        self.calls: list[AgentRequest] = []

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
        if self.lose:
            return LossAdapter(self.admission, binding.worktree.path)
        runner = OfflineRunner(definition, binding.worktree.path, self.calls)
        return CompleteAdapter(
            CodexCliAgentAdapter(
                workspace_root=binding.worktree.path,
                model=route.model,
                agent_id=definition.id,
                agent_version=definition.version,
                prompt_builder=ContextPromptBuilder(context_resolver),
                environment=environment,
                runner=runner,
                initial_workspace_admission=self.admission
                if definition.role is AgentRole.CODER
                else None,
            ),
            runner,
        )


@pytest.mark.mysql
def test_exact_interruption_resume_keeps_seed_and_old_invocation(
    tmp_path: Path,
    mysql_dsn: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=project)
    _git("add", "hello.txt", cwd=project)
    _git("commit", "-m", "initial", cwd=project)
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        default_project_id="project_test",
        default_project_name="Test",
        live_model_execution=True,
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    environment = {"ASE_MYSQL_DSN": mysql_dsn, "PATH": os.environ.get("PATH", "")}
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=InterruptedFactory(),
    )
    entry = host.project_entry()
    started = entry.start(
        StartProjectDelivery(repository_root=str(project), requirement="Change greeting.")
    )
    failed = entry.approve(
        ApproveProductSpec(
            delivery_id=started.checkpoint.delivery_id,
            expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
            approval_reference="initial-approval",
        )
    ).checkpoint
    recovery = host.recovery_entry()
    plan, path = recovery.propose_delivery(failed)
    recovery.approve(path, confirmed_plan=plan.plan_sha256, reference="recovery-approval")

    def lost(seed: RecoverySeedService) -> Factory:
        return Factory(seed, lose=True)

    with pytest.raises(QueueLeaseLost):
        recovery.execute(path, route_factory=lost)
    store, _ = recovery.open_plan(path)
    invocation = store.get_invocation(plan.plan_sha256)
    seed = store.get_seed(plan.plan_sha256)
    task = read_recovery_task(config, environment, store, plan)
    assert task is not None and task.status is TaskStatus.IMPLEMENTING
    # Another Task's Dispatcher may have reaped the old claim before this proposal.
    queue = production_role_queue(mysql_dsn)
    now = datetime.now(UTC)
    queue.reclaim_expired(now=now, retry_at=now + timedelta(milliseconds=1))
    snapshot = ProductionTeamReader(config, environment).snapshot()
    current = next(view for view in snapshot.tasks if view.task_id == task.id)
    assert current.role_queue[-1].lease_liveness == "LEASE_EXPIRED"
    assert current.blocker is not None and "租约" in current.blocker
    service = RecoveryInterruptionService(recovery, store, plan)
    proposal = service.propose()
    assert service.propose() == proposal
    with pytest.raises(RecoveryRejected, match="exact interruption"):
        recovery.execute_interruption(path, confirmed_plan=plan.plan_sha256, reference="stale")
    retained = Path(seed.capture.worktree_path) / "hello.txt"
    original = retained.read_bytes()
    retained.write_text("changed after inspection\n")
    with pytest.raises(WorktreeCaptureRejected):
        service.propose()
    retained.write_bytes(original)
    factories: list[Factory] = []

    def complete(admission: InitialWorkspaceAdmission) -> Factory:
        factory = Factory(admission)
        factories.append(factory)
        return factory

    completed = recovery.execute_interruption(
        path,
        confirmed_plan=proposal.plan_sha256,
        reference="exact-interruption-approval",
        route_factory=complete,
    )
    assert completed.delivery.task.status is TaskStatus.DONE  # type: ignore[union-attr]
    assert completed.dispatch.task_id == task.id
    receipt = store.get_interruption_invocation(plan.plan_sha256)
    assert receipt.request.run_id != invocation.run_id
    assert receipt.previous_invocation_sha256 == invocation.record_sha256
    assert receipt.dispatch_sequence == proposal.dispatch_sequence + 1
    assert store.get_invocation(plan.plan_sha256) == invocation
    assert store.get_seed(plan.plan_sha256) == seed
    assert [r.role for r in factories[0].calls] == [
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]
    with pytest.raises(RecoveryRejected, match="already admitted"):
        service.propose()
