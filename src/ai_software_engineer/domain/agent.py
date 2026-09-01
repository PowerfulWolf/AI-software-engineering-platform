"""Resolved role execution and machine-enforced permission contracts."""

from typing import Annotated, Final, Self

from pydantic import Field, StrictBool, StrictInt, StringConstraints, model_validator

from ai_software_engineer.domain.enums import AgentRole, ArtifactKind, NetworkAccess
from ai_software_engineer.domain.model import DomainModel, JsonValue, NonEmptyStr, ensure_unique

AgentId = Annotated[str, StringConstraints(pattern=r"^agent_[a-z0-9][a-z0-9_-]{2,63}$")]
RetryLimit = Annotated[StrictInt, Field(ge=0, le=5)]
TimeoutSeconds = Annotated[StrictInt, Field(ge=1, le=3600)]
TokenBudget = Annotated[StrictInt, Field(ge=1)]

ROLE_OUTPUT: Final[dict[AgentRole, ArtifactKind]] = {
    AgentRole.ORCHESTRATOR: ArtifactKind.PLAN,
    AgentRole.CODER: ArtifactKind.IMPLEMENTATION_REPORT,
    AgentRole.QA: ArtifactKind.QA_REPORT,
    AgentRole.REVIEWER: ArtifactKind.REVIEW_REPORT,
}

ROLE_INPUTS: Final[dict[AgentRole, frozenset[ArtifactKind]]] = {
    AgentRole.ORCHESTRATOR: frozenset(ArtifactKind),
    AgentRole.CODER: frozenset(
        {ArtifactKind.PLAN, ArtifactKind.QA_REPORT, ArtifactKind.REVIEW_REPORT}
    ),
    AgentRole.QA: frozenset({ArtifactKind.PLAN, ArtifactKind.IMPLEMENTATION_REPORT}),
    AgentRole.REVIEWER: frozenset(
        {ArtifactKind.PLAN, ArtifactKind.IMPLEMENTATION_REPORT, ArtifactKind.QA_REPORT}
    ),
}


class AgentPermissions(DomainModel):
    """The executable path, command, network, and state capabilities of an Agent."""

    read_paths: tuple[NonEmptyStr, ...]
    write_paths: tuple[NonEmptyStr, ...]
    commands: tuple[NonEmptyStr, ...]
    network: NetworkAccess
    can_change_state: StrictBool = False
    can_merge: StrictBool = False

    @model_validator(mode="after")
    def validate_unique_entries(self) -> Self:
        ensure_unique(self.read_paths, "permissions.read_paths")
        ensure_unique(self.write_paths, "permissions.write_paths")
        ensure_unique(self.commands, "permissions.commands")
        return self


class AgentDefinition(DomainModel):
    """Resolved single-role run configuration; the organization identity is AgentProfile."""

    id: AgentId
    role: AgentRole
    version: NonEmptyStr
    model: NonEmptyStr
    provider: NonEmptyStr | None = None
    system_prompt_ref: NonEmptyStr | None = None
    permissions: AgentPermissions
    input_artifacts: tuple[ArtifactKind, ...]
    output_artifacts: tuple[ArtifactKind, ...]
    max_retries: RetryLimit
    timeout_seconds: TimeoutSeconds
    token_budget: TokenBudget | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_role_contract(self) -> Self:
        ensure_unique(self.input_artifacts, "input_artifacts")
        ensure_unique(self.output_artifacts, "output_artifacts")

        expected = ROLE_OUTPUT[self.role]
        if self.output_artifacts != (expected,):
            raise ValueError(f"{self.role} must output exactly {expected}")

        invalid_inputs = sorted(set(self.input_artifacts) - ROLE_INPUTS[self.role])
        if invalid_inputs:
            rendered = ", ".join(str(kind) for kind in invalid_inputs)
            raise ValueError(f"{self.role} cannot consume artifact kinds: {rendered}")

        if self.permissions.can_change_state and self.role is not AgentRole.ORCHESTRATOR:
            raise ValueError("only orchestrator may change Task state")
        if self.permissions.can_merge:
            raise ValueError("v0.1 Agent Definitions cannot merge")
        return self
