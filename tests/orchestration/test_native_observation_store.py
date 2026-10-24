"""Independent native counters cannot alter stops or continuation authority."""

import json

import pytest

from ai_software_engineer.agents.native_observation import NativeOutputObservation
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRejected,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.orchestration.native_observation import NativeExecutionObservation
from ai_software_engineer.recovery.models import digest
from tests.orchestration.test_continuation_store import capture_fixture as capture_fixture
from tests.orchestration.test_native_continuation import Fixture

type CaptureFixture = tuple[Fixture, ExecutionCaptureStart, ExecutionCaptureStop]


def output_observation() -> NativeOutputObservation:
    return NativeOutputObservation.model_validate(
        {
            "elapsed_seconds": 2.0,
            "stdout": {
                "raw_bytes": 12,
                "saturated": False,
                "first_byte_seconds": 0.1,
                "last_byte_seconds": 0.5,
                "eof": True,
            },
            "stderr": {
                "raw_bytes": 0,
                "saturated": False,
                "first_byte_seconds": None,
                "last_byte_seconds": None,
                "eof": True,
            },
        }
    )


def test_observation_replay_is_private_and_keeps_existing_stop_bytes(
    capture_fixture: CaptureFixture,
) -> None:
    fixture, start, stop = capture_fixture
    store = fixture.store
    assert store.native_observation(stop.run_id).availability == "UNAVAILABLE"
    assert store.native_observation(stop.run_id).record is None
    before = {p.name: p.read_bytes() for p in fixture.store_root.iterdir()}
    record = NativeExecutionObservation.from_capture(
        start=start,
        stop=stop,
        output=output_observation(),
        recorded_at=stop.process_stop.stopped_at,
    )
    assert store.put_native_observation(record) == record
    reopened = FileContinuationStore(fixture.store_root, task_id=fixture.task.id)
    read = reopened.native_observation(stop.run_id)
    assert read.availability == "AVAILABLE" and read.record == record
    assert reopened.put_native_observation(record) == record
    assert all((fixture.store_root / name).read_bytes() == data for name, data in before.items())
    assert reopened.receipts_for_task(fixture.task.id) == ()
    assert reopened.admissions_for_task(fixture.task.id) == ()


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", "task_foreign_001"),
        ("run_id", "run_foreign_001"),
        ("work_item_id", "work_foreign_001"),
        ("lease_id", "lease_foreign_001"),
        ("source_revision", "f" * 40),
        ("context_manifest_id", "context_foreign_001"),
        ("request_sha256", "f" * 64),
        ("capture_start_sha256", "f" * 64),
        ("capture_stop_sha256", "f" * 64),
    ],
)
def test_rehashed_binding_tamper_is_rejected(
    capture_fixture: CaptureFixture,
    field: str,
    value: str,
) -> None:
    fixture, start, stop = capture_fixture
    record = NativeExecutionObservation.from_capture(
        start=start,
        stop=stop,
        output=output_observation(),
        recorded_at=stop.process_stop.stopped_at,
    )
    fixture.store.put_native_observation(record)
    path = fixture.store_root / f"native-observation-{stop.run_id}.json"
    wire = record.to_wire()
    wire[field] = value
    wire["observation_sha256"] = digest(
        {k: v for k, v in wire.items() if k != "observation_sha256"}
    )
    path.write_text(json.dumps({"record": wire, "sha256": digest(wire)}))
    with pytest.raises(ContinuationRejected):
        fixture.store.native_observation(stop.run_id)


def test_missing_is_unavailable_but_corrupt_record_is_rejected(
    capture_fixture: CaptureFixture,
) -> None:
    fixture, _, stop = capture_fixture
    path = fixture.store_root / f"native-observation-{stop.run_id}.json"
    path.write_text('{"record":{},"sha256":"' + "0" * 64 + '"}')
    path.chmod(0o600)
    with pytest.raises(ContinuationRejected):
        fixture.store.native_observation(stop.run_id)


def test_rehashed_impossible_timing_is_rejected(capture_fixture: CaptureFixture) -> None:
    fixture, start, stop = capture_fixture
    record = NativeExecutionObservation.from_capture(
        start=start,
        stop=stop,
        output=output_observation(),
        recorded_at=stop.process_stop.stopped_at,
    )
    fixture.store.put_native_observation(record)
    wire = record.to_wire()
    output = wire["output"]
    assert isinstance(output, dict)
    output["elapsed_seconds"] = 0.01
    wire["observation_sha256"] = digest(
        {k: v for k, v in wire.items() if k != "observation_sha256"}
    )
    path = fixture.store_root / f"native-observation-{stop.run_id}.json"
    path.write_text(json.dumps({"record": wire, "sha256": digest(wire)}))
    with pytest.raises(ContinuationRejected):
        fixture.store.native_observation(stop.run_id)
