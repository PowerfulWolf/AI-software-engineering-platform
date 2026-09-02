"""Product-specific context routing and integrity contract tests."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError
from referencing import Registry, Resource

from ai_software_engineer.domain import ProjectPreparation
from ai_software_engineer.product.context import (
    PRODUCT_AGENT_PERMISSIONS,
    ProductContextBuilder,
    ProductContextIntegrityError,
    ProductContextLineageError,
    ProductContextManifest,
    ProductDialogueActor,
    ProductDialogueContextItem,
)
from tests.product.factories import prepared_product_facts
from tests.project_manager.test_contracts import NOW, product_spec, request

SCHEMA_DIR = Path(__file__).parents[2] / "schemas"


def _dialogue() -> tuple[ProductDialogueContextItem, ...]:
    first = ProductDialogueContextItem(
        sequence=1,
        actor=ProductDialogueActor.HUMAN,
        summary="The first release must expose an auditable product intake.",
        dialogue_sha256="d" * 64,
    )
    return (
        first,
        ProductDialogueContextItem(
            sequence=2,
            actor=ProductDialogueActor.PRODUCT_AGENT,
            summary="Clarified the expected review boundary.",
            previous_sha256=first.dialogue_sha256,
            dialogue_sha256="e" * 64,
        ),
    )


def _manifest(tmp_path: Path, *, with_spec: bool = False) -> ProductContextManifest:
    prepared, profile, baseline = prepared_product_facts(
        tmp_path, project_id="project_delivery_001"
    )
    project_request = request(prepared)
    current = product_spec(project_request) if with_spec else None
    return ProductContextBuilder().build(
        prepared,
        profile,
        baseline,
        project_request,
        dialogue=_dialogue(),
        current_product_spec=current,
        built_at=NOW,
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


def test_context_is_task_independent_deterministic_and_fail_closed(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    rebuilt = ProductContextBuilder().build(
        manifest.preparation,
        manifest.project_profile,
        manifest.project_baseline,
        manifest.project_request,
        dialogue=manifest.dialogue,
        built_at=NOW + timedelta(hours=1),
    )

    assert rebuilt.context_id == manifest.context_id
    assert rebuilt.context_sha256 == manifest.context_sha256
    assert rebuilt.built_at != manifest.built_at
    assert manifest.expected_product_spec_version == 1
    assert manifest.expected_supersedes is None
    assert manifest.permissions == PRODUCT_AGENT_PERMISSIONS
    assert manifest.permissions.write_code is False
    assert manifest.permissions.execute_shell is False
    assert manifest.permissions.change_project_state is False
    assert manifest.permissions.approve_product_spec is False
    assert manifest.project_profile.languages[0].language.value == "python"
    assert manifest.project_baseline.rules[0].layer.value == "platform_hard"
    assert manifest.project_baseline.rules[0].field == "safety.self_approval"
    assert not hasattr(manifest, "task_id")
    assert [item.uri for item in manifest.sources[:5]] == [
        "policy://product-agent/v0.1",
        f"preparation://{manifest.project_id}",
        f"project-profile://{manifest.project_id}",
        f"baseline://{manifest.project_id}",
        f"request://{manifest.request_id}",
    ]
    manifest.validate_integrity()


def test_context_routes_current_spec_as_next_version(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, with_spec=True)

    assert manifest.current_product_spec is not None
    assert manifest.expected_product_spec_version == 2
    assert manifest.expected_supersedes == manifest.current_product_spec.id
    assert manifest.sources[-1].uri == f"product-spec://{manifest.current_product_spec.id}"


def test_context_does_not_reuse_aggregate_digest_for_native_source_uris(
    tmp_path: Path,
) -> None:
    base, profile, baseline = prepared_product_facts(tmp_path, project_id="project_delivery_001")
    prepared = ProjectPreparation.create(
        organization_id=base.organization_id,
        project_id=base.project_id,
        project_root=base.project_root,
        project_workspace_root=base.project_workspace_root,
        organization_root=base.organization_root,
        project_profile_sha256=base.project_profile_sha256,
        runtime_binding_sha256=base.runtime_binding_sha256,
        baseline_spec_sha256=base.baseline_spec_sha256,
        baseline_source_uris=("project://rules/AGENTS.md",),
        prepared_at=base.prepared_at,
    )
    manifest = ProductContextBuilder().build(
        prepared,
        profile,
        baseline,
        request(prepared),
        built_at=NOW,
    )

    assert "project://rules/AGENTS.md" not in {source.uri for source in manifest.sources}
    assert (
        next(
            source.sha256
            for source in manifest.sources
            if source.uri == f"baseline://{prepared.project_id}"
        )
        == prepared.baseline_spec_sha256
    )


def test_context_rejects_cross_project_and_broken_dialogue(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    prepared, profile, baseline = prepared_product_facts(
        first_root, project_id="project_delivery_001"
    )
    other_prepared, _, _ = prepared_product_facts(second_root, project_id="project_delivery_002")
    other_request = request(other_prepared)

    with pytest.raises(ProductContextLineageError, match="ProjectRequest"):
        ProductContextBuilder().build(prepared, profile, baseline, other_request, built_at=NOW)

    broken = ProductDialogueContextItem(
        sequence=2,
        actor=ProductDialogueActor.HUMAN,
        summary="This message has no chain head.",
        previous_sha256="a" * 64,
        dialogue_sha256="b" * 64,
    )
    with pytest.raises(ProductContextLineageError, match="contiguous"):
        ProductContextBuilder().build(
            prepared,
            profile,
            baseline,
            request(prepared),
            dialogue=(broken,),
            built_at=NOW,
        )


def test_context_rejects_naive_clock_and_integrity_tamper(tmp_path: Path) -> None:
    prepared, profile, baseline = prepared_product_facts(
        tmp_path, project_id="project_delivery_001"
    )
    project_request = request(prepared)
    with pytest.raises(ProductContextLineageError, match="timezone-aware"):
        ProductContextBuilder().build(
            prepared,
            profile,
            baseline,
            project_request,
            built_at=datetime(2026, 9, 2, 9, 0),
        )

    manifest = ProductContextBuilder().build(
        prepared, profile, baseline, project_request, built_at=NOW
    )
    changed = manifest.model_copy(update={"context_sha256": "f" * 64})
    with pytest.raises(ProductContextIntegrityError, match="identity"):
        changed.validate_integrity()


def test_context_model_and_schema_reject_extra_or_changed_policy(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    schemas, registry = _schema_registry()
    validator = Draft202012Validator(
        schemas["product-context.schema.json"],
        registry=registry,
        format_checker=FormatChecker(),
    )

    assert list(validator.iter_errors(manifest.to_wire())) == []
    bad_wire = manifest.to_wire()
    bad_wire["unexpected"] = True
    assert list(validator.iter_errors(bad_wire))
    with pytest.raises(ValidationError):
        ProductContextManifest.model_validate(bad_wire)

    permissions = manifest.permissions.model_copy(update={"approve_product_spec": True})
    with pytest.raises(ValidationError):
        ProductContextManifest.model_validate(
            {**manifest.to_wire(), "permissions": permissions.to_wire()}
        )
