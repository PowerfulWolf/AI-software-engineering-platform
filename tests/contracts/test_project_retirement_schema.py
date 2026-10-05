"""Project retirement wire schemas retain the exact typed command and audit receipt."""

import json
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import TypeAdapter

from ai_software_engineer.domain.model import JsonValue, WirePayload
from ai_software_engineer.project_retirement import (
    ProjectArchiveEntry,
    ProjectRetirementReceipt,
    RetireEmptyProject,
)
from tests.manager.test_project_retirement import _command, _project, _retire

SCHEMA_PATH = Path(__file__).parents[2] / "schemas" / "project-retirement.schema.json"


def _schema() -> dict[str, object]:
    return cast(dict[str, object], json.loads(SCHEMA_PATH.read_text()))


def _errors(payload: WirePayload) -> list[str]:
    return [
        error.message
        for error in Draft202012Validator(_schema(), format_checker=FormatChecker()).iter_errors(
            payload
        )
    ]


def test_command_and_receipt_wire_schema_match_the_complete_typed_contract(tmp_path: Path) -> None:
    schema = _schema()
    Draft202012Validator.check_schema(schema)
    expected = TypeAdapter(RetireEmptyProject | ProjectRetirementReceipt).json_schema()
    assert {
        key: value for key, value in schema.items() if key not in {"$schema", "$id"}
    } == expected
    project = _project(tmp_path)
    command = _command(project)
    receipt = _retire(project)
    for model in (command, receipt):
        assert not _errors(model.to_wire())
    assert RetireEmptyProject.model_validate(command.to_wire()) == command
    assert ProjectRetirementReceipt.model_validate(receipt.to_wire()) == receipt
    receipt.validate_integrity()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_id", "../retired"),
        ("expected_manifest_sha256", "not-a-sha"),
        ("reason", ""),
        ("submitted_at", "2026-10-05T08:00:00"),
        ("idle", True),
        ("principal", {"operator_id": "request-controlled"}),
    ],
)
def test_command_schema_rejects_stale_shape_and_request_controlled_authority(
    tmp_path: Path, field: str, value: JsonValue
) -> None:
    payload = {**_command(_project(tmp_path)).to_wire(), field: value}
    assert _errors(payload)
    with pytest.raises(ValueError):
        RetireEmptyProject.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [("schema_version", "v2"), ("inventory", []), ("retirement_sha256", "missing"), ("idle", True)],
)
def test_receipt_schema_rejects_missing_audit_or_unknown_fields(
    tmp_path: Path, field: str, value: JsonValue
) -> None:
    payload = {**_retire(_project(tmp_path)).to_wire(), field: value}
    assert _errors(payload)
    with pytest.raises(ValueError):
        ProjectRetirementReceipt.model_validate(payload)


@pytest.mark.parametrize("path", [".", "..", "../outside", "/absolute", "a//b", "a/./b", "a\\b"])
def test_typed_inventory_rejects_noncanonical_or_escaping_paths(path: str) -> None:
    with pytest.raises(ValueError):
        ProjectArchiveEntry(path=path, kind="file", mode=0o600, bytes=1, sha256="a" * 64)
