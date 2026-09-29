"""Canonical schemas accept actual Manager receipts, not fabricated success facts."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.manager.model_execution import ManagerContext, ManagerRunRecord
from tests.manager.test_manager_model_execution import executor, invoke, ok


def validator(name: str) -> Draft202012Validator:
    path = Path(__file__).resolve().parents[2] / "schemas" / (name + ".schema.json")
    return Draft202012Validator(json.loads(path.read_text()))


def test_actual_manager_claim_context_and_receipt_match_schema(tmp_path: Path) -> None:
    runner = executor(tmp_path)
    client = Mock()
    client.complete.return_value = ok()
    invoke(runner, client)
    for namespace in ("manager-start", "manager-final"):
        for item in runner.store.list(namespace, ManagerRunRecord):
            validator("manager-model-run").validate(item.to_wire())
    context = runner.store.list("manager-context", ManagerContext)[0]
    validator("manager-model-context").validate(context.to_wire())
    success = runner._history()[0]
    with pytest.raises(ValidationError):
        ManagerRunRecord.model_validate({**success.to_wire(), "result": None})


def test_config_schema_carries_real_manager_and_time_contract() -> None:
    config = ProductionConfig.default().to_wire()
    validator("production-config").validate(config)
    for key in ("initial_seconds", "max_seconds", "max_capacity_timeouts"):
        changed = json.loads(json.dumps(config))
        changed["execution_retry_policy"]["execution_time"]["manager"][key] = 0
        assert not validator("production-config").is_valid(changed)
