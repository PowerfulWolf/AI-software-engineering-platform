"""A real forward knowledge refusal crosses public Host recovery and fresh delivery."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.agents.structured import (
    FallbackStructuredModelClient,
    StructuredModelClient,
    StructuredModelResult,
    StructuredModelRoute,
)
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolutionKind,
    InspectDeliveryWait,
    ResolveDeliveryWait,
)
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, TeamRole, WorkItemStatus
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationOutcome,
    invocation_lane_sha256,
    read_paused_preparation,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.delivery import ApproveProductSpec, StartProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.owned_processes import HostOwnedProcessRegistry
from ai_software_engineer.service_pause import ServicePauseControl
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from tests.manager.test_production_backend import _git, _ScriptedClientFactory
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_public_context_capacity_baseline import public_capacity_host


@pytest.fixture
def owned_processes() -> Iterator[HostOwnedProcessRegistry]:
    registry = HostOwnedProcessRegistry()
    with registry.operation_scope("operation_public_knowledge_fixture_owned"):
        yield registry
    registry.require_stopped()


@pytest.mark.mysql
def test_public_forward_knowledge_pause_retains_attempt_then_delivers_independently(
    tmp_path: Path,
    mysql_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    owned_processes: HostOwnedProcessRegistry,
) -> None:
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    prepared: list[AgentRequest] = []
    invoked: list[AgentRequest] = []
    host = public_capacity_host(
        tmp_path=tmp_path,
        repository=repository,
        mysql_dsn=mysql_dsn,
        monkeypatch=monkeypatch,
        preparation_requests=prepared,
        invoked=invoked,
        should_reject=lambda _: False,
    )
    original_factory = _ScriptedClientFactory.for_project
    pause = ServicePauseControl(grace_seconds=0)
    pause_observed = False
    provider_calls = 0

    class PausingKnowledge:
        def __init__(self, delegate: StructuredModelClient) -> None:
            self.fallback = FallbackStructuredModelClient(
                (StructuredModelRoute(provider="fixture", model="fixture", client=delegate),),
                role=TeamRole.CODER,
            )

        def complete(
            self,
            *,
            instructions: str,
            input_payload: Mapping[str, object],
            output_schema: Mapping[str, object],
            timeout_seconds: int,
            input_images: tuple[Path, ...] = (),
        ) -> StructuredModelResult:
            nonlocal pause_observed, provider_calls
            if not pause_observed and output_schema.get("title") == "KnowledgeIntent":
                pause_observed = True
                pause.request(request_id="pause_public_knowledge", instance_id="instance_fixture")
            else:
                provider_calls += 1
            # The actual Fallback pre-route Host guard produces the raw receipt;
            # this fixture never constructs, seals or edits a recovery receipt.
            return self.fallback.complete(
                instructions=instructions,
                input_payload=input_payload,
                output_schema=output_schema,
                timeout_seconds=timeout_seconds,
                input_images=input_images,
            )

    def for_project(
        self: _ScriptedClientFactory,
        repository_root: Path,
        role: TeamRole = TeamRole.PRODUCT,
    ) -> StructuredModelClient:
        delegate = original_factory(self, repository_root, role)
        return PausingKnowledge(delegate) if role is TeamRole.CODER else delegate

    monkeypatch.setattr(_ScriptedClientFactory, "for_project", for_project)
    entry = host.project_entry()
    product = entry.start(
        StartProjectDelivery(repository_root=str(repository), requirement="Update the greeting.")
    ).checkpoint
    with pause.operation_scope("operation_public_knowledge_pause"):
        checkpoint = entry.approve(
            ApproveProductSpec(
                delivery_id=product.delivery_id,
                expected_checkpoint_sha256=product.checkpoint_sha256,
                approval_reference="exact-product",
            )
        ).checkpoint
    assert checkpoint.task_id is not None and checkpoint.stage is DeliveryStage.DELIVERING
    assert pause_observed and not provider_calls and not invoked
    sidecar = host.projects()[0].root / "repositories" / checkpoint.repository_id
    records = KnowledgeRecordStore(sidecar / "knowledge/runs", read_only=True)
    invocations = KnowledgeRecordStore(sidecar / "state/invocations", read_only=True)
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        original_task = tasks.get(checkpoint.task_id)
        original_events = tasks.list_events(original_task.id)
    (waiting,) = host.work_queue.items_for_task(original_task.id)
    assert waiting.status is WorkItemStatus.WAITING_DEPENDENCY
    disposition = waiting.wait_disposition
    assert disposition is not None and disposition.facts.classification == "SERVICE_PAUSED"
    assert len(disposition.facts.evidence_ids) == 1
    pause_id = disposition.facts.evidence_ids[0].removeprefix("knowledge-pause://")
    outcome = read_paused_preparation(records.root, pause_id)
    original_claim = outcome.intent.claim
    assert original_claim is not None
    assert outcome.pre_admission_pause is not None and not outcome.executions
    assert not invocations.list("invocation-starts", DeliveryInvocationStart)
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    old_bytes = {path: path.read_bytes() for path in records.root.rglob("*.json")}
    command = InspectDeliveryWait(
        work_item_id=waiting.id,
        expected_disposition_sha256=disposition.disposition_sha256,
        expected_task_intent_sha256=disposition.facts.task_intent_sha256,
        expected_source_revision=disposition.facts.source_revision,
        expected_checkpoint_sequence=waiting.checkpoint_sequence,
    )
    pause.cancel()
    proof = host.inspect_delivery_wait(
        command, project_id="project_test", delivery_id=checkpoint.delivery_id
    )
    assert not proof.missing
    assert proof.permitted_resolutions == (DeliveryResolutionKind.RESUME_UNINVOKED,)
    assert proof.knowledge_pause is not None
    assert proof.knowledge_pause.outcome_sha256 == pause_id
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        assert tasks.get(original_task.id) == original_task
        assert tasks.list_events(original_task.id) == original_events
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
    assert resolution.knowledge_pause == proof.knowledge_pause
    assert resolution.retry_cause is None and resolution.retry_failure is None
    delivered = entry.status(checkpoint.delivery_id).checkpoint
    assert delivered.stage is DeliveryStage.DONE and delivered.task_id == original_task.id
    assert [request.role for request in invoked] == [
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]
    assert delivered.candidate_revision is not None
    assert all(
        request.source_revision == delivered.candidate_revision
        for request in invoked
        if request.role in {AgentRole.QA, AgentRole.REVIEWER}
    )
    claims = host.work_queue.claims_for_work_item(waiting.id)
    assert len(claims) == 2
    fresh = max(claims, key=lambda value: value.work_item.dispatch_sequence)
    assert fresh.lease.id != original_claim.lease.id
    assert fresh.work_item.attempt == original_claim.work_item.attempt == original_task.attempts
    assert fresh.work_item.dispatch_sequence == original_claim.work_item.dispatch_sequence + 1
    lane = KnowledgeRecordStore(
        records.root / "invocations" / invocation_lane_sha256(outcome.intent.binding),
        read_only=True,
    )
    successors = tuple(
        value
        for value in lane.list("knowledge-invocation-outcomes", KnowledgeInvocationOutcome)
        if value.intent.claim is not None and value.intent.claim.lease.id == fresh.lease.id
    )
    assert successors and all(value.state == "RETURNED" for value in successors)
    assert all(
        value.intent.binding.run_id != outcome.intent.binding.run_id
        and value.intent.binding.context_manifest_id != outcome.intent.binding.context_manifest_id
        for value in successors
    )
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        final = tasks.get(original_task.id)
    assert final.status is TaskStatus.DONE and final.attempts == original_task.attempts
    assert final.retry_failures == original_task.retry_failures
    assert all(path.read_bytes() == body for path, body in old_bytes.items())
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    assert not owned_processes.snapshot()
    assert (repository / "hello.txt").read_text() == "hello\n"
