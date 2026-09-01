"""Typed context manifest values shared by the Builder and Agent adapters."""

from typing import Annotated, Self

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, StringConstraints, model_validator

from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.identity import ContextId as ContextId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import TaskId

ContextSourceId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.:-]{0,127}$")]
ContextSectionName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.:/-]{0,127}$")]
TokenCount = Annotated[StrictInt, Field(ge=0)]
BudgetTokens = Annotated[StrictInt, Field(ge=1)]
ReservedTokens = Annotated[StrictInt, Field(ge=0)]
Priority = Annotated[StrictInt, Field(ge=0, le=10_000)]


class ContextSource(DomainModel):
    """A declared inline or root-relative source eligible for role routing."""

    source_id: ContextSourceId
    uri: NonEmptyStr
    content: str | None = None
    relative_path: NonEmptyStr | None = None
    roles: tuple[AgentRole, ...] = ()
    priority: Priority = 100
    required: StrictBool = False

    @model_validator(mode="after")
    def validate_source_shape(self) -> Self:
        if any(ord(character) < 32 for character in self.uri):
            raise ValueError("ContextSource uri cannot contain control characters")
        if self.relative_path is not None and any(
            ord(character) < 32 for character in self.relative_path
        ):
            raise ValueError("ContextSource relative_path cannot contain control characters")
        if (self.content is None) == (self.relative_path is None):
            raise ValueError("ContextSource must define exactly one of content or relative_path")
        ensure_unique(self.roles, "ContextSource roles")
        return self


class ContextSection(DomainModel):
    """One redacted, delivered context section and its integrity metadata."""

    name: ContextSectionName
    uri: NonEmptyStr
    sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    tokens: TokenCount
    content: str
    priority: Priority
    truncated: StrictBool = False


class ContextRedaction(DomainModel):
    """Safe audit metadata for one or more replacements in a source."""

    uri: NonEmptyStr
    kind: NonEmptyStr
    count: Annotated[StrictInt, Field(gt=0)]


class ContextBudget(DomainModel):
    """Input/output budget and actual input usage for one context bundle."""

    max_input_tokens: BudgetTokens
    reserved_output_tokens: ReservedTokens
    used_input_tokens: TokenCount = 0

    @model_validator(mode="after")
    def validate_usage(self) -> Self:
        if self.used_input_tokens > self.max_input_tokens:
            raise ValueError("used_input_tokens cannot exceed max_input_tokens")
        return self


class ContextBundle(DomainModel):
    """Immutable, redacted, role-scoped context manifest delivered to an Agent Run."""

    context_id: ContextId
    task_id: TaskId
    role: AgentRole
    attempt: Annotated[StrictInt, Field(ge=1, le=10)]
    source_revision: NonEmptyStr
    sections: Annotated[tuple[ContextSection, ...], Field(min_length=1)]
    redactions: tuple[ContextRedaction, ...] = ()
    budget: ContextBudget
    built_at: AwareDatetime

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        ensure_unique((section.name for section in self.sections), "Context section names")
        ensure_unique((section.uri for section in self.sections), "Context section URIs")
        if sum(section.tokens for section in self.sections) != self.budget.used_input_tokens:
            raise ValueError("budget.used_input_tokens must equal section token total")
        return self
