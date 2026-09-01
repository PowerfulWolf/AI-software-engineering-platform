"""Recomputable delivery metrics and ADR through the pure EvaluationEngine seam."""

from datetime import timedelta

from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.evaluation import (
    AdrStatus,
    AgentRunEvent,
    ArtifactOutputStatus,
    EvaluationEngine,
    EvaluationEvent,
    EvaluationTrace,
    HumanAction,
    RegressionStatus,
)
from tests.domain.factories import (
    CANDIDATE_SHA,
    NOW,
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
    make_review_artifact,
    make_task,
)
from tests.evaluation.factories import (
    make_agent_run,
    make_case_started,
    make_human_action,
    make_regression_check,
)


def _state_events(*, terminal: TaskStatus = TaskStatus.DONE) -> tuple[StateEvent, ...]:
    transitions = [
        (TaskStatus.NEW, TaskStatus.PLANNING, ()),
        (TaskStatus.PLANNING, TaskStatus.IMPLEMENTING, ("art_plan_001",)),
        (TaskStatus.IMPLEMENTING, TaskStatus.QA, ("art_impl_001",)),
        (TaskStatus.QA, TaskStatus.REVIEW, ("art_qa_001",)),
        (
            TaskStatus.REVIEW,
            terminal,
            ("art_plan_001", "art_impl_001", "art_qa_001", "art_review_001")
            if terminal is TaskStatus.DONE
            else ("art_qa_001",),
        ),
    ]
    return tuple(
        StateEvent(
            event_id=f"evt_eval_{index:02d}_{to_status.value.lower()}",
            task_id="task_domain_001",
            from_status=from_status,
            to_status=to_status,
            actor=AgentRole.ORCHESTRATOR,
            attempt=1,
            reason="review_approved" if to_status is TaskStatus.DONE else "evaluation fixture",
            artifact_ids=artifact_ids,
            source_revision=CANDIDATE_SHA,
            occurred_at=NOW + timedelta(minutes=index),
        )
        for index, (from_status, to_status, artifact_ids) in enumerate(transitions, start=1)
    )


def _run(*, role: AgentRole, artifact_id: str, event_id: str, minute: int) -> AgentRunEvent:
    producer_run_ids = {
        AgentRole.ORCHESTRATOR: "run_agent_orchestrator_001_001",
        AgentRole.CODER: "run_agent_coder_001_001",
        AgentRole.QA: "run_agent_qa_001_001",
        AgentRole.REVIEWER: "run_agent_reviewer_001_001",
    }
    return make_agent_run().model_copy(
        update={
            "event_id": event_id,
            "run_id": producer_run_ids[role],
            "role": role,
            "artifact_id": artifact_id,
            "occurred_at": NOW + timedelta(minutes=minute),
        }
    )


def _trace(
    *,
    case_id: str = "case_domain_001",
    terminal: TaskStatus = TaskStatus.DONE,
    regression: bool | None = True,
    human_action: HumanAction | None = None,
) -> EvaluationTrace:
    state_events = _state_events(terminal=terminal)
    task = make_task().model_copy(
        update={
            "base_ref": "a" * 40,
            "status": terminal,
            "attempts": 1,
            "updated_at": state_events[-1].occurred_at,
        }
    )
    started = make_case_started().model_copy(update={"case_id": case_id})
    evaluation_events: list[EvaluationEvent] = [
        started,
        _run(
            role=AgentRole.ORCHESTRATOR,
            artifact_id="art_plan_001",
            event_id="evalevt_run_plan_001",
            minute=1,
        ).model_copy(update={"case_id": case_id}),
        _run(
            role=AgentRole.CODER,
            artifact_id="art_impl_001",
            event_id="evalevt_run_coder_001",
            minute=2,
        ).model_copy(update={"case_id": case_id}),
        _run(
            role=AgentRole.QA,
            artifact_id="art_qa_001",
            event_id="evalevt_run_qa_001",
            minute=3,
        ).model_copy(update={"case_id": case_id}),
        _run(
            role=AgentRole.REVIEWER,
            artifact_id="art_review_001",
            event_id="evalevt_run_review_001",
            minute=4,
        ).model_copy(update={"case_id": case_id}),
    ]
    if human_action is not None:
        evaluation_events.append(
            make_human_action(action=human_action).model_copy(update={"case_id": case_id})
        )
    if regression is not None:
        check = make_regression_check().model_copy(
            update={
                "case_id": case_id,
                "status": RegressionStatus.PASS if regression else RegressionStatus.FAIL,
                "window_started_at": state_events[-1].occurred_at + timedelta(minutes=1),
            }
        )
        evaluation_events.append(check)
    return EvaluationTrace(
        case=started,
        task=task,
        state_events=state_events,
        artifacts=(
            make_plan_artifact(),
            make_implementation_artifact(),
            make_qa_artifact(),
            make_review_artifact(),
        ),
        evaluation_events=tuple(evaluation_events),
    )


