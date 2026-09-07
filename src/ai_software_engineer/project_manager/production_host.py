"""Application composition root for the long-lived organization team."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from ai_software_engineer.company_workspace import CompanyWorkspace
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context import ContextSource
from ai_software_engineer.multi_directory.production import ProductionJointBackend
from ai_software_engineer.multi_directory.service import JointDeliveryService
from ai_software_engineer.product import HumanProductDecisionVerifier
from ai_software_engineer.project_manager.delivery import (
    ProjectDeliveryCheckpointCatalog,
    UnifiedProjectEntryService,
)
from ai_software_engineer.project_manager.production_backend import (
    ConfiguredStructuredClientFactory,
    ProductionProjectDeliveryBackend,
    StructuredClientFactory,
)
from ai_software_engineer.project_manager.production_delivery import (
    DeliveryRouteAdapterFactory,
)
from ai_software_engineer.project_manager.production_rules import (
    production_rules,
)
from ai_software_engineer.runtime_workspace import OrganizationWorkspace
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
        self._company = CompanyWorkspace.initialize(
            root, company_id=config.company_id, name=config.company_name
        )
        registry = self._company.project_registry()
        knowledge = self._company.knowledge_sources(config.company_knowledge_paths)
        rules = production_rules(self._company, knowledge)

        def validate_company_context() -> None:
            if self._company.knowledge_sources(config.company_knowledge_paths) != knowledge:
                raise ValueError("company knowledge changed; re-prepare and resolve context drift")

        backend = ProductionProjectDeliveryBackend(
            config=config,
            environment=self._environment,
            organization=organization,
            registry=registry,
            platform_rules=rules,
            structured_clients=structured_clients,
            delivery_route_adapters=delivery_route_adapters,
            preparation_guard=validate_company_context,
        )
        self._entry = UnifiedProjectEntryService(
            backend=backend,
            catalog=ProjectDeliveryCheckpointCatalog(registry.registry_root),
            delivery_namespace=config.company_id,
        )

        def derived_backend(
            clients: StructuredClientFactory,
            sources: tuple[ContextSource, ...],
            verifier: HumanProductDecisionVerifier,
        ) -> ProductionProjectDeliveryBackend:
            return ProductionProjectDeliveryBackend(
                config=config,
                environment=self._environment,
                organization=organization,
                registry=registry,
                platform_rules=rules,
                structured_clients=clients,
                delivery_route_adapters=delivery_route_adapters,
                preparation_guard=validate_company_context,
                delivery_context_sources=sources,
                human_decision_verifier=verifier,
            )

        self._requirements = JointDeliveryService(
            company=self._company,
            backend=ProductionJointBackend(
                native=backend,
                factory=derived_backend,
                clients=structured_clients
                or ConfiguredStructuredClientFactory(config, self._environment),
                company=self._company,
                environment=self._environment,
            ),
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

    def requirement_entry(self) -> JointDeliveryService:
        return self._requirements

    @property
    def company_workspace(self) -> CompanyWorkspace:
        """Selected company only; organization Agent ownership stays outside this workspace."""
        return self._company


__all__ = ["OrganizationTeamHost"]
