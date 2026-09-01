"""Public-seam fixture delivery tests for the serial Orchestrator."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents import FakeAgentAdapter, FakeBehavior, FakeScenario
from ai_software_engineer.artifacts import ArtifactNotFound, FileArtifactStore, seal_artifact
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentPermissions,
    AgentRole,
    ArtifactKind,
    ImplementationReportArtifact,
    NetworkAccess,
    PlanArtifact,
    QaReportArtifact,
    QaReportStatus,
    ReviewReportArtifact,
    Task,
    TaskStatus,
)
from ai_software_engineer.orchestration import (
    AgentRunFailed,
    DeliveryContractViolation,
    FileRunContextBuilder,
    OrchestrationIdentityFactory,
    SerialOrchestrator,
    TaskNotRunnable,
    UnexpectedVerdict,
)
from ai_software_engineer.store import SqliteTaskRepository
from tests.domain.factories import (
    CANDIDATE_SHA,
    NOW,
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
    make_review_artifact,
    make_task,
)

DELIVERY_TIME = NOW + timedelta(days=1)
RUN_IDS = {
    AgentRole.ORCHESTRATOR: "run_orchestrator_001",
    AgentRole.CODER: "run_coder_001",
    AgentRole.QA: "run_qa_001",
    AgentRole.REVIEWER: "run_reviewer_001",
}
ROLE_INPUTS = {
    AgentRole.ORCHESTRATOR: (),
    AgentRole.CODER: (
        ArtifactKind.PLAN,
        ArtifactKind.QA_REPORT,
        ArtifactKind.REVIEW_REPORT,
    ),
    AgentRole.QA: (ArtifactKind.PLAN, ArtifactKind.IMPLEMENTATION_REPORT),
    AgentRole.REVIEWER: (
        ArtifactKind.PLAN,
        ArtifactKind.IMPLEMENTATION_REPORT,
        ArtifactKind.QA_REPORT,
    ),
}
ROLE_OUTPUT = {
    AgentRole.ORCHESTRATOR: ArtifactKind.PLAN,
    AgentRole.CODER: ArtifactKind.IMPLEMENTATION_REPORT,
    AgentRole.QA: ArtifactKind.QA_REPORT,
    AgentRole.REVIEWER: ArtifactKind.REVIEW_REPORT,
}


class FixedIdentityFactory(OrchestrationIdentityFactory):
    """Known independent IDs make the fake scenario reproducible."""

    def new_run_id(self, task_id: str, role: AgentRole, attempt: int) -> str:
        del task_id, attempt
        return RUN_IDS[role]

    def new_event_id(
        self,
        task_id: str,
        from_status: TaskStatus,
        to_status: TaskStatus,
        attempt: int,
    ) -> str:
        del task_id
        return f"evt_{from_status.value.lower()}_{to_status.value.lower()}_{attempt:02d}"


class DuplicateRunIdentityFactory(FixedIdentityFactory):
    def new_run_id(self, task_id: str, role: AgentRole, attempt: int) -> str:
        del task_id, role, attempt
        return RUN_IDS[AgentRole.ORCHESTRATOR]


def _clock() -> datetime:
    return DELIVERY_TIME


def _task(project_root: Path) -> Task:
    return make_task().model_copy(update={"repository": str(project_root)})


def _definitions() -> dict[AgentRole, AgentDefinition]:
    definitions: dict[AgentRole, AgentDefinition] = {}
    for role in AgentRole:
        definitions[role] = AgentDefinition(
            id=f"agent_{role.value}_001",
            role=role,
            version="v0.1",
            model=f"fake-{role.value}",
            provider="local",
            permissions=AgentPermissions(
                read_paths=("**",),
                write_paths=() if role is AgentRole.REVIEWER else ("**",),
                commands=("pytest",),
                network=NetworkAccess.NONE,
                can_change_state=role is AgentRole.ORCHESTRATOR,
            ),
            input_artifacts=ROLE_INPUTS[role],
            output_artifacts=(ROLE_OUTPUT[role],),
            max_retries=0,
            timeout_seconds=60,
            token_budget=4_000,
        )
    return definitions


def _successful_adapter(
    task: Task,
    definitions: dict[AgentRole, AgentDefinition],
    contexts: FileRunContextBuilder,
    *,
    plan_covers_criteria: bool = True,
    qa_behavior: FakeBehavior = FakeBehavior.SUCCESS,
) -> tuple[FakeAgentAdapter, tuple[str, ...]]:
    planning_task = task.model_copy(
        update={"status": TaskStatus.PLANNING, "updated_at": DELIVERY_TIME}
    )
    implementing_task = task.model_copy(
        update={"status": TaskStatus.IMPLEMENTING, "updated_at": DELIVERY_TIME}
    )
    qa_task = task.model_copy(update={"status": TaskStatus.QA, "updated_at": DELIVERY_TIME})
    review_task = task.model_copy(update={"status": TaskStatus.REVIEW, "updated_at": DELIVERY_TIME})
    plan_context = contexts.build(planning_task, definitions[AgentRole.ORCHESTRATOR], attempt=1)
    plan = make_plan_artifact().model_copy(
        update={
            "task_id": task.id,
            "source_revision": task.base_ref,
            "context_manifest_id": plan_context.context_id,
            "producer": make_plan_artifact().producer.model_copy(
                update={"run_id": RUN_IDS[AgentRole.ORCHESTRATOR]}
            ),
        }
    )
    if not plan_covers_criteria:
        plan = plan.model_copy(
            update={"content": plan.content.model_copy(update={"acceptance_mapping": ()})}
        )
    plan = cast(PlanArtifact, seal_artifact(plan, validated_at=DELIVERY_TIME))

    coder_context = contexts.build(
        implementing_task,
        definitions[AgentRole.CODER],
        attempt=1,
        input_artifacts=(plan,),
    )
    implementation = make_implementation_artifact().model_copy(
        update={
            "task_id": task.id,
            "context_manifest_id": coder_context.context_id,
            "parent_artifact_ids": (plan.artifact_id,),
            "producer": make_implementation_artifact().producer.model_copy(
                update={"run_id": RUN_IDS[AgentRole.CODER]}
            ),
        }
    )
    implementation = cast(
        ImplementationReportArtifact,
        seal_artifact(implementation, validated_at=DELIVERY_TIME),
    )

    qa_context = contexts.build(
        qa_task,
        definitions[AgentRole.QA],
        attempt=1,
        candidate_revision=CANDIDATE_SHA,
        input_artifacts=(plan, implementation),
    )
    qa = make_qa_artifact().model_copy(
        update={
            "task_id": task.id,
            "context_manifest_id": qa_context.context_id,
            "parent_artifact_ids": (implementation.artifact_id,),
            "producer": make_qa_artifact().producer.model_copy(
                update={"run_id": RUN_IDS[AgentRole.QA]}
            ),
        }
    )
    if qa_behavior is FakeBehavior.QA_FAIL:
        qa = qa.model_copy(
            update={"content": qa.content.model_copy(update={"status": QaReportStatus.FAIL})}
        )
    qa = cast(QaReportArtifact, seal_artifact(qa, validated_at=DELIVERY_TIME))

    review_context = contexts.build(
        review_task,
        definitions[AgentRole.REVIEWER],
        attempt=1,
        candidate_revision=CANDIDATE_SHA,
        input_artifacts=(plan, implementation, qa),
    )
    review = make_review_artifact().model_copy(
        update={
            "task_id": task.id,
            "context_manifest_id": review_context.context_id,
            "parent_artifact_ids": (qa.artifact_id,),
            "producer": make_review_artifact().producer.model_copy(
                update={"run_id": RUN_IDS[AgentRole.REVIEWER]}
            ),
        }
    )
    review = cast(
        ReviewReportArtifact,
        seal_artifact(review, validated_at=DELIVERY_TIME),
    )

    adapter = FakeAgentAdapter(
        scenarios={
            (AgentRole.ORCHESTRATOR, 1): FakeScenario(behavior=FakeBehavior.SUCCESS, artifact=plan),
            (AgentRole.CODER, 1): FakeScenario(
                behavior=FakeBehavior.SUCCESS, artifact=implementation
            ),
            (AgentRole.QA, 1): FakeScenario(behavior=qa_behavior, artifact=qa),
            (AgentRole.REVIEWER, 1): FakeScenario(behavior=FakeBehavior.SUCCESS, artifact=review),
        }
    )
    return adapter, (
        plan_context.context_id,
        coder_context.context_id,
        qa_context.context_id,
        review_context.context_id,
    )


def test_fixture_task_reaches_done_with_replayable_events_and_artifacts(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    task = _task(project_root)
    definitions = _definitions()
    contexts = FileRunContextBuilder(project_root)
    adapter, expected_context_ids = _successful_adapter(task, definitions, contexts)
    database = tmp_path / "state.sqlite3"
    artifacts = FileArtifactStore(tmp_path / "artifacts")

    with SqliteTaskRepository(database) as repository:
        repository.create(task)
        runner = SerialOrchestrator(
            repository=repository,
            artifact_store=artifacts,
            context_builder=contexts,
            agent_adapter=adapter,
            agent_definitions=definitions,
            identities=FixedIdentityFactory(),
            clock=_clock,
        )

        result = runner.run_task(task.id)
        events = repository.list_events(task.id)

        assert result.task.status is TaskStatus.DONE
        assert result.candidate_revision == CANDIDATE_SHA
        assert result.artifact_ids == (
            "art_plan_001",
            "art_impl_001",
            "art_qa_001",
            "art_review_001",
        )
        assert result.context_manifest_ids == expected_context_ids
        assert result.run_ids == tuple(RUN_IDS.values())
        assert repository.current_revision(task.id) == 5
        assert tuple(event.to_status for event in events) == (
            TaskStatus.PLANNING,
            TaskStatus.IMPLEMENTING,
            TaskStatus.QA,
            TaskStatus.REVIEW,
            TaskStatus.DONE,
        )
        assert events[-1].artifact_ids == result.artifact_ids
        assert all(event.actor is AgentRole.ORCHESTRATOR for event in events)

        persisted = tuple(artifacts.get(artifact_id) for artifact_id in result.artifact_ids)
        assert tuple(artifact.parent_artifact_ids for artifact in persisted) == (
            (),
            ("art_plan_001",),
            ("art_impl_001",),
            ("art_qa_001",),
        )
        assert len({artifact.producer.run_id for artifact in persisted}) == 4
        assert all(artifact.integrity.validated for artifact in persisted)

    with SqliteTaskRepository(database) as reopened:
        assert reopened.get(task.id).status is TaskStatus.DONE
        assert reopened.current_revision(task.id) == 5
        assert len(reopened.list_events(task.id)) == 5


def test_agent_failure_stops_at_the_current_checkpoint_without_an_artifact(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    task = _task(project_root)
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    with SqliteTaskRepository(tmp_path / "state.sqlite3") as repository:
        repository.create(task)
        runner = SerialOrchestrator(
            repository=repository,
            artifact_store=artifacts,
            context_builder=FileRunContextBuilder(project_root),
            agent_adapter=FakeAgentAdapter(default=FakeScenario(behavior=FakeBehavior.TIMEOUT)),
            agent_definitions=_definitions(),
            identities=FixedIdentityFactory(),
            clock=_clock,
        )

        with pytest.raises(AgentRunFailed) as captured:
            runner.run_task(task.id)

        assert captured.value.result.error is not None
        assert repository.get(task.id).status is TaskStatus.PLANNING
        assert repository.current_revision(task.id) == 1
        with pytest.raises(ArtifactNotFound):
            artifacts.get("art_plan_001")


def test_qa_fail_is_persisted_but_cannot_advance_to_review(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    task = _task(project_root)
    definitions = _definitions()
    contexts = FileRunContextBuilder(project_root)
    adapter, _ = _successful_adapter(
        task,
        definitions,
        contexts,
        qa_behavior=FakeBehavior.QA_FAIL,
    )
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    with SqliteTaskRepository(tmp_path / "state.sqlite3") as repository:
        repository.create(task)
        runner = SerialOrchestrator(
            repository=repository,
            artifact_store=artifacts,
            context_builder=contexts,
            agent_adapter=adapter,
            agent_definitions=definitions,
            identities=FixedIdentityFactory(),
            clock=_clock,
        )

        with pytest.raises(UnexpectedVerdict, match="T010 routing required"):
            runner.run_task(task.id)

        assert repository.get(task.id).status is TaskStatus.QA
        assert repository.current_revision(task.id) == 3
        qa_artifact = artifacts.get("art_qa_001")
        assert isinstance(qa_artifact, QaReportArtifact)
        assert qa_artifact.content.status is QaReportStatus.FAIL
        with pytest.raises(ArtifactNotFound):
            artifacts.get("art_review_001")


def test_missing_plan_criterion_cannot_advance_to_implementation(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    task = _task(project_root)
    definitions = _definitions()
    contexts = FileRunContextBuilder(project_root)
    adapter, _ = _successful_adapter(
        task,
        definitions,
        contexts,
        plan_covers_criteria=False,
    )
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    with SqliteTaskRepository(tmp_path / "state.sqlite3") as repository:
        repository.create(task)
        runner = SerialOrchestrator(
            repository=repository,
            artifact_store=artifacts,
            context_builder=contexts,
            agent_adapter=adapter,
            agent_definitions=definitions,
            identities=FixedIdentityFactory(),
            clock=_clock,
        )

        with pytest.raises(DeliveryContractViolation, match="exactly cover"):
            runner.run_task(task.id)

        assert repository.get(task.id).status is TaskStatus.PLANNING
        assert artifacts.get("art_plan_001").artifact_id == "art_plan_001"
        with pytest.raises(ArtifactNotFound):
            artifacts.get("art_impl_001")


def test_duplicate_run_identity_stops_before_the_second_agent(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    task = _task(project_root)
    definitions = _definitions()
    contexts = FileRunContextBuilder(project_root)
    adapter, _ = _successful_adapter(task, definitions, contexts)
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    with SqliteTaskRepository(tmp_path / "state.sqlite3") as repository:
        repository.create(task)
        runner = SerialOrchestrator(
            repository=repository,
            artifact_store=artifacts,
            context_builder=contexts,
            agent_adapter=adapter,
            agent_definitions=definitions,
            identities=DuplicateRunIdentityFactory(),
            clock=_clock,
        )

        with pytest.raises(DeliveryContractViolation, match="duplicate Agent run ID"):
            runner.run_task(task.id)

        assert repository.get(task.id).status is TaskStatus.IMPLEMENTING
        assert repository.current_revision(task.id) == 2
        assert artifacts.get("art_plan_001").artifact_id == "art_plan_001"
        with pytest.raises(ArtifactNotFound):
            artifacts.get("art_impl_001")


def test_non_new_task_is_rejected_without_new_events(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    task = _task(project_root).model_copy(update={"status": TaskStatus.PLANNING})
    with SqliteTaskRepository(tmp_path / "state.sqlite3") as repository:
        repository.create(task)
        runner = SerialOrchestrator(
            repository=repository,
            artifact_store=FileArtifactStore(tmp_path / "artifacts"),
            context_builder=FileRunContextBuilder(project_root),
            agent_adapter=FakeAgentAdapter(default=FakeScenario(behavior=FakeBehavior.TIMEOUT)),
            agent_definitions=_definitions(),
            identities=FixedIdentityFactory(),
            clock=_clock,
        )

        with pytest.raises(TaskNotRunnable, match="must be NEW"):
            runner.run_task(task.id)

        assert repository.current_revision(task.id) == 0
        assert repository.list_events(task.id) == ()
