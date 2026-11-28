"""Optional stronger stop scope preserves historical canonical bytes and all graphs."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.owned_sessions import OwnedProcessIdentity, OwnedSessionStopProof

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 11, tzinfo=UTC)


def _proof() -> OwnedSessionStopProof:
    leader = OwnedProcessIdentity(
        process_id=101,
        group_id=101,
        session_id=101,
        birth_identity="fixture:123:456",
    )
    child = OwnedProcessIdentity(
        process_id=102,
        group_id=102,
        session_id=101,
        birth_identity="fixture:123:789",
    )
    return OwnedSessionStopProof.create(
        boot_identity="fixture:boot",
        leader=leader,
        observed_processes=(leader, child),
        observation_count=4,
        observations_sha256="a" * 64,
        observed_at=NOW,
    )


def _stop() -> NativeProcessStop:
    return NativeProcessStop.create(
        process_id=101,
        group_id=101,
        returncode=0,
        kind="completed",
        stopped_at=NOW + timedelta(seconds=1),
        session_proof=_proof(),
    )


def test_absent_new_field_preserves_original_wire_and_nested_digests() -> None:
    old_body = {
        "process_id": 101,
        "group_id": 101,
        "returncode": 0,
        "kind": "completed",
        "stopped_at": "2026-10-11T00:00:00Z",
    }
    expected = hashlib.sha256(
        json.dumps(
            old_body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    old_wire = {**old_body, "stop_sha256": expected}
    stop = NativeProcessStop.model_validate(old_wire)
    stop.validate_integrity()
    assert stop.session_proof is None and stop.to_wire() == old_wire
    assert stop.model_dump(mode="json") == old_wire
    with_null = NativeProcessStop.model_validate({**old_wire, "session_proof": None})
    assert with_null.model_dump(mode="json") == old_wire
    assert with_null.recompute_sha256() == expected
    # Existing enclosing models use model_dump without exclude_none in hashing.
    from ai_software_engineer.domain.model import DomainModel

    class Enclosing(DomainModel):
        process_stop: NativeProcessStop

    nested = Enclosing(process_stop=stop).model_dump(mode="json")
    assert nested == {"process_stop": old_wire}
    assert (
        hashlib.sha256(json.dumps(nested, sort_keys=True).encode()).digest()
        == hashlib.sha256(json.dumps({"process_stop": old_wire}, sort_keys=True).encode()).digest()
    )


@pytest.mark.parametrize("mutation", ["digest", "leader", "scope", "future", "extra"])
def test_typed_stop_rejects_unbound_or_corrupt_scope(mutation: str) -> None:
    wire = _stop().to_wire()
    proof = _proof().to_wire()
    if mutation == "digest":
        proof["proof_sha256"] = "b" * 64
    elif mutation == "leader":
        wire["process_id"] = wire["group_id"] = 201
    elif mutation == "scope":
        proof["proof_scope"] = "all_descendants_stopped"
    elif mutation == "future":
        wire["stopped_at"] = (NOW - timedelta(seconds=1)).isoformat()
    else:
        proof["arbitrary_pid_kill"] = True
    wire["session_proof"] = proof
    with pytest.raises(ValidationError):
        NativeProcessStop.model_validate(wire)
