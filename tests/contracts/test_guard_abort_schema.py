"""Additive fixed guard reasons retain old wire/digests and survive fresh Schema generation."""

import json
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator

from ai_software_engineer.agents.execution import ExecutionAbortReason, NativeProcessStop
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.domain.model import JsonValue, WirePayload
from ai_software_engineer.orchestration.continuation_models import ExecutionCaptureStop
from ai_software_engineer.recovery.models import digest
from tests.contracts.test_owned_session_stop_schema import _stop

ROOT = Path(__file__).resolve().parents[2]


def _old_body() -> WirePayload:
    return {
        "kind": "execution_capture_stop",
        "schema_version": "v1",
        "task_id": "task_guard_contract",
        "run_id": "run_guard_contract",
        "capture_start_sha256": "b" * 64,
        "process_stop": _stop().to_wire(),
        "output_present": False,
    }


def _guard_stop() -> ExecutionCaptureStop:
    return ExecutionCaptureStop.create(
        **_old_body(),
        original_error_code=AgentErrorCode.WORK_INTERRUPTED,
        execution_abort_reason=ExecutionAbortReason(detail="local_expiry"),
    )


def test_absent_or_null_abort_reason_preserves_original_bytes_and_nested_digest() -> None:
    body = _old_body()
    old_wire = {**body, "observation_sha256": digest(body)}
    stop = ExecutionCaptureStop.model_validate(old_wire)
    stop.validate_integrity()
    assert stop.to_wire() == old_wire
    assert stop.execution_abort_reason is None
    old_dump = {**old_wire, "cause": None, "original_error_code": None}
    assert stop.model_dump(mode="json") == old_dump
    with_null = ExecutionCaptureStop.model_validate({**old_wire, "execution_abort_reason": None})
    assert with_null.to_wire() == old_wire
    assert with_null.recompute_sha256() == stop.observation_sha256
    assert digest({"capture_stop": stop.model_dump(mode="json")}) == digest(
        {"capture_stop": old_dump}
    )


@pytest.mark.parametrize(
    "detail", [None, "local_expiry", "renewal_exception", "heartbeat_stop_timeout"]
)
def test_safe_reason_values_satisfy_typed_and_static_schemas(detail: str | None) -> None:
    reason = ExecutionAbortReason.model_validate(
        {"kind": "lease_authority_unconfirmed", "detail": detail}
    )
    stop = ExecutionCaptureStop.create(
        **_old_body(), original_error_code="WORK_INTERRUPTED", execution_abort_reason=reason
    )
    stop.validate_integrity()
    published = json.loads((ROOT / "schemas/execution-capture.schema.json").read_text())
    for schema in (published, ExecutionCaptureStop.model_json_schema()):
        assert not list(Draft202012Validator(schema).iter_errors(stop.to_wire()))


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "provider_error"},
        {"detail": "mysql://private:secret@localhost/database"},
        {"detail": "Exception: network down"},
        {"message": "secret"},
        {"exception": {"dsn": "secret"}},
        {"traceback": "secret"},
    ],
)
def test_safe_reason_rejects_free_text_or_unknown_fields(changes: dict[str, JsonValue]) -> None:
    payload = {"kind": "lease_authority_unconfirmed", **changes}
    with pytest.raises(ValueError):
        ExecutionAbortReason.model_validate(payload)
    assert list(Draft202012Validator(ExecutionAbortReason.model_json_schema()).iter_errors(payload))


@pytest.mark.parametrize(
    "field,value", [("cause", "provider_transient"), ("original_error_code", "PROVIDER_ERROR")]
)
def test_guard_reason_is_not_a_provider_failure(field: str, value: JsonValue) -> None:
    payload = {**_guard_stop().to_wire(), field: value}
    with pytest.raises(ValueError):
        ExecutionCaptureStop.model_validate(payload)
    for schema in (
        ExecutionCaptureStop.model_json_schema(),
        json.loads((ROOT / "schemas/execution-capture.schema.json").read_text()),
    ):
        assert list(Draft202012Validator(schema).iter_errors(payload))


def test_guard_reason_requires_complete_real_owned_session_stop() -> None:
    stop = _stop()
    old_stop = NativeProcessStop.create(**stop.model_dump(exclude={"session_proof", "stop_sha256"}))
    payload = {**_guard_stop().to_wire(), "process_stop": old_stop.to_wire()}
    with pytest.raises(ValueError):
        ExecutionCaptureStop.model_validate(payload)
    schema = cast(dict[str, JsonValue], ExecutionCaptureStop.model_json_schema())
    assert list(Draft202012Validator(schema).iter_errors(payload))
