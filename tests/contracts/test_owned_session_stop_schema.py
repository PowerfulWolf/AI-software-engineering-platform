"""Optional stronger stop scope preserves historical canonical bytes and all graphs."""

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
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


def test_all_known_embeddings_and_fresh_repair_regeneration_keep_exact_stop_graph(
    tmp_path: Path,
) -> None:
    expected = NativeProcessStop.model_json_schema()
    expected_defs = expected.pop("$defs")
    paths = [
        p
        for p in ROOT.joinpath("schemas").glob("*.schema.json")
        if "NativeProcessStop" in json.loads(p.read_text()).get("$defs", {})
    ]
    assert {path.name for path in paths} == {
        "completed-coder-output-unavailable.schema.json",
        "console-deletion-cleanup.schema.json",
        "console-operation.schema.json",
        "engineering-wait-resolution.schema.json",
        "execution-baseline-plan.schema.json",
        "execution-baseline-queue-consumption.schema.json",
        "execution-capture.schema.json",
        "execution-continuation.schema.json",
        "knowledge-execution-record.schema.json",
        "knowledge-invocation-outcome.schema.json",
        "knowledge-preparation-isolation.schema.json",
        "rejected-coder-output-checkpoint.schema.json",
        "service-pause-stop.schema.json",
        "stopped-failure-budget-settlement.schema.json",
        "stopped-failure.schema.json",
        "stopped-provider-failure.schema.json",
        "stopped-coder-execution.schema.json",
        "structured-execution-observation.schema.json",
    }
    for path in paths:
        defs = json.loads(path.read_text())["$defs"]
        assert defs["NativeProcessStop"] == expected, path.name
        for name, node in expected_defs.items():
            assert defs[name] == node, (path.name, name)
        validator = Draft202012Validator({"$ref": "#/$defs/NativeProcessStop", "$defs": defs})
        validator.validate(_stop().to_wire())
        for kind, returncode in (("completed", 1), ("failed", 0)):
            assert not validator.is_valid(
                {**_stop().to_wire(), "kind": kind, "returncode": returncode}
            )
        malformed = _stop().to_wire()
        proof = dict(_proof().to_wire())
        proof["proof_scope"] = "all_descendants_stopped"
        malformed["session_proof"] = proof
        assert not validator.is_valid(malformed)

    scripts, schemas = tmp_path / "scripts", tmp_path / "schemas"
    scripts.mkdir()
    schemas.mkdir()
    for name in ("generate-repair-schemas.py", "sync-legacy-rescue-schemas.py"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    shutil.copyfile(
        ROOT / "schemas/engineering-wait-resolution.schema.json",
        schemas / "engineering-wait-resolution.schema.json",
    )
    command = (sys.executable, str(scripts / "generate-repair-schemas.py"))
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, timeout=60)
    first = (schemas / "console-operation.schema.json").read_bytes()
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, timeout=60)
    assert first == (schemas / "console-operation.schema.json").read_bytes()
    defs = json.loads(first)["$defs"]
    assert defs["NativeProcessStop"] == expected
    for name, node in expected_defs.items():
        assert defs[name] == node


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


@pytest.mark.parametrize("inventory", ["known", "missing", "extra", "replacement"])
def test_stop_schema_sync_checks_exact_inventory_before_any_write(
    tmp_path: Path, inventory: str
) -> None:
    scripts, schemas = tmp_path / "scripts", tmp_path / "schemas"
    scripts.mkdir()
    schemas.mkdir()
    shutil.copyfile(
        ROOT / "scripts/sync-owned-session-schemas.py", scripts / "sync-owned-session-schemas.py"
    )
    for original in ROOT.joinpath("schemas").glob("*.schema.json"):
        schema = json.loads(original.read_text())
        if "NativeProcessStop" in schema.get("$defs", {}):
            # A successful sync must replace stale stop graphs; a refused inventory
            # must leave even these deliberately stale bytes entirely untouched.
            schema["$defs"]["NativeProcessStop"] = {"type": "null"}
            (schemas / original.name).write_text(json.dumps(schema))
    if inventory in {"missing", "replacement"}:
        (schemas / "execution-baseline-queue-consumption.schema.json").unlink()
    if inventory in {"extra", "replacement"}:
        (schemas / "unreviewed-stop-embedding.schema.json").write_text(
            '{"$defs":{"NativeProcessStop":{"type":"null"}}}'
        )
    before = {p.name: p.read_bytes() for p in schemas.iterdir()}
    result = subprocess.run(
        (sys.executable, str(scripts / "sync-owned-session-schemas.py")),
        cwd=ROOT,
        check=False,
        capture_output=True,
        timeout=20,
    )
    if inventory != "known":
        assert result.returncode != 0
        assert {p.name: p.read_bytes() for p in schemas.iterdir()} == before
        return
    assert result.returncode == 0, result.stderr
    canonical = NativeProcessStop.model_json_schema()
    closure = canonical.pop("$defs")
    assert {p.name for p in schemas.iterdir()} == before.keys()
    for path in schemas.iterdir():
        synchronized = json.loads(path.read_text())
        assert synchronized["$defs"]["NativeProcessStop"] == canonical
        for name, definition in closure.items():
            assert synchronized["$defs"][name] == definition
