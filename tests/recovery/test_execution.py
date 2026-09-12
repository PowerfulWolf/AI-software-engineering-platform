"""Full linked recovery on real Git/MySQL; provider process is explicitly offline."""

import json
import os
from collections.abc import Mapping
from pathlib import Path

import pytest

import ai_software_engineer.manager.production_backend as production_backend
from ai_software_engineer.agents import (
    AgentAdapter,
    AgentRequest,
    AgentResult,
    CodexCliAgentAdapter,
    CodexInvocationResult,
    ContextPromptBuilder,
    StoredContextResolver,
)
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.context import FileContextBuilder, FileContextStore
from ai_software_engineer.domain import AgentDefinition, AgentRole, TaskStatus
from ai_software_engineer.evaluation import CaseStartedEvent, FileEvaluationEventStore
from ai_software_engineer.git import WorktreeCaptureRejected, WorktreeSeedRejected
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    ReplyToProduct,
    StartProjectDelivery,
)
from ai_software_engineer.manager.dispatch import DispatchCommitCorruption
from ai_software_engineer.manager.mysql_dispatch_authority import MySqlDispatchAuthority
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.multi_directory.service import CreateRequirement
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.orchestration.retry import RetryDeliveryResult
from ai_software_engineer.planning import FileExecutionPlanStore
from ai_software_engineer.product import FileProductRecordStore
from ai_software_engineer.recovery import RecoveryRejected
from ai_software_engineer.recovery.entry import read_recovery_task
from ai_software_engineer.recovery.native import NativeRecoverySourceReader
from ai_software_engineer.recovery.seed import RecoverySeedService
from ai_software_engineer.recovery.store import RecoveryRecordMissing
from ai_software_engineer.role_workspace import RoleWorktreeBinding
from ai_software_engineer.runtime import _default_case_id
from ai_software_engineer.store import MySqlTaskRepository
from tests.e2e.test_joint_delivery import setup_host
from tests.git.test_capture import git
from tests.manager.test_production_backend import (
    _git,
    _ScriptedClientFactory,
    _ScriptedDeliveryAdapter,
)
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.recovery.test_native import InterruptedFactory, _snapshot


class OfflineRunner:
    def __init__(
        self,
        definition: AgentDefinition,
        root: Path,
        calls: list[AgentRequest],
        *,
        reapply: bool = False,
    ) -> None:
        self.definition, self.root, self.calls = definition, root, calls
        self.reapply = reapply
        self.request: AgentRequest | None = None

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
    ) -> CodexInvocationResult:
        assert self.request is not None and cwd == self.root
        assert (
            timeout_seconds
            == {
                AgentRole.CODER: 1_800,
                AgentRole.QA: 1_200,
                AgentRole.REVIEWER: 1_200,
            }[self.request.role]
        )
        reserve_seconds = {
            AgentRole.CODER: 300,
            AgentRole.QA: 240,
            AgentRole.REVIEWER: 240,
        }[self.request.role]
        assert f"hard execution limit is {int(timeout_seconds)} seconds" in stdin
        assert f"Reserve the final {reserve_seconds} seconds" in stdin
        if self.request.role is AgentRole.CODER:
            assert "Do not run git add or git commit" in stdin
            assert "platform will policy-check and bind the candidate" in stdin
            if self.reapply:
                assert (cwd / "hello.txt").read_text() == "new base greeting\n"
                assert git(cwd, "status", "--porcelain") == ""
                assert "recovery.patch" in stdin and "partially implemented" in stdin
            else:
                assert (cwd / "hello.txt").read_text() == "partially implemented\n"
            assert "recovery.origin" in stdin
        self.calls.append(self.request)
        result = _ScriptedDeliveryAdapter(self.definition, cwd).run(self.request)
        assert result.artifact is not None
        Path(argv[argv.index("--output-last-message") + 1]).write_text(
            json.dumps(result.artifact.to_wire())
        )
        return CodexInvocationResult(returncode=0)


