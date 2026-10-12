"""Public joint-parent knowledge lineage survives exact source baseline recovery."""

from __future__ import annotations

import json
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentRequest, StructuredModelResult
from ai_software_engineer.agents.model_diagnostics import model_call_phase
from ai_software_engineer.agents.openai_compatible import HttpResponse
from ai_software_engineer.agents.structured import (
    FallbackStructuredModelClient,
    StructuredModelRoute,
)
from ai_software_engineer.context import ContextBundle
from ai_software_engineer.domain import AgentDefinition, AgentRole, Artifact, Task, TeamRole
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.enums import TaskStatus, WorkItemStatus
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode
from ai_software_engineer.knowledge.context import snapshot_from_sources
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationJournal,
    KnowledgeInvocationOutcome,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.models import KnowledgeRunBinding, digest
from ai_software_engineer.knowledge.preparation_retry import claim_identity_sha256
from ai_software_engineer.knowledge.runtime import KnowledgeRunContextBuilder
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_production import (
    BaselineContinueCommand,
    BaselineExecuteCommand,
    BaselineProposeCommand,
    BaselineQuiescenceProof,
)
from ai_software_engineer.manager.delivery import ApproveProductSpec, ReplyToProduct
from ai_software_engineer.manager.delivery_checkpoint import DeliveryStage
from ai_software_engineer.manager.production_agents import ExecutionPlanDraft, TechnicalDesignDraft
from ai_software_engineer.multi_directory.models import JointStage
from ai_software_engineer.multi_directory.models import digest as joint_digest
from ai_software_engineer.multi_directory.scope import DirectoryScope
from ai_software_engineer.multi_directory.service import CreateRequirement
from ai_software_engineer.store import MySqlTaskRepository
from tests.knowledge.test_invocation_native import _http_client, _HttpTransport
from tests.manager.test_production_backend import (
    _git,
    _git_output,
    _ScriptedClientFactory,
    _ScriptedStructuredClient,
)
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_public_context_capacity_baseline import public_capacity_host


class _RecordedClients:
    """Produce offline typed consultation through actual HTTP observation machinery."""

    def for_project(self, repository_root: Path, role: TeamRole) -> FallbackStructuredModelClient:
        scripted = _ScriptedClientFactory().for_project(repository_root, role)

        class Client:
            def complete(
                self,
                *,
                instructions: str,
                input_payload: Mapping[str, object],
                output_schema: Mapping[str, object],
                timeout_seconds: int,
                input_images: tuple[Path, ...] = (),
            ) -> StructuredModelResult:
                result = scripted.complete(
                    instructions=instructions,
                    input_payload=input_payload,
                    output_schema=output_schema,
                    timeout_seconds=timeout_seconds,
                    input_images=input_images,
                )
                body = {
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": json.dumps(dict(result.payload))}
                            ],
                        }
                    ]
                }
                transport = _HttpTransport(
                    HttpResponse(status_code=200, body=json.dumps(body).encode()),
                    before_return=lambda: None,
                )
                return _http_client(transport, "fixture-model").complete(
                    instructions=instructions,
                    input_payload=input_payload,
                    output_schema=output_schema,
                    timeout_seconds=timeout_seconds,
                    input_images=input_images,
                )

        return FallbackStructuredModelClient(
            (StructuredModelRoute(provider="fixture", model="fixture-model", client=Client()),),
            role=role,
        )


