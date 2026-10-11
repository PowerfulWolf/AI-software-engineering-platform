"""Public HANDLE closes a legacy exhausted wait before exact recovery approval."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentRequest,
    AgentResult,
    StructuredModelResult,
)
from ai_software_engineer.agents.codex_cli import (
    CodexCliAgentAdapter,
    CodexInvocationResult,
    SubprocessCodexCommandRunner,
)
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.delivery_resolution import HandleDeliveryWait
from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy, StageRetryPolicy
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager import production_backend, production_delivery
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    ReplyToProduct,
    ResumeProjectDelivery,
)
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.production_agents import ExecutionPlanDraft, TechnicalDesignDraft
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.multi_directory.models import JointDeliveryResult, JointStage
from ai_software_engineer.multi_directory.scope import DirectoryScope
from ai_software_engineer.multi_directory.service import CreateRequirement
from ai_software_engineer.orchestration import RetryClassification, retry
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.runner import AgentRunFailed
from ai_software_engineer.recovery.resume import DeliveryResumeOutcome, JointDeliveryResumeResult
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.manager.test_production_backend import (
    _git,
    _git_output,
    _ScriptedClientFactory,
    _ScriptedStructuredClient,
)
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_production_continuation import Invocation


@pytest.mark.mysql
def test_public_handle_settles_legacy_wait_and_requires_exact_recovery_approval(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    original_source = _git_output("rev-parse", "HEAD", cwd=repository)
    calls: list[Invocation] = []
    results: list[AgentResult] = []
    coordination_actions: list[str] = []
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
            assert "PROPOSE_RECOVERY" in cast(tuple[str, ...], input_payload["advertised_actions"])
            coordination_actions.append("PROPOSE_RECOVERY")
            return StructuredModelResult(
                payload={
                    "action": "PROPOSE_RECOVERY",
                    "summary": "原开发执行已停止且普通额度耗尽, 保留原需求与现场。",
                    "next_action": "准备精确恢复方案, 交工程授权者确认后继续原需求。",
                    "responsible_actor": "工程授权者",
                    "resume_condition": "精确恢复方案获批准, 不能自动增加旧任务额度。",
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
            return StructuredModelResult(
                payload={
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
                },
                duration_ms=0,
            )
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

    monkeypatch.setattr(_ScriptedStructuredClient, "complete", source_inspection)
    monkeypatch.setattr(
        production_backend, "ConfiguredStructuredClientFactory", lambda *_: _ScriptedClientFactory()
    )

    class Runner:
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
            del argv
            guard = cast(WorkerExecutionGuard, self.adapter._execution_guard)
            guard.check()
            assert guard.lease is not None
            request = self.request
            assert request.role is AgentRole.CODER
            calls.append(
                Invocation(
                    request,
                    guard.lease.claim,
                    cwd,
                    _git_output("branch", "--show-current", cwd=cwd),
                    _git_output("rev-parse", "HEAD", cwd=cwd),
                    self.adapter._model,
                )
            )
            assert len(calls) == 1, "handling and proposing recovery must not call another model"
            outcome = SubprocessCodexCommandRunner(guard).run(
                (
                    sys.executable,
                    "-c",
                    "import sys; sys.stdin.read(); "
                    "sys.stderr.write('Error: HTTP 401 Unauthorized\\n'); raise SystemExit(1)",
                ),
                cwd=cwd,
                environment=environment,
                stdin=stdin,
                timeout_seconds=min(timeout_seconds, 5),
            )
            assert outcome.returncode == 1 and not outcome.timed_out
            assert outcome.process_stop is not None
            outcome.process_stop.validate_integrity()
            with pytest.raises(ProcessLookupError):
                os.killpg(outcome.process_stop.group_id, 0)
            # This runner wrapper seals its actual owned process observation,
            # matching the existing public stopped-provider regression fixture.
            continuation = self.adapter._interruption_control
            assert isinstance(continuation, NativeCoderContinuation)
            continuation.record_native_stop(
                request,
                cwd,
                process_stop=outcome.process_stop,
                output_present=False,
                cause=None,
                original_error_code=AgentErrorCode.AUTHENTICATION_ERROR,
            )
            return outcome

    class ObservedCodex(CodexCliAgentAdapter):
        def run(self, request: AgentRequest) -> AgentResult:
            self._runner = Runner(self, request)
            result = super().run(request)
            results.append(result)
            return result

    monkeypatch.setattr(production_delivery, "CodexCliAgentAdapter", ObservedCodex)
    config = ProductionConfig(
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
    )
    host = TeamHost(
        config=config,
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
        CreateRequirement(name="Stopped exhausted legacy wait", repository_roots=(str(repository),))
    ).checkpoint
    product = service.reply(
        ReplyToProduct(
            delivery_id=created.delivery_id,
            expected_checkpoint_sha256=created.checkpoint_sha256,
            message="Update the greeting.",
        )
    ).checkpoint

    def legacy_classification(error: AgentRunFailed) -> RetryClassification:
        # Reproduce only the historical routing defect. The real model failure,
        # flags, owned stop, claim and SQL facts are never rewritten by the fixture.
        assert error.result.error is not None
        assert error.result.error.code is AgentErrorCode.AUTHENTICATION_ERROR
        assert not error.result.error.transient
        return RetryClassification.TRANSIENT_INFRA

    with monkeypatch.context() as legacy:
        legacy.setattr(retry, "_classification", legacy_classification)
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
    assert pending.stage is DeliveryStage.DELIVERING
    assert pending.task_id is not None
    assert len(calls) == len(results) == 1
    assert results[0].error is not None and not results[0].error.transient
    (item,) = tuple(
        current
        for current in host.work_queue.items_for_task(pending.task_id)
        if current.status is not WorkItemStatus.CLOSED
    )
    assert item.status is WorkItemStatus.WAITING_DEPENDENCY
    assert item.wait_disposition is not None
    disposition = item.wait_disposition
    assert disposition.facts.classification == "TRANSIENT_INFRA"
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        before = tasks.get(pending.task_id)
        events = tasks.list_events(before.id)
    assert before.status is TaskStatus.IMPLEMENTING and before.work_budget_exhausted
    assert before.retry_failures is None
    assert before.transient_failures(AgentRole.CODER) == 0
    claims = host.work_queue.claims_for_work_item(item.id)
    assert len(claims) == 1
    sidecar = host.projects()[0].root / "repositories" / pending.repository_id
    original_records = {
        path: path.read_bytes()
        for directory in (sidecar / "state/invocations", sidecar / "state/continuations")
        for path in directory.rglob("*.json")
    }
    invocation = KnowledgeRecordStore(sidecar / "state/invocations", read_only=True).get(
        "invocation-outcomes", item.id, DeliveryInvocationOutcome
    )
    assert invocation.result == results[0]
    assert invocation.start.lease_id == claims[0].lease.id
    command = HandleDeliveryWait(
        work_item_id=item.id,
        expected_disposition_sha256=disposition.disposition_sha256,
        expected_task_intent_sha256=disposition.facts.task_intent_sha256,
        expected_source_revision=disposition.facts.source_revision,
        expected_checkpoint_sequence=disposition.facts.checkpoint_sequence,
    )
    handled = host.handle_delivery_wait(
        command, project_id="project_test", delivery_id=created.delivery_id
    )
    assert handled.status == "BUDGET_EXHAUSTED"
    assert handled.budget_settlement_sha256 is not None
    assert coordination_actions == ["PROPOSE_RECOVERY"]
    assert host.work_queue.get(item.id).status is WorkItemStatus.CLOSED
    assert host.work_queue.claims_for_work_item(item.id) == claims
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        settled = tasks.get(before.id)
        assert settled.status is TaskStatus.BLOCKED
        assert settled.attempts == before.attempts
        assert settled.retry_failures == before.retry_failures
        assert tasks.list_events(before.id)[:-1] == events
        assert len(tasks.list_events(before.id)) == len(events) + 1
    current = service.status(created.delivery_id).checkpoint
    assert current.stage is JointStage.BLOCKED
    assert current.children[0].checkpoint.task_id == before.id
    assert current.children[0].checkpoint.task_status is TaskStatus.BLOCKED
    assert current.children[0].checkpoint.task_revision == len(events) + 1

    resumed = host.resume_delivery(
        ResumeProjectDelivery(delivery_id=created.delivery_id), project_id="project_test"
    )
    assert isinstance(resumed, JointDeliveryResumeResult)
    assert resumed.checkpoint == service.status(created.delivery_id).checkpoint
    assert resumed.continuation.checkpoint == resumed.checkpoint.children[0].checkpoint
    assert resumed.continuation.outcome is DeliveryResumeOutcome.RECOVERY_APPROVAL_REQUIRED
    assert resumed.continuation.recovery_plan_file is not None
    _, plan = host.recovery_entry().open_plan(Path(resumed.continuation.recovery_plan_file))
    assert plan.plan_sha256 == resumed.continuation.recovery_plan_sha256
    assert plan.source.task_id == before.id
    assert plan.capture.branch_name == before.branch_name
    assert plan.source.scope.repository_root == str(repository)
    assert plan.target_base_revision == original_source
    assert len(calls) == len(results) == 1
    assert host.work_queue.claims_for_work_item(item.id) == claims
    assert (calls[0].workspace / "hello.txt").read_text() == "hello\n"
    assert (repository / "hello.txt").read_text() == "hello\n"
    for path, body in original_records.items():
        assert path.read_bytes() == body, path
