"""Compact role prompts preserve frozen knowledge and historical human decisions."""

import json
from pathlib import Path

import pytest

from ai_software_engineer.context import ContextBudget, FileContextStore
from ai_software_engineer.context.native import native_rule_prompt_sources
from ai_software_engineer.context.ports import ContextBudgetExceeded
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.knowledge.agents import KnowledgeConsultation
from ai_software_engineer.knowledge.context_reads import retrieved_context_section
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGapService,
    KnowledgeResolution,
    KnowledgeResolutionSource,
)
from ai_software_engineer.knowledge.models import (
    KnowledgeError,
    KnowledgeEvidence,
    KnowledgeSnapshot,
    digest,
    text_digest,
)
from ai_software_engineer.knowledge.runtime import KnowledgeRunContextBuilder
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.orchestration.context import FileRunContextBuilder
from tests.knowledge.test_delivery_context import Clients, _builder
from tests.knowledge.test_gaps import Approval
from tests.orchestration.test_runner import _definitions


def test_old_approved_resolution_survives_prompt_projection_and_store_reopen(
    tmp_path: Path,
) -> None:
    task, contexts, records, original = _builder(tmp_path)
    sources = (original.sources[0].model_copy(update={"uri": "repository://rules/refunds.md"}),)
    original.sources = sources
    original.delegate = FileRunContextBuilder(tmp_path, sources=sources, context_store=contexts)
    agent = _definitions()[AgentRole.CODER]
    old = original.build(task, agent, attempt=1)
    receipt = KnowledgeConsultation.model_validate_json(
        next(s.content for s in old.sections if s.name == "knowledge.consultation")
    )
    snapshot = records.get("snapshots", receipt.binding.snapshot_sha256, KnowledgeSnapshot)
    service = KnowledgeGapService(records)
    gap = service.report(
        manifest=receipt.manifest,
        question="Which refund SLA?",
        required_decision="Specify SLA",
        reason="MISSING",
        severity="BLOCKING",
        impact="Acceptance needs SLA",
        risk="medium",
    )
    answer = "Refund within five days."
    resolution = KnowledgeResolution(
        gap_id=gap.gap_id,
        previous_run_id=gap.binding.run_id,
        answer=answer,
        sources=(
            KnowledgeResolutionSource(
                uri="human://test/decision", sha256=text_digest(answer), content=answer
            ),
        ),
        approval_reference="test-human-approval",
        approved_by="human:owner",
        resolution_id="0" * 64,
    )
    resolution = resolution.model_copy(
        update={
            "resolution_id": digest(resolution.model_dump(mode="json", exclude={"resolution_id"}))
        }
    )
    service.resolve(resolution, Approval(resolution))
    reopened_contexts = FileContextStore(tmp_path / "contexts")
    reopened_records = KnowledgeRecordStore(tmp_path / "knowledge")
    resumed = KnowledgeRunContextBuilder(
        FileRunContextBuilder(
            tmp_path, sources=native_rule_prompt_sources(sources), context_store=reopened_contexts
        ),
        contexts=reopened_contexts,
        records=reopened_records,
        clients=Clients(),
        repository_root=tmp_path,
        team_id=original.team_id,
        project_id=original.project_id,
        repository_id=original.repository_id,
        sources=sources,
    ).build(task, agent, attempt=1)
    assert contexts.get(old.context_id) == old
    assert (
        reopened_records.get("snapshots", snapshot.snapshot_sha256, KnowledgeSnapshot) == snapshot
    )
    sections = {s.name: s for s in resumed.sections}
    assert json.loads(sections["knowledge.resolutions"].content) == [resolution.to_wire()]
    new_receipt = KnowledgeConsultation.model_validate_json(
        sections["knowledge.consultation"].content
    )
    assert new_receipt.binding.snapshot_sha256 == receipt.binding.snapshot_sha256
    assert new_receipt.binding.run_id != receipt.binding.run_id
    assert new_receipt.resolutions == (resolution,)
    assert "Use original payment identity." in sections["knowledge.reads"].content


