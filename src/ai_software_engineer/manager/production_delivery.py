"""Production delivery adapters bound to dispatch-owned role worktrees."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

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
from ai_software_engineer.agents.candidate_binding import BoundCandidateSource
from ai_software_engineer.agents.codex_cli import InitialWorkspaceAdmission
from ai_software_engineer.agents.continuation import CoderInterruptionControl
from ai_software_engineer.agents.execution import ExecutionGuard
from ai_software_engineer.agents.fallback import model_route_root
from ai_software_engineer.config import (
    ModelProviderKind,
    ProductionConfig,
    ProductionConfigError,
    ProviderRouteConfig,
)
from ai_software_engineer.config.codex_proxy import codex_cli_proxy_key_environment
from ai_software_engineer.domain import AgentDefinition, AgentRole, TeamRole
from ai_software_engineer.git import DirtyWorktree, GitWorktreeManager
from ai_software_engineer.manager.dispatch import (
    DeliveryAllocation,
    VerificationReservation,
)
from ai_software_engineer.orchestration import ExecutionPlanAgentAdapter
from ai_software_engineer.role_workspace import (
    DispatchRoleWorktreeCoordinator,
    RoleWorktreeBinding,
    RoleWorktreeSession,
)

if TYPE_CHECKING:
    from ai_software_engineer.recovery.verification_execution import VerificationEvidenceProvider


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

    def __init__(
        self,
        *,
        initial_workspace_admission: InitialWorkspaceAdmission | None = None,
        execution_guard: ExecutionGuard | None = None,
        verification_evidence: VerificationEvidenceProvider | None = None,
        interruption_control: CoderInterruptionControl | None = None,
    ) -> None:
        self._initial_admission = initial_workspace_admission
        self._execution_guard = execution_guard
        self._verification_evidence = verification_evidence
        self._interruption_control = interruption_control

    def with_execution_guard(self, guard: ExecutionGuard) -> ConfiguredDeliveryRouteAdapterFactory:
        """Bind Worker ownership while preserving explicitly approved recovery admission."""
        return ConfiguredDeliveryRouteAdapterFactory(
            initial_workspace_admission=self._initial_admission,
            execution_guard=guard,
            verification_evidence=self._verification_evidence,
            interruption_control=self._interruption_control,
        )

    def with_verification_evidence(
        self, provider: VerificationEvidenceProvider
    ) -> ConfiguredDeliveryRouteAdapterFactory:
        return ConfiguredDeliveryRouteAdapterFactory(
            initial_workspace_admission=self._initial_admission,
            execution_guard=self._execution_guard,
            verification_evidence=provider,
            interruption_control=self._interruption_control,
        )

    def with_interruption_control(
        self, control: CoderInterruptionControl
    ) -> ConfiguredDeliveryRouteAdapterFactory:
        return ConfiguredDeliveryRouteAdapterFactory(
            initial_workspace_admission=self._initial_admission,
            execution_guard=self._execution_guard,
            verification_evidence=self._verification_evidence,
            interruption_control=control,
        )

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
        from ai_software_engineer.agents.openai_compatible import PromptBuilder

        prompt_builder: PromptBuilder = ContextPromptBuilder(context_resolver)
        if self._verification_evidence is not None:
            from ai_software_engineer.recovery.verification_execution import (
                VerificationEvidencePromptBuilder,
            )

            if definition.role not in (AgentRole.QA, AgentRole.REVIEWER):
                raise ProductionConfigError("controlled verification evidence is verifier-only")
            prompt_builder = VerificationEvidencePromptBuilder(
                prompt_builder,
                self._verification_evidence,
                Path(binding.worktree.path),
                self._execution_guard,
            )
        if route.kind is ModelProviderKind.CODEX_CLI:
            proxy = config.effective_connection_mode(route) == "proxy"
            if proxy:
                try:
                    codex_cli_proxy_key_environment(environment, config.codex_cli_proxy_api_key_env)
                except ValueError as error:
                    raise ProductionConfigError(
                        "Codex CLI proxy API key environment variable is missing: "
                        f"{config.codex_cli_proxy_api_key_env}"
                    ) from error
            return CodexCliAgentAdapter(
                workspace_root=binding.worktree.path,
                execution_guard=self._execution_guard,
                model=route.model,
                agent_id=definition.id,
                agent_version=definition.version,
                prompt_builder=prompt_builder,
                candidate_source=BoundCandidateSource(context_resolver),
                executable=config.codex_executable,
                proxy_base_url=config.codex_cli_proxy_base_url if proxy else None,
                proxy_api_key_env=config.codex_cli_proxy_api_key_env if proxy else None,
                reasoning_effort=route.reasoning_effort,
                environment=environment,
                initial_workspace_admission=(
                    self._initial_admission if definition.role is AgentRole.CODER else None
                ),
                interruption_control=(
                    self._interruption_control if definition.role is AgentRole.CODER else None
                ),
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
            execution_guard=self._execution_guard,
            endpoint=route.endpoint,
            api_key=api_key,
            model=route.model,
            reasoning_effort=route.reasoning_effort,
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
        dispatch: DeliveryAllocation | VerificationReservation,
        definitions: Mapping[AgentRole, AgentDefinition],
        plan_adapter: ExecutionPlanAgentAdapter | None,
        config: ProductionConfig,
        repository_root: str | Path,
        repository_workspace_root: str | Path,
        context_resolver: StoredContextResolver,
        environment: Mapping[str, str] | None = None,
        route_adapters: DeliveryRouteAdapterFactory | None = None,
        route_scope: tuple[ProviderRouteConfig, ...] | None = None,
        route_validator: Callable[[AgentRole, tuple[ProviderRouteConfig, ...]], None] | None = None,
    ) -> None:
        if isinstance(dispatch, VerificationReservation):
            if plan_adapter is not None:
                raise ProductionConfigError(
                    "candidate verification must not configure a planning adapter"
                )
        elif plan_adapter is None:
            raise ProductionConfigError("delivery requires a planning adapter")
        self._dispatch = dispatch
        self._definitions = dict(definitions)
        self._plan_adapter = plan_adapter
        self._config = config
        self._repository_root = Path(repository_root).resolve()
        self._repository_workspace_root = Path(repository_workspace_root).resolve()
        self._environment = dict(environment if environment is not None else os.environ)
        worktree_root = (
            Path(config.platform_root).expanduser().resolve()
            / "worktrees"
            / str(dispatch.repository_id)
        )
        self._coordinator = DispatchRoleWorktreeCoordinator(
            RoleWorktreeSession(
                GitWorktreeManager(
                    self._repository_root,
                    worktree_root,
                    branch_names=(
                        {}
                        if isinstance(dispatch, VerificationReservation)
                        else {dispatch.task_id: dispatch.task.branch_name}
                    ),
                ),
                environment=self._environment,
            )
        )
        self._context_resolver = context_resolver
        self._route_adapters = route_adapters or ConfiguredDeliveryRouteAdapterFactory()
        self._route_scope = route_scope
        self._route_validator = route_validator
        self._coder: RoleWorktreeBinding | None = None
        self._verifiers: dict[tuple[AgentRole, int], RoleWorktreeBinding] = {}
        self._adapters: dict[tuple[AgentRole, int], AgentAdapter] = {}

    def run(self, request: AgentRequest) -> AgentResult:
        if isinstance(self._dispatch, VerificationReservation):
            if request.role not in (AgentRole.QA, AgentRole.REVIEWER):
                raise ProductionConfigError(
                    f"candidate verification cannot invoke {request.role.value.capitalize()}"
                )
            # Artifact/Context provenance stays on the original Task; only checkout
            # and workforce reservations use the separate verification Task identity.
            request_task_id = self._dispatch.source_task_id
        else:
            request_task_id = self._dispatch.task_id
        if request.task_id != request_task_id:
            raise ProductionConfigError("Agent request does not belong to this dispatch Task")
        if request.role is AgentRole.ORCHESTRATOR:
            if self._plan_adapter is None:
                raise ProductionConfigError("candidate verification cannot invoke Orchestrator")
            return self._plan_adapter.run(request)
        binding = self._binding(request)
        key = (request.role, binding.worktree.attempt)
        adapter = self._adapters.get(key)
        if adapter is None:
            adapter = self._route_adapter(request.role, binding)
            self._adapters[key] = adapter
        return adapter.run(request)

    def close_clean_worktrees(self) -> None:
        """Remove only clean worktrees; dirty failure evidence stays on disk."""
        bindings: list[RoleWorktreeBinding] = []
        if self._coder is not None:
            bindings.append(self._coder)
        bindings.extend(self._verifiers.values())
        for binding in reversed(bindings):
            with suppress(Exception):
                self._coordinator.close(binding)

    def _binding(self, request: AgentRequest) -> RoleWorktreeBinding:
        if request.role is AgentRole.CODER:
            if isinstance(self._dispatch, VerificationReservation):
                raise ProductionConfigError("candidate verification cannot invoke Coder")
            if self._coder is None:
                self._coder = self._coordinator.open_coder(
                    self._dispatch,
                    self._definitions,
                    source_revision=request.source_revision,
                    recover=self._worktree_exists(AgentRole.CODER),
                )
            return self._coder
        if request.role not in {AgentRole.QA, AgentRole.REVIEWER}:
            raise ProductionConfigError(f"unsupported delivery role: {request.role.value}")
        attempt = 1 if isinstance(self._dispatch, VerificationReservation) else request.attempt
        binding = self._coordinator.open_verifier(
            self._dispatch,
            request.role,
            request.source_revision,
            self._definitions,
            attempt=attempt,
            recover=self._worktree_exists(request.role, attempt=attempt),
        )
        snapshot = self._coordinator.inspect(binding)
        if snapshot.dirty:
            raise DirtyWorktree(snapshot.changed_paths)
        self._verifiers[(request.role, attempt)] = binding
        return binding

    def _route_adapter(
        self,
        role: AgentRole,
        binding: RoleWorktreeBinding,
    ) -> AgentAdapter:
        definition = self._definitions[role]
        configured = self._ordered_routes(definition)
        if self._route_validator is not None:
            self._route_validator(role, configured)
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
                    reasoning_effort=route.reasoning_effort,
                    route_kind=route.kind.value,
                    connection_mode=self._config.effective_connection_mode(route),
                )
            )
        return FallbackAgentAdapter(
            tuple(routes),
            attempt_store=FileModelRouteAttemptStore(
                model_route_root(self._repository_workspace_root)
            ),
        )

    def _ordered_routes(
        self,
        definition: AgentDefinition,
    ) -> tuple[ProviderRouteConfig, ...]:
        routes = self._route_scope or self._config.routes_for(TeamRole(definition.role.value))
        primary = tuple(
            route
            for route in routes
            if route.provider == definition.provider
            and route.model == definition.model
            and (
                definition.reasoning_effort is None
                or route.reasoning_effort == definition.reasoning_effort
            )
            and (definition.route_kind is None or route.kind.value == definition.route_kind)
            and (
                definition.connection_mode is None
                or self._config.effective_connection_mode(route) == definition.connection_mode
            )
        )
        if len(primary) != 1:
            raise ProductionConfigError(
                "dispatch route is unavailable or ambiguous: "
                f"{definition.provider}/{definition.model}@{definition.reasoning_effort}"
            )
        selected = primary[0]
        return (selected, *(route for route in routes if route is not selected))

    def _worktree_exists(self, role: AgentRole, *, attempt: int = 1) -> bool:
        root = (
            Path(self._config.platform_root).expanduser().resolve()
            / "worktrees"
            / str(self._dispatch.repository_id)
            / self._dispatch.task_id
            / f"{role.value}-attempt-{attempt:02d}"
        )
        return root.exists()


__all__ = [
    "ConfiguredDeliveryRouteAdapterFactory",
    "DeliveryRouteAdapterFactory",
    "DispatchDeliveryAgentAdapter",
]
