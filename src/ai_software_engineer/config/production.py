"""Secret-free, operator-owned configuration for the production Team Host."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StringConstraints, model_validator

from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique

EnvVarName = Annotated[str, StringConstraints(pattern=r"^[A-Z_][A-Z0-9_]{0,127}$")]


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
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] = "medium"
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


class ProductionConfig(DomainModel):
    """Validated one-time Team Host configuration."""

    schema_version: Literal["v0.1"] = "v0.1"
    platform_root: NonEmptyStr
    database: ProductionDatabaseConfig = ProductionDatabaseConfig()
    model_routes: Annotated[tuple[ProviderRouteConfig, ...], Field(min_length=1, max_length=16)]
    codex_executable: NonEmptyStr = "codex"
    live_model_execution: StrictBool = False

    @model_validator(mode="after")
    def validate_production_contract(self) -> Self:
        root = Path(self.platform_root).expanduser()
        if not root.is_absolute() or any(ord(character) < 32 for character in self.platform_root):
            raise ValueError("platform_root must be an absolute safe path")
        ensure_unique(
            ((route.provider, route.model) for route in self.model_routes),
            "production provider/model routes",
        )
        if not any(route.enabled for route in self.model_routes):
            raise ValueError("at least one production model route must be enabled")
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
        configured = variables.get("ASE_CONFIG")
        path = (
            Path(configured).expanduser()
            if configured
            else Path.home() / ".config" / "ai-software-engineer" / "config.json"
        )
        return cls.from_file(path)

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
