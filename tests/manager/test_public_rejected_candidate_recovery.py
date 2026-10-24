"""Public Requirement recovery of a historically rejected native candidate.

The fixture deliberately emulates the old-version platform bug at one exact
Coder invocation.  It still uses real Git, a real native child process and a
real MySQL claim; only the first invocation's version admission is temporarily
relaxed so that an unsupported SUCCEEDED outcome can be sealed for recovery.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.agents import (
    AgentRequest,
    AgentResult,
    AgentRunStatus,
    StructuredModelResult,
    codex_cli,
)
from ai_software_engineer.agents.codex_cli import (
    CodexCliAgentAdapter,
    CodexInvocationResult,
    SubprocessCodexCommandRunner,
)
from ai_software_engineer.agents.models import AgentOutputContractError
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.context.execution_baseline import parse_execution_baseline_context
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentRole,
    Artifact,
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
from ai_software_engineer.domain.artifact import validate_current_artifact_version
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.coordination import ManagerCoordinationDraft
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    BaselinePurpose,
)
from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy, StageRetryPolicy
from ai_software_engineer.execution import SubprocessCommandExecutor
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager import production_backend, production_delivery
from ai_software_engineer.manager.baseline_production import (
    BaselineContinueCommand,
    BaselineExecuteCommand,
    BaselineProposeCommand,
)
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    ReplyToProduct,
    ResumeProjectDelivery,
)
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.production_agents import ExecutionPlanDraft, TechnicalDesignDraft
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.multi_directory.models import JointDeliveryResult
from ai_software_engineer.multi_directory.scope import DirectoryScope
from ai_software_engineer.multi_directory.service import CreateRequirement
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.scheduling import PortfolioScheduler
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.store.mysql_repository import open_mysql_connection
from ai_software_engineer.work_queue.baseline import consumptions
from ai_software_engineer.work_queue.dispatcher import DispatcherLoop, DispatcherTickResult
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DurableInvocationControl,
)
from ai_software_engineer.work_queue.ports import DeliveryQueuePending
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
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
@pytest.mark.parametrize("blocked_child", [False, True], ids=["pending_child", "blocked_child"])
def test_public_requirement_recovers_rejected_candidate_with_pause_and_resume(
    tmp_path: Path,
    mysql_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    blocked_child: bool,
) -> None:
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n", encoding="utf-8")
    _git("init", "-b", "main", cwd=repository)
    _git("add", ".", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    approved_source = _git_output("rev-parse", "HEAD", cwd=repository)

    # The public joint flow needs typed joint design/plan wrappers.  All actual
    # product/design/planning checks remain the production implementation.
    original_complete = _ScriptedStructuredClient.complete

    def complete(
        self: _ScriptedStructuredClient,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        del input_images
        title = output_schema.get("title")
        if title == "ManagerCoordinationDraft":
            assert blocked_child
            assert "WAITING_HUMAN" in cast(list[str], input_payload["advertised_actions"])
            return StructuredModelResult(
                payload=ManagerCoordinationDraft(
                    action="WAITING_HUMAN",
                    summary="原 Coder 版本不被接纳, 完整候选和成功调用历史保留。",
                    next_action="核验原调用、真实停止和完整候选, 通过公开精确恢复授权继续。",
                    responsible_actor="ASE 平台与工程授权者",
                    resume_condition="原需求的精确候选恢复方案已批准。",
                ).to_wire(),
                duration_ms=0,
            )
        if title in {"JointTechnicalDesign", "JointExecutionPlan"}:
            scope = DirectoryScope.model_validate(input_payload["scope"])
            (unit,) = scope.units
            nested = original_complete(
                self,
                instructions=instructions,
                input_payload=input_payload,
                output_schema=(
                    TechnicalDesignDraft.model_json_schema()
                    if title == "JointTechnicalDesign"
                    else ExecutionPlanDraft.model_json_schema()
                ),
                timeout_seconds=timeout_seconds,
            )
            if title == "JointTechnicalDesign":
                payload = dict(nested.payload)
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
                    for mapping in cast(list[Mapping[str, object]], payload["acceptance_mappings"])
                ]
                nested = StructuredModelResult(payload=payload, duration_ms=nested.duration_ms)
                return StructuredModelResult(
                    payload={
                        "product_spec_sha256": input_payload["product_spec_sha256"],
                        "summary": "Inspect the greeting.",
                        "blocking_issues": [],
                        "units": [
                            {
                                "unit_id": unit.id,
                                "requirement_ids": ["req_001"],
                                "design": nested.payload,
                            }
                        ],
                    },
                    duration_ms=0,
                )
            return StructuredModelResult(
                payload={
                    "design_sha256": input_payload["design_sha256"],
                    "units": [{"unit_id": unit.id, "plan": nested.payload}],
                    "integration_checks": [],
                },
                duration_ms=0,
            )
        return original_complete(
            self,
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
        )

    monkeypatch.setattr(_ScriptedStructuredClient, "complete", complete)
    monkeypatch.setattr(
        production_backend,
        "ConfiguredStructuredClientFactory",
        lambda *_: _ScriptedClientFactory(),
    )

    calls: list[Invocation] = []
    old_run_id: str | None = None
    old_output_seen = False
    results: list[AgentResult] = []
    fixture_errors: list[str] = []
    expected_binding: str | None = None
    retained_candidate: str | None = None

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
            nonlocal old_run_id, old_output_seen
            guard = cast(WorkerExecutionGuard, self.adapter._execution_guard)
            guard.check()
            assert guard.lease is not None
            claim = guard.lease.claim
            calls.append(
                Invocation(
                    self.request,
                    claim,
                    cwd,
                    _git_output("branch", "--show-current", cwd=cwd),
                    _git_output("rev-parse", "HEAD", cwd=cwd),
                    self.adapter._model,
                )
            )
            assert calls[-1].input_head == self.request.source_revision
            assert claim.work_item.role is self.request.role
            assert claim.work_item.attempt == self.request.attempt
            output_path = Path(argv[argv.index("--output-last-message") + 1])
            artifact: Artifact
            if self.request.role is AgentRole.CODER and old_run_id is None:
                old_run_id = self.request.run_id
                assert self.request.execution_baseline_sha256 is None
                artifact = _coder_draft(self.adapter, self.request).model_copy(
                    update={"schema_version": "v1.0"}
                )
                old_output_seen = True
                worktree_text = DESIRED
            elif self.request.role is AgentRole.CODER:
                assert self.request.source_revision == retained_candidate
                assert self.request.execution_baseline_sha256 == expected_binding
                assert (cwd / "hello.txt").read_text() == DESIRED
                assert _git_output("status", "--porcelain", cwd=cwd) == ""
                # A fresh current report describes the already committed
                # complete candidate; only the trusted rescue admission may
                # authorize this no-new-commit re-report.
                artifact = _coder_draft(self.adapter, self.request)
                worktree_text = DESIRED
            else:
                # QA/Review reports are generated from the independent report
                # templates below; they never reuse the Coder verdict.
                definition = AgentDefinition(
                    id=self.adapter._agent_id,
                    role=self.request.role,
                    version=self.adapter._agent_version,
                    model=self.adapter._model,
                    permissions=self.request.permissions,
                    input_artifacts=(),
                    output_artifacts=ROLE_OUTPUTS[self.request.role],
                    max_retries=0,
                    timeout_seconds=self.request.timeout_seconds,
                )
                independent = _ReportTemplate(definition, cwd, DESIRED).run(self.request)
                assert independent.artifact is not None
                artifact = independent.artifact
                command = ("git", "show", f"{self.request.source_revision}:hello.txt")
                observed = SubprocessCommandExecutor(
                    cwd,
                    self.request.permissions,
                    environment=environment,
                    execution_guard=guard,
                ).run(command, timeout_seconds=5)
                assert observed.returncode == 0 and observed.stdout == DESIRED
                evidence_path = tmp_path / f"verification-{self.request.run_id}.json"
                evidence_path.write_text(observed.model_dump_json())
                evidence = Evidence(
                    evidence_id=f"ev_{self.request.run_id.removeprefix('run_')}",
                    type=EvidenceType.TEST
                    if self.request.role is AgentRole.QA
                    else EvidenceType.COMMAND,
                    uri=evidence_path.as_uri(),
                    description="Independent candidate greeting inspection.",
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
                                            duration_ms=observed.duration_ms,
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
                output_path.write_text(artifact.model_dump_json())
                return CodexInvocationResult(returncode=0)
            payload = json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False)
            encoded = base64.b64encode(payload.encode()).decode()
            script = (
                "import base64, pathlib, sys; sys.stdin.read(); "
                "pathlib.Path('hello.txt').write_text(sys.argv[2]); "
                "pathlib.Path(sys.argv[1]).write_text(base64.b64decode(sys.argv[3]).decode())"
            )
            result = SubprocessCodexCommandRunner(guard).run(
                (sys.executable, "-c", script, str(output_path), worktree_text, encoded),
                cwd=cwd,
                environment=environment,
                stdin=stdin,
                timeout_seconds=min(timeout_seconds, 5),
            )
            assert result.process_stop is not None
            result.process_stop.validate_integrity()
            assert result.returncode == 0 and result.process_stop.kind == "completed"
            assert result.process_stop.session_proof is not None
            assert result.process_stop.session_proof.proof_scope == "owned_session_empty"
            with pytest.raises(ProcessLookupError):
                os.killpg(result.process_stop.group_id, 0)
            control = self.adapter._interruption_control
            assert isinstance(control, NativeCoderContinuation)
            control.record_native_stop(
                self.request,
                cwd,
                process_stop=result.process_stop,
                output_present=True,
                cause=None,
                original_error_code=None,
            )
            return result

    class ObservedCodex(CodexCliAgentAdapter):
        def run(self, request: AgentRequest) -> AgentResult:
            self._runner = Runner(self, request)
            try:
                result = super().run(request)
            except AssertionError as error:
                fixture_errors.append(str(error))
                raise
            results.append(result)
            return result

    monkeypatch.setattr(production_delivery, "CodexCliAgentAdapter", ObservedCodex)

    # Simulate exactly the old unsupported-version acceptance for the first
    # invocation. Current validation is restored before PAUSE/RESUME.
    original_version = validate_current_artifact_version
    original_result_validation = AgentResult.validate_current_output
    original_completed = DurableInvocationControl.completed
    original_tick = DispatcherLoop.tick

    def old_version(artifact: Artifact) -> None:
        if artifact.producer.run_id == old_run_id and artifact.schema_version == "v1.0":
            return
        original_version(artifact)

    def old_result(self: AgentResult) -> None:
        if self.run_id == old_run_id and getattr(self.artifact, "schema_version", None) == "v1.0":
            return
        original_result_validation(self)

    def seal_then_crash(
        control: DurableInvocationControl, request: AgentRequest, result: AgentResult
    ) -> None:
        original_completed(control, request, result)
        if request.run_id == old_run_id and not blocked_child:
            # Test-only old worker crash boundary. The public pending handler
            # preserves its real child mapping; no queue/journal is fabricated.
            raise DeliveryQueuePending(
                "historical worker stopped after sealing unsupported SUCCEEDED"
            )

    def short_first_lease(
        dispatcher: DispatcherLoop, *, now: datetime, work_item_id: str | None = None
    ) -> DispatcherTickResult:
        # Real SQL ownership, owner fencing and heartbeats remain enabled.
        # Its shortened TTL avoids waiting a production minute after the crash.
        dispatcher._scheduler = PortfolioScheduler(lease_duration=timedelta(seconds=6))
        return original_tick(dispatcher, now=now, work_item_id=work_item_id)

    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        default_project_id="project_test",
        default_project_name="Test Project",
        live_model_execution=True,
        model_routes=(
            ProviderRouteConfig(
                provider="codex", model="gpt-primary", kind=ModelProviderKind.CODEX_CLI
            ),
        ),
        execution_retry_policy=ExecutionRetryPolicy(coder=StageRetryPolicy(max_attempts=3)),
    )
    environment = {
        "ASE_MYSQL_DSN": mysql_dsn,
        "PATH": os.environ.get("PATH", os.defpath),
        "GIT_AUTHOR_NAME": "ASE Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "ASE Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    }
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=production_delivery.ConfiguredDeliveryRouteAdapterFactory(),
    )

    service = host.requirement_entry()
    initial = service.create(
        CreateRequirement(name="Recover rejected greeting", repository_roots=(str(repository),))
    ).checkpoint
    product = service.reply(
        ReplyToProduct(
            delivery_id=initial.delivery_id,
            expected_checkpoint_sha256=initial.checkpoint_sha256,
            message="Update the greeting.",
        )
    ).checkpoint
    # The first Coder call happens as the approved Requirement advances through
    # its public child delivery.  A transient backend stop is expected here.
    with monkeypatch.context() as historical:
        historical.setattr(codex_cli, "validate_current_artifact_version", old_version)
        historical.setattr(AgentResult, "validate_current_output", old_result)
        historical.setattr(DurableInvocationControl, "completed", seal_then_crash)
        historical.setattr(DispatcherLoop, "tick", short_first_lease)
        approved = service.approve(
            ApproveProductSpec(
                delivery_id=product.delivery_id,
                expected_checkpoint_sha256=product.checkpoint_sha256,
                approval_reference="exact-original-product-approval",
            )
        )
    assert isinstance(approved, JointDeliveryResult)
    child = approved.checkpoint.children[0].checkpoint
    assert old_output_seen and old_run_id is not None
    assert child.task_id is not None and len(calls) == 1

    with MySqlTaskRepository(mysql_dsn) as tasks:
        frozen = tasks.get(child.task_id)
        frozen_revision = tasks.current_revision(frozen.id)
        frozen_events = tasks.list_events(frozen.id)
    assert frozen.status is TaskStatus.IMPLEMENTING
    assert child.stage is (DeliveryStage.BLOCKED if blocked_child else DeliveryStage.DELIVERING)
    if blocked_child:
        # The old adapter/result validators admitted v1.0 into the real durable
        # invocation journal; current ArtifactStore independently rejects it.
        # No Task/item/journal patch manufactures the production K1 shape.
        assert child.failure_code is not None
        assert child.failure_code.value == "INVARIANT_VIOLATION"
        assert child.failure_summary is not None and "SchemaVersionError" in child.failure_summary
    retained_candidate = _git_output("rev-parse", "HEAD", cwd=calls[0].workspace)
    assert retained_candidate != approved_source
    assert frozen.attempts == frozen.work_attempt == 1
    assert not frozen.retry_failures
    sidecar = host.projects()[0].root / "repositories" / child.repository_id
    artifacts = FileArtifactStore(sidecar / "artifacts", read_only=True)
    original_artifacts = artifacts.list_for_task(frozen.id)
    assert not any(isinstance(a, ImplementationReportArtifact) for a in original_artifacts)
    original_immutable_bytes = {
        path: path.read_bytes()
        for root in (
            sidecar / "state/invocations",
            sidecar / "state/continuations" / frozen.id,
            sidecar / "runs/model-routes",
            sidecar / "policy",
        )
        for path in root.rglob("*.json")
    }
    original_item = next(
        item
        for item in host.work_queue.items_for_task(frozen.id)
        if item.status is WorkItemStatus.RUNNING
    )
    ledger = KnowledgeRecordStore(sidecar / "state/invocations", read_only=True)
    old_outcome = ledger.get("invocation-outcomes", original_item.id, DeliveryInvocationOutcome)
    old_outcome.validate_integrity()
    assert old_outcome.result.status is AgentRunStatus.SUCCEEDED
    assert isinstance(old_outcome.result.artifact, ImplementationReportArtifact)
    assert old_outcome.result.artifact.schema_version == "v1.0"
    assert old_outcome.result.artifact.source_revision == retained_candidate
    with pytest.raises(AgentOutputContractError):
        old_outcome.result.validate_current_output()
    receipt_store = FileContinuationStore(
        sidecar / "state/continuations" / frozen.id, task_id=frozen.id
    )
    stop = receipt_store.capture_stop(old_run_id)
    stop.validate_integrity()
    assert stop.process_stop.returncode == 0 and stop.output_present
    assert stop.process_stop.session_proof is not None
    assert stop.process_stop.session_proof.proof_scope == "owned_session_empty"
    assert receipt_store.receipts_for_task(frozen.id) == ()

    def old_claim_state() -> str:
        # Read the real SQL claim state: list_active_leases intentionally hides
        # expired ACTIVE rows, which are the historical recovery stock here.
        with (
            closing(open_mysql_connection(mysql_dsn)) as connection,
            connection.cursor(DictCursor) as cursor,
        ):
            cursor.execute(
                "SELECT state FROM work_queue_claims WHERE lease_id=%s",
                (calls[0].claim.lease.id,),
            )
            row = cursor.fetchone()
            assert row is not None
            return str(row["state"])

    assert old_claim_state() == "ACTIVE"
    deadline = time.monotonic() + 15
    while any(
        lease.id == calls[0].claim.lease.id
        for lease in host.work_queue.list_active_leases(now=datetime.now(UTC))
    ):
        assert time.monotonic() < deadline, "original real lease did not expire after Worker stop"
        time.sleep(0.05)
    assert old_claim_state() == "ACTIVE"

    # From this point all current gates are active.  The proposal is public and
    # binds the exact original Task/item/source; no old output is edited.
    command = BaselineProposeCommand(
        delivery_id=product.delivery_id,
        task_id=frozen.id,
        expected_task_intent_sha256=task_intent_sha256(frozen),
        expected_task_revision=frozen_revision,
        expected_work_item_id=original_item.id,
        expected_source_revision=approved_source,
        purpose=BaselinePurpose.REJECTED_CANDIDATE_RESCUE,
    )
    plan = host.propose_execution_baseline(command, project_id="project_test")
    assert len(calls) == 1
    assert old_claim_state() == "EXPIRED"
    assert host.work_queue.get(original_item.id) == original_item
    assert plan.facts.rejected_candidate_output is not None
    assert plan.facts.rejected_candidate_output.outcome == old_outcome
    assert plan.facts.rejected_candidate_output.candidate_revision == retained_candidate
    execute = BaselineExecuteCommand(
        delivery_id=product.delivery_id,
        task_id=frozen.id,
        expected_plan_sha256=plan.plan_sha256,
        reference="exact rejected candidate recovery",
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    binding = host.execute_execution_baseline(execute, project_id="project_test")
    expected_binding = binding.binding_sha256
    assert binding.approved_base_ref == binding.execution_base_ref == approved_source
    assert binding.execution_source_revision == retained_candidate
    assert binding.rejected_candidate_output_sha256 is not None
    assert binding.continuation_mode is BaselineContinuationMode.PAUSE
    assert _git_output("rev-parse", "HEAD", cwd=calls[0].workspace) == retained_candidate
    assert _git_output("status", "--porcelain", cwd=calls[0].workspace) == ""
    waiting = next(
        item
        for item in host.work_queue.items_for_task(frozen.id)
        if item.status is not WorkItemStatus.CLOSED
    )
    assert waiting.status is WorkItemStatus.WAITING_HUMAN
    assert waiting.wait_disposition is not None
    assert waiting.parent_work_item_id == original_item.id
    assert waiting.attempt == 2 and waiting.dispatch_sequence == 0
    assert host.work_queue.get(original_item.id).status is WorkItemStatus.CLOSED
    assert len(calls) == 1
    assert host.execute_execution_baseline(execute, project_id="project_test") == binding
    service.resume(ResumeProjectDelivery(delivery_id=product.delivery_id))
    assert len(calls) == 1
    assert host.work_queue.get(waiting.id) == waiting
    continue_command = BaselineContinueCommand(
        delivery_id=product.delivery_id,
        task_id=frozen.id,
        expected_task_intent_sha256=task_intent_sha256(frozen),
        expected_task_revision=frozen_revision,
        expected_work_item_id=waiting.id,
        expected_source_revision=binding.execution_source_revision,
        expected_execution_baseline_sha256=binding.binding_sha256,
        expected_disposition_sha256=waiting.wait_disposition.disposition_sha256,
        reference="explicit exact rejected candidate resume",
    )
    resumed = host.continue_execution_baseline(continue_command, project_id="project_test")
    assert resumed is not None
    current = service.status(product.delivery_id).checkpoint
    delivered = current.children[0].checkpoint
    assert delivered.stage is DeliveryStage.DONE, (
        delivered.failure_summary,
        [(result.role, result.error) for result in results],
        fixture_errors,
    )
    assert delivered.task_id == frozen.id
    assert delivered.preparation_sha256 == child.preparation_sha256
    assert delivered.approval_sha256 == child.approval_sha256
    assert current.delivery_id == product.delivery_id
    assert current.product_spec == approved.checkpoint.product_spec
    assert current.approval == approved.checkpoint.approval
    assert len(calls) == 4
    assert [call.request.role for call in calls] == [
        AgentRole.CODER,
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]
    assert len({call.request.run_id for call in calls}) == 4
    assert len({call.claim.lease.id for call in calls}) == 4
    assert calls[1].request.source_revision == retained_candidate
    assert calls[0].request.source_revision == approved_source
    assert all(
        call.request.source_revision == calls[1].request.source_revision for call in calls[1:]
    )
    assert calls[1].request.execution_baseline_sha256 == binding.binding_sha256
    assert calls[0].workspace == calls[1].workspace
    assert calls[0].branch == calls[1].branch
    assert len({call.workspace for call in calls[1:]}) == 3
    assert len({call.claim.assignment.agent_id for call in calls}) == 3
    assert frozen.base_ref == approved_source
    assert _git_output("rev-parse", "HEAD", cwd=repository) == approved_source
    assert (repository / "hello.txt").read_text() == "hello\n"
    assert not (repository / ".ase").exists()
    assert delivered.candidate_revision == retained_candidate
    with MySqlTaskRepository(mysql_dsn) as tasks:
        completed = tasks.get(frozen.id)
        assert tasks.list_events(frozen.id)[: len(frozen_events)] == frozen_events
    assert completed.status is TaskStatus.DONE
    assert completed.base_ref == approved_source
    assert completed.attempts == completed.work_attempt == 2
    assert completed.retry_failures == frozen.retry_failures
    assert task_intent_sha256(completed) == task_intent_sha256(frozen)
    final_artifacts = artifacts.list_for_task(frozen.id)
    (implementation,) = tuple(
        a for a in final_artifacts if isinstance(a, ImplementationReportArtifact)
    )
    (qa,) = tuple(a for a in final_artifacts if isinstance(a, QaReportArtifact))
    (review,) = tuple(a for a in final_artifacts if isinstance(a, ReviewReportArtifact))
    assert implementation.schema_version == qa.schema_version == review.schema_version == "v0.1"
    assert (
        implementation.content.commit_sha
        == qa.source_revision
        == review.source_revision
        == retained_candidate
    )
    assert qa.content.status is QaReportStatus.PASS
    assert review.content.verdict is ReviewVerdict.APPROVE
    assert len({a.producer.agent_id for a in (implementation, qa, review)}) == 3
    assert all(a in final_artifacts for a in original_artifacts)
    assert all(path.read_bytes() == body for path, body in original_immutable_bytes.items())
    assert (
        ledger.get("invocation-outcomes", original_item.id, DeliveryInvocationOutcome)
        == old_outcome
    )
    assert old_claim_state() == "EXPIRED"
    assert all(
        item.status is WorkItemStatus.CLOSED for item in host.work_queue.items_for_task(frozen.id)
    )
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    store = FileExecutionBaselineStore(
        sidecar / "state/execution-baselines" / frozen.id, read_only=True
    )
    assert store.bindings_for_task(frozen.id) == (binding,)
    assert len(consumptions(host.work_queue, frozen.id)) == 1
    contexts = FileContextStore(sidecar / "contexts")
    for call in calls[1:]:
        context = contexts.get(call.request.context_manifest_id)
        (section,) = tuple(s for s in context.sections if s.name == "execution.baseline")
        assert not section.truncated
        assert parse_execution_baseline_context(section.content).binding == binding
    assert AgentResult.validate_current_output is original_result_validation
    assert vars(codex_cli)["validate_current_artifact_version"] is original_version
    assert DurableInvocationControl.completed is original_completed
    host.continue_execution_baseline(continue_command, project_id="project_test")
    assert len(calls) == 4
