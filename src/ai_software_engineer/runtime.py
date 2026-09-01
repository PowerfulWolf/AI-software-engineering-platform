"""Operator-owned runtime configuration and serial Task execution composition."""

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Self

from pydantic import Field, StrictBool, StrictInt, StringConstraints, model_validator

from ai_software_engineer.agents import (
    AgentAdapter,
    AgentRequest,
    AgentResult,
    OpenAICompatibleAgentAdapter,
    StoredContextResolver,
)
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.context import ContextSource, FileContextStore
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentPermissions,
    AgentRole,
    ArtifactKind,
    NetworkAccess,
    TaskStatus,
)
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.evaluation import (
    CaseStartedEvent,
    EvaluatingAgentAdapter,
    EvaluationCaseId,
    EvaluationEventStore,
    FileEvaluationEventStore,
)
from ai_software_engineer.orchestration import (
    FileRunContextBuilder,
    RetryingOrchestrator,
    RetryResult,
    TaskNotRunnable,
)
from ai_software_engineer.store import SqliteTaskRepository

EnvVarName = Annotated[str, StringConstraints(pattern=r"^[A-Z_][A-Z0-9_]{0,127}$")]

_ROLE_INPUTS: dict[AgentRole, tuple[ArtifactKind, ...]] = {
    AgentRole.ORCHESTRATOR: (),
    AgentRole.CODER: (
        ArtifactKind.PLAN,
        ArtifactKind.QA_REPORT,
        ArtifactKind.REVIEW_REPORT,
    ),
    AgentRole.QA: (ArtifactKind.PLAN, ArtifactKind.IMPLEMENTATION_REPORT),
    AgentRole.REVIEWER: (
        ArtifactKind.PLAN,
        ArtifactKind.IMPLEMENTATION_REPORT,
        ArtifactKind.QA_REPORT,
    ),
}
_ROLE_OUTPUTS: dict[AgentRole, tuple[ArtifactKind, ...]] = {
    AgentRole.ORCHESTRATOR: (ArtifactKind.PLAN,),
    AgentRole.CODER: (ArtifactKind.IMPLEMENTATION_REPORT,),
    AgentRole.QA: (ArtifactKind.QA_REPORT,),
    AgentRole.REVIEWER: (ArtifactKind.REVIEW_REPORT,),
}
_DEFAULT_READ_PATHS: tuple[str, ...] = ("**",)
_DEFAULT_COMMANDS: tuple[str, ...] = ("pytest", "ruff", "git diff", "git status")


class RuntimeConfigurationError(RuntimeError):
    """Raised when operator runtime configuration cannot safely be composed."""


class RuntimePaths(DomainModel):
    """Durable roots used by one local serial runtime session."""

    database: NonEmptyStr = ".ase/state.sqlite3"
    artifacts: NonEmptyStr = "artifacts/runs"
    contexts: NonEmptyStr = "artifacts/contexts"
    evaluation_events: NonEmptyStr = "artifacts/evaluation-events"
    handoffs: NonEmptyStr = "artifacts/handoffs"


class RoleAgentOverride(DomainModel):
    """Optional per-role model and machine-policy overrides."""

    role: AgentRole
    agent_id: NonEmptyStr | None = None
    model: NonEmptyStr | None = None
    version: NonEmptyStr | None = None
    read_paths: tuple[NonEmptyStr, ...] | None = None
    write_paths: tuple[NonEmptyStr, ...] | None = None
    commands: tuple[NonEmptyStr, ...] | None = None
    network: NetworkAccess | None = None
    max_retries: StrictInt | None = Field(default=None, ge=0, le=5)
    timeout_seconds: StrictInt | None = Field(default=None, ge=1, le=3600)
    token_budget: StrictInt | None = Field(default=None, ge=1)


