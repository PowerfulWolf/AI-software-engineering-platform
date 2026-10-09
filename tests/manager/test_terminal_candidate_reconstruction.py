"""Restart reconstructs accepted candidates independently of execution input SHAs."""

from datetime import timedelta

import pytest

from ai_software_engineer.artifacts import ArtifactRef, seal_artifact
from ai_software_engineer.domain.artifact import (
    Artifact,
    CoderProgressArtifact,
    ImplementationReportArtifact,
)
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import TaskStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.execution_baseline import (
    BaselineInputMode,
    CoderExecutionInput,
    ExecutionBaselineBinding,
    RetainedExecutionPatch,
    resolve_coder_execution_input,
)
from ai_software_engineer.domain.retry_policy import DeliveryRetryFailure
from ai_software_engineer.domain.task import Task
from ai_software_engineer.manager.production_backend import _terminal_delivery_result
from ai_software_engineer.orchestration.retry import BlockedResult, RetryDeliveryResult
from tests.domain.factories import (
    NOW,
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
    make_review_artifact,
    make_state_event,
    make_task,
)


class _ReadOnlyRepository:
    def __init__(self, task: Task, events: tuple[StateEvent, ...]) -> None:
        self.task, self.events = task, events

    def get(self, task_id: str) -> Task:
        assert task_id == self.task.id
        return self.task

    def list_events(self, task_id: str) -> tuple[StateEvent, ...]:
        assert task_id == self.task.id
        return self.events

    def current_revision(self, task_id: str) -> int:
        assert task_id == self.task.id
        return len(self.events)

    def create(self, task: Task) -> None:
        raise AssertionError("reconstruction cannot create Task")

    def append_event(self, event: StateEvent) -> None:
        raise AssertionError("reconstruction cannot append StateEvent")

    def record_attempt(self, task_id: str, attempt: int) -> None:
        raise AssertionError("reconstruction cannot reserve execution")

    def record_retry_failure(self, task_id: str, failure: DeliveryRetryFailure) -> None:
        raise AssertionError("reconstruction cannot rewrite failure history")


class _AcceptedArtifacts:
    def __init__(self, artifacts: tuple[Artifact, ...]) -> None:
        self.artifacts = artifacts

    def get(self, artifact_id: str) -> Artifact:
        return next(artifact for artifact in self.artifacts if artifact.artifact_id == artifact_id)

    def list_for_task(self, task_id: str) -> tuple[Artifact, ...]:
        assert all(artifact.task_id == task_id for artifact in self.artifacts)
        return self.artifacts

    def put(self, artifact: Artifact) -> ArtifactRef:
        raise AssertionError("reconstruction cannot publish an artifact")


class _BaselineResolver:
    def __init__(
        self,
        binding: ExecutionBaselineBinding,
        *,
        history: tuple[ExecutionBaselineBinding, ...] = (),
    ) -> None:
        self.binding = binding
        self.history = history

    def current(
        self,
        task: Task,
        *,
        implementation: ImplementationReportArtifact | None,
        progress: CoderProgressArtifact | None,
    ) -> CoderExecutionInput:
        return resolve_coder_execution_input(
            task,
            implementation=implementation,
            progress=progress,
            baseline=self.binding,
            baseline_history=self.history,
        )

    def required_context(self, source: CoderExecutionInput) -> str | None:
        raise AssertionError("terminal reconstruction cannot build role Context")


def _repository(
    *, status: TaskStatus = TaskStatus.BLOCKED, candidate_checkpoint: bool = False
) -> _ReadOnlyRepository:
    task = make_task().model_copy(
        update={
            "base_ref": "a" * 40,
            "branch_name": "ai/feature/terminal-restart",
            "status": status,
            "attempts": 2,
        }
    )
    event = make_state_event(from_status=TaskStatus.IMPLEMENTING, to_status=status).model_copy(
        update={
            "reason": "BUDGET_EXHAUSTED: 工作额度已耗尽。",
            "source_revision": "d" * 40,
            "artifact_ids": ("art_plan_001",),
        }
    )
    events: tuple[StateEvent, ...] = (event,)
    if candidate_checkpoint:
        candidate = make_state_event(
            event_id="evt_candidate_checkpoint",
            from_status=TaskStatus.IMPLEMENTING,
            to_status=TaskStatus.QA,
        ).model_copy(
            update={
                "reason": "candidate_ready",
                "source_revision": "b" * 40,
                "artifact_ids": ("art_impl_001",),
            }
        )
        events = (candidate, event.model_copy(update={"from_status": TaskStatus.QA}))
    return _ReadOnlyRepository(task, events)


