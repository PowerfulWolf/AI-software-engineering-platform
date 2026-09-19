"""Independent QA: approved knowledge resolutions remain human ADR interventions."""

from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.domain import TaskStatus, TeamRole
from ai_software_engineer.evaluation import (
    AdrStatus,
    CaseStartedEvent,
    EvaluationEngine,
    EvaluationTraceBuilder,
    FileEvaluationEventStore,
    HumanAction,
    HumanActionEvent,
)
from ai_software_engineer.knowledge.agents import KnowledgeConsultationService
from ai_software_engineer.knowledge.audit import KnowledgeHumanActionRecorder
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGapRaised,
    KnowledgeGapService,
    KnowledgeResolution,
    KnowledgeResolutionSource,
)
from ai_software_engineer.knowledge.models import KnowledgeSnapshot, digest, text_digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.runtime import RuntimeSession
from ai_software_engineer.store import SqliteTaskRepository
from tests.domain.factories import NOW, make_task
from tests.evaluation.factories import make_case_started
from tests.evaluation.test_metrics import _trace
from tests.knowledge.test_consultation import Model
from tests.knowledge.test_gaps import Approval
from tests.knowledge.test_retrieval_contract import binding
from tests.runtime.test_runtime import RuntimeFixtureAdapter, _config


def _approved_resolution(
    root: Path, *, task_id: str | None, requirement_id: str = "requirement_refund"
) -> tuple[KnowledgeRecordStore, KnowledgeResolution]:
    records = KnowledgeRecordStore(root)
    frozen = KnowledgeSnapshot.create(
        team_id="team_ai",
        project_id="project_payments",
        requirement_id=requirement_id,
        repository_ids=("repository_payments",),
    )
    bound = binding(frozen).model_copy(
        update={"task_id": task_id, "role": TeamRole.CODER if task_id else TeamRole.PRODUCT}
    )
    with pytest.raises(KnowledgeGapRaised) as raised:
        KnowledgeConsultationService(Model(), records).consult(
            bound,
            frozen,
            {"requirement": "Refund using the correct payment ID"},
            timeout_seconds=10,
        )
    gap = raised.value.gap
    answer = "Refunds must use the original payment ID."
    resolution = KnowledgeResolution(
        gap_id=gap.gap_id,
        previous_run_id=gap.binding.run_id,
        answer=answer,
        sources=(
            KnowledgeResolutionSource(
                uri="human://audit-qa/refund", content=answer, sha256=text_digest(answer)
            ),
        ),
        approval_reference="human:exact-approved-answer",
        approved_by="human:fixture-owner",
        resolution_id="0" * 64,
    )
    resolution = resolution.model_copy(
        update={
            "resolution_id": digest(resolution.model_dump(mode="json", exclude={"resolution_id"}))
        }
    )
    assert KnowledgeGapService(records).resolve(resolution, Approval(resolution)) == resolution
    return records, resolution


def test_exact_task_resolution_records_one_human_clarification_after_reopening(
    tmp_path: Path,
) -> None:
    task = make_task()
    records, resolution = _approved_resolution(tmp_path / "knowledge", task_id=task.id)
    events = FileEvaluationEventStore(tmp_path / "evaluation")
    case = make_case_started()
    events.append(case)
    KnowledgeHumanActionRecorder((records,)).record(task, case.case_id, events)
    original = events.list_for_case(case.case_id)
    actions = tuple(event for event in original if isinstance(event, HumanActionEvent))
    assert len(actions) == 1
    assert actions[0].task_id == task.id and actions[0].case_id == case.case_id
    assert actions[0].action is HumanAction.CLARIFY_REQUIREMENTS
    assert actions[0].evidence_uri == "knowledge-resolution://" + resolution.resolution_id
    reopened = KnowledgeRecordStore(tmp_path / "knowledge")
    # Repeated discovery through more than one input store must still be idempotent.
    KnowledgeHumanActionRecorder((reopened, reopened)).record(
        task, case.case_id, FileEvaluationEventStore(tmp_path / "evaluation")
    )
    assert FileEvaluationEventStore(tmp_path / "evaluation").list_for_case(case.case_id) == original


def test_upstream_resolution_audits_each_associated_child_once(tmp_path: Path) -> None:
    records, resolution = _approved_resolution(tmp_path / "upstream", task_id=None)
    events = FileEvaluationEventStore(tmp_path / "evaluation")
    recorder = KnowledgeHumanActionRecorder((records,), requirement_id="requirement_refund")
    event_ids = set()
    for number in (1, 2):
        task = make_task().model_copy(update={"id": f"task_child_{number:03d}"})
        case_id = f"case_child_{number:03d}"
        recorder.record(task, case_id, events)
        recorder.record(task, case_id, events)
        (event,) = events.list_for_case(case_id)
        assert isinstance(event, HumanActionEvent)
        assert event.task_id == task.id and event.case_id == case_id
        assert event.evidence_uri == "knowledge-resolution://" + resolution.resolution_id
        event_ids.add(event.event_id)
    assert len(event_ids) == 2