class RuntimeConfig(DomainModel):
    """Validated operator configuration; secrets remain in the process environment."""

    endpoint: NonEmptyStr
    model: NonEmptyStr
    api_key_env: EnvVarName = "OPENAI_API_KEY"
    api_key_required: StrictBool = True
    agent_version: NonEmptyStr = "v0.1"
    prompt_version: NonEmptyStr = "prompt-v0.1"
    spec_version: NonEmptyStr = "spec-v0.1"
    test_entrypoints: tuple[NonEmptyStr, ...] = ("pytest",)
    paths: RuntimePaths = RuntimePaths()
    context_sources: tuple[ContextSource, ...] = ()
    role_overrides: tuple[RoleAgentOverride, ...] = ()
    timeout_seconds: StrictInt = Field(default=600, ge=1, le=3600)
    token_budget: StrictInt = Field(default=20_000, ge=1)
    max_retries: StrictInt = Field(default=0, ge=0, le=5)

    @model_validator(mode="after")
    def validate_runtime_contract(self) -> Self:
        ensure_unique((item.role for item in self.role_overrides), "runtime role overrides")
        ensure_unique(self.test_entrypoints, "runtime test_entrypoints")
        if any(ord(character) < 32 for character in self.endpoint):
            raise ValueError("runtime endpoint cannot contain control characters")
        return self

    @classmethod
    def from_file(cls, path: str | Path) -> "RuntimeConfig":
        """Load and validate one operator configuration document."""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(payload)

    def agent_definitions(self) -> dict[AgentRole, AgentDefinition]:
        """Build the four deterministic role definitions used by the serial runner."""
        overrides = {item.role: item for item in self.role_overrides}
        definitions: dict[AgentRole, AgentDefinition] = {}
        for role in AgentRole:
            override = overrides.get(role)
            permissions = _permissions(role, override)
            definitions[role] = AgentDefinition(
                id=(
                    override.agent_id
                    if override and override.agent_id
                    else f"agent_{role.value}_runtime"
                ),
                role=role,
                version=(override.version if override and override.version else self.agent_version),
                model=(override.model if override and override.model else self.model),
                provider="openai-compatible",
                permissions=permissions,
                input_artifacts=_ROLE_INPUTS[role],
                output_artifacts=_ROLE_OUTPUTS[role],
                max_retries=(
                    override.max_retries
                    if override and override.max_retries is not None
                    else self.max_retries
                ),
                timeout_seconds=(
                    override.timeout_seconds
                    if override and override.timeout_seconds is not None
                    else self.timeout_seconds
                ),
                token_budget=(
                    override.token_budget
                    if override and override.token_budget is not None
                    else self.token_budget
                ),
            )
        ensure_unique((definition.id for definition in definitions.values()), "runtime agent IDs")
        return definitions


@dataclass(frozen=True, slots=True)
class RuntimeRunResult:
    """One run result plus the evaluation case identity used to record it."""

    case_id: EvaluationCaseId
    result: RetryResult


class RoleAwareAgentAdapter:
    """Route typed AgentRequests to the adapter configured for their role."""

    def __init__(self, adapters: Mapping[AgentRole, AgentAdapter]) -> None:
        self._adapters = dict(adapters)
        missing = set(AgentRole) - set(self._adapters)
        if missing:
            roles = ", ".join(sorted(role.value for role in missing))
            raise RuntimeConfigurationError(f"missing AgentAdapter for role(s): {roles}")

    def run(self, request: AgentRequest) -> AgentResult:
        """Delegate without allowing provider-specific values across the typed seam."""
        return self._adapters[request.role].run(request)