def _binding(task: Task) -> ExecutionBaselineBinding:
    return ExecutionBaselineBinding.create(
        scope=EngineeringScope(
            team_id="team_terminal",
            project_id="project_terminal",
            repository_id="repository_terminal",
            repository_root=task.repository,
        ),
        task_id=task.id,
        task_intent_sha256=task_intent_sha256(task),
        sequence=1,
        approved_base_ref=task.base_ref,
        branch_name=task.branch_name,
        worktree_path="/workspace/terminal-worktree",
        prior_execution_base_ref=task.base_ref,
        prior_source_revision="b" * 40,
        execution_base_ref="d" * 40,
        execution_source_revision="d" * 40,
        input_mode=BaselineInputMode.CODER_REAPPLY,
        superseded_implementation_artifact_id="art_impl_001",
        source_artifact_ids=("art_plan_001", "art_impl_001"),
        retained_patch=RetainedExecutionPatch(
            uri="baseline://full-patch", sha256="1" * 64, bytes=10
        ),
        authority_source="engineering_operator_decision",
        authority_sha256="2" * 64,
        plan_sha256="3" * 64,
        facts_sha256="4" * 64,
        prior_task_revision=1,
        before_inventory_sha256="5" * 64,
        after_inventory_sha256="6" * 64,
        completed_at=NOW,
    )


@pytest.mark.parametrize("status", [TaskStatus.BLOCKED, TaskStatus.FAILED])
def test_changed_execution_source_without_accepted_implementation_is_not_candidate(
    status: TaskStatus,
) -> None:
    repository = _repository(status=status)
    result = _terminal_delivery_result(
        repository, _AcceptedArtifacts((make_plan_artifact(),)), repository.task.id
    )
    assert isinstance(result, BlockedResult) and result.candidate_revision is None


@pytest.mark.parametrize("status", [TaskStatus.BLOCKED, TaskStatus.FAILED])
def test_accepted_implementation_before_candidate_checkpoint_survives_restart(
    status: TaskStatus,
) -> None:
    repository = _repository(status=status)
    artifacts = _AcceptedArtifacts(
        tuple(
            seal_artifact(artifact, validated_at=NOW)
            for artifact in (make_plan_artifact(), make_implementation_artifact())
        )
    )
    original_task, original_events = repository.task.to_wire(), repository.events
    result = _terminal_delivery_result(repository, artifacts, repository.task.id)
    assert isinstance(result, BlockedResult) and result.candidate_revision == "b" * 40
    assert "art_impl_001" in result.artifact_ids
    assert repository.task.to_wire() == original_task and repository.events == original_events
    assert _terminal_delivery_result(repository, artifacts, repository.task.id) == result


@pytest.mark.parametrize("new_candidate", [False, True])
def test_restart_excludes_baseline_superseded_candidate_and_keeps_new_candidate(
    new_candidate: bool,
) -> None:
    repository = _repository(candidate_checkpoint=True)
    implementation = make_implementation_artifact()
    artifacts: tuple[Artifact, ...] = (make_plan_artifact(), implementation)
    if new_candidate:
        next_implementation = implementation.model_copy(
            update={
                "artifact_id": "art_impl_a_new",
                "supersedes": implementation.artifact_id,
                "created_at": NOW - timedelta(days=100),
                "source_revision": "c" * 40,
                "content": implementation.content.model_copy(update={"commit_sha": "c" * 40}),
            }
        )
        artifacts += (next_implementation,)
    sealed = tuple(seal_artifact(artifact, validated_at=NOW) for artifact in reversed(artifacts))
    result = _terminal_delivery_result(
        repository,
        _AcceptedArtifacts(sealed),
        repository.task.id,
        coder_execution_inputs=_BaselineResolver(_binding(repository.task)),
    )
    assert isinstance(result, BlockedResult)
    assert result.candidate_revision == ("c" * 40 if new_candidate else None)
    assert "art_impl_001" in result.artifact_ids


