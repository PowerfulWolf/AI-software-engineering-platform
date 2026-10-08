"""Additive continuation contracts preserve old Task and diagnostic wire schemas."""

import fcntl
import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from ai_software_engineer.agents.models import AgentResult
from ai_software_engineer.domain.continuation import InterruptionContinuationPolicy
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.model import JsonValue, WirePayload
from ai_software_engineer.domain.task import Task
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationAdmission,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
    ExecutionInterruptionReceipt,
)
from tests.domain.factories import make_task
from tests.orchestration.test_capture_reconciliation import observations
from tests.orchestration.test_continuation_records import make_admission, make_receipt
from tests.orchestration.test_native_continuation import Fixture, Guard

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


def _schema(name: str) -> dict[str, object]:
    return cast(dict[str, object], json.loads((SCHEMAS / name).read_text()))


def _errors(name: str, payload: WirePayload) -> list[str]:
    return [
        error.message
        for error in Draft202012Validator(
            _schema(name), format_checker=FormatChecker()
        ).iter_errors(payload)
    ]


@pytest.fixture
def capture_facts(
    tmp_path: Path,
) -> Iterator[tuple[ExecutionCaptureStart, ExecutionCaptureStop]]:
    descriptor = os.open(tmp_path / "original.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    fixture = Fixture(tmp_path, Guard(descriptor))
    try:
        yield observations(fixture)
    finally:
        fixture.repository.close()
        os.close(descriptor)


def test_policy_and_new_task_satisfy_schema_without_granting_legacy_task() -> None:
    policy = InterruptionContinuationPolicy()
    assert not _errors("interruption-continuation-policy.schema.json", policy.to_wire())
    legacy = make_task()
    task = Task.model_validate(
        {**legacy.to_wire(), "interruption_continuation_policy": policy.to_wire()}
    )
    assert not _errors("task.schema.json", task.to_wire())
    assert not _errors("task.schema.json", legacy.to_wire())
    assert Task.model_validate(legacy.to_wire()).interruption_continuation_policy is None


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", "v2"),
        ("authorization_source", "manager_model"),
        ("capability_id", "unverified_shell"),
        ("max_continuations", 0),
        ("max_continuations", 2),
        ("max_continuations", True),
        ("max_continuations", "1"),
        ("allowed_causes", ["unknown_crash"]),
        ("allowed_causes", ["provider_transient", "local_execution_limit"]),
        ("allowed_changes", ["text_added", "text_modified", "deleted"]),
        ("allowed_changes", ["text_modified", "text_added"]),
        ("can_change_verdict", True),
    ),
)
def test_policy_schema_rejects_authority_expansion(field: str, value: JsonValue) -> None:
    payload = {**InterruptionContinuationPolicy().to_wire(), field: value}
    assert _errors("interruption-continuation-policy.schema.json", payload)
    with pytest.raises(ValueError):
        InterruptionContinuationPolicy.model_validate(payload)


def test_every_nested_task_has_the_identical_optional_frozen_policy_contract() -> None:
    expected = Task.model_json_schema()
    field = "interruption_continuation_policy"
    found: list[str] = []
    for path in SCHEMAS.glob("*.schema.json"):
        schema = _schema(path.name)
        definitions = schema.get("$defs", {})
        assert isinstance(definitions, dict)
        node = definitions.get("Task", schema if path.name == "task.schema.json" else None)
        if node is None:
            continue
        assert isinstance(node, dict)
        properties = node["properties"]
        assert isinstance(properties, dict)
        assert properties[field] == expected["properties"][field], path.name
        assert (
            definitions["InterruptionContinuationPolicy"]
            == expected["$defs"]["InterruptionContinuationPolicy"]
        )
        assert field not in node["required"]
        found.append(path.name)
    assert "task.schema.json" in found
    assert "recovery-task-record.schema.json" in found
    assert "recovery-execution.schema.json" in found


