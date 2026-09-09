"""Current-fact and durable at-most-once admission; no model or Task mutation."""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Protocol

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.artifacts import ArtifactStore, artifact_digest
from ai_software_engineer.domain.agent import AgentDefinition
from ai_software_engineer.domain.artifact import QaReportArtifact
from ai_software_engineer.domain.enums import AgentRole, QaReportStatus
from ai_software_engineer.recovery.models import (
    RecoveryApprovalCommand,
    RecoveryAuthorization,
    RecoveryRejected,
    VerifiedRecoveryDecision,
)
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.recovery.verification import CandidateVerificationResult
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationCompletion,
    CandidateVerificationInputs,
    CandidateVerificationInvocation,
    CandidateVerificationPlan,
)


class VerificationFacts(Protocol):
    """Resolve authoritative native/current facts, not just caller-supplied hashes."""

    def validate(self, plan: CandidateVerificationPlan) -> None: ...


class VerificationHuman(Protocol):
    def verify(self, command: RecoveryApprovalCommand) -> VerifiedRecoveryDecision: ...


class ExplicitVerificationHuman:
    """Local human confirmation for this exact candidate verification plan only."""

    def __init__(self, confirmed_plan: str | None) -> None:
        self.confirmed_plan = confirmed_plan

    def verify(self, command: RecoveryApprovalCommand) -> VerifiedRecoveryDecision:
        if self.confirmed_plan != command.plan_sha256:
            raise RecoveryRejected("explicit confirmation of the verification plan is required")
        return VerifiedRecoveryDecision(
            plan_sha256=command.plan_sha256,
            approval_reference=command.approval_reference,
            approved=True,
            operator_id="local-operator",
            rationale="Approved independent QA and Review of the pinned original candidate",
            decided_at=command.submitted_at,
        )


