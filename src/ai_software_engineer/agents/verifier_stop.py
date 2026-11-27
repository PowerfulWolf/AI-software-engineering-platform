"""Actual QA/Reviewer execution stops, observed by the adapter that ran the role.

A rejected verifier output can only be rerun when the original execution is proven
stopped. The adapter that owned the execution records exactly what it observed:
an owned native process-session stop (Codex CLI), or the synchronous Responses tool
loop having returned. Nothing here infers a stop from a lease, a timeout or text.

The capture is a context-local slot bound by the role runner around one exact
invocation, so a recording can never attach to another request.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from ai_software_engineer.agents.execution import (
    ExecutionStop,
    NativeProcessStop,
    SynchronousToolLoopStop,
)
from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.knowledge.models import digest

VERIFIER_ROLES = frozenset({AgentRole.QA, AgentRole.REVIEWER})


@dataclass
class _Capture:
    request_sha256: str
    stop: ExecutionStop | None = None


_capture: ContextVar[_Capture | None] = ContextVar("verifier_stop_capture", default=None)


@contextmanager
def capture_verifier_stop(request: AgentRequest) -> Iterator[None]:
    """Bind one exact verifier invocation; other roles bind nothing."""
    if request.role not in VERIFIER_ROLES:
        yield
        return
    binding = _capture.set(_Capture(digest(request.to_wire())))
    try:
        yield
    finally:
        _capture.reset(binding)


def record_verifier_stop(request: AgentRequest, stop: ExecutionStop | None) -> None:
    """Record the adapter's own stop observation for the bound exact request."""
    capture = _capture.get()
    if (
        stop is None
        or capture is None
        or request.role not in VERIFIER_ROLES
        or capture.request_sha256 != digest(request.to_wire())
    ):
        return
    stop.validate_integrity()
    if isinstance(stop, SynchronousToolLoopStop):
        stop.require_request(request)
    elif not isinstance(stop, NativeProcessStop) or stop.session_proof is None:
        # Legacy leader/group observations cannot prove the whole owned session ended.
        return
    capture.stop = stop


def current_verifier_stop(request: AgentRequest) -> ExecutionStop | None:
    capture = _capture.get()
    if capture is None or capture.request_sha256 != digest(request.to_wire()):
        return None
    return capture.stop
