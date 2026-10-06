"""Public Host baseline updates preserve one Task and independent native delivery."""

from __future__ import annotations

import hashlib
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
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
    StructuredModelResult,
)
from ai_software_engineer.agents.codex_cli import (
    CodexCliAgentAdapter,
    CodexInvocationResult,
    SubprocessCodexCommandRunner,
)
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.context.execution_baseline import ExecutionBaselineContext
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
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal, OperatorDuty
from ai_software_engineer.domain.execution_baseline import BaselineInputMode
from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy, StageRetryPolicy
from ai_software_engineer.execution import SubprocessCommandExecutor
from ai_software_engineer.git import WorkspacePolicy, WorkspacePolicyError
from ai_software_engineer.git.baseline import BaselineGitConflict
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager import production_backend, production_delivery
from ai_software_engineer.manager.baseline_production import (
    BaselineExecuteCommand,
    BaselineProposeCommand,
    BaselineQuiescenceProof,
)
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.delivery import ApproveProductSpec, StartProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.baseline import consumptions
from ai_software_engineer.work_queue.dispatcher import (
    DispatcherLoop,
    DispatcherTickResult,
    DispatcherTickStatus,
)
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
@pytest.mark.parametrize(
    ("mode", "reject_after_baseline"),
    [
        (BaselineInputMode.PRESERVE_DRAFT, False),
        (BaselineInputMode.CODER_REAPPLY, False),
        (BaselineInputMode.PRESERVE_DRAFT, True),
    ],
)
def test_public_baseline_updates_original_workspace_then_completes_independent_delivery(
    tmp_path: Path,
    mysql_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    mode: BaselineInputMode,
    reject_after_baseline: bool,
) -> None:
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    approved_source = _git_output("rev-parse", "HEAD", cwd=repository)
    calls: list[Invocation] = []
    results: list[AgentResult] = []
    fixture_errors: list[str] = []
    paused = True
    expected_binding: str | None = None
    execution_base: str | None = None
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
                    "checklist": [
                        "Read the exact candidate greeting and compare the approved format."
                    ],
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
            adapter, request = self.adapter, self.request
            guard = cast(WorkerExecutionGuard, adapter._execution_guard)
            guard.check()
            assert guard.lease is not None
            claim = guard.lease.claim
            assert claim.work_item.role is request.role
            assert claim.work_item.attempt == request.attempt
            assert claim.work_item.task_id == request.task_id
            calls.append(
                Invocation(
                    request,
                    claim,
                    cwd,
                    _git_output("branch", "--show-current", cwd=cwd),
                    _git_output("rev-parse", "HEAD", cwd=cwd),
                    adapter._model,
                )
            )
            assert calls[-1].input_head == request.source_revision
            policy = WorkspacePolicy(cwd, request.permissions)
            if request.role is AgentRole.CODER and len(calls) == 1:
                assert request.execution_baseline_sha256 is None
                assert isinstance(adapter._interruption_control, NativeCoderContinuation)
                outcome = SubprocessCodexCommandRunner(guard).run(
                    (
                        sys.executable,
                        "-c",
                        "from pathlib import Path; import sys,time; "
                        "sys.stdin.read(); Path('hello.txt').write_text('retained draft\\n'); "
                        "time.sleep(30)",
                    ),
                    cwd=cwd,
                    environment=environment,
                    stdin=stdin,
                    timeout_seconds=min(timeout_seconds, 0.5),
                )
                assert outcome.timed_out and outcome.process_stop is not None
                outcome.process_stop.validate_integrity()
                with pytest.raises(ProcessLookupError):
                    os.killpg(outcome.process_stop.group_id, 0)
                return outcome

            assert request.execution_baseline_sha256 == expected_binding
            assert request.execution_base_ref == execution_base
            assert "complete_patch" in stdin and "+retained draft" in stdin
            context = FileContextStore(sidecar / "contexts").get(request.context_manifest_id)
            (section,) = tuple(s for s in context.sections if s.name == "execution.baseline")
            assert not section.truncated
            trusted = ExecutionBaselineContext.model_validate_json(section.content)
            assert trusted.binding.binding_sha256 == expected_binding
            assert trusted.binding.execution_base_ref == execution_base
            assert (
                hashlib.sha256(trusted.complete_patch.encode()).hexdigest()
                == trusted.binding.retained_patch.sha256
            )
            assert trusted.complete_patch.endswith("+retained draft\n")
            assert (cwd / "tooling.txt").read_text() == "fixed platform baseline\n"
            if request.role is AgentRole.CODER:
                policy.authorize_write("hello.txt")
                with pytest.raises(WorkspacePolicyError):
                    policy.authorize_write(".trellis/spec/core/forbidden.md")
                prior = (
                    "retained draft\n"
                    if mode is BaselineInputMode.PRESERVE_DRAFT
                    else "upstream greeting\n"
                )
                assert (cwd / "hello.txt").read_text() == prior
                (cwd / "hello.txt").write_text(DESIRED)
                artifact = _coder_draft(adapter, request)
            else:
                assert request.role in (AgentRole.QA, AgentRole.REVIEWER)
                assert adapter._interruption_control is None
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
                observed = SubprocessCommandExecutor(
                    cwd, request.permissions, environment=environment, execution_guard=guard
                ).run(command, timeout_seconds=5)
                assert observed.returncode == 0 and observed.stdout == DESIRED
                evidence_path = tmp_path / f"verification-{request.run_id}.json"
                evidence_path.write_text(observed.model_dump_json())
                evidence = Evidence(
                    evidence_id=f"ev_{request.run_id.removeprefix('run_')}",
                    type=EvidenceType.TEST
                    if request.role is AgentRole.QA
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
                                            update={
                                                "evidence_ids": (evidence.evidence_id,),
                                            }
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
                                update={
                                    "evidence": (evidence.evidence_id,),
                                }
                            ),
                        }
                    )
            output = Path(argv[argv.index("--output-last-message") + 1])
            output.write_text(artifact.model_dump_json())
            return CodexInvocationResult(returncode=0)

    class ObservedCodex(CodexCliAgentAdapter):
        def run(self, request: AgentRequest) -> AgentResult:
            if (
                reject_after_baseline
                and expected_binding is not None
                and request.role is AgentRole.CODER
            ):
                guard = cast(WorkerExecutionGuard, self._execution_guard)
                guard.check()
                assert guard.lease is not None
                assert request.source_revision != approved_source
                result = AgentResult(
                    run_id=request.run_id,
                    task_id=request.task_id,
                    role=request.role,
                    attempt=request.attempt,
                    source_revision=request.source_revision,
                    context_manifest_id=request.context_manifest_id,
                    status=AgentRunStatus.FAILED,
                    error=AgentFailure(
                        code=AgentErrorCode.INVALID_OUTPUT,
                        message="Rejected structured draft",
                        transient=False,
                    ),
                )
                results.append(result)
                return result
            self._runner = Runner(self, request)
            try:
                result = super().run(request)
            except AssertionError as error:
                fixture_errors.append(str(error))
                raise
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
                provider="codex",
                model="gpt-primary",
                kind=ModelProviderKind.CODEX_CLI,
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
    original_tick = DispatcherLoop.tick

    def pause_successor(
        dispatcher: DispatcherLoop, *, now: datetime, work_item_id: str | None = None
    ) -> DispatcherTickResult:
        if paused and work_item_id is not None:
            item = dispatcher._queue.get(work_item_id)
            if item.role is AgentRole.CODER and item.attempt >= 2:
                return DispatcherTickResult(status=DispatcherTickStatus.IDLE, ticked_at=now)
        return original_tick(dispatcher, now=now, work_item_id=work_item_id)

    monkeypatch.setattr(DispatcherLoop, "tick", pause_successor)
    service = host.project_entry()
    product = service.start(
        StartProjectDelivery(
            repository_root=str(repository),
            requirement="Update the greeting.",
            title=f"Execution baseline {mode.value}",
        )
    ).checkpoint
    pending = service.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="exact-original-product-approval",
        )
    ).checkpoint
    assert pending.stage is DeliveryStage.DELIVERING, (
        pending.failure_code,
        pending.failure_summary,
    )
    assert pending.task_id is not None and pending.repository_id is not None
    assert len(calls) == 1 and calls[0].request.role is AgentRole.CODER
    original_worktree = calls[0].workspace
    original_branch = calls[0].branch
    assert original_worktree.name == "coder-attempt-01"
    sidecar = host.projects()[0].root / "repositories" / pending.repository_id
    artifacts = FileArtifactStore(sidecar / "artifacts", read_only=True)
    original_artifacts = artifacts.list_for_task(pending.task_id)
    preparation_bytes = {path: path.read_bytes() for path in (sidecar / "policy").rglob("*.json")}
    receipt_store = FileContinuationStore(
        sidecar / "state/continuations" / pending.task_id,
        task_id=pending.task_id,
    )
    (original_receipt,) = receipt_store.receipts_for_task(pending.task_id)
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        frozen_task = tasks.get(pending.task_id)
        frozen_revision = tasks.current_revision(pending.task_id)
    (current_item,) = tuple(
        item
        for item in host.work_queue.items_for_task(pending.task_id)
        if item.status is not WorkItemStatus.CLOSED
    )
    assert current_item.attempt == frozen_task.attempts == 2
    assert not host.work_queue.claims_for_work_item(current_item.id)
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))

    # A main checkout upgrade cannot rewrite the original preparation/product approval.
    (repository / "tooling.txt").write_text("fixed platform baseline\n")
    if mode is BaselineInputMode.CODER_REAPPLY:
        (repository / "hello.txt").write_text("upstream greeting\n")
    _git("add", "hello.txt", "tooling.txt", cwd=repository)
    _git("commit", "-m", "upgrade source baseline", cwd=repository)
    execution_base = _git_output("rev-parse", "HEAD", cwd=repository)
    command = BaselineProposeCommand(
        delivery_id=pending.delivery_id,
        task_id=frozen_task.id,
        expected_task_intent_sha256=task_intent_sha256(frozen_task),
        expected_task_revision=frozen_revision,
        expected_work_item_id=current_item.id,
        expected_source_revision=approved_source,
        target_base_ref=execution_base,
    )
    product_only = TeamHost(
        config=config,
        environment=environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=production_delivery.ConfiguredDeliveryRouteAdapterFactory(),
        operator_principal=LocalOperatorPrincipal(
            operator_id="operator:product-only",
            duties=(OperatorDuty.PRODUCT,),
        ),
    )
    with pytest.raises(ValueError, match="职责权限"):
        product_only.propose_execution_baseline(command, project_id="project_test")
    with pytest.raises(ValueError, match="事实已变化"):
        host.propose_execution_baseline(
            command.model_copy(
                update={
                    "expected_task_revision": frozen_revision + 1,
                }
            ),
            project_id="project_test",
        )

    # Newly added native rules also require an explicit scope/rule decision.
    (repository / "AGENTS.md").write_text("A changed native rule is not an engineering upgrade.\n")
    _git("add", "AGENTS.md", cwd=repository)
    _git("commit", "-m", "changed native rules", cwd=repository)
    unsafe_target = _git_output("rev-parse", "HEAD", cwd=repository)
    with pytest.raises(ValueError, match="原批准的项目规范"):
        host.propose_execution_baseline(
            command.model_copy(
                update={
                    "target_base_ref": unsafe_target,
                }
            ),
            project_id="project_test",
        )
    _git("reset", "--hard", execution_base, cwd=repository)

    preserve = host.propose_execution_baseline(command, project_id="project_test")
    if mode is BaselineInputMode.CODER_REAPPLY:
        assert preserve.conflicted
        with pytest.raises(BaselineGitConflict, match="new exact coder_reapply"):
            host.execute_execution_baseline(
                BaselineExecuteCommand(
                    delivery_id=pending.delivery_id,
                    task_id=frozen_task.id,
                    expected_plan_sha256=preserve.plan_sha256,
                    reference="refused-conflicted-plan",
                ),
                project_id="project_test",
            )
        plan = host.propose_execution_baseline(
            command.model_copy(
                update={
                    "input_mode": BaselineInputMode.CODER_REAPPLY,
                }
            ),
            project_id="project_test",
        )
        assert plan.plan_sha256 != preserve.plan_sha256 and not plan.conflicted
    else:
        assert not preserve.conflicted
        plan = preserve
    assert plan.complete_capture.patch.endswith("+retained draft\n")
    assert plan.dirty_capture.worktree_path == str(original_worktree)
    assert plan.complete_capture.base_revision == approved_source
    execute = BaselineExecuteCommand(
        delivery_id=pending.delivery_id,
        task_id=frozen_task.id,
        expected_plan_sha256=plan.plan_sha256,
        reference="exact-engineering-baseline-decision",
    )
    with pytest.raises(ValueError, match="职责权限"):
        product_only.execute_execution_baseline(execute, project_id="project_test")
    assert len(calls) == 1

    # A post-proposal edit invalidates the exact plan. Restoring exact bytes is safe replay.
    if mode is BaselineInputMode.PRESERVE_DRAFT:
        (original_worktree / "hello.txt").write_text("unapproved drift\n")
        with pytest.raises((ValueError, RuntimeError)):
            host.execute_execution_baseline(execute, project_id="project_test")
        assert len(calls) == 1
        (original_worktree / "hello.txt").write_text("retained draft\n")

    # Keep the native Supervisor paused while publication commits the same-item overlay.
    binding = host.execute_execution_baseline(execute, project_id="project_test")
    expected_binding = binding.binding_sha256
    assert binding.approved_base_ref == approved_source
    assert binding.execution_base_ref == execution_base
    assert binding.input_mode is mode
    assert binding.resolved_interruption_receipt_sha256s == (original_receipt.receipt_sha256,)
    assert _git_output("branch", "--show-current", cwd=original_worktree) == original_branch
    assert (
        _git_output("rev-parse", "HEAD", cwd=original_worktree) == binding.execution_source_revision
    )
    rebound_item = host.work_queue.get(current_item.id)
    assert rebound_item.status is WorkItemStatus.READY
    assert rebound_item.dispatch_sequence == current_item.dispatch_sequence + 1
    assert (
        host.work_queue.original_step(current_item.id).boundary.source_revision == approved_source
    )
    assert (
        host.work_queue.step(current_item.id).boundary.source_revision
        == binding.execution_source_revision
    )
    assert len(calls) == 1
    paused = False
    # The public idempotent action resumes the same queued Coder with a real new claim.
    assert host.execute_execution_baseline(execute, project_id="project_test") == binding
    delivered = service.status(pending.delivery_id).checkpoint
    if reject_after_baseline:
        from ai_software_engineer.domain.delivery_resolution import (
            DeliveryProofMissing,
            InspectDeliveryWait,
        )

        (waiting,) = tuple(
            item
            for item in host.work_queue.items_for_task(frozen_task.id)
            if item.status in (WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY)
        )
        assert waiting.wait_disposition is not None
        facts = waiting.wait_disposition.facts
        assert facts.source_revision == binding.execution_source_revision != approved_source
        proof = host.inspect_delivery_wait(
            InspectDeliveryWait(
                work_item_id=waiting.id,
                expected_disposition_sha256=waiting.wait_disposition.disposition_sha256,
                expected_task_intent_sha256=facts.task_intent_sha256,
                expected_source_revision=facts.source_revision,
                expected_checkpoint_sequence=facts.checkpoint_sequence,
            ),
            project_id="project_test",
            delivery_id=pending.delivery_id,
        )
        assert proof.source_revision == binding.execution_source_revision
        assert DeliveryProofMissing.OUTCOME_REJECTED in proof.missing
        assert not proof.permitted_resolutions
        with MySqlTaskRepository(mysql_dsn) as current_repository:
            investigation_task = current_repository.get(frozen_task.id)
        with pytest.raises(ValueError, match="baseline binding differs"):
            host._runtime("project_test").backend.inspect_delivery_wait_prerequisites(
                investigation_task.model_copy(update={"title": "unapproved intent"}),
                host.work_queue.step(waiting.id),
                delivered,
            )
        with MySqlTaskRepository(mysql_dsn) as current_repository:
            retained = current_repository.get(frozen_task.id)
        assert retained.base_ref == approved_source and retained.status is TaskStatus.IMPLEMENTING
        assert _git_output("branch", "--show-current", cwd=original_worktree) == original_branch
        return
    if delivered.stage is not DeliveryStage.DONE:
        pytest.fail(
            str(delivered.failure_summary) + " | fixture_errors=" + repr(fixture_errors),
            pytrace=False,
        )
    assert delivered.stage is DeliveryStage.DONE, (
        delivered.failure_code,
        delivered.failure_summary,
        [(r.role, r.error) for r in results],
        fixture_errors,
    )
    assert [call.request.role for call in calls] == [
        AgentRole.CODER,
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]
    candidate = delivered.candidate_revision
    assert candidate and candidate != approved_source and candidate != execution_base
    assert all(call.request.source_revision == candidate for call in calls[2:])
    coder_calls = calls[:2]
    assert {call.workspace for call in coder_calls} == {original_worktree}
    assert {call.branch for call in coder_calls} == {original_branch}
    assert len({call.claim.assignment.agent_id for call in calls}) == 3
    assert len({call.claim.lease.id for call in calls}) == len(calls)
    assert len({call.request.run_id for call in calls}) == len(calls)
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        completed_task = tasks.get(frozen_task.id)
    assert completed_task.status is TaskStatus.DONE
    assert completed_task.base_ref == frozen_task.base_ref == approved_source
    assert task_intent_sha256(completed_task) == task_intent_sha256(frozen_task)
    assert completed_task.attempts == completed_task.work_attempt == 2
    assert not completed_task.retry_failures
    assert delivered.preparation_sha256 == pending.preparation_sha256
    assert delivered.approval_sha256 == pending.approval_sha256
    assert all(path.read_bytes() == body for path, body in preparation_bytes.items())
    final_artifacts = artifacts.list_for_task(frozen_task.id)
    assert all(artifacts.get(artifact.artifact_id) == artifact for artifact in original_artifacts)
    (implementation,) = tuple(
        a for a in final_artifacts if isinstance(a, ImplementationReportArtifact)
    )
    (qa,) = tuple(a for a in final_artifacts if isinstance(a, QaReportArtifact))
    (review,) = tuple(a for a in final_artifacts if isinstance(a, ReviewReportArtifact))
    assert (
        implementation.content.commit_sha
        == qa.source_revision
        == review.source_revision
        == candidate
    )
    assert qa.content.status is QaReportStatus.PASS
    assert review.content.verdict is ReviewVerdict.APPROVE
    assert (
        _git_output("diff", "--name-only", execution_base, candidate, cwd=repository) == "hello.txt"
    )
    assert (
        _git_output("show", f"{candidate}:tooling.txt", cwd=repository) == "fixed platform baseline"
    )
    assert _git_output("rev-parse", "HEAD", cwd=repository) == execution_base
    assert not (repository / ".ase").exists()
    assert receipt_store.receipts_for_task(frozen_task.id) == (original_receipt,)
    assert all(result.status is AgentRunStatus.SUCCEEDED for result in results[1:])
    assert all(
        item.status is WorkItemStatus.CLOSED
        for item in host.work_queue.items_for_task(frozen_task.id)
    )
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    baseline_store = FileExecutionBaselineStore(
        sidecar / "state/execution-baselines" / frozen_task.id,
        read_only=True,
    )
    assert baseline_store.bindings_for_task(frozen_task.id) == (binding,)
    assert len(consumptions(host.work_queue, frozen_task.id)) == 1
    contexts = FileContextStore(sidecar / "contexts")
    for call in calls[1:]:
        context = contexts.get(call.request.context_manifest_id)
        assert any(s.name == "execution.baseline" and not s.truncated for s in context.sections)
    count = len(calls)
    assert host.execute_execution_baseline(execute, project_id="project_test") == binding
    assert len(calls) == count
    assert baseline_store.bindings_for_task(frozen_task.id) == (binding,)
    assert len(consumptions(host.work_queue, frozen_task.id)) == 1


