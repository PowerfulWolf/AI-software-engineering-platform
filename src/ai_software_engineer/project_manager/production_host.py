"""Application composition root for the long-lived organization team."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ai_software_engineer.company_workspace import CompanyWorkspace
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context import ContextSource
from ai_software_engineer.multi_directory.models import JointDeliveryResult, JointStage
from ai_software_engineer.multi_directory.production import ProductionJointBackend
from ai_software_engineer.multi_directory.service import JointDeliveryService
from ai_software_engineer.product import HumanProductDecisionVerifier
from ai_software_engineer.project_manager.delivery import (
    ProjectDeliveryCheckpointCatalog,
    ResumeProjectDelivery,
    UnifiedProjectEntryService,
)
from ai_software_engineer.project_manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.project_manager.organization_team import production_organization_team
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
from ai_software_engineer.runtime_workspace import (
    FileOrganizationWorkforceStore,
    OrganizationWorkspace,
)
from ai_software_engineer.scheduling import ModelRouter, PortfolioScheduler
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue import DispatcherLoop, MySqlPersistentWorkQueue
from ai_software_engineer.work_queue.dispatcher import OwnerTokenFactory, RunDemandBuilder
from ai_software_engineer.work_queue.models import LeaseWorkerId

if TYPE_CHECKING:
    from ai_software_engineer.recovery.entry import NativeRecoveryEntry
    from ai_software_engineer.recovery.resume import (
        DeliveryResumeController,
        DeliveryResumeResult,
    )
    from ai_software_engineer.recovery.verification_entry import CandidateVerificationEntry


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
        workforce = FileOrganizationWorkforceStore(organization)
        profiles, policy = production_organization_team(config)
        workforce.put_policy(policy, versioned=True)
        for profile in profiles:
            workforce.put_agent(profile)
        self._work_queue = MySqlPersistentWorkQueue(dsn)
        self._profiles = profiles
        self._model_policy = policy
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
        self._recovery_backend = backend

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

    def recovery_entry(self) -> NativeRecoveryEntry:
        """Explicit human recovery; does not restart an old terminal delivery."""
        from ai_software_engineer.recovery.entry import NativeRecoveryEntry

        return NativeRecoveryEntry(self._config, self._environment, self._recovery_backend)

    def verification_entry(self) -> CandidateVerificationEntry:
        """Independent QA/Reviewer verification of a pinned candidate; never reruns Coder."""
        from ai_software_engineer.recovery.verification_entry import CandidateVerificationEntry

        return CandidateVerificationEntry(
            self._config,
            self._environment,
            self._recovery_backend,
        )

    def resume_delivery(
        self, command: ResumeProjectDelivery
    ) -> DeliveryResumeResult | JointDeliveryResult:
        """Project Manager's single public continuation seam for native and joint work."""
        if str(command.delivery_id).startswith("delivery_multi_"):
            joint = self._requirements.status(command.delivery_id).checkpoint
            if joint.stage is JointStage.BLOCKED and joint.integration is None:
                for child in joint.children:
                    if child.checkpoint.stage not in {
                        DeliveryStage.BLOCKED,
                        DeliveryStage.FAILED,
                        DeliveryStage.DONE,
                    }:
                        continue
                    if child.checkpoint.stage is DeliveryStage.DONE:
                        continue
                    child_result = self._resume_controller().resume(
                        command.model_copy(update={"delivery_id": child.checkpoint.delivery_id})
                    )
                    if child_result.checkpoint.stage is not DeliveryStage.DONE:
                        return child_result
            elif command.approved_plan_sha256 is not None:
                raise ValueError("joint delivery has no blocked child awaiting this approval")
            return self._requirements.resume(command)
        return self._resume_controller().resume(command)

    def _resume_controller(self) -> DeliveryResumeController:
        from ai_software_engineer.recovery.resume import DeliveryResumeController

        return DeliveryResumeController(
            config=self._config,
            environment=self._environment,
            backend=self._recovery_backend,
            entry=self._entry,
            recovery=self.recovery_entry(),
            verification=self.verification_entry(),
        )

    @property
    def work_queue(self) -> MySqlPersistentWorkQueue:
        """Organization Run queue; project sidecars never own this state."""
        return self._work_queue

    def planner_dispatcher(
        self,
        *,
        demand_builder: RunDemandBuilder,
        worker_id: LeaseWorkerId | str,
        owner_token_factory: OwnerTokenFactory | None = None,
    ) -> DispatcherLoop:
        """Compose the deterministic execution side of Planner dispatch authority."""
        capacities = {
            (route.provider, route.model): 2_000_000 for route in self._model_policy.routes
        }
        return DispatcherLoop(
            queue=self._work_queue,
            scheduler=PortfolioScheduler(),
            model_router=ModelRouter(route_context_capacities=capacities),
            agents=self._profiles,
            policies=(self._model_policy,),
            demand_builder=demand_builder,
            worker_id=worker_id,
            owner_token_factory=owner_token_factory,
        )

    @property
    def company_workspace(self) -> CompanyWorkspace:
        """Selected company only; organization Agent ownership stays outside this workspace."""
        return self._company


__all__ = ["OrganizationTeamHost"]
