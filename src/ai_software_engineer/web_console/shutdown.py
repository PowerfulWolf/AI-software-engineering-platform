"""Typed, local admission and readiness facts for controlled service shutdown.

This module coordinates application lifetimes, not Task ownership or role verdicts.
An admission lease stays live until the actual writer returns, including when the
HTTP caller has disconnected or cancelled its own task.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from threading import Condition, Lock
from time import monotonic

from pydantic import Field, model_validator

from ai_software_engineer.domain.model import DomainModel, NonEmptyStr


class ShutdownState(StrEnum):
    RUNNING = "RUNNING"
    DRAINING = "DRAINING"
    READY = "READY"
    REFUSED = "REFUSED"


class ShutdownResult(DomainModel):
    """Readiness of one component; the Host must verify every component."""

    state: ShutdownState
    safe_summary: NonEmptyStr
    active_operations: int = Field(default=0, ge=0)
    active_writes: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def ready_requires_no_active_work(self) -> ShutdownResult:
        if self.state is ShutdownState.READY and (self.active_operations or self.active_writes):
            raise ValueError("shutdown readiness cannot contain active operation or write facts")
        return self


class ServiceDraining(RuntimeError):
    """A new writer was refused before it could change durable state."""

    code = "SERVICE_DRAINING"
    safe_summary = "ASE 正在安全停止, 暂不接收新的操作; 请等待收尾或解除安全停止后重试。"

    def __init__(self) -> None:
        super().__init__(self.safe_summary)


def shutdown_deadline(timeout: float) -> float:
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("shutdown timeout must be finite and non-negative")
    return monotonic() + timeout


class ServiceWriteLease:
    """A retained writer reference; release only when its actual work finishes."""

    def __init__(self, gate: ServiceWriteGate) -> None:
        self._gate = gate
        self._released = False

    def retain(self) -> ServiceWriteLease:
        """Continue an already admitted request without admitting unrelated work."""
        with self._gate._condition:
            if self._released:
                raise RuntimeError("released service write lease cannot be retained")
            self._gate._active += 1
            return ServiceWriteLease(self._gate)

    def release(self) -> None:
        with self._gate._condition:
            if self._released:
                return
            self._released = True
            self._gate._active -= 1
            self._gate._condition.notify_all()


class ServiceWriteGate:
    """Linearize new HTTP writes with drain and await existing writers."""

    def __init__(self) -> None:
        self._condition = Condition(Lock())
        self._draining = False
        self._ready = False
        self._timed_out = False
        self._active = 0

    def acquire_write(self) -> ServiceWriteLease:
        with self._condition:
            if self._draining:
                raise ServiceDraining()
            self._active += 1
            return ServiceWriteLease(self)

    @contextmanager
    def enter(self) -> Iterator[ServiceWriteLease]:
        lease = self.acquire_write()
        try:
            yield lease
        finally:
            lease.release()

    def begin_shutdown(self) -> ShutdownResult:
        with self._condition:
            self._draining = True
            return self._result_locked()

    def await_shutdown(self, timeout: float) -> ShutdownResult:
        deadline = shutdown_deadline(timeout)
        with self._condition:
            if not self._draining:
                return self._result_locked()
            while self._active:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    self._timed_out = True
                    return self._result_locked()
                self._condition.wait(remaining)
                if self._drain_cancelled_locked():
                    return self._result_locked()
            self._ready = True
            self._timed_out = False
            return self._result_locked()

    def cancel_shutdown(self) -> ShutdownResult:
        with self._condition:
            self._draining = False
            self._ready = False
            self._timed_out = False
            self._condition.notify_all()
            return self._result_locked()

    def shutdown_status(self) -> ShutdownResult:
        with self._condition:
            return self._result_locked()

    def _drain_cancelled_locked(self) -> bool:
        return not self._draining

    def _result_locked(self) -> ShutdownResult:
        if not self._draining:
            state = ShutdownState.RUNNING
            summary = "ASE 正常接收操作。"
        elif self._ready:
            state = ShutdownState.READY
            summary = "已进入的写入全部完成, 写入入口已安全停止。"
        elif self._timed_out:
            state = ShutdownState.REFUSED
            summary = "现有写入仍在收尾, 未安全停止; 服务保留, 可稍后重试或解除安全停止。"
        else:
            state = ShutdownState.DRAINING
            summary = "已停止接收新写入, 正在等待现有写入收尾。"
        return ShutdownResult(state=state, safe_summary=summary, active_writes=self._active)


__all__ = [
    "ServiceDraining",
    "ServiceWriteGate",
    "ServiceWriteLease",
    "ShutdownResult",
    "ShutdownState",
    "shutdown_deadline",
]
