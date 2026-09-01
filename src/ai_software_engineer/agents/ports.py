"""Agent adapter protocol and stable configuration errors."""

from typing import Protocol

from ai_software_engineer.agents.models import AgentRequest, AgentResult


class AgentError(RuntimeError):
    """Base class for adapter invocation/configuration failures."""


class AgentRequestConflict(AgentError):
    """Raised when one run ID is reused with a different request identity."""


class AgentConfigurationError(AgentError):
    """Raised when a fake scenario is absent or incompatible with a request."""


class AgentAdapter(Protocol):
    """Stable seam shared by fake and future provider-backed adapters."""

    def run(self, request: AgentRequest) -> AgentResult: ...


__all__ = [
    "AgentAdapter",
    "AgentConfigurationError",
    "AgentError",
    "AgentRequestConflict",
]
