"""Real Git/MySQL legacy recovery: full audit, narrowed policy, independent delivery."""

import os
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult, StructuredModelResult
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.manager import production_backend
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    ResumeProjectDelivery,
    StartProjectDelivery,
)
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.orchestration import RetryDeliveryResult
from ai_software_engineer.recovery import RecoveryRejected
from ai_software_engineer.recovery.resume import DeliveryResumeResult
from ai_software_engineer.store import MySqlTaskRepository
from tests.git.test_capture import git
from tests.manager.test_production_backend import _ScriptedClientFactory, _ScriptedStructuredClient
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.recovery.test_execution import OfflineFactory
from tests.recovery.test_native import InterruptedCoder, InterruptedFactory


@pytest.mark.mysql
def test_legacy_rule_edits_are_quarantined_and_requirement_recovers_on_current_base(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    rule = ".trellis/spec/core/contracts.md"
    file = root / rule
    file.parent.mkdir(parents=True)
    file.write_text("Original organization rule.\n")
    (root / "hello.txt").write_text("hello\n")
    existing_audit = "src/knowledge/audit.py"
    intended_audit = "src/learning_collection/audit.py"
    other = root / existing_audit
    other.parent.mkdir(parents=True)
    other.write_text("# unrelated existing module\n")
    git(root, "init", "--initial-branch=main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "add", ".")
    git(root, "commit", "-m", "base")
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
    factory = InterruptedFactory()
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=factory,
    )
    original_complete = _ScriptedStructuredClient.complete
    original_run = InterruptedCoder.run

    def complete(
        self: _ScriptedStructuredClient,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        result = original_complete(
            self,
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            input_images=input_images,
        )
        if "components" in result.payload:
            payload = dict(result.payload)
            payload["components"] = [
                {
                    "key": "greeting",
                    "name": "Greeting",
                    "responsibility": "Store greeting.",
                    "affected_paths": ["hello.txt", rule, intended_audit],
                }
            ]
            result = replace(result, payload=payload)
        return result

    def run(self: InterruptedCoder, request: AgentRequest) -> AgentResult:
        (self.root / rule).write_text("Mistaken historical Coder rule change.\n")
        return original_run(self, request)

    # Produce actual durable old-version grants, then restore current code. This
    # simulates the deployed historical bug without editing SQL or sealed records.
    with monkeypatch.context() as old_version:
        old_version.setattr(production_backend, "delivery_write_paths", lambda paths: paths)
        old_version.setattr(_ScriptedStructuredClient, "complete", complete)
        old_version.setattr(InterruptedCoder, "run", run)
        entry = host.project_entry()
        started = entry.start(
            StartProjectDelivery(repository_root=str(root), requirement="Greeting")
        )
        blocked = entry.approve(
            ApproveProductSpec(
                delivery_id=started.checkpoint.delivery_id,
                expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
                approval_reference="exact-spec",
            )
        )
    cp = blocked.checkpoint
    assert cp.stage.value == "BLOCKED" and cp.task_id is not None
    assert rule in factory.requests[0].permissions.write_paths
    with MySqlTaskRepository(mysql_dsn) as repository:
        history = repository.get(cp.task_id), repository.list_events(cp.task_id)
    (root / "hello.txt").write_text("new base greeting\n")
    git(root, "add", "hello.txt")
    git(root, "commit", "-m", "platform fix")
    recovery = host.recovery_entry()
    plan, path = recovery.propose_delivery(cp)
    assert plan.source.scope.delivery_id == cp.delivery_id
    assert plan.input_mode == "coder_reapply" and plan.quarantined_paths == (rule,)
    assert plan.path_rebindings is None
    assert intended_audit in plan.effective_target_permissions.write_paths
    assert existing_audit not in plan.effective_target_permissions.write_paths
    assert rule not in plan.effective_target_permissions.write_paths
    assert "Mistaken historical Coder rule change." in plan.capture.patch
    old_root = Path(plan.capture.worktree_path)
    old_status = git(old_root, "status", "--porcelain")
    old_patch = plan.capture.patch
    # Previously issued plans are readable but cannot authorize protected reuse.
    from ai_software_engineer.recovery import RecoveryPlan

    legacy = RecoveryPlan.create(
        **{
            **plan.to_wire(),
            "quarantined_paths": None,
            "input_mode": None,
            "target_permissions": plan.permissions,
        }
    )
    legacy.validate_integrity()
    with pytest.raises(RecoveryRejected):
        recovery._facts.inspect(legacy)
    recovery.approve(path, confirmed_plan=plan.plan_sha256, reference="exact-rule-quarantine")
    completed = recovery.execute(path, route_factory=OfflineFactory)
    assert isinstance(completed, RetryDeliveryResult)
    assert completed.task.status.value == "DONE"
    assert completed.task.constraints is not None
    assert rule not in completed.task.constraints.allowed_paths
    assert plan.source.scope.delivery_id == cp.delivery_id
    assert recovery.open_plan(path)[1].capture.patch == old_patch
    assert (old_root / rule).read_text() == "Mistaken historical Coder rule change.\n"
    assert git(old_root, "status", "--porcelain") == old_status
    assert (root / rule).read_text() == "Original organization rule.\n"
    target = Path(completed.task.repository)
    assert target == root
    assert (
        git(root, "show", f"{completed.candidate_revision}:{rule}") == "Original organization rule."
    )
    with MySqlTaskRepository(mysql_dsn) as repository:
        assert (repository.get(cp.task_id), repository.list_events(cp.task_id)) == history
    # Public Continue adopts the verified terminal result, then advances the SAME
    # requirement without another model call or repeated Product approval.
    finished = host.resume_delivery(ResumeProjectDelivery(delivery_id=cp.delivery_id))
    assert isinstance(finished, DeliveryResumeResult)
    assert finished.checkpoint.delivery_id == cp.delivery_id
    assert finished.checkpoint.stage.value == "DONE"
    assert finished.checkpoint.task_id == plan.new_task_id
    assert finished.checkpoint.product_spec_sha256 == cp.product_spec_sha256
    assert finished.checkpoint.approval_sha256 == cp.approval_sha256
    assert len(factory.requests) == 1
