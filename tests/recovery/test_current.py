"""Real Git/MySQL current-fact gate; all Agents and human decisions are offline fixtures."""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.manager.delivery import ApproveProductSpec, StartProjectDelivery
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.recovery import (
    CapturedChanges,
    FileRecoveryStore,
    RecoveryApprovalCommand,
    RecoveryAuthorizationService,
    RecoveryPlan,
    RecoveryRejected,
    RecoveryScope,
    VerifiedRecoveryDecision,
)
from ai_software_engineer.recovery.current import NativeRecoveryFactsVerifier
from ai_software_engineer.recovery.native import NativeRecoverySourceReader
from ai_software_engineer.recovery.sealing import RecoveryTaskSealingService
from ai_software_engineer.recovery.task import AuthorizedRecoveryTaskBuilder
from tests.git.test_capture import git
from tests.manager.test_production_backend import _git, _ScriptedClientFactory
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.recovery.test_authorization import make_plan
from tests.recovery.test_native import InterruptedFactory, _snapshot


class OfflineHuman:
    def verify(self, command: RecoveryApprovalCommand) -> VerifiedRecoveryDecision:
        return VerifiedRecoveryDecision(
            plan_sha256=command.plan_sha256,
            approval_reference=command.approval_reference,
            approved=True,
            operator_id="offline-human",
            rationale="fixture only",
            decided_at=command.submitted_at,
        )


