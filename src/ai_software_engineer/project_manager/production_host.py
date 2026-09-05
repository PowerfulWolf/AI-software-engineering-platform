"""Application composition root for the long-lived organization team."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.project_manager.delivery import (
    ProjectDeliveryCheckpointCatalog,
    UnifiedProjectEntryService,
)
from ai_software_engineer.project_manager.production_backend import (
    ProductionProjectDeliveryBackend,
    StructuredClientFactory,
)
from ai_software_engineer.project_manager.production_delivery import (
    DeliveryRouteAdapterFactory,
)
from ai_software_engineer.project_workspace import ProjectWorkspaceRegistry
from ai_software_engineer.runtime_workspace import OrganizationWorkspace
from ai_software_engineer.spec_compiler import SpecRule, SpecRuleLayer
from ai_software_engineer.store import MySqlTaskRepository


class OrganizationTeamHost:
    """Own configuration, durable stores, and the Project Manager Agent skill facade."""

    def __init__(
        self,
        *,
        config: ProductionConfig,
        environment: Mapping[str, str],
        structured_clients: StructuredClientFactory | None = None,
        delivery_route_adapters: DeliveryRouteAdapterFactory | None = None,
    ) -> None:
        self._config = config
        self._environment = dict(environment)
        root = Path(config.platform_root).expanduser().resolve(strict=False)
        root.mkdir(parents=True, exist_ok=True)
        dsn = config.require_mysql_dsn(self._environment)
        # Validate connectivity and initialize the Task schema at the composition boundary.
        MySqlTaskRepository(dsn).close()
        organization = OrganizationWorkspace.initialize(
            root / "organization",
            organization_id="organization_ai_software_engineer",
            created_at=datetime.now(UTC),
        )
        registry = ProjectWorkspaceRegistry(root / "projects")
        backend = ProductionProjectDeliveryBackend(
            config=config,
            environment=self._environment,
            organization=organization,
            registry=registry,
            platform_rules=(_no_self_approval_rule(),),
            structured_clients=structured_clients,
            delivery_route_adapters=delivery_route_adapters,
        )
        self._entry = UnifiedProjectEntryService(
            backend=backend,
            catalog=ProjectDeliveryCheckpointCatalog(registry.registry_root),
        )

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> OrganizationTeamHost:
        variables = environment if environment is not None else os.environ
        return cls(
            config=ProductionConfig.from_environment(variables),
            environment=variables,
        )

    def project_entry(self) -> UnifiedProjectEntryService:
        return self._entry


def _no_self_approval_rule() -> SpecRule:
    return SpecRule(
        id="rule_platform_no_self_approval",
        field="safety.self_approval",
        value=False,
        layer=SpecRuleLayer.PLATFORM_HARD,
        priority=1_000,
        source_uri="platform://organization/safety/v0.1",
        source_sha256="0" * 64,
        rationale="No Agent may be the sole judge of its own work.",
    )


__all__ = ["OrganizationTeamHost"]
