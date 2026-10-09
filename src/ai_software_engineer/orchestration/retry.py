"""Bounded failure routing and restart-safe serial orchestration for T010."""

from enum import StrEnum

from ai_software_engineer.agents import AgentErrorCode, AgentRunStatus, RunId
from ai_software_engineer.agents.continuation import (
    ContinuationExecutionUncertain,
    InterruptionAdmissionRejected,
    InterruptionBudgetExhausted,
)
from ai_software_engineer.agents.structured import StructuredModelError
from ai_software_engineer.artifacts.ordering import (
    ArtifactOrderingError,
    compare_artifact_order,
    latest_accepted_artifact,
)
from ai_software_engineer.context import ContextBudgetExceeded
from ai_software_engineer.context.models import ContextId
from ai_software_engineer.domain.artifact import (
    Artifact,
    ArtifactId,
    CoderProgressArtifact,
    CommitSha,
    ImplementationReportArtifact,
    PlanArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
    classify_qa_failure,
)
from ai_software_engineer.domain.enums import (
    AgentRole,
    ArtifactKind,
    QaFailureDisposition,
    QaReportStatus,
    ReviewVerdict,
    TaskStatus,
)
from ai_software_engineer.domain.event import EventId, StateEvent
from ai_software_engineer.domain.execution_baseline import CoderExecutionInput
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.retry_policy import TRANSIENT_CODES, DeliveryRetryFailure
from ai_software_engineer.domain.task import Task, TaskId
from ai_software_engineer.orchestration.runner import (
    AgentRunFailed,
    DeliveryContractViolation,
    SerialOrchestrator,
    TaskNotRunnable,
)


class RetryClassification(StrEnum):
    """Stable categories used by the v0.1 routing policy."""

    TRANSIENT_INFRA = "TRANSIENT_INFRA"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    QA_FINDING = "QA_FINDING"
    VERIFICATION_INCONCLUSIVE = "VERIFICATION_INCONCLUSIVE"
    REVIEW_FINDING = "REVIEW_FINDING"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    REQUIREMENT_AMBIGUITY = "REQUIREMENT_AMBIGUITY"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    PLATFORM_BUG = "PLATFORM_BUG"


class RetryAction(StrEnum):
    """The only routing decisions available to the serial v0.1 runner."""

    RETRY_ROLE = "RETRY_ROLE"
    RETRY_CODER = "RETRY_CODER"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class RetryDecision(DomainModel):
    """An auditable classification and next action for one failure."""

    classification: RetryClassification
    action: RetryAction
    role: AgentRole
    attempt: int
    reason: NonEmptyStr
    artifact_ids: tuple[ArtifactId, ...] = ()


class BlockedResult(DomainModel):
    """Durable, human-actionable result when delivery cannot continue safely."""

    task: Task
    classification: RetryClassification
    reason: NonEmptyStr
    attempt: int
    artifact_ids: tuple[ArtifactId, ...]
    event_ids: tuple[EventId, ...]
    candidate_revision: CommitSha | None = None


class RetryDeliveryResult(DomainModel):
    """Auditable delivery output whose event history may contain retry transitions."""

    task: Task
    candidate_revision: CommitSha
    artifact_ids: tuple[ArtifactId, ...]
    context_manifest_ids: tuple[ContextId, ...]
    run_ids: tuple[RunId, ...]
    event_ids: tuple[EventId, ...]


type RetryResult = RetryDeliveryResult | BlockedResult


