"""A legacy uninvoked CLI claim becomes a new, independently reviewed Responses Task."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.agents import (
    AgentAdapter,
    AgentRequest,
    AgentResult,
    StoredContextResolver,
)
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentDefinition, AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    BaselineInputMode,
    BaselinePurpose,
)
from ai_software_engineer.manager import production_backend, production_host, queued_delivery
from ai_software_engineer.manager.baseline_production import (
    BaselineContinueCommand,
    BaselineExecuteCommand,
    BaselineProposeCommand,
)
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    ResumeProjectDelivery,
    StartProjectDelivery,
)
from ai_software_engineer.manager.delivery_checkpoint import DeliveryFailureCode, DeliveryStage
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.recovery.entry import NativeRecoveryEntry, NativeRecoveryExecution
from ai_software_engineer.recovery.resume import DeliveryResumeOutcome, DeliveryResumeResult
from ai_software_engineer.role_workspace import RoleWorktreeBinding
from ai_software_engineer.scheduling import PortfolioScheduler
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.work_queue.dispatcher import (
    DispatcherLoop,
    DispatcherTickResult,
    DispatcherTickStatus,
)
from tests.manager.test_production_backend import _git, _git_output, _ScriptedDeliveryFactory
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.recovery.execution_fixture import OfflineRecoveryClients
from tests.recovery.test_native import ContinuedCoder, ContinuedFactory
from tests.recovery.test_resume import _SeededCompleteRecoveryFactory


@pytest.mark.mysql
def test_public_route_transition_recovery_keeps_history_and_runs_independent_roles(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n", encoding="utf-8")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    source_revision = _git_output("rev-parse", "HEAD", cwd=repository)
    environment = {"ASE_MYSQL_DSN": mysql_dsn, "PATH": os.environ.get("PATH", "")}
    original_config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        default_project_id="project_test",
        default_project_name="Test Project",
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-5.5", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
        live_model_execution=True,
    )
    monkeypatch.setattr(
        production_backend,
        "ConfiguredStructuredClientFactory",
        lambda *_args, **_kwargs: OfflineRecoveryClients(),
    )
    monkeypatch.setattr(
        queued_delivery,
        "PortfolioScheduler",
        lambda **_kwargs: PortfolioScheduler(lease_duration=timedelta(seconds=1)),
    )
    original_tick = DispatcherLoop.tick
    hold_second = [True]

    def held_tick(
        dispatcher: DispatcherLoop, *, now: datetime, work_item_id: str | None = None
    ) -> DispatcherTickResult:
        if hold_second[0] and work_item_id is not None:
            item = dispatcher._queue.get(work_item_id)
            if item.role is AgentRole.CODER and item.attempt >= 2:
                return DispatcherTickResult(status=DispatcherTickStatus.IDLE, ticked_at=now)
        return original_tick(dispatcher, now=now, work_item_id=work_item_id)

    monkeypatch.setattr(DispatcherLoop, "tick", held_tick)
    original_run = ContinuedCoder.run

    def accepted_first_progress(self: ContinuedCoder, request: AgentRequest) -> AgentResult:
        result = original_run(self, request)
        if request.work_slice is not None and result.artifact is not None:
            work = request.work_slice
            progress = result.artifact
            result = result.model_copy(
                update={
                    "artifact": progress.model_copy(
                        update={
                            "content": progress.content.model_copy(
                                update={
                                    "completed_step_ids": work.completed_step_ids,
                                    "remaining_step_ids": (
                                        *work.selected_step_ids,
                                        *work.later_step_ids,
                                    ),
                                }
                            )
                        }
                    )
                }
            )
        return result

    monkeypatch.setattr(ContinuedCoder, "run", accepted_first_progress)
    old_factory = ContinuedFactory()
    old_host = TeamHost(
        config=original_config,
        environment=environment,
        structured_clients=OfflineRecoveryClients(),
        delivery_route_adapters=old_factory,
    )
    started = old_host.project_entry().start(
        StartProjectDelivery(repository_root=str(repository), requirement="Change greeting.")
    )
    pending = (
        old_host.project_entry()
        .approve(
            ApproveProductSpec(
                delivery_id=started.checkpoint.delivery_id,
                expected_checkpoint_sha256=started.checkpoint.checkpoint_sha256,
                approval_reference="fixture-product-approval",
            )
        )
        .checkpoint
    )
    assert pending.stage is DeliveryStage.DELIVERING
    assert pending.task_id is not None
    assert pending.task_status is TaskStatus.IMPLEMENTING
    assert len(old_factory.requests) == 1
    with MySqlTaskRepository(mysql_dsn) as tasks:
        old_task = tasks.get(pending.task_id)
        old_revision = tasks.current_revision(old_task.id)
    (retry_item,) = tuple(
        item
        for item in old_host.work_queue.items_for_task(old_task.id)
        if item.status is not WorkItemStatus.CLOSED
    )
    assert retry_item.status is WorkItemStatus.READY and retry_item.attempt == 2

    (repository / "tooling.txt").write_text("source update\n", encoding="utf-8")
    _git("add", "tooling.txt", cwd=repository)
    _git("commit", "-m", "source update", cwd=repository)
    target_revision = _git_output("rev-parse", "HEAD", cwd=repository)
    plan = old_host.propose_execution_baseline(
        BaselineProposeCommand(
            delivery_id=pending.delivery_id,
            task_id=old_task.id,
            expected_task_intent_sha256=task_intent_sha256(old_task),
            expected_task_revision=old_revision,
            expected_work_item_id=retry_item.id,
            expected_source_revision=source_revision,
            target_base_ref=target_revision,
            purpose=BaselinePurpose.SOURCE_REBIND,
        ),
        project_id="project_test",
    )
    assert plan.input_mode is BaselineInputMode.PRESERVE_DRAFT and not plan.conflicted
    binding = old_host.execute_execution_baseline(
        BaselineExecuteCommand(
            delivery_id=pending.delivery_id,
            task_id=old_task.id,
            expected_plan_sha256=plan.plan_sha256,
            reference="fixture-preserve-draft",
            continuation_mode=BaselineContinuationMode.PAUSE,
        ),
        project_id="project_test",
    )
    paused = old_host.work_queue.get(retry_item.id)
    assert paused.status is WorkItemStatus.WAITING_HUMAN
    assert paused.wait_disposition is not None
    continuation = BaselineContinueCommand(
        delivery_id=pending.delivery_id,
        task_id=old_task.id,
        expected_task_intent_sha256=task_intent_sha256(old_task),
        expected_task_revision=old_revision,
        expected_work_item_id=paused.id,
        expected_source_revision=binding.execution_source_revision,
        expected_execution_baseline_sha256=binding.binding_sha256,
        expected_disposition_sha256=paused.wait_disposition.disposition_sha256,
        reference="fixture-legacy-route-change",
    )

    responses_config = original_config.model_copy(
        update={
            "model_routes": (
                ProviderRouteConfig(
                    provider="codex",
                    model="gpt-6-sol",
                    kind=ModelProviderKind.RESPONSES,
                    endpoint="https://example.invalid/responses",
                    api_key_env="CODEX_RESPONSES_API_KEY",
                ),
            )
        }
    )
    new_host = TeamHost(
        config=responses_config,
        environment=environment,
        structured_clients=OfflineRecoveryClients(),
        delivery_route_adapters=_ScriptedDeliveryFactory(),
    )
    hold_second[0] = False
    # Seed only the old buggy release in this isolated fixture. The production
    # pre-consumption guard stays enabled before and after this one call.
    with monkeypatch.context() as old_release:
        old_release.setattr(
            production_host, "require_compatible_baseline_routes", lambda *_a, **_k: None
        )
        new_host.continue_execution_baseline(continuation, project_id="project_test")
    blocked = new_host.project_entry().status(pending.delivery_id).checkpoint
    assert blocked.stage is DeliveryStage.BLOCKED
    assert blocked.task_status is TaskStatus.IMPLEMENTING
    assert blocked.task_revision == old_revision
    assert blocked.failure_code is DeliveryFailureCode.PERMISSION_DENIED
    assert len(old_factory.requests) == 1
    claim = new_host.work_queue.claims_for_work_item(retry_item.id)[-1]
    with open_mysql_connection(mysql_dsn) as connection, connection.cursor(DictCursor) as cursor:
        cursor.execute(
            "SELECT expires_at FROM work_queue_claims WHERE lease_id=%s", (claim.lease.id,)
        )
        row = cursor.fetchone()
    assert row is not None
    expires_at = datetime.fromisoformat(str(row["expires_at"]))
    time.sleep(max(0.0, (expires_at - datetime.now(UTC)).total_seconds()) + 0.1)
    now = datetime.now(UTC)
    new_host.work_queue.reclaim_expired(now=now, retry_at=now + timedelta(minutes=1))
    expired = new_host.work_queue.get(retry_item.id)
    assert expired.status is WorkItemStatus.RETRY_SCHEDULED
    assert expired.wait_reason == "lease_expired:" + claim.lease.id

    proposed = new_host.resume_delivery(ResumeProjectDelivery(delivery_id=pending.delivery_id))
    assert isinstance(proposed, DeliveryResumeResult)
    assert proposed.outcome is DeliveryResumeOutcome.RECOVERY_APPROVAL_REQUIRED
    assert proposed.recovery_plan_sha256 is not None
    assert proposed.recovery_plan_file is not None
    _, recovery_plan = new_host.recovery_entry().open_plan(Path(proposed.recovery_plan_file))
    assert recovery_plan.plan_sha256 == proposed.recovery_plan_sha256
    assert recovery_plan.source.route_transition_settlement_sha256 is not None
    assert recovery_plan.source.failed_run_id is None
    assert recovery_plan.source.failed_context_id is None
    assert recovery_plan.source.historical_progress_run_id == old_factory.requests[0].run_id
    assert (
        recovery_plan.source.historical_progress_context_id
        == old_factory.requests[0].context_manifest_id
    )
    assert recovery_plan.target_base_revision == target_revision
    assert recovery_plan.input_mode == "coder_reapply"
    with MySqlTaskRepository(mysql_dsn) as tasks:
        assert tasks.get(old_task.id).status is TaskStatus.BLOCKED
        assert tasks.current_revision(old_task.id) == old_revision + 1
    assert new_host.work_queue.get(retry_item.id).status is WorkItemStatus.CLOSED
    assert len(old_factory.requests) == 1

    observed: list[tuple[AgentRole, str]] = []

    class ResponsesSeededFactory(_SeededCompleteRecoveryFactory):
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
            assert route.kind is ModelProviderKind.RESPONSES
            delegate = super().create(
                route=route,
                definition=definition,
                binding=binding,
                context_resolver=context_resolver,
                config=config,
                environment=environment,
            )

            class ObservedAdapter:
                def run(self, request: AgentRequest) -> AgentResult:
                    observed.append((request.role, request.run_id))
                    return delegate.run(request)

            return ObservedAdapter()

    def execute_offline(self: NativeRecoveryEntry, path: Path) -> NativeRecoveryExecution:
        store, approved_plan = self.open_plan(path)
        delivery = self.execute(path, route_factory=ResponsesSeededFactory)
        return NativeRecoveryExecution(
            approved_plan, self._dispatch_for(store, approved_plan), delivery
        )

    with monkeypatch.context() as offline:
        offline.setattr(NativeRecoveryEntry, "resume_execution", execute_offline)
        completed = new_host.resume_delivery(
            ResumeProjectDelivery(
                delivery_id=pending.delivery_id,
                approved_plan_sha256=proposed.recovery_plan_sha256,
                approval_reference="fixture-independent-engineering-approval",
            )
        )
    assert isinstance(completed, DeliveryResumeResult)
    assert completed.outcome is DeliveryResumeOutcome.RECOVERED
    assert completed.checkpoint.stage is DeliveryStage.DONE
    assert completed.checkpoint.task_id == recovery_plan.new_task_id
    assert [role for role, _ in observed] == [
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]
    assert len({run_id for _, run_id in observed}) == 3
    with MySqlTaskRepository(mysql_dsn) as tasks:
        assert tasks.get(old_task.id).status is TaskStatus.BLOCKED
        assert tasks.get(recovery_plan.new_task_id).status is TaskStatus.DONE
    assert len(old_factory.requests) == 1
