"""A public Host decision sends a missing planned entry to independent QA."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime
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
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.artifact import Finding
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolutionKind,
    InspectDeliveryWait,
    ResolveDeliveryWait,
)
from ai_software_engineer.domain.enums import FindingSeverity
from ai_software_engineer.manager import production_delivery
from ai_software_engineer.manager.candidate_test_entry_absence import (
    observe_accepted_candidate_test_entry_absence,
)
from ai_software_engineer.manager.delivery import ApproveProductSpec, StartProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.store import MySqlTaskRepository
from tests.manager.test_production_backend import (
    _git,
    _ScriptedDeliveryAdapter,
    _ScriptedStructuredClient,
)
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_public_context_capacity_baseline import public_capacity_host
from tests.orchestration.test_runner import _definitions


@pytest.mark.mysql
def test_public_static_qa_decision_yields_proof_bound_fail_and_coder_retry(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch
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
    current_qa: list[AgentRequest] = []

    def prepare_input(self: CodexCliAgentAdapter, request: AgentRequest) -> None:
        if request.role is AgentRole.QA:
            prepared.append(request)
            fixture_prepare(self, request)
        else:
            fixture_prepare(self, request)

    def run(self: CodexCliAgentAdapter, request: AgentRequest) -> AgentResult:
        if request.role is AgentRole.QA:
            current_qa[:] = [request]
            invoked.append(request)
            return fixture_run(self, request)
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
    assert len(qa_model_calls) == 1
    assert len(host.work_queue.claims_for_work_item(waiting.id)) == 2
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