class RetryingOrchestrator(SerialOrchestrator):
    """Run the serial workflow with bounded retries and durable checkpoints.

    The class deliberately reuses T009's request, context, Artifact and transition guards.  It
    only adds a small state-aware loop; no queue, DAG scheduler or shared mutable Agent state is
    introduced.
    """

    def run_task(self, task_id: TaskId) -> RetryResult:  # type: ignore[override]
        if self._transition_gate is not None:
            self._transition_gate.begin_task(self._repository.get(task_id))
        try:
            return self._run_task(task_id)
        except ContextBudgetExceeded:
            task = self._repository.get(task_id)
            events = self._repository.list_events(task_id)
            artifact_ids = tuple(
                dict.fromkeys(artifact_id for event in events for artifact_id in event.artifact_ids)
            )
            return self._blocked(
                task,
                RetryClassification.BUDGET_EXHAUSTED,
                "Required context exceeds the configured input budget; no automatic retry.",
                max(task.attempts, 1),
                tuple(event.event_id for event in events),
                artifact_ids,
                source_revision=events[-1].source_revision if events else task.base_ref,
            )

    def _run_task(self, task_id: TaskId) -> RetryResult:
        task = self._repository.get(task_id)
        if task.status in {TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.FAILED}:
            raise TaskNotRunnable(f"Task {task.id} is terminal at {task.status.value}")

        existing_events = self._repository.list_events(task.id)
        role = {
            TaskStatus.IMPLEMENTING: AgentRole.CODER,
            TaskStatus.QA: AgentRole.QA,
            TaskStatus.REVIEW: AgentRole.REVIEWER,
        }.get(task.status)
        if (
            task.retry_policy is not None
            and role is not None
            and task.transient_failures(role) >= task.retry_policy.transient_limit(role)
        ):
            return self._blocked(
                task,
                RetryClassification.BUDGET_EXHAUSTED,
                f"{role.value} transient allowance exhausted; preserve evidence for recovery",
                max(task.attempts, 1),
                tuple(event.event_id for event in existing_events),
                tuple(dict.fromkeys(a for event in existing_events for a in event.artifact_ids)),
                source_revision=existing_events[-1].source_revision
                if existing_events
                else task.base_ref,
            )
        checkpointed_artifact_ids = {
            artifact_id for event in existing_events for artifact_id in event.artifact_ids
        }
        recovered_attempt = max((event.attempt for event in existing_events), default=0)
        if recovered_attempt > task.attempts:
            self._record_attempt(task, recovered_attempt)
            task = self._repository.get(task.id)

        artifacts = self._artifacts_for_task(task.id)
        baseline_input = (
            self._coder_execution_inputs.current(task, implementation=None, progress=None)
            if self._coder_execution_inputs is not None
            else None
        )
        plan = _latest(artifacts, PlanArtifact)
        implementation = _implementation_for_feedback(artifacts, source=baseline_input)
        qa = _latest(artifacts, QaReportArtifact)
        review = _latest(artifacts, ReviewReportArtifact)
        event_ids: list[str] = [event.event_id for event in existing_events]
        run_ids: list[str] = []
        context_ids: list[str] = []
        seen_run_ids: set[str] = {artifact.producer.run_id for artifact in artifacts}
        recover_candidate = _recoverable_candidate(task, existing_events, implementation)

        if task.status is TaskStatus.NEW:
            self._record_attempt(task, 1)
            task, event_id = self._transition(
                self._repository.get(task.id),
                TaskStatus.PLANNING,
                reason="task_validated",
                source_revision=task.base_ref,
                attempt=1,
            )
            event_ids.append(event_id)

        if task.status is TaskStatus.PLANNING:
            if plan is None:
                planner_result = self._run_planner(
                    task,
                    seen_run_ids,
                    run_ids,
                    context_ids,
                )
                if isinstance(planner_result, BlockedResult):
                    return planner_result.model_copy(
                        update={"event_ids": tuple(event_ids) + planner_result.event_ids}
                    )
                plan, task, plan_attempt = planner_result
                task, event_id = self._transition(
                    task,
                    TaskStatus.IMPLEMENTING,
                    reason="plan_validated",
                    source_revision=task.base_ref,
                    artifact_ids=(plan.artifact_id,),
                    attempt=plan_attempt,
                )
                event_ids.append(event_id)
            else:
                self._validate_plan(task, plan)
                task, event_id = self._transition(
                    task,
                    TaskStatus.IMPLEMENTING,
                    reason="plan_recovered",
                    source_revision=task.base_ref,
                    artifact_ids=(plan.artifact_id,),
                    attempt=max(task.attempts, 1),
                )
                event_ids.append(event_id)

        if plan is None:
            return self._blocked(
                self._repository.get(task.id),
                RetryClassification.INVALID_OUTPUT,
                "已保存的执行计划产物缺失, 需要工程核验记录后继续。",
                max(task.attempts, 1),
                event_ids,
                (),
            )

        while True:
            task = self._repository.get(task.id)
            coder_source = self._current_coder_input(task)
            active_progress = coder_source.active_progress
            if (
                implementation is not None
                and implementation.artifact_id in coder_source.superseded_artifact_ids
            ):
                recover_candidate = False
            if task.status is TaskStatus.CONTINUE_REQUIRED:
                if active_progress is None:
                    return self._blocked(
                        task,
                        RetryClassification.PLATFORM_BUG,
                        "continuation checkpoint has no coder-progress Artifact",
                        max(task.attempts, 1),
                        event_ids,
                        (),
                    )
                if task.work_budget_exhausted:
                    return self._blocked(
                        task,
                        RetryClassification.BUDGET_EXHAUSTED,
                        "Coder requested continuation after the configured run budget",
                        task.attempts,
                        event_ids,
                        (active_progress.artifact_id,),
                        source_revision=active_progress.source_revision,
                    )
                task, event_id = self._transition(
                    task,
                    TaskStatus.QUEUED,
                    reason="coder_continuation_queued",
                    source_revision=active_progress.source_revision,
                    artifact_ids=(active_progress.artifact_id,),
                    attempt=task.attempts,
                )
                event_ids.append(event_id)

            if task.status is TaskStatus.QUEUED:
                if active_progress is None:
                    return self._blocked(
                        task,
                        RetryClassification.PLATFORM_BUG,
                        "queued Coder continuation has no progress Artifact",
                        max(task.attempts, 1),
                        event_ids,
                        (),
                    )
                queued_attempt = _latest_transition_attempt(
                    self._repository.list_events(task.id),
                    TaskStatus.QUEUED,
                )
                # record_attempt and append_event are separate durable boundaries. If the
                # process stopped between them, reuse the already-reserved attempt instead of
                # skipping a number or exhausting the budget early.
                next_attempt = (
                    task.attempts if task.attempts > queued_attempt else task.attempts + 1
                )
                if next_attempt > task.max_attempts:
                    return self._blocked(
                        task,
                        RetryClassification.BUDGET_EXHAUSTED,
                        "Coder continuation run budget is exhausted",
                        task.attempts,
                        event_ids,
                        (active_progress.artifact_id,),
                        source_revision=active_progress.source_revision,
                    )
                self._record_attempt(task, next_attempt)
                task, event_id = self._transition(
                    self._repository.get(task.id),
                    TaskStatus.IMPLEMENTING,
                    reason="coder_continuation_resumed",
                    source_revision=active_progress.source_revision,
                    artifact_ids=(active_progress.artifact_id,),
                    attempt=next_attempt,
                )
                event_ids.append(event_id)

            if task.status is TaskStatus.IMPLEMENTING:
                if (
                    active_progress is not None
                    and active_progress.artifact_id not in checkpointed_artifact_ids
                ):
                    task, event_id = self._transition(
                        task,
                        TaskStatus.CONTINUE_REQUIRED,
                        reason="coder_progress_recovered",
                        source_revision=active_progress.source_revision,
                        artifact_ids=(active_progress.artifact_id,),
                        attempt=max(task.attempts, 1),
                    )
                    event_ids.append(event_id)
                    checkpointed_artifact_ids.add(active_progress.artifact_id)
                    continue
                if recover_candidate and implementation is not None:
                    self._validate_implementation(task, implementation)
                    task, event_id = self._transition(
                        task,
                        TaskStatus.QA,
                        reason="candidate_recovered",
                        source_revision=implementation.content.commit_sha,
                        artifact_ids=(implementation.artifact_id,),
                        attempt=max(task.attempts, 1),
                    )
                    event_ids.append(event_id)
                    recover_candidate = False
                else:
                    result = self._run_coder_with_retries(
                        task,
                        plan,
                        implementation,
                        qa,
                        review,
                        active_progress,
                        seen_run_ids,
                        run_ids,
                        context_ids,
                    )
                    if isinstance(result, BlockedResult):
                        return result.model_copy(
                            update={"event_ids": tuple(event_ids) + result.event_ids}
                        )
                    coder_artifact, task, event_id = result
                    event_ids.append(event_id)
                    if isinstance(coder_artifact, CoderProgressArtifact):
                        checkpointed_artifact_ids.add(coder_artifact.artifact_id)
                        continue
                    implementation = coder_artifact

            if task.status is TaskStatus.QA:
                if implementation is None:
                    return self._blocked(
                        task,
                        RetryClassification.PLATFORM_BUG,
                        "QA checkpoint has no implementation Artifact",
                        max(task.attempts, 1),
                        event_ids,
                        (),
                    )
                current_qa = (
                    qa
                    if qa is not None
                    and qa.source_revision == implementation.content.commit_sha
                    and qa.parent_artifact_ids == (implementation.artifact_id,)
                    and (
                        self._verification_reservation is None
                        or self._verification_reservation.is_current(task, qa)
                    )
                    else None
                )
                if current_qa is None:
                    qa_result = self._run_qa_with_retries(
                        task,
                        plan,
                        implementation,
                        seen_run_ids,
                        run_ids,
                        context_ids,
                        previous=qa
                        if qa is not None
                        and qa.source_revision == implementation.content.commit_sha
                        else None,
                    )
                    if isinstance(qa_result, BlockedResult):
                        return qa_result.model_copy(
                            update={"event_ids": tuple(event_ids) + qa_result.event_ids}
                        )
                    qa, task = qa_result
                else:
                    qa = current_qa
                if qa.content.status is QaReportStatus.FAIL:
                    if classify_qa_failure(qa.content) is QaFailureDisposition.RETRY_VERIFICATION:
                        return self._blocked(
                            task,
                            RetryClassification.VERIFICATION_INCONCLUSIVE,
                            "QA verification could not complete in the current environment; "
                            "the candidate is retained for fresh verification",
                            task.attempts,
                            event_ids,
                            (qa.artifact_id,),
                            source_revision=implementation.content.commit_sha,
                        )
                    if task.work_budget_exhausted:
                        return self._blocked(
                            task,
                            RetryClassification.QA_FINDING,
                            "QA findings remain after the configured attempt budget",
                            task.attempts,
                            event_ids,
                            (qa.artifact_id,),
                            source_revision=implementation.content.commit_sha,
                        )
                    next_attempt = task.attempts + 1
                    self._record_attempt(task, next_attempt)
                    task, event_id = self._transition(
                        self._repository.get(task.id),
                        TaskStatus.IMPLEMENTING,
                        reason="qa_failed_route_to_coder",
                        source_revision=implementation.content.commit_sha,
                        artifact_ids=(qa.artifact_id,),
                        attempt=next_attempt,
                    )
                    event_ids.append(event_id)
                    continue
                task, event_id = self._transition(
                    task,
                    TaskStatus.REVIEW,
                    reason="qa_passed",
                    source_revision=implementation.content.commit_sha,
                    artifact_ids=(qa.artifact_id,),
                    attempt=max(task.attempts, 1),
                )
                event_ids.append(event_id)

            if task.status is TaskStatus.REVIEW:
                if implementation is None or qa is None:
                    return self._blocked(
                        task,
                        RetryClassification.PLATFORM_BUG,
                        "review checkpoint is missing implementation or QA evidence",
                        max(task.attempts, 1),
                        event_ids,
                        (),
                    )
                current_review = (
                    review
                    if review is not None
                    and review.source_revision == implementation.content.commit_sha
                    and review.parent_artifact_ids == (qa.artifact_id,)
                    and qa.parent_artifact_ids == (implementation.artifact_id,)
                    and (
                        self._verification_reservation is None
                        or self._verification_reservation.is_current(task, review)
                    )
                    else None
                )
                if current_review is None:
                    review_result = self._run_review_with_retries(
                        task,
                        plan,
                        implementation,
                        qa,
                        seen_run_ids,
                        run_ids,
                        context_ids,
                        previous=review
                        if review is not None
                        and review.source_revision == implementation.content.commit_sha
                        else None,
                    )
                    if isinstance(review_result, BlockedResult):
                        return review_result.model_copy(
                            update={"event_ids": tuple(event_ids) + review_result.event_ids}
                        )
                    review, task = review_result
                else:
                    review = current_review
                if review.content.verdict is ReviewVerdict.REJECT:
                    if task.work_budget_exhausted:
                        return self._blocked(
                            task,
                            RetryClassification.REVIEW_FINDING,
                            "review findings remain after the configured attempt budget",
                            task.attempts,
                            event_ids,
                            (review.artifact_id,),
                            source_revision=implementation.content.commit_sha,
                        )
                    next_attempt = task.attempts + 1
                    self._record_attempt(task, next_attempt)
                    task, event_id = self._transition(
                        self._repository.get(task.id),
                        TaskStatus.IMPLEMENTING,
                        reason="review_rejected_route_to_coder",
                        source_revision=implementation.content.commit_sha,
                        artifact_ids=(review.artifact_id,),
                        attempt=next_attempt,
                    )
                    event_ids.append(event_id)
                    continue
                task, event_id = self._transition(
                    task,
                    TaskStatus.DONE,
                    reason="review_approved",
                    source_revision=implementation.content.commit_sha,
                    artifact_ids=(
                        plan.artifact_id,
                        implementation.artifact_id,
                        qa.artifact_id,
                        review.artifact_id,
                    ),
                    attempt=max(task.attempts, 1),
                )
                event_ids.append(event_id)
                return RetryDeliveryResult(
                    task=task,
                    candidate_revision=implementation.content.commit_sha,
                    artifact_ids=(
                        plan.artifact_id,
                        implementation.artifact_id,
                        qa.artifact_id,
                        review.artifact_id,
                    ),
                    context_manifest_ids=(
                        plan.context_manifest_id,
                        implementation.context_manifest_id,
                        qa.context_manifest_id,
                        review.context_manifest_id,
                    ),
                    run_ids=(
                        plan.producer.run_id,
                        implementation.producer.run_id,
                        qa.producer.run_id,
                        review.producer.run_id,
                    ),
                    event_ids=tuple(event_ids),
                )

    def _run_planner(
        self,
        task: Task,
        seen_run_ids: set[str],
        run_ids: list[str],
        context_ids: list[str],
    ) -> tuple[PlanArtifact, Task, int] | BlockedResult:
        attempt = max(task.attempts, 1)
        while True:
            self._record_attempt(task, attempt)
            try:
                completed = self._run_agent(
                    self._repository.get(task.id),
                    AgentRole.ORCHESTRATOR,
                    attempt=attempt,
                    candidate_revision=None,
                    input_artifacts=(),
                    expected_parents=(),
                    seen_run_ids=seen_run_ids,
                )
                plan = completed.artifact
                if not isinstance(plan, PlanArtifact):
                    raise DeliveryContractViolation("planning run did not produce a plan")
                self._validate_plan(self._repository.get(task.id), plan)
                run_ids.append(completed.run_id)
                context_ids.append(completed.context_id)
                return plan, self._repository.get(task.id), attempt
            except AgentRunFailed as error:
                next_attempt = self._retry_failure(task, error)
                if next_attempt is not None:
                    attempt = next_attempt
                    continue
                return self._blocked(
                    self._repository.get(task.id),
                    _classification(error),
                    f"Planner failed at attempt {attempt}: {error}",
                    attempt,
                    (),
                    (),
                )
            except DeliveryContractViolation:
                raise

    def _run_coder_with_retries(
        self,
        task: Task,
        plan: PlanArtifact,
        previous: ImplementationReportArtifact | None,
        qa: QaReportArtifact | None,
        review: ReviewReportArtifact | None,
        progress: CoderProgressArtifact | None,
        seen_run_ids: set[str],
        run_ids: list[str],
        context_ids: list[str],
    ) -> tuple[ImplementationReportArtifact | CoderProgressArtifact, Task, str] | BlockedResult:
        attempt = max(task.attempts, 1)
        from ai_software_engineer.domain.coder_feedback import coder_feedback

        feedback = coder_feedback(previous, qa, review)
        inputs = (plan, *feedback, *((progress,) if progress is not None else ()))
        coder_source = self._current_coder_input(task)
        progress_supersedes = (
            progress.artifact_id if progress is not None else coder_source.progress_supersedes
        )
        parents = tuple(item.artifact_id for item in inputs)
        if self.execution_control is not None:
            self.execution_control.before_checkpoint_recovery(
                task,
                AgentRole.CODER,
                attempt,
                coder_source.source_revision,
            )
        if self._interruption_control is not None:
            try:
                self._guard_write()
                restored_attempt = self._interruption_control.resume(
                    self._repository.get(task.id), self._repository
                )
            except ContinuationExecutionUncertain:
                raise
            except InterruptionAdmissionRejected as error:
                return self._blocked(
                    self._repository.get(task.id),
                    RetryClassification.BUDGET_EXHAUSTED
                    if isinstance(error, InterruptionBudgetExhausted)
                    else RetryClassification.TRANSIENT_INFRA,
                    "工程中断现场不满足安全续跑条件。草稿和历史已保留。需要工程处理。",
                    attempt,
                    (),
                    tuple(item.artifact_id for item in feedback),
                    source_revision=coder_source.source_revision,
                )
            if restored_attempt is not None:
                attempt = restored_attempt
        while True:
            self._record_attempt(task, attempt)
            try:
                completed = self._run_agent(
                    self._repository.get(task.id),
                    AgentRole.CODER,
                    attempt=attempt,
                    candidate_revision=(
                        previous.content.commit_sha if previous is not None else None
                    ),
                    input_artifacts=inputs,
                    expected_parents=parents,
                    expected_supersedes_by_kind={
                        ArtifactKind.CODER_PROGRESS: progress_supersedes,
                        ArtifactKind.IMPLEMENTATION_REPORT: (
                            previous.artifact_id if previous is not None else None
                        ),
                    },
                    seen_run_ids=seen_run_ids,
                )
                implementation = completed.artifact
                run_ids.append(completed.run_id)
                context_ids.append(completed.context_id)
                if isinstance(implementation, CoderProgressArtifact):
                    if implementation.content.checkpoint_sequence != attempt:
                        raise DeliveryContractViolation(
                            "coder-progress checkpoint_sequence must equal the run attempt"
                        )
                    task, event_id = self._transition(
                        self._repository.get(task.id),
                        TaskStatus.CONTINUE_REQUIRED,
                        reason="coder_requested_continuation",
                        source_revision=implementation.source_revision,
                        artifact_ids=(implementation.artifact_id,),
                        attempt=attempt,
                    )
                    return implementation, task, event_id
                if not isinstance(implementation, ImplementationReportArtifact):
                    raise DeliveryContractViolation(
                        "Coder run did not produce an implementation-report"
                    )
                self._validate_criteria(
                    self._repository.get(task.id),
                    "implementation-report",
                    implementation.content.acceptance_mapping,
                )
                task, event_id = self._transition(
                    self._repository.get(task.id),
                    TaskStatus.QA,
                    reason="candidate_ready",
                    source_revision=implementation.content.commit_sha,
                    artifact_ids=(implementation.artifact_id,),
                    attempt=attempt,
                )
                return implementation, task, event_id
            except AgentRunFailed as error:
                next_attempt = self._retry_failure(task, error)
                if next_attempt is not None:
                    attempt = next_attempt
                    continue
                current = self._repository.get(task.id)
                interrupted = (
                    error.result.error is not None
                    and error.result.error.code is AgentErrorCode.WORK_INTERRUPTED
                )
                interruption_exhausted = interrupted and (
                    current.work_budget_exhausted
                    or current.attempts >= current.max_attempts
                    or (
                        current.retry_policy is not None
                        and current.transient_failures(AgentRole.CODER)
                        >= current.retry_policy.transient_limit(AgentRole.CODER)
                    )
                )
                return self._blocked(
                    current,
                    RetryClassification.BUDGET_EXHAUSTED
                    if interruption_exhausted
                    else _classification(error),
                    "工程续跑额度已用尽。草稿和失败历史已保留。需要工程处理。"
                    if interruption_exhausted
                    else f"Coder failed at attempt {attempt}: {error}",
                    attempt,
                    (),
                    tuple(item.artifact_id for item in feedback),
                    source_revision=coder_source.source_revision,
                )
            except StructuredModelError as error:
                outcome = self._knowledge_failure(task, error)
                if isinstance(outcome, int):
                    attempt = outcome
                    continue
                return outcome
            except DeliveryContractViolation as error:
                self._fail_platform(
                    self._repository.get(task.id),
                    attempt,
                    str(error),
                    source_revision=coder_source.source_revision,
                )
                raise

    def _run_qa_with_retries(
        self,
        task: Task,
        plan: PlanArtifact,
        implementation: ImplementationReportArtifact,
        seen_run_ids: set[str],
        run_ids: list[str],
        context_ids: list[str],
        *,
        previous: QaReportArtifact | None = None,
    ) -> tuple[QaReportArtifact, Task] | BlockedResult:
        attempt = max(task.attempts, 1)
        while True:
            self._record_attempt(task, attempt)
            try:
                completed = self._run_agent(
                    self._repository.get(task.id),
                    AgentRole.QA,
                    attempt=attempt,
                    candidate_revision=implementation.content.commit_sha,
                    input_artifacts=(plan, implementation)
                    + ((previous,) if previous is not None else ()),
                    expected_parents=(implementation.artifact_id,),
                    expected_supersedes=previous.artifact_id if previous is not None else None,
                    seen_run_ids=seen_run_ids,
                )
                qa = completed.artifact
                if not isinstance(qa, QaReportArtifact):
                    raise DeliveryContractViolation("QA run did not produce a qa-report")
                self._validate_criteria(
                    self._repository.get(task.id), "qa-report", qa.content.criteria_results
                )
                if qa.source_revision != implementation.content.commit_sha:
                    raise DeliveryContractViolation("QA report must target the candidate revision")
                run_ids.append(completed.run_id)
                context_ids.append(completed.context_id)
                return qa, self._repository.get(task.id)
            except AgentRunFailed as error:
                next_attempt = self._retry_failure(task, error)
                if next_attempt is not None:
                    attempt = next_attempt
                    continue
                return self._blocked(
                    self._repository.get(task.id),
                    _classification(error),
                    f"QA failed at attempt {attempt}: {error}",
                    attempt,
                    (),
                    (implementation.artifact_id,),
                    source_revision=implementation.content.commit_sha,
                )
            except StructuredModelError as error:
                outcome = self._knowledge_failure(task, error)
                if isinstance(outcome, int):
                    attempt = outcome
                    continue
                return outcome
            except DeliveryContractViolation as error:
                self._fail_platform(
                    self._repository.get(task.id),
                    attempt,
                    str(error),
                    source_revision=implementation.content.commit_sha,
                )
                raise

    def _run_review_with_retries(
        self,
        task: Task,
        plan: PlanArtifact,
        implementation: ImplementationReportArtifact,
        qa: QaReportArtifact,
        seen_run_ids: set[str],
        run_ids: list[str],
        context_ids: list[str],
        *,
        previous: ReviewReportArtifact | None = None,
    ) -> tuple[ReviewReportArtifact, Task] | BlockedResult:
        attempt = max(task.attempts, 1)
        while True:
            self._record_attempt(task, attempt)
            try:
                completed = self._run_agent(
                    self._repository.get(task.id),
                    AgentRole.REVIEWER,
                    attempt=attempt,
                    candidate_revision=implementation.content.commit_sha,
                    input_artifacts=(plan, implementation, qa)
                    + ((previous,) if previous is not None else ()),
                    expected_parents=(qa.artifact_id,),
                    expected_supersedes=previous.artifact_id if previous is not None else None,
                    seen_run_ids=seen_run_ids,
                )
                review = completed.artifact
                if not isinstance(review, ReviewReportArtifact):
                    raise DeliveryContractViolation("Reviewer run did not produce a review-report")
                if review.source_revision != implementation.content.commit_sha:
                    raise DeliveryContractViolation(
                        "Review report must target the candidate revision"
                    )
                run_ids.append(completed.run_id)
                context_ids.append(completed.context_id)
                return review, self._repository.get(task.id)
            except AgentRunFailed as error:
                next_attempt = self._retry_failure(task, error)
                if next_attempt is not None:
                    attempt = next_attempt
                    continue
                return self._blocked(
                    self._repository.get(task.id),
                    _classification(error),
                    f"Reviewer failed at attempt {attempt}: {error}",
                    attempt,
                    (),
                    (qa.artifact_id,),
                    source_revision=implementation.content.commit_sha,
                )
            except StructuredModelError as error:
                outcome = self._knowledge_failure(task, error)
                if isinstance(outcome, int):
                    attempt = outcome
                    continue
                return outcome
            except DeliveryContractViolation as error:
                self._fail_platform(
                    self._repository.get(task.id),
                    attempt,
                    str(error),
                    source_revision=implementation.content.commit_sha,
                )
                raise

    def _blocked(
        self,
        task: Task,
        classification: RetryClassification,
        reason: str,
        attempt: int,
        event_ids: list[str] | tuple[str, ...],
        artifact_ids: tuple[ArtifactId, ...],
        source_revision: str | None = None,
    ) -> BlockedResult:
        baseline_input = (
            self._coder_execution_inputs.current(task, implementation=None, progress=None)
            if self._coder_execution_inputs is not None
            else None
        )
        implementation = _latest(
            self._artifacts_for_task(task.id),
            ImplementationReportArtifact,
            excluded_artifact_ids=(
                baseline_input.superseded_artifact_ids
                if baseline_input is not None
                else frozenset()
            ),
        )
        retained_candidate = None
        if implementation is not None:
            self._validate_implementation(task, implementation)
            retained_candidate = implementation.content.commit_sha
        if (
            task.engineering_policy is not None
            and self._delivery_failure_control is not None
            and classification
            in {
                RetryClassification.REQUIREMENT_AMBIGUITY,
                RetryClassification.VERIFICATION_INCONCLUSIVE,
                RetryClassification.PLATFORM_BUG,
                RetryClassification.INVALID_OUTPUT,
                RetryClassification.TRANSIENT_INFRA,
            }
        ):
            self._delivery_failure_control.wait(
                task,
                classification=classification.value,
                reason=reason,
                source_revision=source_revision or task.base_ref,
                artifact_ids=artifact_ids,
            )
        if task.status not in {TaskStatus.BLOCKED, TaskStatus.FAILED}:
            _, event_id = self._transition(
                task,
                TaskStatus.BLOCKED,
                reason=f"{classification.value}: {reason}",
                source_revision=task.base_ref if source_revision is None else source_revision,
                artifact_ids=artifact_ids,
                attempt=attempt,
            )
            event_ids = (*tuple(event_ids), event_id)
        return BlockedResult(
            task=self._repository.get(task.id),
            classification=classification,
            reason=reason,
            attempt=attempt,
            artifact_ids=artifact_ids,
            event_ids=tuple(event_ids),
            candidate_revision=retained_candidate,
        )

    def _fail_platform(
        self, task: Task, attempt: int, reason: str, *, source_revision: str
    ) -> None:
        if task.status not in {TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.FAILED}:
            if task.engineering_policy is not None and self._delivery_failure_control is not None:
                self._delivery_failure_control.wait(
                    task,
                    classification=RetryClassification.PLATFORM_BUG.value,
                    reason=reason,
                    source_revision=source_revision,
                    artifact_ids=tuple(
                        artifact.artifact_id for artifact in self._artifacts_for_task(task.id)
                    ),
                )
                return
            self._transition(
                task,
                TaskStatus.FAILED,
                reason=f"{RetryClassification.PLATFORM_BUG.value}: {reason}",
                source_revision=source_revision,
                attempt=attempt,
            )

    def _knowledge_failure(self, task: Task, error: StructuredModelError) -> int | BlockedResult:
        current = self._repository.get(task.id)
        role = {
            TaskStatus.IMPLEMENTING: AgentRole.CODER,
            TaskStatus.QA: AgentRole.QA,
            TaskStatus.REVIEW: AgentRole.REVIEWER,
        }[current.status]
        next_attempt = (
            self._record_transient(current, role, error.code.value) if error.retryable else None
        )
        if next_attempt is not None:
            return next_attempt
        events = self._repository.list_events(task.id)
        classification = {
            AgentErrorCode.INVALID_OUTPUT: RetryClassification.INVALID_OUTPUT,
            AgentErrorCode.POLICY_VIOLATION: RetryClassification.POLICY_VIOLATION,
        }.get(error.code, RetryClassification.TRANSIENT_INFRA)
        if error.retryable and current.retry_policy is not None:
            classification = RetryClassification.BUDGET_EXHAUSTED
        return self._blocked(
            self._repository.get(task.id),
            classification,
            (
                f"{role.value} knowledge preparation reached local time limit"
                if error.expandable_timeout
                else f"{role.value} knowledge preparation failed: {error.code.value}"
            ),
            current.attempts,
            (),
            tuple(a.artifact_id for a in self._artifacts_for_task(task.id)),
            source_revision=events[-1].source_revision if events else task.base_ref,
        )

    def _retry_failure(self, task: Task, error: AgentRunFailed) -> int | None:
        current = self._repository.get(task.id)
        result = error.result
        if result.error is not None and result.error.code is AgentErrorCode.WORK_INTERRUPTED:
            if result.role is not AgentRole.CODER or self._interruption_control is None:
                return None
            self._guard_write()
            return self._interruption_control.next_attempt(current, result, self._repository)
        if current.retry_policy is None:
            return (
                current.attempts + 1
                if _retryable(error) and current.attempts < current.max_attempts
                else None
            )
        failure = result.error
        if (
            failure is None
            or not failure.transient
            or failure.code not in TRANSIENT_CODES
            or result.role is AgentRole.ORCHESTRATOR
        ):
            return None
        return self._record_transient(current, result.role, failure.code.value, result.run_id)

    def _record_transient(
        self, task: Task, role: AgentRole, code: str, run_id: str | None = None
    ) -> int | None:
        if task.retry_policy is None or role is AgentRole.ORCHESTRATOR:
            return None
        self._guard_write()
        self._repository.record_retry_failure(
            task.id,
            DeliveryRetryFailure.model_validate(
                {
                    "role": role,
                    "attempt": task.attempts,
                    "code": code,
                    "run_id": run_id,
                }
            ),
        )
        updated = self._repository.get(task.id)
        return updated.attempts if updated.attempts > task.attempts else None

    def _record_attempt(self, task: Task, attempt: int) -> None:
        self._guard_write()
        self._repository.record_attempt(task.id, attempt)

    def _artifacts_for_task(self, task_id: TaskId) -> tuple[Artifact, ...]:
        return self._artifact_store.list_for_task(task_id)

    def _validate_plan(self, task: Task, plan: PlanArtifact) -> None:
        self._validate_criteria(task, "plan", plan.content.acceptance_mapping)
        if plan.source_revision != task.base_ref:
            raise DeliveryContractViolation("plan revision must match Task base_ref")

    def _validate_implementation(
        self, task: Task, implementation: ImplementationReportArtifact
    ) -> None:
        self._validate_criteria(
            task,
            "implementation-report",
            implementation.content.acceptance_mapping,
        )
        if implementation.source_revision != implementation.content.commit_sha:
            raise DeliveryContractViolation(
                "implementation-report source_revision must equal commit_sha"
            )


