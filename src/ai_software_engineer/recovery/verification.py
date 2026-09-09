"""Internal, admission-gated verification of an existing candidate.

This is not a production recovery entry. Its injected admission port must establish
native provenance, current authority and durable at-most-once invocation before execution.
Terminal Tasks and their events are never rewritten or presented as newly successful.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise
from typing import Protocol

from ai_software_engineer.agents import AgentAdapter, AgentRequest, AgentResult, AgentRunStatus
from ai_software_engineer.artifacts import ArtifactStore, artifact_digest
from ai_software_engineer.domain import AgentDefinition, AgentRole, Task, TaskStatus
from ai_software_engineer.domain.artifact import (
    ImplementationReportArtifact,
    PlanArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
)
from ai_software_engineer.domain.enums import QaReportStatus, ReviewVerdict
from ai_software_engineer.orchestration.context import RunContextBuilder
from ai_software_engineer.orchestration.runner import (
    Clock,
    OrchestrationIdentityFactory,
    SerialOrchestrator,
)
from ai_software_engineer.recovery.models import RecoveryRejected, digest
from ai_software_engineer.recovery.verification_records import CandidateVerificationInputs
from ai_software_engineer.store import TaskRepository


@dataclass(frozen=True, slots=True)
class CandidateVerificationResult:
    """Verification facts, deliberately not DeliveryResult or a Task status."""

    inputs: CandidateVerificationInputs
    plan: PlanArtifact
    implementation: ImplementationReportArtifact
    qa: QaReportArtifact
    review: ReviewReportArtifact | None

    @property
    def verified(self) -> bool:
        return (
            self.qa.content.status is QaReportStatus.PASS
            and self.review is not None
            and self.review.content.verdict is ReviewVerdict.APPROVE
        )

    @property
    def candidate_revision(self) -> str:
        return self.inputs.candidate_revision


class VerificationAdmission(Protocol):
    """Trusted production port: validate approved facts and consume a durable role slot.

    Must refuse missing/stale approval, repeated or uncertain invocation, wrong role order,
    unavailable allocation and current candidate/policy drift. A plain digest is not authority.
    Called immediately before each adapter call, with the complete exact AgentRequest.
    """

    def admit(self, inputs: CandidateVerificationInputs, request: AgentRequest) -> None: ...

    def validate_configuration(
        self,
        inputs: CandidateVerificationInputs,
        definitions: Mapping[AgentRole, AgentDefinition],
    ) -> None: ...


class _AdmittedVerifier:
    def __init__(
        self,
        owner: CandidateVerificationRunner,
        inputs: CandidateVerificationInputs,
    ) -> None:
        self.owner, self.inputs = owner, inputs

    def run(self, request: AgentRequest) -> AgentResult:
        if request.role not in (AgentRole.QA, AgentRole.REVIEWER):
            raise RecoveryRejected("candidate verification cannot invoke Coder or Planner")
        task, _, _ = self.owner._read_inputs(self.inputs)
        self.owner._admission.admit(self.inputs, request)
        result = self.owner._adapter.run(request)
        if result.status is AgentRunStatus.SUCCEEDED:
            artifact = result.artifact
            expected = QaReportArtifact if request.role is AgentRole.QA else ReviewReportArtifact
            if not isinstance(artifact, expected):
                raise RecoveryRejected("verification output has the wrong artifact kind")
            assert isinstance(artifact, (QaReportArtifact, ReviewReportArtifact))
            self.owner._validate_verdict(
                task, artifact, request.role, self.inputs.candidate_revision
            )
        return result


class CandidateVerificationRunner:
    """Reuse shared role guards without any terminal Task transition or Coder retry."""

    def __init__(
        self,
        *,
        repository: TaskRepository,
        artifact_store: ArtifactStore,
        context_builder: RunContextBuilder,
        agent_adapter: AgentAdapter,
        agent_definitions: Mapping[AgentRole, AgentDefinition],
        admission: VerificationAdmission,
        identities: OrchestrationIdentityFactory | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repository, self._artifacts = repository, artifact_store
        self._contexts, self._adapter = context_builder, agent_adapter
        self._definitions = dict(agent_definitions)
        self._admission, self._identities, self._clock = admission, identities, clock

    def verify_candidate(self, inputs: CandidateVerificationInputs) -> CandidateVerificationResult:
        inputs = CandidateVerificationInputs.model_validate(inputs.to_wire())
        task, plan, implementation = self._read_inputs(inputs)
        self._admission.validate_configuration(inputs, self._definitions)
        runner = SerialOrchestrator(
            repository=self._repository,
            artifact_store=self._artifacts,
            context_builder=self._contexts,
            agent_adapter=_AdmittedVerifier(self, inputs),
            agent_definitions=self._definitions,
            identities=self._identities,
            clock=self._clock,
        )
        # Reuse the same request/context/output/store guards as normal delivery. Do NOT call
        # run_task, _transition or record_attempt: the original Task remains terminal.
        seen = {a.producer.run_id for a in self._artifacts.list_for_task(task.id)}
        seen.update(inputs.prior_run_ids)
        qa = runner._run_agent(
            task,
            AgentRole.QA,
            attempt=max(task.attempts, 1),
            candidate_revision=inputs.candidate_revision,
            input_artifacts=(plan, implementation),
            expected_parents=(implementation.artifact_id,),
            seen_run_ids=seen,
        ).artifact
        if not isinstance(qa, QaReportArtifact):
            raise RecoveryRejected("verification did not produce a QA report")
        self._validate_verdict(task, qa, AgentRole.QA, inputs.candidate_revision)
        self._read_inputs(inputs)
        review: ReviewReportArtifact | None = None
        if qa.content.status is QaReportStatus.PASS:
            artifact = runner._run_agent(
                task,
                AgentRole.REVIEWER,
                attempt=max(task.attempts, 1),
                candidate_revision=inputs.candidate_revision,
                input_artifacts=(plan, implementation, qa),
                expected_parents=(qa.artifact_id,),
                seen_run_ids=seen,
            ).artifact
            if not isinstance(artifact, ReviewReportArtifact):
                raise RecoveryRejected("verification did not produce a Review report")
            review = artifact
            self._validate_verdict(task, review, AgentRole.REVIEWER, inputs.candidate_revision)
            self._read_inputs(inputs)
        return CandidateVerificationResult(inputs, plan, implementation, qa, review)

    def _read_inputs(
        self, inputs: CandidateVerificationInputs
    ) -> tuple[Task, PlanArtifact, ImplementationReportArtifact]:
        task = self._repository.get(inputs.task_id)
        events = self._repository.list_events(task.id)
        revision = self._repository.current_revision(task.id)
        if (
            task.status not in (TaskStatus.BLOCKED, TaskStatus.FAILED)
            or digest(task.to_wire()) != inputs.task_sha256
            or revision != inputs.task_revision
            or len(events) != revision
            or len(events) < 2
            or events[-1].from_status is not TaskStatus.QA
            or events[-1].to_status is not task.status
            or events[-2].to_status is not TaskStatus.QA
            or events[-2].reason != "candidate_ready"
            or events[-2].source_revision != inputs.candidate_revision
            or events[-2].artifact_ids != (inputs.implementation_id,)
            or len(inputs.candidate_revision) not in (40, 64)
            or any(c not in "0123456789abcdef" for c in inputs.candidate_revision)
        ):
            raise RecoveryRejected("terminal candidate checkpoint differs from pinned inputs")
        for previous, current in pairwise(events):
            if current.task_id != task.id or current.from_status is not previous.to_status:
                raise RecoveryRejected("original event chain is inconsistent")
        if events[0].task_id != task.id or events[0].from_status is not TaskStatus.NEW:
            raise RecoveryRejected("original event chain has no NEW origin")
        plan = self._artifacts.get(inputs.plan_id)
        implementation = self._artifacts.get(inputs.implementation_id)
        if not isinstance(plan, PlanArtifact) or not isinstance(
            implementation, ImplementationReportArtifact
        ):
            raise RecoveryRejected("original plan or implementation artifact has the wrong kind")
        if (
            plan.task_id != task.id
            or implementation.task_id != task.id
            or artifact_digest(plan) != inputs.plan_sha256
            or artifact_digest(implementation) != inputs.implementation_sha256
            or plan.source_revision != task.base_ref
            or plan.parent_artifact_ids
            or implementation.parent_artifact_ids != (plan.artifact_id,)
            or implementation.supersedes is not None
            or implementation.source_revision != inputs.candidate_revision
            or implementation.content.commit_sha != inputs.candidate_revision
            or plan.producer.run_id == implementation.producer.run_id
        ):
            raise RecoveryRejected("original candidate artifact lineage differs from pinned inputs")
        expected = {c.id for c in task.acceptance_criteria}
        if {m.criterion_id for m in plan.content.acceptance_mapping} != expected or {
            m.criterion_id for m in implementation.content.acceptance_mapping
        } != expected:
            raise RecoveryRejected("original artifacts do not cover the approved criteria")
        self._validate_independence(task)
        if (
            self._repository.get(task.id) != task
            or self._repository.current_revision(task.id) != revision
        ):
            raise RecoveryRejected("original task changed during verification")
        return task, plan, implementation

    def _validate_independence(self, task: Task) -> None:
        roles = (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER)
        history = self._artifacts.list_for_task(task.id)
        for role in (AgentRole.QA, AgentRole.REVIEWER):
            definition = self._definitions.get(role)
            if definition is None or definition.role is not role:
                raise RecoveryRejected("missing verifier definition")
            if any(
                a.producer.agent_id == definition.id
                and a.producer.role in roles
                and a.producer.role is not role
                for a in history
            ):
                raise RecoveryRejected("verifier would judge its own historical work")

    def _validate_verdict(
        self,
        task: Task,
        artifact: QaReportArtifact | ReviewReportArtifact,
        role: AgentRole,
        candidate: str,
    ) -> None:
        if (
            artifact.source_revision != candidate
            or artifact.producer.agent_id != self._definitions[role].id
        ):
            raise RecoveryRejected("verifier output has the wrong candidate or Agent identity")
        if isinstance(artifact, QaReportArtifact) and {
            c.criterion_id for c in artifact.content.criteria_results
        } != {c.id for c in task.acceptance_criteria}:
            raise RecoveryRejected("QA report does not cover the approved criteria")
