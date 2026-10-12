"""Claimed final-input stops have a public same-Task PAUSE/RESUME path."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult, StructuredModelResult
from ai_software_engineer.agents.codex_cli import CodexCliAgentAdapter
from ai_software_engineer.agents.model_input import FinalModelInputCapacityExceeded
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.context import ContextStoreError
from ai_software_engineer.domain import (
    AgentRole,
    Evidence,
    EvidenceType,
    QaReportArtifact,
    QaTestRun,
    QaTestStatus,
    ReviewReportArtifact,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode
from ai_software_engineer.execution import SubprocessCommandExecutor
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager import production_backend, production_delivery
from ai_software_engineer.manager.baseline_production import (
    BaselineContinueCommand,
    BaselineExecuteCommand,
    BaselineProposeCommand,
    BaselineQuiescenceProof,
)
from ai_software_engineer.manager.context_capacity import ContextCapacityReceipt
from ai_software_engineer.manager.delivery import ApproveProductSpec, StartProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.delivery_preflight import DeliveryPreflightReceipt
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.orchestration.continuation_models import ContinuationRejected
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from tests.domain.factories import make_plan_artifact
from tests.manager.test_production_backend import (
    _git,
    _git_output,
    _ScriptedClientFactory,
    _ScriptedDeliveryAdapter,
    _ScriptedStructuredClient,
)
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.orchestration.test_runner import _definitions


def _assert_refused_capacity_proposals(
    host: TeamHost,
    command: BaselineProposeCommand,
    sidecar: Path,
    marker: ContextCapacityReceipt,
) -> None:
    """Exercise exact public refusals without leaving fixture observations changed."""
    item_before = host.work_queue.get(marker.work_item_id)

    def refuse(error: type[Exception] | tuple[type[Exception], ...], match: str) -> None:
        with pytest.raises(error, match=match):
            host.propose_execution_baseline(command, project_id="project_test")
        assert host.work_queue.get(marker.work_item_id) == item_before
        assert not host.work_queue.list_active_leases(now=datetime.now(UTC))

    root = sidecar / "state/delivery-preflight"
    marker_path = root / KnowledgeRecordStore._name(
        "context-capacity-receipts", marker.receipt_sha256
    )
    original_marker_bytes = marker_path.read_bytes()
    marker_path.unlink()
    try:
        refuse(ValueError, "停止记录.*claim")
    finally:
        marker_path.write_bytes(original_marker_bytes)
    # Fully re-sealing content cannot replace the original real queue claim.
    changed = marker.model_copy(update={"claim_sha256": "f" * 64})
    changed = changed.model_copy(
        update={
            "receipt_sha256": digest(changed.model_dump(mode="json", exclude={"receipt_sha256"}))
        }
    )
    replacement = root / KnowledgeRecordStore._name(
        "context-capacity-receipts", changed.receipt_sha256
    )
    marker_path.unlink()
    try:
        KnowledgeRecordStore(root).put("context-capacity-receipts", changed.receipt_sha256, changed)
        refuse(ValueError, "真实 claim")
    finally:
        replacement.unlink(missing_ok=True)
        marker_path.write_bytes(original_marker_bytes)
    context_path = sidecar / "contexts" / f"{marker.context_manifest_id}.json"
    context_bytes = context_path.read_bytes()
    context_path.unlink()
    try:
        refuse(ContextStoreError, "Context manifest not found")
    finally:
        context_path.write_bytes(context_bytes)
    # A conflicting real-looking model start is evidence against no-start recovery.
    request = marker.request
    assert request is not None
    start = DeliveryInvocationStart(
        work_item_id=marker.work_item_id,
        checkpoint_sequence=marker.checkpoint_sequence,
        request=request,
        lease_id=marker.lease_id,
        started_at=marker.observed_at,
        start_sha256="0" * 64,
    )
    start = start.model_copy(
        update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
    )
    invocations = sidecar / "state/invocations"
    start_path = invocations / KnowledgeRecordStore._name("invocation-starts", marker.work_item_id)
    try:
        KnowledgeRecordStore(invocations).put("invocation-starts", marker.work_item_id, start)
        refuse(ValueError, "原调用结果|模型开始或结果")
    finally:
        start_path.unlink(missing_ok=True)
    # No SQL acceptance is necessary for a sealed role producer to contradict
    # claimed no-start. Ordinary accepted-input filtering must not hide this fact.
    original_plan = make_plan_artifact()
    stranded = seal_artifact(
        original_plan.model_copy(
            update={
                "artifact_id": "art_stranded_capacity",
                "task_id": marker.task_id,
                "source_revision": marker.source_revision,
                "context_manifest_id": request.context_manifest_id,
                "producer": original_plan.producer.model_copy(
                    update={
                        "run_id": request.run_id,
                    }
                ),
            }
        ),
        validated_at=marker.observed_at,
    )
    raw_artifacts = FileArtifactStore(sidecar / "artifacts")
    raw_artifacts.put(stranded)
    try:
        refuse(ValueError, "角色产出")
    finally:
        (sidecar / "artifacts" / (stranded.artifact_id + ".json")).unlink()
    native_root = sidecar / "state/continuations" / marker.task_id
    assert native_root.is_dir()
    # Orphan or corrupt native records cannot be treated as evidence of no invocation.
    for prefix in ("capture-stop", "receipt", "admission"):
        native_path = native_root / f"{prefix}-{request.run_id}.json"
        assert not native_path.exists()
        native_path.write_text("{}")
        try:
            refuse((ValueError, ContinuationRejected), "原生执行记录|continuation record")
        finally:
            native_path.unlink()
    saved_native_root = native_root.with_name("preserved-native-ledger")
    native_root.rename(saved_native_root)
    try:
        native_root.symlink_to(native_root.with_name("missing-native-ledger"))
        try:
            refuse(ValueError, "symlink")
        finally:
            native_root.unlink()
        native_root.write_text("unreadable native ledger")
        try:
            refuse(
                (ValueError, ContinuationRejected),
                "记录目录不可读取|directory is missing or unsafe",
            )
        finally:
            native_root.unlink()
    finally:
        saved_native_root.rename(native_root)
    assert marker_path.read_bytes() == original_marker_bytes
    assert context_path.read_bytes() == context_bytes
    assert json.loads(original_marker_bytes)["record"] == marker.to_wire()


def public_capacity_host(
    *,
    tmp_path: Path,
    repository: Path,
    mysql_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    preparation_requests: list[AgentRequest],
    invoked: list[AgentRequest],
    should_reject: Callable[[AgentRequest], bool],
) -> TeamHost:
    original_complete = _ScriptedStructuredClient.complete

    def source_inspection(
        self: _ScriptedStructuredClient,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        result = original_complete(
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
        payload["acceptance_mappings"] = [
            {
                "acceptance_criterion_id": "ac_001_001",
                "verification_strategy": "Inspect the exact candidate greeting.",
                "test_levels": ["inspection"],
                "verification_inspection": {
                    "kind": "source",
                    "paths": ["hello.txt"],
                    "checklist": ["Compare the candidate greeting to the approved format."],
                },
            }
        ]
        return StructuredModelResult(payload=payload, duration_ms=0)

    class CapacityThenDelivery(CodexCliAgentAdapter):
        def prepare_input(self, request: AgentRequest) -> None:
            preparation_requests.append(request)
            if should_reject(request):
                assert self._input_budget is not None
                maximum = self._input_budget._resolver.get_context(
                    request.context_manifest_id
                ).budget.max_input_tokens
                raise FinalModelInputCapacityExceeded(
                    estimated_input_tokens=maximum + 1, max_input_tokens=maximum
                )

        def run(self, request: AgentRequest) -> AgentResult:
            invoked.append(request)
            definition = _definitions()[request.role].model_copy(
                update={
                    "id": self._agent_id,
                    "version": self._agent_version,
                    "timeout_seconds": request.timeout_seconds,
                    "permissions": request.permissions,
                }
            )
            result = _ScriptedDeliveryAdapter(definition, self._workspace_root).run(request)
            if request.role is AgentRole.CODER:
                return result
            artifact = result.artifact
            assert isinstance(artifact, (QaReportArtifact, ReviewReportArtifact))
            command = ("git", "show", f"{request.source_revision}:hello.txt")
            observed = SubprocessCommandExecutor(
                self._workspace_root,
                request.permissions,
                execution_guard=self._execution_guard,
            ).run(command, timeout_seconds=5)
            assert observed.returncode == 0 and observed.stdout == "hello from the team\n"
            evidence_path = tmp_path / f"verification-{request.run_id}.json"
            evidence_path.write_text(observed.model_dump_json())
            evidence = Evidence(
                evidence_id=f"ev_{request.run_id.removeprefix('run_')}",
                type=EvidenceType.TEST if request.role is AgentRole.QA else EvidenceType.COMMAND,
                uri=evidence_path.as_uri(),
                description="Independent candidate greeting inspection.",
                sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            )
            if isinstance(artifact, QaReportArtifact):
                artifact = artifact.model_copy(
                    update={
                        "evidence": (evidence,),
                        "content": artifact.content.model_copy(
                            update={
                                "criteria_results": tuple(
                                    item.model_copy(
                                        update={"evidence_ids": (evidence.evidence_id,)}
                                    )
                                    for item in artifact.content.criteria_results
                                ),
                                "tests_run": (
                                    QaTestRun(
                                        command=" ".join(command),
                                        status=QaTestStatus.PASS,
                                        evidence_id=evidence.evidence_id,
                                        duration_ms=observed.duration_ms,
                                    ),
                                ),
                            }
                        ),
                    }
                )
            else:
                artifact = artifact.model_copy(
                    update={
                        "evidence": (evidence,),
                        "content": artifact.content.model_copy(
                            update={"evidence": (evidence.evidence_id,)}
                        ),
                    }
                )
            return result.model_copy(update={"artifact": artifact})

    monkeypatch.setattr(
        production_backend, "ConfiguredStructuredClientFactory", lambda *_: _ScriptedClientFactory()
    )
    monkeypatch.setattr(_ScriptedStructuredClient, "complete", source_inspection)
    monkeypatch.setattr(production_delivery, "CodexCliAgentAdapter", CapacityThenDelivery)
    host = TeamHost(
        config=ProductionConfig(
            platform_root=str(tmp_path / "platform"),
            default_project_id="project_test",
            default_project_name="Test Project",
            live_model_execution=True,
            model_routes=(
                ProviderRouteConfig(
                    provider="codex", model="gpt-primary", kind=ModelProviderKind.CODEX_CLI
                ),
            ),
        ),
        environment={
            "ASE_MYSQL_DSN": mysql_dsn,
            "PATH": os.environ.get("PATH", os.defpath),
            "GIT_AUTHOR_NAME": "ASE Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "ASE Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        },
        structured_clients=_ScriptedClientFactory(),
        delivery_route_adapters=production_delivery.ConfiguredDeliveryRouteAdapterFactory(),
    )
    return host


@pytest.mark.mysql
@pytest.mark.parametrize("rounds", [1, 2])
def test_public_capacity_pause_resume_preserves_one_task_and_independent_delivery(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch, rounds: int
) -> None:
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    source = _git_output("rev-parse", "HEAD", cwd=repository)
    preparation_requests: list[AgentRequest] = []
    invoked: list[AgentRequest] = []
    capacity = True
    host = public_capacity_host(
        tmp_path=tmp_path,
        repository=repository,
        mysql_dsn=mysql_dsn,
        monkeypatch=monkeypatch,
        preparation_requests=preparation_requests,
        invoked=invoked,
        should_reject=lambda request: request.role is AgentRole.CODER and capacity,
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
    invocation_records = KnowledgeRecordStore(sidecar / "state/invocations", read_only=True)
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        original_task = tasks.get(checkpoint.task_id)
        original_events = tasks.list_events(original_task.id)
        revision = tasks.current_revision(original_task.id)
    (original_item,) = host.work_queue.items_for_task(original_task.id)
    frozen_capacity_bytes: dict[Path, bytes] = {}
    for ordinal in range(1, rounds + 1):
        item = host.work_queue.get(original_item.id)
        assert item.status is WorkItemStatus.WAITING_DEPENDENCY
        assert item.wait_disposition is not None
        assert item.wait_disposition.facts.classification == "CONTEXT_CAPACITY"
        assert not invoked and not host.work_queue.list_active_leases(now=datetime.now(UTC))
        markers = records.list("context-capacity-receipts", ContextCapacityReceipt)
        assert len(markers) == ordinal
        for path in (sidecar / "state/delivery-preflight").glob("context-capacity-receipts-*.json"):
            frozen_capacity_bytes.setdefault(path, path.read_bytes())
        assert not invocation_records.list("invocation-starts", DeliveryInvocationStart)
        assert all(
            value.status == "READY"
            for value in records.list("preflight-receipts", DeliveryPreflightReceipt)
        )
        (repository / "tooling.txt").write_text(f"updated platform baseline {ordinal}\n")
        _git("add", "tooling.txt", cwd=repository)
        _git("commit", "-m", f"platform baseline fix {ordinal}", cwd=repository)
        target = _git_output("rev-parse", "HEAD", cwd=repository)
        command = BaselineProposeCommand(
            delivery_id=checkpoint.delivery_id,
            task_id=original_task.id,
            expected_task_intent_sha256=task_intent_sha256(original_task),
            expected_task_revision=revision,
            expected_work_item_id=item.id,
            expected_source_revision=source,
            target_base_ref=target,
        )
        latest = max(markers, key=lambda marker: marker.dispatch_sequence)
        if ordinal == 1 and rounds == 1:
            _assert_refused_capacity_proposals(host, command, sidecar, latest)
            with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
                assert tasks.get(original_task.id) == original_task
                assert tasks.list_events(original_task.id) == original_events
        plan = host.propose_execution_baseline(command, project_id="project_test")
        assert plan.facts.context_capacity_receipt_sha256 == latest.receipt_sha256
        reservation = plan.facts.continuation
        assert reservation is not None and reservation.retry_cause == "uninvoked"
        assert reservation.current_attempt == reservation.next_execution_attempt == 1
        assert reservation.reservation_already_applied and reservation.retry_failure is None
        proofs = KnowledgeRecordStore(
            sidecar / "state/execution-baselines" / original_task.id, read_only=True
        ).get("baseline-quiescence", plan.facts.quiescence_proof_sha256, BaselineQuiescenceProof)
        (proof,) = proofs.invocations
        assert proof.proof_kind == "claimed_context_capacity"
        assert len(proof.context_capacity_receipt_sha256s) == ordinal
        assert proof.start_sha256 is proof.outcome_sha256 is None
        with pytest.raises(ValueError, match="容量恢复需先"):
            host.execute_execution_baseline(
                BaselineExecuteCommand(
                    delivery_id=checkpoint.delivery_id,
                    task_id=original_task.id,
                    expected_plan_sha256=plan.plan_sha256,
                    reference="not-paused",
                ),
                project_id="project_test",
            )
        binding = host.execute_execution_baseline(
            BaselineExecuteCommand(
                delivery_id=checkpoint.delivery_id,
                task_id=original_task.id,
                expected_plan_sha256=plan.plan_sha256,
                reference="exact-capacity-pause",
                continuation_mode=BaselineContinuationMode.PAUSE,
            ),
            project_id="project_test",
        )
        paused = host.work_queue.get(item.id)
        assert paused.wait_disposition is not None
        assert paused.wait_disposition.facts.classification == "EXECUTION_BASELINE_PAUSED"
        assert paused.dispatch_sequence > item.dispatch_sequence and paused.attempt == 1
        with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
            assert tasks.get(original_task.id) == original_task
            assert tasks.list_events(original_task.id) == original_events
        assert not invoked
        capacity = ordinal < rounds
        source = binding.execution_source_revision
        host.continue_execution_baseline(
            BaselineContinueCommand(
                delivery_id=checkpoint.delivery_id,
                task_id=original_task.id,
                expected_task_intent_sha256=task_intent_sha256(original_task),
                expected_task_revision=revision,
                expected_work_item_id=paused.id,
                expected_source_revision=source,
                expected_execution_baseline_sha256=binding.binding_sha256,
                expected_disposition_sha256=paused.wait_disposition.disposition_sha256,
                reference="explicit-capacity-resume",
            ),
            project_id="project_test",
        )
    delivered = entry.status(checkpoint.delivery_id).checkpoint
    assert delivered.stage is DeliveryStage.DONE and delivered.task_id == original_task.id
    assert [request.role for request in invoked] == [
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]
    assert len({request.run_id for request in preparation_requests}) == rounds + 3
    assert (
        len({claim.lease.id for claim in host.work_queue.claims_for_work_item(original_item.id)})
        == rounds + 1
    )
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        final = tasks.get(original_task.id)
        assert final.status is TaskStatus.DONE and final.attempts == 1 and not final.retry_failures
    assert all(path.read_bytes() == content for path, content in frozen_capacity_bytes.items())
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    assert (repository / "hello.txt").read_text() == "hello\n"