class OfflineAdapter:
    def __init__(
        self, adapter: CodexCliAgentAdapter, runner: OfflineRunner, seed: RecoverySeedService
    ) -> None:
        self.adapter, self.runner = adapter, runner
        self.seed = seed

    def run(self, request: AgentRequest) -> AgentResult:
        self.runner.request = request
        if request.role is AgentRole.CODER:
            for bad, root in (
                (request.model_copy(update={"task_id": "task_wrong"}), self.runner.root),
                (request.model_copy(update={"source_revision": "0" * 40}), self.runner.root),
                (request.model_copy(update={"attempt": 2}), self.runner.root),
                (
                    request.model_copy(
                        update={
                            "permissions": request.permissions.model_copy(
                                update={"write_paths": ("**",)}
                            )
                        }
                    ),
                    self.runner.root,
                ),
                (request, self.runner.root.parent),
            ):
                with pytest.raises(RecoveryRejected):
                    self.seed.authorize(bad, root)
            receipt = self.seed.store.get_seed(self.seed.dispatch.recovery_plan_sha256)
            if self.runner.reapply:
                without_patch = FileContextBuilder(self.runner.root, request.permissions).build(
                    self.seed.dispatch.task, AgentRole.CODER, attempt=1
                )
                wrong_context = self.seed.contexts.put(without_patch)
                with pytest.raises(RecoveryRejected, match="complete approved recovery patch"):
                    self.seed.authorize(
                        request.model_copy(
                            update={"context_manifest_id": wrong_context.context_id}
                        ),
                        self.runner.root,
                    )
            before = (self.runner.root / "hello.txt").read_bytes()
            (self.runner.root / "hello.txt").write_text("unexpected drift\n")
            with pytest.raises(WorktreeCaptureRejected):
                self.seed.verify(receipt)
            (self.runner.root / "hello.txt").write_bytes(before)
            self.seed.verify(receipt)
            with pytest.raises(RecoveryRecordMissing):
                self.seed.store.get_invocation(self.seed.dispatch.recovery_plan_sha256)
        return self.adapter.run(request)


class OfflineFactory:
    def __init__(self, seed: RecoverySeedService) -> None:
        self.seed = seed
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
        plan = self.seed.store.get_plan(self.seed.dispatch.recovery_plan_sha256)
        runner = OfflineRunner(
            definition,
            binding.worktree.path,
            self.calls,
            reapply=plan.input_mode == "coder_reapply",
        )
        return OfflineAdapter(
            CodexCliAgentAdapter(
                workspace_root=binding.worktree.path,
                model=route.model,
                agent_id=definition.id,
                agent_version=definition.version,
                prompt_builder=ContextPromptBuilder(context_resolver),
                environment=environment,
                runner=runner,
                initial_workspace_admission=self.seed
                if definition.role is AgentRole.CODER
                else None,
            ),
            runner,
            self.seed,
        )


