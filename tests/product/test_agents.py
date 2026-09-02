"""Offline Product Agent adapter and wire-contract tests."""

import json
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError
from referencing import Registry, Resource

from ai_software_engineer.product.agents import (
    FakeProductAgentAdapter,
    FakeProductBehavior,
    FakeProductScenario,
    ProductAgentErrorCode,
    ProductAgentRequest,
    ProductAgentRequestConflict,
    ProductAgentResult,
    ProductAgentRunStatus,
    ProductClarification,
)
from ai_software_engineer.product.context import ProductContextBuilder
from tests.product.factories import prepared_product_facts
from tests.project_manager.test_contracts import NOW, product_spec, request

SCHEMA_DIR = Path(__file__).parents[2] / "schemas"


def _request(tmp_path: Path, *, run_id: str = "run_product_001") -> ProductAgentRequest:
    prepared, profile, baseline = prepared_product_facts(
        tmp_path, project_id="project_delivery_001"
    )
    project_request = request(prepared)
    context = ProductContextBuilder().build(
        prepared, profile, baseline, project_request, built_at=NOW
    )
    return ProductAgentRequest(
        run_id=run_id,
        project_id=prepared.project_id,
        request_id=project_request.id,
        context=context,
    )


def _schema_registry() -> tuple[dict[str, dict[str, object]], Registry]:
    schemas: dict[str, dict[str, object]] = {}
    resources: list[tuple[str, Resource[object]]] = []
    for path in SCHEMA_DIR.glob("*.schema.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        schema = cast(dict[str, object], payload)
        schemas[path.name] = schema
        resources.append((cast(str, schema["$id"]), Resource.from_contents(schema)))
    return schemas, Registry().with_resources(resources)


def test_fake_clarifies_and_exact_run_replay_is_stable(tmp_path: Path) -> None:
    agent_request = _request(tmp_path)
    clarification = ProductClarification(
        summary="One product decision is still missing.",
        questions=("Must the first release support multiple repositories?",),
    )
    adapter = FakeProductAgentAdapter(
        default=FakeProductScenario(
            behavior=FakeProductBehavior.CLARIFY,
            clarification=clarification,
        )
    )

    first = adapter.run(agent_request)
    replay = adapter.run(agent_request)

    assert replay is first
    assert first.status is ProductAgentRunStatus.SUCCEEDED
    assert first.clarification == clarification
    assert first.product_spec is None
    assert first.error is None


def test_fake_ready_validates_exact_context_lineage(tmp_path: Path) -> None:
    agent_request = _request(tmp_path)
    ready = product_spec(agent_request.context.project_request)
    adapter = FakeProductAgentAdapter(
        default=FakeProductScenario(
            behavior=FakeProductBehavior.READY,
            product_spec=ready,
        )
    )

    result = adapter.run(agent_request)

    assert result.status is ProductAgentRunStatus.SUCCEEDED
    assert result.product_spec == ready
    assert result.context_id == agent_request.context.context_id


@pytest.mark.parametrize(
    ("behavior", "status", "code", "transient"),
    (
        (
            FakeProductBehavior.TIMEOUT,
            ProductAgentRunStatus.TIMED_OUT,
            ProductAgentErrorCode.TIMEOUT,
            True,
        ),
        (
            FakeProductBehavior.INVALID_OUTPUT,
            ProductAgentRunStatus.FAILED,
            ProductAgentErrorCode.INVALID_OUTPUT,
            False,
        ),
        (
            FakeProductBehavior.PROVIDER_ERROR,
            ProductAgentRunStatus.FAILED,
            ProductAgentErrorCode.PROVIDER_ERROR,
            True,
        ),
    ),
)
def test_fake_has_typed_failure_routes(
    tmp_path: Path,
    behavior: FakeProductBehavior,
    status: ProductAgentRunStatus,
    code: ProductAgentErrorCode,
    transient: bool,
) -> None:
    result = FakeProductAgentAdapter(default=FakeProductScenario(behavior=behavior)).run(
        _request(tmp_path)
    )

    assert result.status is status
    assert result.error is not None
    assert result.error.code is code
    assert result.error.transient is transient
    assert result.clarification is None
    assert result.product_spec is None


def test_fake_maps_wrong_spec_version_to_invalid_output(tmp_path: Path) -> None:
    agent_request = _request(tmp_path)
    ready = product_spec(agent_request.context.project_request)
    wrong_version = ready.model_copy(update={"version": 2})
    adapter = FakeProductAgentAdapter(
        default=FakeProductScenario(
            behavior=FakeProductBehavior.READY,
            product_spec=wrong_version,
        )
    )

    result = adapter.run(agent_request)

    assert result.status is ProductAgentRunStatus.FAILED
    assert result.error is not None
    assert result.error.code is ProductAgentErrorCode.INVALID_OUTPUT
    assert result.product_spec is None


def test_fake_rejects_changed_run_replay(tmp_path: Path) -> None:
    agent_request = _request(tmp_path)
    adapter = FakeProductAgentAdapter(
        default=FakeProductScenario(
            behavior=FakeProductBehavior.CLARIFY,
            clarification=ProductClarification(
                summary="Need an explicit boundary.",
                questions=("What is out of scope?",),
            ),
        )
    )
    adapter.run(agent_request)
    changed = agent_request.model_copy(update={"timeout_seconds": 601})

    with pytest.raises(ProductAgentRequestConflict, match="different request"):
        adapter.run(changed)


def test_request_rejects_context_or_permission_mismatch(tmp_path: Path) -> None:
    agent_request = _request(tmp_path)
    with pytest.raises(ValidationError, match="identity"):
        ProductAgentRequest(
            run_id="run_product_other",
            project_id="project_another_001",
            request_id=agent_request.request_id,
            context=agent_request.context,
        )
    changed_permissions = agent_request.permissions.model_copy(update={"write_code": True})
    with pytest.raises(ValidationError):
        ProductAgentRequest.model_validate(
            {**agent_request.to_wire(), "permissions": changed_permissions.to_wire()}
        )


def test_result_and_scenario_enforce_exclusive_outputs(tmp_path: Path) -> None:
    agent_request = _request(tmp_path)
    clarification = ProductClarification(
        summary="Need more detail.",
        questions=("Which users are in scope?",),
    )
    ready = product_spec(agent_request.context.project_request)

    with pytest.raises(ValidationError, match="exactly one output"):
        ProductAgentResult(
            run_id=agent_request.run_id,
            project_id=agent_request.project_id,
            request_id=agent_request.request_id,
            context_id=agent_request.context.context_id,
            status=ProductAgentRunStatus.SUCCEEDED,
            clarification=clarification,
            product_spec=ready,
        )
    with pytest.raises(ValidationError, match="requires only clarification"):
        FakeProductScenario(
            behavior=FakeProductBehavior.CLARIFY,
            clarification=clarification,
            product_spec=ready,
        )


def test_request_and_results_match_canonical_schema(tmp_path: Path) -> None:
    agent_request = _request(tmp_path)
    schemas, registry = _schema_registry()
    validator = Draft202012Validator(
        schemas["product-agent-run.schema.json"],
        registry=registry,
        format_checker=FormatChecker(),
    )
    clarification = ProductClarification(
        summary="Need the release boundary.",
        questions=("Is migration in scope?",),
    )
    results = (
        FakeProductAgentAdapter(
            default=FakeProductScenario(
                behavior=FakeProductBehavior.CLARIFY,
                clarification=clarification,
            )
        ).run(agent_request),
        FakeProductAgentAdapter(
            default=FakeProductScenario(
                behavior=FakeProductBehavior.READY,
                product_spec=product_spec(agent_request.context.project_request),
            )
        ).run(agent_request),
        FakeProductAgentAdapter(
            default=FakeProductScenario(behavior=FakeProductBehavior.TIMEOUT)
        ).run(agent_request),
    )

    for value in (agent_request, *results):
        errors = list(validator.iter_errors(value.to_wire()))
        assert errors == [], [error.message for error in errors]

    bad = cast(dict[str, object], results[1].to_wire())
    bad["unexpected"] = "not allowed"
    assert list(validator.iter_errors(bad))
