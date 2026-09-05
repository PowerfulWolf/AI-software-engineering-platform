"""Strict structured-output Schema compatibility tests."""

from typing import cast

from ai_software_engineer.agents.json_schema import strict_output_schema
from ai_software_engineer.project_manager.production_agents import ProductDraft


def test_strict_schema_requires_every_property_recursively_without_mutating_source() -> None:
    source = ProductDraft.model_json_schema()

    strict = strict_output_schema(source)
    properties = cast(dict[str, object], strict["properties"])
    definitions = cast(dict[str, object], strict["$defs"])
    acceptance = cast(dict[str, object], definitions["AcceptanceDraft"])
    acceptance_properties = cast(dict[str, object], acceptance["properties"])

    assert "questions" not in source["required"]
    assert strict["required"] == list(properties)
    assert strict["additionalProperties"] is False
    assert acceptance["required"] == list(acceptance_properties)
    assert "test_ids" in acceptance["required"]
    assert acceptance["additionalProperties"] is False
    test_ids = cast(dict[str, object], acceptance_properties["test_ids"])
    assert "default" not in test_ids


def test_strict_schema_preserves_arrays_refs_and_scalar_constraints() -> None:
    strict = strict_output_schema(ProductDraft.model_json_schema())
    properties = cast(dict[str, object], strict["properties"])
    requirements = cast(dict[str, object], properties["requirements"])
    action = cast(dict[str, object], properties["action"])

    assert requirements["type"] == "array"
    assert requirements["items"] == {"$ref": "#/$defs/RequirementDraft"}
    assert action["enum"] == ["clarify", "ready"]
