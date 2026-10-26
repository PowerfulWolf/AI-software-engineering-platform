"""Published and freshly generated UNKNOWN settlement graphs keep exact stop gates."""

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator

from ai_software_engineer.domain.delivery_resolution import HandleDeliveryWait
from ai_software_engineer.domain.stopped_unknown_budget import StoppedUnknownBudgetSettlement
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from tests.manager.test_completed_output_checkpoint import CompletedFixture
from tests.manager.test_completed_output_checkpoint import completed as completed_fixture
from tests.manager.test_stopped_unknown_budget import service_for

ROOT = Path(__file__).resolve().parents[2]
completed = completed_fixture


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("unknown-settlement-schema")
    scripts = root / "scripts"
    scripts.mkdir()
    schemas = root / "schemas"
    schemas.mkdir()
    for name in ("sync-stopped-unknown-budget-schema.py", "sync-legacy-rescue-schemas.py"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    shutil.copyfile(
        ROOT / "schemas/engineering-wait-resolution.schema.json",
        schemas / "engineering-wait-resolution.schema.json",
    )
    command = (sys.executable, str(scripts / "sync-stopped-unknown-budget-schema.py"))
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, timeout=60)
    path = schemas / "stopped-unknown-budget-settlement.schema.json"
    first = path.read_bytes()
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, timeout=60)
    assert path.read_bytes() == first
    published = (ROOT / "schemas/stopped-unknown-budget-settlement.schema.json").read_bytes()
    assert first == published
    return json.loads(first)  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    "completed", ["stopped_unknown_exhausted", "stopped_unknown_completed_exhausted"], indirect=True
)
def test_settlement_schema_keeps_unknown_and_the_real_v1_v2_stop(
    completed: CompletedFixture, regenerated: dict[str, Any]
) -> None:
    f = completed
    service = service_for(f)
    result = service.handle(HandleDeliveryWait.model_validate(f.queue.command().to_wire()))
    assert result.budget_settlement_sha256 is not None
    record = KnowledgeRecordStore(f.root / "delivery-preflight", read_only=True).get(
        "stopped-unknown-budget-settlements",
        result.budget_settlement_sha256,
        StoppedUnknownBudgetSettlement,
    )
    wire = record.to_wire()
    validator = Draft202012Validator(regenerated)
    validator.validate(wire)
    invalid = cast(dict[str, Any], deepcopy(wire))
    cast(dict[str, Any], invalid["event"])["to_status"] = "DONE"
    assert not validator.is_valid(invalid)
    invalid = cast(dict[str, Any], deepcopy(wire))
    cast(dict[str, Any], invalid["investigation"])["invocation_outcome_sha256"] = "a" * 64
    assert not validator.is_valid(invalid)
    invalid = cast(dict[str, Any], deepcopy(wire))
    cast(dict[str, Any], cast(dict[str, Any], invalid["stopped_execution"])["capture_stop"])[
        "output_present"
    ] = not record.stopped_execution.capture_stop.output_present
    assert not validator.is_valid(invalid)
