"""Trusted source-bound workspace admission shared by supported provider routes."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from ai_software_engineer.agents.continuation import InterruptionAdmissionRejected
from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.domain.artifact import ImplementationReportArtifact
from ai_software_engineer.domain.enums import AgentRole


class WorkspaceAdmissionRejected(InterruptionAdmissionRejected):
    """A trusted workspace precondition failed before the provider was invoked."""


class InitialWorkspaceAdmission(Protocol):
    """Authorize an exact recovery seed; never grant an arbitrary dirty allowance."""

    def authorize(self, request: AgentRequest, workspace_root: Path) -> None: ...


@runtime_checkable
class RequestWorkspaceAdmission(Protocol):
    """Select from trusted durable execution facts, never an attempt counter."""

    def for_request(self, request: AgentRequest) -> InitialWorkspaceAdmission | None: ...


@dataclass(frozen=True, slots=True)
class FirstCoderRunWorkspaceAdmission:
    """Explicit seed policy across fresh provider adapters, never a live authority cache.

    The delegate selects seed versus normal checkpoint checks from durable facts.
    Unscoped delegates remain authoritative on every call: an attempt number does
    not prove that knowledge preparation reached the main role invocation.
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
    try:
        if isinstance(admission, ConditionalWorkspaceAdmission):
            return workspace_admission_for_request(admission.select(request), request)
        if isinstance(admission, FirstCoderRunWorkspaceAdmission):
            delegate = admission.delegate
            if isinstance(delegate, RequestWorkspaceAdmission):
                return workspace_admission_for_request(delegate.for_request(request), request)
            return delegate
        return admission
    except ValueError as error:
        raise WorkspaceAdmissionRejected("恢复工作区的准入条件校验未通过") from error


def authorize_workspace_admission(
    admission: InitialWorkspaceAdmission, request: AgentRequest, workspace_root: Path
) -> None:
    """Validation failures are preconditions; ownership and waiting signals propagate."""
    try:
        admission.authorize(request, workspace_root)
    except ValueError as error:
        raise WorkspaceAdmissionRejected("恢复工作区的准入条件校验未通过") from error


@runtime_checkable
class RetainedCandidateReportAdmission(InitialWorkspaceAdmission, Protocol):
    """A trusted consumed recovery, never an Agent-provided comparison revision."""

    def retained_candidate_report_base(
        self,
        request: AgentRequest,
        workspace_root: Path,
        artifact: ImplementationReportArtifact,
    ) -> str: ...


def retained_candidate_report_base(
    admission: InitialWorkspaceAdmission | None,
    request: AgentRequest,
    workspace_root: Path,
    artifact: ImplementationReportArtifact,
) -> str | None:
    if (
        request.role is not AgentRole.CODER
        or request.execution_baseline_sha256 is None
        or request.execution_base_ref is None
    ):
        return None
    selected = workspace_admission_for_request(admission, request)
    if not isinstance(selected, RetainedCandidateReportAdmission):
        return None
    base = selected.retained_candidate_report_base(request, workspace_root, artifact)
    if base != request.execution_base_ref or base == request.source_revision:
        raise WorkspaceAdmissionRejected("保留候选报告缺少精确原执行基线")
    return base
