"""T014 runtime composition tests through the public configuration and adapter seams."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.agents import AgentRequest, AgentResult, AgentRunStatus
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.context import ContextSource, FileContextStore
from ai_software_engineer.domain import AgentRole, Artifact, QaReportStatus
from ai_software_engineer.evaluation import (
    CaseStartedEvent,
    EvaluationTraceBuilder,
    FileEvaluationEventStore,
)
from ai_software_engineer.orchestration import BlockedResult, TaskNotRunnable
from ai_software_engineer.runtime import (
    RoleAgentOverride,
    RuntimeConfig,
    RuntimeConfigurationError,
    RuntimePaths,
    RuntimePersistence,
    RuntimeSession,
)
from ai_software_engineer.store import SqliteTaskRepository
from tests.domain.factories import (
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
    make_review_artifact,
    make_task,
)


class RuntimeFixtureAdapter:
    """Offline adapter that returns valid, request-bound artifacts for all four roles."""

    def __init__(self) -> None:
        self.requests: list[AgentRequest] = []

    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        artifact = self._artifact(request)
        return AgentResult(
            run_id=request.run_id,
            task_id=request.task_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=AgentRunStatus.SUCCEEDED,
            artifact=artifact,
        )

    def _artifact(self, request: AgentRequest) -> Artifact:
        producer_update = {
            "run_id": request.run_id,
            "agent_id": f"agent_{request.role.value}_001",
        }
        if request.role is AgentRole.ORCHESTRATOR:
            return make_plan_artifact().model_copy(
                update={
                    "artifact_id": "art_plan_runtime",
                    "task_id": request.task_id,
                    "source_revision": request.source_revision,
                    "context_manifest_id": request.context_manifest_id,
                    "parent_artifact_ids": (),
                    "producer": make_plan_artifact().producer.model_copy(update=producer_update),
                }
            )
        if request.role is AgentRole.CODER:
            candidate = "b" * 40
            return make_implementation_artifact().model_copy(
                update={
                    "artifact_id": "art_impl_runtime",
                    "task_id": request.task_id,
                    "source_revision": candidate,
                    "context_manifest_id": request.context_manifest_id,
                    "parent_artifact_ids": request.input_artifact_ids,
                    "producer": make_implementation_artifact().producer.model_copy(
                        update=producer_update
                    ),
                    "content": make_implementation_artifact().content.model_copy(
                        update={"commit_sha": candidate}
                    ),
                }
            )
        if request.role is AgentRole.QA:
            return make_qa_artifact().model_copy(
                update={
                    "artifact_id": "art_qa_runtime",
                    "task_id": request.task_id,
                    "source_revision": request.source_revision,
                    "context_manifest_id": request.context_manifest_id,
                    "parent_artifact_ids": (request.input_artifact_ids[1],),
                    "producer": make_qa_artifact().producer.model_copy(update=producer_update),
                    "content": make_qa_artifact().content.model_copy(
                        update={"status": QaReportStatus.PASS}
                    ),
                }
            )
        return make_review_artifact().model_copy(
            update={
                "artifact_id": "art_review_runtime",
                "task_id": request.task_id,
                "source_revision": request.source_revision,
                "context_manifest_id": request.context_manifest_id,
                "parent_artifact_ids": (request.input_artifact_ids[2],),
                "producer": make_review_artifact().producer.model_copy(update=producer_update),
            }
        )


def _config(tmp_path: Path, *, api_key_required: bool = False) -> RuntimeConfig:
    return RuntimeConfig(
        endpoint="https://api.example.test/v1",
        model="fake-runtime-model",
        api_key_required=api_key_required,
        paths=RuntimePaths(
            database=str(tmp_path / "state.sqlite3"),
            artifacts=str(tmp_path / "artifacts"),
            contexts=str(tmp_path / "contexts"),
            evaluation_events=str(tmp_path / "evaluation-events"),
            handoffs=str(tmp_path / "handoffs"),
        ),
    )


@pytest.mark.parametrize("input_limit", [12_000, 32_000])
def test_explicit_context_limit_reaches_all_runtime_roles(tmp_path: Path, input_limit: int) -> None:
    config = _config(tmp_path).model_copy(
        update={
            "context_max_input_tokens": input_limit,
            "context_sources": (
                ContextSource(
                    source_id="approved.design",
                    uri="design://fixture",
                    content="Design detail. " * 4000,
                    required=True,
                ),
            ),
        }
    )
    task = make_task().model_copy(update={"repository": str(tmp_path)})
    with SqliteTaskRepository(config.paths.database) as repository:
        repository.create(task)
    adapter = RuntimeFixtureAdapter()
    with RuntimeSession(config, agent_adapter=adapter, environment={}) as runtime:
        if input_limit == 12_000:
            blocked = runtime.run_task(task.id).result
            assert isinstance(blocked, BlockedResult)
            assert blocked.classification.value == "BUDGET_EXHAUSTED"
            assert blocked.task.status.value == "BLOCKED"
            assert adapter.requests == []
            return
        result = runtime.run_task(task.id)
    assert result.result.task.status.value == "DONE"
    assert len(adapter.requests) == 4
    store = FileContextStore(config.paths.contexts)
    for request in adapter.requests:
        context = store.get(request.context_manifest_id)
        assert context.budget.max_input_tokens == input_limit
        assert 12_000 < context.budget.used_input_tokens < input_limit
        assert all(not section.truncated for section in context.sections)


@pytest.mark.parametrize("overflow_role", list(AgentRole))
def test_context_overflow_records_current_phase_without_retry(
    tmp_path: Path, overflow_role: AgentRole
) -> None:
    config = _config(tmp_path).model_copy(
        update={
            "context_sources": (
                ContextSource(
                    source_id="large.required",
                    uri="source://large",
                    content="x" * 52_000,
                    roles=(overflow_role,),
                    required=True,
                ),
            )
        }
    )
    task = make_task().model_copy(update={"repository": str(tmp_path)})
    with SqliteTaskRepository(config.paths.database) as repository:
        repository.create(task)
    adapter = RuntimeFixtureAdapter()
    with RuntimeSession(config, agent_adapter=adapter, environment={}) as runtime:
        blocked = runtime.run_task(task.id).result
        assert isinstance(blocked, BlockedResult)
        assert blocked.task.status.value == "BLOCKED"
        assert blocked.classification.value == "BUDGET_EXHAUSTED"
        assert blocked.attempt == 1
        with pytest.raises(TaskNotRunnable):
            runtime.run_task(task.id)
    roles = list(AgentRole)
    assert [request.role for request in adapter.requests] == roles[: roles.index(overflow_role)]
    with SqliteTaskRepository(config.paths.database) as repository:
        events = repository.list_events(task.id)
        assert tuple(event.event_id for event in events) == blocked.event_ids
        assert repository.get(task.id) == blocked.task
        assert (
            events[-1].from_status.value
            == {
                AgentRole.ORCHESTRATOR: "PLANNING",
                AgentRole.CODER: "IMPLEMENTING",
                AgentRole.QA: "QA",
                AgentRole.REVIEWER: "REVIEW",
            }[overflow_role]
        )
        assert events[-1].source_revision == events[-2].source_revision
    artifacts = FileArtifactStore(config.paths.artifacts).list_for_task(task.id)
    assert set(blocked.artifact_ids) == {artifact.artifact_id for artifact in artifacts}


def test_runtime_config_builds_all_roles_with_v01_permission_boundaries() -> None:
    config = RuntimeConfig(endpoint="https://api.example.test/v1", model="runtime-model")

    definitions = config.agent_definitions()

    assert set(definitions) == set(AgentRole)
    assert definitions[AgentRole.CODER].permissions.write_paths == ("src/**", "tests/**")
    assert definitions[AgentRole.QA].permissions.write_paths == ("tests/**",)
    assert definitions[AgentRole.REVIEWER].permissions.write_paths == ()
    assert definitions[AgentRole.ORCHESTRATOR].permissions.can_change_state is True
    assert all(definition.permissions.can_merge is False for definition in definitions.values())


def test_runtime_config_rejects_duplicate_role_overrides() -> None:
    with pytest.raises(ValidationError, match="runtime role overrides"):
        RuntimeConfig(
            endpoint="https://api.example.test/v1",
            model="runtime-model",
            role_overrides=(
                RoleAgentOverride(role=AgentRole.CODER),
                RoleAgentOverride(role=AgentRole.CODER),
            ),
        )


def test_runtime_config_rejects_unknown_fields_and_invalid_secret_names() -> None:
    with pytest.raises(ValidationError, match="api_key"):
        RuntimeConfig.model_validate(
            {
                "endpoint": "https://api.example.test/v1",
                "model": "runtime-model",
                "api_key": "must-not-be-accepted",
            }
        )
    with pytest.raises(ValidationError, match="api_key_env"):
        RuntimeConfig(
            endpoint="https://api.example.test/v1",
            model="runtime-model",
            api_key_env="not-an-env-name",
        )


def test_runtime_role_overrides_cannot_widen_write_boundaries() -> None:
    config = RuntimeConfig(
        endpoint="https://api.example.test/v1",
        model="runtime-model",
        role_overrides=(RoleAgentOverride(role=AgentRole.REVIEWER, write_paths=("src/**",)),),
    )

    with pytest.raises(RuntimeConfigurationError, match="reviewer cannot write"):
        config.agent_definitions()


def test_runtime_role_overrides_require_unique_agent_ids() -> None:
    config = RuntimeConfig(
        endpoint="https://api.example.test/v1",
        model="runtime-model",
        role_overrides=(RoleAgentOverride(role=AgentRole.CODER, agent_id="agent_qa_runtime"),),
    )

    with pytest.raises(ValueError, match="runtime agent IDs"):
        config.agent_definitions()


def test_runtime_session_requires_only_declared_environment_secret(tmp_path: Path) -> None:
    with pytest.raises(RuntimeConfigurationError, match="OPENAI_API_KEY"):
        RuntimeSession(_config(tmp_path, api_key_required=True), environment={})


def test_mysql_runtime_requires_only_the_declared_dsn_environment_name(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path).model_copy(
        update={
            "persistence": RuntimePersistence(
                backend="mysql",
                mysql_dsn_env="TEAM_MYSQL_DSN",
            )
        }
    )

    with pytest.raises(RuntimeConfigurationError, match="TEAM_MYSQL_DSN") as captured:
        RuntimeSession(config, environment={}, agent_adapter=RuntimeFixtureAdapter())

    assert "mysql://" not in str(captured.value)


def test_runtime_session_rejects_changed_runtime_identity_for_existing_case(tmp_path: Path) -> None:
    repository_root = tmp_path / "project"
    repository_root.mkdir()
    config = _config(tmp_path)
    task = make_task().model_copy(update={"repository": str(repository_root)})
    case_id = "case_runtime_001"
    FileEvaluationEventStore(config.paths.evaluation_events).append(
        CaseStartedEvent(
            event_id="evalevt_case_started_001",
            case_id=case_id,
            task_id=task.id,
            occurred_at=datetime.now(UTC),
            base_revision=task.base_ref,
            model_id="different-frozen-model",
            prompt_version=config.prompt_version,
            spec_version=config.spec_version,
            test_entrypoints=config.test_entrypoints,
        )
    )
    with SqliteTaskRepository(config.paths.database) as repository:
        repository.create(task)

    with (
        RuntimeSession(config, environment={}, agent_adapter=RuntimeFixtureAdapter()) as session,
        pytest.raises(RuntimeConfigurationError, match="frozen Task/runtime identity"),
    ):
        session.run_task(task.id, case_id=case_id)


def test_runtime_session_composes_serial_delivery_and_persists_case_facts(tmp_path: Path) -> None:
    repository_root = tmp_path / "project"
    repository_root.mkdir()
    adapter = RuntimeFixtureAdapter()
    config = _config(tmp_path)
    task = make_task().model_copy(update={"repository": str(repository_root)})

    with SqliteTaskRepository(config.paths.database) as repository:
        repository.create(task)
    with RuntimeSession(config, environment={}, agent_adapter=adapter) as session:
        assert Path(config.paths.evidence).is_dir()
        assert Path(config.paths.runs).is_dir()
        result = session.run_task(task.id)
    events = FileEvaluationEventStore(config.paths.evaluation_events).list_for_case(result.case_id)
    with SqliteTaskRepository(config.paths.database) as repository:
        trace = EvaluationTraceBuilder(
            repository=repository,
            artifact_store=FileArtifactStore(config.paths.artifacts),
            event_store=FileEvaluationEventStore(config.paths.evaluation_events),
        ).build(result.case_id)

    assert result.result.task.status.value == "DONE"
    assert trace.task.status.value == "DONE"
    assert len(adapter.requests) == 4
    assert tuple(request.role for request in adapter.requests) == (
        AgentRole.ORCHESTRATOR,
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    )
    assert len(events) == 5
    assert isinstance(events[0], CaseStartedEvent)
    assert result.case_id.startswith("case_")
