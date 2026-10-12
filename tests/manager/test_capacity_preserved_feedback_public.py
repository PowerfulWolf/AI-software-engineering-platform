"""Accepted progress and actual QA findings survive public same-source capacity recovery."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult
from ai_software_engineer.agents.codex_cli import CodexCliAgentAdapter, CodexInvocationResult
from ai_software_engineer.agents.model_input import FinalModelInputCapacityExceeded
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import (
    AgentProducer,
    AgentRole,
    Artifact,
    ArtifactIntegrity,
    CoderProgressArtifact,
    CoderProgressContent,
    Evidence,
    EvidenceType,
    Finding,
    FindingSeverity,
    ImplementationReportArtifact,
    QaCriterionResult,
    QaCriterionStatus,
    QaReportArtifact,
    QaReportContent,
    QaReportStatus,
    ReviewReportArtifact,
    ReviewVerdict,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    BaselineInputMode,
    BaselinePurpose,
)
from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy, StageRetryPolicy
from ai_software_engineer.execution import SubprocessCommandExecutor
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager import production_delivery
from ai_software_engineer.manager.baseline_production import (
    BaselineContinueCommand,
    BaselineExecuteCommand,
    BaselineProposeCommand,
)
from ai_software_engineer.manager.context_capacity import ContextCapacityReceipt
from ai_software_engineer.manager.delivery import ApproveProductSpec, StartProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.manager.test_production_backend import _git, _git_output, _ScriptedClientFactory
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_production_continuation import Invocation, _coder_draft
from tests.manager.test_public_context_capacity_baseline import public_capacity_host
from tests.manager.test_same_base_capacity_baseline import _independent_report

_DESIRED = "hello from the team\n"
_BROKEN = "hello from the team"
_FINDING = "The committed greeting is missing its required final newline."


def _progress(adapter: CodexCliAgentAdapter, request: AgentRequest) -> CoderProgressArtifact:
    draft = _coder_draft(adapter, request)
    assert isinstance(draft, ImplementationReportArtifact) and request.work_slice is not None
    return CoderProgressArtifact.model_validate(
        {
            **draft.to_wire(),
            "kind": "coder-progress",
            "artifact_id": "art_progress_" + request.run_id.removeprefix("run_"),
            "content": CoderProgressContent(
                checkpoint_sequence=request.attempt,
                summary="Greeting draft saved; finish and verify it in the next execution.",
                changed_files=draft.content.changed_files,
                completed_step_ids=request.work_slice.completed_step_ids,
                remaining_step_ids=(
                    *request.work_slice.selected_step_ids,
                    *request.work_slice.later_step_ids,
                ),
                tests_run=(),
                next_actions=("Finish the greeting and return a complete candidate report.",),
            ).to_wire(),
        }
    )


def _failed_qa(
    adapter: CodexCliAgentAdapter, request: AgentRequest, cwd: Path, evidence_root: Path
) -> QaReportArtifact:
    observed = SubprocessCommandExecutor(
        cwd, request.permissions, execution_guard=adapter._execution_guard
    ).run(("git", "show", f"{request.source_revision}:hello.txt"), timeout_seconds=5)
    assert observed.returncode == 0 and observed.stdout == _BROKEN != _DESIRED
    path = evidence_root / f"qa-finding-{request.run_id}.json"
    path.write_text(observed.model_dump_json())
    evidence = Evidence(
        evidence_id="ev_" + request.run_id.removeprefix("run_"),
        type=EvidenceType.COMMAND,
        uri=path.as_uri(),
        description="Independent QA read the committed greeting and observed the missing newline.",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    return QaReportArtifact(
        artifact_id="art_qa_" + request.run_id.removeprefix("run_"),
        task_id=request.task_id,
        schema_version="v0.1",
        producer=AgentProducer(
            role=AgentRole.QA,
            agent_id=adapter._agent_id,
            agent_version=adapter._agent_version,
            run_id=request.run_id,
        ),
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        created_at=datetime.now(UTC),
        parent_artifact_ids=(request.input_artifact_ids[-1],),
        evidence=(evidence,),
        integrity=ArtifactIntegrity(sha256="0" * 64, validated=False),
        content=QaReportContent(
            status=QaReportStatus.FAIL,
            criteria_results=(
                QaCriterionResult(
                    criterion_id="ac_001_001",
                    status=QaCriterionStatus.FAIL,
                    evidence_ids=(evidence.evidence_id,),
                    notes=_FINDING,
                ),
            ),
            tests_run=(),
            findings=(
                Finding(
                    finding_id="finding_missing_final_newline",
                    severity=FindingSeverity.MAJOR,
                    message=_FINDING,
                    file="hello.txt",
                    line=1,
                    evidence_ids=(evidence.evidence_id,),
                    recommendation="Append the required newline and rerun independent inspection.",
                ),
            ),
        ),
    )


@pytest.mark.mysql
def test_public_capacity_recovery_preserves_accepted_progress_candidate_and_qa_finding(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    base = _git_output("rev-parse", "HEAD", cwd=repository)
    prepared: list[AgentRequest] = []
    invoked: list[AgentRequest] = []
    calls: list[Invocation] = []
    capacity_blocked = True
    prototype = public_capacity_host(
        tmp_path=tmp_path,
        repository=repository,
        mysql_dsn=mysql_dsn,
        monkeypatch=monkeypatch,
        preparation_requests=prepared,
        invoked=invoked,
        should_reject=lambda _: False,
    )
    # Freeze four ordinary work slots before this Task exists; never change a
    # running Task's allowance to make an acceptance or recovery pass.
    host = TeamHost(
        config=prototype._config.model_copy(
            update={
                "execution_retry_policy": ExecutionRetryPolicy(
                    coder=StageRetryPolicy(max_attempts=4)
                )
            }
        ),
        environment=prototype._environment,
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=production_delivery.ConfiguredDeliveryRouteAdapterFactory(),
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
            del environment, stdin, timeout_seconds
            adapter, request = self.adapter, self.request
            guard = cast(WorkerExecutionGuard, adapter._execution_guard)
            guard.check()
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
                (cwd / "hello.txt").write_text(_BROKEN if request.attempt <= 2 else _DESIRED)
                artifact = (
                    _progress(adapter, request)
                    if request.attempt in {1, 3}
                    else _coder_draft(adapter, request)
                )
                artifact = artifact.model_copy(
                    update={
                        "supersedes": (request.expected_supersedes_by_kind or {}).get(artifact.kind)
                    }
                )
            elif request.role is AgentRole.QA and request.attempt == 2:
                artifact = _failed_qa(adapter, request, cwd, tmp_path)
            else:
                artifact = _independent_report(adapter, request, cwd, tmp_path)
            Path(argv[argv.index("--output-last-message") + 1]).write_text(
                artifact.model_dump_json()
            )
            return CodexInvocationResult(returncode=0)

    class ProgressFindingThenCapacity(CodexCliAgentAdapter):
        def prepare_input(self, request: AgentRequest) -> None:
            prepared.append(request)
            if request.role is AgentRole.CODER and request.attempt == 4 and capacity_blocked:
                assert self._input_budget is not None
                maximum = self._input_budget._resolver.get_context(
                    request.context_manifest_id
                ).budget.max_input_tokens
                raise FinalModelInputCapacityExceeded(
                    estimated_input_tokens=maximum + 1, max_input_tokens=maximum
                )
            super().prepare_input(request)

        def run(self, request: AgentRequest) -> AgentResult:
            invoked.append(request)
            self._runner = Runner(self, request)
            return super().run(request)

    monkeypatch.setattr(production_delivery, "CodexCliAgentAdapter", ProgressFindingThenCapacity)
    entry = host.project_entry()
    product = entry.start(
        StartProjectDelivery(repository_root=str(repository), requirement="Update the greeting.")
    ).checkpoint
    checkpoint = entry.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="exact-product-with-four-work-slots",
        )
    ).checkpoint
    assert checkpoint.task_id is not None and checkpoint.repository_id is not None
    assert checkpoint.stage is DeliveryStage.DELIVERING
    assert [(request.role, request.attempt) for request in invoked] == [
        (AgentRole.CODER, 1),
        (AgentRole.CODER, 2),
        (AgentRole.QA, 2),
        (AgentRole.CODER, 3),
    ]
    sidecar = host.projects()[0].root / "repositories" / checkpoint.repository_id
    artifacts = FileArtifactStore(sidecar / "artifacts")
    history = artifacts.list_for_task(checkpoint.task_id)
    (progress,) = [
        value
        for value in history
        if isinstance(value, CoderProgressArtifact) and value.content.checkpoint_sequence == 3
    ]
    (candidate,) = [value for value in history if isinstance(value, ImplementationReportArtifact)]
    (qa,) = [value for value in history if isinstance(value, QaReportArtifact)]
    assert qa.content.status is QaReportStatus.FAIL and qa.content.findings[0].message == _FINDING
    assert qa.source_revision == candidate.content.commit_sha != base
    assert qa.artifact_id in progress.parent_artifact_ids
    original_publications = host.work_queue.accepted(checkpoint.task_id)
    assert {progress.artifact_id, candidate.artifact_id, qa.artifact_id} <= {
        value.receipt.artifact_id for value in original_publications
    }
    worktree, branch = calls[0].workspace, calls[0].branch
    assert (worktree / "hello.txt").read_text() == _DESIRED
    inventory = capture_mutation_inventory(worktree)
    frozen = {
        path: path.read_bytes()
        for root in (sidecar / "artifacts", sidecar / "contexts")
        for path in root.glob("*.json")
    }
    qa_evidence = tmp_path / f"qa-finding-{qa.producer.run_id}.json"
    frozen[qa_evidence] = qa_evidence.read_bytes()
    assert hashlib.sha256(frozen[qa_evidence]).hexdigest() == qa.evidence[0].sha256
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        original = tasks.get(checkpoint.task_id)
        events = tasks.list_events(original.id)
        revision = tasks.current_revision(original.id)
    assert original.status is TaskStatus.IMPLEMENTING and original.attempts == 4
    assert any(event.reason == "qa_failed_route_to_coder" for event in events)
    (waiting,) = [
        item
        for item in host.work_queue.items_for_task(original.id)
        if item.status is not WorkItemStatus.CLOSED
    ]
    assert (
        waiting.wait_disposition is not None
        and waiting.wait_disposition.facts.classification == "CONTEXT_CAPACITY"
    )
    (receipt,) = KnowledgeRecordStore(sidecar / "state/delivery-preflight", read_only=True).list(
        "context-capacity-receipts", ContextCapacityReceipt
    )
    assert (
        receipt.request == prepared[-1] and receipt.source_revision == candidate.content.commit_sha
    )
    proposal = BaselineProposeCommand(
        purpose=BaselinePurpose.CONTEXT_CAPACITY_RESUME,
        delivery_id=checkpoint.delivery_id,
        task_id=original.id,
        expected_task_intent_sha256=task_intent_sha256(original),
        expected_task_revision=revision,
        expected_work_item_id=waiting.id,
        expected_source_revision=receipt.source_revision,
        input_mode=BaselineInputMode.PRESERVE_DRAFT,
    )
    accepted = host.work_queue.accepted
    for fault in ("missing-candidate-receipt", "foreign-candidate-source"):
        # Change only a typed read port; original SQL, immutable model results and
        # accepted artifacts stay untouched. A legitimate historical candidate
        # may bridge input Context and output commit only through real acceptance.
        def altered_acceptance(
            task_id: str, *, fault: str = fault
        ) -> tuple[AcceptedRoleArtifact, ...]:
            publications = accepted(task_id)
            if task_id != original.id:
                return publications
            if fault == "missing-candidate-receipt":
                return tuple(
                    value
                    for value in publications
                    if value.receipt.artifact_id != candidate.artifact_id
                )
            return tuple(
                value.model_copy(update={"source_revision": "f" * 40})
                if value.receipt.artifact_id == candidate.artifact_id
                else value
                for value in publications
            )

        with monkeypatch.context() as patches:
            patches.setattr(host.work_queue, "accepted", altered_acceptance)
            with pytest.raises(ValueError):
                host.propose_execution_baseline(proposal, project_id="project_test")
        assert not tuple((sidecar / "state/execution-baselines" / original.id).glob("*.json"))
        assert host.work_queue.get(waiting.id) == waiting
        assert accepted(original.id) == original_publications
        assert capture_mutation_inventory(worktree) == inventory and len(invoked) == 4
        assert all(path.read_bytes() == body for path, body in frozen.items())
        with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
            assert tasks.get(original.id) == original
            assert tasks.list_events(original.id) == events
    plan = host.propose_execution_baseline(proposal, project_id="project_test")
    assert plan.facts.progress_artifact_id == progress.artifact_id
    assert plan.facts.implementation_artifact_id == candidate.artifact_id
    binding = host.execute_execution_baseline(
        BaselineExecuteCommand(
            delivery_id=checkpoint.delivery_id,
            task_id=original.id,
            expected_plan_sha256=plan.plan_sha256,
            continuation_mode=BaselineContinuationMode.PAUSE,
            reference="preserve-real-progress-and-qa-feedback",
        ),
        project_id="project_test",
    )
    assert binding.superseded_progress_artifact_id is None
    assert binding.superseded_implementation_artifact_id is None
    assert (
        binding.execution_base_ref == base
        and binding.execution_source_revision == candidate.content.commit_sha
    )
    assert capture_mutation_inventory(worktree) == inventory
    assert binding.before_inventory_sha256 == binding.after_inventory_sha256 == inventory.sha256
    assert len(invoked) == 4 and all(path.read_bytes() == body for path, body in frozen.items())
    assert host.work_queue.accepted(original.id) == original_publications
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        assert tasks.get(original.id) == original
        assert tasks.list_events(original.id) == events
    paused = host.work_queue.get(waiting.id)
    assert paused.status is WorkItemStatus.WAITING_HUMAN and paused.attempt == 4
    assert (
        paused.wait_disposition is not None
        and paused.wait_disposition.facts.classification == "EXECUTION_BASELINE_PAUSED"
    )
    capacity_blocked = False
    host.continue_execution_baseline(
        BaselineContinueCommand(
            delivery_id=checkpoint.delivery_id,
            task_id=original.id,
            expected_task_intent_sha256=task_intent_sha256(original),
            expected_task_revision=revision,
            expected_work_item_id=paused.id,
            expected_source_revision=binding.execution_source_revision,
            expected_execution_baseline_sha256=binding.binding_sha256,
            expected_disposition_sha256=paused.wait_disposition.disposition_sha256,
            reference="explicitly-continue-same-feedback-task",
        ),
        project_id="project_test",
    )
    delivered = entry.status(checkpoint.delivery_id).checkpoint
    assert delivered.stage is DeliveryStage.DONE and delivered.task_id == original.id
    resumed = next(
        call for call in calls if call.request.role is AgentRole.CODER and call.request.attempt == 4
    )
    assert resumed.workspace == worktree and resumed.branch == branch
    assert resumed.request.source_revision == candidate.content.commit_sha
    assert {progress.artifact_id, qa.artifact_id} <= set(resumed.request.input_artifact_ids)
    assert resumed.request.context_manifest_id != receipt.context_manifest_id
    context = FileContextStore(sidecar / "contexts").get(resumed.request.context_manifest_id)
    complete_input = "\n".join(section.content for section in context.sections)
    assert _FINDING in complete_input and progress.content.summary in complete_input
    assert qa.content.findings[0].evidence_ids[0] in complete_input
    assert any(
        section.name == "execution.baseline" and not section.truncated
        for section in context.sections
    )
    assert all(path.read_bytes() == body for path, body in frozen.items())
    final_artifacts = artifacts.list_for_task(original.id)
    (final_implementation,) = [
        value
        for value in final_artifacts
        if isinstance(value, ImplementationReportArtifact)
        and value.artifact_id != candidate.artifact_id
    ]
    (final_qa,) = [
        value
        for value in final_artifacts
        if isinstance(value, QaReportArtifact) and value.content.status is QaReportStatus.PASS
    ]
    (final_review,) = [
        value for value in final_artifacts if isinstance(value, ReviewReportArtifact)
    ]
    assert final_review.content.verdict is ReviewVerdict.APPROVE
    assert (
        final_implementation.content.commit_sha
        == final_qa.source_revision
        == final_review.source_revision
        != candidate.content.commit_sha
    )
    assert final_implementation.artifact_id in final_qa.parent_artifact_ids
    assert final_qa.artifact_id in final_review.parent_artifact_ids
    assert [(request.role, request.attempt) for request in invoked] == [
        (AgentRole.CODER, 1),
        (AgentRole.CODER, 2),
        (AgentRole.QA, 2),
        (AgentRole.CODER, 3),
        (AgentRole.CODER, 4),
        (AgentRole.QA, 4),
        (AgentRole.REVIEWER, 4),
    ]
    assert all(
        publication in host.work_queue.accepted(original.id)
        for publication in original_publications
    )
    assert len({call.claim.assignment.agent_id for call in calls}) == 3
    assert len({call.claim.lease.id for call in calls}) == len(calls)
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        completed = tasks.get(original.id)
    assert completed.status is TaskStatus.DONE and completed.attempts == 4
    assert (
        completed.retry_policy == original.retry_policy
        and completed.retry_failures == original.retry_failures
    )
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    assert (repository / "hello.txt").read_text() == "hello\n"
