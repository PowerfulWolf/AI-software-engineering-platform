"""Complete sidecar engineering ledgers are reused only by one bounded read."""

import json
from pathlib import Path

import pytest

from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import EngineeringDispositionRecord
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.models import KnowledgeError, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.delivery_preflight import (
    DeliveryPreflightReceipt,
    DeliveryPreflightScope,
)
from ai_software_engineer.manager.delivery_preflight import (
    _digest as preflight_digest,
)
from ai_software_engineer.manager.verifier_preparation import VerifierPreparationIntent
from ai_software_engineer.team_view.engineering_history import (
    EngineeringHistorySnapshot,
    engineering_history,
)
from tests.domain.factories import NOW, make_task
from tests.manager.test_native_verification import _fixture as native_fixture
from tests.team_view.test_engineering_history import (
    _bytes,
    _decision,
    _handling,
    _policy_decision,
    _policy_task,
    _proof,
    _publish,
    _scope,
)


def test_two_tasks_share_full_prefix_without_sharing_their_timeline_or_returned_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = make_task()
    second = first.model_copy(update={"id": "task_engineering_second"})
    sidecar = tmp_path / "sidecar"
    for task in (first, second):
        proof = _proof(task)
        decision = _decision(proof)
        _publish(sidecar, proof, decision, _handling(proof, decision))
    expected = tuple(
        engineering_history(sidecar, task, _scope(task), "delivery_history")
        for task in (first, second)
    )
    saved = _bytes(sidecar)
    original = KnowledgeRecordStore._read_name
    names: list[str] = []

    def counted[T: DomainModel](store: KnowledgeRecordStore, name: str, model: type[T]) -> T | None:
        names.append(name)
        return original(store, name, model)

    monkeypatch.setattr(KnowledgeRecordStore, "_read_name", counted)
    snapshot = EngineeringHistorySnapshot()
    actual = tuple(
        engineering_history(
            sidecar, task, _scope(task), "delivery_history", history_snapshot=snapshot
        )
        for task in (first, second)
    )
    assert actual == expected
    assert all(len(history) == 3 for history in actual)
    assert all(entry.task_id == first.id for entry in actual[0])
    assert all(entry.task_id == second.id for entry in actual[1])
    # Six records are listed and independently key-checked once. Each Task still
    # reads the decision's proof and the handling's original proof+resolution.
    assert len(names) == 18
    assert sum(name.startswith("wait-handlings-") for name in names) == 4
    missing = actual[0][0].details["missing"]
    assert isinstance(missing, list)
    missing.append("caller mutation")
    assert (
        engineering_history(
            sidecar, first, _scope(first), "delivery_history", history_snapshot=snapshot
        )
        == expected[0]
    )
    assert _bytes(sidecar) == saved


def test_captured_policy_facts_do_not_cache_task_or_project_authorization(tmp_path: Path) -> None:
    task = _policy_task()
    proof = _proof(task)
    decision = _policy_decision(task, proof)
    sidecar = tmp_path / "sidecar"
    _publish(sidecar, proof, decision, _handling(proof, decision))
    snapshot = EngineeringHistorySnapshot()
    assert (
        len(
            engineering_history(
                sidecar, task, _scope(task), "delivery_history", history_snapshot=snapshot
            )
        )
        == 3
    )
    with pytest.raises(ValueError, match="Project scope"):
        engineering_history(
            sidecar,
            task,
            _scope(task).model_copy(update={"project_id": "project_foreign"}),
            "delivery_history",
            history_snapshot=snapshot,
        )
    with pytest.raises(ValueError, match="Task intent"):
        engineering_history(
            sidecar,
            task.model_copy(update={"title": "Another approved intent"}),
            _scope(task),
            "delivery_history",
            history_snapshot=snapshot,
        )


def test_new_snapshot_observes_append_and_missing_root_without_creating_directories(
    tmp_path: Path,
) -> None:
    task = make_task()
    sidecar = tmp_path / "sidecar"
    snapshot = EngineeringHistorySnapshot()
    assert (
        engineering_history(
            sidecar, task, _scope(task), "delivery_history", history_snapshot=snapshot
        )
        == ()
    )
    assert not sidecar.exists()
    first = _proof(task)
    _publish(sidecar, first)
    assert (
        engineering_history(
            sidecar, task, _scope(task), "delivery_history", history_snapshot=snapshot
        )
        == ()
    )
    next_snapshot = EngineeringHistorySnapshot()
    assert (
        len(
            engineering_history(
                sidecar, task, _scope(task), "delivery_history", history_snapshot=next_snapshot
            )
        )
        == 1
    )
    _publish(sidecar, _proof(task, 1))
    assert (
        len(
            engineering_history(
                sidecar, task, _scope(task), "delivery_history", history_snapshot=next_snapshot
            )
        )
        == 1
    )
    assert len(engineering_history(sidecar, task, _scope(task), "delivery_history")) == 2


