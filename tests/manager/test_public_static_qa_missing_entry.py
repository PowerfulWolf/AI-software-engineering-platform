"""A public Host decision sends a missing planned entry to independent QA."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult, StructuredModelResult
from ai_software_engineer.agents.codex_cli import (
    CodexCliAgentAdapter,
    CodexInvocationResult,
    SubprocessCodexCommandRunner,
)
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.domain import (
    AgentRole,
    Evidence,
    EvidenceType,
    QaCriterionStatus,
    QaReportArtifact,
    QaReportStatus,
    Task,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.artifact import Finding
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import (
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolutionKind,
    InspectDeliveryWait,
    ResolveDeliveryWait,
)
from ai_software_engineer.domain.enums import FindingSeverity, TeamRole
from ai_software_engineer.domain.native_verification import NativeVerificationWaitReason
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGapService,
    KnowledgeResolution,
    KnowledgeResolutionSource,
)
from ai_software_engineer.knowledge.models import (
    KnowledgeRunBinding,
    KnowledgeSnapshot,
    digest,
    text_digest,
)
from ai_software_engineer.knowledge.queue import QueueKnowledgeWaitPort
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager import production_delivery
from ai_software_engineer.manager.candidate_test_entry_absence import (
    observe_accepted_candidate_test_entry_absence,
)
from ai_software_engineer.manager.delivery import ApproveProductSpec, StartProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.manager.verifier_preparation import (
    VerifierPreparationCheckpoint,
    VerifierPreparationIntent,
    VerifierPreparationObservation,
)
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from ai_software_engineer.work_queue.models import QueuedWorkItem
from tests.knowledge.test_queue import route as knowledge_route
from tests.manager.test_production_backend import (
    _git,
    _ScriptedDeliveryAdapter,
    _ScriptedStructuredClient,
)
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_public_context_capacity_baseline import public_capacity_host
from tests.orchestration.test_runner import _definitions
from tests.work_queue.test_mysql_queue import demand


def _recover_static_qa_after_knowledge_wait(
    *,
    host: TeamHost,
    task: Task,
    waiting: QueuedWorkItem,
    candidate: str,
    sidecar: Path,
    delivery_id: str,
    original_marker_sha256: str,
) -> None:
    queue = host.work_queue
    dispatch = host.planner_dispatcher(
        demand_builder=demand,
        worker_id="worker_static_qa_recovery_test",
        owner_token_factory=lambda: "static-qa-recovery-owner-token",
    )
    first = dispatch.tick(now=datetime.now(UTC), work_item_id=waiting.id).claim
    assert first is not None and first.work_item.dispatch_sequence == 1
    preflight = KnowledgeRecordStore(sidecar / "state/delivery-preflight")
    original = preflight.get(
        "verifier-preparations", original_marker_sha256, VerifierPreparationCheckpoint
    )
    request = original.request.model_copy(
        update={
            "run_id": "run_static_qa_public_recovery_first",
            "context_manifest_id": "ctx_" + "e" * 64,
        }
    )
    assert request.role is AgentRole.QA and request.source_revision == candidate
    intent = VerifierPreparationIntent.create(
        work_item_id=first.work_item.id,
        lease_id=first.lease.id,
        task_id=task.id,
        task_snapshot_sha256=digest(task.to_wire()),
        checkpoint_sequence=first.work_item.checkpoint_sequence,
        dispatch_sequence=first.work_item.dispatch_sequence,
        request=request,
        request_sha256=digest(request.to_wire()),
        started_at=first.claimed_at,
    )
    preflight.put(
        "verifier-preparation-intents",
        f"{first.work_item.id}:{first.work_item.checkpoint_sequence}:1",
        intent,
    )
    observation = VerifierPreparationObservation(native_execution_state="NOT_STARTED")
    ready_marker = VerifierPreparationCheckpoint.create(
        work_item_id=first.work_item.id,
        lease_id=first.lease.id,
        task_id=task.id,
        task_snapshot_sha256=digest(task.to_wire()),
        checkpoint_sequence=first.work_item.checkpoint_sequence,
        dispatch_sequence=1,
        wait_dispatch_sequence=1,
        wait_lease_id=first.lease.id,
        intent_sha256=intent.intent_sha256,
        source_revision=request.source_revision,
        run_id=request.run_id,
        role=request.role,
        attempt=request.attempt,
        context_manifest_id=request.context_manifest_id,
        request_sha256=intent.request_sha256,
        request=request,
        result="READY",
        observation=observation,
        checked_at=first.claimed_at,
    )
    preflight.put("verifier-preparations", ready_marker.checkpoint_sha256, ready_marker)
    retry_at = first.lease.expires_at + timedelta(seconds=1)
    queue.reclaim_expired(now=first.lease.expires_at, retry_at=retry_at)
    second = dispatch.tick(now=retry_at + timedelta(seconds=1), work_item_id=waiting.id).claim
    assert second is not None and second.work_item.dispatch_sequence == 2
    knowledge = KnowledgeRecordStore(sidecar / "knowledge/runs")
    snapshot = KnowledgeSnapshot.create(
        team_id="team_test",
        project_id="project_test",
        requirement_id=delivery_id,
        repository_ids=(second.work_item.repository_id,),
        documents=(),
    )
    binding = KnowledgeRunBinding(
        run_id="run_knowledge_static_qa_public_recovery",
        task_id=task.id,
        role=TeamRole.QA,
        team_id=snapshot.team_id,
        project_id=snapshot.project_id,
        requirement_id=delivery_id,
        repository_ids=snapshot.repository_ids,
        source_revision=candidate,
        context_manifest_id="ctx_" + "f" * 64,
        snapshot_sha256=snapshot.snapshot_sha256,
    )
    route = knowledge_route(knowledge, binding)
    QueueKnowledgeWaitPort(
        queue,
        claim=second,
        owner_token="static-qa-recovery-owner-token",
        binding=binding,
        records=knowledge,
        clock=lambda: second.claimed_at + timedelta(seconds=1),
    ).wait(binding, route)
    content = "Current static QA checks candidate-tree absence; future real checks stay NOT_RUN."
    resolution = KnowledgeResolution(
        gap_id=route.gap_id,
        previous_run_id=binding.run_id,
        answer=content,
        sources=(
            KnowledgeResolutionSource(
                uri="test://verified-static-qa-scope",
                content=content,
                sha256=text_digest(content),
            ),
        ),
        approval_reference="test://exact-human-decision",
        approved_by="human:local-console",
        resolution_id="0" * 64,
    )
    resolution = resolution.model_copy(
        update={
            "resolution_id": digest(resolution.model_dump(mode="json", exclude={"resolution_id"}))
        }
    )

    class _HumanApproval:
        def require_approval(self, approved: KnowledgeResolution) -> None:
            assert approved == resolution

    KnowledgeGapService(knowledge).resolve(resolution, _HumanApproval())
    third_ready = queue.make_ready(waiting.id, now=second.claimed_at + timedelta(seconds=2))
    third = dispatch.tick(
        now=second.claimed_at + timedelta(seconds=3), work_item_id=third_ready.id
    ).claim
    assert third is not None and third.work_item.dispatch_sequence == 3
    stale_marker = VerifierPreparationCheckpoint.create(
        work_item_id=third.work_item.id,
        lease_id=first.lease.id,
        task_id=task.id,
        task_snapshot_sha256=digest(task.to_wire()),
        checkpoint_sequence=third.work_item.checkpoint_sequence,
        dispatch_sequence=1,
        wait_dispatch_sequence=3,
        wait_lease_id=third.lease.id,
        intent_sha256=intent.intent_sha256,
        source_revision=request.source_revision,
        run_id=request.run_id,
        role=request.role,
        attempt=request.attempt,
        context_manifest_id=request.context_manifest_id,
        request_sha256=intent.request_sha256,
        request=request,
        result="WAIT",
        observation=observation,
        failure_reason=NativeVerificationWaitReason.FACTS_CHANGED,
        checked_at=third.claimed_at,
    )
    preflight.put("verifier-preparations", stale_marker.checkpoint_sha256, stale_marker)
    disposition = decide_delivery_disposition(
        waiting.wait_disposition.facts.model_copy(
            update={
                "classification": "ENGINEERING_AUTHORIZATION",
                "evidence_ids": ("verifier-preparation://" + stale_marker.checkpoint_sha256,),
            }
        )
    )
    queue.wait(
        waiting.id,
        lease_id=third.lease.id,
        owner_token="static-qa-recovery-owner-token",
        status=WorkItemStatus.WAITING_DEPENDENCY,
        reason=disposition.reason,
        disposition=disposition,
        now=third.claimed_at + timedelta(seconds=1),
    )
    command = InspectDeliveryWait(
        work_item_id=waiting.id,
        expected_disposition_sha256=disposition.disposition_sha256,
        expected_task_intent_sha256=task_intent_sha256(task),
        expected_source_revision=candidate,
        expected_checkpoint_sequence=third.work_item.checkpoint_sequence,
    )
    proof = host.inspect_delivery_wait(command, project_id="project_test", delivery_id=delivery_id)
    assert proof.permitted_resolutions == (DeliveryResolutionKind.RESUME_UNINVOKED,), (
        proof.missing,
        proof.verifier_preparation,
    )
    recovered = host.resolve_delivery_wait(
        ResolveDeliveryWait.model_validate(
            {
                **command.to_wire(),
                "proof_sha256": proof.proof_sha256,
                "resolution_kind": DeliveryResolutionKind.RESUME_UNINVOKED,
                "submitted_at": datetime.now(UTC),
            }
        ),
        project_id="project_test",
        delivery_id=delivery_id,
    )
    assert recovered.resolution_kind is DeliveryResolutionKind.RESUME_UNINVOKED
    assert len(queue.claims_for_work_item(waiting.id)) == 5
    assert len(preflight.list("verifier-preparations", VerifierPreparationCheckpoint)) >= 3


@pytest.mark.mysql
@pytest.mark.parametrize("recovery", [False, True])
def test_public_static_qa_decision_yields_proof_bound_fail_and_coder_retry(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch, recovery: bool
) -> None:
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n", encoding="utf-8")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    prepared: list[AgentRequest] = []
    invoked: list[AgentRequest] = []
    qa_model_calls: list[AgentRequest] = []
    host = public_capacity_host(
        tmp_path=tmp_path,
        repository=repository,
        mysql_dsn=mysql_dsn,
        monkeypatch=monkeypatch,
        preparation_requests=prepared,
        invoked=invoked,
        should_reject=lambda request: request.role is AgentRole.CODER and bool(qa_model_calls),
    )

    source_inspection = _ScriptedStructuredClient.complete

    def planned_browser_test(
        self: _ScriptedStructuredClient,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        result = source_inspection(
            self,
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            input_images=input_images,
        )
        if output_schema.get("title") != "TechnicalDesignDraft":
            return result
        payload = dict(result.payload)
        mappings = [
            dict(item) for item in cast(list[dict[str, object]], payload["acceptance_mappings"])
        ]
        mappings[0].update(
            {
                "verification_strategy": "Run the planned browser test against the candidate.",
                "test_levels": ["e2e"],
                "verification_argv": ["node", "--test", "tests/browser.test.cjs"],
                "planned_test_files": ["tests/browser.test.cjs"],
            }
        )
        mappings[0].pop("verification_inspection", None)
        payload["acceptance_mappings"] = mappings
        return StructuredModelResult(payload=payload, duration_ms=result.duration_ms)

    monkeypatch.setattr(_ScriptedStructuredClient, "complete", planned_browser_test)
    fixture_adapter = production_delivery.CodexCliAgentAdapter  # type: ignore[attr-defined]
    fixture_prepare = fixture_adapter.prepare_input
    fixture_run = fixture_adapter.run
    native_prepare = CodexCliAgentAdapter.prepare_input
    native_run = CodexCliAgentAdapter.run
    assert fixture_adapter is not CodexCliAgentAdapter
    current_qa: list[AgentRequest] = []

    def prepare_input(self: CodexCliAgentAdapter, request: AgentRequest) -> None:
        if request.role is AgentRole.QA:
            prepared.append(request)
            native_prepare(self, request)
        else:
            fixture_prepare(self, request)

    def run(self: CodexCliAgentAdapter, request: AgentRequest) -> AgentResult:
        if request.role is AgentRole.QA:
            current_qa[:] = [request]
            invoked.append(request)
            return native_run(self, request)
        return fixture_run(self, request)

    monkeypatch.setattr(fixture_adapter, "prepare_input", prepare_input)
    monkeypatch.setattr(fixture_adapter, "run", run)

    def fake_qa_model(
        self: SubprocessCodexCommandRunner,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
    ) -> CodexInvocationResult:
        del self, environment, timeout_seconds
        assert current_qa and "Trusted static QA evidence" in stdin
        request = current_qa[0]
        proof = re.search(r"static-qa-missing-entry://([0-9a-f]{64})", stdin)
        assert proof is not None
        assert f"SHA-256 {proof.group(1)}" in stdin
        definition = _definitions()[AgentRole.QA].model_copy(
            update={"timeout_seconds": request.timeout_seconds}
        )
        result = _ScriptedDeliveryAdapter(definition, cwd).run(request)
        artifact = result.artifact
        assert isinstance(artifact, QaReportArtifact)
        evidence = Evidence(
            evidence_id="ev_missing_planned_entry",
            type=EvidenceType.FILE,
            uri=proof.group(0),
            description="Frozen planned browser test is absent at the candidate commit.",
            sha256=proof.group(1),
            required=True,
        )
        content = artifact.content.model_copy(
            update={
                "status": QaReportStatus.FAIL,
                "criteria_results": tuple(
                    item.model_copy(
                        update={
                            "status": QaCriterionStatus.FAIL,
                            "evidence_ids": (evidence.evidence_id,),
                        }
                    )
                    for item in artifact.content.criteria_results
                ),
                "tests_run": (),
                "findings": (
                    Finding(
                        finding_id="finding_missing_planned_browser_test",
                        severity=FindingSeverity.MAJOR,
                        code="MISSING_PLANNED_TEST_ENTRY",
                        message="The planned browser test is absent from the candidate tree.",
                        file="tests/browser.test.cjs",
                        evidence_ids=(evidence.evidence_id,),
                    ),
                ),
            }
        )
        artifact = artifact.model_copy(
            update={
                "parent_artifact_ids": (request.input_artifact_ids[1],),
                "evidence": (evidence,),
                "content": content,
            }
        )
        output = Path(argv[argv.index("--output-last-message") + 1])
        output.write_text(json.dumps(artifact.to_wire()), encoding="utf-8")
        qa_model_calls.append(request)
        return CodexInvocationResult(returncode=0)

    monkeypatch.setattr(SubprocessCodexCommandRunner, "run", fake_qa_model)

    entry = host.project_entry()
    product = entry.start(
        StartProjectDelivery(repository_root=str(repository), requirement="Update the greeting.")
    ).checkpoint
    delivering = entry.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="exact-product",
        )
    ).checkpoint
    assert delivering.task_id is not None, (
        delivering.stage,
        delivering.failure_code,
        delivering.failure_summary,
        delivering.next_action,
    )
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        before = tasks.get(delivering.task_id)
    (waiting,) = tuple(
        item
        for item in host.work_queue.items_for_task(delivering.task_id)
        if item.status is WorkItemStatus.WAITING_DEPENDENCY
    )
    assert waiting.role is AgentRole.QA
    candidate = host.work_queue.step(waiting.id).boundary.source_revision
    disposition = waiting.wait_disposition
    assert disposition is not None
    command = InspectDeliveryWait(
        work_item_id=waiting.id,
        expected_disposition_sha256=disposition.disposition_sha256,
        expected_task_intent_sha256=disposition.facts.task_intent_sha256,
        expected_source_revision=candidate,
        expected_checkpoint_sequence=waiting.checkpoint_sequence,
    )
    proof = host.inspect_delivery_wait(
        command, project_id="project_test", delivery_id=delivering.delivery_id
    )
    sidecar = host.projects()[0].root / "repositories" / delivering.repository_id
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        observation = observe_accepted_candidate_test_entry_absence(
            repository_root=repository,
            task=before,
            repository=tasks,
            source_revision=candidate,
            accepted=host.work_queue.accepted(before.id),
            artifacts=FileArtifactStore(sidecar / "artifacts", read_only=True),
        )
    assert observation.missing[0].path == "tests/browser.test.cjs"
    assert proof.permitted_resolutions == (DeliveryResolutionKind.STATIC_QA_MISSING_ENTRY,), (
        proof.missing,
        proof.verifier_preparation,
        proof.static_qa_missing_entry,
        disposition.facts.classification,
    )
    assert proof.verifier_preparation is not None
    assert proof.verifier_preparation.native_execution_state == "NOT_STARTED"
    assert proof.static_qa_missing_entry is not None
    assert proof.static_qa_missing_entry.candidate_revision == candidate
    assert not qa_model_calls
    if recovery:
        original_resume = host._resume_delivery_once
        monkeypatch.setattr(host, "_resume_delivery_once", lambda *_args, **_kwargs: None)
    resolution = host.resolve_delivery_wait(
        ResolveDeliveryWait.model_validate(
            {
                **command.to_wire(),
                "proof_sha256": proof.proof_sha256,
                "resolution_kind": DeliveryResolutionKind.STATIC_QA_MISSING_ENTRY,
                "submitted_at": datetime.now(UTC),
            }
        ),
        project_id="project_test",
        delivery_id=delivering.delivery_id,
    )
    assert resolution.resolution_kind is DeliveryResolutionKind.STATIC_QA_MISSING_ENTRY
    if recovery:
        monkeypatch.setattr(host, "_resume_delivery_once", original_resume)
        _recover_static_qa_after_knowledge_wait(
            host=host,
            task=before,
            waiting=waiting,
            candidate=candidate,
            sidecar=sidecar,
            delivery_id=delivering.delivery_id,
            original_marker_sha256=proof.verifier_preparation.preparation_checkpoint_sha256,
        )
    if recovery:
        markers = KnowledgeRecordStore(sidecar / "state/delivery-preflight").list(
            "verifier-preparations", VerifierPreparationCheckpoint
        )
        current_queue = host.work_queue.get(waiting.id)
        diagnosis = (
            current_queue.status,
            current_queue.wait_reason,
            [
                (marker.result, marker.failure_reason, marker.wait_dispatch_sequence)
                for marker in markers
            ],
        )
    else:
        diagnosis = None
    assert len(qa_model_calls) == 1, diagnosis
    assert len(host.work_queue.claims_for_work_item(waiting.id)) == (5 if recovery else 2)
    if recovery:
        (final_claim,) = tuple(
            claim
            for claim in host.work_queue.claims_for_work_item(waiting.id)
            if claim.work_item.id == waiting.id and claim.work_item.dispatch_sequence == 4
        )
        assert final_claim.work_item.dispatch_sequence == 4
        qa_start = KnowledgeRecordStore(sidecar / "state/invocations").get(
            "invocation-starts", waiting.id, DeliveryInvocationStart
        )
        assert qa_start.lease_id == final_claim.lease.id
        assert qa_start.request == qa_model_calls[0]
        assert any(
            marker.result == "READY"
            and marker.wait_dispatch_sequence == 4
            and marker.lease_id == final_claim.lease.id
            for marker in markers
        )
    assert [request.role for request in invoked[:2]] == [AgentRole.CODER, AgentRole.QA]
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        after = tasks.get(delivering.task_id)
    assert after.attempts == before.attempts + 1, "only the ordinary Coder rework consumes work"
    assert after.retry_failures == before.retry_failures
    assert after.status in (TaskStatus.IMPLEMENTING, TaskStatus.CONTINUE_REQUIRED)
    qa_records = tuple(
        record
        for record in host.work_queue.accepted(after.id)
        if record.run_id == qa_model_calls[0].run_id
    )
    assert len(qa_records) == 1
    qa = FileArtifactStore(sidecar / "artifacts", read_only=True).get(
        qa_records[0].receipt.artifact_id
    )
    assert isinstance(qa, QaReportArtifact)
    assert qa.content.status is QaReportStatus.FAIL and not qa.content.tests_run
    assert qa.content.findings[0].code == "MISSING_PLANNED_TEST_ENTRY"
    assert entry.status(delivering.delivery_id).checkpoint.stage is DeliveryStage.DELIVERING
    assert not (repository / "tests/browser.test.cjs").exists()