def _latest[
    ArtifactT: (
        PlanArtifact,
        CoderProgressArtifact,
        ImplementationReportArtifact,
        QaReportArtifact,
        ReviewReportArtifact,
    )
](
    artifacts: tuple[Artifact, ...],
    artifact_type: type[ArtifactT],
    *,
    excluded_artifact_ids: frozenset[str] = frozenset(),
) -> ArtifactT | None:
    return latest_accepted_artifact(
        artifacts, artifact_type, excluded_artifact_ids=excluded_artifact_ids
    )


def _implementation_for_feedback(
    artifacts: tuple[Artifact, ...], *, source: CoderExecutionInput | None
) -> ImplementationReportArtifact | None:
    """Select current output, retaining exact retired output only for verifier findings.

    An old candidate remains a valid parent for its historical QA/Review findings,
    but never authorizes candidate recovery or supplies the new execution source.
    """
    implementation = _latest(
        artifacts,
        ImplementationReportArtifact,
        excluded_artifact_ids=source.superseded_artifact_ids if source is not None else frozenset(),
    )
    if (
        implementation is not None
        or source is None
        or not source.superseded_implementation_artifact_ids
    ):
        return implementation
    identity = source.superseded_implementation_artifact_ids[-1]
    return next(
        (
            artifact
            for artifact in artifacts
            if isinstance(artifact, ImplementationReportArtifact)
            and artifact.artifact_id == identity
        ),
        None,
    )


