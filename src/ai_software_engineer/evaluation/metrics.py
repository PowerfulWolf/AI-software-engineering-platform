"""Pure, replayable metrics and Autonomous Delivery Rate calculation."""

from enum import StrEnum
from statistics import median
from typing import Self

from pydantic import Field, StrictBool, StrictFloat, StrictInt, model_validator

from ai_software_engineer.domain.artifact import (
    Artifact,
    CommitSha,
    QaReportArtifact,
    ReviewReportArtifact,
)
from ai_software_engineer.domain.enums import (
    AgentRole,
    QaCriterionStatus,
    QaReportStatus,
    ReviewVerdict,
    TaskStatus,
)
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.model import DomainModel, ensure_unique
from ai_software_engineer.domain.task import Task, TaskId
from ai_software_engineer.evaluation.delivery import DeliveryChain, resolve_delivery_chain
from ai_software_engineer.evaluation.models import (
    AgentRunEvent,
    ArtifactOutputStatus,
    CaseStartedEvent,
    EvaluationCaseId,
    EvaluationEvent,
    HumanAction,
    HumanActionEvent,
    RegressionCheckEvent,
    RegressionStatus,
)


class AdrStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    PENDING = "PENDING"
    EXCLUDED = "EXCLUDED"


class AdrReason(StrEnum):
    EXCLUDED_BY_CASE = "EXCLUDED_BY_CASE"
    TASK_NOT_STARTED = "TASK_NOT_STARTED"
    TASK_NOT_DONE = "TASK_NOT_DONE"
    INVALID_DELIVERY_CHAIN = "INVALID_DELIVERY_CHAIN"
    INCOMPLETE_RUN_EVIDENCE = "INCOMPLETE_RUN_EVIDENCE"
    INCOMPLETE_ACCEPTANCE_EVIDENCE = "INCOMPLETE_ACCEPTANCE_EVIDENCE"
    HUMAN_INTERVENTION = "HUMAN_INTERVENTION"
    POLICY_OVERRIDE = "POLICY_OVERRIDE"
    UNCAUGHT_POLICY_VIOLATION = "UNCAUGHT_POLICY_VIOLATION"
    REGRESSION_PENDING = "REGRESSION_PENDING"
    REGRESSION_FAILED = "REGRESSION_FAILED"


class Rate(DomainModel):
    """A ratio that retains its counts instead of only storing a rounded number."""

    numerator: StrictInt = Field(ge=0)
    denominator: StrictInt = Field(ge=0)
    value: StrictFloat | None

    @model_validator(mode="after")
    def validate_ratio(self) -> Self:
        expected = None if self.denominator == 0 else self.numerator / self.denominator
        if self.value != expected:
            raise ValueError("rate value must be recomputable from numerator and denominator")
        return self


class AdrAssessment(DomainModel):
    status: AdrStatus
    reasons: tuple[AdrReason, ...] = ()

    @model_validator(mode="after")
    def validate_reasons(self) -> Self:
        ensure_unique(self.reasons, "ADR reasons")
        if self.status is AdrStatus.ELIGIBLE and self.reasons:
            raise ValueError("eligible ADR assessment cannot contain failure reasons")
        if self.status is not AdrStatus.ELIGIBLE and not self.reasons:
            raise ValueError("non-eligible ADR assessment requires a reason")
        return self


class EvaluationTrace(DomainModel):
    """All durable facts needed to replay one evaluation case."""

    case: CaseStartedEvent
    task: Task
    state_events: tuple[StateEvent, ...]
    artifacts: tuple[Artifact, ...]
    evaluation_events: tuple[EvaluationEvent, ...]

    @model_validator(mode="after")
    def validate_trace_identity(self) -> Self:
        if self.case.task_id != self.task.id:
            raise ValueError("evaluation case and Task IDs must match")
        if self.case.base_revision != self.task.base_ref:
            raise ValueError("evaluation case base_revision must match Task base_ref")
        starts = tuple(
            event for event in self.evaluation_events if isinstance(event, CaseStartedEvent)
        )
        if starts != (self.case,):
            raise ValueError("evaluation trace requires exactly its declared CaseStartedEvent")
        if any(
            event.case_id != self.case.case_id or event.task_id != self.task.id
            for event in self.evaluation_events
        ):
            raise ValueError("evaluation event identity differs from its trace")
        if any(event.task_id != self.task.id for event in self.state_events):
            raise ValueError("StateEvent belongs to another Task")
        if any(artifact.task_id != self.task.id for artifact in self.artifacts):
            raise ValueError("Artifact belongs to another Task")
        ensure_unique(
            (event.event_id for event in self.evaluation_events),
            "evaluation trace event IDs",
        )
        ensure_unique((event.event_id for event in self.state_events), "StateEvent IDs")
        ensure_unique((artifact.artifact_id for artifact in self.artifacts), "Artifact IDs")
        for previous, current in zip(self.state_events, self.state_events[1:], strict=False):
            if previous.to_status is not current.from_status:
                raise ValueError("StateEvent sequence is not contiguous")
            if previous.occurred_at > current.occurred_at:
                raise ValueError("StateEvent sequence is not chronological")
        if self.state_events and self.state_events[-1].to_status is not self.task.status:
            raise ValueError("Task status differs from final StateEvent")
        return self


