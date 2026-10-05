"""Per-Run continuation receipts cannot lose history or admit alternative successors."""

import json

import pytest

from ai_software_engineer.orchestration.continuation_models import (
    ContinuationAdmission,
    ContinuationConflict,
    ContinuationRejected,
    ExecutionInterruptionReceipt,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.recovery.models import digest
from tests.orchestration.test_native_continuation_v2 import (
    V2Fixture,
)
from tests.orchestration.test_native_continuation_v2 import (
    denied_paths as denied_paths,
)
from tests.orchestration.test_native_continuation_v2 import (
    transient_limit as transient_limit,
)
from tests.orchestration.test_native_continuation_v2 import (
    v2_fixture as v2_fixture,
)
from tests.orchestration.test_native_continuation_v2 import (
    work_limit as work_limit,
)


def _two_rounds(
    f: V2Fixture,
) -> tuple[ExecutionInterruptionReceipt, ExecutionInterruptionReceipt, ContinuationAdmission]:
    service = f.service()
    first = f.interrupt(service)
    assert f.reserve(service) == 2
    f.activate(2)
    service = f.service()
    assert service.prepare(f.request, f.worktree.path) is not None
    admission = f.store.admission_for_run(f.request.run_id)
    assert admission is not None
    second = f.interrupt(service, text="VALUE = 3\n", provider=True)
    return first, second, admission


def test_reopen_retains_all_per_run_immutable_bodies_and_hashes(v2_fixture: V2Fixture) -> None:
    f = v2_fixture
    first, second, admission = _two_rounds(f)
    before = {path.name: path.read_bytes() for path in f.store_root.iterdir()}
    reopened = FileContinuationStore(f.store_root, task_id=f.task.id)
    assert reopened.receipts_for_task(f.task.id) == (first, second)
    assert reopened.admissions_for_task(f.task.id) == (admission,)
    assert reopened.put_receipt(second) == second
    assert reopened.put_admission(admission) == admission
    assert {path.name: path.read_bytes() for path in f.store_root.iterdir()} == before
    assert set(before) == {
        f"receipt-{first.request.run_id}.json",
        f"receipt-{second.request.run_id}.json",
        f"admission-{admission.new_request.run_id}.json",
    }


def test_replacement_receipt_cannot_omit_the_consumed_admission_chain(
    v2_fixture: V2Fixture,
) -> None:
    f = v2_fixture
    _, second, _ = _two_rounds(f)
    forged = ExecutionInterruptionReceipt.create(
        **{**second.to_wire(), "previous_admission_sha256": None}
    )
    with pytest.raises(ContinuationRejected, match="admission"):
        f.store.put_receipt(forged)
    assert f.store.get_receipt(second.request.run_id) == second


def test_same_interrupted_run_cannot_admit_another_run_or_attempt(v2_fixture: V2Fixture) -> None:
    f = v2_fixture
    _, _, admission = _two_rounds(f)
    forged = ContinuationAdmission.create(
        **{
            **admission.to_wire(),
            "new_request": admission.new_request.model_copy(
                update={"run_id": "run_v2_alternate", "context_manifest_id": "ctx_" + "e" * 64}
            ),
            "next_work_item_id": "work_v2_alternate",
            "next_lease_id": "lease_v2_alternate",
        }
    )
    with pytest.raises(ContinuationConflict):
        f.store.put_admission(forged)
    assert f.store.admissions_for_task(f.task.id) == (admission,)


def test_self_consistent_envelope_cannot_change_mutation_body_digest(v2_fixture: V2Fixture) -> None:
    f = v2_fixture
    first, _, _ = _two_rounds(f)
    path = f.store_root / f"receipt-{first.request.run_id}.json"
    envelope = json.loads(path.read_text())
    envelope["record"]["capture"]["mutations"][0]["after"]["text"] = "VALUE = 99\n"
    envelope["sha256"] = digest(envelope["record"])
    path.write_text(json.dumps(envelope))
    with pytest.raises(ContinuationRejected):
        f.store.receipts_for_task(f.task.id)
