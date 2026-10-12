"""No-start legacy capacity observations preserve their exact Context and epoch."""

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.context.models import ContextBudget, ContextSection
from tests.recovery.test_terminal_baseline_context import _fixture


def test_legacy_capacity_context_requires_real_claim_and_complete_latest_patch(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.recovery.context_capacity import validate_capacity_context

    _, task, context, epoch, _ = _fixture(tmp_path)
    claim = {
        "task_id": task.id,
        "work_item_id": "work_capacity_original",
        "lease_id": "lease_capacity_original",
        "assignment_id": "assignment_capacity_original",
        "role": "coder",
        "attempt": 2,
        "dispatch_sequence": 1,
        "checkpoint_sequence": 3,
    }
    body = json.dumps(claim)
    section = ContextSection(
        name="source:execution.claim",
        uri="claim://lease_capacity_original",
        sha256=hashlib.sha256(body.encode()).hexdigest(),
        tokens=1,
        content=body,
        priority=1,
    )
    context = context.model_copy(
        update={
            "sections": (*context.sections, section),
            "budget": ContextBudget(
                max_input_tokens=100, reserved_output_tokens=99, used_input_tokens=2
            ),
        }
    )
    observed = validate_capacity_context(
        task=task.model_copy(update={"attempts": 2}),
        context=context,
        epoch=epoch,
        terminal_at=context.built_at + timedelta(seconds=1),
    )
    assert observed.claim.work_item_id == "work_capacity_original"
    assert observed.complete.complete_patch == "retained complete patch\n"
    assert observed.available_input_tokens == 1

    for changed in (
        context.model_copy(update={"attempt": 1}),
        context.model_copy(update={"source_revision": "e" * 40}),
        context.model_copy(update={"sections": context.sections[:1]}),
        context.model_copy(
            update={
                "budget": ContextBudget(
                    max_input_tokens=100, reserved_output_tokens=0, used_input_tokens=2
                )
            }
        ),
        context.model_copy(
            update={
                "sections": (*context.sections[:1], section.model_copy(update={"truncated": True}))
            }
        ),
    ):
        with pytest.raises(ValueError):
            validate_capacity_context(
                task=task.model_copy(update={"attempts": 2}),
                context=changed,
                epoch=epoch,
                terminal_at=context.built_at + timedelta(seconds=1),
            )


@pytest.mark.parametrize("fact", ("start", "outcome", "route", "artifact"))
def test_capacity_absence_proof_rejects_actual_durable_invocation_and_keeps_prior_attempt(
    tmp_path: Path,
    fact: str,
) -> None:
    from ai_software_engineer.agents import AgentErrorCode, FileModelRouteAttemptStore
    from ai_software_engineer.agents.fallback import ModelRouteAttempt, model_route_root
    from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
    from ai_software_engineer.context import FileContextStore
    from ai_software_engineer.context.store import _manifest_digest
    from ai_software_engineer.knowledge.models import digest
    from ai_software_engineer.knowledge.store import KnowledgeRecordStore
    from ai_software_engineer.recovery.context_capacity import LegacyContextCapacitySourceReader
    from ai_software_engineer.work_queue.invocation import (
        DeliveryInvocationOutcome,
        DeliveryInvocationStart,
    )
    from tests.agents.test_fallback import _failed
    from tests.domain.factories import NOW, make_coder_progress_artifact, make_plan_artifact
    from tests.orchestration.test_native_continuation import claim

    _, task, context, _, request = _fixture(tmp_path)
    task = task.model_copy(update={"attempts": 2})
    owner = claim(task, 2)
    records = KnowledgeRecordStore(tmp_path / "state/invocations")
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    contexts = FileContextStore(tmp_path / "contexts")
    prior_context = context.model_copy(update={"attempt": 1})
    prior_context = prior_context.model_copy(
        update={"context_id": "ctx_" + _manifest_digest(prior_context)}
    )
    contexts.put(prior_context)
    parent = make_plan_artifact().model_copy(update={"task_id": task.id})
    artifacts.put(seal_artifact(parent, validated_at=NOW))
    prior = make_coder_progress_artifact().model_copy(
        update={"task_id": task.id, "context_manifest_id": prior_context.context_id}
    )
    artifacts.put(seal_artifact(prior, validated_at=NOW))
    old_request = request.model_copy(update={"attempt": 1, "run_id": "run_capacity_prior"})
    old = DeliveryInvocationStart(
        work_item_id="work_capacity_prior",
        checkpoint_sequence=1,
        request=old_request,
        lease_id="lease_capacity_prior",
        started_at=context.built_at,
        start_sha256="0" * 64,
    )
    old = old.model_copy(
        update={"start_sha256": digest(old.model_dump(mode="json", exclude={"start_sha256"}))}
    )
    records.put("invocation-starts", old.work_item_id, old)
    LegacyContextCapacitySourceReader._require_no_start(tmp_path, task, owner)
    start = DeliveryInvocationStart(
        work_item_id=owner.work_item.id,
        checkpoint_sequence=3,
        request=request,
        lease_id=owner.lease.id,
        started_at=context.built_at,
        start_sha256="0" * 64,
    )
    start = start.model_copy(
        update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
    )
    if fact == "start":
        records.put("invocation-starts", start.work_item_id, start)
    elif fact == "outcome":
        outcome = DeliveryInvocationOutcome(
            start=start,
            result=_failed(request, AgentErrorCode.TIMEOUT, transient=False),
            outcome_sha256="0" * 64,
        )
        outcome = outcome.model_copy(
            update={
                "outcome_sha256": digest(
                    outcome.model_dump(mode="json", exclude={"outcome_sha256"})
                )
            }
        )
        records.put("invocation-outcomes", start.work_item_id, outcome)
    elif fact == "route":
        route = ModelRouteAttempt.create(
            request=request,
            route_index=1,
            provider="offline",
            model="offline",
            started_at=context.built_at,
            completed_at=context.built_at,
            result=_failed(request, AgentErrorCode.TIMEOUT, transient=False),
            fallback=False,
        )
        FileModelRouteAttemptStore(model_route_root(tmp_path)).append(route)
    else:
        current_context = context.model_copy(
            update={"context_id": "ctx_" + _manifest_digest(context)}
        )
        contexts.put(current_context)
        current = prior.model_copy(
            update={
                "artifact_id": "art_capacity_current",
                "producer": prior.producer.model_copy(update={"run_id": "run_capacity_current"}),
                "context_manifest_id": current_context.context_id,
            }
        )
        artifacts.put(seal_artifact(current, validated_at=NOW))
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    with pytest.raises(ValueError):
        LegacyContextCapacitySourceReader._require_no_start(tmp_path, task, owner)
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*.json")}


@pytest.mark.parametrize(
    "fact",
    (
        "receipt_current",
        "receipt_claim_alias",
        "admission_current",
        "admission_claim_alias",
        "receipt_corrupt",
        "admission_corrupt",
    ),
)
def test_capacity_no_start_rejects_current_or_invalid_continuation_facts(
    tmp_path: Path, fact: str
) -> None:
    from ai_software_engineer.artifacts import FileArtifactStore
    from ai_software_engineer.orchestration.continuation_models import (
        ContinuationAdmission,
        ContinuationRejected,
        ExecutionInterruptionReceipt,
    )
    from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
    from ai_software_engineer.recovery.context_capacity import LegacyContextCapacitySourceReader
    from tests.domain.factories import make_task
    from tests.orchestration.test_continuation_records import make_admission, make_receipt
    from tests.orchestration.test_native_continuation import claim

    receipt = make_receipt(tmp_path)
    attempts = 1 if fact == "receipt_current" else 2 if fact.endswith("current") else 3
    task = make_task().model_copy(update={"id": receipt.request.task_id, "attempts": attempts})
    owner = claim(task, attempts)
    FileArtifactStore(tmp_path / "artifacts")
    directory = tmp_path / "state/continuations"
    directory.mkdir(parents=True)
    ledger = FileContinuationStore.initialize(directory / task.id, task_id=task.id)
    if fact == "receipt_claim_alias":
        receipt = ExecutionInterruptionReceipt.create(
            **{**receipt.to_wire(), "original_work_item_id": owner.work_item.id}
        )
    ledger.put_receipt(receipt)
    admission = make_admission(receipt)
    if fact == "admission_claim_alias":
        admission = ContinuationAdmission.create(
            **{**admission.to_wire(), "next_work_item_id": owner.work_item.id}
        )
    if fact.startswith("admission"):
        ledger.put_admission(admission)
    if fact.endswith("corrupt"):
        (directory / task.id / f"{fact.split('_')[0]}.json").write_text("{}")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    with pytest.raises((ValueError, ContinuationRejected)):
        LegacyContextCapacitySourceReader._require_no_start(tmp_path, task, owner)
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*.json")}


def test_capacity_no_start_keeps_earlier_receipts_and_admissions(tmp_path: Path) -> None:
    from ai_software_engineer.artifacts import FileArtifactStore
    from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
    from ai_software_engineer.recovery.context_capacity import LegacyContextCapacitySourceReader
    from tests.domain.factories import make_task
    from tests.orchestration.test_continuation_records import make_admission, make_receipt
    from tests.orchestration.test_native_continuation import claim

    receipt = make_receipt(tmp_path)
    task = make_task().model_copy(update={"id": receipt.request.task_id, "attempts": 3})
    FileArtifactStore(tmp_path / "artifacts")
    directory = tmp_path / "state/continuations"
    directory.mkdir(parents=True)
    ledger = FileContinuationStore.initialize(directory / task.id, task_id=task.id)
    ledger.put_receipt(receipt)
    ledger.put_admission(make_admission(receipt))
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    LegacyContextCapacitySourceReader._require_no_start(tmp_path, task, claim(task, 3))
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*.json")}


@pytest.mark.parametrize(
    "fault",
    (
        "none",
        "original_plan",
        "earlier",
        "source",
        "reason",
        "from",
        "to",
        "attempt",
        "binding_time",
        "minimum_attempt",
        "prior_revision",
        "artifact",
    ),
)
def test_capacity_source_compatibility_is_only_exact_last_legacy_event(
    tmp_path: Path, fault: str
) -> None:
    from ai_software_engineer.domain import TaskStatus
    from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
    from ai_software_engineer.recovery.baseline_source import RecoveryBaselineEpoch
    from ai_software_engineer.recovery.context_capacity import (
        LEGACY_CAPACITY_REASON,
        _CapacityNativeRecoverySourceReader,
    )
    from ai_software_engineer.recovery.native import NativeRecoverySourceReader
    from tests.domain.factories import make_state_event

    _, task, _, epoch, _ = _fixture(tmp_path)
    task = task.model_copy(update={"attempts": 2, "status": TaskStatus.BLOCKED})
    binding = ExecutionBaselineBinding.create(
        **{**epoch.binding.to_wire(), "prior_task_revision": 2}
    )
    events = tuple(
        make_state_event(event_id=f"evt_capacity_{index}").model_copy(
            update={
                "task_id": task.id,
                "from_status": before,
                "to_status": after,
                "attempt": 2 if index == 3 else 1,
                "reason": LEGACY_CAPACITY_REASON if index == 3 else "plan_validated",
                "source_revision": task.base_ref,
                "artifact_ids": (),
                "occurred_at": binding.completed_at + timedelta(seconds=index - 2),
            }
        )
        for index, before, after in (
            (1, TaskStatus.NEW, TaskStatus.PLANNING),
            (2, TaskStatus.PLANNING, TaskStatus.IMPLEMENTING),
            (3, TaskStatus.IMPLEMENTING, TaskStatus.BLOCKED),
        )
    )
    minimum = 2
    if fault == "original_plan":
        events = (
            events[0],
            events[1].model_copy(update={"artifact_ids": ("art_original_plan",)}),
            events[2].model_copy(update={"artifact_ids": ("art_original_plan",)}),
        )
    elif fault == "earlier":
        events = (events[0].model_copy(update={"source_revision": "f" * 40}), *events[1:])
    elif fault in {"source", "reason", "from", "to", "attempt", "artifact"}:
        change: dict[str, object] = {
            "source": {"source_revision": "f" * 40},
            "reason": {"reason": "another_terminal_error"},
            "from": {"from_status": TaskStatus.CONTINUE_REQUIRED},
            "to": {"to_status": TaskStatus.FAILED},
            "attempt": {"attempt": 1},
            "artifact": {"artifact_ids": ("art_output_001",)},
        }[fault]
        events = (*events[:2], events[2].model_copy(update=change))
    elif fault == "binding_time":
        binding = ExecutionBaselineBinding.create(
            **{**binding.to_wire(), "completed_at": events[-1].occurred_at + timedelta(seconds=1)}
        )
    elif fault == "minimum_attempt":
        minimum = 3
    elif fault == "prior_revision":
        binding = ExecutionBaselineBinding.create(**{**binding.to_wire(), "prior_task_revision": 3})
    epochs = (RecoveryBaselineEpoch(binding, minimum),)
    original = tuple(event.to_wire() for event in events)
    with pytest.raises(ValueError):
        NativeRecoverySourceReader._validate_pre_candidate_sources(task, events, epochs)
    if fault in {"none", "original_plan"}:
        _CapacityNativeRecoverySourceReader._validate_pre_candidate_sources(task, events, epochs)
    else:
        with pytest.raises(ValueError):
            _CapacityNativeRecoverySourceReader._validate_pre_candidate_sources(
                task, events, epochs
            )
    assert original == tuple(event.to_wire() for event in events)
