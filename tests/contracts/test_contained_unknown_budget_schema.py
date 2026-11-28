"""Published start-only settlement Schema retains exact UNKNOWN and human gates."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from runpy import run_path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.manager.test_completed_output_checkpoint import completed as completed_fixture

ROOT = Path(__file__).resolve().parents[2]
completed = completed_fixture


def test_local_stop_embedded_schemas_keep_pair_guard_and_regenerate_idempotently() -> None:
    synchronize = run_path(str(ROOT / "scripts/sync-contained-unknown-contracts.py"))["synchronize"]
    base = {
        "work_item_id": "work_exact",
        "expected_disposition_sha256": "a" * 64,
        "expected_task_intent_sha256": "b" * 64,
        "expected_source_revision": "c" * 40,
        "expected_checkpoint_sequence": 1,
        "project_id": "project_exact",
        "delivery_id": "delivery_exact",
        "expected_checkpoint_sha256": "d" * 64,
        "action": "HANDLE_DELIVERY_WAIT",
    }
    for name in (
        "engineering-wait-resolution.schema.json",
        "console-operation.schema.json",
        "console-deletion-cleanup.schema.json",
    ):
        schema = json.loads((ROOT / "schemas" / name).read_text())
        assert synchronize(schema) == schema
        investigation = schema["$defs"]["DeliveryWaitInvestigation"]
        assert "local_stop_confirmation_available" in investigation["properties"]
        assert any(
            guard.get("if", {}).get("properties", {}).get("local_stop_confirmation_available")
            == {"const": True}
            for guard in investigation["allOf"]
        )
        if "HandleDeliveryWaitIntent" not in schema["$defs"]:
            continue
        validator = Draft202012Validator(
            {"$defs": schema["$defs"], "$ref": "#/$defs/HandleDeliveryWaitIntent"}
        )
        validator.validate(base)
        confirmed = {
            **base,
            "confirm_local_execution_stopped": True,
            "local_stop_reference": "call_a7e4ebe2aed34bad899f8cc3588da3b5",
        }
        validator.validate(confirmed)
        for invalid in (
            {**base, "confirm_local_execution_stopped": True},
            {**base, "local_stop_reference": confirmed["local_stop_reference"]},
            {**confirmed, "local_stop_reference": "free text"},
        ):
            assert not validator.is_valid(invalid), (name, invalid)


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("contained-unknown-schema")
    scripts = root / "scripts"
    scripts.mkdir()
    schemas = root / "schemas"
    schemas.mkdir()
    for name in ("sync-contained-unknown-budget-schema.py", "sync-legacy-rescue-schemas.py"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    shutil.copyfile(
        ROOT / "schemas/engineering-wait-resolution.schema.json",
        schemas / "engineering-wait-resolution.schema.json",
    )
    command = (sys.executable, str(scripts / "sync-contained-unknown-budget-schema.py"))
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, timeout=60)
    path = schemas / "contained-unknown-budget-settlement.schema.json"
    first = path.read_bytes()
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, timeout=60)
    assert path.read_bytes() == first
    assert first == (ROOT / "schemas/contained-unknown-budget-settlement.schema.json").read_bytes()
    return json.loads(first)  # type: ignore[no-any-return]
