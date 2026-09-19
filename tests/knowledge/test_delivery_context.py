"""Knowledge is a durable input to native delivery and gaps preserve checkpoints."""

from pathlib import Path

import pytest

from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.context import ContextSource, FileContextStore
from ai_software_engineer.domain import AgentRole, TaskStatus, TeamRole
from ai_software_engineer.knowledge.agents import KnowledgeConsultation
from ai_software_engineer.knowledge.delivery import KnowledgeDeliveryGate
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGapRaised,
    KnowledgeGapService,
)
from ai_software_engineer.knowledge.runtime import KnowledgeRunContextBuilder
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.production_backend import ProductionProjectDeliveryBackend
from ai_software_engineer.orchestration import FileRunContextBuilder, RetryingOrchestrator
from ai_software_engineer.store import SqliteTaskRepository
from tests.knowledge.test_consultation import Model
from tests.orchestration.test_retry import ScriptedAdapter
from tests.orchestration.test_runner import _clock, _definitions, _task


class Clients:
    def __init__(self) -> None:
        self.model = Model()

    def for_project(self, repository_root: Path, role: TeamRole) -> Model:
        return self.model


def _builder(tmp_path: Path, *, enabled: bool = True):  # type: ignore[no-untyped-def]
    task = _task(tmp_path)
    contexts = FileContextStore(tmp_path / "contexts")
    records = KnowledgeRecordStore(tmp_path / "knowledge")
    sources = (
        (
            ContextSource(
                source_id="native.rule.0",
                uri="repository://rules/AGENTS.md",
                content="# Refunds\nUse original payment identity.",
            ),
        )
        if enabled
        else ()
    )
    builder = KnowledgeRunContextBuilder(
        FileRunContextBuilder(task.repository, context_store=contexts),
        contexts=contexts,
        clients=Clients(),
        repository_root=Path(task.repository),
        records=records,
        team_id="team_ai",
        project_id="project_payments",
        repository_id="repository_payments",
        sources=sources,
    )
    return task, contexts, records, builder


@pytest.mark.parametrize("role", (AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER))
def test_native_rules_and_consultation_are_in_exact_role_context(
    tmp_path: Path, role: AgentRole
) -> None:
    task, contexts, records, builder = _builder(tmp_path)
    context = builder.build(task, _definitions()[role], attempt=1)
    assert contexts.get(context.context_id) == context
    section = next(s for s in context.sections if s.name == "knowledge.consultation")
    receipt = KnowledgeConsultation.model_validate_json(section.content)
    assert receipt.manifest.citations[0].scope == "repository"
    assert receipt.call_ids
    assert receipt.binding.context_manifest_id != context.context_id
    assert context.budget.used_input_tokens == sum(s.tokens for s in context.sections)
    assert builder.build(task, _definitions()[role], attempt=1) == context
    assert records.get("consultations", receipt.binding.run_id, KnowledgeConsultation) == receipt


def test_active_retrieval_then_independent_native_delivery(tmp_path: Path) -> None:
    task, contexts, records, builder = _builder(tmp_path)
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
                records=records, artifacts=artifacts, contexts=contexts
            ),
        ).run_task(task.id)
        assert result.task.status is TaskStatus.DONE
    assert (
        len(
            {
                a.producer.agent_id
                for a in artifacts.list_for_task(task.id)
                if a.producer.role is not AgentRole.ORCHESTRATOR
            }
        )
        == 3
    )
    for artifact in artifacts.list_for_task(task.id):
        if artifact.producer.role is not AgentRole.ORCHESTRATOR:
            assert any(
                s.name == "knowledge.consultation"
                for s in contexts.get(artifact.context_manifest_id).sections
            )


def test_gap_is_not_converted_to_terminal_delivery_failure(tmp_path: Path) -> None:
    task, _, records, builder = _builder(tmp_path, enabled=False)

    def consult():  # type: ignore[no-untyped-def]
        return builder.build(task, _definitions()[AgentRole.CODER], attempt=1)

    with pytest.raises(KnowledgeGapRaised) as caught:
        ProductionProjectDeliveryBackend._guard("Delivery", consult)
    assert KnowledgeGapService(records).unresolved(caught.value.gap.binding)
