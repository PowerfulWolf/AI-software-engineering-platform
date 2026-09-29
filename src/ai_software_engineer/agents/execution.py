"""Optional trusted execution ownership, independent of queue implementations."""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from contextvars import ContextVar
from typing import Protocol


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
