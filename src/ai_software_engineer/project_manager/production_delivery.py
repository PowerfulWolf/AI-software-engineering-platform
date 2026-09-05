"""Production delivery adapters bound to dispatch-owned role worktrees."""

from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Protocol

from ai_software_engineer.agents import (
    AgentAdapter,
    AgentRequest,
    AgentResult,
    CodexCliAgentAdapter,
    ContextPromptBuilder,
    FallbackAgentAdapter,
    FileModelRouteAttemptStore,
    ProviderAgentRoute,
    ResponsesAgentAdapter,
    StoredContextResolver,
)
from ai_software_engineer.config import (
    ModelProviderKind,
    ProductionConfig,
    ProductionConfigError,
    ProviderRouteConfig,
)
from ai_software_engineer.domain import AgentDefinition, AgentRole
from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.orchestration import ExecutionPlanAgentAdapter
from ai_software_engineer.project_manager.dispatch import DispatchCommitRecord
from ai_software_engineer.role_workspace import (
    DispatchRoleWorktreeCoordinator,
    RoleWorktreeBinding,
    RoleWorktreeSession,
    VerificationWorktreeBindings,
)


class DeliveryRouteAdapterFactory(Protocol):
    """Testable construction seam for one provider bound to one role worktree."""

    def create(
        self,
        *,
        route: ProviderRouteConfig,
        definition: AgentDefinition,
        binding: RoleWorktreeBinding,
        context_resolver: StoredContextResolver,
        config: ProductionConfig,
        environment: Mapping[str, str],
    ) -> AgentAdapter: ...


class ConfiguredDeliveryRouteAdapterFactory:
    """Build real Codex CLI or Responses adapters from secret-free route metadata."""

    def create(
        self,
        *,
        route: ProviderRouteConfig,
        definition: AgentDefinition,
        binding: RoleWorktreeBinding,
        context_resolver: StoredContextResolver,
        config: ProductionConfig,
        environment: Mapping[str, str],
    ) -> AgentAdapter:
        prompt_builder = ContextPromptBuilder(context_resolver)
        if route.kind is ModelProviderKind.CODEX_CLI:
            return CodexCliAgentAdapter(
                workspace_root=binding.worktree.path,
                model=route.model,
                agent_id=definition.id,
                agent_version=definition.version,
                prompt_builder=prompt_builder,
                executable=config.codex_executable,
                reasoning_effort=route.reasoning_effort,
                environment=environment,
            )
        assert route.api_key_env is not None and route.endpoint is not None
        api_key = environment.get(route.api_key_env)
        if not api_key:
            raise ProductionConfigError(
                "enabled Responses route is missing API key environment variable: "
                f"{route.api_key_env}"
            )
        return ResponsesAgentAdapter(
            workspace_root=binding.worktree.path,
            endpoint=route.endpoint,
            api_key=api_key,
            model=route.model,
            agent=definition,
            prompt_builder=prompt_builder,
        )


