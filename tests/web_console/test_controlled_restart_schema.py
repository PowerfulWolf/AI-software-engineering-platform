"""Static local lifecycle schemas stay in sync with the typed service boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ai_software_engineer.web_console.service_lifecycle import (
    ServiceInstance,
    ServiceShutdownRequest,
    ServiceShutdownResult,
)


@pytest.mark.parametrize(
    ("filename", "model"),
    (
        ("console-service-instance.schema.json", ServiceInstance),
        ("console-service-shutdown-request.schema.json", ServiceShutdownRequest),
        ("console-service-shutdown-result.schema.json", ServiceShutdownResult),
    ),
)
def test_static_lifecycle_schema_matches_typed_boundary(
    filename: str, model: type[ServiceInstance | ServiceShutdownRequest | ServiceShutdownResult]
) -> None:
    schema = json.loads((Path(__file__).parents[2] / "schemas" / filename).read_text())
    Draft202012Validator.check_schema(schema)
    schema.pop("$schema")
    schema.pop("$id")
    assert schema == model.model_json_schema()
