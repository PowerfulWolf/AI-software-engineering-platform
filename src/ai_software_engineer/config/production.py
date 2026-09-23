"""Secret-free, operator-owned configuration for the production Team Host."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from ai_software_engineer.config.codex_proxy import (
    CODEX_PROXY_API_KEY_ENV,
    normalize_local_codex_proxy_base_url,
)
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.domain.identity import ProjectId, TeamId
from ai_software_engineer.domain.model import (
    DomainModel,
    NonEmptyStr,
    ReasoningEffort,
    ensure_unique,
)
from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy, StageRetryPolicy
from ai_software_engineer.multi_directory.budget import DesignRetryPolicy
from ai_software_engineer.project_workspace import ProjectName
from ai_software_engineer.team_workspace import TeamName, validate_knowledge_path

EnvVarName = Annotated[str, StringConstraints(pattern=r"^[A-Z_][A-Z0-9_]{0,127}$")]


def _default_platform_root() -> str:
    """Return the supported platform default without creating it."""
    if sys.platform not in {"darwin", "linux"}:
        raise ValueError("platform_root must be explicitly configured on this platform")
    return str(Path.home() / ".ase")


def _normalize_platform_root(value: str) -> str:
    """Reject lexical traversal and expand the supported home-relative form."""
    suffix = value[2:] if value.startswith("~/") else value
    if any(part == ".." for part in Path(suffix).parts):
        raise ValueError("platform_root must be an absolute safe path")
    if not value.startswith("~/"):
        return value
    if suffix.startswith("/"):
        raise ValueError("platform_root must be an absolute safe path")
    return str(Path.home() / suffix)


class ProductionConfigError(RuntimeError):
    """Raised when production configuration is missing or cannot be decoded safely."""


class ModelProviderKind(StrEnum):
    CODEX_CLI = "codex_cli"
    RESPONSES = "responses"


class ProductionDatabaseConfig(DomainModel):
    """MySQL connection indirection; the DSN itself remains in the environment."""

    backend: Literal["mysql"] = "mysql"
    dsn_env: EnvVarName = "ASE_MYSQL_DSN"


class ProviderRouteConfig(DomainModel):
    """One ordered model route without credentials."""

    provider: NonEmptyStr
    model: NonEmptyStr
    kind: ModelProviderKind
    endpoint: NonEmptyStr | None = None
    api_key_env: EnvVarName | None = None
    reasoning_effort: ReasoningEffort = "medium"
    image_input: StrictBool | None = None
    enabled: StrictBool = True

    @model_validator(mode="after")
    def validate_provider_contract(self) -> Self:
        if self.kind is ModelProviderKind.CODEX_CLI:
            if self.endpoint is not None or self.api_key_env is not None:
                raise ValueError("Codex CLI route cannot embed endpoint or API key settings")
        elif self.endpoint is None or self.api_key_env is None:
            raise ValueError("Responses route requires endpoint and api_key_env")
        if self.endpoint is not None and any(ord(character) < 32 for character in self.endpoint):
            raise ValueError("provider endpoint cannot contain control characters")
        return self

    def accepts_image_input(self) -> bool:
        if self.image_input is not None:
            return self.image_input
        return self.kind is ModelProviderKind.CODEX_CLI


class ProviderRouteReference(DomainModel):
    provider: NonEmptyStr
    model: NonEmptyStr
    reasoning_effort: ReasoningEffort | None = None


class AgentModelRoutePolicy(DomainModel):
    role: TeamRole
    routes: Annotated[tuple[ProviderRouteReference, ...], Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def validate_routes(self) -> Self:
        ensure_unique(
            ((route.provider, route.model, route.reasoning_effort) for route in self.routes),
            f"{self.role.value} Agent model routes",
        )
        return self


class ProductionConfig(DomainModel):
    """Validated one-time Team Host configuration."""

    schema_version: Literal["v0.2"] = "v0.2"
    platform_root: NonEmptyStr = Field(default_factory=_default_platform_root)
    team_id: TeamId = "team_ai"
    team_name: TeamName = "AI Team"
    team_knowledge_paths: tuple[NonEmptyStr, ...] = ()
    default_project_id: ProjectId | None = None
    default_project_name: ProjectName | None = None
    project_knowledge_paths: tuple[NonEmptyStr, ...] = ()
    database: ProductionDatabaseConfig = ProductionDatabaseConfig()
    model_routes: Annotated[tuple[ProviderRouteConfig, ...], Field(min_length=1, max_length=16)]
    agent_model_routes: Annotated[tuple[AgentModelRoutePolicy, ...], Field(max_length=7)] = ()
    codex_executable: NonEmptyStr = "codex"
    codex_cli_proxy_base_url: str | None = None
    codex_cli_proxy_api_key_env: EnvVarName | None = None
    live_model_execution: StrictBool = False
    console_port: Annotated[StrictInt, Field(ge=1, le=65535)] = 8765
    execution_retry_policy: ExecutionRetryPolicy = ExecutionRetryPolicy()

    @field_validator("codex_cli_proxy_base_url")
    @classmethod
    def validate_codex_cli_proxy_base_url(cls, value: str | None) -> str | None:
        return None if value is None else normalize_local_codex_proxy_base_url(value)

    @field_validator("codex_cli_proxy_api_key_env")
    @classmethod
    def validate_codex_cli_proxy_api_key_env(cls, value: str | None) -> str | None:
        if value is not None and value != CODEX_PROXY_API_KEY_ENV:
            raise ValueError("Codex CLI proxy API key environment name is invalid")
        return value

    @model_validator(mode="before")
    @classmethod
    def migrate_design_policy(cls, value: object) -> object:
        if not isinstance(value, dict) or "design_retry_policy" not in value:
            return value
        payload = dict(value)
        legacy = DesignRetryPolicy.model_validate(payload.pop("design_retry_policy"))
        designer = StageRetryPolicy(
            max_attempts=legacy.max_design_attempts,
            max_transient_failures=legacy.max_transient_failures,
        )
        if "execution_retry_policy" in payload:
            current = ExecutionRetryPolicy.model_validate(payload["execution_retry_policy"])
            if current.designer != designer:
                raise ValueError("conflicting Design and execution retry policies")
        else:
            payload["execution_retry_policy"] = ExecutionRetryPolicy(designer=designer)
        return payload

    @property
    def design_retry_policy(self) -> DesignRetryPolicy:
        """Read compatibility for the existing Design projection and recovery contract."""
        return DesignRetryPolicy(
            max_design_attempts=self.execution_retry_policy.designer.max_attempts,
            max_transient_failures=self.execution_retry_policy.designer.max_transient_failures,
        )

    @classmethod
    def default(cls) -> Self:
        """Build the visible first-run defaults without writing operator state."""
        return cls(
            model_routes=(
                ProviderRouteConfig(
                    provider="codex",
                    model="gpt-5.6-terra",
                    kind=ModelProviderKind.CODEX_CLI,
                    reasoning_effort="high",
                ),
                ProviderRouteConfig(
                    provider="deepseek",
                    model="YOUR_DEEPSEEK_MODEL",
                    kind=ModelProviderKind.RESPONSES,
                    endpoint="https://api.deepseek.com/v1/responses",
                    api_key_env="DEEPSEEK_API_KEY",
                    enabled=False,
                ),
                ProviderRouteConfig(
                    provider="qwen",
                    model="YOUR_QWEN_MODEL",
                    kind=ModelProviderKind.RESPONSES,
                    endpoint=(
                        "https://YOUR_WORKSPACE_ID.cn-beijing.maas.aliyuncs.com/"
                        "compatible-mode/v1/responses"
                    ),
                    api_key_env="DASHSCOPE_API_KEY",
                    enabled=False,
                ),
            )
        )

    @field_validator("platform_root", mode="before")
    @classmethod
    def expand_home_relative_platform_root(cls, value: object) -> object:
        """Normalize explicit ``~/`` input before the shared safety guard runs."""
        return _normalize_platform_root(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_production_contract(self) -> Self:
        root = Path(self.platform_root)
        if not root.is_absolute() or any(ord(character) < 32 for character in self.platform_root):
            raise ValueError("platform_root must be an absolute safe path")
        if self.codex_cli_proxy_api_key_env is not None:
            if self.codex_cli_proxy_base_url is None:
                raise ValueError("Codex CLI proxy API key requires a proxy URL")
            if self.codex_cli_proxy_api_key_env in {
                self.database.dsn_env,
                *(route.api_key_env for route in self.model_routes),
            }:
                raise ValueError("Codex CLI proxy API key must have a dedicated environment name")
        ensure_unique(
            ((route.provider, route.model, route.reasoning_effort) for route in self.model_routes),
            "production provider/model/reasoning routes",
        )
        if not any(route.enabled for route in self.model_routes):
            raise ValueError("at least one production model route must be enabled")
        ensure_unique(
            (policy.role for policy in self.agent_model_routes),
            "Agent model route roles",
        )
        if self.agent_model_routes and {policy.role for policy in self.agent_model_routes} != set(
            TeamRole
        ):
            raise ValueError("Agent model routes must cover every Team role")
        for policy in self.agent_model_routes:
            resolved = tuple(
                self._resolve_route_reference(reference) for reference in policy.routes
            )
            ensure_unique(
                ((route.provider, route.model, route.reasoning_effort) for route in resolved),
                f"{policy.role.value} resolved Agent model routes",
            )
        ensure_unique(self.team_knowledge_paths, "team knowledge selection")
        if len(self.team_knowledge_paths) > 64:
            raise ValueError("team knowledge selection exceeds document budget")
        for path in self.team_knowledge_paths:
            validate_knowledge_path(path)
        if (self.default_project_id is None) != (self.default_project_name is None):
            raise ValueError(
                "default_project_id and default_project_name must be configured together"
            )
        ensure_unique(self.project_knowledge_paths, "Project knowledge selection")
        if len(self.project_knowledge_paths) > 64:
            raise ValueError("Project knowledge selection exceeds document budget")
        for path in self.project_knowledge_paths:
            validate_knowledge_path(path)
        return self

    @classmethod
    def from_file(cls, path: str | Path) -> ProductionConfig:
        """Read one config document without interpolating or accepting secrets."""
        source = Path(path).expanduser()
        try:
            payload: object = json.loads(source.read_text(encoding="utf-8"))
            return cls.model_validate(payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise ProductionConfigError(
                f"cannot load production configuration: {source}"
            ) from error

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> ProductionConfig:
        variables = environment if environment is not None else os.environ
        return cls.from_file(cls.path_from_environment(variables))

    @staticmethod
    def path_from_environment(environment: Mapping[str, str] | None = None) -> Path:
        """Resolve the operator-owned config path without reading or creating it."""
        variables = environment if environment is not None else os.environ
        configured = variables.get("ASE_CONFIG")
        return (
            Path(configured).expanduser()
            if configured
            else Path.home() / ".config" / "ai-software-engineer" / "config.json"
        )

    def require_mysql_dsn(self, environment: Mapping[str, str]) -> str:
        """Resolve only the configured env name and never echo its value."""
        value = environment.get(self.database.dsn_env)
        if not value:
            raise ProductionConfigError(
                f"required MySQL DSN environment variable is missing: {self.database.dsn_env}"
            )
        return value

    def enabled_routes(self) -> tuple[ProviderRouteConfig, ...]:
        return tuple(route for route in self.model_routes if route.enabled)

    def routes_for(self, role: TeamRole) -> tuple[ProviderRouteConfig, ...]:
        """Return the role's frozen primary/fallback order, or the legacy global order."""
        policy = next((item for item in self.agent_model_routes if item.role == role), None)
        if policy is None:
            return self.enabled_routes()
        return tuple(self._resolve_route_reference(reference) for reference in policy.routes)

    def _resolve_route_reference(
        self,
        reference: ProviderRouteReference,
    ) -> ProviderRouteConfig:
        candidates = tuple(
            route
            for route in self.enabled_routes()
            if route.provider == reference.provider
            and route.model == reference.model
            and (
                reference.reasoning_effort is None
                or route.reasoning_effort == reference.reasoning_effort
            )
        )
        if not candidates:
            raise ValueError(
                "Agent routes must reference enabled model routes: "
                f"{reference.provider}/{reference.model}"
            )
        if len(candidates) > 1:
            raise ValueError(
                f"Agent route {reference.provider}/{reference.model} is ambiguous without "
                "reasoning_effort"
            )
        return candidates[0]
