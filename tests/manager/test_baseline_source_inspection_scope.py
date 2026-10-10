"""Real baseline reads share bounded pure scans without reusing authorization or files."""

import ast
import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer import redaction
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode
from ai_software_engineer.knowledge.models import KnowledgeError
from ai_software_engineer.manager.baseline_models import (
    BaselineContinueAuthorization,
    BaselineOperatorAuthorization,
)
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.redaction import source_secret_occurrences
from tests.manager.test_execution_baseline import authorize, setup
from tests.orchestration.test_continuation_records import NOW
from tests.orchestration.test_native_continuation_v2 import V2Fixture
from tests.orchestration.test_native_continuation_v2 import denied_paths as denied_paths
from tests.orchestration.test_native_continuation_v2 import transient_limit as transient_limit
from tests.orchestration.test_native_continuation_v2 import v2_fixture as v2_fixture
from tests.orchestration.test_native_continuation_v2 import work_limit as work_limit

LARGE_SOURCE = "VALUE = 2\nEXTRA = 3\n" + "".join(
    f"def value_{index}():\n    token=settings.token\n    return token\n\n" for index in range(300)
)


@contextmanager
def parsed_sources(monkeypatch: pytest.MonkeyPatch) -> Iterator[Counter[str]]:
    original = ast.parse
    calls: Counter[str] = Counter()

    def counted(source: str, filename: str = "<unknown>", mode: str = "exec") -> ast.AST:
        calls[source] += 1
        return cast(ast.AST, original(source, filename, mode))

    monkeypatch.setattr(ast, "parse", counted)
    yield calls


def test_standalone_plan_read_scans_large_complete_source_once_and_releases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = setup(tmp_path)
    (fixture.worktree.path / "src/app.py").write_text(LARGE_SOURCE)
    plan = fixture.service.propose(fixture.target)
    before = {path.name: path.read_bytes() for path in fixture.service.store.root.iterdir()}
    with parsed_sources(monkeypatch) as calls:
        loaded = fixture.service.store.plan(plan.plan_sha256)
        assert loaded == plan
        assert calls[LARGE_SOURCE] == 1
        assert fixture.service.store.plan(plan.plan_sha256) == plan
        assert calls[LARGE_SOURCE] == 2, "a new read must not retain the previous scope"
    assert {path.name: path.read_bytes() for path in fixture.service.store.root.iterdir()} == before


def test_proposal_shares_fresh_capture_and_sealed_plan_scans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = setup(tmp_path)
    source_path = fixture.worktree.path / "src/app.py"
    source_path.write_text(LARGE_SOURCE)
    with parsed_sources(monkeypatch) as calls:
        first = fixture.service.propose(fixture.target)
        assert calls[LARGE_SOURCE] == 1
        assert fixture.service.propose(fixture.target) == first
        assert calls[LARGE_SOURCE] == 2
    assert source_path.read_text() == LARGE_SOURCE


def test_execution_shares_capture_store_and_binding_scans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = setup(tmp_path)
    (fixture.worktree.path / "src/app.py").write_text(LARGE_SOURCE)
    plan = fixture.service.propose(fixture.target)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="explicitly preserve progress and pause",
        submitted_at=NOW,
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    with parsed_sources(monkeypatch) as calls:
        binding = fixture.service.execute(plan.plan_sha256, authority=authority)
        assert calls[LARGE_SOURCE] == 1
        assert fixture.service.execute(plan.plan_sha256, authority=authority) == binding
        assert calls[LARGE_SOURCE] == 2
    assert binding.continuation_mode is BaselineContinuationMode.PAUSE


def test_standalone_binding_reads_share_nested_plan_checks_and_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = setup(tmp_path)
    (fixture.worktree.path / "src/app.py").write_text(LARGE_SOURCE)
    plan = fixture.service.propose(fixture.target)
    binding = fixture.service.execute(plan.plan_sha256, authority=authorize(plan))
    store = fixture.service.store
    before = {path.name: path.read_bytes() for path in store.root.iterdir()}
    with parsed_sources(monkeypatch) as calls:
        started = store.start(plan.plan_sha256)
        assert started is not None and started.plan == plan
        assert calls[LARGE_SOURCE] == 1
        assert store.bindings_for_task(binding.task_id) == (binding,)
        assert calls[LARGE_SOURCE] == 2
        assert plan.complete_capture.patch in store.required_context(binding)
        assert calls[LARGE_SOURCE] == 3
    assert {path.name: path.read_bytes() for path in store.root.iterdir()} == before