@pytest.mark.mysql
@pytest.mark.parametrize(
    "scenario",
    ["baseline_updates", "changed_checkout", "missing_preparation", "corrupt_preparation"],
)
def test_public_repeated_preflight_waits_keep_exact_historical_sources_without_model_calls(
    tmp_path: Path,
    mysql_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    (repository / "pyproject.toml").write_text('[project]\nname="greeting"\nversion="0.1.0"\n')
    (repository / "tests").mkdir()
    (repository / "tests/test_greeting.py").write_text("def test_greeting():\n    assert True\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", "pyproject.toml", "tests/test_greeting.py", cwd=repository)
    _git("commit", "-m", "original", cwd=repository)
    approved_source = _git_output("rev-parse", "HEAD", cwd=repository)
    original_complete = _ScriptedStructuredClient.complete
    invoked: list[AgentRequest] = []

    def unavailable_verification(
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
        payload["acceptance_mappings"] = [
            {
                "acceptance_criterion_id": "ac_001_001",
                "verification_strategy": "Run exact test.",
                "test_levels": ["unit"],
                "verification_argv": ["pytest", "tests/test_greeting.py::test_greeting"],
                "controlled_capability_kind": "unregistered_greeting_executor_v1",
            }
        ]
        return StructuredModelResult(payload=payload, duration_ms=result.duration_ms)

    class UninvokedCodex(CodexCliAgentAdapter):
        def run(self, request: AgentRequest) -> AgentResult:
            invoked.append(request)
            raise AssertionError("preflight must stop before every delivery model call")

    monkeypatch.setattr(_ScriptedStructuredClient, "complete", unavailable_verification)
    monkeypatch.setattr(
        production_backend,
        "ConfiguredStructuredClientFactory",
        lambda *_: _ScriptedClientFactory(),
    )
    monkeypatch.setattr(production_delivery, "CodexCliAgentAdapter", UninvokedCodex)
    config = ProductionConfig(
        platform_root=str(tmp_path / "platform"),
        default_project_id="project_test",
        default_project_name="Test Project",
        live_model_execution=True,
        model_routes=(
            ProviderRouteConfig(
                provider="codex",
                model="gpt-primary",
                kind=ModelProviderKind.CODEX_CLI,
            ),
        ),
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
    entry = host.project_entry()
    product = entry.start(
        StartProjectDelivery(
            repository_root=str(repository),
            requirement="Update the greeting.",
            title="Preflight source history",
        )
    ).checkpoint
    checkpoint = entry.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="exact-preflight-product-approval",
        )
    ).checkpoint
    assert checkpoint.stage is DeliveryStage.DELIVERING
    assert checkpoint.task_id is not None
    (original_item,) = tuple(
        item
        for item in host.work_queue.items_for_task(checkpoint.task_id)
        if item.status is not WorkItemStatus.CLOSED
    )
    assert original_item.status is WorkItemStatus.WAITING_DEPENDENCY
    sidecar = host.projects()[0].root / "repositories" / checkpoint.repository_id
    if scenario != "baseline_updates":
        from ai_software_engineer.domain.delivery_resolution import (
            DeliveryProofMissing,
            InspectDeliveryWait,
        )
        from ai_software_engineer.manager.delivery_preflight import DeliveryPreflightReceipt
        from ai_software_engineer.manager.delivery_wait import DeliveryWaitRejected

        assert original_item.wait_disposition is not None
        facts = original_item.wait_disposition.facts
        command = InspectDeliveryWait(
            work_item_id=original_item.id,
            expected_disposition_sha256=original_item.wait_disposition.disposition_sha256,
            expected_task_intent_sha256=facts.task_intent_sha256,
            expected_source_revision=facts.source_revision,
            expected_checkpoint_sequence=facts.checkpoint_sequence,
        )
        with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
            original_task = tasks.get(checkpoint.task_id)
            original_events = tasks.list_events(original_task.id)
            original_revision = tasks.current_revision(original_task.id)
        frozen_records = {path: path.read_bytes() for path in (sidecar / "policy").rglob("*.json")}
        (repository / "hello.txt").write_text("upgraded platform\n")
        (repository / "AGENTS.md").write_text("New native rules need separate authorization.\n")
        _git("add", "hello.txt", "AGENTS.md", cwd=repository)
        _git("commit", "-m", "platform and native rules upgrade", cwd=repository)
        current_head = _git_output("rev-parse", "HEAD", cwd=repository)
        assert current_head != approved_source
        from ai_software_engineer.manager.store import (
            FileProjectPreparationStore,
            ProjectPreparationCorruption,
        )

        (preparation_path,) = tuple(
            path
            for path in (sidecar / "policy").rglob(
                f"project-preparation-{checkpoint.repository_id}.json"
            )
            if FileProjectPreparationStore(path.parent, read_only=True)
            .get(checkpoint.repository_id)
            .preparation_sha256
            == checkpoint.preparation_sha256
        )
        if scenario == "missing_preparation":
            preparation_path.unlink()
        elif scenario == "corrupt_preparation":
            preparation_path.write_text("{}")
        if scenario == "changed_checkout":
            investigation = host.inspect_delivery_wait(
                command, project_id="project_test", delivery_id=checkpoint.delivery_id
            )
            investigation.validate_integrity()
            assert investigation.source_revision == approved_source
            assert DeliveryProofMissing.PREREQUISITES_UNVERIFIED in investigation.missing
            assert not investigation.permitted_resolutions
            assert investigation.prerequisite_facts_sha256 is not None
            assert investigation.prerequisite_receipt_sha256 is not None
            records = KnowledgeRecordStore(sidecar / "state" / "delivery-waits", read_only=True)
            prerequisites = records.get(
                "wait-prerequisites",
                investigation.prerequisite_receipt_sha256,
                DeliveryPreflightReceipt,
            )
            assert prerequisites.source_revision == approved_source
            assert prerequisites.task_id == original_task.id
            assert prerequisites.status == "WAIT_ENGINEERING"
            assert all(path.read_bytes() == body for path, body in frozen_records.items())
            with pytest.raises(DeliveryWaitRejected):
                host.inspect_delivery_wait(
                    command.model_copy(update={"expected_source_revision": current_head}),
                    project_id="project_test",
                    delivery_id=checkpoint.delivery_id,
                )
        else:
            with pytest.raises((ValueError, ProjectPreparationCorruption)):
                host._runtime("project_test").backend.inspect_delivery_wait_prerequisites(
                    original_task, host.work_queue.step(original_item.id), checkpoint
                )
            assert not tuple(
                (sidecar / "state" / "delivery-waits").glob("wait-investigations-*.json")
            )
            if scenario == "missing_preparation":
                assert not preparation_path.exists()
            else:
                assert preparation_path.read_text() == "{}"
        with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
            assert tasks.get(original_task.id) == original_task
            assert tasks.list_events(original_task.id) == original_events
            assert tasks.current_revision(original_task.id) == original_revision
        assert host.work_queue.get(original_item.id) == original_item
        if scenario == "changed_checkout":
            assert entry.status(checkpoint.delivery_id).checkpoint == checkpoint
        assert _git_output("rev-parse", "HEAD", cwd=repository) == current_head
        assert not invoked
        return
    proof_records = KnowledgeRecordStore(
        sidecar / "state/execution-baselines" / checkpoint.task_id,
        read_only=True,
    )
    sources = [approved_source]
    bindings = []
    for ordinal in range(1, 4):
        (repository / "tooling.txt").write_text(f"platform baseline {ordinal}\n")
        _git("add", "tooling.txt", cwd=repository)
        _git("commit", "-m", f"source upgrade {ordinal}", cwd=repository)
        target = _git_output("rev-parse", "HEAD", cwd=repository)
        with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
            task = tasks.get(checkpoint.task_id)
            revision = tasks.current_revision(task.id)
        plan = host.propose_execution_baseline(
            BaselineProposeCommand(
                delivery_id=checkpoint.delivery_id,
                task_id=task.id,
                expected_task_intent_sha256=task_intent_sha256(task),
                expected_task_revision=revision,
                expected_work_item_id=original_item.id,
                expected_source_revision=sources[-1],
                target_base_ref=target,
            ),
            project_id="project_test",
        )
        proof = proof_records.get(
            "baseline-quiescence",
            plan.facts.quiescence_proof_sha256,
            BaselineQuiescenceProof,
        )
        (original_proof,) = proof.invocations
        assert original_proof.proof_kind == "claimed_preflight"
        assert len(original_proof.preflight_checkpoint_sha256s) == ordinal
        assert not plan.dirty_capture.patch and not plan.complete_capture.patch
        if ordinal == 3:
            break  # The third proposal proves both completed upgrades and all three old claims.
        binding = host.execute_execution_baseline(
            BaselineExecuteCommand(
                delivery_id=checkpoint.delivery_id,
                task_id=task.id,
                expected_plan_sha256=plan.plan_sha256,
                reference=f"exact-baseline-{ordinal}",
            ),
            project_id="project_test",
        )
        bindings.append(binding)
        sources.append(binding.execution_source_revision)
        current = host.work_queue.get(original_item.id)
        assert current.status is WorkItemStatus.WAITING_DEPENDENCY
        assert current.dispatch_sequence == ordinal
        assert (
            host.work_queue.step(current.id).boundary.source_revision
            == binding.execution_source_revision
        )
        assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
        assert not invoked
    claims = host.work_queue.claims_for_work_item(original_item.id)
    assert len(claims) == 3
    assert len({claim.lease.id for claim in claims}) == 3
    assert {
        host.work_queue.step_for_claim(claim).boundary.source_revision for claim in claims
    } == set(sources)
    assert (
        host.work_queue.original_step(original_item.id).boundary.source_revision == approved_source
    )
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        task = tasks.get(checkpoint.task_id)
    assert task.status is TaskStatus.IMPLEMENTING
    assert task.base_ref == approved_source and task.attempts == task.work_attempt == 1
    assert not task.retry_failures and not invoked
    assert len(consumptions(host.work_queue, task.id)) == 2
    stored = FileExecutionBaselineStore(
        sidecar / "state/execution-baselines" / task.id,
        read_only=True,
    )
    assert stored.bindings_for_task(task.id) == tuple(bindings)
    assert not (repository / ".ase").exists()
