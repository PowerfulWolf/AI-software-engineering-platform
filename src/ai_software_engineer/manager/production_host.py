"""Application composition root for one long-lived AI Team."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.knowledge_selection import (
    effective_project_knowledge_paths,
    effective_team_knowledge_paths,
)
from ai_software_engineer.manager.delivery import (
    ProjectDeliveryCheckpointCatalog,
    ResumeProjectDelivery,
    UnifiedProjectEntryService,
)
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.production_backend import (
    ConfiguredStructuredClientFactory,
    ProductionProjectDeliveryBackend,
    StructuredClientFactory,
)
from ai_software_engineer.manager.production_delivery import (
    DeliveryRouteAdapterFactory,
)
from ai_software_engineer.manager.production_rules import (
    production_rules,
)
from ai_software_engineer.manager.team_roster import production_team_roster
from ai_software_engineer.multi_directory.models import JointDeliveryResult, JointStage
from ai_software_engineer.multi_directory.production import ProductionJointBackend
from ai_software_engineer.multi_directory.service import JointDeliveryService
from ai_software_engineer.product import HumanProductDecisionVerifier
from ai_software_engineer.project_workspace import ProjectWorkspace, ProjectWorkspaceRegistry
from ai_software_engineer.runtime_workspace import (
    FileTeamWorkforceStore,
    TeamWorkforceWorkspace,
)
from ai_software_engineer.scheduling import ModelRouter, PortfolioScheduler
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.team_workspace import TeamWorkspace
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


@dataclass(frozen=True, slots=True)
class _ProjectRuntime:
    project: ProjectWorkspace
    knowledge: tuple[ContextSource, ...]
    backend: ProductionProjectDeliveryBackend
    entry: UnifiedProjectEntryService
    requirements: JointDeliveryService


class TeamHost:
    """Own configuration, durable stores, and the Manager Agent skill facade."""

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
        self._team = TeamWorkspace.initialize(root, team_id=config.team_id, name=config.team_name)
        workforce_workspace = TeamWorkforceWorkspace.from_team(self._team)
        self._workforce_workspace = workforce_workspace
        workforce = FileTeamWorkforceStore(workforce_workspace)
        profiles, policy = production_team_roster(config)
        workforce.put_policy(policy, versioned=True)
        for profile in profiles:
            workforce.put_agent(profile)
        self._work_queue = MySqlPersistentWorkQueue(dsn)
        self._profiles = profiles
        self._model_policy = policy
        self._structured_clients = structured_clients
        self._delivery_route_adapters = delivery_route_adapters
        self._projects = self._team.project_registry()
        self._project_runtimes: dict[str, _ProjectRuntime] = {}
        if config.default_project_id is not None:
            assert config.default_project_name is not None
            self._projects.register(
                project_id=config.default_project_id,
                name=config.default_project_name,
            )

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> TeamHost:
        variables = environment if environment is not None else os.environ
        return cls(
            config=ProductionConfig.from_environment(variables),
            environment=variables,
        )

    def create_project(self, *, name: str, project_id: str | None = None) -> ProjectWorkspace:
        """Register one business Project; no Repository or Requirement is implied."""
        return (
            self._projects.create(name=name)
            if project_id is None
            else self._projects.register(project_id=project_id, name=name)
        )

    def projects(self) -> tuple[ProjectWorkspace, ...]:
        return self._projects.discover()

    def project_entry(self, project_id: str | None = None) -> UnifiedProjectEntryService:
        return self._runtime(self._resolve_project_id(project_id)).entry

    def requirement_entry(self, project_id: str | None = None) -> JointDeliveryService:
        return self._runtime(self._resolve_project_id(project_id)).requirements

    def recovery_entry(self, project_id: str | None = None) -> NativeRecoveryEntry:
        """Explicit human recovery; does not restart an old terminal delivery."""
        from ai_software_engineer.recovery.entry import NativeRecoveryEntry

        runtime = self._runtime(self._resolve_project_id(project_id))
        return NativeRecoveryEntry(self._config, self._environment, runtime.backend)

    def verification_entry(self, project_id: str | None = None) -> CandidateVerificationEntry:
        """Independent QA/Reviewer verification of a pinned candidate; never reruns Coder."""
        from ai_software_engineer.recovery.verification_entry import CandidateVerificationEntry

        runtime = self._runtime(self._resolve_project_id(project_id))
        return CandidateVerificationEntry(self._config, self._environment, runtime.backend)

    def resume_delivery(
        self, command: ResumeProjectDelivery, *, project_id: str | None = None
    ) -> DeliveryResumeResult | JointDeliveryResult:
        """Manager's single public continuation seam for native and joint work."""
        runtime = self._runtime(self._resolve_project_id(project_id, command.delivery_id))
        if str(command.delivery_id).startswith("delivery_multi_"):
            joint = runtime.requirements.status(command.delivery_id).checkpoint
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
                    child_result = self._resume_controller(runtime).resume(
                        command.model_copy(update={"delivery_id": child.checkpoint.delivery_id})
                    )
                    if child_result.checkpoint.stage is not DeliveryStage.DONE:
                        return child_result
            elif command.approved_plan_sha256 is not None:
                raise ValueError("joint delivery has no blocked child awaiting this approval")
            return runtime.requirements.resume(command)
        return self._resume_controller(runtime).resume(command)

    def _resume_controller(self, runtime: _ProjectRuntime) -> DeliveryResumeController:
        from ai_software_engineer.recovery.resume import DeliveryResumeController

        return DeliveryResumeController(
            config=self._config,
            environment=self._environment,
            backend=runtime.backend,
            entry=runtime.entry,
            recovery=self.recovery_entry(runtime.project.manifest.project_id),
            verification=self.verification_entry(runtime.project.manifest.project_id),
        )

    def _runtime(self, project_id: ProjectId | str) -> _ProjectRuntime:
        identity = str(project_id)
        project = self._projects.open(project_id)
        knowledge = self._knowledge_sources(project)
        cached = self._project_runtimes.get(identity)
        if cached is not None:
            cached.project.validate_current()
            if cached.knowledge == knowledge:
                return cached
        registry = project.repository_registry()
        rules = production_rules(self._team, knowledge)

        def validate_context() -> None:
            project.validate_current()
            current = self._knowledge_sources(project)
            if current != knowledge:
                raise ValueError(
                    "Team or Project knowledge changed; re-prepare and resolve context drift"
                )

        backend = ProductionProjectDeliveryBackend(
            config=self._config,
            environment=self._environment,
            organization=self._workforce_workspace,
            registry=registry,
            platform_rules=rules,
            structured_clients=self._structured_clients,
            delivery_route_adapters=self._delivery_route_adapters,
            preparation_guard=validate_context,
        )

        def derived_backend(
            clients: StructuredClientFactory,
            sources: tuple[ContextSource, ...],
            verifier: HumanProductDecisionVerifier,
        ) -> ProductionProjectDeliveryBackend:
            return ProductionProjectDeliveryBackend(
                config=self._config,
                environment=self._environment,
                organization=self._workforce_workspace,
                registry=registry,
                platform_rules=rules,
                structured_clients=clients,
                delivery_route_adapters=self._delivery_route_adapters,
                preparation_guard=validate_context,
                delivery_context_sources=sources,
                human_decision_verifier=verifier,
            )

        entry = UnifiedProjectEntryService(
            backend=backend,
            catalog=ProjectDeliveryCheckpointCatalog(registry.registry_root),
            delivery_namespace=project.manifest.project_id,
        )
        requirements = JointDeliveryService(
            team=self._team,
            project=project,
            backend=ProductionJointBackend(
                native=backend,
                factory=derived_backend,
                clients=self._structured_clients
                or ConfiguredStructuredClientFactory(self._config, self._environment),
                team=self._team,
                project=project,
                environment=self._environment,
            ),
        )
        runtime = _ProjectRuntime(project, knowledge, backend, entry, requirements)
        self._project_runtimes[identity] = runtime
        return runtime

    def _knowledge_sources(self, project: ProjectWorkspace) -> tuple[ContextSource, ...]:
        project_fallback = (
            self._config.project_knowledge_paths
            if self._config.default_project_id == project.manifest.project_id
            else ()
        )
        team_paths = effective_team_knowledge_paths(self._team, self._config.team_knowledge_paths)
        project_paths = effective_project_knowledge_paths(project, project_fallback)
        return (
            *self._team.knowledge_sources(team_paths),
            *project.knowledge_sources(project_paths),
        )

    def _resolve_project_id(
        self,
        project_id: str | None,
        delivery_id: str | None = None,
    ) -> ProjectId:
        if project_id is not None:
            return self._projects.open(project_id).manifest.project_id
        if self._config.default_project_id is not None:
            return self._config.default_project_id
        projects = self._projects.discover()
        if delivery_id is not None:
            matches: list[ProjectWorkspace] = []
            for project in projects:
                root = project.requirements_root / delivery_id
                if root.is_dir():
                    matches.append(project)
                    continue
                for repository in project.repository_registry().discover():
                    if (
                        repository.directory("state") / "project-deliveries" / delivery_id
                    ).is_dir():
                        matches.append(project)
                        break
            if len(matches) == 1:
                return matches[0].manifest.project_id
            if len(matches) > 1:
                raise ValueError("delivery identity is ambiguous across Projects")
        if len(projects) == 1:
            return projects[0].manifest.project_id
        raise ValueError("select a Project before creating or continuing a Requirement")

    @property
    def work_queue(self) -> MySqlPersistentWorkQueue:
        """Team Run queue; project sidecars never own this state."""
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
    def team_workspace(self) -> TeamWorkspace:
        """Selected Team workspace, including Team-owned knowledge and workforce facts."""
        return self._team

    @property
    def project_registry(self) -> ProjectWorkspaceRegistry:
        """Project catalog used by browser administration and read projections."""
        return self._projects


__all__ = ["TeamHost"]
