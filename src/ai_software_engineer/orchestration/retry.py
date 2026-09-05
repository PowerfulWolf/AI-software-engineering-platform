"""Bounded failure routing and restart-safe serial orchestration for T010."""

from enum import StrEnum

from ai_software_engineer.agents import AgentErrorCode, AgentRunStatus, RunId
from ai_software_engineer.context.models import ContextId
from ai_software_engineer.domain.artifact import (
    Artifact,
    ArtifactId,
    CommitSha,
    ImplementationReportArtifact,
    PlanArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
)
from ai_software_engineer.domain.enums import AgentRole, QaReportStatus, ReviewVerdict, TaskStatus
from ai_software_engineer.domain.event import EventId, StateEvent
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
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
        task = self._repository.get(task_id)
        if task.status in {TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.FAILED}:
            raise TaskNotRunnable(f"Task {task.id} is terminal at {task.status.value}")

        existing_events = self._repository.list_events(task.id)
        recovered_attempt = max((event.attempt for event in existing_events), default=0)
        if recovered_attempt > task.attempts:
            self._record_attempt(task, recovered_attempt)
            task = self._repository.get(task.id)

        artifacts = self._artifacts_for_task(task.id)
        plan = _latest(artifacts, PlanArtifact)
        implementation = _latest(artifacts, ImplementationReportArtifact)
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
                RetryClassification.REQUIREMENT_AMBIGUITY,
                "cannot continue without a persisted plan Artifact",
                max(task.attempts, 1),
                event_ids,
                (),
            )

        while True:
            task = self._repository.get(task.id)
            if task.status is TaskStatus.IMPLEMENTING:
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
                        seen_run_ids,
                        run_ids,
                        context_ids,
                    )
                    if isinstance(result, BlockedResult):
                        return result.model_copy(
                            update={"event_ids": tuple(event_ids) + result.event_ids}
                        )
                    implementation, task, event_id = result
                    event_ids.append(event_id)

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
                    if qa is not None and qa.source_revision == implementation.content.commit_sha
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
                    )
                    if isinstance(qa_result, BlockedResult):
                        return qa_result.model_copy(
                            update={"event_ids": tuple(event_ids) + qa_result.event_ids}
                        )
                    qa, task = qa_result
                else:
                    qa = current_qa
                if qa.content.status is QaReportStatus.FAIL:
                    if task.attempts >= task.max_attempts:
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
                    )
                    if isinstance(review_result, BlockedResult):
                        return review_result.model_copy(
                            update={"event_ids": tuple(event_ids) + review_result.event_ids}
                        )
                    review, task = review_result
                else:
                    review = current_review
                if review.content.verdict is ReviewVerdict.REJECT:
                    if task.attempts >= task.max_attempts:
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
                if _retryable(error) and attempt < task.max_attempts:
                    attempt += 1
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
        seen_run_ids: set[str],
        run_ids: list[str],
        context_ids: list[str],
    ) -> tuple[ImplementationReportArtifact, Task, str] | BlockedResult:
        attempt = max(task.attempts, 1)
        feedback: tuple[Artifact, ...] = tuple(item for item in (qa, review) if item is not None)
        inputs = (plan, *feedback)
        parents = tuple(item.artifact_id for item in inputs)
        while True:
            self._record_attempt(task, attempt)
            try:
                completed = self._run_agent(
                    self._repository.get(task.id),
                    AgentRole.CODER,
                    attempt=attempt,
                    candidate_revision=None,
                    input_artifacts=inputs,
                    expected_parents=parents,
                    expected_supersedes=previous.artifact_id if previous is not None else None,
                    seen_run_ids=seen_run_ids,
                )
                implementation = completed.artifact
                if not isinstance(implementation, ImplementationReportArtifact):
                    raise DeliveryContractViolation(
                        "Coder run did not produce an implementation-report"
                    )
                self._validate_criteria(
                    self._repository.get(task.id),
                    "implementation-report",
                    implementation.content.acceptance_mapping,
                )
                run_ids.append(completed.run_id)
                context_ids.append(completed.context_id)
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
                if _retryable(error) and attempt < task.max_attempts:
                    attempt += 1
                    continue
                return self._blocked(
                    self._repository.get(task.id),
                    _classification(error),
                    f"Coder failed at attempt {attempt}: {error}",
                    attempt,
                    (),
                    tuple(item.artifact_id for item in feedback),
                )
            except DeliveryContractViolation as error:
                self._fail_platform(self._repository.get(task.id), attempt, str(error))
                raise

    def _run_qa_with_retries(
        self,
        task: Task,
        plan: PlanArtifact,
        implementation: ImplementationReportArtifact,
        seen_run_ids: set[str],
        run_ids: list[str],
        context_ids: list[str],
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
                    input_artifacts=(plan, implementation),
                    expected_parents=(implementation.artifact_id,),
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
                if _retryable(error) and attempt < task.max_attempts:
                    attempt += 1
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
            except DeliveryContractViolation as error:
                self._fail_platform(self._repository.get(task.id), attempt, str(error))
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
                    input_artifacts=(plan, implementation, qa),
                    expected_parents=(qa.artifact_id,),
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
                if _retryable(error) and attempt < task.max_attempts:
                    attempt += 1
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
            except DeliveryContractViolation as error:
                self._fail_platform(self._repository.get(task.id), attempt, str(error))
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
        )

    def _fail_platform(self, task: Task, attempt: int, reason: str) -> None:
        if task.status not in {TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.FAILED}:
            self._transition(
                task,
                TaskStatus.FAILED,
                reason=f"{RetryClassification.PLATFORM_BUG.value}: {reason}",
                source_revision=task.base_ref,
                attempt=attempt,
            )

    def _record_attempt(self, task: Task, attempt: int) -> None:
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
    ArtifactT: (PlanArtifact, ImplementationReportArtifact, QaReportArtifact, ReviewReportArtifact)
](artifacts: tuple[Artifact, ...], artifact_type: type[ArtifactT]) -> ArtifactT | None:
    candidates = tuple(item for item in artifacts if isinstance(item, artifact_type))
    return max(candidates, key=lambda item: (item.created_at, item.artifact_id), default=None)


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