class CandidateVerificationAdmission:
    """One invocation per role per approved plan, including after process loss.

    The caller's production facts port also owns candidate/policy/allocation freshness. This
    service reserves calls, never infers success from a receipt or an adapter-level result.
    """

    def __init__(
        self,
        *,
        store: FileRecoveryStore,
        plan_sha256: str,
        facts: VerificationFacts,
        artifacts: ArtifactStore,
        clock: Callable[[], datetime],
    ) -> None:
        self.store, self.plan_sha256 = store, plan_sha256
        self.facts, self.artifacts, self.clock = facts, artifacts, clock

    def propose(self, plan: CandidateVerificationPlan) -> CandidateVerificationPlan:
        plan.validate_integrity()
        if plan.plan_sha256 != self.plan_sha256:
            raise RecoveryRejected("verification plan identity differs from service")
        self.facts.validate(plan)
        return self.store.put_verification_plan(plan)

    def approve(
        self, command: RecoveryApprovalCommand, *, human: VerificationHuman
    ) -> RecoveryAuthorization:
        if command.plan_sha256 != self.plan_sha256:
            raise RecoveryRejected("approval targets another verification plan")
        plan = self.store.get_verification_plan(self.plan_sha256)
        try:
            previous = self.store.get_verification_authorization(self.plan_sha256)
        except RecoveryRecordMissing:
            pass
        else:
            if previous.command != command:
                raise RecoveryRejected("verification approval conflicts with the recorded decision")
            return previous
        self.facts.validate(plan)
        decision = human.verify(command)
        record = RecoveryAuthorization.create(command, decision)
        self.facts.validate(plan)
        return self.store.put_verification_authorization(record)

    def admit(self, inputs: CandidateVerificationInputs, request: AgentRequest) -> None:
        with self.store.execution_lock():
            plan = self.store.get_verification_plan(self.plan_sha256)
            authorization = self.store.get_verification_authorization(self.plan_sha256)
            if plan.inputs != inputs or not authorization.decision.approved:
                raise RecoveryRejected("verification is not approved for these inputs")
            self.facts.validate(plan)
            try:
                self.store.get_verification_invocation(self.plan_sha256, request.role)
            except RecoveryRecordMissing:
                pass
            else:
                raise RecoveryRejected("verification role was already admitted; inspect its result")
            self._validate_inputs(plan, request)
            self.store.put_verification_invocation(
                CandidateVerificationInvocation.create(
                    plan_sha256=self.plan_sha256,
                    authorization_sha256=authorization.authorization_sha256,
                    request=request,
                    admitted_at=self.clock(),
                )
            )

    def validate_configuration(
        self,
        inputs: CandidateVerificationInputs,
        definitions: Mapping[AgentRole, AgentDefinition],
    ) -> None:
        plan = self.store.get_verification_plan(self.plan_sha256)
        authorization = self.store.get_verification_authorization(self.plan_sha256)
        if (
            not authorization.decision.approved
            or plan.inputs != inputs
            or dict(definitions) != {d.role: d for d in plan.definitions}
        ):
            raise RecoveryRejected("verification configuration differs from the approved plan")
        self.facts.validate(plan)

    def complete(self, result: CandidateVerificationResult) -> CandidateVerificationCompletion:
        """Seal only accepted artifact-store facts from this approved execution."""
        with self.store.execution_lock():
            plan = self.store.get_verification_plan(self.plan_sha256)
            if result.inputs != plan.inputs:
                raise RecoveryRejected("completion targets different candidate inputs")
            if (
                result.plan.artifact_id != plan.inputs.plan_id
                or artifact_digest(result.plan) != plan.inputs.plan_sha256
                or result.implementation.artifact_id != plan.inputs.implementation_id
                or artifact_digest(result.implementation) != plan.inputs.implementation_sha256
                or {c.criterion_id for c in result.qa.content.criteria_results}
                != {c.criterion_id for c in result.plan.content.acceptance_mapping}
            ):
                raise RecoveryRejected("completion differs from approved artifacts or criteria")
            self.facts.validate(plan)
            for artifact in (result.plan, result.implementation, result.qa, result.review):
                if artifact is not None and self.artifacts.get(artifact.artifact_id) != artifact:
                    raise RecoveryRejected("completion must reference sealed artifact-store facts")
            try:
                previous = self.store.get_verification_completion(self.plan_sha256)
            except RecoveryRecordMissing:
                pass
            else:
                if previous.qa != result.qa or previous.review != result.review:
                    raise RecoveryRejected("completion conflicts with the recorded result")
                return previous
            authorization = self.store.get_verification_authorization(self.plan_sha256)
            qa = self.store.get_verification_invocation(self.plan_sha256, AgentRole.QA)
            reviewer = (
                self.store.get_verification_invocation(self.plan_sha256, AgentRole.REVIEWER)
                if result.review is not None
                else None
            )
            return self.store.put_verification_completion(
                CandidateVerificationCompletion.create(
                    plan_sha256=self.plan_sha256,
                    authorization_sha256=authorization.authorization_sha256,
                    qa_invocation_sha256=qa.invocation_sha256,
                    reviewer_invocation_sha256=reviewer.invocation_sha256
                    if reviewer is not None
                    else None,
                    qa=result.qa,
                    review=result.review,
                    completed_at=self.clock(),
                )
            )

    def _validate_inputs(self, plan: CandidateVerificationPlan, request: AgentRequest) -> None:
        prefix = (plan.inputs.plan_id, plan.inputs.implementation_id)
        if request.role is AgentRole.QA:
            if (
                request.input_artifact_ids != prefix
                or request.expected_parent_artifact_ids != prefix[1:]
            ):
                raise RecoveryRejected("QA invocation does not bind the approved implementation")
            return
        if request.role is not AgentRole.REVIEWER or len(request.input_artifact_ids) != 3:
            raise RecoveryRejected("verification only permits QA followed by Reviewer")
        qa_invocation = self.store.get_verification_invocation(self.plan_sha256, AgentRole.QA)
        qa = self.artifacts.get(request.input_artifact_ids[-1])
        qa_definition = next(d for d in plan.definitions if d.role is AgentRole.QA)
        if (
            not isinstance(qa, QaReportArtifact)
            or qa.producer.run_id != qa_invocation.request.run_id
            or qa.context_manifest_id != qa_invocation.request.context_manifest_id
            or qa.producer.agent_id != qa_definition.id
            or qa.task_id != plan.inputs.task_id
            or qa.source_revision != plan.inputs.candidate_revision
            or qa.parent_artifact_ids != prefix[1:]
            or qa.content.status is not QaReportStatus.PASS
            or request.input_artifact_ids[:2] != prefix
            or request.expected_parent_artifact_ids != (qa.artifact_id,)
            or request.run_id == qa_invocation.request.run_id
        ):
            raise RecoveryRejected("Reviewer requires this recovery's accepted QA report")
