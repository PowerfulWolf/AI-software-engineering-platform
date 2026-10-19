"""Public same-Task recovery of a stored legacy knowledge pause, then independent delivery."""

from __future__ import annotations

import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult, AgentRunStatus
from ai_software_engineer.agents.codex_cli import CodexCliAgentAdapter
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.agents.structured import StructuredModelError
from ai_software_engineer.context import ContextBundle
from ai_software_engineer.domain import AgentDefinition, AgentRole, Artifact, CoderProgressArtifact
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.enums import TaskStatus, TeamRole, WorkItemStatus
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode, BaselinePurpose
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.knowledge.invocation import KnowledgeInvocationJournal
from ai_software_engineer.knowledge.models import (
    KnowledgeError,
    KnowledgeRunBinding,
    KnowledgeSnapshot,
)
from ai_software_engineer.knowledge.runtime import KnowledgeRunContextBuilder
from ai_software_engineer.manager import production_delivery
from ai_software_engineer.manager.baseline_production import (
    BaselineContinueCommand,
    BaselineExecuteCommand,
    BaselineProposeCommand,
)
from ai_software_engineer.manager.delivery import ApproveProductSpec, StartProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.legacy_containment import (
    LocalBootObservation,
    TrustedLocalBootObserver,
)
from ai_software_engineer.manager.legacy_local_execution import (
    LegacyLocalExecutionSurvey,
    TrustedLegacyLocalExecutionObserver,
)
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.store import MySqlTaskRepository
from tests.manager.test_production_backend import _git
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_production_continuation import _coder_draft
from tests.manager.test_production_continuation_v2 import _progress
from tests.manager.test_public_context_capacity_baseline import public_capacity_host


