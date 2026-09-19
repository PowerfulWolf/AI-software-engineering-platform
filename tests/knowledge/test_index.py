"""Executable contracts for asynchronous scope-owned knowledge indexing."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.knowledge.index import IndexedKnowledgeRetrieval, KnowledgeIndexer
from ai_software_engineer.knowledge.index_models import (
    KnowledgeChunkCache,
    KnowledgeIndexJob,
    KnowledgeIndexManifest,
)
from ai_software_engineer.knowledge.models import KnowledgeError, KnowledgeSnapshot
from ai_software_engineer.knowledge.retrieval import MarkdownKnowledgeRetrieval
from ai_software_engineer.knowledge_documents import KnowledgeRetirement, TeamKnowledgeDocumentStore
from ai_software_engineer.knowledge_selection import TeamKnowledgeSelectionStore
from ai_software_engineer.team_workspace import TeamWorkspace


def _team(tmp_path: Path) -> TeamWorkspace:
    return TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")


def test_upload_does_not_parse_and_restarts_with_durable_job(tmp_path: Path) -> None:
    team = _team(tmp_path)
    indexer = KnowledgeIndexer(team)
    job = indexer.enqueue(filename="guide.md", content=b"# Guide\n\nReview evidence.\n")
    assert job.status == "QUEUED"
    assert TeamKnowledgeDocumentStore(team).list() == ()
    restarted = KnowledgeIndexer(team)
    assert restarted.status().backlog == 1
    assert restarted.tick()[0].status == "READY"
    assert restarted.status().active_manifest is not None
    assert (
        restarted.enqueue(filename="guide.md", content=b"# Guide\n\nReview evidence.\n").job_id
        == job.job_id
    )
    assert restarted.tick() == ()


def test_failed_parse_keeps_previous_snapshot_and_explicit_retry(tmp_path: Path) -> None:
    indexer = KnowledgeIndexer(_team(tmp_path))
    indexer.enqueue(filename="ok.md", content=b"# OK\nEvidence\n")
    indexer.tick()
    before = indexer.status().active_manifest
    bad = indexer.enqueue(filename="bad.pdf", content=b"broken document")
    assert indexer.tick()[0].status == "FAILED"
    assert indexer.status().active_manifest == before
    assert indexer.retry(bad.job_id).status == "QUEUED"
    assert indexer.tick()[0].status == "FAILED"


def test_selection_and_retirement_reuse_chunks(tmp_path: Path) -> None:
    team = _team(tmp_path)
    indexer = KnowledgeIndexer(team)
    indexer.enqueue(filename="guide.md", content=b"# Guide\nReview first\n")
    ready = indexer.tick()[0]
    document = TeamKnowledgeDocumentStore(team).list()[0]
    before = indexer.status().active_manifest
    TeamKnowledgeSelectionStore(team).save((document.normalized_relative_path,))
    assert indexer.tick() == ()
    selected = indexer.status().active_manifest
    assert selected is not None and before is not None
    assert selected.manifest_sha256 != before.manifest_sha256
    assert selected.documents[0].cache_key == before.documents[0].cache_key
    TeamKnowledgeSelectionStore(team).save(())
    TeamKnowledgeDocumentStore(team).retire(document.document_id)
    assert indexer.current_documents() == ()
    indexer.tick()
    assert next(j for j in indexer.status().jobs if j.job_id == ready.job_id).status == "RETIRED"


def test_concurrent_enqueue_and_workers_deduplicate(tmp_path: Path) -> None:
    team = _team(tmp_path)
    indexer = KnowledgeIndexer(team)
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = tuple(
            pool.map(lambda _: indexer.enqueue(filename="same.md", content=b"# Same"), range(8))
        )
    assert len({job.job_id for job in jobs}) == 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        tuple(pool.map(lambda _: KnowledgeIndexer(team).tick(), range(4)))
    assert len(indexer.status().jobs) == 1
    assert indexer.status().jobs[0].status == "READY"


def test_replacement_transfers_selection_after_success(tmp_path: Path) -> None:
    team = _team(tmp_path)
    indexer = KnowledgeIndexer(team)
    indexer.enqueue(filename="guide.md", content=b"# Old\nOld policy")
    indexer.tick()
    original = TeamKnowledgeDocumentStore(team).list()[0]
    TeamKnowledgeSelectionStore(team).save((original.normalized_relative_path,))
    replacement = indexer.enqueue(
        filename="guide.md", content=b"# New\nNew policy", replaces_document_id=original.document_id
    )
    assert TeamKnowledgeDocumentStore(team).list() == (original,)
    assert indexer.tick()[0].job_id == replacement.job_id
    current = TeamKnowledgeDocumentStore(team).list()[0]
    assert current.document_id != original.document_id
    selection = TeamKnowledgeSelectionStore(team).load()
    assert selection is not None
    assert selection.selected_paths == (current.normalized_relative_path,)
    assert (team.root / "knowledge" / original.normalized_relative_path).is_file()


def test_project_scope_and_job_retry_are_isolated(tmp_path: Path) -> None:
    team = _team(tmp_path)
    first = team.project_registry().create(name="First")
    second = team.project_registry().create(name="Second")
    indexer = KnowledgeIndexer(first)
    job = indexer.enqueue(filename="private.md", content=b"# First only")
    indexer.tick()
    other = KnowledgeIndexer(second)
    assert other.status().jobs == ()
    with pytest.raises(KnowledgeError):
        other.retry(job.job_id)


def test_version_upgrade_rebuilds_only_new_version(tmp_path: Path) -> None:
    team = _team(tmp_path)
    initial = KnowledgeIndexer(team)
    initial.enqueue(filename="guide.md", content=b"# Guide")
    initial.tick()
    upgraded = KnowledgeIndexer(team, parser_version="markdown-v2")
    assert len(upgraded.tick()) == 1
    assert upgraded.tick() == ()
    assert len(upgraded.status().jobs) == 2


def test_cached_adapter_exact_parity_and_historical_retirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    team = _team(tmp_path)
    indexer = KnowledgeIndexer(team)
    indexer.enqueue(
        filename="guide.md",
        content="# Payments\n\nRefunds use original payment ID.\n退款原支付单号".encode(),
    )
    indexer.tick()
    imported = TeamKnowledgeDocumentStore(team).list()[0]
    TeamKnowledgeSelectionStore(team).save((imported.normalized_relative_path,))
    indexer.tick()
    (doc,) = indexer.current_documents()
    frozen = KnowledgeSnapshot.create(
        team_id="team_test",
        project_id="project_payments",
        requirement_id="requirement_refund",
        repository_ids=("repository_payments",),
        documents=(doc,),
    )
    baseline = MarkdownKnowledgeRetrieval()
    expected = baseline.search(frozen, "payment 原支付")
    monkeypatch.setattr(
        "ai_software_engineer.knowledge.index.parse_document",
        lambda _: pytest.fail("cached document reparsed"),
    )
    adapter = IndexedKnowledgeRetrieval((indexer,))
    assert adapter.search(frozen, "payment 原支付") == expected
    TeamKnowledgeDocumentStore(team).retire(doc.document_id)
    assert indexer.current_documents() == ()
    assert adapter.read(frozen, expected[0].citation) == baseline.read(frozen, expected[0].citation)


def test_claim_recovery_and_stale_owner_cannot_publish(tmp_path: Path) -> None:
    now = datetime(2026, 9, 19, tzinfo=UTC)
    indexer = KnowledgeIndexer(_team(tmp_path), clock=lambda: now)
    indexer.enqueue(filename="guide.md", content=b"# Guide")
    claim = indexer.store.claim(
        now=now,
        parser_version=indexer.parser_version,
        index_version=indexer.index_version,
        lease_seconds=1,
    )
    assert claim is not None
    first, _, token = claim
    reclaimed = indexer.store.claim(
        now=now + timedelta(seconds=2),
        parser_version=indexer.parser_version,
        index_version=indexer.index_version,
    )
    assert reclaimed is not None and reclaimed[0].attempts == 2
    with pytest.raises(KnowledgeError, match="CLAIM_LOST"):
        indexer.store.finish(first, token, now=now + timedelta(seconds=2))


def test_index_schema_models_are_current(tmp_path: Path) -> None:
    from jsonschema import Draft202012Validator

    indexer = KnowledgeIndexer(_team(tmp_path))
    indexer.enqueue(filename="guide.md", content=b"# Guide")
    indexer.tick()
    status = indexer.status()
    assert status.active_manifest is not None
    cache = indexer.store.cache(status.active_manifest.documents[0].cache_key)
    assert cache is not None
    for name, model, value in (
        ("knowledge-index-job", KnowledgeIndexJob, status.jobs[0]),
        ("knowledge-index-manifest", KnowledgeIndexManifest, status.active_manifest),
        ("knowledge-index-chunk-cache", KnowledgeChunkCache, cache),
    ):
        schema = json.loads(
            (Path(__file__).parents[2] / "schemas" / (name + ".schema.json")).read_text()
        )
        Draft202012Validator(schema).validate(value.to_wire())
        assert {
            key: val for key, val in schema.items() if key not in {"$id", "$schema"}
        } == model.model_json_schema()


def test_backoff_is_bounded_and_retry_history_is_preserved(tmp_path: Path) -> None:
    now = datetime(2026, 9, 19, tzinfo=UTC)
    indexer = KnowledgeIndexer(_team(tmp_path), clock=lambda: now)
    job = indexer.enqueue(filename="broken.pdf", content=b"invalid pdf")
    assert indexer.tick()[0].attempts == 1
    assert indexer.tick() == ()
    now += timedelta(seconds=11)
    assert indexer.tick()[0].attempts == 2
    now += timedelta(seconds=21)
    assert indexer.tick()[0].attempts == 3
    now += timedelta(hours=1)
    assert indexer.tick() == ()
    indexer.retry(job.job_id)
    assert indexer.tick()[0].status == "FAILED"
    history = indexer.store.history(job.job_id)
    assert [event.status for event in history].count("FAILED") == 4
    assert history[0] == job


def test_replayed_document_does_not_repeat_extraction_or_chunking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team = _team(tmp_path)
    indexer = KnowledgeIndexer(team)
    indexer.enqueue(filename="guide.md", content=b"# Guide")
    indexer.tick()
    monkeypatch.setattr(
        "ai_software_engineer.knowledge_documents._normalize",
        lambda *_: pytest.fail("document extracted twice"),
    )
    monkeypatch.setattr(
        "ai_software_engineer.knowledge.index.parse_document",
        lambda *_: pytest.fail("document parsed twice"),
    )
    indexer.enqueue(filename="guide.md", content=b"# Guide")
    assert indexer.tick() == ()
    TeamKnowledgeDocumentStore(team).import_document(filename="guide.md", content=b"# Guide")


def test_replacement_conflicts_do_not_retire_wrong_document(tmp_path: Path) -> None:
    team = _team(tmp_path)
    indexer = KnowledgeIndexer(team)
    old = indexer.enqueue(filename="guide.md", content=b"# Old")
    indexer.tick()
    manifest = TeamKnowledgeDocumentStore(team).list()[0]
    TeamKnowledgeSelectionStore(team).save((manifest.normalized_relative_path,))
    first = indexer.enqueue(
        filename="guide.md", content=b"# First", replaces_document_id=old.document_id
    )
    with pytest.raises(KnowledgeError, match="REPLACEMENT_STALE"):
        indexer.enqueue(
            filename="guide.md", content=b"# Second", replaces_document_id=old.document_id
        )
    assert indexer.tick()[0].job_id == first.job_id
    assert [document.document_id for document in indexer.current_documents()] == [first.document_id]


def test_tampered_cache_and_cross_scope_database_are_rejected(tmp_path: Path) -> None:
    team = _team(tmp_path)
    indexer = KnowledgeIndexer(team)
    indexer.enqueue(filename="guide.md", content=b"# Guide")
    indexer.tick()
    manifest = indexer.status().active_manifest
    assert manifest is not None
    key = manifest.documents[0].cache_key
    with indexer.store.connection() as connection:
        connection.execute(
            "UPDATE chunks SET payload=json_set(payload,'$.chunks[0].content','tampered') "
            "WHERE cache_key=?",
            (key,),
        )
    with pytest.raises(KnowledgeError, match="INTEGRITY"):
        indexer.store.cache(key)
    from ai_software_engineer.knowledge.index_store import KnowledgeIndexStore

    with pytest.raises(KnowledgeError, match="OWNER_MISMATCH"):
        KnowledgeIndexStore(
            indexer.store.root, scope="project", team_id="team_test", project_id="project_other"
        )


def test_incomplete_build_preserves_previous_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    indexer = KnowledgeIndexer(_team(tmp_path))
    indexer.enqueue(filename="guide.md", content=b"# Existing")
    indexer.tick()
    before = indexer.status().active_manifest
    indexer.enqueue(filename="new.md", content=b"# New")

    def fail_parse(_: object) -> tuple[()]:
        raise KnowledgeError("PARSER_FAILED")

    monkeypatch.setattr("ai_software_engineer.knowledge.index.parse_document", fail_parse)
    assert indexer.tick()[0].status == "FAILED"
    assert indexer.status().active_manifest == before


def test_retired_document_can_be_reimported_without_changing_history(tmp_path: Path) -> None:
    team = _team(tmp_path)
    indexer = KnowledgeIndexer(team)
    original = indexer.enqueue(filename="guide.md", content=b"# Guide")
    indexer.tick()
    TeamKnowledgeDocumentStore(team).retire(original.document_id)
    indexer.tick()
    assert indexer.enqueue(filename="guide.md", content=b"# Guide").status == "QUEUED"
    assert indexer.tick()[0].status == "READY"
    manifest = TeamKnowledgeDocumentStore(team).list()[0]
    TeamKnowledgeSelectionStore(team).save((manifest.normalized_relative_path,))
    indexer.tick()
    assert len(indexer.current_documents()) == 1
    assert "RETIRED" in {job.status for job in indexer.store.history(original.job_id)}


def test_same_source_different_format_gets_distinct_parse_job(tmp_path: Path) -> None:
    indexer = KnowledgeIndexer(_team(tmp_path))
    wrong_format = indexer.enqueue(filename="guide.pdf", content=b"# Markdown guide")
    assert indexer.tick()[0].status == "FAILED"
    corrected = indexer.enqueue(filename="guide.md", content=b"# Markdown guide")
    assert corrected.job_id != wrong_format.job_id
    assert corrected.status == "QUEUED"
    assert indexer.tick()[0].status == "READY"
    # Renaming within the same parser format still deduplicates exactly.
    assert (
        indexer.enqueue(filename="renamed.md", content=b"# Markdown guide").job_id
        == corrected.job_id
    )


def test_deselection_excludes_current_queries_before_and_after_tick(tmp_path: Path) -> None:
    team = _team(tmp_path)
    indexer = KnowledgeIndexer(team)
    indexer.enqueue(filename="guide.md", content=b"# Guide")
    indexer.tick()
    assert indexer.current_documents() == ()
    manifest = TeamKnowledgeDocumentStore(team).list()[0]
    TeamKnowledgeSelectionStore(team).save((manifest.normalized_relative_path,))
    indexer.tick()
    assert len(indexer.current_documents()) == 1
    TeamKnowledgeSelectionStore(team).save(())
    assert indexer.current_documents() == ()
    indexer.tick()
    assert indexer.current_documents() == ()


def test_claim_reads_only_selected_job_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    indexer = KnowledgeIndexer(_team(tmp_path))
    indexer.enqueue(filename="ready.md", content=b"# Ready")
    indexer.tick()
    queued = indexer.enqueue(filename="queued.md", content=b"# Queued")
    statements: list[str] = []
    original_connect = sqlite3.connect

    def tracked_connect(path: Path, *, timeout: int) -> sqlite3.Connection:
        connection = original_connect(path, timeout=timeout)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(
        "ai_software_engineer.knowledge.index_store.sqlite3.connect", tracked_connect
    )
    claimed = indexer.store.claim(
        now=datetime.now(UTC),
        parser_version=indexer.parser_version,
        index_version=indexer.index_version,
    )
    assert claimed is not None and claimed[0].job_id == queued.job_id
    source_reads = [sql for sql in statements if sql.startswith("SELECT") and "source" in sql]
    assert len(source_reads) == 1
    assert "WHERE job_id=" in source_reads[0]
    assert queued.job_id in source_reads[0]


def test_failed_unrelated_document_does_not_hide_successful_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.knowledge.models import KnowledgeChunk, KnowledgeDocument
    from ai_software_engineer.knowledge.retrieval import parse_document

    team = _team(tmp_path)
    indexer = KnowledgeIndexer(team)
    original = indexer.enqueue(filename="old.md", content=b"# Old")
    indexer.tick()
    manifest = indexer.documents.list()[0]
    indexer.selection.save((manifest.normalized_relative_path,))
    indexer.tick()

    def parse(document: KnowledgeDocument) -> tuple[KnowledgeChunk, ...]:
        if document.content.startswith("# Broken"):
            raise KnowledgeError("PARSER_FAILED")
        return parse_document(document)

    monkeypatch.setattr("ai_software_engineer.knowledge.index.parse_document", parse)
    indexer.enqueue(filename="broken.md", content=b"# Broken")
    assert indexer.tick()[0].status == "FAILED"
    replacement = indexer.enqueue(
        filename="new.md", content=b"# New", replaces_document_id=original.document_id
    )
    assert indexer.tick()[0].status == "READY"
    assert [doc.document_id for doc in indexer.current_documents()] == [replacement.document_id]
    assert original.document_id in indexer.documents.retirement().retired_document_ids


def test_failed_selected_replacement_keeps_old_document_available(tmp_path: Path) -> None:
    indexer = KnowledgeIndexer(_team(tmp_path))
    original = indexer.enqueue(filename="old.md", content=b"# Old")
    indexer.tick()
    manifest = indexer.documents.list()[0]
    indexer.selection.save((manifest.normalized_relative_path,))
    indexer.tick()
    before = indexer.store.active()
    indexer.enqueue(
        filename="broken.pdf", content=b"invalid", replaces_document_id=original.document_id
    )
    assert indexer.tick()[0].status == "FAILED"
    assert indexer.store.active() == before
    assert [doc.document_id for doc in indexer.current_documents()] == [original.document_id]


@pytest.mark.parametrize("scope", ["team", "project"])
def test_replacement_cannot_overwrite_concurrent_deselection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    from threading import Event

    team = _team(tmp_path)
    indexer = KnowledgeIndexer(
        team if scope == "team" else team.project_registry().create(name="Project")
    )
    original = indexer.enqueue(filename="old.md", content=b"# Old")
    indexer.tick()
    manifest = indexer.documents.list()[0]
    indexer.selection.save((manifest.normalized_relative_path,))
    indexer.tick()
    indexer.enqueue(filename="new.md", content=b"# New", replaces_document_id=original.document_id)
    read_selection, resume, saved = Event(), Event(), Event()
    paths = indexer._paths

    def paused_paths() -> tuple[str, ...]:
        result = paths()
        if not read_selection.is_set():
            read_selection.set()
            assert resume.wait(5)
        return result

    def deselect() -> None:
        indexer.selection.save(())
        saved.set()

    monkeypatch.setattr(indexer, "_paths", paused_paths)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replacement = pool.submit(indexer.tick)
        assert read_selection.wait(5)
        deselection = pool.submit(deselect)
        saved.wait(0.05)
        resume.set()
        replacement.result(timeout=5)
        deselection.result(timeout=5)
    selection = indexer.selection.load()
    assert selection is not None and selection.selected_paths == ()
    assert indexer.current_documents() == ()


def test_replacement_publish_failure_cannot_retire_trusted_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    indexer = KnowledgeIndexer(_team(tmp_path))
    original = indexer.enqueue(filename="old.md", content=b"# Old")
    indexer.tick()
    manifest = indexer.documents.list()[0]
    indexer.selection.save((manifest.normalized_relative_path,))
    indexer.tick()
    indexer.enqueue(filename="new.md", content=b"# New", replaces_document_id=original.document_id)
    publish = indexer.store.publish
    failed = False

    def fail_first_publish(manifest: KnowledgeIndexManifest) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise KnowledgeError("INDEX_STORE_UNAVAILABLE")
        publish(manifest)

    monkeypatch.setattr(indexer.store, "publish", fail_first_publish)
    assert indexer.tick()[0].status == "FAILED"
    assert original.document_id not in indexer.documents.retirement().retired_document_ids
    assert [doc.document_id for doc in indexer.current_documents()] == [original.document_id]


def test_concurrent_retirements_do_not_drop_each_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event

    store = TeamKnowledgeDocumentStore(_team(tmp_path))
    first = store.import_document(filename="first.md", content=b"# First")
    second = store.import_document(filename="second.md", content=b"# Second")
    first_read, resume, second_done = Event(), Event(), Event()
    retirement = TeamKnowledgeDocumentStore.retirement

    def paused_retirement(self: TeamKnowledgeDocumentStore) -> KnowledgeRetirement:
        result = retirement(self)
        if not first_read.is_set():
            first_read.set()
            assert resume.wait(5)
        return result

    def retire_second() -> None:
        store.retire(second.document_id)
        second_done.set()

    monkeypatch.setattr(TeamKnowledgeDocumentStore, "retirement", paused_retirement)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_retirement = pool.submit(store.retire, first.document_id)
        assert first_read.wait(5)
        second_retirement = pool.submit(retire_second)
        second_done.wait(0.05)
        resume.set()
        first_retirement.result(timeout=5)
        second_retirement.result(timeout=5)
    assert set(store.retirement().retired_document_ids) == {first.document_id, second.document_id}


def test_replacement_recovers_after_publication_before_selection_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 9, 19, tzinfo=UTC)
    team = _team(tmp_path)
    indexer = KnowledgeIndexer(team, clock=lambda: now)
    original = indexer.enqueue(filename="old.md", content=b"# Old")
    indexer.tick()
    manifest = indexer.documents.list()[0]
    indexer.selection.save((manifest.normalized_relative_path,))
    indexer.tick()
    replacement = indexer.enqueue(
        filename="new.md", content=b"# New", replaces_document_id=original.document_id
    )

    def crash_before_selection(
        self: TeamKnowledgeSelectionStore, selected_paths: tuple[str, ...]
    ) -> None:
        raise SystemExit("simulated worker interruption")

    with monkeypatch.context() as patch:
        patch.setattr(TeamKnowledgeSelectionStore, "save", crash_before_selection)
        with pytest.raises(SystemExit, match="worker interruption"):
            indexer.tick()
    restarted = KnowledgeIndexer(team, clock=lambda: now)
    assert [doc.document_id for doc in restarted.current_documents()] == [original.document_id]
    now += timedelta(seconds=301)
    assert restarted.tick()[0].status == "READY"
    assert [doc.document_id for doc in restarted.current_documents()] == [replacement.document_id]


def test_scope_mutation_lock_rejects_symlink_without_writing_target(tmp_path: Path) -> None:
    from ai_software_engineer.knowledge.mutation import knowledge_mutation_lock

    knowledge = _team(tmp_path).root / "knowledge"
    outside = tmp_path / "outside.txt"
    outside.write_text("preserved")
    (knowledge / "mutation.lock").symlink_to(outside)
    with pytest.raises(OSError), knowledge_mutation_lock(knowledge):
        pytest.fail("symlink lock was accepted")
    assert outside.read_text() == "preserved"
