"""Optional trusted execution ownership, independent of queue implementations."""

from contextlib import AbstractContextManager, nullcontext
from typing import Protocol


class ExecutionGuard(Protocol):
    @property
    def inherited_fds(self) -> tuple[int, ...]: ...

    def check(self) -> None: ...

    def write_scope(self) -> AbstractContextManager[None]: ...


def execution_scope(guard: ExecutionGuard | None) -> AbstractContextManager[None]:
    return guard.write_scope() if guard is not None else nullcontext()
