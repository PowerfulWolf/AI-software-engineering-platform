"""Engineering continuation is frozen intent, never a retroactive Task permission."""

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.agents.models import AgentErrorCode, AgentFailure, AgentResult
from ai_software_engineer.domain.continuation import (
    InterruptionContinuationPolicy,
    task_intent_sha256,
)
from ai_software_engineer.domain.project_delivery import derive_delivery_task
from ai_software_engineer.domain.task import Task, task_matches_dispatch
from ai_software_engineer.manager.dispatch import DispatchPreviewStale, ManagerDispatchService
from ai_software_engineer.planning.preview import PlanningPreviewService
from ai_software_engineer.scheduling import PortfolioScheduler
from tests.domain.factories import make_task
from tests.manager.test_contracts import NOW, stage_chain
from tests.manager.test_dispatch import RecordingDispatchStore, _facts, _router, _service


def test_legacy_task_omits_continuation_policy_from_wire_and_default_dump() -> None:
    task = make_task()
    original = task.to_wire()
    assert task.interruption_continuation_policy is None
    assert "interruption_continuation_policy" not in original
    assert "interruption_continuation_policy" not in task.model_dump(mode="json")
    assert Task.model_validate(original).to_wire() == original
    explicit_none = Task.model_validate({**original, "interruption_continuation_policy": None})
    assert explicit_none.model_dump(mode="json") == task.model_dump(mode="json")


def test_engineering_policy_has_fixed_version_capability_and_canonical_identity() -> None:
    policy = InterruptionContinuationPolicy()
    payload = policy.to_wire()
    assert payload == {
        "kind": "interruption_continuation_policy",
        "schema_version": "v1",
        "authorization_source": "organization_engineering_policy",
        "capability_id": "git-text-mutation-inventory-v1",
        "max_continuations": 1,
        "allowed_causes": ["local_execution_limit", "provider_transient"],
        "allowed_changes": ["text_added", "text_modified"],
    }
    expected = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()
    assert policy.policy_sha256 == expected
    assert InterruptionContinuationPolicy.model_validate(payload).policy_sha256 == expected
    with pytest.raises(ValueError):
        policy.max_continuations = 2


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", "v2"),
        ("authorization_source", "manager_model"),
        ("capability_id", "unverified_shell"),
        ("max_continuations", 0),
        ("max_continuations", 2),
        ("max_continuations", True),
        ("max_continuations", "1"),
        ("allowed_causes", ["unknown_crash"]),
        ("allowed_causes", ["provider_transient", "local_execution_limit"]),
        ("allowed_changes", ["text_added", "text_modified", "deleted"]),
        ("allowed_changes", ["text_modified", "text_added"]),
        ("can_change_verdict", True),
    ),
)
def test_policy_rejects_expanded_or_ambiguous_authority(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        InterruptionContinuationPolicy.model_validate(
            {**InterruptionContinuationPolicy().to_wire(), field: value}
        )


def test_frozen_continuation_policy_never_uses_legacy_retry_compatibility() -> None:
    legacy = make_task()
    current = Task.model_validate(
        {
            **legacy.to_wire(),
            "interruption_continuation_policy": InterruptionContinuationPolicy().to_wire(),
        }
    )
    assert not task_matches_dispatch(current, legacy)
    assert not task_matches_dispatch(current, legacy, allow_legacy_retry_policy=True)
    assert not task_matches_dispatch(legacy, current, allow_legacy_retry_policy=True)
    assert task_matches_dispatch(current.model_copy(update={"attempts": 1}), current)


def test_task_intent_fingerprint_excludes_execution_facts_but_binds_authority() -> None:
    task = make_task()
    executing = task.model_copy(
        update={
            "status": "IMPLEMENTING",
            "attempts": 1,
            "updated_at": task.updated_at + timedelta(seconds=1),
            "retry_failures": (),
        }
    )
    assert task_intent_sha256(executing) == task_intent_sha256(task)
    for field, value in (
        ("base_ref", "f" * 40),
        ("branch_name", "ai/feature/changed-intent"),
        ("constraints", None),
        ("repository", "/workspace/foreign"),
        ("acceptance_criteria", ()),
        ("metadata", {"repository_id": "repository_foreign"}),
        ("max_attempts", 10),
        ("interruption_continuation_policy", InterruptionContinuationPolicy()),
    ):
        assert task_intent_sha256(task.model_copy(update={field: value})) != task_intent_sha256(
            task
        ), field


def test_approved_chain_freezes_supplied_policy_without_changing_approval(tmp_path: Path) -> None:
    prepared, req, product, approval, design, plan = stage_chain(tmp_path)
    original_approval = approval.to_wire()
    task = derive_delivery_task(
        prepared,
        req,
        product,
        approval,
        design,
        plan,
        task_id="task_continuation_001",
        repository=prepared.repository_root,
        base_ref="a" * 40,
        max_attempts=3,
        created_at=NOW,
        interruption_continuation_policy=InterruptionContinuationPolicy(),
    )
    assert task.interruption_continuation_policy == InterruptionContinuationPolicy()
    assert approval.to_wire() == original_approval
    assert task.acceptance_criteria == product.acceptance_criteria


def test_dispatch_freezes_exact_preview_policy_and_rejects_removed_authority(
    tmp_path: Path,
) -> None:
    legacy_request, snapshot = _facts(tmp_path)
    assert "interruption_continuation_policy" not in legacy_request.model_dump(mode="json")
    request = legacy_request.model_copy(
        update={"interruption_continuation_policy": InterruptionContinuationPolicy()}
    )
    task = ManagerDispatchService._derive_task(request)
    preview_service = PlanningPreviewService(scheduler=PortfolioScheduler(), model_router=_router())
    preview = preview_service.preview(
        task=task,
        work_item=snapshot.work_item,
        execution_plan=request.execution_plan,
        agents=snapshot.agents,
        active_leases=snapshot.active_leases,
        assignments=snapshot.assignments,
        policies=snapshot.model_policies,
        previewed_at=request.planning_preview.previewed_at,
    )
    request = request.model_copy(update={"planning_preview": preview})
    store = RecordingDispatchStore()
    record = _service(store, snapshot, request).commit_dispatch(request)
    assert record.task.interruption_continuation_policy == request.interruption_continuation_policy
    record.validate_integrity()
    without_authority = request.model_copy(update={"interruption_continuation_policy": None})
    with pytest.raises(DispatchPreviewStale, match="Task lineage"):
        _service(store, snapshot, without_authority).commit_dispatch(without_authority)
    assert store.records == [record]


def test_work_interrupted_is_not_inline_transient_failure_or_timeout_result() -> None:
    error = AgentFailure(
        code=AgentErrorCode.WORK_INTERRUPTED,
        message="草稿已保留; 等待新执行核验。",
        transient=False,
    )
    result_payload = {
        "run_id": "run_interrupted_001",
        "task_id": "task_interrupted_001",
        "role": "coder",
        "attempt": 1,
        "source_revision": "a" * 40,
        "context_manifest_id": "ctx_" + "b" * 64,
        "status": "FAILED",
        "error": error.to_wire(),
    }
    assert AgentResult.model_validate(result_payload).error == error
    with pytest.raises(ValueError, match=r"interrupted|interruption|WORK_INTERRUPTED"):
        AgentFailure.model_validate({**error.to_wire(), "transient": True})
    with pytest.raises(ValueError):
        AgentResult.model_validate({**result_payload, "status": "TIMED_OUT"})