@pytest.mark.parametrize(
    ("resolution_task", "resolution_requirement", "current_requirement"),
    (
        ("task_unrelated", "requirement_refund", "requirement_refund"),
        (None, "requirement_other", "requirement_refund"),
        (None, "requirement_refund", None),
    ),
)
def test_unrelated_task_or_requirement_resolution_does_not_enter_case(
    tmp_path: Path,
    resolution_task: str | None,
    resolution_requirement: str,
    current_requirement: str | None,
) -> None:
    records, _ = _approved_resolution(
        tmp_path / "knowledge",
        task_id=resolution_task,
        requirement_id=resolution_requirement,
    )
    events = FileEvaluationEventStore(tmp_path / "evaluation")
    case = make_case_started()
    events.append(case)
    KnowledgeHumanActionRecorder((records,), requirement_id=current_requirement).record(
        make_task(), case.case_id, events
    )
    assert events.list_for_case(case.case_id) == (case,)


def test_durable_resolution_fact_changes_eligible_delivery_to_non_autonomous(
    tmp_path: Path,
) -> None:
    expected = _trace()
    records, _ = _approved_resolution(tmp_path / "knowledge", task_id=expected.task.id)
    events = FileEvaluationEventStore(tmp_path / "evaluation")
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    with SqliteTaskRepository(tmp_path / "tasks.sqlite") as repository:
        initial = make_task().model_copy(update={"base_ref": expected.task.base_ref})
        repository.create(initial)
        repository.record_attempt(initial.id, 1)
        for state_event in expected.state_events:
            repository.append_event(state_event)
        for artifact in expected.artifacts:
            artifacts.put(seal_artifact(artifact, validated_at=NOW))
        for evaluation_event in expected.evaluation_events:
            events.append(evaluation_event)
        builder = EvaluationTraceBuilder(
            repository=repository, artifact_store=artifacts, event_store=events
        )
        before = EvaluationEngine().evaluate((builder.build(expected.case.case_id),))
        assert before.cases[0].adr.status is AdrStatus.ELIGIBLE
        KnowledgeHumanActionRecorder((records,)).record(initial, expected.case.case_id, events)
        after = EvaluationEngine().evaluate((builder.build(expected.case.case_id),))
        assert repository.get(initial.id).status is TaskStatus.DONE
        assert after.cases[0].adr.status is AdrStatus.INELIGIBLE
        assert "HUMAN_INTERVENTION" in after.cases[0].adr.reasons
        assert after.summary.autonomous_delivery_rate.numerator == 0
        assert after.summary.autonomous_delivery_rate.denominator == 1
        assert after.summary.completed_cases == 1


def test_runtime_records_human_fact_after_case_start_before_first_agent(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config = config.model_copy(
        update={
            "paths": config.paths.model_copy(
                update={"evidence": str(tmp_path / "evidence"), "runs": str(tmp_path / "runs")}
            )
        }
    )
    task = make_task().model_copy(update={"repository": str(tmp_path)})
    records, _ = _approved_resolution(tmp_path / "knowledge", task_id=task.id)
    with SqliteTaskRepository(config.paths.database) as repository:
        repository.create(task)
    case_id = "case_runtime_knowledge_qa"

    class AuditObservingAdapter(RuntimeFixtureAdapter):
        def run(self, request: AgentRequest) -> AgentResult:
            events = FileEvaluationEventStore(config.paths.evaluation_events).list_for_case(case_id)
            starts = [event for event in events if isinstance(event, CaseStartedEvent)]
            humans = [event for event in events if isinstance(event, HumanActionEvent)]
            assert len(starts) == len(humans) == 1
            assert humans[0].action is HumanAction.CLARIFY_REQUIREMENTS
            assert starts[0].occurred_at <= humans[0].occurred_at
            return super().run(request)

    adapter = AuditObservingAdapter()
    with RuntimeSession(
        config,
        environment={},
        agent_adapter=adapter,
        human_action_recorder=KnowledgeHumanActionRecorder((records,)),
    ) as runtime:
        result = runtime.run_task(task.id, case_id=case_id)
    assert result.result.task.status is TaskStatus.DONE
    assert len(adapter.requests) == 4