@pytest.mark.mysql
@pytest.mark.parametrize(
    ("reapply", "legacy_direct_commit"),
    [(False, False), (True, False), (True, True)],
)
def test_recovery_complete_native_delivery_and_preserve_failed_history(
    tmp_path: Path,
    mysql_dsn: str,
    reapply: bool,
    legacy_direct_commit: bool,
    monkeypatch: pytest.MonkeyPatch,
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
        default_project_name="Test Project",
        live_model_execution=True,
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    environment = {"ASE_MYSQL_DSN": mysql_dsn, "PATH": os.environ.get("PATH", "")}
    current_task_commands = production_backend._task_commands
    if legacy_direct_commit:
        monkeypatch.setattr(
            production_backend,
            "_task_commands",
            lambda profile: tuple(
                sorted((*current_task_commands(profile), "git add", "git commit"))
            ),
        )
    interrupted = InterruptedFactory()
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=interrupted,
    )
    entry = host.project_entry()
    started = entry.start(
        StartProjectDelivery(repository_root=str(project), requirement="Change greeting.")
    )
    failed = entry.approve(
        ApproveProductSpec(
            delivery_id=started.checkpoint.delivery_id,
            expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
            approval_reference="offline-original-approval",
        )
    ).checkpoint
    original_run = interrupted.requests[0]
    if legacy_direct_commit:
        monkeypatch.setattr(production_backend, "_task_commands", current_task_commands)
    recovery = host.recovery_entry()
    (project / "platform-fix.txt").write_text("independent fix\n")
    _git("add", "platform-fix.txt", cwd=project)
    if reapply:
        (project / "hello.txt").write_text("new base greeting\n")
        _git("add", "hello.txt", cwd=project)
    _git("commit", "-m", "platform fixes", cwd=project)
    plan, path = recovery.propose(
        repository_root=str(project),
        delivery_id=failed.delivery_id,
        failed_run_id=original_run.run_id,
        failed_context_id=original_run.context_manifest_id,
        input_mode="coder_reapply" if reapply else None,
    )
    store, loaded = recovery.open_plan(path)
    assert loaded == plan
    assert plan.target_permissions is not None
    assert "git commit" not in plan.target_permissions.commands
    if legacy_direct_commit:
        assert "git commit" in plan.permissions.commands
        assert plan.target_permissions != plan.permissions
    with pytest.raises(RecoveryRejected):
        recovery.execute(path)
    with pytest.raises(RecoveryRejected):
        recovery.approve(path, confirmed_plan="0" * 64, reference="offline-recovery")
    recovery.approve(path, confirmed_plan=plan.plan_sha256, reference="offline-recovery")
    recovery.approve(path, confirmed_plan=plan.plan_sha256, reference="offline-recovery")
    original_tree = Path(plan.capture.worktree_path)
    old_bytes = _snapshot(original_tree)
    repository = MySqlTaskRepository(mysql_dsn)
    try:
        old_task = repository.get(plan.source.task_id)
        old_events = repository.list_events(plan.source.task_id)
    finally:
        repository.close()
    factories: list[OfflineFactory] = []

    def factory(seed: RecoverySeedService) -> OfflineFactory:
        if reapply:
            # Prove this exact input really conflicts on the strict Git path. Preflight
            # must leave the already captured clean target unchanged for Coder reapplication.
            receipt = seed.store.get_seed(plan.plan_sha256)
            with pytest.raises(WorktreeSeedRejected):
                seed.manager.seed_changes(
                    plan.capture.to_capture(),
                    receipt.capture.to_capture().worktree,
                    plan.permissions,
                    seed.permissions,
                    source_denied_paths=plan.denied_paths,
                    target_denied_paths=plan.denied_paths,
                )
            seed.verify(receipt)
        sidecar = path.parent.parent.parent
        authority = MySqlDispatchAuthority(
            mysql_dsn,
            request_revisions=FileProductRecordStore(sidecar / "state/product"),
            planner_records=FileExecutionPlanStore(sidecar / "state/planning"),
        )
        dispatch = authority.get_allocation(seed.dispatch.id)
        assert dispatch == seed.dispatch
        with pytest.raises(DispatchCommitCorruption):
            authority.get_commit(seed.dispatch.id)
        # Original Task's workforce snapshot sees the new reservations as well.
        shared = authority.current_snapshot(
            repository_id=dispatch.repository_id, task_id=plan.source.task_id
        )
        assert {p.lease.id for p in dispatch.phases} <= {lease.id for lease in shared.active_leases}
        assert not any(lease.task_id == plan.source.task_id for lease in shared.active_leases)
        result = OfflineFactory(seed)
        factories.append(result)
        return result

    result = recovery.execute(path, route_factory=factory)
    assert result.task.status is TaskStatus.DONE, result
    assert isinstance(result, RetryDeliveryResult)
    assert read_recovery_task(config, environment, store, plan) == result.task
    assert len(result.artifact_ids) == 4
    assert [r.role for r in factories[0].calls] == [
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]
    assert factories[0].calls[1].source_revision == factories[0].calls[2].source_revision
    assert (project / "hello.txt").read_text() == ("new base greeting\n" if reapply else "hello\n")
    assert (
        git(project, "show", f"{result.candidate_revision}:platform-fix.txt") == "independent fix"
    )
    if reapply:
        assert not store.get_seed(plan.plan_sha256).capture.patch
    assert git(project, "status", "--porcelain") == ""
    assert _snapshot(original_tree) == old_bytes
    assert (
        NativeRecoverySourceReader(config, environment)
        .inspect(
            plan.source.scope,
            failed_run_id=original_run.run_id,
            failed_context_id=original_run.context_manifest_id,
        )
        .source
        == plan.source
    )
    assert store.get_seed(plan.plan_sha256).capture.task_id == result.task.id
    assert store.get_invocation(plan.plan_sha256).run_id == factories[0].calls[0].run_id
    events = FileEvaluationEventStore(path.parent.parent.parent / "evaluations", read_only=True)
    starts = [
        e
        for e in events.list_for_case(_default_case_id(result.task.id))
        if isinstance(e, CaseStartedEvent)
    ]
    assert len(starts) == 1 and starts[0].included is False
    with pytest.raises(RecoveryRejected, match="already admitted"):
        recovery.execute(path, route_factory=factory)
    assert len(factories) == 1
    adopted = recovery.resume_execution(path)
    assert adopted.plan == plan
    assert adopted.delivery == result
    assert adopted.dispatch.task_id == result.task.id
    assert len(factories) == 1
    repository = MySqlTaskRepository(mysql_dsn)
    try:
        assert repository.get(plan.source.task_id) == old_task
        assert repository.list_events(plan.source.task_id) == old_events
        assert repository.get(result.task.id).status is TaskStatus.DONE
    finally:
        repository.close()


