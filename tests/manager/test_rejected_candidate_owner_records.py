"""Expired owner observations are typed retained facts and physically deletable."""

from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.rejected_candidate_owner import (
    EXPIRED_OWNER_EVENT,
    EXPIRED_OWNER_NAMESPACE,
    RejectedCandidateExpiredOwnerSettlement,
)
from ai_software_engineer.multi_directory.purge_state import (
    StateDeletionScope,
    task_state_directories,
)
from tests.manager.test_rejected_candidate_output import RejectedCandidateFixture
from tests.manager.test_rejected_candidate_output import (
    rejected_candidate_proof_fixture as rejected_candidate_proof_fixture,
)


def settlement(f: RejectedCandidateFixture) -> RejectedCandidateExpiredOwnerSettlement:
    original = f.proof.original_claim
    return RejectedCandidateExpiredOwnerSettlement.create(
        task_id=f.task.id,
        task_revision=f.proof.task_revision,
        proof=f.proof,
        current_claim=original,
        original_claim_sha256=digest(original.to_wire()),
        current_claim_sha256=digest(original.to_wire()),
        observed_at=original.lease.expires_at + timedelta(seconds=1),
    )


def test_settlement_identifiers_fit_existing_storage_contracts() -> None:
    assert len(EXPIRED_OWNER_EVENT) <= 32
    assert KnowledgeRecordStore._name(EXPIRED_OWNER_NAMESPACE, "typed-fixture").endswith(".json")


def scope(f: RejectedCandidateFixture, **changes: object) -> StateDeletionScope:
    return StateDeletionScope.model_validate(
        {
            **f.scope.to_wire(),
            "requirement_ids": frozenset((f.proof.capture_start.scope.requirement_id,)),
            "task_ids": frozenset((f.task.id,)),
            **changes,
        }
    )


def test_exact_settlement_roundtrips_without_requiring_future_baseline_plan(
    tmp_path: Path,
    rejected_candidate_proof_fixture: RejectedCandidateFixture,
) -> None:
    f = rejected_candidate_proof_fixture
    root = tmp_path / "state/execution-baselines" / f.task.id
    store = FileExecutionBaselineStore(root)
    record = settlement(f)
    uri = store.put_expired_owner_settlement(record)
    assert uri == store.put_expired_owner_settlement(record)
    assert (
        store.records.get(
            EXPIRED_OWNER_NAMESPACE,
            record.settlement_sha256,
            RejectedCandidateExpiredOwnerSettlement,
        )
        == record
    )
    assert task_state_directories(tmp_path, scope(f)) == (root,)


@pytest.mark.parametrize("mutation", ["project", "repository", "task_directory", "key"])
def test_foreign_or_noncanonical_settlement_cannot_enter_physical_delete_plan(
    tmp_path: Path,
    rejected_candidate_proof_fixture: RejectedCandidateFixture,
    mutation: str,
) -> None:
    f = rejected_candidate_proof_fixture
    directory_task = "task_foreign_directory" if mutation == "task_directory" else f.task.id
    root = tmp_path / "state/execution-baselines" / directory_task
    store = FileExecutionBaselineStore(root)
    record = settlement(f)
    store.put_expired_owner_settlement(record)
    expected = scope(f)
    if mutation in {"project", "repository"}:
        expected = scope(f, **{mutation + "_id": mutation + "_foreign"})
    elif mutation == "task_directory":
        expected = scope(f, task_ids=frozenset((f.task.id, directory_task)))
    elif mutation == "key":
        path = root / store.records._name(EXPIRED_OWNER_NAMESPACE, record.settlement_sha256)
        path.rename(root / store.records._name(EXPIRED_OWNER_NAMESPACE, "f" * 64))
    with pytest.raises(ValueError):
        task_state_directories(tmp_path, expected)


@pytest.mark.parametrize("mutation", ["not_expired", "foreign_claim", "wrong_digest"])
def test_settlement_record_refuses_unproven_owner_inputs(
    rejected_candidate_proof_fixture: RejectedCandidateFixture,
    mutation: str,
) -> None:
    f = rejected_candidate_proof_fixture
    record = settlement(f)
    values = record.model_dump(mode="python", exclude={"settlement_sha256"})
    if mutation == "not_expired":
        values["observed_at"] = record.current_claim.lease.expires_at - timedelta(seconds=1)
    elif mutation == "foreign_claim":
        values["current_claim"] = record.current_claim.model_copy(update={"worker_id": "foreign"})
    else:
        values["current_claim_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        RejectedCandidateExpiredOwnerSettlement.create(**values)
