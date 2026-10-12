"""Exact no-invocation preparation observations, with no execution authority."""

from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    Field,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.context.models import ContextId
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.knowledge.models import digest

Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]


class ContextCapacityReceipt(DomainModel):
    """A future exact failed preparation or an explicitly retrospective observation.

    A legacy record never invents the missing AgentRequest, Run or final token count.
    Neither origin proves an invocation result, approves recovery or refunds work.
    """

    kind: Literal["context_capacity_receipt"] = "context_capacity_receipt"
    schema_version: Literal["v1"] = "v1"
    origin: Literal["final_input", "legacy_terminal_context"]
    task_id: NonEmptyStr
    task_sha256: Sha256
    task_intent_sha256: Sha256
    task_revision: NonNegativeInt
    work_item_id: NonEmptyStr
    lease_id: NonEmptyStr
    assignment_id: NonEmptyStr
    claim_sha256: Sha256
    dispatch_sequence: NonNegativeInt
    checkpoint_sequence: NonNegativeInt
    role: AgentRole
    attempt: PositiveInt
    source_revision: NonEmptyStr
    context_manifest_id: ContextId
    context_sha256: Sha256
    max_input_tokens: PositiveInt
    context_input_tokens: NonNegativeInt
    final_input_tokens: PositiveInt | None = None
    request: AgentRequest | None = None
    execution_baseline_sha256: Sha256 | None = None
    legacy_terminal_event_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    legacy_terminal_source_revision: NonEmptyStr | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    provider_started: Literal[False] = False
    observed_at: AwareDatetime
    receipt_sha256: Sha256

    @field_validator("provider_started", mode="before")
    @classmethod
    def require_definitive_no_start(cls, value: object) -> object:
        if value is not False:
            raise ValueError("capacity receipt requires an explicit false no-start observation")
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if (self.legacy_terminal_event_sha256 is None) != (
            self.legacy_terminal_source_revision is None
        ):
            raise ValueError(
                "legacy terminal event digest and original source must appear together"
            )
        if self.role not in (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER):
            raise ValueError("capacity receipt requires a delivery role")
        if self.origin == "final_input":
            if self.legacy_terminal_event_sha256 is not None:
                raise ValueError("final input receipt cannot carry legacy terminal facts")
            request = self.request
            if request is None or self.final_input_tokens is None:
                raise ValueError("final input capacity requires its actual request and estimate")
            if self.final_input_tokens <= self.max_input_tokens:
                raise ValueError("final input capacity requires an actual overflow")
            if (
                request.task_id,
                request.role,
                request.attempt,
                request.source_revision,
                request.context_manifest_id,
                request.execution_baseline_sha256,
            ) != (
                self.task_id,
                self.role,
                self.attempt,
                self.source_revision,
                self.context_manifest_id,
                self.execution_baseline_sha256,
            ):
                raise ValueError("capacity request differs from its exact preparation")
        elif self.request is not None or self.final_input_tokens is not None:
            raise ValueError("legacy capacity cannot invent the missing original request or count")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.receipt_sha256 != digest(self.model_dump(mode="json", exclude={"receipt_sha256"})):
            raise ValueError("context capacity receipt integrity mismatch")