@pytest.mark.mysql
def test_public_parent_knowledge_failure_then_capacity_recovers_same_task_to_done(
    tmp_path: Path, mysql_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Genuine approved parent, claimed 503, capacity, public PAUSE/RESUME, native QA/Review."""
    repository = tmp_path / "target"
    repository.mkdir()
    (repository / "hello.txt").write_text("hello\n")
    _git("init", "-b", "main", cwd=repository)
    _git("add", "hello.txt", cwd=repository)
    _git("commit", "-m", "initial", cwd=repository)
    capacity = True
    preparation: list[AgentRequest] = []
    invoked: list[AgentRequest] = []
    failed_bindings: list[KnowledgeRunBinding] = []
    original_build = KnowledgeRunContextBuilder.build

    def prepare(
        self: KnowledgeRunContextBuilder,
        task: Task,
        agent: AgentDefinition,
        *,
        attempt: int,
        candidate_revision: str | None = None,
        input_artifacts: tuple[Artifact, ...] = (),
    ) -> ContextBundle:
        if failed_bindings or agent.role is not AgentRole.CODER:
            self.clients = _RecordedClients()
            return original_build(
                self,
                task,
                agent,
                attempt=attempt,
                candidate_revision=candidate_revision,
                input_artifacts=input_artifacts,
            )
        base = self.delegate.build(
            task,
            agent,
            attempt=attempt,
            candidate_revision=candidate_revision,
            input_artifacts=input_artifacts,
        )
        # Use the exact production source mapping. The public workflow below
        # creates and independently approves this source; no parent is invented.
        parent_ids = {
            source.uri.split("/")[2] for source in self.sources if source.uri.startswith("joint://")
        }
        assert len(parent_ids) == 1
        (parent_id,) = parent_ids
        assert parent_id.startswith("delivery_multi_") and parent_id != task.id
        frozen = snapshot_from_sources(
            team_id=self.team_id,
            project_id=self.project_id,
            requirement_id=parent_id,
            repository_ids=(self.repository_id,),
            sources=tuple((self.repository_id, source) for source in self.sources),
        )
        self.records.put("snapshots", frozen.snapshot_sha256, frozen)
        binding = KnowledgeRunBinding(
            run_id="run_knowledge_" + digest((base.context_id, frozen.snapshot_sha256))[:32],
            task_id=task.id,
            role=TeamRole.CODER,
            team_id=self.team_id,
            project_id=self.project_id,
            requirement_id=parent_id,
            repository_ids=(self.repository_id,),
            source_revision=base.source_revision,
            context_manifest_id=base.context_id,
            snapshot_sha256=frozen.snapshot_sha256,
        )
        failed_bindings.append(binding)
        transport = _HttpTransport(
            HttpResponse(status_code=503, body=b'{"error":{"message":"Unavailable"}}'),
            before_return=lambda: None,
        )
        client = FallbackStructuredModelClient(
            (
                StructuredModelRoute(
                    provider="fixture",
                    model="fixture-model",
                    client=_http_client(transport, "fixture-model"),
                ),
            ),
            role=TeamRole.CODER,
        )
        with model_call_phase("knowledge_assessment"):
            KnowledgeInvocationJournal(self.records, claimed=self.invocation_claim).call(
                binding,
                "assessment",
                client=client,
                instructions="Read-only preparation of the actually approved joint requirement",
                input_payload={},
                output_schema={"type": "object", "properties": {}},
                timeout_seconds=2,
            )
        raise AssertionError("HTTP 503 preparation must stop before the main Coder invocation")

    monkeypatch.setattr(KnowledgeRunContextBuilder, "build", prepare)
    host = public_capacity_host(
        tmp_path=tmp_path,
        repository=repository,
        mysql_dsn=mysql_dsn,
        monkeypatch=monkeypatch,
        preparation_requests=preparation,
        invoked=invoked,
        should_reject=lambda request: request.role is AgentRole.CODER and capacity,
    )
    # Extend the existing offline provider at its ordinary typed seam. Single
    # repository requirements still use the public joint Product/Design/Plan gate.
    simple_complete = _ScriptedStructuredClient.complete
    stage_calls: list[str] = []

    def joint_complete(
        self: _ScriptedStructuredClient,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        title = output_schema.get("title")
        if title not in {"JointTechnicalDesign", "JointExecutionPlan"}:
            return simple_complete(
                self,
                instructions=instructions,
                input_payload=input_payload,
                output_schema=output_schema,
                timeout_seconds=timeout_seconds,
                input_images=input_images,
            )
        stage_calls.append(str(title))
        (unit,) = DirectoryScope.model_validate(input_payload["scope"]).units
        draft = simple_complete(
            self,
            instructions="",
            input_payload={},
            output_schema=(
                TechnicalDesignDraft.model_json_schema()
                if title == "JointTechnicalDesign"
                else ExecutionPlanDraft.model_json_schema()
            ),
            timeout_seconds=timeout_seconds,
        ).payload
        return StructuredModelResult(
            payload={
                "product_spec_sha256": input_payload["product_spec_sha256"],
                "summary": "Inspect the exact candidate greeting.",
                "blocking_issues": [],
                "units": [{"unit_id": unit.id, "requirement_ids": ["req_001"], "design": draft}],
            }
            if title == "JointTechnicalDesign"
            else {
                "design_sha256": input_payload["design_sha256"],
                "units": [{"unit_id": unit.id, "plan": draft}],
                "integration_checks": [],
            },
            duration_ms=0,
        )

    monkeypatch.setattr(_ScriptedStructuredClient, "complete", joint_complete)
    entry = host.requirement_entry()
    created = entry.create(
        CreateRequirement(
            name="Parent knowledge scope recovery", repository_roots=(str(repository),)
        )
    ).checkpoint
    product = entry.reply(
        ReplyToProduct(
            delivery_id=created.delivery_id,
            expected_checkpoint_sha256=created.checkpoint_sha256,
            message="Update the greeting.",
        )
    ).checkpoint
    checkpoint = entry.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="exact-parent-product-approval",
        )
    ).checkpoint
    # Scheduling waits preserve the delivery checkpoint; they are not terminal BLOCKED.
    assert checkpoint.stage is JointStage.DELIVERING
    assert checkpoint.approval is not None and checkpoint.product_spec is not None
    assert checkpoint.approval.product_spec_sha256 == joint_digest(checkpoint.product_spec)
    assert checkpoint.design is not None and checkpoint.plan is not None
    assert checkpoint.design.product_spec_sha256 == checkpoint.approval.product_spec_sha256
    assert checkpoint.plan.design_sha256 == joint_digest(checkpoint.design)
    # This small single-repository scope uses the ordinary deterministic fast
    # Planner path. Its persisted plan is still bound to the genuine joint design.
    assert stage_calls == ["JointTechnicalDesign"]
    (child,) = checkpoint.children
    native = child.checkpoint
    assert native.task_id is not None and native.repository_id is not None
    assert native.delivery_id != checkpoint.delivery_id
    (failed_binding,) = failed_bindings
    assert failed_binding.requirement_id == checkpoint.delivery_id
    assert failed_binding.requirement_id != native.delivery_id
    assert failed_binding.task_id == native.task_id
    sidecar = host.projects()[0].root / "repositories" / native.repository_id
    failed_records = KnowledgeRecordStore(
        sidecar / "knowledge/runs/invocations" / invocation_lane_sha256(failed_binding),
        read_only=True,
    )
    (failed_outcome,) = tuple(
        outcome
        for outcome in failed_records.list(
            "knowledge-invocation-outcomes", KnowledgeInvocationOutcome
        )
        if outcome.intent.binding == failed_binding
    )
    assert failed_outcome.state == "FAILED" and failed_outcome.intent.claim is not None
    assert failed_outcome.failure is not None and failed_outcome.failure.transient
    historical_claim = host.work_queue.original_claim(failed_outcome.intent.claim.lease.id)
    assert claim_identity_sha256(historical_claim) == claim_identity_sha256(
        failed_outcome.intent.claim
    )
    frozen_records = {
        path: path.read_bytes() for path in failed_records.root.iterdir() if path.is_file()
    }
    with closing(MySqlTaskRepository(mysql_dsn)) as tasks:
        original = tasks.get(native.task_id)
        events = tasks.list_events(original.id)
        revision = tasks.current_revision(original.id)
        assert original.attempts == 2 and not invoked
        assert original.retry_failures is not None and len(original.retry_failures) == 1
        current = max(host.work_queue.items_for_task(original.id), key=lambda item: item.attempt)
        assert current.status is WorkItemStatus.WAITING_DEPENDENCY
        assert current.wait_disposition is not None
        assert current.wait_disposition.facts.classification == "CONTEXT_CAPACITY"
        assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
        (repository / "platform.txt").write_text("new source prerequisite\n")
        _git("add", "platform.txt", cwd=repository)
        _git("commit", "-m", "new platform baseline", cwd=repository)
        target = _git_output("rev-parse", "HEAD", cwd=repository)
        plan = host.propose_execution_baseline(
            BaselineProposeCommand(
                delivery_id=checkpoint.delivery_id,
                task_id=original.id,
                expected_task_intent_sha256=task_intent_sha256(original),
                expected_task_revision=revision,
                expected_work_item_id=current.id,
                expected_source_revision=current.wait_disposition.facts.source_revision,
                target_base_ref=target,
            ),
            project_id="project_test",
        )
        proof = KnowledgeRecordStore(
            sidecar / "state/execution-baselines" / original.id,
            read_only=True,
        ).get("baseline-quiescence", plan.facts.quiescence_proof_sha256, BaselineQuiescenceProof)
        assert {value.proof_kind for value in proof.invocations} == {
            "claimed_knowledge_failure",
            "claimed_context_capacity",
        }
        (knowledge_proof,) = [
            value for value in proof.invocations if value.proof_kind == "claimed_knowledge_failure"
        ]
        (claim_proof,) = knowledge_proof.knowledge_only_claims
        assert claim_proof.lease_id == historical_claim.lease.id
        assert claim_proof.claim_sha256 == claim_identity_sha256(historical_claim)
        assert claim_proof.outcome_sha256s == (failed_outcome.outcome_sha256,)
        assert plan.facts.continuation is not None
        assert plan.facts.continuation.current_attempt == 2
        binding = host.execute_execution_baseline(
            BaselineExecuteCommand(
                delivery_id=checkpoint.delivery_id,
                task_id=original.id,
                expected_plan_sha256=plan.plan_sha256,
                reference="exact-parent-pause",
                continuation_mode=BaselineContinuationMode.PAUSE,
            ),
            project_id="project_test",
        )
        assert binding.branch_name == original.branch_name
        assert binding.execution_base_ref == target
        assert tasks.get(original.id) == original and tasks.list_events(original.id) == events
        paused = host.work_queue.get(current.id)
        assert paused.wait_disposition is not None
        assert paused.wait_disposition.facts.classification == "EXECUTION_BASELINE_PAUSED"
        assert not invoked
        capacity = False
        host.continue_execution_baseline(
            BaselineContinueCommand(
                delivery_id=checkpoint.delivery_id,
                task_id=original.id,
                expected_task_intent_sha256=task_intent_sha256(original),
                expected_task_revision=revision,
                expected_work_item_id=paused.id,
                expected_source_revision=binding.execution_source_revision,
                expected_execution_baseline_sha256=binding.binding_sha256,
                expected_disposition_sha256=paused.wait_disposition.disposition_sha256,
                reference="exact-parent-resume",
            ),
            project_id="project_test",
        )
        delivered = entry.status(checkpoint.delivery_id).checkpoint
        assert delivered.stage is JointStage.DONE
        assert delivered.delivery_id == checkpoint.delivery_id
        assert delivered.approval == checkpoint.approval
        assert delivered.product_spec == checkpoint.product_spec
        assert delivered.design == checkpoint.design and delivered.plan == checkpoint.plan
        (completed_child,) = delivered.children
        assert completed_child.checkpoint.delivery_id == native.delivery_id
        assert completed_child.checkpoint.task_id == original.id
        assert completed_child.checkpoint.stage is DeliveryStage.DONE
        final = tasks.get(original.id)
        assert final.status is TaskStatus.DONE and final.attempts == 2
        assert final.retry_policy == original.retry_policy
        assert final.retry_failures == original.retry_failures
        assert tasks.list_events(original.id)[: len(events)] == events
        assert [request.role for request in invoked] == [
            AgentRole.CODER,
            AgentRole.QA,
            AgentRole.REVIEWER,
        ]
        assert len({request.run_id for request in invoked}) == 3
        assert (
            len(
                {
                    claim.assignment.agent_id
                    for item in host.work_queue.items_for_task(original.id)
                    for claim in host.work_queue.claims_for_work_item(item.id)
                }
            )
            == 3
        )
    assert all(path.read_bytes() == content for path, content in frozen_records.items())
    assert not host.work_queue.list_active_leases(now=datetime.now(UTC))
    assert (repository / "hello.txt").read_text() == "hello\n"
    assert _git_output("status", "--porcelain", cwd=repository) == ""
