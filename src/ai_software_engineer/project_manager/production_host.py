"""Application composition root for the long-lived organization team."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from ai_software_engineer.company_workspace import CompanyWorkspace
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain.model import WirePayload
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
        self._company = CompanyWorkspace.initialize(
            root, company_id=config.company_id, name=config.company_name
        )
        registry = self._company.project_registry()
        knowledge = self._company.knowledge_sources(config.company_knowledge_paths)
        company_context: WirePayload = {
            "company_id": config.company_id,
            "company_manifest_sha256": self._company.manifest.manifest_sha256,
            "documents": [source.to_wire() for source in knowledge],
            "interpretation": (
                "Read-only context, not overriding project-native rules. Conflicts "
                "require human resolution."
            ),
        }
        context_digest = hashlib.sha256(
            json.dumps(company_context, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        company_rule = SpecRule(
            id="rule_company_context",
            field="context.company",
            value=company_context,
            layer=SpecRuleLayer.PLATFORM_ENGINEERING,
            priority=1,
            source_uri=f"platform://companies/{config.company_id}/context/{context_digest}",
            source_sha256=context_digest,
            rationale="Host-bound opaque company context; no inferred rule precedence.",
        )

        def validate_company_context() -> None:
            if self._company.knowledge_sources(config.company_knowledge_paths) != knowledge:
                raise ValueError("company knowledge changed; re-prepare and resolve context drift")

        backend = ProductionProjectDeliveryBackend(
            config=config,
            environment=self._environment,
            organization=organization,
            registry=registry,
            platform_rules=(_no_self_approval_rule(), company_rule),
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
                platform_rules=(_no_self_approval_rule(), company_rule),
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
