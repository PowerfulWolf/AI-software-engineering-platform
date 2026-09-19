"""Independent QA for durable role recovery and delivery workflow proof boundaries."""

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents.structured import StructuredModelResult
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.context import ContextSource, FileContextStore
from ai_software_engineer.domain import AgentRole, TaskStatus, TeamRole
from ai_software_engineer.knowledge.agents import KnowledgeConsultation
from ai_software_engineer.knowledge.delivery import DeliveryWorkflowProof, KnowledgeDeliveryGate
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGap,
    KnowledgeGapRaised,
    KnowledgeGapService,
    KnowledgeResolution,
    KnowledgeResolutionSource,
    KnowledgeResume,
)
from ai_software_engineer.knowledge.models import KnowledgeError, digest, text_digest
from ai_software_engineer.knowledge.retrieval import MarkdownKnowledgeRetrieval
from ai_software_engineer.knowledge.runtime import KnowledgeRunContextBuilder
from ai_software_engineer.knowledge.skills import KnowledgeSkillRegistry
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.knowledge.workflow import (
    SkillName,
    WorkflowGateFacts,
    WorkflowSkillRegistry,
)
from ai_software_engineer.orchestration import FileRunContextBuilder, RetryingOrchestrator
from ai_software_engineer.store import SqliteTaskRepository
from tests.knowledge.test_consultation import Model
from tests.knowledge.test_gaps import Approval
from tests.knowledge.test_retrieval_contract import binding, snapshot
from tests.orchestration.test_retry import ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions, _task


class ResolutionAwareModel(Model):
    """A role needs one missing fact until an exact human resolution is delivered."""

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        if output_schema["title"] == "KnowledgeIntent":
            task_payload = cast(Mapping[str, object], input_payload["task"])
            approved = task_payload["approved_knowledge_resolutions"]
            self.calls.append("KnowledgeIntent")
            return StructuredModelResult(
                payload={"queries": [] if approved else ["missing_operation_policy"]},
                duration_ms=2,
            )
        return super().complete(
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            input_images=input_images,
        )


class RecoveryClients:
    def __init__(self, gap_role: AgentRole) -> None:
        self.gap_role = gap_role
        self.missing = ResolutionAwareModel()
        self.standard = Model()

    def for_project(self, repository_root: Path, role: TeamRole) -> Model:
        return self.missing if role.value == self.gap_role.value else self.standard


@pytest.mark.parametrize(
    ("role", "checkpoint"),
    (
        (AgentRole.CODER, TaskStatus.IMPLEMENTING),
        (AgentRole.QA, TaskStatus.QA),
        (AgentRole.REVIEWER, TaskStatus.REVIEW),
    ),
)
def test_gap_resolution_reopens_same_sqlite_task_and_preserves_role_lineage(
    tmp_path: Path, role: AgentRole, checkpoint: TaskStatus
) -> None:
    task = _task(tmp_path)
    database = tmp_path / "tasks.sqlite"
    definitions = {
        key: value.model_copy(update={"token_budget": 16_000})
        for key, value in _definitions().items()
    }

    def runner(repository: SqliteTaskRepository, adapter: ScriptedAdapter) -> RetryingOrchestrator:
        # Every invocation reconstructs stores, clients and builders, as after restart.
        contexts = FileContextStore(tmp_path / "contexts")
        records = KnowledgeRecordStore(tmp_path / "knowledge")
        artifacts = FileArtifactStore(tmp_path / "artifacts")
        context_builder = KnowledgeRunContextBuilder(
            FileRunContextBuilder(task.repository, context_store=contexts),
            contexts=contexts,
            clients=RecoveryClients(role),
            repository_root=Path(task.repository),
            records=records,
            team_id="team_ai",
            project_id="project_payments",
            repository_id="repository_payments",
            sources=(
                ContextSource(
                    source_id="native.rule.0",
                    uri="repository://rules/AGENTS.md",
                    content="# Refunds\nUse original payment identity.",
                ),
            ),
        )
        return RetryingOrchestrator(
            repository=repository,
            artifact_store=artifacts,
            context_builder=context_builder,
            agent_adapter=adapter,
            agent_definitions=definitions,
            clock=_clock,
            transition_gate=KnowledgeDeliveryGate(
                records=records, artifacts=artifacts, contexts=contexts
            ),
        )

    first_adapter = ScriptedAdapter()
    with SqliteTaskRepository(database) as repository:
        repository.create(task)
        with pytest.raises(KnowledgeGapRaised) as caught:
            runner(repository, first_adapter).run_task(task.id)
        stopped = repository.get(task.id)
        prefix = repository.list_events(task.id)
        assert stopped.status is checkpoint
        assert role not in {request.role for request in first_adapter.requests}
        assert not any(
            event.to_status in {TaskStatus.BLOCKED, TaskStatus.FAILED} for event in prefix
        )

    records = KnowledgeRecordStore(tmp_path / "knowledge")
    gap = caught.value.gap
    answer = "The approved operation policy preserves the original payment identity."
    resolution = KnowledgeResolution(
        gap_id=gap.gap_id,
        previous_run_id=gap.binding.run_id,
        answer=answer,
        sources=(
            KnowledgeResolutionSource(
                uri="human://qa-fixture/decision", content=answer, sha256=text_digest(answer)
            ),
        ),
        approval_reference="human:exact-fixture-decision",
        approved_by="human:fixture-owner",
        resolution_id="0" * 64,
    )
    resolution = resolution.model_copy(
        update={
            "resolution_id": digest(resolution.model_dump(mode="json", exclude={"resolution_id"}))
        }
    )
    assert KnowledgeGapService(records).resolve(resolution, Approval(resolution)) == resolution

    resumed_adapter = ScriptedAdapter()
    with SqliteTaskRepository(database) as repository:
        assert repository.get(task.id) == stopped
        result = runner(repository, resumed_adapter).run_task(task.id)
        assert result.task.id == task.id
        assert result.task.status is TaskStatus.DONE
        assert repository.list_events(task.id)[: len(prefix)] == prefix
        assert resumed_adapter.requests[0].role is role

    reopened = KnowledgeRecordStore(tmp_path / "knowledge")
    assert reopened.get("gaps", gap.gap_id, KnowledgeGap) == gap
    assert reopened.get("resolutions", resolution.resolution_id, KnowledgeResolution) == resolution
    (resume,) = reopened.list("gap-resumes", KnowledgeResume)
    assert resume.previous_binding == gap.binding
    assert resume.resolution_id == resolution.resolution_id
    assert resume.new_binding.run_id != gap.binding.run_id
    assert resume.new_binding.context_manifest_id != gap.binding.context_manifest_id
    assert resume.new_binding.snapshot_sha256 == gap.binding.snapshot_sha256
    receipt = reopened.get("consultations", resume.new_binding.run_id, KnowledgeConsultation)
    assert receipt.intent.queries == ()
    assert receipt.resolutions == (resolution,)
    artifacts = FileArtifactStore(tmp_path / "artifacts").list_for_task(task.id)
    role_artifacts = [a for a in artifacts if a.producer.role is not AgentRole.ORCHESTRATOR]
    assert len(role_artifacts) == 3
    assert len({a.producer.agent_id for a in role_artifacts}) == 3
    resolved_artifact = next(a for a in role_artifacts if a.producer.role is role)
    context = FileContextStore(tmp_path / "contexts").get(resolved_artifact.context_manifest_id)
    assert any(section.name == "knowledge.resolutions" for section in context.sections)


