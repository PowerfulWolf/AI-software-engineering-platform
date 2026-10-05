"""Trusted pre-model verifier observations; absence is scoped to the claimed Run."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.native_verification import (
    NativeVerificationWaitReason,
    role_verification_digest,
)
from ai_software_engineer.manager.native_verification_store import NativeRoleVerificationBinding
from ai_software_engineer.recovery.verification_records import VerificationExecutionRecord

NativeExecutionState = Literal["NOT_STARTED", "FINISHED", "UNCERTAIN"]


class VerifierPreparationObservation(DomainModel):
    native_execution_state: NativeExecutionState
    native_binding_plan_sha256: Sha256 | None = None
    native_started_sha256: Sha256 | None = None
    native_finished_sha256: Sha256 | None = None
    native_failure_code: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.native_execution_state == "NOT_STARTED" and (
            self.native_started_sha256 is not None or self.native_finished_sha256 is not None
        ):
            raise ValueError("unstarted verification cannot reference execution receipts")
        if self.native_execution_state == "FINISHED" and (
            self.native_binding_plan_sha256 is None
            or self.native_started_sha256 is None
            or self.native_finished_sha256 is None
        ):
            raise ValueError("finished verification requires binding and both receipts")
        if self.native_failure_code is not None and self.native_execution_state != "FINISHED":
            raise ValueError("only a sealed finished command establishes its failure")
        return self


class VerifierPreparationIntent(DomainModel):
    """Original claimed request sealed before any native verification can begin."""

    kind: Literal["verifier_preparation_intent"] = "verifier_preparation_intent"
    work_item_id: NonEmptyStr
    lease_id: NonEmptyStr
    task_id: NonEmptyStr
    task_snapshot_sha256: Sha256
    checkpoint_sequence: Annotated[int, Field(ge=0)]
    dispatch_sequence: Annotated[int, Field(ge=0)]
    request: AgentRequest
    request_sha256: Sha256
    started_at: AwareDatetime
    intent_sha256: Sha256

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if (
            self.request.role not in (AgentRole.QA, AgentRole.REVIEWER)
            or self.request.task_id != self.task_id
            or self.request_sha256 != role_verification_digest(self.request.to_wire())
        ):
            raise ValueError("preparation intent must bind its exact claimed verifier request")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "intent_sha256": "0" * 64})
        return value.model_copy(update={"intent_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return role_verification_digest(self.model_dump(mode="json", exclude={"intent_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.intent_sha256 != self.recompute_sha256():
            raise ValueError("verifier preparation intent changed")


class VerifierPreparationCheckpoint(DomainModel):
    kind: Literal["verifier_preparation_checkpoint"] = "verifier_preparation_checkpoint"
    work_item_id: NonEmptyStr
    lease_id: NonEmptyStr
    task_id: NonEmptyStr
    task_snapshot_sha256: Sha256
    checkpoint_sequence: Annotated[int, Field(ge=0)]
    dispatch_sequence: Annotated[int, Field(ge=0)]
    wait_dispatch_sequence: Annotated[int, Field(ge=0)]
    wait_lease_id: NonEmptyStr
    intent_sha256: Sha256
    source_revision: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
    run_id: NonEmptyStr
    role: Literal[AgentRole.QA, AgentRole.REVIEWER]
    attempt: Annotated[int, Field(ge=1)]
    context_manifest_id: NonEmptyStr
    request_sha256: Sha256
    request: AgentRequest
    result: Literal["READY", "WAIT"]
    observation: VerifierPreparationObservation
    failure_reason: NativeVerificationWaitReason | None = None
    checked_at: AwareDatetime
    checkpoint_sha256: Sha256

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.request_sha256 != role_verification_digest(self.request.to_wire()) or (
            self.task_id,
            self.run_id,
            self.role,
            self.attempt,
            self.source_revision,
            self.context_manifest_id,
        ) != (
            self.request.task_id,
            self.request.run_id,
            self.request.role,
            self.request.attempt,
            self.request.source_revision,
            self.request.context_manifest_id,
        ):
            raise ValueError("preparation marker must bind its exact original claimed request")
        if self.wait_dispatch_sequence < self.dispatch_sequence:
            raise ValueError("preparation wait cannot precede its original dispatch")
        if (self.result == "WAIT") != (self.failure_reason is not None):
            raise ValueError("waiting preparation requires a typed failure reason")
        if self.result == "READY" and self.observation.native_execution_state == "UNCERTAIN":
            raise ValueError("uncertain verification cannot become ready")
        if self.result == "READY" and (
            self.lease_id != self.wait_lease_id
            or self.dispatch_sequence != self.wait_dispatch_sequence
        ):
            raise ValueError("preparation readiness belongs only to its original live claim")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "checkpoint_sha256": "0" * 64})
        return value.model_copy(update={"checkpoint_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return role_verification_digest(self.model_dump(mode="json", exclude={"checkpoint_sha256"}))

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.checkpoint_sha256 != self.recompute_sha256():
            raise ValueError("verifier preparation checkpoint changed")


def _read[T: DomainModel](path: Path, model: type[T]) -> T | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("native preparation record must be a regular file")
        raw = stream.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError("native preparation record exceeded its bound")
    return model.model_validate_json(raw)


def observe_verifier_preparation(
    *,
    repository_workspace_root: Path,
    request: AgentRequest,
    lease_id: str,
) -> VerifierPreparationObservation:
    """Read immutable native records without running cleanup, models, or commands.

    Called while the application still owns the original real claim, before its
    MODEL invocation starts. Corrupt, mismatched or partial records are uncertain.
    """
    started: VerificationExecutionRecord | None = None
    binding: NativeRoleVerificationBinding | None = None
    try:
        sidecar = repository_workspace_root.absolute()
        root = (
            sidecar
            / "native-role-verification"
            / hashlib.sha256(request.task_id.encode()).hexdigest()
            / hashlib.sha256(request.run_id.encode()).hexdigest()
        )
        if sidecar.resolve(strict=True) != sidecar or any(
            parent.is_symlink() for parent in (root, *root.parents)
        ):
            raise ValueError("native preparation sidecar identity changed")
        binding = _read(root / "binding.json", NativeRoleVerificationBinding)
        started = _read(root / "started.json", VerificationExecutionRecord)
        finished = _read(root / "finished.json", VerificationExecutionRecord)
        if binding is None:
            if started is not None or finished is not None:
                raise ValueError("execution receipts have no original admitted binding")
            return VerifierPreparationObservation(native_execution_state="NOT_STARTED")
        binding.validate_integrity()
        plan = binding.plan
        if (
            plan.request_sha256 != role_verification_digest(request.to_wire())
            or plan.claim.lease_id != lease_id
            or (
                plan.task_id,
                plan.run_id,
                plan.role,
                plan.attempt,
                plan.candidate_revision,
                plan.context_manifest_id,
            )
            != (
                request.task_id,
                request.run_id,
                request.role,
                request.attempt,
                request.source_revision,
                request.context_manifest_id,
            )
        ):
            raise ValueError("native binding does not belong to this exact claimed request")
        if started is None:
            if finished is not None:
                raise ValueError("native final receipt has no durable start")
            return VerifierPreparationObservation(
                native_execution_state="NOT_STARTED",
                native_binding_plan_sha256=plan.plan_sha256,
            )
        for record in (started, finished):
            if record is None:
                continue
            record.validate_integrity()
            if (
                record.plan_sha256 != plan.plan_sha256
                or record.invocation_sha256 != plan.request_sha256
                or record.authorization_sha256 != binding.admission.admission_sha256
                or record.candidate_revision != request.source_revision
                or record.role is not request.role
                or record.source_root != plan.workspace_root
                or record.capability != binding.capability
            ):
                raise ValueError("native receipt differs from its original role binding")
        if started.phase != "STARTED":
            raise ValueError("native STARTED record has another phase")
        if finished is None:
            return VerifierPreparationObservation(
                native_execution_state="UNCERTAIN",
                native_binding_plan_sha256=plan.plan_sha256,
                native_started_sha256=started.record_sha256,
            )
        excluded = {"phase", "recorded_at", "record_sha256", "results", "failure_code"}
        if (
            finished.phase == "STARTED"
            or finished.recorded_at < started.recorded_at
            or finished.model_dump(exclude=excluded) != started.model_dump(exclude=excluded)
        ):
            raise ValueError("native final receipt changed its original execution")
        return VerifierPreparationObservation(
            native_execution_state="FINISHED",
            native_binding_plan_sha256=plan.plan_sha256,
            native_started_sha256=started.record_sha256,
            native_finished_sha256=finished.record_sha256,
            native_failure_code=finished.effective_failure_code,
        )
    except (OSError, ValueError):
        return VerifierPreparationObservation(native_execution_state="UNCERTAIN")