class CaseEvaluation(DomainModel):
    case_id: EvaluationCaseId
    task_id: TaskId
    included: StrictBool
    started: StrictBool
    completed: StrictBool
    candidate_revision: CommitSha | None = None
    first_pass_qa: StrictBool | None = None
    first_pass_review: StrictBool | None = None
    artifact_outputs_valid: StrictInt = Field(ge=0)
    artifact_outputs_attempted: StrictInt = Field(ge=0)
    evidence_covered: StrictInt = Field(ge=0)
    evidence_required: StrictInt = Field(ge=0)
    cycle_time_ms: StrictInt | None = Field(default=None, ge=0)
    attempts: StrictInt = Field(ge=0)
    regression_escape: StrictBool | None = None
    human_escalated: StrictBool
    policy_violations: StrictInt = Field(ge=0)
    uncaught_policy_violations: StrictInt = Field(ge=0)
    agent_runs: StrictInt = Field(ge=0)
    adr: AdrAssessment


class EvaluationSummary(DomainModel):
    started_cases: StrictInt = Field(ge=0)
    completed_cases: StrictInt = Field(ge=0)
    pending_adr_cases: StrictInt = Field(ge=0)
    task_completion_rate: Rate
    first_pass_qa_rate: Rate
    first_pass_review_rate: Rate
    artifact_validity_rate: Rate
    evidence_coverage: Rate
    median_cycle_time_ms: StrictInt | None = Field(default=None, ge=0)
    mean_attempts: StrictFloat | None = Field(default=None, ge=0)
    regression_escape_rate: Rate
    regression_observation_coverage: Rate
    human_escalation_rate: Rate
    policy_violation_rate: Rate
    autonomous_delivery_rate: Rate


class EvaluationReport(DomainModel):
    cases: tuple[CaseEvaluation, ...]
    summary: EvaluationSummary


