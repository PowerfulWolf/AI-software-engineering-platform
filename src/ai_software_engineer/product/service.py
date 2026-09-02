"""Durable Product Agent discovery and exact human approval workflow."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self

from pydantic import StringConstraints, model_validator

from ai_software_engineer.domain import (
    ProductApprovalDecision,
    ProductSpec,
    ProductSpecApproval,
    ProductSpecStatus,
    ProjectPreparation,
    ProjectRequest,
    ProjectRequestStatus,
)
from ai_software_engineer.domain.agent import TimeoutSeconds
from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.model import DomainModel, JsonValue, NonEmptyStr
from ai_software_engineer.domain.project_delivery import (
    ProductSpecId,
    ProjectRequestId,
    StageSha256,
)
from ai_software_engineer.product.agents import (
    ProductAgentAdapter,
    ProductAgentErrorCode,
    ProductAgentRequest,
    ProductAgentResult,
    ProductAgentRunStatus,
    ProductClarification,
)
from ai_software_engineer.product.context import (
    ProductContextBuilder,
    ProductContextManifest,
    ProductDialogueContextItem,
)
from ai_software_engineer.product.models import (
    ProductDialogueActor,
    ProductDialogueRecord,
    ProductDiscoveryCheckpoint,
    ProductDiscoveryStatus,
    ProductOperationId,
    ProductOperationKind,
    ProductOperationRecord,
    ProductRecordIntegrityError,
    ProjectRequestRevision,
)
from ai_software_engineer.product.store import ProductRecordNotFound, ProductRecordStore
from ai_software_engineer.project_manager.baseline import ProjectSpecBaseline
from ai_software_engineer.project_manager.stages import (
    ProjectStage,
    ProjectStageError,
    StageAdvanceAuthorization,
    StageAdvanceRequest,
)
from ai_software_engineer.project_profile import ProjectProfile

Clock = Callable[[], datetime]
CommandId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{2,127}$")]
ProductEffect = ProjectRequestRevision | ProductDialogueRecord | ProductSpec | ProductSpecApproval


class ProductDiscoveryError(RuntimeError):
    """Base error for product-discovery application failures."""


class ProductDiscoveryNotStarted(ProductDiscoveryError):
    """A command targeted a request with no durable checkpoint."""


class ProductDiscoveryAlreadyStarted(ProductDiscoveryError):
    """A second start command targeted an existing request."""


class ProductDiscoveryStateError(ProductDiscoveryError):
    """An operation is not legal from the current checkpoint."""


class ProductDiscoveryStaleCheckpoint(ProductDiscoveryError):
    """A command was composed from an older checkpoint or ProductSpec."""


class ProductOperationConflict(ProductDiscoveryError):
    """An operation ID was replayed with different typed input."""


class ProductAgentOutputRejected(ProductDiscoveryError):
    """The adapter output did not match its exact request and context."""


class ProductAgentExecutionError(ProductDiscoveryError):
    """The adapter raised instead of returning a typed terminal result."""


class ProjectStageAdvancePort(Protocol):
    """Project Manager Skill port that revalidates current project facts."""

    def advance_stage(self, request: StageAdvanceRequest) -> StageAdvanceAuthorization: ...


class HumanProductDecisionVerifier(Protocol):
    """Trusted human-channel port; never exposed to Product Agent tools."""

    def verify(self, command: HumanProductDecisionCommand) -> VerifiedHumanProductDecision: ...


class StartProductDiscoveryCommand(DomainModel):
    kind: Literal["start_product_discovery_command"] = "start_product_discovery_command"
    schema_version: Literal["v0.1"] = "v0.1"
    operation_id: CommandId
    request_id: ProjectRequestId
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    initial_requirement: NonEmptyStr
    submitted_at: datetime

    @model_validator(mode="after")
    def require_aware_submission(self) -> Self:
        _require_aware(self.submitted_at, "submitted_at")
        return self


class RecordHumanMessageCommand(DomainModel):
    kind: Literal["record_product_human_message_command"] = "record_product_human_message_command"
    schema_version: Literal["v0.1"] = "v0.1"
    operation_id: CommandId
    request_id: ProjectRequestId
    expected_checkpoint_sha256: StageSha256
    content: Annotated[str, StringConstraints(min_length=1, max_length=20_000)]
    submitted_at: datetime

    @model_validator(mode="after")
    def require_aware_submission(self) -> Self:
        _require_aware(self.submitted_at, "submitted_at")
        return self


class RunProductAgentCommand(DomainModel):
    kind: Literal["run_product_agent_command"] = "run_product_agent_command"
    schema_version: Literal["v0.1"] = "v0.1"
    run_id: RunId
    request_id: ProjectRequestId
    expected_checkpoint_sha256: StageSha256
    timeout_seconds: TimeoutSeconds = 600
    submitted_at: datetime

    @model_validator(mode="after")
    def require_aware_submission(self) -> Self:
        _require_aware(self.submitted_at, "submitted_at")
        return self


class HumanProductDecisionCommand(DomainModel):
    """Reference a decision captured by an independently trusted human channel."""

    kind: Literal["human_product_decision_command"] = "human_product_decision_command"
    schema_version: Literal["v0.1"] = "v0.1"
    operation_id: CommandId
    request_id: ProjectRequestId
    expected_checkpoint_sha256: StageSha256
    product_spec_id: ProductSpecId
    product_spec_sha256: StageSha256
    approval_reference: NonEmptyStr
    submitted_at: datetime

    @model_validator(mode="after")
    def require_aware_submission(self) -> Self:
        _require_aware(self.submitted_at, "submitted_at")
        return self


class VerifiedHumanProductDecision(DomainModel):
    """Decision fact returned by a trusted verifier, not constructed by Product Agent."""

    kind: Literal["verified_human_product_decision"] = "verified_human_product_decision"
    schema_version: Literal["v0.1"] = "v0.1"
    approval_reference: NonEmptyStr
    request_id: ProjectRequestId
    product_spec_id: ProductSpecId
    product_spec_sha256: StageSha256
    decision: ProductApprovalDecision
    operator_id: NonEmptyStr
    rationale: NonEmptyStr
    decided_at: datetime

    @model_validator(mode="after")
    def require_aware_decision_time(self) -> Self:
        if self.decided_at.tzinfo is None or self.decided_at.utcoffset() is None:
            raise ValueError("verified human decision time must be timezone-aware")
        return self


class ProductDiscoveryOutcome(StrEnum):
    STARTED = "STARTED"
    HUMAN_MESSAGE_RECORDED = "HUMAN_MESSAGE_RECORDED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    AGENT_FAILED = "AGENT_FAILED"
    AGENT_TIMED_OUT = "AGENT_TIMED_OUT"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"


class ProductDiscoveryResult(DomainModel):
    kind: Literal["product_discovery_result"] = "product_discovery_result"
    schema_version: Literal["v0.1"] = "v0.1"
    operation_id: CommandId
    outcome: ProductDiscoveryOutcome
    replayed: bool = False
    request_revision: ProjectRequestRevision
    checkpoint: ProductDiscoveryCheckpoint
    dialogue: ProductDialogueRecord | None = None
    clarification: ProductClarification | None = None
    product_spec: ProductSpec | None = None
    approval: ProductSpecApproval | None = None
    authorization: StageAdvanceAuthorization | None = None
    agent_error_code: ProductAgentErrorCode | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if (
            self.request_revision.request.id != self.checkpoint.request_id
            or self.request_revision.revision != self.checkpoint.request_revision
            or self.request_revision.request.request_sha256 != self.checkpoint.request_sha256
        ):
            raise ValueError("result request revision does not match checkpoint")
        if self.clarification is not None and self.dialogue is None:
            raise ValueError("clarification result requires durable dialogue")
        if self.outcome is ProductDiscoveryOutcome.READY_FOR_APPROVAL and (
            self.product_spec is None or self.approval is not None
        ):
            raise ValueError("ready result requires only ProductSpec")
        if self.outcome in {
            ProductDiscoveryOutcome.CHANGES_REQUESTED,
            ProductDiscoveryOutcome.APPROVED,
        } and (self.product_spec is None or self.approval is None):
            raise ValueError("decision result requires ProductSpec and approval")
        if (self.outcome is ProductDiscoveryOutcome.APPROVED) != (self.authorization is not None):
            raise ValueError("only approved result requires stage authorization")
        failure = self.outcome in {
            ProductDiscoveryOutcome.AGENT_FAILED,
            ProductDiscoveryOutcome.AGENT_TIMED_OUT,
        }
        if failure != (self.agent_error_code is not None):
            raise ValueError("agent failure and error code must appear together")
        return self


class ProductDiscoveryService:
    """Coordinate immutable product dialogue, spec review, and Designer unlock."""

    def __init__(
        self,
        *,
        preparation: ProjectPreparation,
        project_profile: ProjectProfile,
        project_baseline: ProjectSpecBaseline,
        store: ProductRecordStore,
        adapter: ProductAgentAdapter,
        stage_advancer: ProjectStageAdvancePort,
        human_decision_verifier: HumanProductDecisionVerifier,
        context_builder: ProductContextBuilder | None = None,
        clock: Clock | None = None,
    ) -> None:
        preparation.validate_integrity()
        project_profile.validate_integrity()
        project_baseline.validate_integrity()
        if (
            project_profile.project_id != preparation.project_id
            or project_profile.profile_sha256 != preparation.project_profile_sha256
            or project_baseline.project_id != preparation.project_id
            or project_baseline.project_profile_sha256 != project_profile.profile_sha256
            or project_baseline.baseline_sha256 != preparation.baseline_spec_sha256
        ):
            raise ProductDiscoveryError(
                "Product project knowledge does not match ProjectPreparation"
            )
        self._preparation = preparation
        self._project_profile = project_profile
        self._project_baseline = project_baseline
        self._store = store
        self._adapter = adapter
        self._stage_advancer = stage_advancer
        self._human_decision_verifier = human_decision_verifier
        self._context_builder = context_builder or ProductContextBuilder()
        self._clock = clock or _utc_now

    def start(self, command: StartProductDiscoveryCommand) -> ProductDiscoveryResult:
        input_sha256 = _command_digest(
            command, preparation_sha256=self._preparation.preparation_sha256
        )
        replay = self._replay(
            command.operation_id,
            ProductOperationKind.START,
            command.request_id,
            input_sha256,
        )
        if replay is not None:
            return replay
        if self._find_checkpoint(command.request_id) is not None:
            raise ProductDiscoveryAlreadyStarted(command.request_id)
        now = command.submitted_at
        request = ProjectRequest.create(
            request_id=command.request_id,
            project_id=self._preparation.project_id,
            preparation_sha256=self._preparation.preparation_sha256,
            title=command.title,
            original_request=command.initial_requirement,
            status=ProjectRequestStatus.PRODUCT_DISCOVERY,
            created_at=now,
        )
        revision = ProjectRequestRevision.create(
            request, revision=1, supersedes_sha256=None, recorded_at=now
        )
        dialogue = ProductDialogueRecord.create(
            request_id=request.id,
            project_id=request.project_id,
            sequence=1,
            actor=ProductDialogueActor.HUMAN,
            content=command.initial_requirement,
            previous_dialogue_sha256=None,
            recorded_at=now,
        )
        checkpoint = ProductDiscoveryCheckpoint.create(
            request_id=request.id,
            project_id=request.project_id,
            revision=1,
            previous_checkpoint_sha256=None,
            request_revision=1,
            request_sha256=request.request_sha256,
            dialogue_count=1,
            dialogue_head_sha256=dialogue.dialogue_sha256,
            status=ProductDiscoveryStatus.PRODUCT_DISCOVERY,
            updated_at=now,
        )
        self._record_operation(
            command.operation_id,
            ProductOperationKind.START,
            request.id,
            input_sha256,
            ProductDiscoveryOutcome.STARTED,
            checkpoint,
            now,
            effects=(revision, dialogue),
        )
        revision = self._store.put_request_revision(revision)
        dialogue = self._store.put_dialogue(dialogue)
        checkpoint = self._store.put_checkpoint(checkpoint)
        return ProductDiscoveryResult(
            operation_id=command.operation_id,
            outcome=ProductDiscoveryOutcome.STARTED,
            request_revision=revision,
            checkpoint=checkpoint,
            dialogue=dialogue,
        )

    def record_human_message(self, command: RecordHumanMessageCommand) -> ProductDiscoveryResult:
        input_sha256 = _command_digest(command)
        replay = self._replay(
            command.operation_id,
            ProductOperationKind.HUMAN_MESSAGE,
            command.request_id,
            input_sha256,
        )
        if replay is not None:
            return replay
        revision, checkpoint = self._load_current(command.request_id)
        self._require_checkpoint(command.expected_checkpoint_sha256, checkpoint)
        if checkpoint.status not in {
            ProductDiscoveryStatus.PRODUCT_DISCOVERY,
            ProductDiscoveryStatus.CHANGES_REQUESTED,
        }:
            raise ProductDiscoveryStateError("human message requires active discovery")
        now = command.submitted_at
        dialogue = self._new_dialogue(checkpoint, ProductDialogueActor.HUMAN, command.content, now)
        advanced = self._checkpoint_after_dialogue(checkpoint, revision, dialogue, now)
        self._record_operation(
            command.operation_id,
            ProductOperationKind.HUMAN_MESSAGE,
            command.request_id,
            input_sha256,
            ProductDiscoveryOutcome.HUMAN_MESSAGE_RECORDED,
            advanced,
            now,
            effects=(dialogue,),
        )
        dialogue = self._store.put_dialogue(dialogue)
        advanced = self._store.put_checkpoint(advanced)
        return ProductDiscoveryResult(
            operation_id=command.operation_id,
            outcome=ProductDiscoveryOutcome.HUMAN_MESSAGE_RECORDED,
            request_revision=revision,
            checkpoint=advanced,
            dialogue=dialogue,
        )

    def run_product(self, command: RunProductAgentCommand) -> ProductDiscoveryResult:
        input_sha256 = _command_digest(command)
        replay = self._replay(
            command.run_id,
            ProductOperationKind.PRODUCT_RUN,
            command.request_id,
            input_sha256,
        )
        if replay is not None:
            return replay
        revision, checkpoint = self._load_current(command.request_id)
        self._require_checkpoint(command.expected_checkpoint_sha256, checkpoint)
        if checkpoint.status not in {
            ProductDiscoveryStatus.PRODUCT_DISCOVERY,
            ProductDiscoveryStatus.CHANGES_REQUESTED,
        }:
            raise ProductDiscoveryStateError("Product Agent requires active discovery")
        now = command.submitted_at
        context = self._context_builder.build(
            self._preparation,
            self._project_profile,
            self._project_baseline,
            revision.request,
            dialogue=tuple(
                _dialogue_context(record)
                for record in self._store.list_dialogue(command.request_id)[
                    : checkpoint.dialogue_count
                ]
            ),
            current_product_spec=self._current_spec(checkpoint),
            built_at=now,
        )
        agent_request = ProductAgentRequest(
            run_id=command.run_id,
            project_id=checkpoint.project_id,
            request_id=checkpoint.request_id,
            context=context,
            permissions=context.permissions,
            timeout_seconds=command.timeout_seconds,
        )
        try:
            agent_result = self._adapter.run(agent_request)
        except Exception as error:
            raise ProductAgentExecutionError(
                "ProductAgentAdapter raised instead of returning typed failure"
            ) from error
        self._validate_agent_result(agent_request, agent_result)
        if agent_result.status is not ProductAgentRunStatus.SUCCEEDED:
            return self._agent_failure(
                command,
                input_sha256,
                revision,
                checkpoint,
                agent_result,
                now,
            )
        if agent_result.clarification is not None:
            return self._agent_clarification(
                command,
                input_sha256,
                revision,
                checkpoint,
                agent_result.clarification,
                now,
            )
        if agent_result.product_spec is None:
            raise ProductAgentOutputRejected("successful result has no ProductSpec")
        return self._agent_ready(
            command,
            input_sha256,
            revision,
            checkpoint,
            context,
            agent_result.product_spec,
            now,
        )

    def decide_as_human(self, command: HumanProductDecisionCommand) -> ProductDiscoveryResult:
        input_sha256 = _command_digest(command)
        replay = self._replay(
            command.operation_id,
            ProductOperationKind.PRODUCT_DECISION,
            command.request_id,
            input_sha256,
        )
        if replay is not None:
            return replay
        try:
            verified = self._human_decision_verifier.verify(command)
            verified = VerifiedHumanProductDecision.model_validate(verified.to_wire())
        except Exception as error:
            raise ProductDiscoveryStateError("human decision could not be verified") from error
        if (
            verified.approval_reference != command.approval_reference
            or verified.request_id != command.request_id
            or verified.product_spec_id != command.product_spec_id
            or verified.product_spec_sha256 != command.product_spec_sha256
        ):
            raise ProductDiscoveryStateError(
                "verified human decision does not match the approval command"
            )
        revision, checkpoint = self._load_current(command.request_id)
        self._require_checkpoint(command.expected_checkpoint_sha256, checkpoint)
        if checkpoint.status is not ProductDiscoveryStatus.WAITING_PRODUCT_APPROVAL:
            raise ProductDiscoveryStateError("decision requires WAITING_PRODUCT_APPROVAL")
        if (
            checkpoint.current_product_spec_id != command.product_spec_id
            or checkpoint.current_product_spec_sha256 != command.product_spec_sha256
        ):
            raise ProductDiscoveryStaleCheckpoint(
                "decision does not bind exact current ProductSpec"
            )
        spec = self._current_spec(checkpoint)
        if spec is None:
            raise ProductRecordIntegrityError("approval checkpoint has no ProductSpec")
        now = verified.decided_at
        approval = ProductSpecApproval.create(
            spec,
            decision=verified.decision,
            operator_id=verified.operator_id,
            rationale=verified.rationale,
            decided_at=verified.decided_at,
        )
        status = (
            ProjectRequestStatus.DESIGNING
            if verified.decision is ProductApprovalDecision.APPROVED
            else ProjectRequestStatus.PRODUCT_DISCOVERY
        )
        next_request = _request_with_status(revision.request, status, now)
        next_revision = ProjectRequestRevision.create(
            next_request,
            revision=revision.revision + 1,
            supersedes_sha256=revision.request_revision_sha256,
            recorded_at=now,
        )
        authorization: StageAdvanceAuthorization | None = None
        if verified.decision is ProductApprovalDecision.APPROVED:
            stage_request = StageAdvanceRequest(
                target=ProjectStage.SOLUTION_DESIGN,
                preparation=self._preparation,
                project_request=next_request,
                product_spec=spec,
                product_approval=approval,
            )
            try:
                candidate = self._stage_advancer.advance_stage(stage_request)
                authorization = StageAdvanceAuthorization.model_validate(candidate.to_wire())
                _validate_solution_design_authorization(
                    authorization,
                    self._preparation,
                    next_request,
                    spec,
                    approval,
                )
            except (AttributeError, ProjectStageError, TypeError, ValueError) as error:
                raise ProductDiscoveryStateError(
                    "Project Manager returned an invalid solution-design authorization"
                ) from error
        dialogue: ProductDialogueRecord | None = None
        if verified.decision is ProductApprovalDecision.REQUEST_CHANGES:
            dialogue = self._new_dialogue(
                checkpoint, ProductDialogueActor.HUMAN, verified.rationale, now
            )
        advanced = ProductDiscoveryCheckpoint.create(
            request_id=checkpoint.request_id,
            project_id=checkpoint.project_id,
            revision=checkpoint.revision + 1,
            previous_checkpoint_sha256=checkpoint.checkpoint_sha256,
            request_revision=next_revision.revision,
            request_sha256=next_revision.request.request_sha256,
            dialogue_count=(checkpoint.dialogue_count if dialogue is None else dialogue.sequence),
            dialogue_head_sha256=(
                checkpoint.dialogue_head_sha256 if dialogue is None else dialogue.dialogue_sha256
            ),
            current_product_spec_id=spec.id,
            current_product_spec_sha256=spec.product_spec_sha256,
            current_product_spec_version=spec.version,
            current_approval_id=approval.id,
            current_approval_sha256=approval.approval_sha256,
            status=(
                ProductDiscoveryStatus.APPROVED
                if verified.decision is ProductApprovalDecision.APPROVED
                else ProductDiscoveryStatus.CHANGES_REQUESTED
            ),
            updated_at=now,
        )
        outcome = (
            ProductDiscoveryOutcome.APPROVED
            if verified.decision is ProductApprovalDecision.APPROVED
            else ProductDiscoveryOutcome.CHANGES_REQUESTED
        )
        effects: list[ProductEffect] = [next_revision, approval]
        if dialogue is not None:
            effects.append(dialogue)
        self._record_operation(
            command.operation_id,
            ProductOperationKind.PRODUCT_DECISION,
            command.request_id,
            input_sha256,
            outcome,
            advanced,
            now,
            result_payload={
                "verified_decision": verified.to_wire(),
                "authorization": None if authorization is None else authorization.to_wire(),
            },
            effects=tuple(effects),
        )
        persisted_revision = self._store.put_request_revision(next_revision)
        persisted_approval = self._store.put_approval(approval)
        if dialogue is not None:
            dialogue = self._store.put_dialogue(dialogue)
        advanced = self._store.put_checkpoint(advanced)
        return ProductDiscoveryResult(
            operation_id=command.operation_id,
            outcome=outcome,
            request_revision=persisted_revision,
            checkpoint=advanced,
            dialogue=dialogue,
            product_spec=spec,
            approval=persisted_approval,
            authorization=authorization,
        )

    def _agent_failure(
        self,
        command: RunProductAgentCommand,
        input_sha256: str,
        revision: ProjectRequestRevision,
        checkpoint: ProductDiscoveryCheckpoint,
        result: ProductAgentResult,
        now: datetime,
    ) -> ProductDiscoveryResult:
        if result.error is None:
            raise ProductAgentOutputRejected("failed result has no typed error")
        outcome = (
            ProductDiscoveryOutcome.AGENT_TIMED_OUT
            if result.status is ProductAgentRunStatus.TIMED_OUT
            else ProductDiscoveryOutcome.AGENT_FAILED
        )
        self._record_operation(
            command.run_id,
            ProductOperationKind.PRODUCT_RUN,
            command.request_id,
            input_sha256,
            outcome,
            checkpoint,
            now,
            result.error.code,
        )
        return ProductDiscoveryResult(
            operation_id=command.run_id,
            outcome=outcome,
            request_revision=revision,
            checkpoint=checkpoint,
            agent_error_code=result.error.code,
        )

    def _agent_clarification(
        self,
        command: RunProductAgentCommand,
        input_sha256: str,
        revision: ProjectRequestRevision,
        checkpoint: ProductDiscoveryCheckpoint,
        clarification: ProductClarification,
        now: datetime,
    ) -> ProductDiscoveryResult:
        dialogue = self._new_dialogue(
            checkpoint,
            ProductDialogueActor.PRODUCT_AGENT,
            _canonical_json(clarification.to_wire()),
            now,
        )
        advanced = self._checkpoint_after_dialogue(checkpoint, revision, dialogue, now)
        self._record_operation(
            command.run_id,
            ProductOperationKind.PRODUCT_RUN,
            command.request_id,
            input_sha256,
            ProductDiscoveryOutcome.CLARIFICATION_REQUIRED,
            advanced,
            now,
            effects=(dialogue,),
        )
        dialogue = self._store.put_dialogue(dialogue)
        advanced = self._store.put_checkpoint(advanced)
        return ProductDiscoveryResult(
            operation_id=command.run_id,
            outcome=ProductDiscoveryOutcome.CLARIFICATION_REQUIRED,
            request_revision=revision,
            checkpoint=advanced,
            dialogue=dialogue,
            clarification=clarification,
        )

    def _agent_ready(
        self,
        command: RunProductAgentCommand,
        input_sha256: str,
        revision: ProjectRequestRevision,
        checkpoint: ProductDiscoveryCheckpoint,
        context: ProductContextManifest,
        spec: ProductSpec,
        now: datetime,
    ) -> ProductDiscoveryResult:
        self._validate_product_spec(spec, context)
        next_request = _request_with_status(
            revision.request, ProjectRequestStatus.WAITING_PRODUCT_APPROVAL, now
        )
        next_revision = ProjectRequestRevision.create(
            next_request,
            revision=revision.revision + 1,
            supersedes_sha256=revision.request_revision_sha256,
            recorded_at=now,
        )
        advanced = ProductDiscoveryCheckpoint.create(
            request_id=checkpoint.request_id,
            project_id=checkpoint.project_id,
            revision=checkpoint.revision + 1,
            previous_checkpoint_sha256=checkpoint.checkpoint_sha256,
            request_revision=next_revision.revision,
            request_sha256=next_request.request_sha256,
            dialogue_count=checkpoint.dialogue_count,
            dialogue_head_sha256=checkpoint.dialogue_head_sha256,
            current_product_spec_id=spec.id,
            current_product_spec_sha256=spec.product_spec_sha256,
            current_product_spec_version=spec.version,
            status=ProductDiscoveryStatus.WAITING_PRODUCT_APPROVAL,
            updated_at=now,
        )
        self._record_operation(
            command.run_id,
            ProductOperationKind.PRODUCT_RUN,
            command.request_id,
            input_sha256,
            ProductDiscoveryOutcome.READY_FOR_APPROVAL,
            advanced,
            now,
            effects=(next_revision, spec),
        )
        spec = self._store.put_product_spec(spec)
        next_revision = self._store.put_request_revision(next_revision)
        advanced = self._store.put_checkpoint(advanced)
        return ProductDiscoveryResult(
            operation_id=command.run_id,
            outcome=ProductDiscoveryOutcome.READY_FOR_APPROVAL,
            request_revision=next_revision,
            checkpoint=advanced,
            product_spec=spec,
        )

    def _load_current(
        self, request_id: ProjectRequestId
    ) -> tuple[ProjectRequestRevision, ProductDiscoveryCheckpoint]:
        checkpoint = self._find_checkpoint(request_id)
        if checkpoint is None:
            raise ProductDiscoveryNotStarted(request_id)
        revision = self._store.get_request_revision(request_id, checkpoint.request_revision)
        dialogue = self._store.list_dialogue(request_id)[: checkpoint.dialogue_count]
        expected_head = None if not dialogue else dialogue[-1].dialogue_sha256
        if (
            checkpoint.project_id != self._preparation.project_id
            or revision.request.project_id != self._preparation.project_id
            or revision.request.preparation_sha256 != self._preparation.preparation_sha256
            or checkpoint.request_revision != revision.revision
            or checkpoint.request_sha256 != revision.request.request_sha256
            or checkpoint.dialogue_count != len(dialogue)
            or checkpoint.dialogue_head_sha256 != expected_head
        ):
            raise ProductRecordIntegrityError(
                "current Product checkpoint does not match durable facts"
            )
        expected_status = {
            ProductDiscoveryStatus.PRODUCT_DISCOVERY: ProjectRequestStatus.PRODUCT_DISCOVERY,
            ProductDiscoveryStatus.CHANGES_REQUESTED: ProjectRequestStatus.PRODUCT_DISCOVERY,
            ProductDiscoveryStatus.WAITING_PRODUCT_APPROVAL: (
                ProjectRequestStatus.WAITING_PRODUCT_APPROVAL
            ),
            ProductDiscoveryStatus.APPROVED: ProjectRequestStatus.DESIGNING,
        }[checkpoint.status]
        if revision.request.status is not expected_status:
            raise ProductRecordIntegrityError("request status does not match checkpoint")
        self._current_spec(checkpoint)
        self._current_approval(checkpoint)
        return revision, checkpoint

    def _find_checkpoint(self, request_id: ProjectRequestId) -> ProductDiscoveryCheckpoint | None:
        try:
            return self._store.current_checkpoint(request_id)
        except ProductRecordNotFound:
            return None

    def _current_spec(self, checkpoint: ProductDiscoveryCheckpoint) -> ProductSpec | None:
        if checkpoint.current_product_spec_version is None:
            return None
        spec = self._store.get_product_spec(
            checkpoint.request_id, checkpoint.current_product_spec_version
        )
        if (
            spec.id != checkpoint.current_product_spec_id
            or spec.product_spec_sha256 != checkpoint.current_product_spec_sha256
        ):
            raise ProductRecordIntegrityError("checkpoint ProductSpec does not match store")
        return spec

    def _current_approval(
        self, checkpoint: ProductDiscoveryCheckpoint
    ) -> ProductSpecApproval | None:
        if checkpoint.current_approval_id is None:
            return None
        approval = self._store.find_approval(checkpoint.current_approval_id)
        if approval is None or approval.approval_sha256 != checkpoint.current_approval_sha256:
            raise ProductRecordIntegrityError("checkpoint approval does not match store")
        return approval

    def _new_dialogue(
        self,
        checkpoint: ProductDiscoveryCheckpoint,
        actor: ProductDialogueActor,
        content: str,
        now: datetime,
    ) -> ProductDialogueRecord:
        return ProductDialogueRecord.create(
            request_id=checkpoint.request_id,
            project_id=checkpoint.project_id,
            sequence=checkpoint.dialogue_count + 1,
            actor=actor,
            content=content,
            previous_dialogue_sha256=checkpoint.dialogue_head_sha256,
            recorded_at=now,
        )

    def _checkpoint_after_dialogue(
        self,
        previous: ProductDiscoveryCheckpoint,
        revision: ProjectRequestRevision,
        dialogue: ProductDialogueRecord,
        now: datetime,
    ) -> ProductDiscoveryCheckpoint:
        return ProductDiscoveryCheckpoint.create(
            request_id=previous.request_id,
            project_id=previous.project_id,
            revision=previous.revision + 1,
            previous_checkpoint_sha256=previous.checkpoint_sha256,
            request_revision=revision.revision,
            request_sha256=revision.request.request_sha256,
            dialogue_count=dialogue.sequence,
            dialogue_head_sha256=dialogue.dialogue_sha256,
            current_product_spec_id=previous.current_product_spec_id,
            current_product_spec_sha256=previous.current_product_spec_sha256,
            current_product_spec_version=previous.current_product_spec_version,
            current_approval_id=previous.current_approval_id,
            current_approval_sha256=previous.current_approval_sha256,
            status=previous.status,
            updated_at=now,
        )

    def _validate_agent_result(
        self, request: ProductAgentRequest, result: ProductAgentResult
    ) -> None:
        try:
            result = ProductAgentResult.model_validate(result.to_wire())
        except (TypeError, ValueError) as error:
            raise ProductAgentOutputRejected("adapter returned invalid output") from error
        if (
            result.run_id != request.run_id
            or result.project_id != request.project_id
            or result.request_id != request.request_id
            or result.context_id != request.context.context_id
        ):
            raise ProductAgentOutputRejected("adapter result identity does not match request")

    def _validate_product_spec(self, spec: ProductSpec, context: ProductContextManifest) -> None:
        try:
            spec.validate_integrity()
        except RuntimeError as error:
            raise ProductAgentOutputRejected("ProductSpec integrity is invalid") from error
        if (
            spec.project_id != context.project_id
            or spec.request_id != context.request_id
            or spec.status is not ProductSpecStatus.READY_FOR_REVIEW
            or spec.version != context.expected_product_spec_version
            or spec.supersedes != context.expected_supersedes
        ):
            raise ProductAgentOutputRejected(
                "ProductSpec lineage/status/version does not match context"
            )

    def _require_checkpoint(
        self, expected_sha256: str, checkpoint: ProductDiscoveryCheckpoint
    ) -> None:
        if expected_sha256 != checkpoint.checkpoint_sha256:
            raise ProductDiscoveryStaleCheckpoint("command checkpoint is stale")

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ProductDiscoveryError("clock must be timezone-aware")
        return now

    def _record_operation(
        self,
        operation_id: ProductOperationId,
        operation_kind: ProductOperationKind,
        request_id: ProjectRequestId,
        input_sha256: StageSha256,
        outcome: ProductDiscoveryOutcome,
        checkpoint: ProductDiscoveryCheckpoint,
        now: datetime,
        error_code: ProductAgentErrorCode | None = None,
        result_payload: dict[str, JsonValue] | None = None,
        effects: tuple[ProductEffect, ...] = (),
    ) -> None:
        payload: dict[str, JsonValue] = {
            "checkpoint": checkpoint.to_wire(),
            "effects": [effect.to_wire() for effect in effects],
        }
        if result_payload is not None:
            payload.update(result_payload)
        self._store.put_operation(
            ProductOperationRecord.create(
                operation_id=operation_id,
                request_id=request_id,
                operation_kind=operation_kind,
                input_sha256=input_sha256,
                result_identity=_result_identity(outcome, checkpoint.revision, error_code),
                recorded_at=now,
                result_payload=payload,
            )
        )

    def _replay(
        self,
        operation_id: ProductOperationId,
        operation_kind: ProductOperationKind,
        request_id: ProjectRequestId,
        input_sha256: StageSha256,
    ) -> ProductDiscoveryResult | None:
        operation = self._store.find_operation(operation_id)
        if operation is None:
            return None
        if (
            operation.operation_kind is not operation_kind
            or operation.request_id != request_id
            or operation.input_sha256 != input_sha256
        ):
            raise ProductOperationConflict(operation_id)
        outcome, checkpoint_revision, error_code = _parse_result_identity(operation.result_identity)
        self._materialize_operation_effects(operation)
        try:
            checkpoint = self._store.get_checkpoint(request_id, checkpoint_revision)
        except ProductRecordNotFound:
            try:
                checkpoint = ProductDiscoveryCheckpoint.model_validate(
                    operation.result_payload["checkpoint"]
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ProductRecordIntegrityError(
                    "operation checkpoint recovery evidence is invalid"
                ) from error
            if checkpoint.request_id != request_id or checkpoint.revision != checkpoint_revision:
                raise ProductRecordIntegrityError(
                    "operation checkpoint recovery evidence does not match result identity"
                ) from None
            checkpoint = self._store.put_checkpoint(checkpoint)
        revision = self._store.get_request_revision(request_id, checkpoint.request_revision)
        dialogue: ProductDialogueRecord | None = None
        clarification: ProductClarification | None = None
        if outcome in {
            ProductDiscoveryOutcome.STARTED,
            ProductDiscoveryOutcome.HUMAN_MESSAGE_RECORDED,
            ProductDiscoveryOutcome.CLARIFICATION_REQUIRED,
            ProductDiscoveryOutcome.CHANGES_REQUESTED,
        }:
            dialogue = self._store.get_dialogue(request_id, checkpoint.dialogue_count)
            if outcome is ProductDiscoveryOutcome.CLARIFICATION_REQUIRED:
                clarification = _clarification_from_content(dialogue.content)
        spec = self._current_spec(checkpoint)
        approval = self._current_approval(checkpoint)
        authorization: StageAdvanceAuthorization | None = None
        if outcome is ProductDiscoveryOutcome.APPROVED:
            if spec is None or approval is None:
                raise ProductRecordIntegrityError("approved replay chain is incomplete")
            try:
                verified = VerifiedHumanProductDecision.model_validate(
                    operation.result_payload["verified_decision"]
                )
                authorization = StageAdvanceAuthorization.model_validate(
                    operation.result_payload["authorization"]
                )
                _validate_solution_design_authorization(
                    authorization,
                    self._preparation,
                    revision.request,
                    spec,
                    approval,
                )
            except (KeyError, ProjectStageError, TypeError, ValueError) as error:
                raise ProductRecordIntegrityError(
                    "approved operation replay evidence is invalid"
                ) from error
            if (
                verified.request_id != request_id
                or verified.product_spec_id != spec.id
                or verified.product_spec_sha256 != spec.product_spec_sha256
                or verified.decision is not ProductApprovalDecision.APPROVED
                or approval.operator_id != verified.operator_id
                or approval.rationale != verified.rationale
                or approval.decided_at != verified.decided_at
            ):
                raise ProductRecordIntegrityError(
                    "approved operation replay evidence does not match durable facts"
                )
        return ProductDiscoveryResult(
            operation_id=operation_id,
            outcome=outcome,
            replayed=True,
            request_revision=revision,
            checkpoint=checkpoint,
            dialogue=dialogue,
            clarification=clarification,
            product_spec=spec,
            approval=approval,
            authorization=authorization,
            agent_error_code=error_code,
        )

    def _materialize_operation_effects(self, operation: ProductOperationRecord) -> None:
        """Publish every receipt-bound fact before restoring its commit checkpoint."""
        raw_effects = operation.result_payload.get("effects")
        if not isinstance(raw_effects, list):
            raise ProductRecordIntegrityError("operation effect recovery evidence is invalid")
        for raw_effect in raw_effects:
            if not isinstance(raw_effect, dict):
                raise ProductRecordIntegrityError(
                    "operation effect recovery evidence contains a non-object"
                )
            kind = raw_effect.get("kind")
            try:
                if kind == "project_request_revision":
                    self._store.put_request_revision(
                        ProjectRequestRevision.model_validate(raw_effect)
                    )
                elif kind == "product_dialogue_record":
                    self._store.put_dialogue(ProductDialogueRecord.model_validate(raw_effect))
                elif kind == "product_spec":
                    self._store.put_product_spec(ProductSpec.model_validate(raw_effect))
                elif kind == "product_spec_approval":
                    self._store.put_approval(ProductSpecApproval.model_validate(raw_effect))
                else:
                    raise ProductRecordIntegrityError(
                        f"operation effect recovery kind is not supported: {kind!r}"
                    )
            except (TypeError, ValueError) as error:
                raise ProductRecordIntegrityError(
                    "operation effect recovery evidence is invalid"
                ) from error


def _validate_solution_design_authorization(
    authorization: StageAdvanceAuthorization,
    preparation: ProjectPreparation,
    project_request: ProjectRequest,
    product_spec: ProductSpec,
    approval: ProductSpecApproval,
) -> None:
    authorization.validate_integrity()
    expected_inputs = (
        preparation.preparation_sha256,
        project_request.request_sha256,
        product_spec.product_spec_sha256,
        approval.approval_sha256,
    )
    if (
        authorization.target is not ProjectStage.SOLUTION_DESIGN
        or authorization.project_id != preparation.project_id
        or authorization.input_sha256s != expected_inputs
    ):
        raise ProjectStageError(
            "stage authorization does not bind the exact solution-design prefix"
        )


def _dialogue_context(record: ProductDialogueRecord) -> ProductDialogueContextItem:
    return ProductDialogueContextItem(
        sequence=record.sequence,
        actor=record.actor,
        summary=record.content,
        previous_sha256=record.previous_dialogue_sha256,
        dialogue_sha256=record.dialogue_sha256,
    )


def _request_with_status(
    current: ProjectRequest, status: ProjectRequestStatus, now: datetime
) -> ProjectRequest:
    return ProjectRequest.create(
        request_id=current.id,
        project_id=current.project_id,
        preparation_sha256=current.preparation_sha256,
        title=current.title,
        original_request=current.original_request,
        status=status,
        created_at=current.created_at,
        updated_at=now,
    )


def _command_digest(command: DomainModel, **extra: str) -> str:
    payload: dict[str, object] = {"command": command.to_wire(), **extra}
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _result_identity(
    outcome: ProductDiscoveryOutcome,
    revision: int,
    error_code: ProductAgentErrorCode | None,
) -> str:
    error = "-" if error_code is None else error_code.value
    return f"{outcome.value}|{revision}|{error}"


def _parse_result_identity(
    identity: str,
) -> tuple[ProductDiscoveryOutcome, int, ProductAgentErrorCode | None]:
    try:
        outcome_text, revision_text, error_text = identity.split("|", maxsplit=2)
        outcome = ProductDiscoveryOutcome(outcome_text)
        revision = int(revision_text)
        error = None if error_text == "-" else ProductAgentErrorCode(error_text)
    except (TypeError, ValueError) as cause:
        raise ProductRecordIntegrityError("operation result identity is invalid") from cause
    if revision < 1:
        raise ProductRecordIntegrityError("operation checkpoint revision is invalid")
    failure = outcome in {
        ProductDiscoveryOutcome.AGENT_FAILED,
        ProductDiscoveryOutcome.AGENT_TIMED_OUT,
    }
    if failure != (error is not None):
        raise ProductRecordIntegrityError("operation failure identity is invalid")
    return outcome, revision, error


def _clarification_from_content(content: str) -> ProductClarification:
    try:
        return ProductClarification.model_validate(json.loads(content))
    except (TypeError, ValueError, json.JSONDecodeError) as cause:
        raise ProductRecordIntegrityError("clarification dialogue is invalid") from cause


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


__all__ = [
    "HumanProductDecisionCommand",
    "HumanProductDecisionVerifier",
    "ProductAgentExecutionError",
    "ProductAgentOutputRejected",
    "ProductDiscoveryAlreadyStarted",
    "ProductDiscoveryError",
    "ProductDiscoveryNotStarted",
    "ProductDiscoveryOutcome",
    "ProductDiscoveryResult",
    "ProductDiscoveryService",
    "ProductDiscoveryStaleCheckpoint",
    "ProductDiscoveryStateError",
    "ProductOperationConflict",
    "RecordHumanMessageCommand",
    "RunProductAgentCommand",
    "StartProductDiscoveryCommand",
    "VerifiedHumanProductDecision",
]
