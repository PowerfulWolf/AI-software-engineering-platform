"""Keep Python domain payloads aligned with the canonical Draft 2020-12 schemas."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context import ContextBudget, ContextSource, FileContextBuilder
from ai_software_engineer.domain import AgentPermissions, AgentRole, NetworkAccess
from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.evaluation import HandoffBuilder
from ai_software_engineer.knowledge_documents import (
    ProjectKnowledgeDocumentStore,
    TeamKnowledgeDocumentStore,
)
from ai_software_engineer.knowledge_selection import (
    ProjectKnowledgeSelectionStore,
    TeamKnowledgeSelectionStore,
)
from ai_software_engineer.learning import (
    DecideLearningProposal,
    LearningAuthorization,
    LearningDecisionAction,
    LearningTarget,
    ProjectLearningStore,
)
from ai_software_engineer.runtime import RuntimeConfig
from ai_software_engineer.spec_documents import CreateSpecDocument, TeamSpecDocumentStore
from ai_software_engineer.team_workspace import TeamWorkspace
from ai_software_engineer.web_console import (
    CloseRequirementIntent,
    ConsoleCommandResult,
    ConsoleOperation,
    ConsoleOperationStatus,
    CreateRequirementIntent,
    DeleteRequirementIntent,
    ProductReplyIntent,
    UpdateRequirementIntent,
)
from tests.domain.factories import (
    make_agent,
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
    make_review_artifact,
    make_state_event,
    make_task,
)
from tests.evaluation.factories import (
    make_agent_run,
    make_case_started,
    make_human_action,
    make_regression_check,
)
from tests.evaluation.test_handoff import _persist_trace
from tests.specs.test_learning import _project_with_failure

SCHEMA_DIR = Path(__file__).parents[2] / "schemas"


class WireModel(Protocol):
    def to_wire(self) -> WirePayload: ...


type ModelFactory = Callable[[], WireModel]
type JsonSchema = dict[str, object]


def _load_schema(path: Path) -> JsonSchema:
    decoded: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise TypeError(f"Schema must be a JSON object: {path}")
    return cast(JsonSchema, decoded)


SCHEMAS = {path.name: _load_schema(path) for path in SCHEMA_DIR.glob("*.schema.json")}
REGISTRY = Registry().with_resources(
    (
        cast(str, schema["$id"]),
        Resource.from_contents(schema),
    )
    for schema in SCHEMAS.values()
)


def _errors(payload: WirePayload, schema_name: str) -> list[str]:
    validator = Draft202012Validator(
        SCHEMAS[schema_name],
        registry=REGISTRY,
        format_checker=FormatChecker(),
    )
    return sorted(error.message for error in validator.iter_errors(payload))


def _assert_valid(payload: WirePayload, schema_name: str) -> None:
    assert _errors(payload, schema_name) == []


def _assert_invalid(payload: WirePayload, schema_name: str) -> None:
    assert _errors(payload, schema_name)


@pytest.mark.parametrize(
    ("factory", "schema_name"),
    (
        (make_task, "task.schema.json"),
        (make_agent, "agent.schema.json"),
        (make_plan_artifact, "plan.schema.json"),
        (make_implementation_artifact, "implementation-report.schema.json"),
        (make_qa_artifact, "qa-report.schema.json"),
        (make_review_artifact, "review-report.schema.json"),
        (make_state_event, "state-event.schema.json"),
    ),
)
def test_python_positive_examples_satisfy_the_canonical_schema(
    factory: ModelFactory, schema_name: str
) -> None:
    _assert_valid(factory().to_wire(), schema_name)


@pytest.mark.parametrize(
    "factory",
    (make_plan_artifact, make_implementation_artifact, make_qa_artifact, make_review_artifact),
)
def test_every_typed_artifact_satisfies_the_common_envelope(factory: ModelFactory) -> None:
    _assert_valid(factory().to_wire(), "artifact.schema.json")


def test_all_committed_schemas_are_valid_draft_2020_12_documents() -> None:
    for schema in SCHEMAS.values():
        Draft202012Validator.check_schema(schema)


def test_runtime_config_satisfies_the_canonical_schema() -> None:
    config = RuntimeConfig(endpoint="https://api.example.test/v1", model="runtime-model")

    _assert_valid(config.to_wire(), "runtime-config.schema.json")


@pytest.mark.parametrize("limit", [0, True, 2_000_001])
def test_runtime_context_limit_rejects_invalid_values(limit: int) -> None:
    payload = RuntimeConfig(endpoint="https://api.example.test/v1", model="fake").to_wire()
    payload["context_max_input_tokens"] = limit
    _assert_invalid(payload, "runtime-config.schema.json")
    with pytest.raises(ValueError):
        RuntimeConfig.model_validate(payload)


def test_production_config_satisfies_the_canonical_schema(tmp_path: Path) -> None:
    config = ProductionConfig.model_validate(
        {
            "platform_root": str((tmp_path / "platform").resolve()),
            "model_routes": [
                {
                    "provider": "codex",
                    "model": "gpt-5.5",
                    "kind": "codex_cli",
                },
                {
                    "provider": "qwen",
                    "model": "qwen3.8-max",
                    "kind": "responses",
                    "endpoint": "https://example.invalid/v1/responses",
                    "api_key_env": "QWEN_API_KEY",
                    "enabled": False,
                },
            ],
        }
    )

    _assert_valid(config.to_wire(), "production-config.schema.json")


def test_production_config_schema_requires_complete_agent_model_policy(
    tmp_path: Path,
) -> None:
    payload = ProductionConfig.model_validate(
        {
            "platform_root": str((tmp_path / "platform").resolve()),
            "model_routes": [{"provider": "codex", "model": "gpt-5.5", "kind": "codex_cli"}],
        }
    ).to_wire()
    payload["agent_model_routes"] = [
        {
            "role": "product",
            "routes": [{"provider": "codex", "model": "gpt-5.5"}],
        }
    ]

    _assert_invalid(payload, "production-config.schema.json")


def test_production_config_schema_accepts_supported_home_relative_input() -> None:
    payload = ProductionConfig.model_validate(
        {
            "platform_root": "~/custom-ase",
            "model_routes": [{"provider": "codex", "model": "gpt-5.5", "kind": "codex_cli"}],
        }
    ).to_wire()

    _assert_valid(payload, "production-config.schema.json")
    raw_payload = dict(payload)
    raw_payload["platform_root"] = "~/custom-ase"
    _assert_valid(raw_payload, "production-config.schema.json")


@pytest.mark.parametrize(
    "platform_root",
    [
        "relative",
        "~//escape",
        "~/../escape",
        "~/custom/../escape",
        "/../escape",
        "/tmp/platform/../escape",
        "bad\x00path",
    ],
)
def test_production_config_schema_rejects_unsafe_explicit_paths(platform_root: str) -> None:
    payload: WirePayload = {
        "platform_root": platform_root,
        "model_routes": [{"provider": "codex", "model": "gpt-5.5", "kind": "codex_cli"}],
    }

    _assert_invalid(payload, "production-config.schema.json")


def test_production_config_schema_allows_omitted_platform_root() -> None:
    payload: WirePayload = {
        "model_routes": [{"provider": "codex", "model": "gpt-5.5", "kind": "codex_cli"}],
    }

    _assert_valid(payload, "production-config.schema.json")


@pytest.mark.parametrize("console_port", [0, 65536, True])
def test_production_config_schema_rejects_invalid_console_port(console_port: int | bool) -> None:
    payload: WirePayload = {
        "model_routes": [{"provider": "codex", "model": "gpt-5.5", "kind": "codex_cli"}],
        "console_port": console_port,
    }

    _assert_invalid(payload, "production-config.schema.json")


def test_team_manifest_satisfies_canonical_schema(tmp_path: Path) -> None:
    workspace = TeamWorkspace.initialize(tmp_path, team_id="team_test", name="Test")
    _assert_valid(workspace.manifest.to_wire(), "team-workspace.schema.json")
    malformed = workspace.manifest.to_wire()
    malformed["team_id"] = "../escape"
    _assert_invalid(malformed, "team-workspace.schema.json")


def test_knowledge_document_manifest_satisfies_canonical_schema(tmp_path: Path) -> None:
    team = TeamWorkspace.initialize(tmp_path, team_id="team_test", name="Test")
    manifest = TeamKnowledgeDocumentStore(team).import_document(
        filename="guide.md", content=b"# Guide\n"
    )

    _assert_valid(manifest.to_wire(), "knowledge-document.schema.json")
    malformed = manifest.to_wire()
    malformed["normalized_relative_path"] = "../escape.md"
    _assert_invalid(malformed, "knowledge-document.schema.json")
    missing_version = manifest.to_wire()
    missing_version.pop("schema_version")
    _assert_invalid(missing_version, "knowledge-document.schema.json")


def test_project_knowledge_and_scope_selections_satisfy_schemas(
    tmp_path: Path,
) -> None:
    team = TeamWorkspace.initialize(tmp_path, team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Project")
    team_document = TeamKnowledgeDocumentStore(team).import_document(
        filename="team.md", content=b"# Team\n"
    )
    project_document = ProjectKnowledgeDocumentStore(project).import_document(
        filename="project.md", content=b"# Project\n"
    )
    team_selection = TeamKnowledgeSelectionStore(team).save(
        (team_document.normalized_relative_path,)
    )
    project_selection = ProjectKnowledgeSelectionStore(project).save(
        (project_document.normalized_relative_path,)
    )
    team_retirement = TeamKnowledgeDocumentStore(team).retire(team_document.document_id)
    project_retirement = ProjectKnowledgeDocumentStore(project).retire(project_document.document_id)

    _assert_valid(project_document.to_wire(), "project-knowledge-document.schema.json")
    _assert_valid(team_selection.to_wire(), "knowledge-selection.schema.json")
    _assert_valid(project_selection.to_wire(), "knowledge-selection.schema.json")
    _assert_valid(team_retirement.to_wire(), "knowledge-retirement.schema.json")
    _assert_valid(project_retirement.to_wire(), "knowledge-retirement.schema.json")
    malformed = team_selection.to_wire()
    malformed["project_id"] = "project_test"
    _assert_invalid(malformed, "knowledge-selection.schema.json")


def test_spec_document_and_activation_satisfy_canonical_schemas(tmp_path: Path) -> None:
    team = TeamWorkspace.initialize(
        tmp_path / "platform", team_id="team_schema", name="Schema team"
    )
    store = TeamSpecDocumentStore(team)
    document = store.create(
        CreateSpecDocument(
            spec_key="python.testing",
            title="Python testing",
            body_markdown="# Testing\n",
            verification="Record passing pytest evidence.",
        )
    )
    activation = store.activate((document.spec_id,))
    store.activate(())
    retirement = store.retire(document.spec_key)

    _assert_valid(document.to_wire(), "spec-document.schema.json")
    without_verification_guidance = document.to_wire()
    without_verification_guidance["verification"] = ""
    without_verification_guidance["spec_sha256"] = "0" * 64
    _assert_valid(without_verification_guidance, "spec-document.schema.json")
    oversized_verification = document.to_wire()
    oversized_verification["verification"] = "x" * 8_001
    _assert_invalid(oversized_verification, "spec-document.schema.json")
    _assert_valid(activation.to_wire(), "spec-activation.schema.json")
    _assert_valid(retirement.to_wire(), "spec-retirement.schema.json")
    malformed = document.to_wire()
    malformed["scope"] = "unknown"
    _assert_invalid(malformed, "spec-document.schema.json")


def test_learning_proposal_and_decision_satisfy_canonical_schemas(tmp_path: Path) -> None:
    project = _project_with_failure(tmp_path)
    store = ProjectLearningStore(project)
    proposal = store.collect()[0].proposal
    view = store.decide(
        proposal.proposal_id,
        DecideLearningProposal(
            proposal_sha256=proposal.proposal_sha256,
            action=LearningDecisionAction.REJECT,
            target=LearningTarget.SPEC,
            operator_id="schema_operator",
            rationale="Not a reusable rule.",
        ),
    )

    _assert_valid(proposal.to_wire(), "learning-proposal.schema.json")
    authorization = LearningAuthorization.model_validate_json(
        (
            project.root / "specs" / "learning" / proposal.proposal_id / "authorization.json"
        ).read_text()
    )
    _assert_valid(authorization.to_wire(), "learning-authorization.schema.json")
    assert view.decision is not None
    _assert_valid(view.decision.to_wire(), "learning-decision.schema.json")


def test_production_config_schema_rejects_plaintext_secret(tmp_path: Path) -> None:
    payload = ProductionConfig.model_validate(
        {
            "platform_root": str((tmp_path / "platform").resolve()),
            "model_routes": [{"provider": "codex", "model": "gpt-5.5", "kind": "codex_cli"}],
        }
    ).to_wire()
    payload["mysql_dsn"] = "mysql://user:secret@example.invalid/database"

    _assert_invalid(payload, "production-config.schema.json")


def test_repository_workspace_manifest_satisfies_the_canonical_schema(tmp_path: Path) -> None:
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Test Project")
    repository = tmp_path / "repository"
    repository.mkdir()
    workspace = project.repository_registry().register(repository)

    _assert_valid(project.manifest.to_wire(), "project-workspace.schema.json")
    _assert_valid(workspace.manifest.to_wire(), "repository-workspace.schema.json")


def test_repository_workspace_schema_rejects_layout_drift(tmp_path: Path) -> None:
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Test Project")
    repository = tmp_path / "repository"
    repository.mkdir()
    workspace = project.repository_registry().register(repository)
    payload = workspace.manifest.to_wire()
    layout = payload["layout"]
    assert isinstance(layout, dict)
    layout["logs"] = "custom-logs"

    _assert_invalid(payload, "repository-workspace.schema.json")


def test_repository_workspace_schema_rejects_project_owned_agents_directory(tmp_path: Path) -> None:
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Test Project")
    repository = tmp_path / "repository"
    repository.mkdir()
    workspace = project.repository_registry().register(repository)
    payload = workspace.manifest.to_wire()
    layout = payload["layout"]
    assert isinstance(layout, dict)
    layout["agents"] = layout.pop("assignments")
    _assert_invalid(payload, "repository-workspace.schema.json")


def test_runtime_config_schema_rejects_plaintext_api_key() -> None:
    payload = RuntimeConfig(endpoint="https://api.example.test/v1", model="runtime-model").to_wire()
    payload["api_key"] = "secret-that-must-stay-out-of-config"

    _assert_invalid(payload, "runtime-config.schema.json")


def test_task_schema_rejects_malformed_id() -> None:
    payload = make_task().to_wire()
    payload["id"] = "invalid"

    _assert_invalid(payload, "task.schema.json")


def test_agent_schema_rejects_unknown_properties() -> None:
    payload = make_agent().to_wire()
    payload["self_approve"] = True

    _assert_invalid(payload, "agent.schema.json")


@pytest.mark.parametrize(
    ("factory", "schema_name"),
    (
        (make_plan_artifact, "plan.schema.json"),
        (make_implementation_artifact, "implementation-report.schema.json"),
        (make_qa_artifact, "qa-report.schema.json"),
        (make_review_artifact, "review-report.schema.json"),
    ),
)
def test_artifact_schema_rejects_missing_typed_content(
    factory: ModelFactory, schema_name: str
) -> None:
    payload = factory().to_wire()
    payload["content"] = {}

    _assert_invalid(payload, schema_name)


def test_common_artifact_schema_requires_evidence_digest() -> None:
    payload = make_plan_artifact().to_wire()
    payload["evidence"] = [
        {
            "evidence_id": "ev_missing_hash",
            "type": "file",
            "uri": "evidence/spec.txt",
            "description": "Digest intentionally omitted.",
        }
    ]

    _assert_invalid(payload, "artifact.schema.json")


def test_context_bundle_satisfies_the_canonical_schema(tmp_path: Path) -> None:
    bundle = FileContextBuilder(
        tmp_path,
        AgentPermissions(
            read_paths=(),
            write_paths=(),
            commands=("pytest",),
            network=NetworkAccess.NONE,
        ),
        sources=(
            ContextSource(
                source_id="evidence",
                uri="evidence://contract",
                content="contract evidence",
            ),
        ),
        budget=ContextBudget(max_input_tokens=500, reserved_output_tokens=100),
    ).build(make_task(), AgentRole.REVIEWER, attempt=1, candidate_revision="c" * 40)

    _assert_valid(bundle.to_wire(), "context.schema.json")


def test_context_schema_rejects_missing_section_hash(tmp_path: Path) -> None:
    bundle = FileContextBuilder(
        tmp_path,
        AgentPermissions(
            read_paths=(),
            write_paths=(),
            commands=("pytest",),
            network=NetworkAccess.NONE,
        ),
    ).build(make_task(), AgentRole.CODER, attempt=1)
    payload = bundle.to_wire()
    sections = payload["sections"]
    assert isinstance(sections, list)
    section = sections[0]
    assert isinstance(section, dict)
    section.pop("sha256")

    _assert_invalid(payload, "context.schema.json")


def test_common_artifact_schema_rejects_invalid_timestamp_format() -> None:
    payload = make_plan_artifact().to_wire()
    payload["created_at"] = "not-a-date"

    _assert_invalid(payload, "artifact.schema.json")


@pytest.mark.parametrize(
    "factory",
    (make_case_started, make_agent_run, make_human_action, make_regression_check),
)
def test_evaluation_events_satisfy_the_canonical_schema(factory: ModelFactory) -> None:
    _assert_valid(factory().to_wire(), "evaluation-event.schema.json")


def test_evaluation_event_schema_rejects_unknown_human_action() -> None:
    payload = make_human_action().to_wire()
    payload["action"] = "APPROVE_ANYTHING"

    _assert_invalid(payload, "evaluation-event.schema.json")


def test_handoff_bundle_satisfies_the_canonical_schema(tmp_path: Path) -> None:
    repository, artifacts = _persist_trace(tmp_path)
    try:
        bundle = HandoffBuilder(
            repository=repository,
            artifact_store=artifacts,
            clock=lambda: make_task().created_at,
        ).build("task_domain_001")
    finally:
        repository.close()

    _assert_valid(bundle.to_wire(), "handoff-bundle.schema.json")


def test_handoff_schema_rejects_missing_next_actions(tmp_path: Path) -> None:
    repository, artifacts = _persist_trace(tmp_path)
    try:
        payload = (
            HandoffBuilder(
                repository=repository,
                artifact_store=artifacts,
                clock=lambda: make_task().created_at,
            )
            .build("task_domain_001")
            .to_wire()
        )
    finally:
        repository.close()
    payload["next_actions"] = []

    _assert_invalid(payload, "handoff-bundle.schema.json")


def test_console_operation_states_satisfy_the_canonical_schema(tmp_path: Path) -> None:
    at = datetime(2026, 9, 12, tzinfo=UTC)
    queued = ConsoleOperation.queued(
        team_id="team_test",
        idempotency_key="browser-action-0001",
        intent=CreateRequirementIntent(
            project_id="project_test",
            name="Web delivery",
            repository_roots=(str(tmp_path),),
        ),
        requested_at=at,
    )
    running = queued.transition(
        ConsoleOperationStatus.RUNNING, updated_at=at + timedelta(seconds=1)
    )
    succeeded = running.transition(
        ConsoleOperationStatus.SUCCEEDED,
        updated_at=at + timedelta(seconds=2),
        result=ConsoleCommandResult(
            project_id="project_test",
            delivery_id="delivery_multi_" + "a" * 40,
            checkpoint_sha256="1" * 64,
            stage="READY_FOR_DISCUSSION",
            next_action="Discuss the requirement.",
        ),
    )

    for operation in (queued, running, succeeded):
        _assert_valid(operation.to_wire(), "console-operation.schema.json")

    product_reply = ConsoleOperation.queued(
        team_id="team_test",
        idempotency_key="browser-action-reply-0001",
        intent=ProductReplyIntent(
            project_id="project_test",
            delivery_id="delivery_multi_" + "a" * 40,
            expected_checkpoint_sha256="2" * 64,
            screenshot_ids=("requirement_attachment_" + "b" * 40,),
        ),
        requested_at=at,
    )
    _assert_valid(product_reply.to_wire(), "console-operation.schema.json")

    update_requirement = ConsoleOperation.queued(
        team_id="team_test",
        idempotency_key="browser-action-update-0001",
        intent=UpdateRequirementIntent(
            project_id="project_test",
            delivery_id="delivery_multi_" + "a" * 40,
            expected_checkpoint_sha256="2" * 64,
            name="Updated delivery",
            repository_roots=(str(tmp_path),),
        ),
        requested_at=at,
    )
    delete_requirement = ConsoleOperation.queued(
        team_id="team_test",
        idempotency_key="browser-action-delete-0001",
        intent=DeleteRequirementIntent(
            project_id="project_test",
            delivery_id="delivery_multi_" + "a" * 40,
            expected_checkpoint_sha256="2" * 64,
        ),
        requested_at=at,
    )
    _assert_valid(update_requirement.to_wire(), "console-operation.schema.json")
    _assert_valid(delete_requirement.to_wire(), "console-operation.schema.json")
    close_requirement = ConsoleOperation.queued(
        team_id="team_test",
        idempotency_key="browser-action-close-0001",
        intent=CloseRequirementIntent(
            project_id="project_test",
            delivery_id="delivery_multi_" + "a" * 40,
            expected_checkpoint_sha256="2" * 64,
        ),
        requested_at=at,
    )
    _assert_valid(close_requirement.to_wire(), "console-operation.schema.json")

    missing_reply_content = product_reply.to_wire()
    intent = missing_reply_content["intent"]
    assert isinstance(intent, dict)
    intent["screenshot_ids"] = []
    _assert_invalid(missing_reply_content, "console-operation.schema.json")


def test_console_operation_schema_rejects_relative_roots_and_incoherent_status(
    tmp_path: Path,
) -> None:
    operation = ConsoleOperation.queued(
        team_id="team_test",
        idempotency_key="browser-action-0001",
        intent=CreateRequirementIntent(
            project_id="project_test",
            name="Web delivery",
            repository_roots=(str(tmp_path),),
        ),
        requested_at=datetime(2026, 9, 12, tzinfo=UTC),
    ).to_wire()
    intent = operation["intent"]
    assert isinstance(intent, dict)
    intent["repository_roots"] = ["relative/project"]
    _assert_invalid(operation, "console-operation.schema.json")

    operation = ConsoleOperation.queued(
        team_id="team_test",
        idempotency_key="browser-action-0002",
        intent=CreateRequirementIntent(
            project_id="project_test",
            name="Web delivery",
            repository_roots=(str(tmp_path),),
        ),
        requested_at=datetime(2026, 9, 12, tzinfo=UTC),
    ).to_wire()
    operation["status"] = "SUCCEEDED"
    _assert_invalid(operation, "console-operation.schema.json")

    operation = ConsoleOperation.queued(
        team_id="team_test",
        idempotency_key="browser-action-0003",
        intent=CreateRequirementIntent(
            project_id="project_test",
            name="Web delivery",
            repository_roots=(str(tmp_path),),
        ),
        requested_at=datetime(2026, 9, 12, tzinfo=UTC),
    ).to_wire()
    operation["status"] = "RUNNING"
    _assert_invalid(operation, "console-operation.schema.json")