@pytest.mark.parametrize("corruption", ["body", "binding", "citation"])
def test_projected_reads_reject_resealed_wrong_evidence(tmp_path: Path, corruption: str) -> None:
    task, _, records, builder = _builder(tmp_path)
    context = builder.build(task, _definitions()[AgentRole.CODER], attempt=1)
    receipt = KnowledgeConsultation.model_validate_json(
        next(s.content for s in context.sections if s.name == "knowledge.consultation")
    )
    read = next(
        records.get("evidence", identity, KnowledgeEvidence)
        for identity in receipt.manifest.evidence_ids
        if records.get("evidence", identity, KnowledgeEvidence).status == "READ"
    )
    assert read.chunk is not None
    changed = read.model_copy(
        update={"chunk": read.chunk.model_copy(update={"content": "Invented rule"})}
    )
    if corruption == "binding":
        changed = read.model_copy(
            update={"binding": read.binding.model_copy(update={"task_id": "task_wrong"})}
        )
    elif corruption == "citation":
        changed = read.model_copy(
            update={
                "chunk": read.chunk.model_copy(
                    update={
                        "citation": read.chunk.citation.model_copy(
                            update={"chunk_sha256": "0" * 64}
                        )
                    }
                )
            }
        )
    changed = changed.model_copy(
        update={"evidence_id": digest(changed.model_dump(mode="json", exclude={"evidence_id"}))}
    )
    records.put("evidence", changed.evidence_id, changed)
    manifest = receipt.manifest.model_copy(
        update={
            "evidence_ids": tuple(
                changed.evidence_id if value == read.evidence_id else value
                for value in receipt.manifest.evidence_ids
            )
        }
    )
    manifest = manifest.model_copy(
        update={
            "manifest_sha256": digest(manifest.model_dump(mode="json", exclude={"manifest_sha256"}))
        }
    )
    invalid = receipt.model_copy(update={"manifest": manifest})
    invalid = invalid.model_copy(
        update={
            "consultation_sha256": digest(
                invalid.model_dump(mode="json", exclude={"consultation_sha256"})
            )
        }
    )
    with pytest.raises(KnowledgeError, match="CONTEXT_READ"):
        retrieved_context_section(invalid, records)


def test_required_read_text_is_budgeted_before_delivery(tmp_path: Path) -> None:
    task, contexts, _, builder = _builder(tmp_path)
    builder.sources = (
        builder.sources[0].model_copy(
            update={
                "uri": "repository://rules/refunds.md",
                "content": "# Refunds\nUse original payment identity.\n"
                + "long normative body. " * 300,
            }
        ),
    )
    projected = native_rule_prompt_sources(builder.sources)
    agent = _definitions()[AgentRole.CODER]
    delegate = FileRunContextBuilder(tmp_path, sources=projected, context_store=contexts)
    base = delegate.build(task, agent, attempt=1)
    builder.delegate = FileRunContextBuilder(
        tmp_path,
        sources=projected,
        context_store=contexts,
        budget=ContextBudget(
            max_input_tokens=base.budget.used_input_tokens + 50, reserved_output_tokens=4_000
        ),
    )
    with pytest.raises(ContextBudgetExceeded, match="knowledge consultation"):
        builder.build(task, agent, attempt=1)


