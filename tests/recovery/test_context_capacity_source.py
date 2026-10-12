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


@pytest.mark.parametrize("fact", ("start", "outcome", "route"))
def test_capacity_absence_proof_rejects_actual_durable_invocation_and_keeps_prior_attempt(
    tmp_path: Path,
    fact: str,
) -> None:
    from ai_software_engineer.agents import AgentErrorCode, FileModelRouteAttemptStore
    from ai_software_engineer.agents.fallback import ModelRouteAttempt, model_route_root
    from ai_software_engineer.knowledge.models import digest
    from ai_software_engineer.knowledge.store import KnowledgeRecordStore
    from ai_software_engineer.recovery.context_capacity import LegacyContextCapacitySourceReader
    from ai_software_engineer.work_queue.invocation import (
        DeliveryInvocationOutcome,
        DeliveryInvocationStart,
    )
    from tests.agents.test_fallback import _failed
    from tests.orchestration.test_native_continuation import claim

    _, task, context, _, request = _fixture(tmp_path)
    task = task.model_copy(update={"attempts": 2})
    owner = claim(task, 2)
    records = KnowledgeRecordStore(tmp_path / "state/invocations")
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
    else:
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
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    with pytest.raises(ValueError):
        LegacyContextCapacitySourceReader._require_no_start(tmp_path, task, owner)
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
