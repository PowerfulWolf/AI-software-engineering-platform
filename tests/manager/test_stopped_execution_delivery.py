"""A genuinely expired native Coder resumes through exact public engineering gates."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pymysql.cursors import DictCursor

from ai_software_engineer.agents import (
    AgentRequest,
    AgentResult,
    FallbackStructuredModelClient,
    StructuredModelResult,
    StructuredModelRoute,
)
from ai_software_engineer.agents.codex_cli import (
    CodexCliAgentAdapter,
    CodexInvocationResult,
    SubprocessCodexCommandRunner,
)
from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, model_route_root
from ai_software_engineer.agents.openai_compatible import HttpResponse
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentRole,
    Evidence,
    EvidenceType,
    ImplementationReportArtifact,
    QaReportArtifact,
    QaReportStatus,
    QaTestRun,
    QaTestStatus,
    ReviewReportArtifact,
    ReviewVerdict,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.agent import ROLE_OUTPUTS
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    BaselinePurpose,
    ExecutionBaselineBinding,
)
from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy, StageRetryPolicy
from ai_software_engineer.evaluation import (
    AdrStatus,
    EvaluationEngine,
    EvaluationTraceBuilder,
    FileEvaluationEventStore,
    HumanAction,
    HumanActionEvent,
)
from ai_software_engineer.execution import SubprocessCommandExecutor
from ai_software_engineer.git import WorkspacePolicy, WorkspacePolicyError
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.knowledge.preparation_retry import claim_identity_sha256
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager import production_backend, production_delivery
from ai_software_engineer.manager.baseline_models import ExecutionBaselinePlan
from ai_software_engineer.manager.baseline_production import ProductionBaselineFactCollector
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.delivery import StartProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.owned_sessions import require_recorded_session_empty
from ai_software_engineer.runtime import _default_case_id
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.web_console import (
    ConsoleOperationStatus,
    FileConsoleOperationStore,
    ManagerConsoleAdapter,
    ProjectConsole,
)
from ai_software_engineer.web_console.models import (
    ContinueDeliveryIntent,
    ExecuteExecutionBaselineIntent,
    ProductApprovalIntent,
    ProposeExecutionBaselineIntent,
    ResumeExecutionBaselineIntent,
)
from ai_software_engineer.work_queue import baseline as queue_baseline
from ai_software_engineer.work_queue.baseline import consumptions
from ai_software_engineer.work_queue.dispatcher import DispatcherLoop, DispatcherTickResult
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueuedWorkItem
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.knowledge.test_invocation_native import _http_client, _HttpTransport
from tests.manager.test_production_backend import (
    _git,
    _git_output,
    _ScriptedClientFactory,
    _ScriptedStructuredClient,
)
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_production_continuation import Invocation, _coder_draft
from tests.manager.test_production_continuation_v2 import DESIRED, _ReportTemplate


@pytest.mark.mysql
@pytest.mark.parametrize("late_raw_artifact", [False, True], ids=["delivery", "late-artifact"])
def test_public_stopped_unknown_coder_pauses_then_independently_delivers_original_task(
    tmp_path: Path,
    mysql_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    late_raw_artifact: bool,
) -> None:
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", ".", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    source = _git_output("rev-parse", "HEAD", cwd=repository)
    calls: list[Invocation] = []
    native_adapters: list[CodexCliAgentAdapter] = []
    expected_binding: str | None = None
    original_complete = _ScriptedStructuredClient.complete

    def inspect_source(
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
        if output_schema.get("title") != "TechnicalDesignDraft":
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
                    "checklist": ["Inspect the exact committed greeting."],
                },
            }
            for mapping in mappings
        ]
        return StructuredModelResult(payload=payload, duration_ms=result.duration_ms)

    monkeypatch.setattr(_ScriptedStructuredClient, "complete", inspect_source)

    class ObservedClients:
        def for_project(
            self, repository_root: Path, role: TeamRole = TeamRole.PRODUCT
        ) -> FallbackStructuredModelClient:
            scripted = _ScriptedClientFactory().for_project(repository_root, role)

            class Client:
                def complete(
                    self,
                    *,
                    instructions: str,
                    input_payload: Mapping[str, object],
                    output_schema: Mapping[str, object],
                    timeout_seconds: int,
                    input_images: tuple[Path, ...] = (),
                ) -> StructuredModelResult:
                    result = scripted.complete(
                        instructions=instructions,
                        input_payload=input_payload,
                        output_schema=output_schema,
                        timeout_seconds=timeout_seconds,
                        input_images=input_images,
                    )
                    response = {
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": json.dumps(dict(result.payload)),
                                    }
                                ],
                            }
                        ]
                    }
                    # Traverse the actual adapter observer so the knowledge journal
                    # seals independent admission and completed HTTP round-trip facts.
                    transport = _HttpTransport(
                        HttpResponse(status_code=200, body=json.dumps(response).encode()),
                        before_return=lambda: None,
                    )
                    return _http_client(transport, "fixture-model").complete(
                        instructions=instructions,
                        input_payload=input_payload,
                        output_schema=output_schema,
                        timeout_seconds=timeout_seconds,
                        input_images=input_images,
                    )

            return FallbackStructuredModelClient(
                (StructuredModelRoute(provider="fixture", model="fixture-model", client=Client()),),
                role=role,
            )

    monkeypatch.setattr(
        production_backend, "ConfiguredStructuredClientFactory", lambda *_: ObservedClients()
    )

    class ExpiringRunner(SubprocessCodexCommandRunner):
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
            guard = cast(WorkerExecutionGuard, self._execution_guard)
            assert guard.lease is not None
            lease = guard.lease
            now = datetime.now(UTC)
            expires = now + timedelta(milliseconds=750)
            # Exercise the actual queue renewal API and native clock fence.
            # No SQL mutation or manufactured process-stop record is involved.
            lease.queue.renew(
                lease.claim.work_item.id,
                lease_id=lease.claim.lease.id,
                owner_token=lease._token,
                now=now,
                expires_at=expires,
            )
            lease._expires_at = expires
            return super().run_observed(
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import time; "
                    "Path('hello.txt').write_text('retained stopped draft\\n'); time.sleep(10)",
                ),
                cwd=cwd,
                environment=environment,
                stdin=stdin,
                timeout_seconds=timeout_seconds,
                observer=observer,
            )

    class CompletedRunner:
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
            del stdin, timeout_seconds
            adapter, request = self.adapter, self.request
            assert request.execution_baseline_sha256 == expected_binding
            policy = WorkspacePolicy(cwd, request.permissions)
            if request.role is AgentRole.CODER:
                assert request.attempt == 2
                assert (cwd / "hello.txt").read_text() == "retained stopped draft\n"
                policy.authorize_write("hello.txt")
                with pytest.raises(WorkspacePolicyError):
                    policy.authorize_write(".trellis/spec/core/forbidden.md")
                (cwd / "hello.txt").write_text(DESIRED)
                artifact = _coder_draft(adapter, request)
            else:
                with pytest.raises(WorkspacePolicyError):
                    policy.authorize_write("hello.txt")
                definition = AgentDefinition(
                    id=adapter._agent_id,
                    role=request.role,
                    version=adapter._agent_version,
                    model=adapter._model,
                    permissions=request.permissions,
                    input_artifacts=(),
                    output_artifacts=ROLE_OUTPUTS[request.role],
                    max_retries=0,
                    timeout_seconds=request.timeout_seconds,
                )
                independent = _ReportTemplate(definition, cwd, DESIRED).run(request)
                assert independent.artifact is not None
                artifact = independent.artifact
                command = ("git", "show", f"{request.source_revision}:hello.txt")
                inspected = SubprocessCommandExecutor(
                    cwd,
                    request.permissions,
                    environment=environment,
                    execution_guard=cast(WorkerExecutionGuard, adapter._execution_guard),
                ).run(command, timeout_seconds=5)
                assert inspected.returncode == 0 and inspected.stdout == DESIRED
                evidence_path = tmp_path / f"inspection-{request.run_id}.json"
                evidence_path.write_text(inspected.model_dump_json())
                evidence = Evidence(
                    evidence_id=f"ev_{request.run_id.removeprefix('run_')}",
                    type=EvidenceType.TEST
                    if request.role is AgentRole.QA
                    else EvidenceType.COMMAND,
                    uri=evidence_path.as_uri(),
                    description="Independent native inspection of the exact candidate.",
                    sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                )
                if isinstance(artifact, QaReportArtifact):
                    artifact = artifact.model_copy(
                        update={
                            "evidence": (evidence,),
                            "content": artifact.content.model_copy(
                                update={
                                    "criteria_results": tuple(
                                        item.model_copy(
                                            update={"evidence_ids": (evidence.evidence_id,)}
                                        )
                                        for item in artifact.content.criteria_results
                                    ),
                                    "tests_run": (
                                        QaTestRun(
                                            command=" ".join(command),
                                            status=QaTestStatus.PASS,
                                            evidence_id=evidence.evidence_id,
                                            duration_ms=inspected.duration_ms,
                                        ),
                                    ),
                                }
                            ),
                        }
                    )
                else:
                    assert isinstance(artifact, ReviewReportArtifact)
                    artifact = artifact.model_copy(
                        update={
                            "evidence": (evidence,),
                            "content": artifact.content.model_copy(
                                update={"evidence": (evidence.evidence_id,)}
                            ),
                        }
                    )
            Path(argv[argv.index("--output-last-message") + 1]).write_text(
                artifact.model_dump_json()
            )
            return CodexInvocationResult(returncode=0)

    class ObservedCodex(CodexCliAgentAdapter):
        def run(self, request: AgentRequest) -> AgentResult:
            guard = cast(WorkerExecutionGuard, self._execution_guard)
            guard.check()
            assert guard.lease is not None
            native_adapters.append(self)
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
            self._runner = (
                ExpiringRunner(guard)
                if request.role is AgentRole.CODER and request.attempt == 1
                else CompletedRunner(self, request)
            )
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
                    provider="codex", model="offline-native", kind=ModelProviderKind.CODEX_CLI
                ),
            ),
            execution_retry_policy=ExecutionRetryPolicy(coder=StageRetryPolicy(max_attempts=3)),
        ),
        environment={
            "ASE_MYSQL_DSN": mysql_dsn,
            "PATH": os.environ.get("PATH", os.defpath),
            "GIT_AUTHOR_NAME": "ASE Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "ASE Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        },
        structured_clients=ObservedClients(),
        delivery_route_adapters=production_delivery.ConfiguredDeliveryRouteAdapterFactory(),
    )
    service = host.project_entry()
    product = service.start(
        StartProjectDelivery(
            repository_root=str(repository), requirement="Update the greeting.", title="Stopped run"
        )
    ).checkpoint
    console = ProjectConsole(
        store=FileConsoleOperationStore(tmp_path / "operations", team_id="team_test"),
        executor=ManagerConsoleAdapter(host),
    )
    console.submit(
        ProductApprovalIntent(
            project_id="project_test",
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
        ),
        idempotency_key="stopped-public-product-approval",
    )
    console.run_once()
    assert len(calls) == 1
    (stopped,) = calls
    pending = service.status(product.delivery_id).checkpoint
    assert pending.task_id is not None and pending.repository_id is not None
    sidecar = host.projects()[0].root / "repositories" / pending.repository_id
    ledger = FileContinuationStore(
        sidecar / "state/continuations" / pending.task_id, task_id=pending.task_id
    )
    stop = ledger.capture_stop(stopped.request.run_id)
    assert stop.process_stop is not None and stop.process_stop.returncode < 0
    assert stop.process_stop.kind == "failed" and stop.process_stop.session_proof is not None
    require_recorded_session_empty(stop.process_stop.session_proof)
    assert stop.cause is None and not stop.output_present
    assert stop.execution_abort_reason is not None
    assert stop.execution_abort_reason.detail == "local_expiry"
    records = KnowledgeRecordStore(sidecar / "state/invocations", read_only=True)
    original_start = records.get(
        "invocation-starts", stopped.claim.work_item.id, DeliveryInvocationStart
    )
    assert (
        records.find("invocation-outcomes", stopped.claim.work_item.id, DeliveryInvocationOutcome)
        is None
    )
    original_invocation_bytes = {
        path: path.read_bytes()
        for root in (
            sidecar / "state/invocations",
            sidecar / "state/continuations" / pending.task_id,
        )
        for path in root.glob("*.json")
    }
    (expired,) = tuple(
        item
        for item in host.work_queue.items_for_task(pending.task_id)
        if item.status is not WorkItemStatus.CLOSED
    )
    assert expired.status is WorkItemStatus.RUNNING
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    original_tick = DispatcherLoop.tick

    def quick_expiry_retry(
        self: DispatcherLoop, *, now: datetime, work_item_id: str | None = None
    ) -> DispatcherTickResult:
        # Only shorten the test scheduler's ordinary delayed re-claim window.
        # Claims, expiry publication and native continuation gates stay real.
        self._expired_lease_retry_delay = timedelta(microseconds=1)
        return original_tick(self, now=now, work_item_id=work_item_id)

    monkeypatch.setattr(DispatcherLoop, "tick", quick_expiry_retry)
    console.submit(
        ContinueDeliveryIntent(
            project_id="project_test",
            delivery_id=pending.delivery_id,
            expected_checkpoint_sha256=pending.checkpoint_sha256,
        ),
        idempotency_key="stopped-public-ordinary-continue",
    )
    console.run_once()
    assert host.work_queue.get(expired.id).status is WorkItemStatus.RETRY_SCHEDULED
    console.submit(
        ContinueDeliveryIntent(
            project_id="project_test",
            delivery_id=pending.delivery_id,
            expected_checkpoint_sha256=service.status(
                pending.delivery_id
            ).checkpoint.checkpoint_sha256,
        ),
        idempotency_key="stopped-public-reclaim-after-delay",
    )
    console.run_once()
    monkeypatch.setattr(DispatcherLoop, "tick", original_tick)
    assert len(calls) == 1, "ordinary continuation must not invoke another Coder"
    waiting = host.work_queue.get(expired.id)
    assert waiting.status in (WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY)
    assert waiting.wait_disposition is not None
    assert waiting.wait_disposition.facts.classification == "EXECUTION_UNCERTAIN"
    reclaim_claims = host.work_queue.claims_for_work_item(waiting.id)
    assert len(reclaim_claims) == 2
    assert stopped.claim.lease.id in {claim.lease.id for claim in reclaim_claims}
    assert len({claim.lease.id for claim in reclaim_claims}) == 2
    (reclaimed,) = tuple(
        claim for claim in reclaim_claims if claim.lease.id != stopped.claim.lease.id
    )
    assert reclaimed.work_item.dispatch_sequence > stopped.claim.work_item.dispatch_sequence
    assert reclaimed.claimed_at > original_start.started_at
    # The old runtime already performed this real read-only reclaim. No historical
    # replay-refusal marker exists; recovery must form a fresh engineering
    # observation from existing exact facts rather than inventing an old receipt.
    assert all(path.read_bytes() == body for path, body in original_invocation_bytes.items())
    assert records.list("invocation-starts", DeliveryInvocationStart) == (original_start,)
    assert records.list("invocation-outcomes", DeliveryInvocationOutcome) == ()
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        frozen = tasks.get(pending.task_id)
        revision = tasks.current_revision(pending.task_id)
        frozen_events = tasks.list_events(pending.task_id)
    assert frozen.status is TaskStatus.IMPLEMENTING
    assert frozen.attempts == frozen.work_attempt == 1 and not frozen.retry_failures
    original_history = {
        path: path.read_bytes()
        for path in (sidecar / "state/continuations" / frozen.id).rglob("*.json")
    }
    inventory = capture_mutation_inventory(stopped.workspace)
    index_path = Path(_git_output("rev-parse", "--git-path", "index", cwd=stopped.workspace))
    if not index_path.is_absolute():
        index_path = stopped.workspace / index_path
    index_bytes = index_path.read_bytes()
    console.submit(
        ProposeExecutionBaselineIntent(
            project_id="project_test",
            delivery_id=pending.delivery_id,
            expected_checkpoint_sha256=service.status(
                pending.delivery_id
            ).checkpoint.checkpoint_sha256,
            purpose=BaselinePurpose.STOPPED_EXECUTION_RESCUE,
            task_id=frozen.id,
            expected_task_intent_sha256=task_intent_sha256(frozen),
            expected_task_revision=revision,
            expected_work_item_id=waiting.id,
            expected_source_revision=source,
        ),
        idempotency_key="stopped-public-proposal",
    )
    proposed = console.run_once()
    assert proposed is not None and proposed.status is ConsoleOperationStatus.SUCCEEDED, proposed
    assert proposed.result is not None and proposed.result.execution_baseline_plan is not None
    plan = proposed.result.execution_baseline_plan
    assert plan.purpose is BaselinePurpose.STOPPED_EXECUTION_RESCUE
    assert plan.facts.stopped_execution is not None
    assert plan.facts.stopped_execution.invocation_start == original_start
    assert plan.facts.stopped_execution.capture_stop == stop
    assert plan.facts.continuation is not None and plan.facts.continuation.retry_failure is None
    assert "+retained stopped draft\n" in plan.complete_capture.patch
    prior_queue = host.work_queue.items_for_task(frozen.id)
    prior_step = host.work_queue.step(waiting.id)
    original_artifact_bytes = {
        path: path.read_bytes() for path in (sidecar / "artifacts").rglob("*.json")
    }
    last_validation_failures: list[str] = []
    late_artifact_id: str | None = None
    if late_raw_artifact:
        original_consume = queue_baseline.consume_baseline

        def consume_with_late_raw_output(
            queue: MySqlRoleQueue,
            plan: ExecutionBaselinePlan,
            binding: ExecutionBaselineBinding,
            *,
            cursor: DictCursor | None = None,
            validate_new_consumption: Callable[[], None] | None = None,
        ) -> QueuedWorkItem:
            assert validate_new_consumption is not None
            assert plan.facts.stopped_execution is not None
            assert not last_validation_failures

            def inject_then_validate() -> None:
                nonlocal late_artifact_id
                # Inject the adversarial late fact after service collection and
                # binding publication, precisely inside the final SQL fence.
                # It remains a raw immutable artifact, never an accepted result.
                late = seal_artifact(
                    _coder_draft(native_adapters[0], stopped.request),
                    validated_at=datetime.now(UTC),
                )
                raw_artifacts = FileArtifactStore(sidecar / "artifacts")
                raw_artifacts.put(late)
                assert raw_artifacts.get(late.artifact_id) == late
                late_artifact_id = late.artifact_id
                try:
                    validate_new_consumption()
                except ValueError as error:
                    last_validation_failures.append(str(error))
                    raise

            return original_consume(
                queue,
                plan,
                binding,
                cursor=cursor,
                validate_new_consumption=inject_then_validate,
            )

        monkeypatch.setattr(queue_baseline, "consume_baseline", consume_with_late_raw_output)
    console.submit(
        ExecuteExecutionBaselineIntent(
            project_id="project_test",
            delivery_id=pending.delivery_id,
            expected_checkpoint_sha256=service.status(
                pending.delivery_id
            ).checkpoint.checkpoint_sha256,
            task_id=frozen.id,
            expected_plan_sha256=plan.plan_sha256,
            reference="exact engineering decision: retain old unknown and all draft; pause",
            continuation_mode=BaselineContinuationMode.PAUSE,
        ),
        idempotency_key="stopped-public-pause",
    )
    executed = console.run_once()
    if late_raw_artifact:
        assert last_validation_failures, "the real final callback must reject the new raw output"
        assert executed is not None and executed.status is ConsoleOperationStatus.FAILED, executed
        assert executed.error_summary is not None
        assert late_artifact_id is not None
        late = FileArtifactStore(sidecar / "artifacts", read_only=True).get(late_artifact_id)
        assert late.producer.run_id == stopped.request.run_id
        assert late.integrity.validated
        assert not consumptions(host.work_queue, frozen.id)
        assert host.work_queue.items_for_task(frozen.id) == prior_queue
        assert host.work_queue.step(waiting.id) == prior_step
        assert host.work_queue.claims_for_work_item(waiting.id) == reclaim_claims
        assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
        assert len(calls) == len(native_adapters) == 1
        with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
            assert tasks.get(frozen.id) == frozen
            assert tasks.current_revision(frozen.id) == revision
            assert tasks.list_events(frozen.id) == frozen_events
        assert capture_mutation_inventory(stopped.workspace) == inventory
        assert index_path.read_bytes() == index_bytes
        assert _git_output("branch", "--show-current", cwd=stopped.workspace) == stopped.branch
        assert _git_output("rev-parse", "HEAD", cwd=stopped.workspace) == source
        assert all(path.read_bytes() == body for path, body in original_history.items())
        assert all(path.read_bytes() == body for path, body in original_invocation_bytes.items())
        assert all(path.read_bytes() == body for path, body in original_artifact_bytes.items())
        assert records.find("invocation-outcomes", waiting.id, DeliveryInvocationOutcome) is None
        assert not ledger.receipts_for_task(frozen.id)
        assert _git_output("rev-parse", "HEAD", cwd=repository) == source
        assert (repository / "hello.txt").read_text() == "hello\n"
        return
    assert executed is not None and executed.status is ConsoleOperationStatus.SUCCEEDED, executed
    assert executed.result is not None and executed.result.execution_baseline_binding is not None
    binding = executed.result.execution_baseline_binding
    expected_binding = binding.binding_sha256
    assert binding.stopped_execution_sha256 == plan.facts.stopped_execution.proof_sha256
    assert binding.execution_source_revision == binding.execution_base_ref == source
    assert len(calls) == 1 and len(consumptions(host.work_queue, frozen.id)) == 1
    assert capture_mutation_inventory(stopped.workspace) == inventory
    assert index_path.read_bytes() == index_bytes
    assert _git_output("branch", "--show-current", cwd=stopped.workspace) == stopped.branch
    assert all(path.read_bytes() == body for path, body in original_history.items())
    assert all(path.read_bytes() == body for path, body in original_invocation_bytes.items())
    (preserved,) = tuple(
        item
        for item in host.work_queue.items_for_task(frozen.id)
        if item.status is not WorkItemStatus.CLOSED
    )
    assert preserved.status is WorkItemStatus.WAITING_HUMAN
    assert preserved.attempt == 2 and preserved.parent_work_item_id == waiting.id
    assert preserved.wait_disposition is not None
    console.submit(
        ResumeExecutionBaselineIntent(
            project_id="project_test",
            delivery_id=pending.delivery_id,
            expected_checkpoint_sha256=service.status(
                pending.delivery_id
            ).checkpoint.checkpoint_sha256,
            task_id=frozen.id,
            expected_task_intent_sha256=task_intent_sha256(frozen),
            expected_task_revision=revision,
            expected_work_item_id=preserved.id,
            expected_source_revision=binding.execution_source_revision,
            expected_execution_baseline_sha256=binding.binding_sha256,
            expected_disposition_sha256=preserved.wait_disposition.disposition_sha256,
            reference="separate exact engineering release of the paused original Task",
        ),
        idempotency_key="stopped-public-explicit-resume",
    )
    resumed = console.run_once()
    assert resumed is not None and resumed.status is ConsoleOperationStatus.SUCCEEDED, resumed
    delivered = service.status(pending.delivery_id).checkpoint
    assert delivered.stage is DeliveryStage.DONE, delivered.failure_summary
    assert [call.request.role for call in calls] == [
        AgentRole.CODER,
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]
    successor, qa_call, reviewer_call = calls[1:]
    assert successor.workspace == stopped.workspace and successor.branch == stopped.branch
    assert successor.request.permissions == stopped.request.permissions
    assert len({call.request.run_id for call in calls}) == len(calls)
    assert len({call.claim.lease.id for call in calls}) == len(calls)
    assert len({call.claim.assignment.agent_id for call in calls}) == 3
    candidate = delivered.candidate_revision
    assert candidate is not None and candidate != source
    assert qa_call.request.source_revision == reviewer_call.request.source_revision == candidate
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        completed = tasks.get(frozen.id)
    assert completed.status is TaskStatus.DONE and completed.attempts == completed.work_attempt == 2
    assert not completed.retry_failures and task_intent_sha256(completed) == task_intent_sha256(
        frozen
    )
    artifacts = FileArtifactStore(sidecar / "artifacts", read_only=True).list_for_task(frozen.id)
    implementation = next(a for a in artifacts if isinstance(a, ImplementationReportArtifact))
    qa = next(a for a in artifacts if isinstance(a, QaReportArtifact))
    review = next(a for a in artifacts if isinstance(a, ReviewReportArtifact))
    assert (
        implementation.source_revision == qa.source_revision == review.source_revision == candidate
    )
    assert (
        qa.content.status is QaReportStatus.PASS and review.content.verdict is ReviewVerdict.APPROVE
    )
    assert all(path.read_bytes() == body for path, body in original_history.items())
    assert all(path.read_bytes() == body for path, body in original_invocation_bytes.items())
    assert records.get("invocation-starts", waiting.id, DeliveryInvocationStart) == original_start
    assert records.find("invocation-outcomes", waiting.id, DeliveryInvocationOutcome) is None
    assert not ledger.receipts_for_task(frozen.id)
    assert not FileModelRouteAttemptStore(model_route_root(sidecar)).list_for_run(
        stopped.request.run_id
    )
    baseline_store = FileExecutionBaselineStore(sidecar / "state/execution-baselines" / frozen.id)
    assert baseline_store.bindings_for_task(frozen.id) == (binding,)
    evaluation_events = FileEvaluationEventStore(sidecar / "evaluations", read_only=True)
    human_evidence = tuple(
        event
        for event in evaluation_events.list_for_case(_default_case_id(frozen.id))
        if isinstance(event, HumanActionEvent) and event.action is HumanAction.SUPPLY_EVIDENCE
    )
    assert len(human_evidence) == 1
    assert human_evidence[0].evidence_uri is not None
    assert human_evidence[0].event_id.startswith("evalevt_stopped_")
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        trace = EvaluationTraceBuilder(
            repository=tasks,
            artifact_store=FileArtifactStore(sidecar / "artifacts", read_only=True),
            event_store=evaluation_events,
        ).build(_default_case_id(frozen.id))
        evaluated = EvaluationEngine().evaluate((trace,)).cases[0]
        assert evaluated.adr.status is AdrStatus.INELIGIBLE
        assert "HUMAN_INTERVENTION" in evaluated.adr.reasons
        collector = (
            host._runtime("project_test")
            .backend.execution_baseline_service(
                delivered, repository=tasks, project_id="project_test"
            )
            .facts
        )
        assert isinstance(collector, ProductionBaselineFactCollector)
        proofs = collector._invocations(
            completed,
            host.work_queue.items_for_task(completed.id),
            collector._receipts(completed),
            tuple(a for a in host.work_queue.list_assignments() if a.task_id == completed.id),
        )
    proofs_by_item = {proof.work_item_id: proof for proof in proofs}
    assert proofs_by_item[waiting.id].proof_kind == "stopped_execution_without_outcome"
    assert proofs_by_item[waiting.id].outcome_sha256 is None
    (replay_observation,) = proofs_by_item[waiting.id].replay_guarded_claims
    replay_observation.validate_integrity()
    assert replay_observation.kind == "replay_guarded_claim_observation"
    assert replay_observation.lease_id == reclaimed.lease.id
    assert replay_observation.claim_sha256 == claim_identity_sha256(reclaimed)
    assert replay_observation.blocking_start_sha256 == original_start.start_sha256
    assert replay_observation.intent_sha256s and replay_observation.outcome_sha256s
    assert replay_observation.execution_record_sha256s and replay_observation.context_sha256s
    assert set(replay_observation.to_wire()) == {
        "kind",
        "lease_id",
        "claim_sha256",
        "blocking_start_sha256",
        "intent_sha256s",
        "outcome_sha256s",
        "execution_record_sha256s",
        "context_sha256s",
        "observation_sha256",
    }, "current engineering observation must not invent a historical refusal, result or stop"
    for call in calls[1:]:
        assert proofs_by_item[call.claim.work_item.id].proof_kind == "definitive_outcome"
    for value, name in (
        (plan.to_wire(), "execution-baseline-plan.schema.json"),
        (binding.to_wire(), "execution-baseline.schema.json"),
        (proposed.to_wire(), "console-operation.schema.json"),
        (
            consumptions(host.work_queue, frozen.id)[0].to_wire(),
            "execution-baseline-queue-consumption.schema.json",
        ),
    ):
        schema = json.loads((Path(__file__).parents[2] / "schemas" / name).read_text())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    assert all(
        item.status is WorkItemStatus.CLOSED for item in host.work_queue.items_for_task(frozen.id)
    )
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    assert _git_output("rev-parse", "HEAD", cwd=repository) == source
    assert (repository / "hello.txt").read_text() == "hello\n"
