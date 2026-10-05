"""Trusted source-bound workspace admission shared by supported provider routes."""

from pathlib import Path
from typing import Protocol

from ai_software_engineer.agents.models import AgentRequest


class InitialWorkspaceAdmission(Protocol):
    """Authorize an exact recovery seed; never grant an arbitrary dirty allowance."""

    def authorize(self, request: AgentRequest, workspace_root: Path) -> None: ...