@pytest.mark.parametrize("new_candidate", [False, True])
def test_restart_excludes_candidate_from_ancestor_binding_before_ordering(
    new_candidate: bool,
) -> None:
    repository = _repository(candidate_checkpoint=True)
    first = _binding(repository.task)
    second = ExecutionBaselineBinding.create(
        **{
            **first.model_dump(exclude={"binding_sha256"}),
            "sequence": 2,
            "previous_binding_sha256": first.binding_sha256,
            "prior_execution_base_ref": first.execution_base_ref,
            "prior_source_revision": first.execution_source_revision,
            "execution_base_ref": "e" * 40,
            "execution_source_revision": "e" * 40,
            "superseded_implementation_artifact_id": None,
        }
    )
    implementation = make_implementation_artifact()
    artifacts: tuple[Artifact, ...] = (make_plan_artifact(), implementation)
    if new_candidate:
        # A candidate after rebinding can have no ordinary supersedes edge to
        # the old accepted output. The verified binding supplies its exclusion.
        artifacts += (
            implementation.model_copy(
                update={
                    "artifact_id": "art_impl_post_rebind",
                    "source_revision": "f" * 40,
                    "content": implementation.content.model_copy(update={"commit_sha": "f" * 40}),
                }
            ),
        )
    sealed = tuple(seal_artifact(artifact, validated_at=NOW) for artifact in artifacts)
    result = _terminal_delivery_result(
        repository,
        _AcceptedArtifacts(sealed),
        repository.task.id,
        coder_execution_inputs=_BaselineResolver(second, history=(first, second)),
    )
    assert isinstance(result, BlockedResult)
    assert result.candidate_revision == ("f" * 40 if new_candidate else None)
    assert "art_impl_001" in result.artifact_ids


@pytest.mark.parametrize("fault", ["source", "coverage"])
def test_retained_candidate_rejects_changed_source_or_acceptance_mapping(fault: str) -> None:
    repository = _repository()
    artifact = make_implementation_artifact()
    artifact = artifact.model_copy(
        update={"source_revision": "f" * 40}
        if fault == "source"
        else {
            "content": artifact.content.model_copy(
                update={
                    "acceptance_mapping": tuple(
                        mapping.model_copy(update={"criterion_id": "ac_unapproved_01"})
                        for mapping in artifact.content.acceptance_mapping
                    )
                }
            )
        }
    )
    with pytest.raises(ValueError, match="invalid source or acceptance coverage"):
        _terminal_delivery_result(
            repository,
            _AcceptedArtifacts((seal_artifact(artifact, validated_at=NOW),)),
            repository.task.id,
        )


@pytest.mark.parametrize("drift", [False, True])
def test_done_still_requires_exact_independent_four_artifact_candidate_chain(drift: bool) -> None:
    repository = _repository(status=TaskStatus.DONE, candidate_checkpoint=True)
    artifacts: tuple[Artifact, ...] = (
        make_plan_artifact(),
        make_implementation_artifact(),
        make_qa_artifact(),
        make_review_artifact(),
    )
    artifacts = tuple(
        artifact.model_copy(update={"context_manifest_id": "ctx_" + f"{index:064x}"})
        for index, artifact in enumerate(artifacts, 1)
    )
    ids = tuple(artifact.artifact_id for artifact in artifacts)
    repository.events = (
        *repository.events[:-1],
        repository.events[-1].model_copy(update={"reason": "review_approved", "artifact_ids": ids}),
    )
    if drift:
        artifacts = (
            *artifacts[:2],
            make_qa_artifact().model_copy(update={"source_revision": "f" * 40}),
            artifacts[3],
        )
    store = _AcceptedArtifacts(
        tuple(seal_artifact(artifact, validated_at=NOW) for artifact in artifacts)
    )
    if drift:
        with pytest.raises(ValueError, match="artifact lineage is incomplete"):
            _terminal_delivery_result(repository, store, repository.task.id)
    else:
        result = _terminal_delivery_result(repository, store, repository.task.id)
        assert isinstance(result, RetryDeliveryResult) and result.candidate_revision == "b" * 40
        assert result.artifact_ids == ids
