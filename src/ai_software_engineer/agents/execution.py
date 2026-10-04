"""Optional trusted execution ownership, independent of queue implementations."""

import hashlib
import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from contextvars import ContextVar
from typing import Annotated, Literal, Protocol, Self

from pydantic import AwareDatetime, Field, StrictInt, model_validator

from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.project_delivery import StageSha256


class NativeProcessStop(DomainModel):
    """Trusted runner observation of its own session after process-group shutdown."""

    process_id: Annotated[StrictInt, Field(gt=0)]
    group_id: Annotated[StrictInt, Field(gt=0)]
    returncode: StrictInt
    kind: Literal["completed", "failed", "local_execution_limit"]
    stopped_at: AwareDatetime
    stop_sha256: StageSha256

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "stop_sha256": "0" * 64})
        return value.model_copy(update={"stop_sha256": value.recompute_sha256()})

    @model_validator(mode="after")
    def validate_owned_session(self) -> Self:
        if self.group_id != self.process_id:
            raise ValueError("native stop requires the runner-owned process session")
        if (self.kind == "completed" and self.returncode != 0) or (
            self.kind == "failed" and self.returncode == 0
        ):
            raise ValueError("native stop kind must agree with process result")
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