def test_interruption_result_schema_requires_nontransient_failed_output() -> None:
    payload: WirePayload = {
        "run_id": "run_interrupted_001",
        "task_id": "task_interrupted_001",
        "role": "coder",
        "attempt": 1,
        "source_revision": "a" * 40,
        "context_manifest_id": "ctx_" + "b" * 64,
        "status": "FAILED",
        "error": {"code": "WORK_INTERRUPTED", "message": "草稿已保留。", "transient": False},
    }
    assert not _errors("agent-result.schema.json", payload)
    assert AgentResult.model_validate(payload).error is not None
    error = payload["error"]
    assert isinstance(error, dict)
    assert _errors("agent-result.schema.json", {**payload, "error": {**error, "transient": True}})
    assert _errors("agent-result.schema.json", {**payload, "status": "TIMED_OUT"})
    assert _errors("agent-result.schema.json", {**payload, "status": "SUCCEEDED"})


def test_changed_schemas_are_valid_draft_2020_12() -> None:
    for path in SCHEMAS.glob("*.schema.json"):
        schema = _schema(path.name)
        Draft202012Validator.check_schema(schema)


def test_receipt_and_admission_schema_retain_the_separate_durable_fact_kinds(
    tmp_path: Path,
) -> None:
    receipt = make_receipt(tmp_path)
    admission = make_admission(receipt)
    for model in (receipt, admission):
        assert not _errors("execution-continuation.schema.json", model.to_wire())
    wrong = admission.to_wire()
    wrong["authorization_source"] = "human_approval"
    assert _errors("execution-continuation.schema.json", wrong)
    with pytest.raises(ValueError):
        ContinuationAdmission.model_validate(wrong)
    absent_capture = receipt.to_wire()
    absent_capture.pop("capture")
    assert _errors("execution-continuation.schema.json", absent_capture)
    with pytest.raises(ValueError):
        ExecutionInterruptionReceipt.model_validate(absent_capture)
    absent_work_item = receipt.to_wire()
    absent_work_item.pop("original_work_item_id")
    assert _errors("execution-continuation.schema.json", absent_work_item)
    with pytest.raises(ValueError):
        ExecutionInterruptionReceipt.model_validate(absent_work_item)


def test_receipt_schema_uses_existing_capture_model_without_changing_old_contract(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.recovery.models import CapturedChanges

    schema = _schema("execution-continuation.schema.json")
    definitions = schema["$defs"]
    assert isinstance(definitions, dict)
    expected = CapturedChanges.model_json_schema()
    expected.pop("$defs")
    assert definitions["CapturedChanges"] == expected
    receipt = make_receipt(tmp_path)
    malformed = receipt.to_wire()
    malformed["claim_lease_id"] = "run_not_a_lease"
    assert _errors("execution-continuation.schema.json", malformed)
    with pytest.raises(ValueError):
        ExecutionInterruptionReceipt.model_validate(malformed)


def test_capture_schema_accepts_a_complete_owned_start_and_stop(
    capture_facts: tuple[ExecutionCaptureStart, ExecutionCaptureStop],
) -> None:
    start, stop = capture_facts
    assert not _errors("execution-capture.schema.json", start.to_wire())
    assert not _errors("execution-capture.schema.json", stop.to_wire())
    start.validate_integrity()
    stop.validate_integrity()


@pytest.mark.parametrize(
    ("kind", "mutate"),
    (
        (
            "role",
            lambda start, stop: start.model_copy(
                update={"request": start.request.model_copy(update={"role": AgentRole.QA})}
            ),
        ),
        ("cause", lambda start, stop: stop.model_copy(update={"cause": "provider_transient"})),
        (
            "stop_kind",
            lambda start, stop: stop.model_copy(
                update={"process_stop": stop.process_stop.model_copy(update={"kind": "completed"})}
            ),
        ),
    ),
)
def test_capture_schema_and_models_reject_bad_role_cause_and_stop_kind(
    capture_facts: tuple[ExecutionCaptureStart, ExecutionCaptureStop],
    kind: str,
    mutate: Callable[
        [ExecutionCaptureStart, ExecutionCaptureStop],
        ExecutionCaptureStart | ExecutionCaptureStop,
    ],
) -> None:
    start, stop = capture_facts
    changed = mutate(start, stop)
    payload = changed.to_wire()
    assert _errors("execution-capture.schema.json", payload)
    model = ExecutionCaptureStart if kind == "role" else ExecutionCaptureStop
    with pytest.raises(ValueError):
        model.model_validate(payload)