class EvaluationEngine:
    """Derive every metric from typed trace facts without mutable counters."""

    def evaluate(self, traces: tuple[EvaluationTrace, ...]) -> EvaluationReport:
        ensure_unique((trace.case.case_id for trace in traces), "evaluation case IDs")
        cases = tuple(
            sorted((self._evaluate_case(trace) for trace in traces), key=lambda item: item.case_id)
        )
        included_started = tuple(case for case in cases if case.included and case.started)
        completed = tuple(case for case in included_started if case.completed)
        cycle_times = tuple(
            case.cycle_time_ms for case in completed if case.cycle_time_ms is not None
        )
        valid_outputs = sum(case.artifact_outputs_valid for case in included_started)
        attempted_outputs = sum(case.artifact_outputs_attempted for case in included_started)
        evidence_covered = sum(case.evidence_covered for case in included_started)
        evidence_required = sum(case.evidence_required for case in included_started)
        agent_runs = sum(case.agent_runs for case in included_started)
        policy_violations = sum(case.policy_violations for case in included_started)
        denominator = len(included_started)
        summary = EvaluationSummary(
            started_cases=denominator,
            completed_cases=len(completed),
            pending_adr_cases=sum(
                case.adr.status is AdrStatus.PENDING for case in included_started
            ),
            task_completion_rate=_rate(len(completed), denominator),
            first_pass_qa_rate=_rate(
                sum(case.first_pass_qa is True for case in included_started), denominator
            ),
            first_pass_review_rate=_rate(
                sum(case.first_pass_review is True for case in included_started), denominator
            ),
            artifact_validity_rate=_rate(valid_outputs, attempted_outputs),
            evidence_coverage=_rate(evidence_covered, evidence_required),
            median_cycle_time_ms=int(median(cycle_times)) if cycle_times else None,
            mean_attempts=(
                sum(case.attempts for case in included_started) / denominator
                if denominator
                else None
            ),
            regression_escape_rate=_rate(
                sum(case.regression_escape is True for case in completed), len(completed)
            ),
            regression_observation_coverage=_rate(
                sum(case.regression_escape is not None for case in completed), len(completed)
            ),
            human_escalation_rate=_rate(
                sum(case.human_escalated for case in included_started), denominator
            ),
            policy_violation_rate=_rate(policy_violations, agent_runs),
            autonomous_delivery_rate=_rate(
                sum(case.adr.status is AdrStatus.ELIGIBLE for case in included_started),
                denominator,
            ),
        )
        return EvaluationReport(cases=cases, summary=summary)

    @staticmethod
    def _evaluate_case(trace: EvaluationTrace) -> CaseEvaluation:
        state_events = tuple(
            sorted(trace.state_events, key=lambda event: (event.occurred_at, event.event_id))
        )
        evaluation_events = tuple(
            sorted(trace.evaluation_events, key=lambda event: (event.occurred_at, event.event_id))
        )
        started = any(event.to_status is TaskStatus.PLANNING for event in state_events)
        completed = bool(state_events and state_events[-1].to_status is TaskStatus.DONE)
        chain = resolve_delivery_chain(trace.task, state_events, trace.artifacts)
        candidate = chain[1].content.commit_sha if chain is not None else None
        runs = tuple(event for event in evaluation_events if isinstance(event, AgentRunEvent))
        output_attempts = tuple(
            event for event in runs if event.output_status is not ArtifactOutputStatus.NOT_PRODUCED
        )
        covered, required = _evidence_coverage(trace.task, chain)
        done_event = state_events[-1] if completed else None
        regression = _regression_escape(evaluation_events, done_event)
        cycle_time = _cycle_time_ms(state_events) if completed else None
        attempts = max(
            (
                trace.task.attempts,
                *(event.attempt for event in state_events),
                *(event.attempt for event in runs),
            ),
            default=trace.task.attempts,
        )
        uncaught = sum(event.policy_violations - event.caught_policy_violations for event in runs)
        adr = _assess_adr(
            trace,
            started=started,
            completed=completed,
            chain=chain,
            runs=runs,
            evidence_complete=covered == required,
            regression=regression,
            uncaught_policy_violations=uncaught,
        )
        return CaseEvaluation(
            case_id=trace.case.case_id,
            task_id=trace.task.id,
            included=trace.case.included,
            started=started,
            completed=completed,
            candidate_revision=candidate,
            first_pass_qa=_first_pass(trace.artifacts, runs, AgentRole.QA),
            first_pass_review=_first_pass(trace.artifacts, runs, AgentRole.REVIEWER),
            artifact_outputs_valid=sum(
                event.output_status is ArtifactOutputStatus.VALID for event in output_attempts
            ),
            artifact_outputs_attempted=len(output_attempts),
            evidence_covered=covered,
            evidence_required=required,
            cycle_time_ms=cycle_time,
            attempts=attempts,
            regression_escape=regression,
            human_escalated=trace.task.status is TaskStatus.BLOCKED,
            policy_violations=sum(event.policy_violations for event in runs),
            uncaught_policy_violations=uncaught,
            agent_runs=len(runs),
            adr=adr,
        )


def _evidence_coverage(task: Task, chain: DeliveryChain | None) -> tuple[int, int]:
    required_ids = {criterion.id for criterion in task.acceptance_criteria if criterion.required}
    if chain is None:
        return 0, len(required_ids)
    qa = chain[2]
    covered = {
        result.criterion_id
        for result in qa.content.criteria_results
        if result.criterion_id in required_ids
        and result.status is QaCriterionStatus.PASS
        and bool(result.evidence_ids)
    }
    return len(covered), len(required_ids)


def _first_pass(
    artifacts: tuple[Artifact, ...], runs: tuple[AgentRunEvent, ...], role: AgentRole
) -> bool | None:
    role_runs = tuple(event for event in runs if event.role is role)
    if not role_runs:
        return None
    first = role_runs[0]
    if first.output_status is not ArtifactOutputStatus.VALID or first.artifact_id is None:
        return False
    artifact = next((item for item in artifacts if item.artifact_id == first.artifact_id), None)
    if role is AgentRole.QA:
        return (
            first.attempt == 1
            and isinstance(artifact, QaReportArtifact)
            and artifact.content.status is QaReportStatus.PASS
        )
    if role is AgentRole.REVIEWER:
        return (
            first.attempt == 1
            and isinstance(artifact, ReviewReportArtifact)
            and artifact.content.verdict is ReviewVerdict.APPROVE
        )
    return None