def test_receipt_reads_and_replayed_publication_share_complete_capture_scans(
    v2_fixture: V2Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = v2_fixture
    receipt = fixture.interrupt(fixture.service(), text=LARGE_SOURCE)
    before = {path.name: path.read_bytes() for path in fixture.store_root.iterdir()}
    with parsed_sources(monkeypatch) as calls:
        assert fixture.store.get_receipt(receipt.request.run_id) == receipt
        assert calls[LARGE_SOURCE] == 1
        assert fixture.store.receipts_for_task(receipt.request.task_id) == (receipt,)
        assert calls[LARGE_SOURCE] == 2
        assert fixture.store.put_receipt(receipt) == receipt
        assert calls[LARGE_SOURCE] == 3
    assert {path.name: path.read_bytes() for path in fixture.store_root.iterdir()} == before


def test_continuation_shares_complete_checks_then_releases_before_caller_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = setup(tmp_path)
    (fixture.worktree.path / "src/app.py").write_text(LARGE_SOURCE)
    facts = fixture.collector.facts.model_copy(update={"checkpoint_sequence": 2})
    fixture.collector.facts = facts.model_copy(
        update={"facts_sha256": digest(facts.model_dump(mode="json", exclude={"facts_sha256"}))}
    )
    plan = fixture.service.propose(fixture.target)
    operator = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="preserve progress first",
        submitted_at=NOW,
        continuation_mode=BaselineContinuationMode.PAUSE,
    )
    binding = fixture.service.execute(plan.plan_sha256, authority=operator)
    fixture.collector.worktree = replace(
        fixture.worktree, head_revision=binding.execution_source_revision
    )
    authority = BaselineContinueAuthorization.create(
        scope=binding.scope,
        task_id=binding.task_id,
        task_intent_sha256=binding.task_intent_sha256,
        task_revision=facts.task_revision,
        work_item_id=facts.work_item_id,
        execution_baseline_sha256=binding.binding_sha256,
        expected_source_revision=binding.execution_source_revision,
        checkpoint_sequence=facts.task_revision,
        expected_disposition_sha256="f" * 64,
        inventory_sha256=binding.after_inventory_sha256,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="explicit continue decision",
        submitted_at=NOW,
    )
    fixture.service.publish_continuation = lambda bound, decision: (
        bound == binding and decision == authority
    )
    with parsed_sources(monkeypatch) as calls:
        assert fixture.service.continue_execution(binding.binding_sha256, authority=authority)
        assert calls[LARGE_SOURCE] == 1
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None
        # Host starts its model only after the synchronous service returns. A caller
        # scanning the same input must get a fresh check, even on exact replay.
        assert not source_secret_occurrences(LARGE_SOURCE, source_path="src/app.py")
        assert calls[LARGE_SOURCE] == 2
        assert fixture.service.continue_execution(binding.binding_sha256, authority=authority)
        assert calls[LARGE_SOURCE] == 3
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None


def test_failed_plan_integrity_check_releases_source_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = setup(tmp_path)
    (fixture.worktree.path / "src/app.py").write_text(LARGE_SOURCE)
    plan = fixture.service.propose(fixture.target)
    path = next(fixture.service.store.root.glob("baseline-plans-*.json"))
    envelope = json.loads(path.read_text())
    envelope["record"]["plan_sha256"] = "e" * 64
    envelope["sha256"] = digest(envelope["record"])
    path.write_text(json.dumps(envelope))
    with parsed_sources(monkeypatch) as calls:
        with pytest.raises(ValueError, match="integrity mismatch"):
            fixture.service.store.plan(plan.plan_sha256)
        assert calls[LARGE_SOURCE] == 1
        assert redaction._SOURCE_INSPECTION_CACHE.get() is None
        assert not source_secret_occurrences(LARGE_SOURCE, source_path="src/app.py")
        assert calls[LARGE_SOURCE] == 2


@pytest.mark.parametrize("change", ["text", "path", "envelope"])
def test_nested_scope_rereads_files_and_rejects_changed_source_path_or_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    fixture = setup(tmp_path)
    (fixture.worktree.path / "src/app.py").write_text(LARGE_SOURCE)
    plan = fixture.service.propose(fixture.target)
    path = next(fixture.service.store.root.glob("baseline-plans-*.json"))
    with parsed_sources(monkeypatch) as calls, redaction.source_inspection_scope():
        assert fixture.service.store.plan(plan.plan_sha256) == plan
        assert calls[LARGE_SOURCE] == 1
        envelope = json.loads(path.read_text())
        mutation = envelope["record"]["dirty_capture"]["mutations"][0]
        if change == "text":
            changed = LARGE_SOURCE + 'password="actual-private-value"\n'
            mutation["after"].update(
                text=changed,
                sha256=hashlib.sha256(changed.encode()).hexdigest(),
                size=len(changed.encode()),
            )
            envelope["sha256"] = digest(envelope["record"])
        elif change == "path":
            mutation["path"] = "src/app.env"
            envelope["sha256"] = digest(envelope["record"])
        else:
            envelope["sha256"] = "e" * 64
        path.write_text(json.dumps(envelope))
        with pytest.raises(KnowledgeError, match="STORE_CORRUPT"):
            fixture.service.store.plan(plan.plan_sha256)
        if change == "text":
            assert calls[changed] > 0, "changed source cannot borrow the previous safe scan"
        assert calls[LARGE_SOURCE] == 1
    assert redaction._SOURCE_INSPECTION_CACHE.get() is None