@pytest.mark.parametrize("mutation", ["remove", "replace"])
def test_gate_rejects_missing_or_modified_read_section(tmp_path: Path, mutation: str) -> None:
    from unittest.mock import Mock

    from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
    from ai_software_engineer.domain import ArtifactKind, TaskStatus
    from ai_software_engineer.knowledge.delivery import KnowledgeDeliveryGate
    from ai_software_engineer.orchestration import RetryingOrchestrator
    from ai_software_engineer.store import SqliteTaskRepository
    from tests.orchestration.test_retry import ScriptedAdapter
    from tests.orchestration.test_runner import _clock

    task, contexts, records, builder = _builder(tmp_path)
    builder.sources = (
        builder.sources[0].model_copy(update={"uri": "repository://rules/refunds.md"}),
    )
    builder.delegate = FileRunContextBuilder(
        tmp_path,
        sources=native_rule_prompt_sources(builder.sources),
        context_store=contexts,
    )
    artifacts = FileArtifactStore(tmp_path / "artifacts")
    with SqliteTaskRepository(tmp_path / "tasks.sqlite") as repository:
        repository.create(task)
        result = RetryingOrchestrator(
            repository=repository,
            artifact_store=artifacts,
            context_builder=builder,
            agent_adapter=ScriptedAdapter(),
            agent_definitions=_definitions(),
            clock=_clock,
            transition_gate=KnowledgeDeliveryGate(
                records=records, contexts=contexts, artifacts=artifacts
            ),
        ).run_task(task.id)
    assert result.task.status is TaskStatus.DONE
    implementation = next(
        a for a in artifacts.list_for_task(task.id) if a.kind is ArtifactKind.IMPLEMENTATION_REPORT
    )
    context = contexts.get(implementation.context_manifest_id)
    reads = next(s for s in context.sections if s.name == "knowledge.reads")
    sections = tuple(s for s in context.sections if s.name != "knowledge.reads")
    if mutation == "replace":
        text = "Forged rule permits bypassing checks."
        replacement = reads.model_copy(
            update={"content": text, "tokens": (len(text) + 3) // 4, "sha256": text_digest(text)}
        )
        sections = tuple(replacement if s == reads else s for s in context.sections)
    forged = context.model_copy(
        update={
            "sections": sections,
            "budget": context.budget.model_copy(
                update={"used_input_tokens": sum(s.tokens for s in sections)}
            ),
        }
    )
    forged = forged.model_copy(
        update={
            "context_id": "ctx_"
            + digest(forged.model_dump(mode="json", exclude={"context_id", "built_at"}))
        }
    )
    contexts.put(forged)
    changed = seal_artifact(
        implementation.model_copy(update={"context_manifest_id": forged.context_id}),
        validated_at=_clock(),
    )
    source = Mock(wraps=artifacts)
    source.get.side_effect = lambda identity: (
        changed if identity == changed.artifact_id else artifacts.get(identity)
    )
    with pytest.raises(KnowledgeError, match="WORKFLOW_CONTEXT_MISMATCH"):
        KnowledgeDeliveryGate(
            records=records, contexts=contexts, artifacts=source
        ).before_transition(
            task,
            TaskStatus.QA,
            (changed.artifact_id,),
        )


def test_read_projection_rejects_cross_role_evidence(tmp_path: Path) -> None:
    from ai_software_engineer.domain import TeamRole

    task, _, records, builder = _builder(tmp_path)
    builder.sources = (builder.sources[0].model_copy(update={"roles": (AgentRole.CODER,)}),)
    context = builder.build(task, _definitions()[AgentRole.CODER], attempt=1)
    receipt = KnowledgeConsultation.model_validate_json(
        next(s.content for s in context.sections if s.name == "knowledge.consultation")
    )
    wrong_binding = receipt.binding.model_copy(update={"role": TeamRole.QA})
    ids = []
    for identity in receipt.manifest.evidence_ids:
        fact = records.get("evidence", identity, KnowledgeEvidence).model_copy(
            update={"binding": wrong_binding}
        )
        fact = fact.model_copy(
            update={"evidence_id": digest(fact.model_dump(mode="json", exclude={"evidence_id"}))}
        )
        records.put("evidence", fact.evidence_id, fact)
        ids.append(fact.evidence_id)
    manifest = receipt.manifest.model_copy(
        update={"binding": wrong_binding, "evidence_ids": tuple(ids)}
    )
    manifest = manifest.model_copy(
        update={
            "manifest_sha256": digest(manifest.model_dump(mode="json", exclude={"manifest_sha256"}))
        }
    )
    invalid = receipt.model_copy(update={"binding": wrong_binding, "manifest": manifest})
    invalid = invalid.model_copy(
        update={
            "consultation_sha256": digest(
                invalid.model_dump(mode="json", exclude={"consultation_sha256"})
            )
        }
    )
    with pytest.raises(KnowledgeError):
        retrieved_context_section(invalid, records)
