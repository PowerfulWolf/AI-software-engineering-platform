"""Public QA/Review capacity resume preserves one candidate and original work allowance."""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.domain import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolutionKind,
    InspectDeliveryWait,
    ResolveDeliveryWait,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.context_capacity import ContextCapacityReceipt
from ai_software_engineer.manager.delivery import ApproveProductSpec, StartProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.verifier_preparation import VerifierPreparationCheckpoint
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from tests.manager.test_production_backend import _git
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_public_context_capacity_baseline import public_capacity_host


@pytest.mark.mysql
@pytest.mark.parametrize("role", [AgentRole.QA, AgentRole.REVIEWER])
@pytest.mark.parametrize("rounds", [1, 2])
def test_public_verifier_capacity_resume_keeps_same_candidate_task_attempt_and_history(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch, role: AgentRole, rounds: int
) -> None:
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    prepared: list[AgentRequest] = []
    invoked: list[AgentRequest] = []
    capacity = True
    host = public_capacity_host(
        tmp_path=tmp_path,
        repository=repository,
        mysql_dsn=mysql_dsn,
        monkeypatch=monkeypatch,
        preparation_requests=prepared,
        invoked=invoked,
        should_reject=lambda request: request.role is role and capacity,
    )
    entry = host.project_entry()
    product = entry.start(
        StartProjectDelivery(repository_root=str(repository), requirement="Update the greeting.")
    ).checkpoint
    checkpoint = entry.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="exact-product",
        )
    ).checkpoint
    assert checkpoint.task_id is not None and checkpoint.stage is DeliveryStage.DELIVERING
    sidecar = host.projects()[0].root / "repositories" / checkpoint.repository_id
    records = KnowledgeRecordStore(sidecar / "state/delivery-preflight", read_only=True)
    invocations = KnowledgeRecordStore(sidecar / "state/invocations", read_only=True)
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        original = tasks.get(checkpoint.task_id)
        events = tasks.list_events(original.id)
    (waiting,) = tuple(
        item
        for item in host.work_queue.items_for_task(original.id)
        if item.status is WorkItemStatus.WAITING_DEPENDENCY
    )
    candidate = host.work_queue.step(waiting.id).boundary.source_revision
    previous_capacity_bytes: dict[Path, bytes] = {}
    previous_ready_bytes: dict[Path, bytes] = {}
    for ordinal in range(1, rounds + 1):
        item = host.work_queue.get(waiting.id)
        assert (
            item.status is WorkItemStatus.WAITING_DEPENDENCY and item.attempt == original.attempts
        )
        disposition = item.wait_disposition
        assert disposition is not None and disposition.facts.classification == "CONTEXT_CAPACITY"
        markers = tuple(
            marker
            for marker in records.list("context-capacity-receipts", ContextCapacityReceipt)
            if marker.role is role
        )
        assert len(markers) == ordinal
        marker = max(markers, key=lambda value: value.dispatch_sequence)
        assert marker.request is not None
        assert not any(
            start.request.run_id == marker.request.run_id
            for start in invocations.list("invocation-starts", DeliveryInvocationStart)
        )
        for path in records.root.glob("context-capacity-receipts-*.json"):
            previous_capacity_bytes.setdefault(path, path.read_bytes())
        for path in records.root.glob("verifier-preparations-*.json"):
            previous_ready_bytes.setdefault(path, path.read_bytes())
        assert all(
            marker.result == "READY"
            for marker in records.list("verifier-preparations", VerifierPreparationCheckpoint)
        )
        command = InspectDeliveryWait(
            work_item_id=item.id,
            expected_disposition_sha256=disposition.disposition_sha256,
            expected_task_intent_sha256=disposition.facts.task_intent_sha256,
            expected_source_revision=candidate,
            expected_checkpoint_sequence=item.checkpoint_sequence,
        )
        proof = host.inspect_delivery_wait(
            command,
            project_id="project_test",
            delivery_id=checkpoint.delivery_id,
        )
        assert not proof.missing and proof.permitted_resolutions == (
            DeliveryResolutionKind.RESUME_UNINVOKED,
        )
        evidence = proof.verifier_preparation
        assert evidence is not None and evidence.budget_source is None
        assert evidence.context_capacity_receipt_sha256 == marker.receipt_sha256
        assert evidence.context_capacity_claim_sha256 == marker.claim_sha256
        assert proof.original_run_id == marker.request.run_id
        assert proof.invocation_start_sha256 is proof.invocation_outcome_sha256 is None
        assert proof.process_stop_sha256 is proof.retry_cause is None
        with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
            assert tasks.get(original.id) == original
            assert tasks.list_events(original.id) == events
        capacity = ordinal < rounds
        resolution = host.resolve_delivery_wait(
            ResolveDeliveryWait.model_validate(
                {
                    **command.to_wire(),
                    "proof_sha256": proof.proof_sha256,
                    "resolution_kind": DeliveryResolutionKind.RESUME_UNINVOKED,
                    "submitted_at": datetime.now(UTC),
                }
            ),
            project_id="project_test",
            delivery_id=checkpoint.delivery_id,
        )
        assert resolution.verifier_preparation == evidence
        assert resolution.retry_failure is None and resolution.retry_cause is None
    delivered = entry.status(checkpoint.delivery_id).checkpoint
    assert delivered.stage is DeliveryStage.DONE and delivered.task_id == original.id
    assert [request.role for request in invoked] == [
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]
    assert all(
        request.source_revision == candidate
        for request in invoked
        if request.role is not AgentRole.CODER
    )
    assert len({request.run_id for request in prepared if request.role is role}) == rounds + 1
    assert len(host.work_queue.claims_for_work_item(waiting.id)) == rounds + 1
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        final = tasks.get(original.id)
    assert final.status is TaskStatus.DONE and final.attempts == original.attempts
    assert final.retry_failures == original.retry_failures and not final.retry_failures
    assert all(path.read_bytes() == body for path, body in previous_capacity_bytes.items())
    assert all(path.read_bytes() == body for path, body in previous_ready_bytes.items())
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    assert (repository / "hello.txt").read_text() == "hello\n"
