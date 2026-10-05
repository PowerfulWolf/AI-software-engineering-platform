"""Context registration contract for the Agent Run context builder."""

from pathlib import Path

from ai_software_engineer.context import ContextSource, InMemoryContextStore
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.orchestration import FileRunContextBuilder
from tests.domain.factories import make_agent, make_task


def test_run_context_builder_registers_the_exact_returned_manifest(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    task = make_task().model_copy(update={"repository": str(project)})
    store = InMemoryContextStore()
    builder = FileRunContextBuilder(project, context_store=store)

    bundle = builder.build(task, make_agent(), attempt=1)

    assert store.get(bundle.context_id) == bundle


def test_reclaimed_same_attempt_has_its_own_immutable_claim_context(tmp_path: Path) -> None:
    task = make_task().model_copy(update={"repository": str(tmp_path)})
    store = InMemoryContextStore()
    generation = 1

    def source() -> ContextSource:
        return ContextSource(
            source_id="execution.claim",
            uri=f"claim://lease_context_{generation}",
            content=f"work item same; dispatch generation {generation}",
            roles=(AgentRole.CODER,),
            required=True,
            priority=5,
        )

    builder = FileRunContextBuilder(tmp_path, context_store=store, claim_context=source)
    old = builder.build(task, make_agent(), attempt=1)
    generation = 2
    new = builder.build(task, make_agent(), attempt=1)
    assert old.context_id != new.context_id
    assert old.attempt == new.attempt and old.source_revision == new.source_revision
    assert store.get(old.context_id) == old and store.get(new.context_id) == new
