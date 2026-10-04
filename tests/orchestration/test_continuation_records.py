"""Stopped work facts and a one-use engineering decision have separate identities."""

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.agents.execution import NativeProcessStop
from ai_software_engineer.agents.models import AgentErrorCode, AgentRequest
from ai_software_engineer.domain import AgentPermissions, AgentRole, NetworkAccess
from ai_software_engineer.domain.continuation import InterruptionContinuationPolicy
from ai_software_engineer.git.capture import WorktreeChangeCapture
from ai_software_engineer.git.mutation import MutationFile, WorkspaceMutationInventory
from ai_software_engineer.git.ports import WorktreeRef
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationAdmission,
    ContinuationRejected,
    ContinuationScope,
    ExecutionInterruptionReceipt,
)
from ai_software_engineer.recovery.models import CapturedChanges

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)


def make_receipt(tmp_path: Path) -> ExecutionInterruptionReceipt:
    request = AgentRequest(
        run_id="run_interrupted_001",
        task_id="task_continuation_001",
        role=AgentRole.CODER,
        attempt=1,
        source_revision="a" * 40,
        context_manifest_id="ctx_" + "b" * 64,
        input_artifact_ids=("art_plan_001",),
        permissions=AgentPermissions(
            read_paths=("src/**",),
            write_paths=("src/**",),
            commands=("pytest",),
            network=NetworkAccess.NONE,
        ),
        output_schema="schemas/coder-output.schema.json",
        timeout_seconds=1800,
    )
    capture = CapturedChanges.from_capture(
        WorktreeChangeCapture(
            worktree=WorktreeRef(
                task_id=request.task_id,
                role=AgentRole.CODER,
                attempt=1,
                path=tmp_path / "worktree",
                head_revision=request.source_revision,
                branch="ai/task_continuation_001/attempt-1",
                detached=False,
            ),
            patch=b"diff --git a/src/work.py b/src/work.py\n",
            index_diff_sha256=hashlib.sha256(b"").hexdigest(),
            file_sha256s=(("src/work.py", hashlib.sha256(b"draft\n").hexdigest()),),
        )
    )
    process_stop = NativeProcessStop.create(
        process_id=12345,
        group_id=12345,
        returncode=-15,
        kind="local_execution_limit",
        stopped_at=NOW - timedelta(seconds=1),
    )
    inventory_before = WorkspaceMutationInventory(files=())
    inventory_after = WorkspaceMutationInventory(
        files=(
            MutationFile(
                path="src/work.py",
                kind="file",
                sha256=capture.files[0].sha256,
                mode=0o644,
                size=6,
            ),
        )
    )
    return ExecutionInterruptionReceipt.create(
        scope=ContinuationScope(
            team_id="team_continuation",
            project_id="project_continuation",
            repository_id="repository_continuation",
            requirement_id="delivery_continuation",
            dispatch_sha256="c" * 64,
        ),
        request=request,
        task_intent_sha256="d" * 64,
        task_revision=2,
        original_work_item_id="work_interrupted_001",
        claim_lease_id="lease_interrupted_001",
        policy_sha256=InterruptionContinuationPolicy().policy_sha256,
        cause="local_execution_limit",
        original_error_code=AgentErrorCode.TIMEOUT,
        process_stop=process_stop,
        process_stop_sha256=process_stop.stop_sha256,
        capture=capture,
        inventory_before=inventory_before,
        inventory_after=inventory_after,
        inventory_before_sha256=inventory_before.sha256,
        inventory_after_sha256=inventory_after.sha256,
        mutation_paths=("src/work.py",),
        created_at=NOW,
    )


def make_admission(receipt: ExecutionInterruptionReceipt) -> ContinuationAdmission:
    return ContinuationAdmission.create(
        scope=receipt.scope,
        task_id=receipt.request.task_id,
        interrupted_run_id=receipt.request.run_id,
        receipt_sha256=receipt.receipt_sha256,
        policy_sha256=receipt.policy_sha256,
        new_request=receipt.request.model_copy(
            update={
                "run_id": "run_replacement_001",
                "attempt": 2,
                "context_manifest_id": "ctx_" + "3" * 64,
            }
        ),
        next_work_item_id="work_replacement_001",
        next_lease_id="lease_replacement_001",
        created_at=NOW + timedelta(seconds=1),
    )


def test_capture_receipt_is_hash_bound_without_fabricated_progress_or_verdict(
    tmp_path: Path,
) -> None:
    receipt = make_receipt(tmp_path)
    receipt.validate_integrity()
    assert ExecutionInterruptionReceipt.model_validate(receipt.to_wire()) == receipt
    assert "remaining_step_ids" not in receipt.to_wire()
    assert "verdict" not in receipt.to_wire()
    assert "approved" not in receipt.to_wire()
    changed = receipt.model_copy(update={"inventory_after_sha256": "4" * 64})
    with pytest.raises(ContinuationRejected, match=r"structure|integrity|digest"):
        changed.validate_integrity()


