"""Positive Host pause refusal before structured execution admission."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from ai_software_engineer.agents.model_diagnostics import CallPhase
from ai_software_engineer.agents.structured_observation import (
    ObservationId,
    StructuredCallIdentity,
    observation_digest,
)
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.project_delivery import StageSha256

PreAdmissionPauseOrigin = Literal[
    "fallback_before_route",
    "native_client_entry",
    "responses_client_entry",
    "responses_before_transport_admission",
]


class StructuredPreAdmissionPauseReceipt(DomainModel):
    """A refusal is neither an admission nor proof that a started process stopped."""

    kind: Literal["structured_pre_admission_pause"] = "structured_pre_admission_pause"
    schema_version: Literal["v1"] = "v1"
    origin: PreAdmissionPauseOrigin
    request_sha256: StageSha256
    timeout_seconds: int = Field(ge=1, le=86_400)
    phase: CallPhase
    role: TeamRole | None = None
    invocation_id: ObservationId | None = None
    selected_call: StructuredCallIdentity | None = None
    operation_id: NonEmptyStr
    pause_request_id: NonEmptyStr
    pause_instance_id: NonEmptyStr | None = None
    pause_requested_at: AwareDatetime
    refused_at: AwareDatetime
    receipt_sha256: StageSha256

    @model_validator(mode="after")
    def require_exact_refusal(self) -> Self:
        if self.refused_at < self.pause_requested_at:
            raise ValueError("structured refusal predates its Host pause")
        if self.origin == "fallback_before_route" and (
            self.selected_call is not None or self.invocation_id is None
        ):
            raise ValueError("unselected fallback refusal cannot invent a route")
        call = self.selected_call
        if call is not None and (
            call.request_sha256 != self.request_sha256
            or call.phase != self.phase
            or call.role != self.role
            or call.invocation_id != self.invocation_id
        ):
            raise ValueError("structured refusal changed the selected call identity")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "receipt_sha256": "0" * 64})
        return value.model_copy(update={"receipt_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return observation_digest(self.model_dump(mode="json", exclude={"receipt_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.receipt_sha256 != self.recompute_sha256():
            raise ValueError("structured pre-admission pause digest mismatch")