def _regression_escape(
    evaluation_events: tuple[EvaluationEvent, ...], done_event: StateEvent | None
) -> bool | None:
    if done_event is None:
        return None
    checks = tuple(
        event
        for event in evaluation_events
        if isinstance(event, RegressionCheckEvent)
        and event.window_started_at >= done_event.occurred_at
    )
    if not checks:
        return None
    return checks[-1].status is RegressionStatus.FAIL


def _cycle_time_ms(events: tuple[StateEvent, ...]) -> int | None:
    planning = next((event for event in events if event.to_status is TaskStatus.PLANNING), None)
    done = next((event for event in reversed(events) if event.to_status is TaskStatus.DONE), None)
    if planning is None or done is None or done.occurred_at < planning.occurred_at:
        return None
    return int((done.occurred_at - planning.occurred_at).total_seconds() * 1000)


def _assess_adr(
    trace: EvaluationTrace,
    *,
    started: bool,
    completed: bool,
    chain: DeliveryChain | None,
    runs: tuple[AgentRunEvent, ...],
    evidence_complete: bool,
    regression: bool | None,
    uncaught_policy_violations: int,
) -> AdrAssessment:
    if not trace.case.included:
        return AdrAssessment(status=AdrStatus.EXCLUDED, reasons=(AdrReason.EXCLUDED_BY_CASE,))
    reasons: list[AdrReason] = []
    if not started:
        reasons.append(AdrReason.TASK_NOT_STARTED)
    if not completed:
        reasons.append(AdrReason.TASK_NOT_DONE)
    if completed and chain is None:
        reasons.append(AdrReason.INVALID_DELIVERY_CHAIN)
    if chain is not None and not _run_evidence_complete(chain, runs):
        reasons.append(AdrReason.INCOMPLETE_RUN_EVIDENCE)
    if chain is not None and not evidence_complete:
        reasons.append(AdrReason.INCOMPLETE_ACCEPTANCE_EVIDENCE)
    human_actions = tuple(
        event.action for event in trace.evaluation_events if isinstance(event, HumanActionEvent)
    )
    disqualifying = set(HumanAction) - {
        HumanAction.START_TASK,
        HumanAction.VIEW_HANDOFF,
        HumanAction.MERGE_DELIVERY,
    }
    if any(action in disqualifying for action in human_actions):
        reasons.append(AdrReason.HUMAN_INTERVENTION)
    if HumanAction.OVERRIDE_POLICY in human_actions:
        reasons.append(AdrReason.POLICY_OVERRIDE)
    if uncaught_policy_violations:
        reasons.append(AdrReason.UNCAUGHT_POLICY_VIOLATION)
    if completed:
        if regression is None:
            reasons.append(AdrReason.REGRESSION_PENDING)
        elif regression:
            reasons.append(AdrReason.REGRESSION_FAILED)
    reasons = list(dict.fromkeys(reasons))
    hard_reasons = tuple(reason for reason in reasons if reason is not AdrReason.REGRESSION_PENDING)
    if hard_reasons:
        return AdrAssessment(status=AdrStatus.INELIGIBLE, reasons=tuple(reasons))
    if reasons:
        return AdrAssessment(status=AdrStatus.PENDING, reasons=tuple(reasons))
    return AdrAssessment(status=AdrStatus.ELIGIBLE)


def _run_evidence_complete(chain: DeliveryChain, runs: tuple[AgentRunEvent, ...]) -> bool:
    by_artifact = {
        event.artifact_id: event
        for event in runs
        if event.output_status is ArtifactOutputStatus.VALID and event.artifact_id is not None
    }
    return all(
        artifact.artifact_id in by_artifact
        and by_artifact[artifact.artifact_id].run_id == artifact.producer.run_id
        and by_artifact[artifact.artifact_id].role is artifact.producer.role
        for artifact in chain
    )


def _rate(numerator: int, denominator: int) -> Rate:
    return Rate(
        numerator=numerator,
        denominator=denominator,
        value=None if denominator == 0 else numerator / denominator,
    )


__all__ = [
    "AdrAssessment",
    "AdrReason",
    "AdrStatus",
    "CaseEvaluation",
    "EvaluationEngine",
    "EvaluationReport",
    "EvaluationSummary",
    "EvaluationTrace",
    "Rate",
]