class RuntimeSession:
    """Open durable stores and compose one bounded serial Task execution."""

    def __init__(
        self,
        config: RuntimeConfig,
        *,
        environment: Mapping[str, str] | None = None,
        agent_adapter: AgentAdapter | None = None,
        agent_definitions: Mapping[AgentRole, AgentDefinition] | None = None,
        project_root: str | Path | None = None,
    ) -> None:
        self._config = config
        self._agent_definitions = _validate_agent_definitions(
            agent_definitions if agent_definitions is not None else config.agent_definitions()
        )
        self._project_root = _validated_project_root(project_root)
        self._case_model_id = _model_identity(self._agent_definitions)
        variables = environment if environment is not None else os.environ
        api_key = variables.get(config.api_key_env)
        if config.api_key_required and not api_key:
            raise RuntimeConfigurationError(
                f"required API key environment variable is missing: {config.api_key_env}"
            )
        self._repository = SqliteTaskRepository(config.paths.database)
        self._artifact_store = FileArtifactStore(config.paths.artifacts)
        self._context_store = FileContextStore(config.paths.contexts)
        self._evaluation_store: EvaluationEventStore = FileEvaluationEventStore(
            config.paths.evaluation_events
        )
        if agent_adapter is not None:
            self._agent_adapter = agent_adapter
        else:
            resolver = StoredContextResolver(self._context_store, self._artifact_store)
            self._agent_adapter = RoleAwareAgentAdapter(
                {
                    role: OpenAICompatibleAgentAdapter(
                        endpoint=config.endpoint,
                        api_key=api_key,
                        model=definition.model,
                        agent_id=definition.id,
                        agent_version=definition.version,
                        context_resolver=resolver,
                    )
                    for role, definition in self._agent_definitions.items()
                }
            )

    def run_task(
        self,
        task_id: TaskId,
        *,
        case_id: EvaluationCaseId | None = None,
    ) -> RuntimeRunResult:
        """Record a CaseStartedEvent and run the existing bounded serial orchestrator."""
        task = self._repository.get(task_id)
        project_root = Path(task.repository).expanduser().resolve(strict=False)
        if self._project_root is not None and project_root != self._project_root:
            raise RuntimeConfigurationError(
                f"Task {task.id} repository does not match bound project root"
            )
        if not project_root.is_dir():
            raise RuntimeConfigurationError(
                f"Task {task.id} repository is not an existing directory: {project_root}"
            )
        if task.status in {TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.FAILED}:
            raise TaskNotRunnable(f"Task {task.id} is terminal at {task.status.value}")
        selected_case = case_id or _default_case_id(task.id)
        self._ensure_case_started(selected_case, task.id, task.base_ref)
        context_builder = FileRunContextBuilder(
            project_root,
            sources=self._config.context_sources,
            context_store=self._context_store,
        )
        instrumented = EvaluatingAgentAdapter(
            case_id=selected_case,
            delegate=self._agent_adapter,
            event_store=self._evaluation_store,
        )
        runner = RetryingOrchestrator(
            repository=self._repository,
            artifact_store=self._artifact_store,
            context_builder=context_builder,
            agent_adapter=instrumented,
            agent_definitions=self._agent_definitions,
        )
        return RuntimeRunResult(case_id=selected_case, result=runner.run_task(task.id))

    def _ensure_case_started(
        self, case_id: EvaluationCaseId, task_id: TaskId, base_revision: str
    ) -> None:
        existing = self._evaluation_store.list_for_case(case_id)
        starts = tuple(event for event in existing if isinstance(event, CaseStartedEvent))
        if len(starts) > 1:
            raise RuntimeConfigurationError(f"case {case_id} has multiple CaseStartedEvent facts")
        if starts:
            start = starts[0]
            if (
                start.task_id != task_id
                or start.base_revision != base_revision
                or start.model_id != self._case_model_id
                or start.prompt_version != self._config.prompt_version
                or start.spec_version != self._config.spec_version
                or start.test_entrypoints != self._config.test_entrypoints
            ):
                raise RuntimeConfigurationError(
                    f"case {case_id} does not match its frozen Task/runtime identity"
                )
            return
        if existing:
            raise RuntimeConfigurationError(
                f"case {case_id} contains facts without CaseStartedEvent"
            )
        self._evaluation_store.append(
            CaseStartedEvent(
                event_id=_case_started_event_id(case_id),
                case_id=case_id,
                task_id=task_id,
                occurred_at=datetime.now(UTC),
                base_revision=base_revision,
                model_id=self._case_model_id,
                prompt_version=self._config.prompt_version,
                spec_version=self._config.spec_version,
                test_entrypoints=self._config.test_entrypoints,
                included=True,
            )
        )

    def close(self) -> None:
        """Close the SQLite connection while retaining all durable facts."""
        self._repository.close()

    def __enter__(self) -> "RuntimeSession":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


