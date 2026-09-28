"""A historical verification DAG is validated once per read, never trusted across reads."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock

import pytest

from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.recovery.verification_records import CandidateVerificationPlan
from tests.recovery.test_verification_environment import _admitted


@pytest.mark.parametrize("successor", [False, True])
def test_verification_diamond_reads_each_plan_once_per_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, successor: bool
) -> None:
    plan, store, _, _, completion = _admitted(tmp_path, environment_error=True)
    target = plan
    if successor:
        incident = store.record_verification_incident(completion)
        target = CandidateVerificationPlan.create(
            **{k: v for k, v in plan.to_wire().items() if k != "plan_sha256"},
            prerequisite_incident_sha256=incident.incident_sha256,
        )
        store.put_verification_plan(target)
    reads: Counter[str] = Counter()
    original = FileRecoveryStore._validate_prerequisite_reference

    def validate(self: FileRecoveryStore, value: CandidateVerificationPlan) -> None:
        reads[value.plan_sha256] += 1
        original(self, value)

    monkeypatch.setattr(FileRecoveryStore, "_validate_prerequisite_reference", validate)
    for round_number in (1, 2):
        if successor:
            assert store.get_verification_plan(target.plan_sha256) == target
        else:
            assert store.get_verification_completion(plan.plan_sha256) == completion
        assert reads[plan.plan_sha256] == round_number
        if successor:
            assert reads[target.plan_sha256] == round_number

    # Completed checks cannot hide later tampering or retain failures across a fresh read.
    path = tmp_path / "verification" / f"verification-plan-{plan.plan_sha256}.json"
    original_bytes = path.read_bytes()
    path.write_text("{}")
    with pytest.raises(RecoveryRejected):
        store.get_verification_plan(target.plan_sha256)
    path.write_bytes(original_bytes)
    assert store.get_verification_plan(target.plan_sha256) == target


def test_recursive_verification_reference_fails_closed_without_recursion_overflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, store, _, _, _ = _admitted(tmp_path)

    def cycle(self: FileRecoveryStore, value: CandidateVerificationPlan) -> None:
        self.get_verification_plan(value.plan_sha256)

    monkeypatch.setattr(FileRecoveryStore, "_validate_prerequisite_reference", cycle)
    with pytest.raises(RecoveryRejected, match="cyclic"):
        store.get_verification_plan(plan.plan_sha256)


def test_simultaneous_reads_do_not_share_validation_trust(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, store, _, _, completion = _admitted(tmp_path)
    barrier, lock = Barrier(2), Lock()
    count = 0
    original = FileRecoveryStore._validate_prerequisite_reference

    def validate(self: FileRecoveryStore, value: CandidateVerificationPlan) -> None:
        nonlocal count
        with lock:
            count += 1
        barrier.wait(timeout=5)
        original(self, value)

    monkeypatch.setattr(FileRecoveryStore, "_validate_prerequisite_reference", validate)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(store.get_verification_completion, [plan.plan_sha256] * 2))
    assert results == (completion, completion)
    assert count == 2