@pytest.mark.parametrize("problem", ["missing", "invalid"])
def test_receipt_requires_original_work_item_binding(tmp_path: Path, problem: str) -> None:
    payload = make_receipt(tmp_path).to_wire()
    if problem == "missing":
        payload.pop("original_work_item_id")
    else:
        payload["original_work_item_id"] = "lease_not_a_work_item"
    with pytest.raises(ValueError, match="original_work_item_id"):
        ExecutionInterruptionReceipt.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (("attempt", 2), ("task_id", "task_foreign_001"), ("source_revision", "f" * 40)),
)
def test_receipt_rejects_request_capture_identity_aliases(
    tmp_path: Path, field: str, value: object
) -> None:
    receipt = make_receipt(tmp_path)
    changed_request = receipt.request.model_copy(update={field: value})
    with pytest.raises(ValueError, match=r"capture|first|identity"):
        ExecutionInterruptionReceipt.model_validate(
            {**receipt.to_wire(), "request": changed_request.to_wire()}
        )


@pytest.mark.parametrize("paths", [(), ("src/b.py", "src/a.py"), ("src/a.py", "src/a.py")])
def test_receipt_rejects_missing_or_ambiguous_mutation_inventory(
    tmp_path: Path, paths: tuple[str, ...]
) -> None:
    with pytest.raises(ValueError):
        ExecutionInterruptionReceipt.model_validate(
            {**make_receipt(tmp_path).to_wire(), "mutation_paths": paths}
        )


@pytest.mark.parametrize(
    ("cause", "code"),
    (
        ("local_execution_limit", "PROVIDER_UNAVAILABLE"),
        ("provider_transient", "INVALID_OUTPUT"),
        ("provider_transient", "POLICY_VIOLATION"),
        ("unknown_crash", "TIMEOUT"),
    ),
)
def test_receipt_preserves_failure_cause_without_refunding_unknown_work(
    tmp_path: Path, cause: str, code: str
) -> None:
    with pytest.raises(ValueError):
        ExecutionInterruptionReceipt.model_validate(
            {**make_receipt(tmp_path).to_wire(), "cause": cause, "original_error_code": code}
        )


@pytest.mark.parametrize("problem", ["body_hash", "reference_hash", "time", "cause"])
def test_receipt_rejects_unverifiable_or_not_yet_stopped_execution(
    tmp_path: Path, problem: str
) -> None:
    receipt = make_receipt(tmp_path)
    payload = receipt.to_wire()
    if problem == "reference_hash":
        payload["process_stop_sha256"] = "f" * 64
    elif problem == "time":
        payload["created_at"] = (receipt.process_stop.stopped_at - timedelta(seconds=1)).isoformat()
    else:
        stop = receipt.process_stop.to_wire()
        if problem == "body_hash":
            stop["process_id"] = 54321
            stop["group_id"] = 54321
        else:
            altered = NativeProcessStop.create(**{**stop, "kind": "failed"})
            stop = altered.to_wire()
            payload["process_stop_sha256"] = altered.stop_sha256
        payload["process_stop"] = stop
    with pytest.raises(ValueError, match=r"stop|digest"):
        ExecutionInterruptionReceipt.model_validate(payload)


@pytest.mark.parametrize("side", ["before", "after"])
def test_receipt_rejects_inventory_body_or_hash_drift(tmp_path: Path, side: str) -> None:
    receipt = make_receipt(tmp_path)
    original = receipt.to_wire()
    hash_alias = {**original, f"inventory_{side}_sha256": "f" * 64}
    with pytest.raises(ValueError, match="inventory"):
        ExecutionInterruptionReceipt.model_validate(hash_alias)
    altered = WorkspaceMutationInventory(
        files=(MutationFile("ignored-cache.tmp", "file", "f" * 64, 0o644, 9),)
    )
    changed = {**original, f"inventory_{side}": altered}
    with pytest.raises(ValueError, match="inventory"):
        ExecutionInterruptionReceipt.model_validate(changed)


def test_admission_has_fresh_identity_and_explicit_policy_authority(tmp_path: Path) -> None:
    receipt = make_receipt(tmp_path)
    admission = make_admission(receipt)
    admission.validate_integrity()
    assert admission.authorization_source == "authorized_by_policy"
    assert admission.new_request.run_id != receipt.request.run_id
    assert admission.new_request.attempt == 2
    assert ContinuationAdmission.model_validate(admission.to_wire()) == admission
    changed = admission.model_copy(update={"next_lease_id": "lease_foreign_001"})
    with pytest.raises(ContinuationRejected, match=r"integrity|digest"):
        changed.validate_integrity()


@pytest.mark.parametrize(
    ("field", "value"),
    (("attempt", 1), ("attempt", 3), ("run_id", "run_interrupted_001")),
)
def test_admission_rejects_same_run_or_recursive_replacement(
    tmp_path: Path, field: str, value: object
) -> None:
    admission = make_admission(make_receipt(tmp_path))
    with pytest.raises(ValueError):
        ContinuationAdmission.model_validate(
            {
                **admission.to_wire(),
                "new_request": admission.new_request.model_copy(update={field: value}).to_wire(),
            }
        )
