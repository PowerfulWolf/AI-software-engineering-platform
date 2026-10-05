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
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationStart,
    DurableInvocationControl,
)
from ai_software_engineer.work_queue.ports import QueueConflict
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.agents.test_openai_compatible import _request


def guard(request: AgentRequest, lease_id: str = "lease_original") -> WorkerExecutionGuard:
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
                        checkpoint_sequence=2,
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