@pytest.mark.mysql
def test_public_legacy_knowledge_isolation_preserves_progress_and_consumes_ordinary_work(
    tmp_path: Path,
    mysql_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    preparation: list[AgentRequest] = []
    invoked: list[AgentRequest] = []
    host = public_capacity_host(
        tmp_path=tmp_path,
        repository=repository,
        mysql_dsn=mysql_dsn,
        monkeypatch=monkeypatch,
        preparation_requests=preparation,
        invoked=invoked,
        should_reject=lambda request: False,
    )
    native_adapter = cast(
        type[CodexCliAgentAdapter], vars(production_delivery)["CodexCliAgentAdapter"]
    )
    real_run = native_adapter.run
    first_progress: list[CoderProgressArtifact] = []
    worktrees: list[Path] = []
    independent_errors: list[str] = []

    def run(self: CodexCliAgentAdapter, request: AgentRequest) -> AgentResult:
        if request.role is not AgentRole.CODER:
            try:
                return real_run(self, request)
            except AssertionError:
                independent_errors.append(traceback.format_exc())
                raise
        invoked.append(request)
        worktrees.append(self._workspace_root)
        artifact: Artifact
        if not first_progress:
            (self._workspace_root / "hello.txt").write_text("retained partial greeting\n")
            artifact = _progress(self, request)
            assert isinstance(artifact, CoderProgressArtifact)
            first_progress.append(artifact)
        else:
            assert first_progress[0].artifact_id in request.input_artifact_ids
            assert (self._workspace_root / "hello.txt").read_text() == "retained partial greeting\n"
            (self._workspace_root / "hello.txt").write_text("hello from the team\n")
            artifact = _coder_draft(self, request)
            artifact = self._finalize_coder_candidate(request, request.source_revision, artifact)
        return AgentResult(
            task_id=request.task_id,
            run_id=request.run_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=AgentRunStatus.SUCCEEDED,
            artifact=artifact,
        )

    monkeypatch.setattr(native_adapter, "run", run)
    original_build = KnowledgeRunContextBuilder.build
    old_outcomes: list[Path] = []

    def build(
        self: KnowledgeRunContextBuilder,
        task: Task,
        agent: AgentDefinition,
        *,
        attempt: int,
        candidate_revision: str | None = None,
        input_artifacts: tuple[Artifact, ...] = (),
    ) -> ContextBundle:
        if agent.role is not AgentRole.CODER or attempt != 2:
            return original_build(
                self,
                task,
                agent,
                attempt=attempt,
                candidate_revision=candidate_revision,
                input_artifacts=input_artifacts,
            )
        base = self.delegate.build(
            task,
            agent,
            attempt=attempt,
            candidate_revision=candidate_revision,
            input_artifacts=input_artifacts,
        )
        requirement_id = task.id
        for source in self.sources:
            if source.uri.startswith("joint://"):
                requirement_id = source.uri.split("/")[2]
        frozen = KnowledgeSnapshot.create(
            team_id=self.team_id,
            project_id=self.project_id,
            requirement_id=requirement_id,
            repository_ids=(self.repository_id,),
        )
        self.records.put("snapshots", frozen.snapshot_sha256, frozen)
        bound = KnowledgeRunBinding(
            run_id="run_knowledge_" + digest((base.context_id, frozen.snapshot_sha256))[:32],
            task_id=task.id,
            role=TeamRole.CODER,
            team_id=self.team_id,
            project_id=self.project_id,
            requirement_id=requirement_id,
            repository_ids=(self.repository_id,),
            source_revision=base.source_revision,
            context_manifest_id=base.context_id,
            snapshot_sha256=frozen.snapshot_sha256,
        )

        class LegacyPausedClient:
            def complete(self, **kwargs: object) -> object:
                del kwargs
                raise StructuredModelError(
                    AgentErrorCode.SERVICE_PAUSED, "旧服务暂停了知识准备", transient=False
                )

        from ai_software_engineer.agents.structured import StructuredModelClient

        try:
            KnowledgeInvocationJournal(self.records, claimed=self.invocation_claim).call(
                bound,
                "intent",
                client=cast(StructuredModelClient, LegacyPausedClient()),
                instructions="Legacy knowledge fixture",
                input_payload={},
                output_schema={"type": "object"},
                timeout_seconds=2,
            )
        finally:
            old_outcomes.extend(self.records.root.glob("invocations/*/knowledge-invocation-*.json"))
        raise AssertionError("legacy knowledge preparation must fail")

    monkeypatch.setattr(KnowledgeRunContextBuilder, "build", build)
    boot = LocalBootObservation(
        machine_sha256="a" * 64,
        boot_session_sha256="b" * 64,
        booted_at=datetime.now(UTC) - timedelta(days=1),
    )
    monkeypatch.setattr(TrustedLocalBootObserver, "observe", lambda self: boot)
    observed_roots: list[Path] = []

    def survey(
        self: TrustedLegacyLocalExecutionObserver,
        *,
        worktree_root: Path,
        boot: LocalBootObservation,
    ) -> LegacyLocalExecutionSurvey:
        observed_roots.append(worktree_root)
        return LegacyLocalExecutionSurvey.create(
            worktree_path=str(worktree_root),
            machine_sha256=boot.machine_sha256,
            boot_session_sha256=boot.boot_session_sha256,
            account_sha256="c" * 64,
            observed_at=datetime.now(UTC),
            scanner_version="fixture-v1",
            blockers=(),
        )

    monkeypatch.setattr(TrustedLegacyLocalExecutionObserver, "observe", survey)
    entry = host.project_entry()
    product = entry.start(
        StartProjectDelivery(repository_root=str(repository), requirement="Update the greeting.")
    ).checkpoint
    checkpoint = entry.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="exact product fixture approval",
        )
    ).checkpoint
    assert checkpoint.task_id is not None
    with MySqlTaskRepository(mysql_dsn) as tasks:
        original = tasks.get(checkpoint.task_id)
        events = tasks.list_events(original.id)
        revision = tasks.current_revision(original.id)
        assert original.attempts == original.work_attempt == 2
        assert original.status is TaskStatus.IMPLEMENTING
        assert first_progress and len(invoked) == 1
        (current,) = tuple(
            item
            for item in host.work_queue.items_for_task(original.id)
            if item.status is not WorkItemStatus.CLOSED
        )
        assert current.wait_disposition is not None
        assert current.wait_disposition.facts.classification == "SERVICE_PAUSED"
        before = capture_mutation_inventory(worktrees[0])
        old_bytes = {p: p.read_bytes() for p in old_outcomes}
        plan = host.propose_execution_baseline(
            BaselineProposeCommand(
                delivery_id=checkpoint.delivery_id,
                task_id=original.id,
                expected_task_intent_sha256=task_intent_sha256(original),
                expected_task_revision=revision,
                expected_work_item_id=current.id,
                expected_source_revision=current.wait_disposition.facts.source_revision,
                purpose=BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION,
            ),
            project_id="project_test",
        )
        execute = BaselineExecuteCommand(
            delivery_id=checkpoint.delivery_id,
            task_id=original.id,
            expected_plan_sha256=plan.plan_sha256,
            continuation_mode=BaselineContinuationMode.PAUSE,
            confirm_current_knowledge_execution_isolated=True,
            reference="ENGINEERING current isolation, original transport stays UNKNOWN",
        )
        before_items = host.work_queue.items_for_task(original.id)
        for invalid in (
            execute.model_copy(update={"confirm_current_knowledge_execution_isolated": None}),
            execute.model_copy(update={"expected_plan_sha256": "e" * 64}),
        ):
            with pytest.raises((ValueError, KnowledgeError)):
                host.execute_execution_baseline(invalid, project_id="project_test")
            assert tasks.get(original.id) == original
            assert host.work_queue.items_for_task(original.id) == before_items
            assert capture_mutation_inventory(worktrees[0]) == before
        binding = host.execute_execution_baseline(
            execute,
            project_id="project_test",
        )
        assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
        updated = tasks.get(original.id)
        assert updated.attempts == updated.work_attempt == 3
        assert updated.retry_failures == original.retry_failures
        assert tasks.list_events(original.id) == events
        assert capture_mutation_inventory(worktrees[0]) == before
        assert all(path.read_bytes() == body for path, body in old_bytes.items())
        (paused,) = tuple(
            item
            for item in host.work_queue.items_for_task(original.id)
            if item.status is not WorkItemStatus.CLOSED
        )
        assert paused.id != current.id and paused.attempt == 3
        assert paused.wait_disposition is not None
        consumed_items = host.work_queue.items_for_task(original.id)
        assert host.execute_execution_baseline(execute, project_id="project_test") == binding
        assert tasks.get(original.id) == updated
        assert host.work_queue.items_for_task(original.id) == consumed_items
        host.continue_execution_baseline(
            BaselineContinueCommand(
                delivery_id=checkpoint.delivery_id,
                task_id=original.id,
                expected_task_intent_sha256=task_intent_sha256(updated),
                expected_task_revision=revision,
                expected_work_item_id=paused.id,
                expected_source_revision=binding.execution_source_revision,
                expected_execution_baseline_sha256=binding.binding_sha256,
                expected_disposition_sha256=paused.wait_disposition.disposition_sha256,
                reference="explicit resume after current isolation",
            ),
            project_id="project_test",
        )
        final = tasks.get(original.id)
        assert not independent_errors, independent_errors
        assert final.status is TaskStatus.DONE, [
            (i.role, i.wait_reason, i.wait_disposition)
            for i in host.work_queue.items_for_task(original.id)
        ]
        assert final.id == original.id and final.attempts == final.work_attempt == 3
        assert final.retry_failures == original.retry_failures
        assert entry.status(checkpoint.delivery_id).checkpoint.stage is DeliveryStage.DONE
        assert [r.role for r in invoked] == [
            AgentRole.CODER,
            AgentRole.CODER,
            AgentRole.QA,
            AgentRole.REVIEWER,
        ]
        assert worktrees[0] == worktrees[1]
        assert all(path.read_bytes() == body for path, body in old_bytes.items())
        accepted = host.work_queue.accepted(original.id)
        verification_runs = {
            r.run_id for r in invoked if r.role in {AgentRole.QA, AgentRole.REVIEWER}
        }
        verified = tuple(v for v in accepted if v.run_id in verification_runs)
        assert len(verified) == 2
        candidate = entry.status(checkpoint.delivery_id).checkpoint.candidate_revision
        assert candidate is not None and {v.source_revision for v in verified} == {candidate}
        assert set(observed_roots) == {repository, worktrees[0]}
        assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
