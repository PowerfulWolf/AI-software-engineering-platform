"""Context compilation seams independent of filesystem and model adapters."""

from typing import Protocol

from ai_software_engineer.context.models import ContextBundle, ContextSource
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.task import Task


class ContextError(RuntimeError):
    """Base class for stable Context Builder failures."""


class ContextSourceError(ContextError):
    """Raised when a declared source is malformed or cannot be decoded."""


class ContextSourceNotFound(ContextSourceError):
    """Raised when a required file source does not exist."""


class ContextSourceDenied(ContextSourceError):
    """Raised when a file source is outside the role read policy."""


class ContextBudgetExceeded(ContextError):
    """Raised when required context cannot fit within the configured input budget."""


class ContextRouter(Protocol):
    @staticmethod
    def route(sources: tuple[ContextSource, ...], role: AgentRole) -> tuple[ContextSource, ...]: ...


class ContextBuilder(Protocol):
    def build(
        self,
        task: Task,
        role: AgentRole,
        *,
        attempt: int,
        candidate_revision: str | None = None,
    ) -> ContextBundle: ...


__all__ = [
    "ContextBudgetExceeded",
    "ContextBuilder",
    "ContextError",
    "ContextRouter",
    "ContextSourceDenied",
    "ContextSourceError",
    "ContextSourceNotFound",
]