@pytest.mark.mysql
def test_native_current_gate_and_authorization_preserve_history(
    tmp_path: Path, mysql_dsn: str
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
    factory = InterruptedFactory()
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=factory,
    )
    entry = host.project_entry()
    started = entry.start(
        StartProjectDelivery(repository_root=str(project), requirement="Change greeting.")
    )
    cp = entry.approve(
        ApproveProductSpec(
            delivery_id=started.checkpoint.delivery_id,
            expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
            approval_reference="offline-approved",
        )
    ).checkpoint
    run = factory.requests[0]
    scope = RecoveryScope(
        team_id=config.team_id,
        repository_id=cp.repository_id,
        repository_root=str(project),
        delivery_id=cp.delivery_id,
    )
    original = NativeRecoverySourceReader(config, environment).inspect(
        scope, failed_run_id=run.run_id, failed_context_id=run.context_manifest_id
    )
    manager = GitWorktreeManager(
        project, Path(config.platform_root) / "worktrees" / cp.repository_id
    )
    worktree = manager.recover(
        WorktreeSpec(
            task_id=run.task_id,
            role=AgentRole.CODER,
            attempt=1,
            source_revision=run.source_revision,
        )
    )
    capture = manager.capture_changes(
        worktree, original.permissions, denied_paths=original.denied_paths
    )
    old_plan = RecoveryPlan.create(
        source=original.source,
        capture=CapturedChanges.from_capture(capture),
        target_base_revision=run.source_revision,
        target_preparation_sha256=original.preparation.preparation_sha256,
        permissions=original.permissions,
        denied_paths=original.denied_paths,
        created_at=datetime.now(UTC),
    )
    verifier = NativeRecoveryFactsVerifier(config, environment)
    before = _snapshot(Path(config.platform_root)), _snapshot(project)
    assert verifier.inspect(old_plan).target == original.preparation
    assert (_snapshot(Path(config.platform_root)), _snapshot(project)) == before

    # Normal Host preparation publishes a NEW version, leaving the old records intact.
    (project / "platform-fix.txt").write_text("independent fix\n")
    _git("add", "platform-fix.txt", cwd=project)
    _git("commit", "-m", "new platform base", cwd=project)
    with pytest.raises(RecoveryRejected):
        verifier.validate(old_plan)
    prepared = entry._backend.prepare(str(project)).preparation
    assert prepared is not None and prepared != original.preparation
    plan = RecoveryPlan.create(
        **{
            **old_plan.to_wire(),
            "target_base_revision": git(project, "rev-parse", "HEAD"),
            "target_preparation_sha256": prepared.preparation_sha256,
        }
    )
    before = _snapshot(Path(config.platform_root)), _snapshot(project)
    facts = verifier.inspect(plan)
    assert facts.original == original and facts.target == prepared
    assert NativeRecoveryFactsVerifier(config, environment).inspect(plan) == facts
    assert (_snapshot(Path(config.platform_root)), _snapshot(project)) == before

    # Concrete facts verifier plugs into the existing authorization service.
    sidecar = Path(prepared.repository_workspace_root)
    store = FileRecoveryStore.initialize(sidecar / "recovery-test", scope=scope)
    service = RecoveryAuthorizationService(
        store, facts=verifier, captures=manager, human=OfflineHuman()
    )
    service.propose(plan)
    builder = AuthorizedRecoveryTaskBuilder(service, verifier)
    with pytest.raises(RecoveryRejected):
        builder.build(plan.plan_sha256)
    command = RecoveryApprovalCommand(
        operation_id="op_current_test",
        plan_sha256=plan.plan_sha256,
        approval_reference="offline-recovery-approval",
        submitted_at=datetime.now(UTC),
    )
    service.authorize(command)
    assert service.require_current_authorization(plan.plan_sha256) == plan
    assert service.authorize(command) == store.get_authorization(plan.plan_sha256)
    before = _snapshot(Path(config.platform_root)), _snapshot(project)
    draft = builder.build(plan.plan_sha256)
    assert draft == builder.build(plan.plan_sha256)
    assert draft.task.id == plan.new_task_id and draft.task.id != original.task.id
    assert draft.task.status.value == "NEW" and draft.task.attempts == 0
    assert draft.task.base_ref == plan.target_base_revision
    assert draft.task.constraints == original.task.constraints
    assert draft.task.max_attempts == original.task.max_attempts
    assert draft.facts.original == original
    assert draft.task.metadata["product_spec_sha256"] == original.product.product_spec_sha256
    assert draft.task.metadata["recovery_of_task_id"] == original.task.id
    assert draft.rebound_request.preparation_sha256 == prepared.preparation_sha256
    assert draft.rebound_request != original.request
    assert (_snapshot(Path(config.platform_root)), _snapshot(project)) == before

    sealing = RecoveryTaskSealingService(store, builder)
    record = sealing.seal(plan.plan_sha256)
    assert record.task == draft.task
    reopened = FileRecoveryStore(sidecar / "recovery-test", scope=scope)
    before = _snapshot(Path(config.platform_root)), _snapshot(project)
    assert reopened.get_task_record(plan.plan_sha256) == record
    assert RecoveryTaskSealingService(reopened, builder).seal(plan.plan_sha256) == record
    assert sealing.require_current(plan.plan_sha256) == record
    assert (_snapshot(Path(config.platform_root)), _snapshot(project)) == before

    for change in (
        {"target_preparation_sha256": "0" * 64},
        {"target_base_revision": run.source_revision},
        {"permissions": original.permissions.model_copy(update={"write_paths": ()})},
        {"target_permissions": original.permissions.model_copy(update={"commands": ()})},
        {"denied_paths": (*original.denied_paths, "hello.txt")},
    ):
        with pytest.raises(RecoveryRejected):
            verifier.validate(RecoveryPlan.create(**{**plan.to_wire(), **change}))
    # Ordinary uncommitted code does not necessarily change RepositoryProfile; Git must catch it.
    (project / "hello.txt").write_text("uncommitted\n")
    with pytest.raises(RecoveryRejected):
        service.require_current_authorization(plan.plan_sha256)
    assert reopened.get_task_record(plan.plan_sha256) == record
    with pytest.raises(RecoveryRejected):
        sealing.require_current(plan.plan_sha256)
    (project / "hello.txt").write_text("hello\n")
    (project / "untracked.txt").write_text("untracked\n")
    with pytest.raises(RecoveryRejected):
        verifier.validate(plan)
    (project / "untracked.txt").unlink()
    # Team context selection/content must be recompiled, not trusted from old baseline.
    knowledge = host.team_workspace.root / "knowledge/current.md"
    knowledge.write_text("new team guidance\n")
    with pytest.raises(RecoveryRejected):
        NativeRecoveryFactsVerifier(
            config.model_copy(update={"team_knowledge_paths": ("current.md",)}), environment
        ).validate(plan)
    profile_file = next((sidecar / "profile").glob(f"*{prepared.repository_profile_sha256}*.json"))
    content = profile_file.read_bytes()
    profile_file.write_text("{}")
    with pytest.raises(RecoveryRejected):
        verifier.validate(plan)
    profile_file.write_bytes(content)
    assert verifier.inspect(plan) == facts
    manager.verify_capture(capture, original.permissions, denied_paths=original.denied_paths)
    assert len(factory.requests) == 1


def test_current_gate_never_initializes_missing_environment(tmp_path: Path) -> None:
    config = ProductionConfig(
        platform_root=str(tmp_path / "missing"),
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
    )
    plan = make_plan(tmp_path / "project")
    with pytest.raises(RecoveryRejected):
        NativeRecoveryFactsVerifier(config, {}).validate(plan)
    assert not Path(config.platform_root).exists()
