"""Semantic carry never captures legitimate knowledge or existing failure routing."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents.structured import StructuredModelError
from ai_software_engineer.context import ContextSource, FileContextBuilder, FileContextStore
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.knowledge.agents import KnowledgeConsultationService
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationJournal,
    KnowledgeInvocationUncertain,
)
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.rejected_knowledge_preparation import carry_rejected_knowledge
from tests.agents.test_openai_compatible import _coder_request
from tests.domain.factories import make_task
from tests.knowledge.test_assessment_rejection import _native_executable
from tests.knowledge.test_invocation_native import _actual_claim, _client
from tests.knowledge.test_retrieval_contract import binding, document, snapshot


@pytest.mark.parametrize("mode", ["empty_queries", "valid", "local_limit", "unknown"])
def test_native_preparation_guard_leaves_existing_nonsemantic_paths_alone(
    tmp_path: Path, mode: str
) -> None:
    frozen = snapshot(document())
    bound = binding(frozen)
    claim = _actual_claim(bound)
    task = make_task().model_copy(
        update={
            "id": bound.task_id,
            "repository": str(tmp_path),
            "base_ref": bound.source_revision,
            "status": TaskStatus.IMPLEMENTING,
            "attempts": 1,
        }
    )
    context = FileContextBuilder(
        tmp_path,
        _coder_request().permissions,
        sources=(
            ContextSource(
                source_id="execution.claim",
                uri="claim://" + claim.lease.id,
                required=True,
                content=json.dumps(
                    {
                        "task_id": task.id,
                        "work_item_id": claim.work_item.id,
                        "lease_id": claim.lease.id,
                        "assignment_id": claim.assignment.id,
                        "dispatch_sequence": claim.work_item.dispatch_sequence,
                        "role": AgentRole.CODER.value,
                        "attempt": claim.work_item.attempt,
                        "checkpoint_sequence": claim.work_item.checkpoint_sequence,
                    }
                ),
            ),
        ),
    ).build(task, AgentRole.CODER, attempt=1)
    FileContextStore(tmp_path / "contexts").put(context)
    bound = bound.model_copy(
        update={
            "context_manifest_id": context.context_id,
            "run_id": "run_knowledge_" + digest((context.context_id, frozen.snapshot_sha256))[:32],
        }
    )
    records = KnowledgeRecordStore(tmp_path / "knowledge" / "runs")
    records.put("snapshots", frozen.snapshot_sha256, frozen)
    executable = _native_executable(tmp_path, unsafe=mode == "unknown")
    source = executable.read_text()
    if mode == "empty_queries":
        source = source.replace("['original payment']", "[]")
    elif mode == "valid":
        source = source.replace("citation['document_id'] = 'doc_unread'", "pass")
        source = source.replace("'status': 'GAP'", "'status': 'SUFFICIENT'")
    elif mode == "local_limit":
        source = source.replace(
            "prompt = sys.stdin.read()", "import time; time.sleep(4)\nprompt = sys.stdin.read()"
        )
    executable.write_text(source)
    service = KnowledgeConsultationService(
        _client(tmp_path, executable, bound.role),
        records,
        allow_repository_inspection=True,
        invocation_journal=KnowledgeInvocationJournal(records, claimed=lambda: claim),
    )
    payload = {"task": task.to_wire(), "context": context.to_wire()}
    if mode in {"local_limit", "unknown"}:
        with pytest.raises((StructuredModelError, KnowledgeInvocationUncertain)):
            service.consult(bound, frozen, payload, timeout_seconds=1)
    else:
        service.consult(bound, frozen, payload, timeout_seconds=1)
    before = {str(path): path.read_bytes() for path in records.root.rglob("*.json")}
    queue, artifacts, git = Mock(), Mock(), Mock()
    carry_rejected_knowledge(
        task=task,
        step=Mock(),
        claim=claim,
        records=records,
        state=tmp_path / "state",
        queue=queue,
        artifacts=artifacts,
        git=git,
        scope=EngineeringScope(
            team_id=bound.team_id,
            project_id=bound.project_id,
            repository_id=bound.repository_ids[0],
            repository_root=str(tmp_path),
        ),
        requirement_id=bound.requirement_id,
    )
    assert {str(path): path.read_bytes() for path in records.root.rglob("*.json")} == before
    assert not queue.mock_calls and not artifacts.mock_calls and not git.mock_calls
    assert not (tmp_path / "state").exists()


def test_unproven_semantic_refusal_defers_to_real_worker_at_last_work_attempt(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.artifacts import FileArtifactStore
    from ai_software_engineer.domain.retry_policy import DeliveryRetryPolicy
    from ai_software_engineer.knowledge.assessment_rejection import KnowledgeAssessmentRejected
    from ai_software_engineer.orchestration import FileRunContextBuilder, RetryingOrchestrator
    from ai_software_engineer.orchestration.state_machine import build_event
    from ai_software_engineer.store import SqliteTaskRepository
    from tests.orchestration.test_execution_retry_budget import budget_task
    from tests.orchestration.test_retry import AttemptIdentityFactory, ScriptedAdapter
    from tests.orchestration.test_runner import _clock, _definitions

    class Waiting(Exception):
        pass

    control = Mock()
    control.wait.side_effect = Waiting
    task = budget_task(tmp_path / "project", DeliveryRetryPolicy(max_work_attempts=1))
    with SqliteTaskRepository(tmp_path / "state.sqlite") as repository:
        repository.create(task)
        repository.record_attempt(task.id, 1)
        for index, status in enumerate((TaskStatus.PLANNING, TaskStatus.IMPLEMENTING)):
            repository.append_event(
                build_event(
                    repository.get(task.id),
                    status,
                    event_id=f"evt_semantic_unproven_{index}",
                    reason="fixture",
                    source_revision=task.base_ref,
                    occurred_at=_clock(),
                )
            )
        current = repository.get(task.id)
        assert current.work_budget_exhausted
        runner = RetryingOrchestrator(
            repository=repository,
            artifact_store=FileArtifactStore(tmp_path / "artifacts"),
            context_builder=FileRunContextBuilder(Path(task.repository)),
            agent_adapter=ScriptedAdapter(),
            agent_definitions=_definitions(),
            identities=AttemptIdentityFactory(),
            clock=_clock,
            delivery_failure_control=control,
        )
        with pytest.raises(KnowledgeAssessmentRejected):
            runner._knowledge_failure(current, KnowledgeAssessmentRejected("CLAIM_WITHOUT_READ"))
        assert not control.wait.called
        assert repository.get(task.id) == current
