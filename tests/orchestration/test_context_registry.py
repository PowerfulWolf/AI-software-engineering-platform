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


def test_run_source_selector_is_per_claim_and_keeps_old_context_immutable(tmp_path: Path) -> None:
    task = make_task().model_copy(update={"repository": str(tmp_path)})
    store = InMemoryContextStore()
    current = "first"

    def select(task_arg, agent_arg, attempt_arg, artifacts_arg):
        assert task_arg == task
        assert agent_arg.role is AgentRole.CODER
        assert attempt_arg == 1 and artifacts_arg == ()
        return (
            ContextSource(
                source_id="selected.patch",
                uri=f"source://{current}",
                content=current,
                roles=(AgentRole.CODER,),
                required=True,
            ),
        )

    builder = FileRunContextBuilder(
        tmp_path,
        context_store=store,
        source_selector=select,
    )
    first = builder.build(task, make_agent(), attempt=1)
    current = "second"
    second = builder.build(task, make_agent(), attempt=1)
    assert first.context_id != second.context_id
    assert store.get(first.context_id) == first
    assert next(s for s in second.sections if s.name == "source:selected.patch").content == "second"
