"""Independent runtime-only capacity wire guards, regeneration and legacy digests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
from ai_software_engineer.web_console.models import ProposeExecutionBaselineIntent
from tests.contracts.test_repair_schema_generation import (
    generated_bundle as generated_bundle,
)
from tests.contracts.test_repair_schema_generation import (
    standalone_regenerated as standalone_regenerated,
)
from tests.manager.test_completed_output_rescue import public_input
from tests.manager.test_execution_baseline import authorize, setup

ROOT = Path(__file__).resolve().parents[2]
PURPOSE = "context_capacity_resume"


@pytest.fixture(scope="module")
def legacy_binding(tmp_path_factory: pytest.TempPathFactory) -> ExecutionBaselineBinding:
    # A genuine existing source-rebind binding is the compatibility input; these
    # schema tests never use the capacity receipt sentinel as operational proof.
    fixture = setup(tmp_path_factory.mktemp("capacity-schema-legacy-binding"))
    plan = fixture.service.propose(fixture.target)
    return fixture.service.execute(plan.plan_sha256, authority=authorize(plan))


@pytest.fixture(scope="module")
def capacity_binding(legacy_binding: ExecutionBaselineBinding) -> ExecutionBaselineBinding:
    values = legacy_binding.to_wire()
    values.pop("binding_sha256")
    values.update(
        purpose=PURPOSE,
        continuation_mode="pause",
        context_capacity_receipt_sha256="c" * 64,
        execution_base_ref=legacy_binding.prior_execution_base_ref,
        execution_source_revision=legacy_binding.prior_source_revision,
        superseded_implementation_artifact_id=None,
        superseded_progress_artifact_id=None,
        after_inventory_sha256=legacy_binding.before_inventory_sha256,
    )
    return ExecutionBaselineBinding.create(**values)


def _documents(
    generated: bool,
    standalone: dict[str, Any],
    repair: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if generated:
        return {**standalone, **repair}
    return {path.name: json.loads(path.read_text()) for path in (ROOT / "schemas").glob("*.json")}


def _nodes(documents: dict[str, Any], model: str) -> dict[str, Any]:
    return {
        filename: document if document.get("title") == model else document["$defs"][model]
        for filename, document in documents.items()
        if document.get("title") == model or model in document.get("$defs", {})
    }


@pytest.mark.parametrize("generated", [False, True])
def test_capacity_proposal_has_no_caller_target_and_preserves_old_source_rebind_command(
    generated_bundle: dict[str, dict[str, Any]], generated: bool
) -> None:
    document = (
        generated_bundle["console-operation.schema.json"]
        if generated
        else json.loads((ROOT / "schemas/console-operation.schema.json").read_text())
    )
    validator = Draft202012Validator(
        {"$defs": document["$defs"], "$ref": "#/$defs/ProposeExecutionBaselineIntent"}
    )
    wire = {**public_input(), "purpose": PURPOSE}
    intent = ProposeExecutionBaselineIntent.model_validate(wire)
    assert intent.target_base_ref is None and "target_base_ref" not in intent.to_wire()
    validator.validate(wire)
    # Explicit null remains the existing optional-field compatibility spelling;
    # neither spelling gives the caller authority to name a target Git revision.
    validator.validate({**wire, "target_base_ref": None})
    ProposeExecutionBaselineIntent.model_validate({**wire, "target_base_ref": None})
    for bad in (
        {"target_base_ref": "d" * 40},
        {"input_mode": "coder_reapply"},
        {"purpose": "source_rebind"},
        {"purpose": "legacy_workspace_rescue"},
    ):
        assert not validator.is_valid({**wire, **bad})
        with pytest.raises(ValidationError):
            ProposeExecutionBaselineIntent.model_validate({**wire, **bad})
    source = {**wire, "purpose": "source_rebind", "target_base_ref": "d" * 40}
    validator.validate(source)
    ProposeExecutionBaselineIntent.model_validate(source)


@pytest.mark.parametrize("generated", [False, True])
def test_every_capacity_plan_graph_requires_claimed_receipt_without_new_reservation(
    standalone_regenerated: dict[str, Any],
    generated_bundle: dict[str, dict[str, Any]],
    generated: bool,
) -> None:
    documents = _documents(generated, standalone_regenerated, generated_bundle)
    nodes = _nodes(documents, "ExecutionBaselinePlan")
    assert {"execution-baseline-plan.schema.json", "console-operation.schema.json"} <= nodes.keys()
    valid: dict[str, Any] = {
        "purpose": PURPOSE,
        "input_mode": "preserve_draft",
        "conflicted": False,
        "facts": {
            "context_capacity_receipt_sha256": "c" * 64,
            "continuation": {"retry_cause": "uninvoked", "reservation_already_applied": True},
        },
    }
    for filename, node in nodes.items():
        gate = Draft202012Validator({"allOf": node.get("allOf", [])})
        assert gate.is_valid(valid), filename
        replacements: tuple[dict[str, Any], ...] = (
            {"input_mode": "coder_reapply"},
            {"conflicted": True},
            {"facts": {"continuation": valid["facts"]["continuation"]}},
            {"facts": {**valid["facts"], "context_capacity_receipt_sha256": None}},
            {"facts": {**valid["facts"], "continuation": None}},
            {
                "facts": {
                    **valid["facts"],
                    "continuation": {
                        "retry_cause": "provider_transient",
                        "reservation_already_applied": True,
                    },
                }
            },
            {
                "facts": {
                    **valid["facts"],
                    "continuation": {
                        "retry_cause": "uninvoked",
                        "reservation_already_applied": False,
                    },
                }
            },
            *(
                {"facts": {**valid["facts"], field: {}}}
                for field in (
                    "legacy_containment",
                    "completed_output",
                    "stopped_provider_failure",
                    "native_rule_change",
                )
            ),
        )
        for replacement in replacements:
            assert not gate.is_valid({**valid, **replacement}), (filename, replacement)


@pytest.mark.parametrize("generated", [False, True])
def test_every_capacity_binding_graph_requires_explicit_purpose_pause_and_preserved_inputs(
    standalone_regenerated: dict[str, Any],
    generated_bundle: dict[str, dict[str, Any]],
    capacity_binding: ExecutionBaselineBinding,
    generated: bool,
) -> None:
    documents = _documents(generated, standalone_regenerated, generated_bundle)
    nodes = _nodes(documents, "ExecutionBaselineBinding")
    assert {
        "execution-baseline.schema.json",
        "execution-baseline-queue-consumption.schema.json",
        "execution-baseline-queue-release.schema.json",
        "console-operation.schema.json",
    } <= nodes.keys()
    valid = capacity_binding.to_wire()
    for filename, node in nodes.items():
        validator = Draft202012Validator({**node, "$defs": documents[filename].get("$defs", {})})
        validator.validate(valid)
        for replacements in (
            {"context_capacity_receipt_sha256": None},
            {"continuation_mode": "resume"},
            {"input_mode": "coder_reapply"},
            {"authority_source": "organization_engineering_policy"},
            {"purpose": "source_rebind"},
            {"legacy_containment_sha256": "d" * 64},
            {"completed_output_sha256": "d" * 64},
            {"stopped_provider_failure_sha256": "d" * 64},
            {"superseded_implementation_artifact_id": "art_old_impl"},
            {"superseded_progress_artifact_id": "art_old_progress"},
        ):
            bad = {**valid, **replacements}
            assert not validator.is_valid(bad), (filename, replacements)
            with pytest.raises(ValidationError):
                ExecutionBaselineBinding.model_validate(bad)
        for field in ("purpose", "context_capacity_receipt_sha256"):
            bad = {key: value for key, value in valid.items() if key != field}
            assert not validator.is_valid(bad), (filename, field)
            with pytest.raises(ValidationError):
                ExecutionBaselineBinding.model_validate(bad)


@pytest.mark.parametrize(
    "field", ["execution_base_ref", "execution_source_revision", "after_inventory_sha256"]
)
def test_capacity_binding_runtime_rejects_cross_field_source_or_inventory_changes(
    capacity_binding: ExecutionBaselineBinding, field: str
) -> None:
    # JSON Schema cannot compare two arbitrary string properties; the runtime
    # validator owns those equalities rather than advertising an unenforced gate.
    replacement = "d" * (64 if field.endswith("sha256") else 40)
    with pytest.raises(ValidationError, match="容量恢复"):
        ExecutionBaselineBinding.model_validate({**capacity_binding.to_wire(), field: replacement})


def test_legacy_binding_absent_or_null_capacity_field_keeps_exact_serialization_and_digest(
    legacy_binding: ExecutionBaselineBinding,
) -> None:
    old = legacy_binding.to_wire()
    assert "context_capacity_receipt_sha256" not in old
    original_bytes = json.dumps(
        old, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    for value in (old, {**old, "context_capacity_receipt_sha256": None}):
        restored = ExecutionBaselineBinding.model_validate(value)
        restored.validate_integrity()
        assert restored.binding_sha256 == legacy_binding.binding_sha256
        assert restored.recompute_sha256() == legacy_binding.recompute_sha256()
        assert restored.to_wire() == old
        assert (
            json.dumps(
                restored.to_wire(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
            == original_bytes
        )


def test_fresh_capacity_guards_and_shape_match_every_published_embedding(
    standalone_regenerated: dict[str, Any], generated_bundle: dict[str, dict[str, Any]]
) -> None:
    fresh = _documents(True, standalone_regenerated, generated_bundle)
    published = _documents(False, {}, {})
    for model in (
        "ProposeExecutionBaselineIntent",
        "ExecutionBaselinePlan",
        "ExecutionBaselineBinding",
    ):
        expected, actual = _nodes(published, model), _nodes(fresh, model)
        assert expected.keys() == actual.keys(), model
        for filename, node in expected.items():
            assert node == actual[filename], (model, filename)
