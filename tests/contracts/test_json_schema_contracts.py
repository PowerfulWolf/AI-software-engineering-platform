"""Keep Python domain payloads aligned with the canonical Draft 2020-12 schemas."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from ai_software_engineer.context import ContextBudget, ContextSource, FileContextBuilder
from ai_software_engineer.domain import AgentPermissions, AgentRole, NetworkAccess
from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.evaluation import HandoffBuilder
from ai_software_engineer.runtime import RuntimeConfig
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