def test_complete_autonomous_trace_is_eligible_and_recomputes_core_metrics() -> None:
    report = EvaluationEngine().evaluate((_trace(),))
    case = report.cases[0]

    assert case.adr.status is AdrStatus.ELIGIBLE
    assert case.candidate_revision == CANDIDATE_SHA
    assert case.first_pass_qa is True
    assert case.first_pass_review is True
    assert case.evidence_covered == case.evidence_required == 1
    assert case.cycle_time_ms == 4 * 60 * 1000
    assert report.summary.autonomous_delivery_rate.to_wire() == {
        "numerator": 1,
        "denominator": 1,
        "value": 1.0,
    }
    assert report.summary.artifact_validity_rate.value == 1.0
    assert report.summary.regression_observation_coverage.value == 1.0


def test_done_without_closed_regression_window_is_pending_not_success() -> None:
    case = EvaluationEngine().evaluate((_trace(regression=None),)).cases[0]

    assert case.adr.status is AdrStatus.PENDING
    assert "REGRESSION_PENDING" in case.adr.reasons


def test_disqualifying_human_action_and_uncaught_policy_violation_are_ineligible() -> None:
    trace = _trace(human_action=HumanAction.MODIFY_CODE)
    events = list(trace.evaluation_events)
    coder = next(
        event
        for event in events
        if isinstance(event, AgentRunEvent) and event.role is AgentRole.CODER
    )
    events[events.index(coder)] = coder.model_copy(
        update={"policy_violations": 1, "caught_policy_violations": 0}
    )
    trace = trace.model_copy(update={"evaluation_events": tuple(events)})

    case = EvaluationEngine().evaluate((trace,)).cases[0]

    assert case.adr.status is AdrStatus.INELIGIBLE
    assert set(case.adr.reasons) >= {"HUMAN_INTERVENTION", "UNCAUGHT_POLICY_VIOLATION"}


def test_five_case_suite_recomputes_conservative_adr_and_completion_rates() -> None:
    traces = (
        _trace(case_id="case_suite_eligible"),
        _trace(case_id="case_suite_pending", regression=None),
        _trace(case_id="case_suite_human", human_action=HumanAction.MODIFY_TESTS),
        _trace(case_id="case_suite_blocked", terminal=TaskStatus.BLOCKED, regression=None),
        _trace(case_id="case_suite_regression", regression=False),
    )

    report = EvaluationEngine().evaluate(traces)

    assert report.summary.started_cases == 5
    assert report.summary.completed_cases == 4
    assert report.summary.pending_adr_cases == 1
    assert report.summary.autonomous_delivery_rate.numerator == 1
    assert report.summary.autonomous_delivery_rate.denominator == 5
    assert report.summary.task_completion_rate.value == 0.8
    assert report.summary.regression_escape_rate.numerator == 1
    assert report.summary.human_escalation_rate.numerator == 1


def test_invalid_agent_output_is_counted_without_becoming_an_artifact() -> None:
    trace = _trace()
    invalid = make_agent_run().model_copy(
        update={
            "event_id": "evalevt_invalid_output_001",
            "run_id": "run_coder_invalid_001",
            "output_status": ArtifactOutputStatus.INVALID,
            "artifact_id": None,
        }
    )
    trace = trace.model_copy(update={"evaluation_events": (*trace.evaluation_events, invalid)})

    report = EvaluationEngine().evaluate((trace,))

    assert report.summary.artifact_validity_rate.numerator == 4
    assert report.summary.artifact_validity_rate.denominator == 5
    assert report.summary.artifact_validity_rate.value == 0.8
