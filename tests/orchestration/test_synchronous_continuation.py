"""Closed Responses loops use exact request facts, never fabricated native PIDs."""

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from ai_software_engineer.agents.continuation import InterruptionObservation
from ai_software_engineer.agents.execution import SynchronousToolLoopStop
from ai_software_engineer.agents.models import AgentErrorCode
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.orchestration.continuation import NativeCoderContinuation
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRejected,
    ExecutionInterruptionReceipt,
)
from tests.contracts.test_continuation_schema import _schema
from tests.orchestration.test_native_continuation import NOW
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


@pytest.mark.parametrize("local", [False, True])
def test_synchronous_stop_seals_full_draft_and_reserves_exact_budget_after_restart(
    v2_fixture: V2Fixture,
    local: bool,
) -> None:
    fixture = v2_fixture
    original_request = fixture.request
    service = fixture.service()
    before = service.started(original_request, fixture.worktree.path)
    assert before is not None
    (fixture.worktree.path / "src/app.py").write_text("VALUE = 2\n")
    stop = SynchronousToolLoopStop.create(
        task_id=original_request.task_id,
        run_id=original_request.run_id,
        request_sha256=digest(original_request.to_wire()),
        completed_operation_ids=("tool.responses.01.001",),
        kind="local_execution_limit" if local else "failed",
        stopped_at=NOW,
    )
    assert (
        service.interrupted(
            original_request,
            fixture.worktree.path,
            before=before,
            cause="local_execution_limit" if local else "provider_transient",
            original_error_code=AgentErrorCode.TIMEOUT
            if local
            else AgentErrorCode.PROVIDER_UNAVAILABLE,
            process_stop=stop,
            output_present=False,
        )
        is InterruptionObservation.CAPTURED
    )
    receipt = fixture.store.get_receipt(original_request.run_id)
    validator = Draft202012Validator(
        _schema("execution-continuation.schema.json"), format_checker=FormatChecker()
    )
    assert not list(validator.iter_errors(receipt.to_wire()))
    wrong_version = {**receipt.to_wire(), "schema_version": "v1"}
    assert list(validator.iter_errors(wrong_version))
    wrong_kind = {
        **receipt.to_wire(),
        "process_stop": {**stop.to_wire(), "kind": "failed" if local else "local_execution_limit"},
    }
    assert list(validator.iter_errors(wrong_kind))
    with pytest.raises(ValueError):
        ExecutionInterruptionReceipt.model_validate(wrong_kind)
    duplicate_operations = {
        **receipt.to_wire(),
        "process_stop": {
            **stop.to_wire(),
            "completed_operation_ids": ["tool.responses.01.001", "tool.responses.01.001"],
        },
    }
    assert list(validator.iter_errors(duplicate_operations))
    assert receipt.process_stop == stop and receipt.capture.to_capture().changed_paths == (
        "src/app.py",
    )
    old_bytes = {path.name: path.read_bytes() for path in fixture.store_root.iterdir()}
    fixture.restart()
    service = fixture.service()
    assert fixture.reserve(service) == 2
    task = fixture.repository.get(fixture.task.id)
    assert task.work_attempt == (2 if local else 1)
    assert task.transient_failures(original_request.role) == (0 if local else 1)
    fixture.activate(2)
    assert service.prepare(fixture.request, fixture.worktree.path) is not None
    assert fixture.request.run_id != original_request.run_id
    assert fixture.request.context_manifest_id != original_request.context_manifest_id
    assert str(fixture.worktree.path) == receipt.capture.worktree_path
    for name, body in old_bytes.items():
        assert (fixture.store_root / name).read_bytes() == body
    NativeCoderContinuation._require_stopped(stop, original_request)


def test_recomputed_synchronous_stop_cannot_change_request_or_claim_native_pid(
    v2_fixture: V2Fixture,
) -> None:
    fixture = v2_fixture
    receipt = fixture.interrupt(fixture.service(), provider=True)
    stop = SynchronousToolLoopStop.create(
        task_id=fixture.request.task_id,
        run_id="run_wrong_sync_loop",
        request_sha256=digest(fixture.request.to_wire()),
        completed_operation_ids=(),
        stopped_at=NOW,
    )
    with pytest.raises(ValueError, match="exact request"):
        ExecutionInterruptionReceipt.create(
            **{
                **receipt.to_wire(),
                "process_stop": stop.to_wire(),
                "process_stop_sha256": stop.stop_sha256,
            }
        )
    with pytest.raises(ValueError):
        SynchronousToolLoopStop.model_validate({**stop.to_wire(), "process_id": 123})
    with pytest.raises(ContinuationRejected, match="original exact request"):
        NativeCoderContinuation._require_stopped(stop)