class DispatchDeliveryAgentAdapter:
    """Open the exact dispatch worktree immediately before each serial role run.

    The adapter deliberately keeps workforce identity and provider identity separate:
    dispatch selects the organization member and primary model, while the bounded fallback
    adapter may temporarily use another configured provider without changing the Agent.
    """

    def __init__(
        self,
        *,
        dispatch: DispatchCommitRecord,
        definitions: Mapping[AgentRole, AgentDefinition],
        plan_adapter: ExecutionPlanAgentAdapter,
        config: ProductionConfig,
        project_root: str | Path,
        project_workspace_root: str | Path,
        context_resolver: StoredContextResolver,
        environment: Mapping[str, str] | None = None,
        route_adapters: DeliveryRouteAdapterFactory | None = None,
    ) -> None:
        self._dispatch = dispatch
        self._definitions = dict(definitions)
        self._plan_adapter = plan_adapter
        self._config = config
        self._project_root = Path(project_root).resolve()
        self._project_workspace_root = Path(project_workspace_root).resolve()
        self._environment = dict(environment if environment is not None else os.environ)
        worktree_root = (
            Path(config.platform_root).expanduser().resolve()
            / "worktrees"
            / str(dispatch.project_id)
        )
        self._coordinator = DispatchRoleWorktreeCoordinator(
            RoleWorktreeSession(
                GitWorktreeManager(self._project_root, worktree_root),
                environment=self._environment,
            )
        )
        self._context_resolver = context_resolver
        self._route_adapters = route_adapters or ConfiguredDeliveryRouteAdapterFactory()
        self._coder: RoleWorktreeBinding | None = None
        self._verifiers: VerificationWorktreeBindings | None = None
        self._adapters: dict[AgentRole, AgentAdapter] = {}

    def run(self, request: AgentRequest) -> AgentResult:
        if request.role is AgentRole.ORCHESTRATOR:
            return self._plan_adapter.run(request)
        binding = self._binding(request)
        adapter = self._adapters.get(request.role)
        if adapter is None:
            adapter = self._route_adapter(request.role, binding)
            self._adapters[request.role] = adapter
        return adapter.run(request)

    def close_clean_worktrees(self) -> None:
        """Remove only clean worktrees; dirty failure evidence stays on disk."""
        bindings: list[RoleWorktreeBinding] = []
        if self._coder is not None:
            bindings.append(self._coder)
        if self._verifiers is not None:
            bindings.extend((self._verifiers.qa, self._verifiers.reviewer))
        for binding in reversed(bindings):
            with suppress(Exception):
                self._coordinator.close(binding)

    def _binding(self, request: AgentRequest) -> RoleWorktreeBinding:
        if request.role is AgentRole.CODER:
            if self._coder is None:
                self._coder = self._coordinator.open_coder(
                    self._dispatch,
                    self._definitions,
                    recover=self._worktree_exists(AgentRole.CODER),
                )
            return self._coder
        if request.role not in {AgentRole.QA, AgentRole.REVIEWER}:
            raise ProductionConfigError(f"unsupported delivery role: {request.role.value}")
        if self._verifiers is None:
            self._verifiers = self._coordinator.open_verifiers(
                self._dispatch,
                request.source_revision,
                self._definitions,
                recover=self._worktree_exists(AgentRole.QA),
            )
        return self._verifiers.qa if request.role is AgentRole.QA else self._verifiers.reviewer

    def _route_adapter(
        self,
        role: AgentRole,
        binding: RoleWorktreeBinding,
    ) -> AgentAdapter:
        definition = self._definitions[role]
        configured = self._ordered_routes(definition)
        routes: list[ProviderAgentRoute] = []
        for route in configured:
            adapter = self._route_adapters.create(
                route=route,
                definition=definition,
                binding=binding,
                context_resolver=self._context_resolver,
                config=self._config,
                environment=self._environment,
            )
            routes.append(
                ProviderAgentRoute(
                    provider=route.provider,
                    model=route.model,
                    adapter=adapter,
                )
            )
        return FallbackAgentAdapter(
            tuple(routes),
            attempt_store=FileModelRouteAttemptStore(
                self._project_workspace_root / "runs" / "model-routes"
            ),
        )

    def _ordered_routes(
        self,
        definition: AgentDefinition,
    ) -> tuple[ProviderRouteConfig, ...]:
        routes = self._config.enabled_routes()
        primary = tuple(
            route
            for route in routes
            if route.provider == definition.provider and route.model == definition.model
        )
        if len(primary) != 1:
            raise ProductionConfigError(
                f"dispatch route is not enabled: {definition.provider}/{definition.model}"
            )
        selected = primary[0]
        return (selected, *(route for route in routes if route is not selected))

    def _worktree_exists(self, role: AgentRole) -> bool:
        root = (
            Path(self._config.platform_root).expanduser().resolve()
            / "worktrees"
            / str(self._dispatch.project_id)
            / self._dispatch.task_id
            / f"{role.value}-attempt-01"
        )
        return root.exists()


__all__ = [
    "ConfiguredDeliveryRouteAdapterFactory",
    "DeliveryRouteAdapterFactory",
    "DispatchDeliveryAgentAdapter",
]
