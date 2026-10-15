"""Optional trusted execution ownership, independent of queue implementations."""

import hashlib
import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from contextvars import ContextVar
from typing import Annotated, Literal, Protocol, Self

from pydantic import AwareDatetime, ConfigDict, Field, StrictInt, model_validator

from ai_software_engineer.agents.models import AgentRequest, AgentResult
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.owned_sessions import OwnedSessionStopProof


class ExecutionAbortReason(DomainModel):
    """Safe trusted authority facts, never provider text or an automatic retry cause."""

    kind: Literal["lease_authority_unconfirmed"] = "lease_authority_unconfirmed"
    detail: Literal["local_expiry", "renewal_exception", "heartbeat_stop_timeout"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class ExecutionAuthorityLost(RuntimeError):
    """An execution guard revoked authority; callers must retain the original fence."""

    def __init__(
        self,
        message: str,
        *,
        execution_abort_reason: ExecutionAbortReason | None = None,
    ) -> None:
        self.execution_abort_reason = execution_abort_reason or ExecutionAbortReason()
        super().__init__(message)


class AgentInvocationControl(Protocol):
    """Durable exact request/result journal, owned by trusted composition."""

    def prepare(self, request: AgentRequest) -> AgentRequest: ...

    def completed(self, request: AgentRequest, result: AgentResult) -> None: ...

    def result(self, request: AgentRequest) -> AgentResult | None: ...


class NativeProcessStop(DomainModel):
    """Legacy leader/group stop, optionally with a new explicit owned-SID proof."""

    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {"required": ["kind"], "properties": {"kind": {"const": "completed"}}},
                    "then": {"properties": {"returncode": {"const": 0}}},
                },
                {
                    "if": {"required": ["kind"], "properties": {"kind": {"const": "failed"}}},
                    "then": {"properties": {"returncode": {"not": {"const": 0}}}},
                },
                {
                    "if": {
                        "required": ["kind"],
                        "properties": {"kind": {"const": "service_pause"}},
                    },
                    "then": {
                        "required": ["session_proof"],
                        "properties": {"session_proof": {"type": "object"}},
                    },
                },
            ]
        }
    )

    process_id: Annotated[StrictInt, Field(gt=0)]
    group_id: Annotated[StrictInt, Field(gt=0)]
    returncode: StrictInt
    kind: Literal["completed", "failed", "local_execution_limit", "service_pause"]
    stopped_at: AwareDatetime
    stop_sha256: StageSha256
    session_proof: OwnedSessionStopProof | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "stop_sha256": "0" * 64})
        return value.model_copy(update={"stop_sha256": value.recompute_sha256()})

    @model_validator(mode="after")
    def validate_owned_session(self) -> Self:
        if self.group_id != self.process_id:
            raise ValueError("native stop requires the runner-owned process session")
        if self.kind == "service_pause" and self.session_proof is None:
            raise ValueError("service pause requires a complete actual owned-session proof")
        if (self.kind == "completed" and self.returncode != 0) or (
            self.kind == "failed" and self.returncode == 0
        ):
            raise ValueError("native stop kind must agree with process result")
        if self.session_proof is not None:
            self.session_proof.validate_integrity()
            if self.session_proof.leader.process_id != self.process_id:
                raise ValueError("native stop session proof belongs to another spawned leader")
            if self.session_proof.observed_at > self.stopped_at:
                raise ValueError("native stop cannot predate its owned-session observation")
        return self

    def recompute_sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json", exclude={"stop_sha256"}),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.stop_sha256 != self.recompute_sha256():
            raise ValueError("native stop digest mismatch")


class SynchronousToolLoopStop(DomainModel):
    """Trusted observation after a synchronous Responses route and its tools returned.

    This is not a native process-group observation. The provider generates data;
    only the bounded local registry runs tools, sequentially and synchronously.
    An interrupted Host cannot create this receipt, nor can request/model text.
    """

    origin: Literal["synchronous_responses_tool_loop"] = "synchronous_responses_tool_loop"
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    request_sha256: StageSha256
    completed_operation_ids: tuple[NonEmptyStr, ...]
    kind: Literal["failed", "local_execution_limit", "service_pause"] = "failed"
    stopped_at: AwareDatetime
    stop_sha256: StageSha256

    @model_validator(mode="after")
    def validate_operations(self) -> Self:
        ensure_unique(self.completed_operation_ids, "completed synchronous operations")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "stop_sha256": "0" * 64})
        return value.model_copy(update={"stop_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json", exclude={"stop_sha256"}),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.stop_sha256 != self.recompute_sha256():
            raise ValueError("synchronous tool-loop stop digest mismatch")

    def require_request(self, request: AgentRequest) -> None:
        from ai_software_engineer.knowledge.models import digest

        self.validate_integrity()
        if (self.task_id, self.run_id, self.request_sha256) != (
            request.task_id,
            request.run_id,
            digest(request.to_wire()),
        ):
            raise ValueError("synchronous tool-loop stop belongs to another exact request")


ExecutionStop = NativeProcessStop | SynchronousToolLoopStop


class ExecutionGuard(Protocol):
    @property
    def inherited_fds(self) -> tuple[int, ...]: ...

    def check(self) -> None: ...

    def write_scope(self) -> AbstractContextManager[None]: ...


def execution_scope(guard: ExecutionGuard | None) -> AbstractContextManager[None]:
    return guard.write_scope() if guard is not None else nullcontext()


_structured_guard: ContextVar[ExecutionGuard | None] = ContextVar("structured_guard", default=None)


def current_execution_guard() -> ExecutionGuard | None:
    return _structured_guard.get()


@contextmanager
def bind_execution_guard(guard: ExecutionGuard) -> Iterator[None]:
    token = _structured_guard.set(guard)
    try:
        guard.check()
        yield
        guard.check()
    finally:
        _structured_guard.reset(token)


class PausedInvocationProof(DomainModel):
    """Trusted stopped/no-start execution bound to one exact admitted request."""

    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "required": ["admission_closed"],
                        "properties": {"admission_closed": {"const": True}},
                    },
                    "then": {"properties": {"process_stop": {"type": "null"}}},
                    "else": {
                        "required": ["process_stop"],
                        "properties": {
                            "process_stop": {
                                "type": "object",
                                "properties": {"kind": {"const": "service_pause"}},
                            }
                        },
                    },
                }
            ]
        }
    )

    request: AgentRequest
    process_stop: NativeProcessStop | SynchronousToolLoopStop | None = None
    admission_closed: bool = False
    proof_sha256: StageSha256

    @model_validator(mode="after")
    def validate_stop(self) -> Self:
        if self.admission_closed == (self.process_stop is not None):
            raise ValueError("pause requires exactly one real stop or confirmed no-start")
        if self.process_stop is not None:
            self.process_stop.validate_integrity()
            if self.process_stop.kind != "service_pause":
                raise ValueError("paused invocation requires the exact service pause cause")
            if isinstance(self.process_stop, SynchronousToolLoopStop):
                self.process_stop.require_request(self.request)
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "proof_sha256": "0" * 64})
        return value.model_copy(update={"proof_sha256": value.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json", exclude={"proof_sha256"}),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.proof_sha256 != self.recompute_sha256():
            raise ValueError("paused invocation proof digest mismatch")
