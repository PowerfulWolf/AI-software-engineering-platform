"""Restart safety at the sealed invocation window, independent of model or SQL."""

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from ai_software_engineer.agents.continuation import ContinuationExecutionUncertain
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentOutputContractError,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
    DurableInvocationControl,
)
from ai_software_engineer.work_queue.ports import QueueConflict
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.agents.test_openai_compatible import _request
from tests.domain.factories import make_coder_progress_artifact


def guard(
    request: AgentRequest, lease_id: str = "lease_original", *, checkpoint_sequence: int = 2
) -> WorkerExecutionGuard:
    return cast(
        WorkerExecutionGuard,
        SimpleNamespace(
            check=lambda: None,
            write_scope=nullcontext,
            lease=SimpleNamespace(
                claim=SimpleNamespace(
                    work_item=SimpleNamespace(
                        id="work_invocation_001",
                        task_id=request.task_id,
                        role=request.role,
                        attempt=request.attempt,
                        checkpoint_sequence=checkpoint_sequence,
                    ),
                    lease=SimpleNamespace(id=lease_id),
                )
            ),
        ),
    )


@pytest.mark.parametrize("role", [AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER])
def test_restart_cannot_recall_an_invocation_without_a_result(
    tmp_path: Path, role: AgentRole
) -> None:
    request = _request(role)
    first = DurableInvocationControl(KnowledgeRecordStore(tmp_path), guard(request))
    assert first.prepare(request) == request
    after_restart = DurableInvocationControl(
        KnowledgeRecordStore(tmp_path), guard(request, "lease_new")
    )
    replacement = request.model_copy(
        update={"run_id": "run_replacement_001", "context_manifest_id": "ctx_" + "a" * 64}
    )
    with pytest.raises(ContinuationExecutionUncertain):
        after_restart.prepare(replacement)
    assert len(after_restart.records.list("invocation-starts", DeliveryInvocationStart)) == 1


@pytest.mark.parametrize("role", [AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER])
def test_restart_replays_exact_recorded_result_with_original_run_and_context(
    tmp_path: Path, role: AgentRole
) -> None:
    request = _request(role)
    control = DurableInvocationControl(KnowledgeRecordStore(tmp_path), guard(request))
    control.prepare(request)
    result = AgentResult(
        run_id=request.run_id,
        task_id=request.task_id,
        role=request.role,
        attempt=request.attempt,
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        status=AgentRunStatus.FAILED,
        error=AgentFailure(
            code=AgentErrorCode.PROVIDER_UNAVAILABLE, message="提供方暂时不可用", transient=True
        ),
    )
    control.completed(request, result)
    restarted = DurableInvocationControl(
        KnowledgeRecordStore(tmp_path), guard(request, "lease_new")
    )
    proposed = request.model_copy(
        update={"run_id": "run_unused_001", "context_manifest_id": "ctx_" + "a" * 64}
    )
    admitted = restarted.prepare(proposed)
    assert admitted == request
    assert restarted.result(admitted) == result
    restarted.completed(admitted, result)
    with pytest.raises(QueueConflict, match="inputs"):
        restarted.prepare(proposed.model_copy(update={"source_revision": "a" * 40}))
    with pytest.raises(QueueConflict, match="request"):
        restarted.result(proposed)


def test_claim_scope_is_required_before_a_journal_write(tmp_path: Path) -> None:
    request = _request(AgentRole.CODER)
    control = DurableInvocationControl(KnowledgeRecordStore(tmp_path), guard(request))
    with pytest.raises(QueueConflict, match="claimed"):
        control.prepare(request.model_copy(update={"attempt": 2}))
    assert tuple(tmp_path.iterdir()) == ()


def _progress_result(request: AgentRequest, sequence: int) -> AgentResult:
    template = make_coder_progress_artifact()
    artifact = template.model_copy(
        update={
            "task_id": request.task_id,
            "source_revision": request.source_revision,
            "context_manifest_id": request.context_manifest_id,
            "producer": template.producer.model_copy(update={"run_id": request.run_id}),
            "content": template.content.model_copy(update={"checkpoint_sequence": sequence}),
        }
    )
    return AgentResult(
        run_id=request.run_id,
        task_id=request.task_id,
        role=request.role,
        attempt=request.attempt,
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        status=AgentRunStatus.SUCCEEDED,
        artifact=artifact,
    )


def test_valid_progress_uses_attempt_even_when_queue_checkpoint_differs(tmp_path: Path) -> None:
    request = _request(AgentRole.CODER).model_copy(update={"attempt": 4})
    control = DurableInvocationControl(
        KnowledgeRecordStore(tmp_path), guard(request, checkpoint_sequence=8)
    )
    control.prepare(request)
    result = _progress_result(request, 4)
    control.completed(request, result)
    assert control.result(request) == result


@pytest.mark.parametrize("sequence", [8, 9])
def test_new_invocation_cannot_seal_a_progress_sequence_from_queue_checkpoint(
    tmp_path: Path, sequence: int
) -> None:
    request = _request(AgentRole.CODER).model_copy(update={"attempt": 4})
    control = DurableInvocationControl(
        KnowledgeRecordStore(tmp_path), guard(request, checkpoint_sequence=8)
    )
    control.prepare(request)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    with pytest.raises(AgentOutputContractError) as captured:
        control.completed(request, _progress_result(request, sequence))
    assert captured.value.result.error is not None
    assert captured.value.result.error.code is AgentErrorCode.INVALID_OUTPUT
    assert not captured.value.result.error.transient
    assert captured.value.result.artifact is None
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_invalid_historical_progress_remains_hash_readable_but_cannot_replay(
    tmp_path: Path,
) -> None:
    request = _request(AgentRole.CODER).model_copy(update={"attempt": 4})
    control = DurableInvocationControl(
        KnowledgeRecordStore(tmp_path), guard(request, checkpoint_sequence=8)
    )
    control.prepare(request)
    start = control.records.get("invocation-starts", "work_invocation_001", DeliveryInvocationStart)
    original = DeliveryInvocationOutcome(
        start=start, result=_progress_result(request, 9), outcome_sha256="0" * 64
    )
    original = original.model_copy(
        update={
            "outcome_sha256": digest(original.model_dump(mode="json", exclude={"outcome_sha256"}))
        }
    )
    control.records.put("invocation-outcomes", "work_invocation_001", original)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert control.prepare(request) == request
    with pytest.raises(AgentOutputContractError) as captured:
        control.result(request)
    assert captured.value.result.status is AgentRunStatus.FAILED
    assert captured.value.result.artifact is None
    preserved = control.records.get(
        "invocation-outcomes", "work_invocation_001", DeliveryInvocationOutcome
    )
    preserved.validate_integrity()
    assert preserved == original
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
