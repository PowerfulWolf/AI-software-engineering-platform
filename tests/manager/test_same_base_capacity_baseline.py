"""Public runtime-only capacity recovery preserves real stopped dirty Coder history."""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult
from ai_software_engineer.agents.codex_cli import (
    CodexCliAgentAdapter,
    CodexInvocationResult,
    SubprocessCodexCommandRunner,
)
from ai_software_engineer.agents.model_input import FinalModelInputCapacityExceeded
from ai_software_engineer.domain import (
    AgentRole,
    Artifact,
    Evidence,
    EvidenceType,
    QaReportArtifact,
    QaTestRun,
    QaTestStatus,
    ReviewReportArtifact,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode
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
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.manager.test_production_backend import _git, _git_output, _ScriptedDeliveryAdapter
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_production_continuation import Invocation, _coder_draft
from tests.manager.test_public_context_capacity_baseline import public_capacity_host
from tests.orchestration.test_runner import _definitions

_DESIRED = "hello from the team\n"


def _independent_report(
    adapter: CodexCliAgentAdapter, request: AgentRequest, cwd: Path, evidence_root: Path
) -> Artifact:
    definition = _definitions()[request.role].model_copy(
        update={
            "id": adapter._agent_id,
            "version": adapter._agent_version,
            "permissions": request.permissions,
            "timeout_seconds": request.timeout_seconds,
        }
    )
    artifact = _ScriptedDeliveryAdapter(definition, cwd).run(request).artifact
    assert isinstance(artifact, (QaReportArtifact, ReviewReportArtifact))
    command = ("git", "show", f"{request.source_revision}:hello.txt")
    observed = SubprocessCommandExecutor(
        cwd, request.permissions, execution_guard=adapter._execution_guard
    ).run(command, timeout_seconds=5)
    assert observed.returncode == 0 and observed.stdout == _DESIRED
    path = evidence_root / f"verification-{request.run_id}.json"
    path.write_text(observed.model_dump_json())
    evidence = Evidence(
        evidence_id=f"ev_{request.run_id.removeprefix('run_')}",
        type=EvidenceType.TEST if request.role is AgentRole.QA else EvidenceType.COMMAND,
        uri=path.as_uri(),
        description="Independent role inspected the exact committed candidate greeting.",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    if isinstance(artifact, QaReportArtifact):
        qa_content = artifact.content.model_copy(
            update={
                "criteria_results": tuple(
                    value.model_copy(update={"evidence_ids": (evidence.evidence_id,)})
                    for value in artifact.content.criteria_results
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
        )
    else:
        return artifact.model_copy(
            update={
                "evidence": (evidence,),
                "content": artifact.content.model_copy(
                    update={"evidence": (evidence.evidence_id,)}
                ),
            }
        )
    return artifact.model_copy(update={"evidence": (evidence,), "content": qa_content})


@dataclass
class _InputCapacity:
    blocked: bool = True


@pytest.mark.mysql
@pytest.mark.parametrize("purpose", ["context_capacity_resume", "source_rebind"])
def test_public_same_base_capacity_pause_resume_keeps_attempt3_native_draft(
    tmp_path: Path,
    mysql_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    purpose: Literal["context_capacity_resume", "source_rebind"],
) -> None:
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    source = _git_output("rev-parse", "HEAD", cwd=repository)
    prepared: list[AgentRequest] = []
    invoked: list[AgentRequest] = []
    calls: list[Invocation] = []
    capacity = _InputCapacity()
    host = public_capacity_host(
        tmp_path=tmp_path,
        repository=repository,
        mysql_dsn=mysql_dsn,
        monkeypatch=monkeypatch,
        preparation_requests=prepared,
        invoked=invoked,
        should_reject=lambda _: False,
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
            if request.role is AgentRole.CODER and request.attempt < 3:
                assert isinstance(adapter._interruption_control, NativeCoderContinuation)
                if request.attempt == 2:
                    assert (cwd / "hello.txt").read_text() == "partial-1\n"
                outcome = SubprocessCodexCommandRunner(guard).run(
                    (
                        sys.executable,
                        "-c",
                        "from pathlib import Path; import sys,time; sys.stdin.read(); "
                        f"Path('hello.txt').write_text('partial-{request.attempt}\\n'); "
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
            if request.role is AgentRole.CODER:
                assert request.attempt == 3 and request.execution_baseline_sha256 is not None
                assert (cwd / "hello.txt").read_text() == "partial-2\n"
                (cwd / "hello.txt").write_text(_DESIRED)
                artifact = _coder_draft(adapter, request)
            else:
                artifact = _independent_report(adapter, request, cwd, tmp_path)
            output = Path(argv[argv.index("--output-last-message") + 1])
            output.write_text(artifact.model_dump_json())
            return CodexInvocationResult(returncode=0)

    class NativeThenCapacity(CodexCliAgentAdapter):
        def prepare_input(self, request: AgentRequest) -> None:
            prepared.append(request)
            if request.role is AgentRole.CODER and request.attempt == 3 and capacity.blocked:
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

    monkeypatch.setattr(production_delivery, "CodexCliAgentAdapter", NativeThenCapacity)
    entry = host.project_entry()
    product = entry.start(
        StartProjectDelivery(repository_root=str(repository), requirement="Update the greeting.")
    ).checkpoint
    checkpoint = entry.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="exact-product",
        )
    ).checkpoint
    assert checkpoint.task_id is not None and checkpoint.repository_id is not None
    assert checkpoint.stage is DeliveryStage.DELIVERING
    assert [request.attempt for request in invoked] == [1, 2]
    assert [request.attempt for request in prepared] == [1, 2, 3]
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    sidecar = host.projects()[0].root / "repositories" / checkpoint.repository_id
    native = FileContinuationStore(
        sidecar / "state/continuations" / checkpoint.task_id, task_id=checkpoint.task_id
    )
    native_receipts = native.receipts_for_task(checkpoint.task_id)
    assert len(native_receipts) == 2
    assert {receipt.request.attempt for receipt in native_receipts} == {1, 2}
    (waiting,) = tuple(
        item
        for item in host.work_queue.items_for_task(checkpoint.task_id)
        if item.status is not WorkItemStatus.CLOSED
    )
    assert waiting.attempt == 3 and waiting.status is WorkItemStatus.WAITING_DEPENDENCY
    assert waiting.wait_disposition is not None
    assert waiting.wait_disposition.facts.classification == "CONTEXT_CAPACITY"
    records = KnowledgeRecordStore(sidecar / "state/delivery-preflight", read_only=True)
    (receipt,) = records.list("context-capacity-receipts", ContextCapacityReceipt)
    assert receipt.work_item_id == waiting.id and receipt.attempt == 3
    assert receipt.source_revision == source and receipt.request == prepared[-1]
    worktree, branch = calls[0].workspace, calls[0].branch
    assert {call.workspace for call in calls} == {worktree}
    assert (worktree / "hello.txt").read_text() == "partial-2\n"
    before = capture_mutation_inventory(worktree)
    frozen_bytes = {
        path: path.read_bytes()
        for root in (
            sidecar / "state/continuations" / checkpoint.task_id,
            sidecar / "state/delivery-preflight",
        )
        for path in root.glob("*.json")
    }
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        original = tasks.get(checkpoint.task_id)
        events = tasks.list_events(original.id)
        revision = tasks.current_revision(original.id)
    assert original.status is TaskStatus.IMPLEMENTING and original.attempts == 3
    failures = original.retry_failures
    proposal = BaselineProposeCommand.model_validate(
        {
            "purpose": purpose,
            "delivery_id": checkpoint.delivery_id,
            "task_id": original.id,
            "expected_task_intent_sha256": task_intent_sha256(original),
            "expected_task_revision": revision,
            "expected_work_item_id": waiting.id,
            "expected_source_revision": source,
            **({"target_base_ref": source} if purpose == "source_rebind" else {}),
            "input_mode": "preserve_draft",
        }
    )
    if purpose == "source_rebind":
        with pytest.raises(ValueError, match="代码基线更新必须选择不同"):
            host.propose_execution_baseline(proposal, project_id="project_test")
        assert host.work_queue.get(waiting.id) == waiting
        assert capture_mutation_inventory(worktree) == before and len(invoked) == 2
        assert all(path.read_bytes() == body for path, body in frozen_bytes.items())
        return
    plan = host.propose_execution_baseline(proposal, project_id="project_test")
    assert not plan.conflicted and plan.prepared_source_revision == source
    assert plan.facts.context_capacity_receipt_sha256 == receipt.receipt_sha256
    assert plan.facts.native_rule_change is None
    reservation = plan.facts.continuation
    assert reservation is not None and reservation.retry_cause == "uninvoked"
    assert reservation.current_attempt == reservation.next_execution_attempt == 3
    assert reservation.reservation_already_applied and reservation.retry_failure is None
    binding = host.execute_execution_baseline(
        BaselineExecuteCommand(
            delivery_id=checkpoint.delivery_id,
            task_id=original.id,
            expected_plan_sha256=plan.plan_sha256,
            continuation_mode=BaselineContinuationMode.PAUSE,
            reference="exact-runtime-input-repair-pause",
        ),
        project_id="project_test",
    )
    assert binding.to_wire()["context_capacity_receipt_sha256"] == receipt.receipt_sha256
    assert binding.before_inventory_sha256 == binding.after_inventory_sha256 == before.sha256
    assert binding.execution_base_ref == binding.execution_source_revision == source
    assert binding.approved_base_ref == original.base_ref == source
    assert binding.worktree_path == str(worktree) and binding.branch_name == branch
    assert {item.receipt_sha256 for item in native_receipts}.issubset(
        binding.resolved_interruption_receipt_sha256s
    )
    paused = host.work_queue.get(waiting.id)
    assert paused.status is WorkItemStatus.WAITING_HUMAN and paused.attempt == 3
    assert paused.wait_disposition is not None
    assert paused.wait_disposition.facts.classification == "EXECUTION_BASELINE_PAUSED"
    assert capture_mutation_inventory(worktree) == before and len(invoked) == 2
    assert all(path.read_bytes() == body for path, body in frozen_bytes.items())
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        assert tasks.get(original.id) == original
        assert tasks.list_events(original.id) == events
    capacity.blocked = False
    host.continue_execution_baseline(
        BaselineContinueCommand(
            delivery_id=checkpoint.delivery_id,
            task_id=original.id,
            expected_task_intent_sha256=task_intent_sha256(original),
            expected_task_revision=revision,
            expected_work_item_id=paused.id,
            expected_source_revision=source,
            expected_execution_baseline_sha256=binding.binding_sha256,
            expected_disposition_sha256=paused.wait_disposition.disposition_sha256,
            reference="explicit-runtime-input-repair-resume",
        ),
        project_id="project_test",
    )
    delivered = entry.status(checkpoint.delivery_id).checkpoint
    assert delivered.stage is DeliveryStage.DONE and delivered.task_id == original.id
    assert [request.role for request in invoked] == [
        AgentRole.CODER,
        AgentRole.CODER,
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]
    assert {call.workspace for call in calls if call.request.role is AgentRole.CODER} == {worktree}
    assert {call.branch for call in calls if call.request.role is AgentRole.CODER} == {branch}
    assert len({call.claim.assignment.agent_id for call in calls}) == 3
    assert len({call.claim.lease.id for call in calls}) == len(calls)
    assert len({call.request.run_id for call in calls}) == len(calls)
    assert len({call.request.source_revision for call in calls[-2:]}) == 1
    assert all(path.read_bytes() == body for path, body in frozen_bytes.items())
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        completed = tasks.get(original.id)
    assert completed.status is TaskStatus.DONE and completed.attempts == 3
    assert completed.base_ref == original.base_ref and completed.retry_failures == failures
    assert (repository / "hello.txt").read_text() == "hello\n"
