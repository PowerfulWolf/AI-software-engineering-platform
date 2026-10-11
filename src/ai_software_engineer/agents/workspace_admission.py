"""Trusted source-bound workspace admission shared by supported provider routes."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ai_software_engineer.agents.models import AgentRequest


class InitialWorkspaceAdmission(Protocol):
    """Authorize an exact recovery seed; never grant an arbitrary dirty allowance."""

    def authorize(self, request: AgentRequest, workspace_root: Path) -> None: ...


@dataclass(frozen=True, slots=True)
class FirstCoderRunWorkspaceAdmission:
    """Explicit seed policy across fresh provider adapters, never a live authority cache.

    Later Coder runs use their normal accepted progress/candidate checks. Ports
    without this wrapper (including same-Task baselines) still run on every call.
    The delegate retains exact Task/context/claim and at-most-once verification.
    """

    delegate: InitialWorkspaceAdmission

    def authorize(self, request: AgentRequest, workspace_root: Path) -> None:
        self.delegate.authorize(request, workspace_root)


@dataclass(frozen=True, slots=True)
class ConditionalWorkspaceAdmission:
    """Choose a trusted exact admission, preserving None and the default dirty gate."""

    select: Callable[[AgentRequest], InitialWorkspaceAdmission | None]

    def authorize(self, request: AgentRequest, workspace_root: Path) -> None:
        selected = workspace_admission_for_request(self.select(request), request)
        if selected is None:
            raise ValueError("conditional admission must be resolved before workspace checks")
        selected.authorize(request, workspace_root)


def workspace_admission_for_request(
    admission: InitialWorkspaceAdmission | None, request: AgentRequest
) -> InitialWorkspaceAdmission | None:
    if isinstance(admission, ConditionalWorkspaceAdmission):
        return workspace_admission_for_request(admission.select(request), request)
    if isinstance(admission, FirstCoderRunWorkspaceAdmission) and request.attempt > 1:
        return None
    return admission
