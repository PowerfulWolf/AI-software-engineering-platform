"""Context registration contract for the Agent Run context builder."""

from pathlib import Path

from ai_software_engineer.context import InMemoryContextStore
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