def _active_progress(
    progress: CoderProgressArtifact | None,
    implementation: ImplementationReportArtifact | None,
    artifacts: tuple[Artifact, ...] = (),
) -> CoderProgressArtifact | None:
    if progress is None:
        return None
    if implementation is not None:
        order = compare_artifact_order(progress, implementation, artifacts=artifacts)
        if order is None:
            raise ArtifactOrderingError("Coder progress and candidate have no publication order")
        if order <= 0:
            return None
    return progress


def _latest_transition_attempt(events: tuple[StateEvent, ...], status: TaskStatus) -> int:
    return max((event.attempt for event in events if event.to_status is status), default=0)


def _recoverable_candidate(
    task: Task,
    events: tuple[StateEvent, ...],
    implementation: ImplementationReportArtifact | None,
) -> bool:
    """Detect a candidate persisted immediately before its QA checkpoint event."""
    if task.status is not TaskStatus.IMPLEMENTING or implementation is None or not events:
        return False
    last_event = events[-1]
    if last_event.to_status is not TaskStatus.IMPLEMENTING:
        return False
    if last_event.from_status is TaskStatus.PLANNING:
        return implementation.supersedes is None
    if last_event.from_status is TaskStatus.QUEUED:
        # Continuation output must consume the exact persisted progress checkpoint;
        # an older candidate cannot satisfy this lineage after a new resume.
        return bool(last_event.artifact_ids) and set(last_event.artifact_ids).issubset(
            implementation.parent_artifact_ids
        )
    if last_event.from_status in {TaskStatus.QA, TaskStatus.REVIEW}:
        return implementation.supersedes is not None
    return False


def _retryable(error: AgentRunFailed) -> bool:
    result = error.result
    return (
        result.status in {AgentRunStatus.TIMED_OUT, AgentRunStatus.FAILED}
        and result.error is not None
        and result.error.code
        in {
            AgentErrorCode.TIMEOUT,
            AgentErrorCode.QUOTA_EXHAUSTED,
            AgentErrorCode.RATE_LIMITED,
            AgentErrorCode.PROVIDER_UNAVAILABLE,
            AgentErrorCode.PROVIDER_ERROR,
            AgentErrorCode.INVALID_OUTPUT,
        }
    )


def _classification(error: AgentRunFailed) -> RetryClassification:
    if error.result.error is not None and error.result.error.code is AgentErrorCode.INVALID_OUTPUT:
        return RetryClassification.INVALID_OUTPUT
    if (
        error.result.error is not None
        and error.result.error.code is AgentErrorCode.POLICY_VIOLATION
    ):
        return RetryClassification.POLICY_VIOLATION
    return RetryClassification.TRANSIENT_INFRA


__all__ = [
    "BlockedResult",
    "RetryAction",
    "RetryClassification",
    "RetryDecision",
    "RetryDeliveryResult",
    "RetryResult",
    "RetryingOrchestrator",
]