@pytest.mark.mysql
def test_joint_child_recovery_retains_approved_parent_context(tmp_path: Path) -> None:
    config, environment, models, projects = setup_host(tmp_path)
    config = config.model_copy(update={"live_model_execution": True})
    interrupted = InterruptedFactory()
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=models,
        delivery_route_adapters=interrupted,
    )
    joint = host.requirement_entry()
    created = joint.create(
        CreateRequirement(
            name="Recovery parent",
            repository_roots=tuple(map(str, projects)),
        )
    ).checkpoint
    product = joint.reply(
        ReplyToProduct(
            delivery_id=created.delivery_id,
            expected_checkpoint_sha256=created.checkpoint_sha256,
            message="Update both greetings",
        )
    ).checkpoint
    parent = joint.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="offline-joint-approved",
        )
    ).checkpoint
    child, run = parent.children[0].checkpoint, interrupted.requests[0]
    recovery = host.recovery_entry()
    plan, path = recovery.propose(
        repository_root=child.repository_root,
        delivery_id=child.delivery_id,
        failed_run_id=run.run_id,
        failed_context_id=run.context_manifest_id,
    )
    recovery.approve(path, confirmed_plan=plan.plan_sha256, reference="offline-joint-recovery")
    result = recovery.execute(path, route_factory=OfflineFactory)
    assert result.task.status is TaskStatus.DONE, result
    assert isinstance(result, RetryDeliveryResult)
    contexts = FileContextStore(path.parent.parent.parent / "contexts", read_only=True)
    for context_id in result.context_manifest_ids:
        context = contexts.get(context_id)
        assert any(s.name == "source:joint.approved_context" for s in context.sections)
    assert (
        JointJournal(host.projects()[0].requirements_root, read_only=True).current(
            parent.delivery_id
        )
        == parent
    )
    assert len(models.calls) == 3
