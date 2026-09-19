"""Independent QA for reviewed revision lineage and pre-upgrade delivery checkpoints."""

from pathlib import Path

import pytest

from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.context import ContextSource, FileContextStore
from ai_software_engineer.domain import AgentRole, Task, TaskStatus
from ai_software_engineer.domain.artifact import Artifact, ImplementationReportArtifact
from ai_software_engineer.knowledge.agents import KnowledgeConsultation
from ai_software_engineer.knowledge.delivery import (
    DeliveryWorkflowAdmission,
    DeliveryWorkflowProof,
    KnowledgeDeliveryGate,
)
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGapRaised,
    KnowledgeGapService,
    KnowledgeResolution,
    KnowledgeResolutionSource,
    KnowledgeResume,
)
from ai_software_engineer.knowledge.models import (
    KnowledgeError,
    KnowledgeRunManifest,
    digest,
    text_digest,
)
from ai_software_engineer.knowledge.runtime import KnowledgeRunContextBuilder
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.knowledge.workflow import WorkflowGateFacts, WorkflowSkillRegistry
from ai_software_engineer.orchestration import FileRunContextBuilder, RetryingOrchestrator
from ai_software_engineer.store import SqliteTaskRepository
from tests.knowledge.test_delivery_context import Clients
from tests.knowledge.test_gaps import Approval
from tests.knowledge.test_runtime_recovery_qa import RecoveryClients
from tests.orchestration.test_retry import ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions, _task


