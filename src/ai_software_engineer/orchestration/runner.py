"""Fail-closed serial Orchestrator application service for the v0.1 happy path."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from ai_software_engineer.agents import (
    ROLE_OUTPUT_SCHEMA,
    AgentAdapter,
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
    RunId,
)
from ai_software_engineer.agents.continuation import InterruptionRetryControl
from ai_software_engineer.agents.execution import AgentInvocationControl
from ai_software_engineer.artifacts import ArtifactStore, seal_artifact
from ai_software_engineer.artifacts.ordering import (
    ArtifactOrderingError,
    compare_artifact_order,
    latest_accepted_artifact,
)
from ai_software_engineer.context.models import ContextId
from ai_software_engineer.domain.agent import ROLE_OUTPUTS, AgentDefinition
from ai_software_engineer.domain.artifact import (
    Artifact,
    ArtifactId,
    CoderProgressArtifact,
    CommitSha,
    ImplementationReportArtifact,
    PlanArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
)
from ai_software_engineer.domain.coder_work import (
    select_coder_work_slice,
    validate_coder_slice_output,
)
from ai_software_engineer.domain.enums import (
    AgentRole,
    ArtifactKind,
    QaReportStatus,
    ReviewVerdict,
    TaskStatus,
)
from ai_software_engineer.domain.event import EventId
from ai_software_engineer.domain.execution_baseline import (
    CoderExecutionInput,
    resolve_coder_execution_input,
)
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.task import Task, TaskId
from ai_software_engineer.orchestration.context import RunContextBuilder
from ai_software_engineer.orchestration.disposition_port import DeliveryFailureControl
from ai_software_engineer.orchestration.execution_baseline import CoderExecutionInputResolver
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.orchestration.steps import BoundedRunControl
from ai_software_engineer.orchestration.verification_reservation import VerificationReservation
from ai_software_engineer.store import TaskRepository

Clock = Callable[[], datetime]


class OrchestrationIdentityFactory(Protocol):
    """Generate identities without hiding time or randomness inside the runner."""

    def new_run_id(self, task_id: TaskId, role: AgentRole, attempt: int) -> RunId: ...

    def new_event_id(
        self,
        task_id: TaskId,
        from_status: TaskStatus,
        to_status: TaskStatus,
        attempt: int,
    ) -> EventId: ...


class UuidOrchestrationIdentityFactory:
    """Production default using opaque UUID-backed run and event identities."""

    def new_run_id(self, task_id: TaskId, role: AgentRole, attempt: int) -> RunId:
        del task_id, role, attempt
        return f"run_{uuid4().hex}"

    def new_event_id(
        self,
        task_id: TaskId,
        from_status: TaskStatus,
        to_status: TaskStatus,
        attempt: int,
    ) -> EventId:
        del task_id, from_status, to_status, attempt
        return f"evt_{uuid4().hex}"


class DeliveryResult(DomainModel):
    """Auditable output of one completed serial Task delivery."""

    task: Task
    candidate_revision: CommitSha
    artifact_ids: tuple[ArtifactId, ArtifactId, ArtifactId, ArtifactId]
    context_manifest_ids: tuple[ContextId, ContextId, ContextId, ContextId]
    run_ids: tuple[RunId, RunId, RunId, RunId]
    event_ids: tuple[EventId, EventId, EventId, EventId, EventId]


class OrchestrationError(RuntimeError):
    """Base class for stable application-level orchestration failures."""


class OrchestratorConfigurationError(OrchestrationError):
    """Raised before execution when role definitions are missing or mis-keyed."""


class TaskNotRunnable(OrchestrationError):
    """Raised when the T009 runner receives a Task outside NEW."""


class AgentRunFailed(OrchestrationError):
    """Raised when an Agent run has no successful typed Artifact."""

    def __init__(self, result: AgentResult) -> None:
        self.result = result
        detail = result.error.message if result.error is not None else result.status.value
        super().__init__(f"{result.role.value} run {result.run_id} failed: {detail}")


class UnexpectedVerdict(OrchestrationError):
    """Raised when T009 encounters a valid verdict that requires T010 routing."""


class DeliveryContractViolation(OrchestrationError):
    """Raised when cross-object delivery identities or gates do not align."""


@dataclass(frozen=True, slots=True)
class _CompletedRun:
    artifact: Artifact
    context_id: ContextId
    run_id: RunId


class DeliveryTransitionGate(Protocol):
    def begin_task(self, task: Task) -> None: ...

    def before_transition(
        self, task: Task, target: TaskStatus, artifact_ids: tuple[str, ...]
    ) -> None: ...


class SerialOrchestrator:
    """Drive exactly one Coder → QA → Reviewer attempt without retry routing."""

    def __init__(
        self,
        *,
        repository: TaskRepository,
        artifact_store: ArtifactStore,
        context_builder: RunContextBuilder,
        agent_adapter: AgentAdapter,
        agent_definitions: Mapping[AgentRole, AgentDefinition],
        identities: OrchestrationIdentityFactory | None = None,
        clock: Clock | None = None,
        transition_gate: DeliveryTransitionGate | None = None,
        execution_control: BoundedRunControl | None = None,
        interruption_control: InterruptionRetryControl | None = None,
        delivery_failure_control: DeliveryFailureControl | None = None,
        invocation_control: AgentInvocationControl | None = None,
        coder_execution_inputs: CoderExecutionInputResolver | None = None,
        verification_reservation: VerificationReservation | None = None,
    ) -> None:
        self._repository = repository
        self._transition_gate = transition_gate
        self.execution_control = execution_control
        self._interruption_control = interruption_control
        self._delivery_failure_control = delivery_failure_control
        self._invocation_control = invocation_control
        self._coder_execution_inputs = coder_execution_inputs
        self._verification_reservation = verification_reservation
        self._artifact_store = artifact_store
        self._context_builder = context_builder
        self._agent_adapter = agent_adapter
        self._definitions = dict(agent_definitions)
        self._identities = identities or UuidOrchestrationIdentityFactory()
        self._clock = clock or _utc_now
        self._validate_configuration()

    def run_task(self, task_id: TaskId) -> DeliveryResult:
        """Run the one-attempt v0.1 happy path from NEW through DONE."""
        task = self._repository.get(task_id)
        if task.status is not TaskStatus.NEW:
            raise TaskNotRunnable(f"Task {task.id} must be NEW, not {task.status.value}")
        if self._transition_gate is not None:
            self._transition_gate.begin_task(task)

        attempt = 1
        seen_run_ids: set[RunId] = set()
        event_ids: list[EventId] = []
        task, event_id = self._transition(
            task,
            TaskStatus.PLANNING,
            reason="task_validated",
            source_revision=task.base_ref,
            attempt=attempt,
        )
        event_ids.append(event_id)

        plan_run = self._run_agent(
            task,
            AgentRole.ORCHESTRATOR,
            attempt=attempt,
            candidate_revision=None,
            input_artifacts=(),
            expected_parents=(),
            seen_run_ids=seen_run_ids,
        )
        plan = _require_plan(plan_run.artifact)
        self._validate_criteria(task, "plan", plan.content.acceptance_mapping)
        if plan.source_revision != task.base_ref:
            raise DeliveryContractViolation("plan revision must match Task base_ref")
        task, event_id = self._transition(
            task,
            TaskStatus.IMPLEMENTING,
            reason="plan_validated",
            source_revision=task.base_ref,
            artifact_ids=(plan.artifact_id,),
            attempt=attempt,
        )
        event_ids.append(event_id)

        coder_run = self._run_agent(
            task,
            AgentRole.CODER,
            attempt=attempt,
            candidate_revision=None,
            input_artifacts=(plan,),
            expected_parents=(plan.artifact_id,),
            seen_run_ids=seen_run_ids,
        )
        implementation = _require_implementation(coder_run.artifact)
        self._validate_criteria(
            task,
            "implementation-report",
            implementation.content.acceptance_mapping,
        )
        candidate = implementation.content.commit_sha
        if implementation.source_revision != candidate:
            raise DeliveryContractViolation(
                "implementation-report source_revision must equal commit_sha"
            )
        task, event_id = self._transition(
            task,
            TaskStatus.QA,
            reason="candidate_ready",
            source_revision=candidate,
            artifact_ids=(implementation.artifact_id,),
            attempt=attempt,
        )
        event_ids.append(event_id)

        qa_run = self._run_agent(
            task,
            AgentRole.QA,
            attempt=attempt,
            candidate_revision=candidate,
            input_artifacts=(plan, implementation),
            expected_parents=(implementation.artifact_id,),
            seen_run_ids=seen_run_ids,
        )
        qa = _require_qa(qa_run.artifact)
        self._validate_criteria(task, "qa-report", qa.content.criteria_results)
        if qa.source_revision != candidate:
            raise DeliveryContractViolation("QA report must target the candidate revision")
        if qa.content.status is not QaReportStatus.PASS:
            raise UnexpectedVerdict(f"QA returned {qa.content.status.value}; T010 routing required")
        task, event_id = self._transition(
            task,
            TaskStatus.REVIEW,
            reason="qa_passed",
            source_revision=candidate,
            artifact_ids=(qa.artifact_id,),
            attempt=attempt,
        )
        event_ids.append(event_id)

        review_run = self._run_agent(
            task,
            AgentRole.REVIEWER,
            attempt=attempt,
            candidate_revision=candidate,
            input_artifacts=(plan, implementation, qa),
            expected_parents=(qa.artifact_id,),
            seen_run_ids=seen_run_ids,
        )
        review = _require_review(review_run.artifact)
        if review.source_revision != candidate:
            raise DeliveryContractViolation("Review report must target the candidate revision")
        if review.content.verdict is not ReviewVerdict.APPROVE:
            raise UnexpectedVerdict(
                f"Reviewer returned {review.content.verdict.value}; T010 routing required"
            )

        artifact_ids = (
            plan.artifact_id,
            implementation.artifact_id,
            qa.artifact_id,
            review.artifact_id,
        )
        task, event_id = self._transition(
            task,
            TaskStatus.DONE,
            reason="review_approved",
            source_revision=candidate,
            artifact_ids=artifact_ids,
            attempt=attempt,
        )
        event_ids.append(event_id)
        return DeliveryResult(
            task=task,
            candidate_revision=candidate,
            artifact_ids=artifact_ids,
            context_manifest_ids=(
                plan_run.context_id,
                coder_run.context_id,
                qa_run.context_id,
                review_run.context_id,
            ),
            run_ids=(
                plan_run.run_id,
                coder_run.run_id,
                qa_run.run_id,
                review_run.run_id,
            ),
            event_ids=(
                event_ids[0],
                event_ids[1],
                event_ids[2],
                event_ids[3],
                event_ids[4],
            ),
        )

    def _run_agent(
        self,
        task: Task,
        role: AgentRole,
        *,
        attempt: int,
        candidate_revision: str | None,
        input_artifacts: tuple[Artifact, ...],
        expected_parents: tuple[ArtifactId, ...],
        seen_run_ids: set[RunId],
        expected_supersedes: ArtifactId | None = None,
        expected_supersedes_by_kind: Mapping[ArtifactKind, ArtifactId | None] | None = None,
    ) -> _CompletedRun:
        source = (
            self._current_coder_input(task)
            if role in {AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER}
            else None
        )
        if source is not None and role is AgentRole.CODER:
            candidate_revision = source.source_revision
        if self.execution_control is not None:
            self.execution_control.before_run(
                task, role, attempt, candidate_revision or task.base_ref
            )
        definition = self._definitions[role]
        context = self._context_builder.build(
            task,
            definition,
            attempt=attempt,
            candidate_revision=candidate_revision,
            input_artifacts=input_artifacts,
        )
        run_id = self._identities.new_run_id(task.id, role, attempt)
        progress_inputs = tuple(
            artifact for artifact in input_artifacts if isinstance(artifact, CoderProgressArtifact)
        )
        if len(progress_inputs) > 1:
            raise DeliveryContractViolation("Coder run received multiple progress checkpoints")
        progress = progress_inputs[0] if progress_inputs else None
        request = AgentRequest(
            run_id=run_id,
            task_id=task.id,
            role=role,
            attempt=attempt,
            source_revision=context.source_revision,
            context_manifest_id=context.context_id,
            input_artifact_ids=tuple(artifact.artifact_id for artifact in input_artifacts),
            expected_parent_artifact_ids=expected_parents,
            expected_supersedes_by_kind=(
                dict(expected_supersedes_by_kind)
                if expected_supersedes_by_kind is not None
                else {kind: expected_supersedes for kind in ROLE_OUTPUTS[role]}
            ),
            permissions=definition.permissions,
            output_schema=ROLE_OUTPUT_SCHEMA[role],
            timeout_seconds=definition.timeout_seconds,
            continuation_checkpoint_id=(progress.artifact_id if progress is not None else None),
            continuation_changed_paths=(
                tuple(sorted(item.path for item in progress.content.changed_files))
                if progress is not None
                else ()
            ),
            execution_baseline_sha256=(
                source.baseline.binding_sha256
                if source is not None and source.baseline is not None
                else None
            ),
            execution_base_ref=(
                source.execution_base_ref
                if source is not None and source.baseline is not None
                else None
            ),
            work_slice=(
                select_coder_work_slice(
                    task,
                    next(a for a in input_artifacts if isinstance(a, PlanArtifact)),
                    attempt=attempt,
                    source_revision=context.source_revision,
                    progress=progress,
                )
                if role is AgentRole.CODER
                else None
            ),
        )
        if self._invocation_control is not None and role is not AgentRole.ORCHESTRATOR:
            request = self._invocation_control.prepare(request)
        if request.run_id in seen_run_ids:
            raise DeliveryContractViolation(f"duplicate Agent run ID: {request.run_id}")
        seen_run_ids.add(request.run_id)
        replayed = (
            self._invocation_control.result(request)
            if self._invocation_control is not None and role is not AgentRole.ORCHESTRATOR
            else None
        )
        result = replayed or self._agent_adapter.run(request)
        self._guard_write()
        self._validate_result_identity(request, result)
        if self._invocation_control is not None and role is not AgentRole.ORCHESTRATOR:
            self._invocation_control.completed(request, result)
        if result.status is not AgentRunStatus.SUCCEEDED or result.artifact is None:
            raise AgentRunFailed(result)
        if request.work_slice is not None:
            validate_coder_slice_output(request.work_slice, result.artifact)
        if result.artifact.parent_artifact_ids != expected_parents:
            raise AgentRunFailed(
                result.model_copy(
                    update={
                        "status": AgentRunStatus.FAILED,
                        "artifact": None,
                        "error": AgentFailure(
                            code=AgentErrorCode.INVALID_OUTPUT,
                            message=(
                                f"{role.value} Artifact parent lineage does not match its inputs"
                            ),
                            transient=False,
                        ),
                    }
                )
            )
        required_supersedes = expected_supersedes
        if expected_supersedes_by_kind is not None:
            if result.artifact.kind not in expected_supersedes_by_kind:
                raise DeliveryContractViolation(
                    f"{role.value} Artifact kind has no supersedes contract"
                )
            required_supersedes = expected_supersedes_by_kind[result.artifact.kind]
        if result.artifact.supersedes != required_supersedes:
            raise AgentRunFailed(
                result.model_copy(
                    update={
                        "status": AgentRunStatus.FAILED,
                        "artifact": None,
                        "error": AgentFailure(
                            code=AgentErrorCode.INVALID_OUTPUT,
                            message=(
                                f"{role.value} Artifact supersedes lineage does not match "
                                "the retry input"
                            ),
                            transient=False,
                        ),
                    }
                )
            )
        sealed = seal_artifact(result.artifact, validated_at=self._clock())
        self._guard_write()
        reference = self._artifact_store.put(sealed)
        persisted = self._artifact_store.get(reference.artifact_id)
        if request.work_slice is not None:
            validate_coder_slice_output(request.work_slice, persisted)
        return _CompletedRun(
            artifact=persisted,
            context_id=request.context_manifest_id,
            run_id=request.run_id,
        )

    def _current_coder_input(self, task: Task) -> CoderExecutionInput:
        artifacts = self._artifact_store.list_for_task(task.id)
        baseline_input = (
            self._coder_execution_inputs.current(task, implementation=None, progress=None)
            if self._coder_execution_inputs is not None
            else None
        )
        excluded = (
            baseline_input.superseded_artifact_ids if baseline_input is not None else frozenset()
        )
        implementation = latest_accepted_artifact(
            artifacts, ImplementationReportArtifact, excluded_artifact_ids=excluded
        )
        progress = latest_accepted_artifact(
            artifacts, CoderProgressArtifact, excluded_artifact_ids=excluded
        )
        if progress is not None and implementation is not None:
            order = compare_artifact_order(progress, implementation, artifacts=artifacts)
            if order is None:
                raise ArtifactOrderingError(
                    "Coder progress and candidate have no publication order"
                )
            if order <= 0:
                progress = None
        if self._coder_execution_inputs is not None:
            return self._coder_execution_inputs.current(
                task, implementation=implementation, progress=progress
            )
        return resolve_coder_execution_input(
            task, implementation=implementation, progress=progress, baseline=None
        )

    def _transition(
        self,
        task: Task,
        to_status: TaskStatus,
        *,
        reason: str,
        source_revision: str,
        attempt: int,
        artifact_ids: tuple[ArtifactId, ...] = (),
    ) -> tuple[Task, EventId]:
        self._guard_write()
        if self._transition_gate is not None:
            self._transition_gate.before_transition(task, to_status, artifact_ids)
        event_id = self._identities.new_event_id(
            task.id,
            task.status,
            to_status,
            attempt,
        )
        event = build_event(
            task,
            to_status,
            event_id=event_id,
            reason=reason,
            source_revision=source_revision,
            artifact_ids=artifact_ids,
            attempt=attempt,
            occurred_at=self._clock(),
        )
        self._guard_write()
        self._repository.append_event(event)
        return self._repository.get(task.id), event_id

    def _guard_write(self) -> None:
        if self.execution_control is not None:
            self.execution_control.before_write()

    def _validate_configuration(self) -> None:
        expected_roles = set(AgentRole)
        if set(self._definitions) != expected_roles:
            missing = sorted(role.value for role in expected_roles - set(self._definitions))
            extra = sorted(str(role) for role in set(self._definitions) - expected_roles)
            raise OrchestratorConfigurationError(
                f"Agent Definitions must cover all roles; missing={missing}, extra={extra}"
            )
        for role, definition in self._definitions.items():
            if definition.role is not role:
                raise OrchestratorConfigurationError(
                    f"Agent Definition key {role.value} contains {definition.role.value}"
                )
        agent_ids = tuple(definition.id for definition in self._definitions.values())
        if len(set(agent_ids)) != len(agent_ids):
            raise OrchestratorConfigurationError("Agent Definition IDs must be unique")

    @staticmethod
    def _validate_result_identity(request: AgentRequest, result: AgentResult) -> None:
        if (
            result.run_id != request.run_id
            or result.task_id != request.task_id
            or result.role is not request.role
            or result.attempt != request.attempt
            or result.source_revision != request.source_revision
            or result.context_manifest_id != request.context_manifest_id
        ):
            raise DeliveryContractViolation("AgentResult does not echo AgentRequest identity")

    @staticmethod
    def _validate_criteria(task: Task, label: str, mappings: tuple[object, ...]) -> None:
        expected = {criterion.id for criterion in task.acceptance_criteria}
        received = {getattr(mapping, "criterion_id", None) for mapping in mappings}
        if received != expected:
            raise DeliveryContractViolation(
                f"{label} acceptance criteria do not exactly cover the Task"
            )


def _require_plan(artifact: Artifact) -> PlanArtifact:
    if not isinstance(artifact, PlanArtifact):
        raise DeliveryContractViolation("planning run did not produce a plan")
    return artifact


def _require_implementation(artifact: Artifact) -> ImplementationReportArtifact:
    if not isinstance(artifact, ImplementationReportArtifact):
        raise DeliveryContractViolation("Coder run did not produce an implementation-report")
    return artifact


def _require_qa(artifact: Artifact) -> QaReportArtifact:
    if not isinstance(artifact, QaReportArtifact):
        raise DeliveryContractViolation("QA run did not produce a qa-report")
    return artifact


def _require_review(artifact: Artifact) -> ReviewReportArtifact:
    if not isinstance(artifact, ReviewReportArtifact):
        raise DeliveryContractViolation("Reviewer run did not produce a review-report")
    return artifact


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "AgentRunFailed",
    "DeliveryContractViolation",
    "DeliveryResult",
    "OrchestrationError",
    "OrchestrationIdentityFactory",
    "OrchestratorConfigurationError",
    "SerialOrchestrator",
    "TaskNotRunnable",
    "UnexpectedVerdict",
    "UuidOrchestrationIdentityFactory",
]
