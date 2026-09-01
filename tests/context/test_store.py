"""Behavior tests for the in-process ContextBundle registry."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.context import (
    ContextBundle,
    ContextConflict,
    ContextCorruption,
    ContextNotFound,
    FileContextStore,
    InMemoryContextStore,
)
from ai_software_engineer.orchestration import FileRunContextBuilder
from tests.domain.factories import NOW, make_agent, make_task


def _bundle(tmp_path: Path) -> ContextBundle:
    project = tmp_path / "project"
    project.mkdir()
    task = make_task().model_copy(update={"repository": str(project)})
    return FileRunContextBuilder(project).build(
        task,
        make_agent(),
        attempt=1,
    )


def test_context_store_returns_registered_bundle_and_replays_identity(tmp_path: Path) -> None:
    store = InMemoryContextStore()
    bundle = _bundle(tmp_path)

    first = store.put(bundle)
    replay = store.put(bundle.model_copy(update={"built_at": NOW + timedelta(days=1)}))

    assert first == bundle
    assert replay == bundle
    assert store.get(bundle.context_id) == bundle


def test_context_store_rejects_same_id_with_different_manifest_identity(tmp_path: Path) -> None:
    store = InMemoryContextStore()
    bundle = _bundle(tmp_path)
    store.put(bundle)

    changed = bundle.model_copy(update={"source_revision": "different-revision"})

    with pytest.raises(ContextConflict):
        store.put(changed)
    assert store.get(bundle.context_id) == bundle


def test_context_store_reports_unknown_manifest() -> None:
    with pytest.raises(ContextNotFound):
        InMemoryContextStore().get("ctx_" + "f" * 64)


def test_file_context_store_rejects_non_context_id_paths(tmp_path: Path) -> None:
    with pytest.raises(ContextNotFound):
        FileContextStore(tmp_path / "contexts").get("../../outside")


def test_file_context_store_round_trips_and_preserves_first_observation(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    store = FileContextStore(tmp_path / "contexts")

    first = store.put(bundle)
    replay = store.put(bundle.model_copy(update={"built_at": NOW + timedelta(days=1)}))

    assert first == bundle
    assert replay == bundle
    assert store.get(bundle.context_id) == bundle
    assert (tmp_path / "contexts" / f"{bundle.context_id}.json").is_file()


def test_file_context_store_detects_tampering(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    root = tmp_path / "contexts"
    store = FileContextStore(root)
    store.put(bundle)
    path = root / f"{bundle.context_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_revision"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContextCorruption):
        store.get(bundle.context_id)
