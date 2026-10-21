"""Exact current draft acceptance does not invent a historical post-progress inventory."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.agents.models import AgentRequest, AgentResult, AgentRunStatus
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import AgentRole, Task, TaskStatus
from ai_software_engineer.domain.artifact import CoderProgressArtifact
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_resolution import RejectedKnowledgePreparationEvidence
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.knowledge.agents import KnowledgeConsultationService
from ai_software_engineer.knowledge.assessment_rejection import (
    KnowledgeAssessmentRejected,
    RejectedKnowledgeAssessment,
)
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationIntent,
    KnowledgeInvocationJournal,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.models import KnowledgeRunBinding, KnowledgeSnapshot, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.rejected_knowledge_draft import RejectedKnowledgeDraftAdmission
from ai_software_engineer.manager.rejected_knowledge_preparation import rejected_knowledge_evidence
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationScope,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.owned_sessions import OwnedSessionController
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome
from ai_software_engineer.work_queue.models import QueueArtifactReceipt, QueueClaim
from tests.agents.test_openai_compatible import _coder_request
from tests.domain.factories import make_coder_progress_artifact, make_plan_artifact, make_task
from tests.git.test_worktree import _create_fixture_repository, _git
from tests.knowledge.test_assessment_rejection import _native_executable
from tests.knowledge.test_invocation_native import _client
from tests.knowledge.test_retrieval_contract import document
from tests.manager.test_rejected_workspace_admission import _claim, _context, _Queue, _start


@dataclass
class CurrentDraftFixture:
    state: Path
    task: Task
    scope: EngineeringScope
    queue: _Queue
    artifacts: FileArtifactStore
    git: GitWorktreeManager
    worktree: Path
    claim: QueueClaim
    step: QueuedRoleStep
    observation: RejectedKnowledgeAssessment
    request: AgentRequest
    progress: CoderProgressArtifact

    def evidence(self) -> RejectedKnowledgePreparationEvidence:
        return rejected_knowledge_evidence(
            observation=self.observation,
            task=self.task,
            item=self.claim.work_item,
            step=self.step,
            scope=self.scope,
            state=self.state,
            route_root=self.state.parent / "runs/model-routes",
            queue=self.queue,
            artifacts=self.artifacts,
            git=self.git,
        )


def current_draft_fixture(
    tmp_path: Path,
    *,
    prepare_task: Callable[[Task, EngineeringScope], Task] | None = None,
    claim_factory: Callable[[Task, EngineeringScope, int, datetime], QueueClaim] | None = None,
    progress_published: Callable[[QueueClaim, CoderProgressArtifact, FileArtifactStore], None]
    | None = None,
    advance_task: Callable[[Task, CoderProgressArtifact], Task] | None = None,
) -> CurrentDraftFixture:
    """A real native completion, publication and later rejected knowledge preparation."""
    root = _create_fixture_repository(tmp_path)
    source = _git(root, "rev-parse", "HEAD")
    state = tmp_path / "sidecar/state"
    state.mkdir(parents=True)
    scope = EngineeringScope(
        team_id="team_current_draft",
        project_id="project_current_draft",
        repository_id="repository_current_draft",
        repository_root=str(root),
    )
    original = make_task()
    old_task = original.model_copy(
        update={
            "repository": str(root),
            "base_ref": source,
            "status": TaskStatus.IMPLEMENTING,
            "attempts": 1,
        }
    )
    if prepare_task is not None:
        old_task = prepare_task(old_task, scope)
    task = old_task.model_copy(update={"attempts": 2})
    create_claim = claim_factory or _claim
    old_claim = create_claim(old_task, scope, 1, datetime.now(UTC) - timedelta(minutes=1))
    git = GitWorktreeManager(root, tmp_path / "worktrees")
    tree = git.create(
        WorktreeSpec(task_id=task.id, role=AgentRole.CODER, attempt=1, source_revision=source)
    )
    template = _coder_request()
    permissions = template.permissions.model_copy(
        update={"read_paths": ("**",), "write_paths": ("src/**",)}
    )
    context = FileContextStore(state.parent / "contexts").put(
        _context(old_task, old_claim, source, permissions)
    )
    request = template.model_copy(
        update={
            "task_id": task.id,
            "run_id": "run_current_draft_progress",
            "attempt": 1,
            "source_revision": source,
            "context_manifest_id": context.context_id,
            "permissions": permissions,
            "execution_baseline_sha256": None,
            "execution_base_ref": None,
            "continuation_checkpoint_id": None,
            "continuation_changed_paths": (),
        }
    )
    at = datetime.now(UTC)
    start = _start(request, old_claim, at)
    (state / "continuations").mkdir()
    native = FileContinuationStore.initialize(state / "continuations" / task.id, task_id=task.id)
    captured = native.put_capture_start(
        ExecutionCaptureStart.create(
            scope=ContinuationScope(
                team_id=scope.team_id,
                project_id=scope.project_id,
                repository_id=scope.repository_id,
                requirement_id="delivery_current_draft",
                dispatch_sha256="1" * 64,
            ),
            request=request,
            claim=old_claim,
            task_intent_sha256=task_intent_sha256(task),
            task_revision=old_claim.work_item.checkpoint_sequence,
            policy_sha256="1" * 64,
            worktree_path=str(tree.path),
            inventory_before=capture_mutation_inventory(tree.path),
            started_at=at,
        )
    )
    # Own and stop a real process. This is not a fixture assertion that some old
    # production process terminated, and does not supply a post-progress inventory.
    process = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(0.1)"), start_new_session=True
    )
    controller = OwnedSessionController(process)
    process.wait(timeout=5)
    proof = controller.stop(timeout_seconds=1)
    stopped = NativeProcessStop.create(
        process_id=process.pid,
        group_id=process.pid,
        returncode=0,
        kind="completed",
        stopped_at=datetime.now(UTC),
        session_proof=proof,
    )
    native.put_capture_stop(
        ExecutionCaptureStop.create(
            task_id=task.id,
            run_id=request.run_id,
            capture_start_sha256=captured.start_sha256,
            process_stop=stopped,
            output_present=True,
        )
    )
    (tree.path / "src/app.py").write_text("VALUE = 2\n")
    template_progress = make_coder_progress_artifact()
    progress = seal_artifact(
        template_progress.model_copy(
            update={
                "source_revision": source,
                "context_manifest_id": context.context_id,
                "producer": template_progress.producer.model_copy(
                    update={
                        "agent_id": old_claim.assignment.agent_id,
                        "run_id": request.run_id,
                    }
                ),
                "content": template_progress.content.model_copy(
                    update={
                        "changed_files": (
                            template_progress.content.changed_files[0].model_copy(
                                update={"path": "src/app.py"}
                            ),
                        ),
                    }
                ),
            }
        ),
        validated_at=datetime.now(UTC),
    )
    assert isinstance(progress, CoderProgressArtifact)
    artifacts = FileArtifactStore(state.parent / "artifacts")
    artifacts.put(
        seal_artifact(
            make_plan_artifact().model_copy(
                update={"source_revision": source, "context_manifest_id": "ctx_" + "a" * 64}
            ),
            validated_at=at,
        )
    )
    artifacts.put(progress)
    result = AgentResult(
        run_id=request.run_id,
        task_id=task.id,
        role=AgentRole.CODER,
        attempt=1,
        source_revision=source,
        context_manifest_id=context.context_id,
        status=AgentRunStatus.SUCCEEDED,
        artifact=progress,
    )
    outcome = DeliveryInvocationOutcome(start=start, result=result, outcome_sha256="0" * 64)
    outcome = outcome.model_copy(
        update={
            "outcome_sha256": digest(outcome.model_dump(mode="json", exclude={"outcome_sha256"}))
        }
    )
    invocations = KnowledgeRecordStore(state / "invocations")
    invocations.put("invocation-starts", old_claim.work_item.id, start)
    invocations.put("invocation-outcomes", old_claim.work_item.id, outcome)
    publication = AcceptedRoleArtifact(
        task_id=task.id,
        work_item_id=old_claim.work_item.id,
        lease_id=old_claim.lease.id,
        dispatch_sequence=old_claim.work_item.dispatch_sequence,
        checkpoint_sequence=old_claim.work_item.checkpoint_sequence,
        run_id=request.run_id,
        context_manifest_id=context.context_id,
        source_revision=source,
        receipt=QueueArtifactReceipt(
            artifact_id=progress.artifact_id, sha256=progress.integrity.sha256
        ),
    )
    if progress_published is not None:
        progress_published(old_claim, progress, artifacts)
    if advance_task is not None:
        task = advance_task(old_task, progress)
    claim = create_claim(task, scope, 2, datetime.now(UTC))
    old_step = QueuedRoleStep(
        work_item=old_claim.work_item,
        allocation_sha256="1" * 64,
        boundary=RoleRunBoundary(
            task.id, AgentRole.CODER, 1, old_claim.work_item.checkpoint_sequence, source
        ),
    )
    step = QueuedRoleStep(
        work_item=claim.work_item,
        allocation_sha256="1" * 64,
        boundary=RoleRunBoundary(
            task.id, AgentRole.CODER, 2, claim.work_item.checkpoint_sequence, source
        ),
    )
    queue = _Queue(
        {old_claim.lease.id: old_claim, claim.lease.id: claim},
        {old_claim.work_item.id: old_step, claim.work_item.id: step},
        (publication,),
    )
    current_context = FileContextStore(state.parent / "contexts").put(
        _context(task, claim, source, permissions)
    )
    records = KnowledgeRecordStore(state.parent / "knowledge/runs")
    frozen = KnowledgeSnapshot.create(
        team_id=scope.team_id,
        project_id=scope.project_id,
        requirement_id=task.id,
        repository_ids=(scope.repository_id,),
        documents=(
            document().model_copy(
                update={"team_id": scope.team_id, "project_id": scope.project_id}
            ),
        ),
    )
    records.put("snapshots", frozen.snapshot_sha256, frozen)
    binding = KnowledgeRunBinding(
        run_id="run_knowledge_" + digest((current_context.context_id, frozen.snapshot_sha256))[:32],
        task_id=task.id,
        role=TeamRole.CODER,
        team_id=scope.team_id,
        project_id=scope.project_id,
        requirement_id=task.id,
        repository_ids=(scope.repository_id,),
        source_revision=source,
        context_manifest_id=current_context.context_id,
        snapshot_sha256=frozen.snapshot_sha256,
    )
    executable = _native_executable(tmp_path)
    executable.write_text(
        executable.read_text().replace(
            "Path('calls')", f"Path({str(tmp_path / 'knowledge-calls')!r})"
        )
    )
    with pytest.raises(KnowledgeAssessmentRejected) as rejected:
        KnowledgeConsultationService(
            _client(tree.path, executable, TeamRole.CODER),
            records,
            allow_repository_inspection=True,
            invocation_journal=KnowledgeInvocationJournal(records, claimed=lambda: claim),
        ).consult(
            binding,
            frozen,
            {"task": task.to_wire(), "context": current_context.to_wire()},
            timeout_seconds=5,
        )
    assert rejected.value.observation is not None
    return CurrentDraftFixture(
        state,
        task,
        scope,
        queue,
        artifacts,
        git,
        tree.path,
        claim,
        step,
        rejected.value.observation,
        request,
        progress,
    )


def test_exact_current_draft_can_be_proposed_without_historical_after_inventory(
    tmp_path: Path,
) -> None:
    f = current_draft_fixture(tmp_path)
    historical = {path: path.read_bytes() for path in f.state.rglob("*.json")}
    evidence = f.evidence()
    assert evidence.current_draft_sha256 is not None
    assert all(path.read_bytes() == data for path, data in historical.items())
    assert not (f.state / "execution-baselines").exists()
    assert _git(f.worktree, "rev-parse", "HEAD") == f.request.source_revision
    assert (f.worktree / "src/app.py").read_text() == "VALUE = 2\n"


def _successor(
    f: CurrentDraftFixture, evidence: RejectedKnowledgePreparationEvidence
) -> tuple[Task, QueueClaim, AgentRequest, RejectedKnowledgeDraftAdmission]:
    task = f.task.model_copy(update={"attempts": 3})
    claim = _claim(task, f.scope, 3, datetime.now(UTC))
    claim = claim.model_copy(
        update={
            "work_item": claim.work_item.model_copy(
                update={
                    "parent_work_item_id": f.claim.work_item.id,
                    "checkpoint_sequence": f.claim.work_item.checkpoint_sequence,
                }
            )
        }
    )
    request = f.request.model_copy(
        update={
            "attempt": 3,
            "run_id": "run_current_draft_successor",
            "context_manifest_id": "ctx_" + "b" * 64,
            "input_artifact_ids": (f.progress.artifact_id,),
            "continuation_checkpoint_id": f.progress.artifact_id,
            "continuation_changed_paths": ("src/app.py",),
        }
    )
    admission = RejectedKnowledgeDraftAdmission(
        state=f.state,
        git=f.git,
        task_reader=lambda: task,
        claim_reader=lambda: claim,
        retry_reader=lambda work_item_id: evidence,
    )
    return task, claim, request, admission


def test_exact_consumed_current_draft_is_rechecked_before_successor_provider(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.manager.rejected_knowledge_draft import read_current_draft

    f = current_draft_fixture(tmp_path)
    evidence = f.evidence()
    assert evidence.current_draft_sha256 is not None
    record = read_current_draft(f.state, evidence.current_draft_sha256)
    assert record.progress == f.progress
    assert record.capture_start.inventory_before != record.inventory
    assert record.task_snapshot_sha256 == digest(f.task.to_wire())
    _, claim, request, admission = _successor(f, evidence)
    admission.authorize(request, f.worktree)
    assert claim.lease.id != f.claim.lease.id
    assert request.run_id != f.observation.binding.run_id
    assert request.context_manifest_id != f.observation.binding.context_manifest_id


@pytest.mark.parametrize(
    "change",
    [
        "body",
        "mode",
        "index",
        "extra",
        "ignored",
        "source",
        "progress",
        "permissions",
        "run",
        "context",
        "decision",
    ],
)
def test_approved_current_draft_refuses_mutation_or_changed_successor_input(
    tmp_path: Path, change: str
) -> None:
    from ai_software_engineer.git.policy import WorkspacePolicyError
    from ai_software_engineer.orchestration.continuation_models import ContinuationRejected

    f = current_draft_fixture(tmp_path)
    evidence = f.evidence()
    _, _, request, admission = _successor(f, evidence)
    if change == "body":
        (f.worktree / "src/app.py").write_text("VALUE = 99\n")
    elif change == "mode":
        (f.worktree / "src/app.py").chmod(0o755)
    elif change == "index":
        _git(f.worktree, "add", "src/app.py")
    elif change == "extra":
        (f.worktree / "src/extra.py").write_text("EXTRA = True\n")
    elif change == "ignored":
        info = Path(_git(f.worktree, "rev-parse", "--git-common-dir")) / "info/exclude"
        with info.open("a") as stream:
            stream.write("\n.pytest_cache/\n")
        (f.worktree / ".pytest_cache").mkdir()
        (f.worktree / ".pytest_cache/new").write_text("unapproved cache\n")
    elif change == "source":
        request = request.model_copy(update={"source_revision": "f" * 40})
    elif change == "progress":
        request = request.model_copy(update={"continuation_checkpoint_id": "art_foreign_progress"})
    elif change == "permissions":
        request = request.model_copy(
            update={"permissions": request.permissions.model_copy(update={"write_paths": ("**",)})}
        )
    elif change == "run":
        request = request.model_copy(update={"run_id": f.observation.binding.run_id})
    elif change == "context":
        request = request.model_copy(
            update={"context_manifest_id": f.observation.binding.context_manifest_id}
        )
    elif change == "decision":
        admission.retry_reader = lambda identity: None
    with pytest.raises((ValueError, WorkspacePolicyError, ContinuationRejected)):
        admission.authorize(request, f.worktree)


@pytest.mark.parametrize("change", ["publication", "stop", "main_outcome"])
def test_current_observation_cannot_replace_missing_original_progress_facts(
    tmp_path: Path, change: str
) -> None:
    from ai_software_engineer.knowledge.models import KnowledgeError
    from ai_software_engineer.orchestration.continuation_models import ContinuationRejected

    f = current_draft_fixture(tmp_path)
    if change == "publication":
        f.queue.publications = ()
    elif change == "stop":
        (f.state / "continuations" / f.task.id / f"capture-stop-{f.request.run_id}.json").unlink()
    else:
        store = KnowledgeRecordStore(f.state / "invocations", read_only=True)
        (
            store.root / store._name("invocation-outcomes", f.queue.publications[0].work_item_id)
        ).unlink()
    with pytest.raises((ValueError, KnowledgeError, ContinuationRejected, FileNotFoundError)):
        f.evidence()


def test_additional_unknown_knowledge_intent_cannot_hide_behind_completed_semantic_rejection(
    tmp_path: Path,
) -> None:
    f = current_draft_fixture(tmp_path)
    bound = f.observation.binding
    lane = KnowledgeRecordStore(
        f.state.parent / "knowledge/runs/invocations" / invocation_lane_sha256(bound)
    )
    intent = lane.get(
        "knowledge-invocation-intents", bound.run_id + ":intent", KnowledgeInvocationIntent
    )
    unknown = KnowledgeInvocationIntent.create(
        **{
            **intent.model_dump(mode="python", exclude={"intent_sha256"}),
            "binding": bound.model_copy(update={"run_id": "run_knowledge_unresolved_extra"}),
            "created_at": datetime.now(UTC),
        }
    )
    lane.put("knowledge-invocation-intents", unknown.binding.run_id + ":intent", unknown)
    with pytest.raises(ValueError):
        f.evidence()
