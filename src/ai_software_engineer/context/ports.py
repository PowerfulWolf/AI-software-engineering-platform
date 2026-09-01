"""Context compilation seams independent of filesystem and model adapters."""

from typing import Protocol

from ai_software_engineer.context.models import ContextBundle, ContextId, ContextSource
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


class ContextStoreError(ContextError):
    """Base class for ContextBundle registration and lookup failures."""


class ContextNotFound(ContextStoreError):
    """Raised when an Agent request references an unknown Context manifest."""


class ContextCorruption(ContextStoreError):
    """Raised when a persisted Context manifest is malformed or fails identity validation."""


class ContextConflict(ContextStoreError):
    """Raised when one Context ID is reused for a different manifest identity."""


class ContextIntegrityError(ContextConflict):
    """Raised when Context content does not produce its declared canonical ID."""


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


class ContextStore(Protocol):
    """Registry seam shared by Context builders and provider prompt resolvers."""

    def put(self, context: ContextBundle) -> ContextBundle: ...

    def get(self, context_id: ContextId) -> ContextBundle: ...


__all__ = [
    "ContextBudgetExceeded",
    "ContextBuilder",
    "ContextConflict",
    "ContextCorruption",
    "ContextError",
    "ContextIntegrityError",
    "ContextNotFound",
    "ContextRouter",
    "ContextSourceDenied",
    "ContextSourceError",
    "ContextSourceNotFound",
    "ContextStore",
    "ContextStoreError",
]