@pytest.mark.parametrize("change", ["body", "wrong-key", "symlink"])
def test_new_snapshot_rejects_corrupt_foreign_record_and_failed_capture_is_not_reused(
    tmp_path: Path, change: str
) -> None:
    task = make_task()
    foreign = task.model_copy(update={"id": "task_foreign_engineering"})
    sidecar = tmp_path / "sidecar"
    _publish(sidecar, _proof(task))
    proof = _proof(foreign)
    _publish(sidecar, proof)
    captured = EngineeringHistorySnapshot()
    expected = engineering_history(
        sidecar, task, _scope(task), "delivery_history", history_snapshot=captured
    )
    store = KnowledgeRecordStore(sidecar / "state" / "delivery-waits", read_only=True)
    path = store.root / store._name("wait-investigations", proof.proof_sha256)
    original = path.read_bytes()
    if change == "body":
        envelope = json.loads(original)
        envelope["record"]["next_action"] = "Changed with a valid envelope digest"
        envelope["sha256"] = digest(envelope["record"])
        path.write_text(json.dumps(envelope), encoding="utf-8")
    elif change == "wrong-key":
        path.rename(store.root / store._name("wait-investigations", "another-key"))
    else:
        external = tmp_path / "outside.json"
        path.rename(external)
        path.symlink_to(external)
    # Already captured foreign facts cannot pollute the selected Task. A fresh
    # read must validate that foreign record too, rather than filtering it first.
    assert (
        engineering_history(
            sidecar, task, _scope(task), "delivery_history", history_snapshot=captured
        )
        == expected
    )
    failed = EngineeringHistorySnapshot()
    saved = _bytes(sidecar)
    with pytest.raises((ValueError, KnowledgeError)):
        engineering_history(
            sidecar, task, _scope(task), "delivery_history", history_snapshot=failed
        )
    assert not failed._records
    assert _bytes(sidecar) == saved
    if path.is_symlink():
        path.unlink()
    path.write_bytes(original)
    if change == "wrong-key":
        (store.root / store._name("wait-investigations", "another-key")).unlink()
    assert (
        engineering_history(
            sidecar, task, _scope(task), "delivery_history", history_snapshot=failed
        )
        == expected
    )


def test_captured_handling_still_reads_its_independent_original_proof(tmp_path: Path) -> None:
    task = make_task()
    proof = _proof(task)
    sidecar = tmp_path / "sidecar"
    _publish(sidecar, proof, handling=_handling(proof))
    snapshot = EngineeringHistorySnapshot()
    assert (
        len(
            engineering_history(
                sidecar, task, _scope(task), "delivery_history", history_snapshot=snapshot
            )
        )
        == 2
    )
    store = KnowledgeRecordStore(sidecar / "state" / "delivery-waits", read_only=True)
    (store.root / store._name("wait-investigations", proof.proof_sha256)).unlink()
    for current in (snapshot, EngineeringHistorySnapshot()):
        with pytest.raises(KnowledgeError, match="RECORD_NOT_FOUND"):
            engineering_history(
                sidecar, task, _scope(task), "delivery_history", history_snapshot=current
            )


def test_preflight_prefix_reuse_preserves_native_requirement_scope_and_foreign_integrity(
    tmp_path: Path,
) -> None:
    task = make_task()
    sidecar = tmp_path / "sidecar"
    receipt = DeliveryPreflightReceipt(
        scope=DeliveryPreflightScope(
            team_id=_scope(task).team_id,
            project_id=_scope(task).project_id,
            repository_id=_scope(task).repository_id,
            requirement_id="delivery_native_child",
        ),
        task_id=task.id,
        source_revision=task.base_ref,
        plan_sha256="a" * 64,
        frozen_policy_sha256="b" * 64,
        requirements_sha256="c" * 64,
        observations=(),
        status="READY",
        checked_at=NOW,
        receipt_sha256="0" * 64,
    )
    receipt = receipt.model_copy(
        update={
            "receipt_sha256": preflight_digest(
                receipt.model_dump(mode="json", exclude={"receipt_sha256"})
            )
        }
    )
    store = KnowledgeRecordStore(sidecar / "state" / "delivery-preflight")
    store.put("preflight-receipts", receipt.receipt_sha256, receipt)
    snapshot = EngineeringHistorySnapshot()
    assert (
        len(
            engineering_history(
                sidecar,
                task,
                _scope(task),
                "delivery_native_child",
                delivery_requirement_id="delivery_parent",
                history_snapshot=snapshot,
            )
        )
        == 1
    )
    with pytest.raises(ValueError, match="current Requirement"):
        engineering_history(
            sidecar, task, _scope(task), "delivery_parent", history_snapshot=snapshot
        )
    path = store.root / store._name("preflight-receipts", receipt.receipt_sha256)
    path.write_bytes(path.read_bytes() + b"corrupt")
    unrelated = task.model_copy(update={"id": "task_foreign_preflight"})
    with pytest.raises(KnowledgeError):
        engineering_history(sidecar, unrelated, _scope(unrelated), "delivery_native_child")