def _permissions(role: AgentRole, override: RoleAgentOverride | None) -> AgentPermissions:
    default_writes = {
        AgentRole.ORCHESTRATOR: (),
        AgentRole.CODER: ("src/**", "tests/**"),
        AgentRole.QA: ("tests/**",),
        AgentRole.REVIEWER: (),
    }[role]
    write_paths = (
        override.write_paths if override and override.write_paths is not None else default_writes
    )
    _validate_write_scope(role, write_paths)
    return AgentPermissions(
        read_paths=(
            override.read_paths
            if override and override.read_paths is not None
            else _DEFAULT_READ_PATHS
        ),
        write_paths=write_paths,
        commands=(
            override.commands if override and override.commands is not None else _DEFAULT_COMMANDS
        ),
        network=(
            override.network
            if override and override.network is not None
            else NetworkAccess.MODEL_ENDPOINT_ONLY
        ),
        can_change_state=role is AgentRole.ORCHESTRATOR,
    )


def _validate_write_scope(role: AgentRole, write_paths: tuple[NonEmptyStr, ...]) -> None:
    """Prevent a role override from widening v0.1's machine-enforced write boundary."""
    if role in {AgentRole.ORCHESTRATOR, AgentRole.REVIEWER} and write_paths:
        raise RuntimeConfigurationError(f"{role.value} cannot write repository paths in v0.1")
    allowed_prefixes = {
        AgentRole.CODER: ("src/", "tests/"),
        AgentRole.QA: ("tests/",),
    }.get(role, ())
    invalid = tuple(path for path in write_paths if not path.startswith(allowed_prefixes))
    if invalid:
        rendered = ", ".join(invalid)
        raise RuntimeConfigurationError(
            f"{role.value} write_paths exceed the v0.1 role boundary: {rendered}"
        )


def _default_case_id(task_id: str) -> EvaluationCaseId:
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:32]
    return f"case_{digest}"


def _case_started_event_id(case_id: str) -> str:
    digest = hashlib.sha256(f"case-started\0{case_id}".encode()).hexdigest()[:32]
    return f"evalevt_case_started_{digest}"


def _validated_project_root(project_root: str | Path | None) -> Path | None:
    if project_root is None:
        return None
    resolved = Path(project_root).expanduser().resolve(strict=False)
    if not resolved.is_dir():
        raise RuntimeConfigurationError(f"bound project root is not a directory: {resolved}")
    return resolved


def _validate_agent_definitions(
    definitions: Mapping[AgentRole, AgentDefinition],
) -> dict[AgentRole, AgentDefinition]:
    resolved = dict(definitions)
    missing = set(AgentRole) - set(resolved)
    extra = set(resolved) - set(AgentRole)
    mismatched = tuple(role for role, definition in resolved.items() if definition.role is not role)
    if missing or extra or mismatched:
        raise RuntimeConfigurationError("runtime AgentDefinitions must match every role exactly")
    ensure_unique((definition.id for definition in resolved.values()), "runtime agent IDs")
    return resolved


def _model_identity(definitions: Mapping[AgentRole, AgentDefinition]) -> str:
    routes = tuple(
        sorted(
            (role.value, definition.provider or "unknown", definition.model)
            for role, definition in definitions.items()
        )
    )
    models = {(provider, model) for _, provider, model in routes}
    if len(models) == 1:
        return next(iter(models))[1]
    encoded = json.dumps(routes, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"model-set-{hashlib.sha256(encoded).hexdigest()[:24]}"


__all__ = [
    "RoleAgentOverride",
    "RoleAwareAgentAdapter",
    "RuntimeConfig",
    "RuntimeConfigurationError",
    "RuntimePaths",
    "RuntimeRunResult",
    "RuntimeSession",
]
