"""Public exhausted start-only UNKNOWN settlement and same-Requirement recovery.

The original native process completes locally, but its outcome and original
capture-stop are never sealed. The old Run remains UNKNOWN throughout recovery.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Never, cast

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.agents import (
    AgentRequest,
    AgentResult,
    StructuredModelResult,
    openai_compatible,
    structured,
)
from ai_software_engineer.agents.codex_cli import (
    CodexCliAgentAdapter,
    CodexInvocationResult,
    SubprocessCodexCommandRunner,
)
from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, model_route_root
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import (
    AgentRole,
    ImplementationReportArtifact,
    QaReportArtifact,
    QaReportStatus,
    ReviewReportArtifact,
    ReviewVerdict,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.artifact import Artifact
from ai_software_engineer.domain.contained_unknown_budget import ContainedUnknownBudgetSettlement
from ai_software_engineer.domain.delivery_resolution import HandleDeliveryWait, InspectDeliveryWait
from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy, StageRetryPolicy
from ai_software_engineer.evaluation import FileEvaluationEventStore, HumanAction, HumanActionEvent
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager import production_backend, production_delivery, production_host
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    ReplyToProduct,
    ResumeProjectDelivery,
)
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.legacy_containment import (
    LocalBootObservation,
    TrustedLocalBootObserver,
)
from ai_software_engineer.manager.legacy_local_execution import (
    LegacyLocalExecutionSurvey,
    TrustedLegacyLocalExecutionObserver,
)
from ai_software_engineer.manager.production_agents import ExecutionPlanDraft, TechnicalDesignDraft
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.multi_directory.models import JointDeliveryResult, JointStage
from ai_software_engineer.multi_directory.scope import DirectoryScope
from ai_software_engineer.multi_directory.service import CreateRequirement
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRecordMissing,
    ContinuationRejected,
    ExecutionCaptureStop,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.orchestration.retry import RetryResult
from ai_software_engineer.owned_processes import OwnedProcessesUncertain
from ai_software_engineer.recovery.entry import NativeRecoveryEntry, NativeRecoveryExecution
from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.recovery.resume import DeliveryResumeOutcome, JointDeliveryResumeResult
from ai_software_engineer.recovery.sealing import RecoveryTaskSealingService
from ai_software_engineer.recovery.seed import RecoverySeedService
from ai_software_engineer.recovery.store import RecoveryRecordMissing
from ai_software_engineer.runtime import _default_case_id
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.manager.test_capacity_preserved_feedback_public import (
    _failed_qa,
    _progress,
)
from tests.manager.test_production_backend import (
    _git,
    _git_output,
    _ScriptedClientFactory,
    _ScriptedStructuredClient,
)
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_production_continuation import Invocation, _coder_draft
from tests.manager.test_public_context_capacity_baseline import public_capacity_host
from tests.manager.test_same_base_capacity_baseline import _independent_report
from tests.recovery.test_execution import OfflineFactory


@pytest.mark.mysql
@pytest.mark.parametrize(
    ("late_artifact", "unsealed_approval"),
    [
        (None, False),
        (None, True),
        ("before", False),
        ("at_fence", False),
        ("late_capture_stop", False),
    ],
    ids=[
        "deliver",
        "approved-but-unsealed-continue",
        "late-raw-artifact",
        "late-artifact-at-SQL-fence",
        "late-original-stop",
    ],
)
def test_public_start_only_unknown_budget_preserves_history_and_recovers_exactly(
    tmp_path: Path,
    mysql_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    late_artifact: Literal["before", "at_fence", "late_capture_stop"] | None,
    unsealed_approval: bool,
) -> None:
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    original_source = _git_output("rev-parse", "HEAD", cwd=repository)
    calls: list[Invocation] = []
    adapters: list[CodexCliAgentAdapter] = []
    original_complete = _ScriptedStructuredClient.complete

    def source_inspection(
        self: _ScriptedStructuredClient,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        title = output_schema.get("title")
        if title == "ManagerCoordinationDraft":
            actions = cast(list[str], input_payload["advertised_actions"])
            action = "PROPOSE_RECOVERY" if "PROPOSE_RECOVERY" in actions else "WAITING_HUMAN"
            return StructuredModelResult(
                payload={
                    "action": action,
                    "summary": "旧执行结果未知, 普通工作预算已耗尽, 原事实与完整草稿保留。",
                    "next_action": "通过精确工程恢复方案继续同一需求。",
                    "responsible_actor": "工程授权者",
                    "resume_condition": "精确恢复方案获批准, 旧执行历史保持 UNKNOWN。",
                },
                duration_ms=0,
            )
        if title in {"JointTechnicalDesign", "JointExecutionPlan"}:
            (unit,) = DirectoryScope.model_validate(input_payload["scope"]).units
            draft = source_inspection(
                self,
                instructions="",
                input_payload={},
                output_schema=(
                    TechnicalDesignDraft.model_json_schema()
                    if title == "JointTechnicalDesign"
                    else ExecutionPlanDraft.model_json_schema()
                ),
                timeout_seconds=timeout_seconds,
            ).payload
            payload = (
                {
                    "product_spec_sha256": input_payload["product_spec_sha256"],
                    "summary": "Inspect the exact candidate greeting.",
                    "blocking_issues": [],
                    "units": [
                        {"unit_id": unit.id, "requirement_ids": ["req_001"], "design": draft}
                    ],
                }
                if title == "JointTechnicalDesign"
                else {
                    "design_sha256": input_payload["design_sha256"],
                    "units": [{"unit_id": unit.id, "plan": draft}],
                    "integration_checks": [],
                }
            )
            return StructuredModelResult(payload=payload, duration_ms=0)
        result = original_complete(
            self,
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            input_images=input_images,
        )
        if title != "TechnicalDesignDraft":
            return result
        payload = dict(result.payload)
        mappings = payload["acceptance_mappings"]
        assert isinstance(mappings, list)
        payload["acceptance_mappings"] = [
            {
                **mapping,
                "test_levels": ["inspection"],
                "verification_inspection": {
                    "kind": "source",
                    "paths": ["hello.txt"],
                    "checklist": ["Read the exact candidate greeting."],
                },
            }
            for mapping in mappings
        ]
        return StructuredModelResult(payload=payload, duration_ms=result.duration_ms)

    def forbid_live_provider(*args: object, **kwargs: object) -> Never:
        pytest.fail("offline public recovery fixture reached a real provider boundary")

    monkeypatch.setattr(structured.CodexCliStructuredModelClient, "complete", forbid_live_provider)
    monkeypatch.setattr(structured.ResponsesStructuredModelClient, "complete", forbid_live_provider)
    monkeypatch.setattr(openai_compatible, "urlopen", forbid_live_provider)
    monkeypatch.setattr(_ScriptedStructuredClient, "complete", source_inspection)
    monkeypatch.setattr(
        production_backend,
        "ConfiguredStructuredClientFactory",
        lambda *_, **__: _ScriptedClientFactory(),
    )

    monkeypatch.setattr(
        production_host,
        "ConfiguredStructuredClientFactory",
        lambda *_, **__: _ScriptedClientFactory(),
    )

    observed_stops: list[CodexInvocationResult] = []

    class LostCompletionRunner(SubprocessCodexCommandRunner):
        def run_observed(
            self,
            argv: tuple[str, ...],
            *,
            cwd: Path,
            environment: Mapping[str, str],
            stdin: str,
            timeout_seconds: float,
            observer: Callable[[CodexInvocationResult], None],
        ) -> CodexInvocationResult:
            output_path = argv[argv.index("--output-last-message") + 1]
            result = super().run_observed(
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import sys; sys.stdin.read(); "
                    "Path('hello.txt').write_text('partially implemented\\n'); "
                    "Path(sys.argv[1]).write_text('{}'); print('unparseable native event')",
                    output_path,
                ),
                cwd=cwd,
                environment=environment,
                stdin=stdin,
                timeout_seconds=min(timeout_seconds, 10),
                # The real subprocess stops, but the original durable stop
                # callback is lost before it can publish capture-stop.
                observer=lambda _: None,
            )
            assert result.process_stop is not None and result.returncode == 0
            assert result.process_stop.kind == "completed"
            assert Path(output_path).is_file()
            observed_stops.append(result)
            raise OwnedProcessesUncertain("fixture lost original stop and outcome publication")

    class ObservedCodex(CodexCliAgentAdapter):
        def run(self, request: AgentRequest) -> AgentResult:
            guard = cast(WorkerExecutionGuard, self._execution_guard)
            assert guard.lease is not None
            calls.append(
                Invocation(
                    request,
                    guard.lease.claim,
                    self._workspace_root,
                    _git_output("branch", "--show-current", cwd=self._workspace_root),
                    _git_output("rev-parse", "HEAD", cwd=self._workspace_root),
                    self._model,
                )
            )
            adapters.append(self)
            assert len(calls) == 1, "unapproved old UNKNOWN execution must never be replayed"
            self._runner = LostCompletionRunner(guard)
            return super().run(request)

    monkeypatch.setattr(production_delivery, "CodexCliAgentAdapter", ObservedCodex)
    host = TeamHost(
        config=ProductionConfig(
            platform_root=str(tmp_path / "platform"),
            default_project_id="project_test",
            default_project_name="Test Project",
            live_model_execution=True,
            model_routes=(
                ProviderRouteConfig(
                    provider="codex", model="fixture", kind=ModelProviderKind.CODEX_CLI
                ),
            ),
            execution_retry_policy=ExecutionRetryPolicy(coder=StageRetryPolicy(max_attempts=1)),
        ),
        environment={
            "ASE_MYSQL_DSN": mysql_dsn,
            "PATH": os.environ.get("PATH", os.defpath),
            "GIT_AUTHOR_NAME": "ASE Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "ASE Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        },
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=production_delivery.ConfiguredDeliveryRouteAdapterFactory(),
    )
    service = host.requirement_entry()
    created = service.create(
        CreateRequirement(name="Unknown exhausted delivery", repository_roots=(str(repository),))
    ).checkpoint
    product = service.reply(
        ReplyToProduct(
            delivery_id=created.delivery_id,
            expected_checkpoint_sha256=created.checkpoint_sha256,
            message="Update the greeting.",
        )
    ).checkpoint
    approved = service.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="exact-original-product-approval",
        )
    )
    assert isinstance(approved, JointDeliveryResult)
    (child,) = approved.checkpoint.children
    pending = child.checkpoint
    assert pending.task_id is not None and pending.repository_id is not None
    assert len(calls) == 1
    stopped = calls[0]
    (item,) = tuple(
        value
        for value in host.work_queue.items_for_task(pending.task_id)
        if value.status is not WorkItemStatus.CLOSED
    )
    assert item.status is WorkItemStatus.WAITING_DEPENDENCY
    assert item.wait_disposition is not None
    disposition = item.wait_disposition
    assert disposition.facts.classification == "EXECUTION_UNCERTAIN"
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        original = tasks.get(pending.task_id)
        events = tasks.list_events(original.id)
    assert original.status is TaskStatus.IMPLEMENTING
    assert original.work_budget_exhausted and original.work_attempt == original.attempts == 1
    assert original.retry_failures is None
    sidecar = host.projects()[0].root / "repositories" / pending.repository_id
    invocation_records = KnowledgeRecordStore(sidecar / "state/invocations", read_only=True)
    assert (
        invocation_records.find("invocation-outcomes", item.id, DeliveryInvocationOutcome) is None
    )
    ledger = FileContinuationStore(
        sidecar / "state/continuations" / original.id, task_id=original.id
    )
    with pytest.raises(ContinuationRecordMissing):
        ledger.capture_stop(stopped.request.run_id)
    assert len(observed_stops) == 1
    assert observed_stops[0].process_stop is not None
    assert observed_stops[0].process_stop.kind == "completed"
    assert observed_stops[0].process_stop.returncode == 0
    assert not ledger.receipts_for_task(original.id)
    routes = FileModelRouteAttemptStore(model_route_root(sidecar))
    assert not routes.list_for_run(stopped.request.run_id)
    original_records = {
        path: path.read_bytes()
        for directory in (sidecar / "state/invocations", sidecar / "state/continuations")
        for path in directory.rglob("*.json")
    }
    claims = host.work_queue.claims_for_work_item(item.id)
    command = HandleDeliveryWait(
        work_item_id=item.id,
        expected_disposition_sha256=disposition.disposition_sha256,
        expected_task_intent_sha256=disposition.facts.task_intent_sha256,
        expected_source_revision=disposition.facts.source_revision,
        expected_checkpoint_sequence=disposition.facts.checkpoint_sequence,
        confirm_local_execution_stopped=True,
        local_stop_reference="call_public_start_only_stop_confirmation",
    )
    boot = LocalBootObservation(
        machine_sha256="a" * 64,
        boot_session_sha256="b" * 64,
        booted_at=datetime.now(UTC) - timedelta(days=1),
    )
    monkeypatch.setattr(TrustedLocalBootObserver, "observe", lambda _self: boot)

    def idle_survey(
        _self: TrustedLegacyLocalExecutionObserver,
        *,
        worktree_root: Path,
        boot: LocalBootObservation,
    ) -> LegacyLocalExecutionSurvey:
        return LegacyLocalExecutionSurvey.create(
            worktree_path=str(worktree_root.resolve()),
            machine_sha256=boot.machine_sha256,
            boot_session_sha256=boot.boot_session_sha256,
            account_sha256="c" * 64,
            observed_at=datetime.now(UTC),
            scanner_version="local-execution-v1",
            blockers=(),
        )

    monkeypatch.setattr(TrustedLegacyLocalExecutionObserver, "observe", idle_survey)
    proof = host.inspect_delivery_wait(
        InspectDeliveryWait.model_validate(
            command.model_dump(mode="python", include=set(InspectDeliveryWait.model_fields))
        ),
        project_id="project_test",
        delivery_id=created.delivery_id,
    )
    assert proof.local_stop_confirmation_available
    assert proof.original_run_id == stopped.request.run_id
    without_confirmation = command.model_copy(
        update={"confirm_local_execution_stopped": None, "local_stop_reference": None}
    )
    waiting = host.handle_delivery_wait(
        without_confirmation, project_id="project_test", delivery_id=created.delivery_id
    )
    assert waiting.budget_settlement_sha256 is None
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        assert tasks.get(original.id) == original
        assert tasks.list_events(original.id) == events
    assert host.work_queue.get(item.id) == item
    if late_artifact == "late_capture_stop":
        process_stop = observed_stops[0].process_stop
        assert process_stop is not None
        ledger.put_capture_stop(
            ExecutionCaptureStop.create(
                task_id=original.id,
                run_id=stopped.request.run_id,
                capture_start_sha256=ledger.capture_start(stopped.request.run_id).start_sha256,
                process_stop=process_stop,
                output_present=True,
                cause=None,
                original_error_code=None,
            )
        )
        try:
            late_handling = host.handle_delivery_wait(
                command, project_id="project_test", delivery_id=created.delivery_id
            )
        except (ContinuationRejected, ValueError, RuntimeError):
            pass
        else:
            assert late_handling.budget_settlement_sha256 is None
        with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
            assert tasks.get(original.id) == original
            assert tasks.list_events(original.id) == events
        assert host.work_queue.get(item.id) == item
        assert not KnowledgeRecordStore(sidecar / "state/delivery-preflight").list(
            "contained-unknown-budget-settlements", ContainedUnknownBudgetSettlement
        )
        return
    if late_artifact is not None:
        # A raw artifact is never an accepted outcome. Both the initial source
        # observation and the last callback under the real SQL fence must refuse.
        original_items = host.work_queue.items_for_task(original.id)
        injected_ids: list[str] = []
        final_rejections: list[str] = []

        def inject_raw_artifact() -> None:
            assert not injected_ids
            artifact = seal_artifact(
                _coder_draft(adapters[0], stopped.request), validated_at=datetime.now(UTC)
            )
            FileArtifactStore(sidecar / "artifacts").put(artifact)
            injected_ids.append(artifact.artifact_id)

        if late_artifact == "before":
            inject_raw_artifact()
        else:
            original_settle = MySqlRoleQueue.settle_stopped_budget

            def inject_at_fence(
                queue: MySqlRoleQueue,
                cursor: DictCursor,
                settlement: ContainedUnknownBudgetSettlement,
                *,
                validate_current: Callable[[], None] | None = None,
            ) -> None:
                assert isinstance(settlement, ContainedUnknownBudgetSettlement)
                assert validate_current is not None
                inject_raw_artifact()

                def validate_after_late_fact() -> None:
                    try:
                        validate_current()
                    except (ValueError, RuntimeError) as error:
                        final_rejections.append(type(error).__name__)
                        raise

                original_settle(
                    queue, cursor, settlement, validate_current=validate_after_late_fact
                )

            monkeypatch.setattr(MySqlRoleQueue, "settle_stopped_budget", inject_at_fence)
        try:
            handling = host.handle_delivery_wait(
                command, project_id="project_test", delivery_id=created.delivery_id
            )
        except (ValueError, RuntimeError):
            pass
        else:
            assert handling.budget_settlement_sha256 is None
        assert len(injected_ids) == 1
        if late_artifact == "at_fence":
            assert final_rejections, "the real last SQL callback must reject the new raw fact"
        with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
            assert tasks.get(original.id) == original
            assert tasks.list_events(original.id) == events
        assert host.work_queue.items_for_task(original.id) == original_items
        assert host.work_queue.get(item.id) == item
        assert host.work_queue.claims_for_work_item(item.id) == claims
        assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
        assert len(calls) == 1
        assert (
            invocation_records.find("invocation-outcomes", item.id, DeliveryInvocationOutcome)
            is None
        )
        assert not routes.list_for_run(stopped.request.run_id)
        assert all(path.read_bytes() == body for path, body in original_records.items())
        assert (stopped.workspace / "hello.txt").read_text() == "partially implemented\n"
        raw = FileArtifactStore(sidecar / "artifacts", read_only=True).get(injected_ids[0])
        assert raw.producer.run_id == stopped.request.run_id
        return

    handling = host.handle_delivery_wait(
        command, project_id="project_test", delivery_id=created.delivery_id
    )
    assert handling.status == "BUDGET_EXHAUSTED"
    assert handling.budget_settlement_sha256 is not None
    assert host.work_queue.get(item.id).status is WorkItemStatus.CLOSED
    assert host.work_queue.claims_for_work_item(item.id) == claims
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        settled = tasks.get(original.id)
        settled_events = tasks.list_events(original.id)
    assert settled.status is TaskStatus.BLOCKED
    assert (
        settled.attempts == original.attempts and settled.retry_failures == original.retry_failures
    )
    assert settled.retry_policy == original.retry_policy
    assert settled_events[:-1] == events and len(settled_events) == len(events) + 1
    assert "UNKNOWN" in settled_events[-1].reason
    audit_events = FileEvaluationEventStore(sidecar / "evaluations").list_for_case(
        _default_case_id(original.id)
    )
    actions = tuple(
        event
        for event in audit_events
        if isinstance(event, HumanActionEvent)
        and event.action is HumanAction.SUPPLY_EVIDENCE
        and "call_public_start_only_stop_confirmation" in (event.note or "")
    )
    assert len(actions) == 1
    replay = host.handle_delivery_wait(
        command, project_id="project_test", delivery_id=created.delivery_id
    )
    assert replay == handling
    assert (
        FileEvaluationEventStore(sidecar / "evaluations").list_for_case(
            _default_case_id(original.id)
        )
        == audit_events
    )
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        assert tasks.get(original.id) == settled
        assert tasks.list_events(original.id) == settled_events
    current = service.status(created.delivery_id).checkpoint
    assert current.stage is JointStage.DELIVERING
    assert current.children[0].checkpoint.task_id == original.id
    assert current.children[0].checkpoint.task_status is TaskStatus.IMPLEMENTING
    assert (
        invocation_records.find("invocation-outcomes", item.id, DeliveryInvocationOutcome) is None
    )
    assert all(path.read_bytes() == body for path, body in original_records.items())
    assert (stopped.workspace / "hello.txt").read_text() == "partially implemented\n"
    # Advance the target main independently. The preserved draft conflicts with
    # this greeting, so only the newly approved Coder may perform reapplication.
    (repository / "hello.txt").write_text("new base greeting\n")
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "independent latest main", cwd=repository)
    latest_main = _git_output("rev-parse", "HEAD", cwd=repository)
    assert latest_main != original_source
    synchronized = host.resume_delivery(
        ResumeProjectDelivery(delivery_id=created.delivery_id), project_id="project_test"
    )
    assert isinstance(synchronized, JointDeliveryResult)
    assert not isinstance(synchronized, JointDeliveryResumeResult)
    assert synchronized.checkpoint.stage is JointStage.BLOCKED
    assert synchronized.checkpoint.children[0].checkpoint.task_status is TaskStatus.BLOCKED
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        assert tasks.get(original.id) == settled
        assert tasks.list_events(original.id) == settled_events
    proposed = host.resume_delivery(
        ResumeProjectDelivery(delivery_id=created.delivery_id), project_id="project_test"
    )
    assert isinstance(proposed, JointDeliveryResumeResult)
    assert proposed.continuation.outcome is DeliveryResumeOutcome.RECOVERY_APPROVAL_REQUIRED, (
        proposed.continuation.next_action,
        proposed.continuation.diagnostic,
    )
    assert proposed.continuation.recovery_plan_file is not None
    recovery = host.recovery_entry()
    path = Path(proposed.continuation.recovery_plan_file)
    _, plan = recovery.open_plan(path)
    assert plan.source.task_id == original.id
    assert plan.source.contained_unknown_settlement_sha256 == handling.budget_settlement_sha256
    assert plan.source.parent_delivery_id == created.delivery_id
    assert plan.target_base_revision == latest_main and plan.input_mode == "coder_reapply"
    assert "+partially implemented\n" in plan.capture.patch
    assert plan.capture.branch_name == original.branch_name
    with pytest.raises(RecoveryRejected):
        recovery.execute(path)
    assert len(calls) == 1
    factories: list[OfflineFactory] = []

    def factory(seed: RecoverySeedService) -> OfflineFactory:
        result = OfflineFactory(seed)
        factories.append(result)
        return result

    resume_native = NativeRecoveryEntry.resume_execution

    def resume_offline(entry: NativeRecoveryEntry, plan_path: Path) -> NativeRecoveryExecution:
        execute_native = entry.execute

        def execute_with_offline_factory(path: Path) -> RetryResult:
            return execute_native(path, route_factory=factory)

        with monkeypatch.context() as offline:
            offline.setattr(entry, "execute", execute_with_offline_factory)
            return resume_native(entry, plan_path)

    if unsealed_approval:
        # The first public approval can persist its exact human decision and then
        # lose the sealing step. A later ordinary Continue must finish that same
        # approval before any new Task, seed, invocation or provider call exists.
        store, _ = recovery.open_plan(path)
        reference = "exact latest-main recovery; original UNKNOWN retained"

        def fail_after_authorization(
            _service: RecoveryTaskSealingService, _plan_sha256: str
        ) -> None:
            raise RecoveryRejected("simulated post-authorization interruption")

        with monkeypatch.context() as interrupted:
            interrupted.setattr(RecoveryTaskSealingService, "seal", fail_after_authorization)
            with pytest.raises(RecoveryRejected, match="simulated post-authorization interruption"):
                recovery.approve(path, confirmed_plan=plan.plan_sha256, reference=reference)
        authorization = store.get_authorization(plan.plan_sha256)
        assert authorization.decision.approved
        with pytest.raises(RecoveryRecordMissing):
            store.get_task_record(plan.plan_sha256)
        with pytest.raises(RecoveryRecordMissing):
            store.get_seed(plan.plan_sha256)
        with pytest.raises(RecoveryRecordMissing):
            store.get_invocation(plan.plan_sha256)
        assert len(calls) == 1
        with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
            assert tasks.get(original.id) == settled
            assert tasks.list_events(original.id) == settled_events

    monkeypatch.setattr(NativeRecoveryEntry, "resume_execution", resume_offline)
    delivered = host.resume_delivery(
        ResumeProjectDelivery(
            delivery_id=created.delivery_id,
            approved_plan_sha256=None if unsealed_approval else plan.plan_sha256,
            approval_reference=(
                None
                if unsealed_approval
                else "exact latest-main recovery; original UNKNOWN retained"
            ),
        ),
        project_id="project_test",
    )
    assert isinstance(delivered, JointDeliveryResult), delivered
    if unsealed_approval:
        assert store.get_authorization(plan.plan_sha256) == authorization
        assert store.get_task_record(plan.plan_sha256).task.id == plan.new_task_id
    assert delivered.checkpoint.delivery_id == created.delivery_id
    assert delivered.checkpoint.stage is JointStage.DONE, delivered.checkpoint
    (finished,) = delivered.checkpoint.children
    assert finished.checkpoint.stage is DeliveryStage.DONE
    assert finished.checkpoint.task_id is not None and finished.checkpoint.task_id != original.id
    assert finished.checkpoint.candidate_revision is not None
    assert len(factories) == 1
    recovery_calls = factories[0].calls
    assert [request.role for request in recovery_calls] == [
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]
    assert recovery_calls[0].source_revision == latest_main
    candidate = finished.checkpoint.candidate_revision
    assert recovery_calls[1].source_revision == recovery_calls[2].source_revision == candidate
    assert len({request.run_id for request in recovery_calls}) == 3
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        assert tasks.get(original.id) == settled
        assert tasks.list_events(original.id) == settled_events
        successor = tasks.get(finished.checkpoint.task_id)
    assert successor.status is TaskStatus.DONE
    assert successor.attempts == successor.work_attempt == 1
    assert original.id != successor.id
    artifacts = FileArtifactStore(sidecar / "artifacts", read_only=True).list_for_task(successor.id)
    implementation = next(a for a in artifacts if isinstance(a, ImplementationReportArtifact))
    qa = next(a for a in artifacts if isinstance(a, QaReportArtifact))
    review = next(a for a in artifacts if isinstance(a, ReviewReportArtifact))
    assert (
        implementation.source_revision == qa.source_revision == review.source_revision == candidate
    )
    assert qa.content.status is QaReportStatus.PASS
    assert review.content.verdict is ReviewVerdict.APPROVE
    assert len({a.producer.agent_id for a in (implementation, qa, review)}) == 3
    assert not routes.list_for_run(stopped.request.run_id)
    assert host.work_queue.claims_for_work_item(item.id) == claims
    assert (
        invocation_records.find("invocation-outcomes", item.id, DeliveryInvocationOutcome) is None
    )
    assert all(path.read_bytes() == body for path, body in original_records.items())
    assert _git_output("rev-parse", "HEAD", cwd=repository) == latest_main
    assert (repository / "hello.txt").read_text() == "new base greeting\n"
    assert (stopped.workspace / "hello.txt").read_text() == "partially implemented\n"


@pytest.mark.mysql
def test_public_contained_unknown_after_qa_feedback_keeps_historical_candidate(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An older QA candidate is not a substitute for the final UNKNOWN Coder work."""
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    prepared: list[AgentRequest] = []
    invoked: list[AgentRequest] = []
    prototype = public_capacity_host(
        tmp_path=tmp_path,
        repository=repository,
        mysql_dsn=mysql_dsn,
        monkeypatch=monkeypatch,
        preparation_requests=prepared,
        invoked=invoked,
        should_reject=lambda _: False,
    )
    original_complete = _ScriptedStructuredClient.complete

    def joint_complete(
        self: _ScriptedStructuredClient,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        title = output_schema.get("title")
        if title == "ManagerCoordinationDraft":
            actions = cast(list[str], input_payload["advertised_actions"])
            return StructuredModelResult(
                payload={
                    "action": "PROPOSE_RECOVERY"
                    if "PROPOSE_RECOVERY" in actions
                    else "WAITING_HUMAN",
                    "summary": "Final UNKNOWN Coder work retained after independent QA feedback.",
                    "next_action": "Approve an exact Coder reapply plan for the same Requirement.",
                    "responsible_actor": "Engineering approver",
                    "resume_condition": "A current exact recovery plan is approved.",
                },
                duration_ms=0,
            )
        if title in {"JointTechnicalDesign", "JointExecutionPlan"}:
            (unit,) = DirectoryScope.model_validate(input_payload["scope"]).units
            draft = original_complete(
                self,
                instructions="",
                input_payload={},
                output_schema=(
                    TechnicalDesignDraft.model_json_schema()
                    if title == "JointTechnicalDesign"
                    else ExecutionPlanDraft.model_json_schema()
                ),
                timeout_seconds=timeout_seconds,
            ).payload
            payload = (
                {
                    "product_spec_sha256": input_payload["product_spec_sha256"],
                    "summary": "Inspect the exact candidate greeting.",
                    "blocking_issues": [],
                    "units": [
                        {"unit_id": unit.id, "requirement_ids": ["req_001"], "design": draft}
                    ],
                }
                if title == "JointTechnicalDesign"
                else {
                    "design_sha256": input_payload["design_sha256"],
                    "units": [{"unit_id": unit.id, "plan": draft}],
                    "integration_checks": [],
                }
            )
            return StructuredModelResult(payload=payload, duration_ms=0)
        return original_complete(
            self,
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            input_images=input_images,
        )

    monkeypatch.setattr(_ScriptedStructuredClient, "complete", joint_complete)
    host = TeamHost(
        config=prototype._config.model_copy(
            update={
                "execution_retry_policy": ExecutionRetryPolicy(
                    coder=StageRetryPolicy(max_attempts=3)
                )
            }
        ),
        environment=prototype._environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=production_delivery.ConfiguredDeliveryRouteAdapterFactory(),
    )
    calls: list[Invocation] = []

    class ReportRunner:
        def __init__(self, adapter: CodexCliAgentAdapter, request: AgentRequest) -> None:
            self.adapter, self.request = adapter, request

        def run(
            self,
            argv: tuple[str, ...],
            *,
            cwd: Path,
            environment: Mapping[str, str],
            stdin: str,
            timeout_seconds: float,
        ) -> CodexInvocationResult:
            del environment, stdin, timeout_seconds
            adapter, request = self.adapter, self.request
            guard = cast(WorkerExecutionGuard, adapter._execution_guard)
            assert guard.lease is not None
            calls.append(
                Invocation(
                    request,
                    guard.lease.claim,
                    cwd,
                    _git_output("branch", "--show-current", cwd=cwd),
                    _git_output("rev-parse", "HEAD", cwd=cwd),
                    adapter._model,
                )
            )
            assert calls[-1].input_head == request.source_revision
            artifact: Artifact
            if request.role is AgentRole.CODER:
                (cwd / "hello.txt").write_text(
                    "hello from the team" if request.attempt <= 2 else "post-QA draft\n"
                )
                artifact = (
                    _progress(adapter, request)
                    if request.attempt == 1
                    else _coder_draft(adapter, request)
                )
                artifact = artifact.model_copy(
                    update={
                        "supersedes": (request.expected_supersedes_by_kind or {}).get(artifact.kind)
                    }
                )
            elif request.role is AgentRole.QA:
                artifact = _failed_qa(adapter, request, cwd, tmp_path)
            else:
                artifact = _independent_report(adapter, request, cwd, tmp_path)
            Path(argv[argv.index("--output-last-message") + 1]).write_text(
                artifact.model_dump_json()
            )
            return CodexInvocationResult(returncode=0)

    class LostFinalStop(SubprocessCodexCommandRunner):
        def run_observed(
            self,
            argv: tuple[str, ...],
            *,
            cwd: Path,
            environment: Mapping[str, str],
            stdin: str,
            timeout_seconds: float,
            observer: Callable[[CodexInvocationResult], None],
        ) -> CodexInvocationResult:
            output_path = argv[argv.index("--output-last-message") + 1]
            result = super().run_observed(
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import sys; sys.stdin.read(); "
                    "Path('hello.txt').write_text('last UNKNOWN draft\\n'); "
                    "Path(sys.argv[1]).write_text('{}')",
                    output_path,
                ),
                cwd=cwd,
                environment=environment,
                stdin=stdin,
                timeout_seconds=min(timeout_seconds, 10),
                observer=lambda _: None,
            )
            assert result.process_stop is not None and result.returncode == 0
            raise OwnedProcessesUncertain("fixture lost final Coder stop")

    class PostFeedbackUnknown(CodexCliAgentAdapter):
        def run(self, request: AgentRequest) -> AgentResult:
            invoked.append(request)
            guard = cast(WorkerExecutionGuard, self._execution_guard)
            if request.role is AgentRole.CODER and request.attempt == 3:
                assert guard.lease is not None
                calls.append(
                    Invocation(
                        request,
                        guard.lease.claim,
                        self._workspace_root,
                        _git_output("branch", "--show-current", cwd=self._workspace_root),
                        _git_output("rev-parse", "HEAD", cwd=self._workspace_root),
                        self._model,
                    )
                )
                self._runner = LostFinalStop(guard)
            else:
                self._runner = ReportRunner(self, request)
            return super().run(request)

    monkeypatch.setattr(production_delivery, "CodexCliAgentAdapter", PostFeedbackUnknown)
    service = host.requirement_entry()
    created = service.create(
        CreateRequirement(name="Post-feedback UNKNOWN", repository_roots=(str(repository),))
    ).checkpoint
    product = service.reply(
        ReplyToProduct(
            delivery_id=created.delivery_id,
            expected_checkpoint_sha256=created.checkpoint_sha256,
            message="Keep the required final newline.",
        )
    ).checkpoint
    service.approve(
        ApproveProductSpec(
            delivery_id=created.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="approved-post-feedback-unknown-product",
        )
    )
    assert [(request.role, request.attempt) for request in invoked] == [
        (AgentRole.CODER, 1),
        (AgentRole.CODER, 2),
        (AgentRole.QA, 2),
        (AgentRole.CODER, 3),
    ]
    (child,) = service.status(created.delivery_id).checkpoint.children
    assert child.checkpoint.task_id is not None
    assert child.checkpoint.candidate_revision is not None
    (item,) = tuple(
        value
        for value in host.work_queue.items_for_task(child.checkpoint.task_id)
        if value.status is not WorkItemStatus.CLOSED
    )
    assert item.wait_disposition is not None
    disposition = item.wait_disposition
    sidecar = host.projects()[0].root / "repositories" / child.checkpoint.repository_id
    reports = FileArtifactStore(sidecar / "artifacts", read_only=True)
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        original = tasks.get(child.checkpoint.task_id)
        before_events = tasks.list_events(original.id)
    (feedback,) = tuple(
        event for event in before_events if event.reason == "qa_failed_route_to_coder"
    )
    assert len(feedback.artifact_ids) == 1
    report = reports.get(feedback.artifact_ids[0])
    assert isinstance(report, QaReportArtifact) and report.content.status is QaReportStatus.FAIL
    (candidate_event,) = tuple(
        event for event in before_events if event.reason == "candidate_ready"
    )
    assert report.parent_artifact_ids == candidate_event.artifact_ids
    boot = LocalBootObservation(
        machine_sha256="a" * 64,
        boot_session_sha256="b" * 64,
        booted_at=datetime.now(UTC) - timedelta(days=1),
    )
    monkeypatch.setattr(TrustedLocalBootObserver, "observe", lambda _self: boot)
    monkeypatch.setattr(
        TrustedLegacyLocalExecutionObserver,
        "observe",
        lambda _self, *, worktree_root, boot: LegacyLocalExecutionSurvey.create(
            worktree_path=str(worktree_root.resolve()),
            machine_sha256=boot.machine_sha256,
            boot_session_sha256=boot.boot_session_sha256,
            account_sha256="c" * 64,
            observed_at=datetime.now(UTC),
            scanner_version="local-execution-v1",
            blockers=(),
        ),
    )
    command = HandleDeliveryWait(
        work_item_id=item.id,
        expected_disposition_sha256=disposition.disposition_sha256,
        expected_task_intent_sha256=disposition.facts.task_intent_sha256,
        expected_source_revision=disposition.facts.source_revision,
        expected_checkpoint_sequence=disposition.facts.checkpoint_sequence,
        confirm_local_execution_stopped=True,
        local_stop_reference="call_post_feedback_unknown_stop_confirmation",
    )
    proof = host.inspect_delivery_wait(
        InspectDeliveryWait.model_validate(
            command.model_dump(mode="python", include=set(InspectDeliveryWait.model_fields))
        ),
        project_id="project_test",
        delivery_id=created.delivery_id,
    )
    assert proof.local_stop_confirmation_available
    handled = host.handle_delivery_wait(
        command, project_id="project_test", delivery_id=created.delivery_id
    )
    assert handled.status == "BUDGET_EXHAUSTED"
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        settled = tasks.get(original.id)
        settled_events = tasks.list_events(original.id)
    assert settled.status is TaskStatus.BLOCKED
    assert settled_events[:-1] == before_events
    synchronized = host.resume_delivery(
        ResumeProjectDelivery(delivery_id=created.delivery_id), project_id="project_test"
    )
    assert isinstance(synchronized, JointDeliveryResult)
    assert synchronized.checkpoint.stage is JointStage.BLOCKED
    proposed = host.resume_delivery(
        ResumeProjectDelivery(delivery_id=created.delivery_id), project_id="project_test"
    )
    assert isinstance(proposed, JointDeliveryResumeResult)
    assert proposed.continuation.outcome is DeliveryResumeOutcome.RECOVERY_APPROVAL_REQUIRED, (
        proposed.continuation.next_action,
        proposed.continuation.diagnostic,
    )
    assert proposed.continuation.recovery_plan_file is not None
    _, plan = host.recovery_entry().open_plan(Path(proposed.continuation.recovery_plan_file))
    assert plan.source.task_id == original.id
    assert plan.source.contained_unknown_settlement_sha256 == handled.budget_settlement_sha256
    assert plan.source.parent_delivery_id == created.delivery_id
    assert plan.input_mode == "coder_reapply"
    assert "+last UNKNOWN draft" in plan.capture.patch
    assert plan.capture.branch_name == original.branch_name
    assert len(invoked) == 4 and host.work_queue.get(item.id).status is WorkItemStatus.CLOSED
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        assert tasks.get(original.id) == settled
        assert tasks.list_events(original.id) == settled_events
