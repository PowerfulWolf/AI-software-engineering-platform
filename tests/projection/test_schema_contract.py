"""Projection wire payloads remain aligned with Draft 2020-12 schemas."""

from collections.abc import Mapping

from jsonschema import Draft202012Validator

from ai_software_engineer.projection import ProjectionFacts, RunProjectionBuilder
from ai_software_engineer.read_api import ReadOnlyProjectionApi
from tests.contracts.test_json_schema_contracts import REGISTRY, SCHEMAS
from tests.domain.factories import make_task


def _assert_valid(payload: Mapping[str, object], schema_name: str) -> None:
    validator = Draft202012Validator(SCHEMAS[schema_name], registry=REGISTRY)
    assert sorted(error.message for error in validator.iter_errors(payload)) == []


def test_empty_projection_snapshot_satisfies_schema() -> None:
    snapshot = RunProjectionBuilder().build(ProjectionFacts(tasks=(make_task(),)))
    _assert_valid(snapshot.to_wire(), "projection-snapshot.schema.json")
    _assert_valid(snapshot.tasks[0].to_wire(), "projection-task.schema.json")


def test_read_api_list_payload_contains_schema_version_and_typed_item() -> None:
    snapshot = RunProjectionBuilder().build(ProjectionFacts(tasks=(make_task(),)))
    response = ReadOnlyProjectionApi(snapshot).list_tasks()
    assert response.status_code == 200
    assert response.payload["schema_version"] == "v0.1"
    items = response.payload["items"]
    assert isinstance(items, list)
    _assert_valid(items[0], "projection-task.schema.json")