def _environment(
    root: Path, *, gap_role: AgentRole | None = None
) -> tuple[Task, FileContextStore, KnowledgeRecordStore, KnowledgeRunContextBuilder]:
    task = _task(root)
    contexts = FileContextStore(root / "contexts")
    records = KnowledgeRecordStore(root / "knowledge")
    builder = KnowledgeRunContextBuilder(
        FileRunContextBuilder(task.repository, context_store=contexts),
        contexts=contexts,
        clients=RecoveryClients(gap_role) if gap_role is not None else Clients(),
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
    return task, contexts, records, builder


@pytest.mark.parametrize("exact_recovery_first", (True, False))
def test_resolved_qa_gap_carries_forward_only_after_exact_candidate_recovery(
    tmp_path: Path, exact_recovery_first: bool
) -> None:
    task, _, records, builder = _environment(tmp_path, gap_role=AgentRole.QA)
    agent = _definitions()[AgentRole.QA].model_copy(update={"token_budget": 16_000})
    with pytest.raises(KnowledgeGapRaised) as raised:
        builder.build(task, agent, attempt=1, candidate_revision="a" * 40)
    gap = raised.value.gap
    answer = "The approved operation policy uses original payment identity."
    resolution = KnowledgeResolution(
        gap_id=gap.gap_id,
        previous_run_id=gap.binding.run_id,
        answer=answer,
        sources=(
            KnowledgeResolutionSource(
                uri="human://qa-revision/decision", content=answer, sha256=text_digest(answer)
            ),
        ),
        approval_reference="human:exact-qa-revision-answer",
        approved_by="human:fixture-owner",
        resolution_id="0" * 64,
    )
    resolution = resolution.model_copy(
        update={
            "resolution_id": digest(resolution.model_dump(mode="json", exclude={"resolution_id"}))
        }
    )
    KnowledgeGapService(records).resolve(resolution, Approval(resolution))
    if not exact_recovery_first:
        with pytest.raises(KnowledgeError, match="RESUME_REQUIRES_NEW_RUN_CONTEXT"):
            builder.build(task, agent, attempt=2, candidate_revision="b" * 40)
        assert records.list("gap-resumes", KnowledgeResume) == ()
        return

    exact_context = builder.build(task, agent, attempt=1, candidate_revision="a" * 40)
    (exact_resume,) = records.list("gap-resumes", KnowledgeResume)
    assert exact_resume.new_binding.source_revision == gap.binding.source_revision == "a" * 40
    assert exact_resume.previous_resume_sha256 is None
    # Reconstruct the builder and stores before moving to a newly implemented candidate.
    task, contexts, reopened, fresh_builder = _environment(tmp_path, gap_role=AgentRole.QA)
    later_context = fresh_builder.build(task, agent, attempt=2, candidate_revision="b" * 40)
    later_resume = next(
        item
        for item in reopened.list("gap-resumes", KnowledgeResume)
        if item.new_binding.source_revision == "b" * 40
    )
    assert later_resume.previous_resume_sha256 == exact_resume.resume_sha256
    assert later_resume.previous_binding == gap.binding
    assert later_resume.resolution_id == resolution.resolution_id
    assert later_resume.new_binding.run_id != exact_resume.new_binding.run_id
    receipt = reopened.get("consultations", later_resume.new_binding.run_id, KnowledgeConsultation)
    assert receipt.assessment.status == "SUFFICIENT" and receipt.resolutions == (resolution,)
    assert later_context.context_id != exact_context.context_id
    assert contexts.get(exact_context.context_id) == exact_context


@pytest.mark.parametrize(
    "drift", ("candidate", "source_revision", "parent_context", "final_context", "run")
)
def test_real_delivery_proof_cannot_be_reused_for_another_run_context_or_revision(
    tmp_path: Path, drift: str
) -> None:
    task, contexts, records, builder = _environment(tmp_path)
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    gate = KnowledgeDeliveryGate(records=records, artifacts=artifacts, contexts=contexts)
    with SqliteTaskRepository(tmp_path / "tasks.sqlite") as repository:
        repository.create(task)
        result = RetryingOrchestrator(
            repository=repository,
            artifact_store=artifacts,
            context_builder=builder,
            agent_adapter=ScriptedAdapter(),
            agent_definitions=_definitions(),
            clock=_clock,
            transition_gate=gate,
        ).run_task(task.id)
    assert result.task.status is TaskStatus.DONE
    proof = next(
        item
        for item in records.list("delivery-proofs", DeliveryWorkflowProof)
        if item.target_status is TaskStatus.REVIEW
    )
    assert proof.consultation_binding is not None
    consultation = records.get(
        "consultations", proof.consultation_binding.run_id, KnowledgeConsultation
    )
    facts = WorkflowGateFacts(
        binding=proof.consultation_binding,
        knowledge_manifest_sha256=consultation.manifest.manifest_sha256,
        durable_evidence=("delivery-proof:" + proof.proof_sha256,),
        required_acceptance_ids=proof.required_acceptance_ids,
        covered_acceptance_ids=proof.covered_acceptance_ids,
        independent_agent_ids=proof.independent_agent_ids,
        final_context_id=proof.final_context_id,
        candidate_revision=proof.candidate_revision,
    )
    registry = WorkflowSkillRegistry(records)
    assert registry.invoke("acceptance-matrix", "v1", facts).status == "PASSED"
    if drift == "candidate":
        changed = facts.model_copy(update={"candidate_revision": "f" * 40})
    elif drift == "final_context":
        changed = facts.model_copy(update={"final_context_id": "ctx_" + "f" * 64})
    else:
        replacement = {
            "source_revision": ("source_revision", "f" * 40),
            "parent_context": ("context_manifest_id", "ctx_" + "f" * 64),
            "run": ("run_id", "run_unrelated_proof"),
        }[drift]
        different_binding = facts.binding.model_copy(update={replacement[0]: replacement[1]})
        manifest = consultation.manifest.model_copy(update={"binding": different_binding})
        manifest = manifest.model_copy(
            update={
                "manifest_sha256": digest(
                    manifest.model_dump(mode="json", exclude={"manifest_sha256"})
                )
            }
        )
        records.put("manifests", manifest.manifest_sha256, manifest)
        assert records.get("manifests", manifest.manifest_sha256, KnowledgeRunManifest) == manifest
        changed = facts.model_copy(
            update={
                "binding": different_binding,
                "knowledge_manifest_sha256": manifest.manifest_sha256,
            }
        )
    with pytest.raises(KnowledgeError, match="SKILL_DELIVERY_PROOF_MISMATCH"):
        registry.invoke("acceptance-matrix", "v1", changed)


class CrashBeforeQaEvent:
    def begin_task(self, task: Task) -> None:
        pass

    def before_transition(
        self, task: Task, target: TaskStatus, artifact_ids: tuple[str, ...]
    ) -> None:
        if target is TaskStatus.QA:
            raise RuntimeError("simulated pre-upgrade crash before QA event")


def _legacy_checkpoint(
    root: Path, *, admitted_while_new: bool = False
) -> tuple[Task, FileArtifactStore, FileContextStore, KnowledgeRecordStore]:
    task = _task(root)
    artifacts = FileArtifactStore(root / "artifacts")
    contexts = FileContextStore(root / "contexts")
    records = KnowledgeRecordStore(root / "knowledge")
    if admitted_while_new:
        KnowledgeDeliveryGate(records=records, artifacts=artifacts, contexts=contexts).begin_task(
            task
        )
    with SqliteTaskRepository(root / "tasks.sqlite") as repository:
        repository.create(task)
        with pytest.raises(RuntimeError, match="pre-upgrade crash"):
            RetryingOrchestrator(
                repository=repository,
                artifact_store=artifacts,
                context_builder=FileRunContextBuilder(task.repository, context_store=contexts),
                agent_adapter=ScriptedAdapter(),
                agent_definitions=_definitions(),
                clock=_clock,
                transition_gate=CrashBeforeQaEvent(),
            ).run_task(task.id)
        stopped = repository.get(task.id)
        assert stopped.status is TaskStatus.IMPLEMENTING
        assert repository.list_events(task.id)[-1].to_status is TaskStatus.IMPLEMENTING
    assert any(
        isinstance(item, ImplementationReportArtifact) for item in artifacts.list_for_task(task.id)
    )
    return stopped, artifacts, contexts, records


def test_upgrade_recovers_sealed_implementation_without_rerunning_coder(tmp_path: Path) -> None:
    stopped, artifacts, contexts, records = _legacy_checkpoint(tmp_path)
    legacy = artifacts.list_for_task(stopped.id)
    old_contexts = tuple(contexts.get(artifact.context_manifest_id) for artifact in legacy)
    assert all(
        not any(s.name == "knowledge.consultation" for s in c.sections) for c in old_contexts
    )
    _, _, _, builder = _environment(tmp_path)
    adapter = ScriptedAdapter()
    gate = KnowledgeDeliveryGate(records=records, artifacts=artifacts, contexts=contexts)
    with SqliteTaskRepository(tmp_path / "tasks.sqlite") as repository:
        prefix = repository.list_events(stopped.id)
        result = RetryingOrchestrator(
            repository=repository,
            artifact_store=artifacts,
            context_builder=builder,
            agent_adapter=adapter,
            agent_definitions=_definitions(),
            clock=_clock,
            transition_gate=gate,
        ).run_task(stopped.id)
        assert result.task.status is TaskStatus.DONE
        assert repository.list_events(stopped.id)[: len(prefix)] == prefix
    assert tuple(request.role for request in adapter.requests) == (AgentRole.QA, AgentRole.REVIEWER)
    assert all(artifacts.get(artifact.artifact_id) == artifact for artifact in legacy)
    assert all(contexts.get(context.context_id) == context for context in old_contexts)
    admission = records.get("delivery-admissions", stopped.id, DeliveryWorkflowAdmission)
    assert set(admission.legacy_artifact_digests) == {
        (artifact.artifact_id, artifact.integrity.sha256) for artifact in legacy
    }


@pytest.mark.parametrize("change", ("late_artifact", "changed_digest", "admitted_new"))
def test_upgrade_admission_does_not_authorize_new_receiptless_work(
    tmp_path: Path, change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    task, artifacts, contexts, records = _legacy_checkpoint(
        tmp_path, admitted_while_new=change == "admitted_new"
    )
    gate = KnowledgeDeliveryGate(records=records, artifacts=artifacts, contexts=contexts)
    gate.begin_task(task)
    first_admission = records.get("delivery-admissions", task.id, DeliveryWorkflowAdmission)
    implementation = next(
        item
        for item in artifacts.list_for_task(task.id)
        if isinstance(item, ImplementationReportArtifact)
    )
    if change == "admitted_new":
        assert first_admission.legacy_artifact_digests == ()
    elif change == "late_artifact":
        late_artifact = seal_artifact(
            implementation.model_copy(update={"artifact_id": "art_impl_after_admission"}),
            validated_at=_clock(),
        )
        assert isinstance(late_artifact, ImplementationReportArtifact)
        implementation = late_artifact
        artifacts.put(implementation)
    else:
        changed = seal_artifact(
            implementation.model_copy(update={"source_revision": "f" * 40}),
            validated_at=_clock(),
        )
        original_get = artifacts.get

        def changed_get(identity: str) -> Artifact:
            return changed if identity == changed.artifact_id else original_get(identity)

        monkeypatch.setattr(artifacts, "get", changed_get)
    gate.begin_task(task)
    assert records.get("delivery-admissions", task.id, DeliveryWorkflowAdmission) == first_admission
    with pytest.raises(KnowledgeError, match="WORKFLOW_CONSULTATION_MISSING"):
        gate.before_transition(task, TaskStatus.QA, (implementation.artifact_id,))