def test_foreign_preparation_intent_requires_its_own_immutable_store_key(tmp_path: Path) -> None:
    fixture = native_fixture(tmp_path)
    intent = VerifierPreparationIntent.create(
        work_item_id=fixture.claim.work_item.id,
        lease_id=fixture.claim.lease.id,
        task_id=fixture.task.id,
        task_snapshot_sha256=digest(fixture.task.to_wire()),
        checkpoint_sequence=0,
        dispatch_sequence=fixture.claim.work_item.dispatch_sequence,
        request=fixture.request,
        request_sha256=digest(fixture.request.to_wire()),
        started_at=NOW,
    )
    sidecar = tmp_path / "sidecar"
    records = KnowledgeRecordStore(sidecar / "state" / "delivery-preflight")
    records.put("verifier-preparation-intents", "another-immutable-key", intent)
    task = make_task().model_copy(update={"id": "task_foreign_preparation"})
    with pytest.raises(KnowledgeError, match="RECORD_NOT_FOUND"):
        engineering_history(sidecar, task, _scope(task), "delivery_history")


@pytest.mark.parametrize("limit", ["records", "bytes", "prefixes", "stores"])
def test_shared_capacity_limits_fall_back_to_complete_validated_history(
    tmp_path: Path, limit: str
) -> None:
    task = make_task()
    sidecar = tmp_path / "sidecar"
    for number in range(3):
        proof = _proof(task, number).model_copy(update={"step_sha256": digest({"step": number})})
        proof = proof.model_copy(update={"proof_sha256": proof.recompute_sha256()})
        _publish(sidecar, proof, handling=_handling(proof))
    expected = engineering_history(sidecar, task, _scope(task), "delivery_history")
    snapshot = EngineeringHistorySnapshot()
    setattr(snapshot, "_maximum_" + limit, 1)
    for root in (sidecar, tmp_path / "another-sidecar"):
        if root != sidecar:
            _publish(root, _proof(task))
        for _ in range(2):
            actual = engineering_history(
                root, task, _scope(task), "delivery_history", history_snapshot=snapshot
            )
            assert actual == (
                expected
                if root == sidecar
                else engineering_history(root, task, _scope(task), "delivery_history")
            )
    assert snapshot._retained_records <= snapshot._maximum_records
    assert snapshot._retained_bytes <= snapshot._maximum_bytes
    assert len(snapshot._records) + len(snapshot._dispositions) <= snapshot._maximum_prefixes
    assert len(snapshot._stores) <= snapshot._maximum_stores
    # Overflow is an optimization fallback. A new read still rejects historical
    # corruption instead of dropping the tail that exceeded the cache capacity.
    path = next((sidecar / "state" / "delivery-waits").glob("wait-handlings-*.json"))
    path.write_bytes(path.read_bytes() + b"corrupt")
    if limit != "stores":
        with pytest.raises(KnowledgeError):
            engineering_history(
                sidecar, task, _scope(task), "delivery_history", history_snapshot=snapshot
            )
    with pytest.raises(KnowledgeError):
        engineering_history(sidecar, task, _scope(task), "delivery_history")


def test_terminal_prefix_reuse_rechecks_full_task_snapshot_and_releases_source_paths(
    tmp_path: Path,
) -> None:
    task = make_task().model_copy(update={"status": TaskStatus.BLOCKED})
    disposition = decide_delivery_disposition(
        DeliveryFailureFacts(
            task_id=task.id,
            role=AgentRole.QA,
            classification="ENGINEERING_AUTHORIZATION",
            source_revision=task.base_ref,
            task_intent_sha256=task_intent_sha256(task),
            checkpoint_sequence=3,
            budget_available=True,
        )
    )
    record = EngineeringDispositionRecord(
        delivery_id="delivery_history",
        native_checkpoint_sha256="a" * 64,
        source_task_id=task.id,
        source_task_status=TaskStatus.BLOCKED,
        source_task_snapshot_sha256=digest(task.to_wire()),
        repository_root=task.repository,
        plan_sha256="b" * 64,
        rejection_code="LEGACY_AUTHORITY",
        disposition=disposition,
        recorded_at=NOW,
        record_sha256="0" * 64,
    )
    record = record.model_copy(update={"record_sha256": record.recompute_sha256()})
    sidecar = tmp_path / "sidecar"
    root = sidecar / "state" / "recovery"
    root.mkdir(parents=True)
    path = root / ("engineering-disposition-" + record.record_sha256 + ".json")
    path.write_text(record.model_dump_json(), encoding="utf-8")
    snapshot = EngineeringHistorySnapshot()
    assert (
        len(
            engineering_history(
                sidecar, task, _scope(task), "delivery_history", history_snapshot=snapshot
            )
        )
        == 1
    )
    with pytest.raises(ValueError, match="source Task facts"):
        engineering_history(
            sidecar,
            task.model_copy(update={"attempts": task.attempts + 1}),
            _scope(task),
            "delivery_history",
            history_snapshot=snapshot,
        )
    path.write_bytes(path.read_bytes() + b"corrupt")
    with pytest.raises(ValueError):
        engineering_history(sidecar, task, _scope(task), "delivery_history")