@pytest.mark.parametrize(
    ("role", "skill"),
    (
        (TeamRole.QA, "acceptance-matrix"),
        (TeamRole.REVIEWER, "code-review"),
        (TeamRole.MANAGER, "finish-work"),
    ),
)
def test_delivery_skill_rejects_missing_and_forged_proof(
    tmp_path: Path, role: TeamRole, skill: SkillName
) -> None:
    records = KnowledgeRecordStore(tmp_path)
    frozen = snapshot()
    bound = binding(frozen, role)
    manifest = KnowledgeSkillRegistry(
        bound, frozen, MarkdownKnowledgeRetrieval(), records
    ).manifest()
    workflows = WorkflowSkillRegistry(records)
    facts = WorkflowGateFacts(
        binding=bound,
        knowledge_manifest_sha256=manifest.manifest_sha256,
        durable_evidence=("knowledge-manifest:" + manifest.manifest_sha256,),
        required_acceptance_ids=("AC1",),
        covered_acceptance_ids=("AC1",),
        independent_agent_ids=("agent_coder_001", "agent_qa_001", "agent_reviewer_001"),
    )
    missing = workflows.invoke(skill, "v1", facts)
    assert missing.status == "REJECTED"
    with pytest.raises(KnowledgeError):
        workflows.require(bound, (skill,), (missing.evidence_sha256,))
    with pytest.raises(KnowledgeError):
        workflows.invoke(
            skill,
            "v1",
            facts.model_copy(update={"durable_evidence": ("delivery-proof:" + "f" * 64,)}),
        )
    proof = DeliveryWorkflowProof(
        task_id=cast(str, bound.task_id),
        target_status=TaskStatus.QA,
        artifact_digests=(),
        required_acceptance_ids=facts.required_acceptance_ids,
        covered_acceptance_ids=facts.covered_acceptance_ids,
        independent_agent_ids=facts.independent_agent_ids,
        proof_sha256="0" * 64,
    )
    # An on-disk proof with a forged digest must not be treated as a passed gate.
    records.put("delivery-proofs", "f" * 64, proof)
    with pytest.raises(KnowledgeError):
        workflows.invoke(
            skill,
            "v1",
            facts.model_copy(update={"durable_evidence": ("delivery-proof:" + "f" * 64,)}),
        )
    # A valid digest cannot make an earlier stage's proof authorize a later gate.
    wrong_stage = proof.model_copy(
        update={"proof_sha256": digest(proof.model_dump(mode="json", exclude={"proof_sha256"}))}
    )
    records.put("delivery-proofs", wrong_stage.proof_sha256, wrong_stage)
    with pytest.raises(KnowledgeError):
        workflows.invoke(
            skill,
            "v1",
            facts.model_copy(
                update={"durable_evidence": ("delivery-proof:" + wrong_stage.proof_sha256,)}
            ),
        )


@pytest.mark.parametrize("target", (TaskStatus.QA, TaskStatus.REVIEW, TaskStatus.DONE))
def test_delivery_transition_rejects_absent_artifact_chain(
    tmp_path: Path, target: TaskStatus
) -> None:
    gate = KnowledgeDeliveryGate(
        records=KnowledgeRecordStore(tmp_path / "records"),
        artifacts=FileArtifactStore(tmp_path / "artifacts"),
        contexts=FileContextStore(tmp_path / "contexts"),
    )
    with pytest.raises(KnowledgeError, match="WORKFLOW_ARTIFACT_MISSING"):
        gate.before_transition(_task(tmp_path), target, ())
