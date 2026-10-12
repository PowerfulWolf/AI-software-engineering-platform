"""Real allocation gates reuse only historical decoding, never current source facts."""

from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch

import pytest

from ai_software_engineer.git import WorktreeRef
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline import ProjectSpecBaseline
from ai_software_engineer.manager.dispatch import DispatchWorkforceSnapshot, RecoveryDispatchRecord
from ai_software_engineer.multi_directory.models import JointCheckpoint
from ai_software_engineer.read_record_scope import (
    current_recovery_record_reads,
    recovery_record_read_scope,
)
from ai_software_engineer.recovery.allocation import RecoveryAllocator
from ai_software_engineer.recovery.current import (
    NativeRecoveryFacts,
    NativeRecoveryFactsVerifier,
    _RecoveryTargetPreflight,
)
from ai_software_engineer.recovery.models import CapturedChanges, RecoveryPlan, RecoveryRejected
from ai_software_engineer.repository_profile import RepositoryProfile
from ai_software_engineer.team_workspace import _read_regular
from tests.manager.test_dispatch import _agents, _policy
from tests.recovery.test_authorization import make_plan
from tests.recovery.test_capacity_parent_journal_scope import fixture as capacity_fixture
from tests.recovery.test_preparation_inspection_scope import (
    OfflineAuthority,
    preparation_fixture,
)


def test_real_allocator_keeps_all_reads_and_fences_but_decodes_ancestors_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capacity_root = tmp_path / "capacity"
    capacity_root.mkdir()
    capacity = capacity_fixture(capacity_root, monkeypatch)
    first = JointCheckpoint.seal(
        {
            **capacity.current.to_wire(),
            "delivery_id": "delivery_multi_large_history",
            "title": "Complete large historical requirement",
            "requirement": "Complete retained input " + "x" * 180_000,
        }
    )
    capacity.journal.append(first, expected=None)
    last = first
    for sequence in range(2, 8):
        last = JointCheckpoint.seal(
            {
                **last.to_wire(),
                "sequence": sequence,
                "previous_checkpoint_sha256": last.checkpoint_sha256,
                "next_action": f"Complete historical checkpoint {sequence}",
            }
        )
        capacity.journal.append(last, expected=last.previous_checkpoint_sha256)
    preparation_root = tmp_path / "preparation"
    preparation_root.mkdir()
    prepared = preparation_fixture(preparation_root, monkeypatch)
    facts = prepared.builder._facts
    original_inspect = facts._inspect

    def inspect(plan: RecoveryPlan) -> NativeRecoveryFacts:
        capacity.reader.discover(capacity.scope)
        return original_inspect(plan)

    monkeypatch.setattr(facts, "_inspect", inspect)
    prepared.sealing.seal(prepared.plan.plan_sha256)
    prepared.reads.clear()
    capacity.sql.reset_mock()
    capacity.claims.reset_mock()
    capacity.no_start.reset_mock()
    capacity.captures.reset_mock()
    authority = OfflineAuthority(prepared)
    allocator = RecoveryAllocator(
        sealing=prepared.sealing,
        builder=prepared.builder,
        authority=authority,  # type: ignore[arg-type]
        agents=_agents(),
        policies=(_policy(),),
    )
    paths = tuple(sorted(capacity.journal.root.glob("delivery_multi_*/*.json")))
    reads: Counter[Path] = Counter()
    preflights: Counter[Path] = Counter()
    inventories: Counter[Path] = Counter()
    original_read = Path.read_bytes
    original_glob = Path.glob

    def read(path: Path) -> bytes:
        if path in paths:
            reads[path] += 1
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", read)

    def preflight(path: Path, limit: int) -> bytes:
        if path in paths:
            preflights[path] += 1
        return _read_regular(path, limit)

    def glob(path: Path, pattern: str, **kwargs: object) -> Iterator[Path]:
        if path in {record.parent for record in paths} and pattern == "*.json":
            inventories[path] += 1
        return original_glob(path, pattern, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "glob", glob)
    monkeypatch.setattr("ai_software_engineer.recovery.native._read_regular", preflight)
    monkeypatch.setattr(
        "ai_software_engineer.multi_directory.history_observation._read_regular", preflight
    )
    ancestor = original_read(capacity.journal.directory(first.delivery_id) / "000001.json")
    decodes: Counter[bytes] = Counter()
    original_decode = JointCheckpoint.model_validate_json

    def decode(payload: str | bytes | bytearray, **kwargs: object) -> JointCheckpoint:
        if payload == ancestor:
            decodes[ancestor] += 1
        return original_decode(payload, **kwargs)  # type: ignore[arg-type]

    with patch.object(JointCheckpoint, "model_validate_json", side_effect=decode):
        # This is the same owner boundary already used by NativeRecoveryEntry._execute.
        with recovery_record_read_scope() as owner:
            allocator.allocate(prepared.plan.plan_sha256)
            assert capacity.sql.call_count == capacity.claims.call_count == 64
            assert capacity.no_start.call_count == capacity.captures.call_count == 64
            assert prepared.reads == {
                "facts": 32,
                "capture": 8,
                "snapshot": 1,
                "fence_before": 1,
                "fence_after": 1,
            }
            assert reads == {
                path: 64 if path.parent.name == first.delivery_id else 96 for path in paths
            }, "32 x two parent observations, plus retirement/replacement initial reads"
            assert preflights == reads, "retain original independent complete regular-file reads"
            assert inventories == {
                directory: 128 if directory.name == first.delivery_id else 192
                for directory in {path.parent for path in paths}
            }, "every observation keeps two independently enumerated inventories"
            assert decodes[ancestor] == 1, "all fenced observations share only immutable decoding"
        assert owner.retained_entries == owner.retained_bytes == 0
    assert current_recovery_record_reads() is None


def test_real_allocator_second_fence_still_rejects_changed_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capacity_root = tmp_path / "capacity"
    capacity_root.mkdir()
    capacity = capacity_fixture(capacity_root, monkeypatch)
    preparation_root = tmp_path / "preparation"
    preparation_root.mkdir()
    prepared = preparation_fixture(preparation_root, monkeypatch)
    original_inspect = prepared.builder._facts._inspect

    def inspect(plan: RecoveryPlan) -> NativeRecoveryFacts:
        capacity.reader.discover(capacity.scope)
        return original_inspect(plan)

    monkeypatch.setattr(prepared.builder._facts, "_inspect", inspect)
    prepared.sealing.seal(prepared.plan.plan_sha256)
    authority = OfflineAuthority(prepared)
    original_commit = authority.commit_recovery

    def commit(
        *,
        repository_id: str,
        task_id: str,
        plan_sha256: str,
        validate_current: Callable[[RecoveryDispatchRecord | None], None],
        build: Callable[[DispatchWorkforceSnapshot], RecoveryDispatchRecord],
    ) -> RecoveryDispatchRecord:
        def build_then_change(snapshot: DispatchWorkforceSnapshot) -> RecoveryDispatchRecord:
            record = build(snapshot)
            path = capacity.journal.directory("delivery_multi_retired_snapshot") / "000001.json"
            payload = path.read_text()
            path.write_text(payload.replace("Prepare the repository", "Tampered history data!"))
            return record

        return original_commit(
            repository_id=repository_id,
            task_id=task_id,
            plan_sha256=plan_sha256,
            validate_current=validate_current,
            build=build_then_change,
        )

    monkeypatch.setattr(authority, "commit_recovery", commit)
    allocator = RecoveryAllocator(
        sealing=prepared.sealing,
        builder=prepared.builder,
        authority=authority,  # type: ignore[arg-type]
        agents=_agents(),
        policies=(_policy(),),
    )
    with pytest.raises(RecoveryRejected), recovery_record_read_scope() as owner:
        allocator.allocate(prepared.plan.plan_sha256)
    assert authority.record is None
    assert prepared.reads["fence_before"] == prepared.reads["fence_after"] == 1
    assert owner.retained_entries == owner.retained_bytes == 0


@pytest.mark.parametrize("fault", ("source", "receipt", "policy", "history"))
def test_actual_native_facts_binds_capacity_source_and_receipt_while_prefix_is_warm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    capacity = capacity_fixture(tmp_path, monkeypatch)
    original = capacity.reader.discover(capacity.scope)
    assert original.capacity_receipt is not None and original.capacity_input is not None
    assert original.task.branch_name is not None
    team = capacity.reader._team(capacity.scope)
    _, repository = team.project_registry().locate_repository(capacity.scope.repository_id)
    KnowledgeRecordStore(repository.root / "state/delivery-preflight").put(
        "context-capacity-receipts",
        original.capacity_receipt.receipt_sha256,
        original.capacity_receipt,
    )
    prototype = make_plan(Path(capacity.scope.repository_root))
    capture = CapturedChanges.from_capture(
        replace(
            prototype.capture.to_capture(),
            worktree=WorktreeRef(
                task_id=original.source.task_id,
                role=prototype.capture.to_capture().worktree.role,
                attempt=original.task.attempts,
                path=Path(prototype.capture.worktree_path),
                head_revision=original.source.effective_base_revision,
                branch=original.task.branch_name,
                detached=False,
            ),
        )
    )
    plan = RecoveryPlan.create(
        **{
            **prototype.to_wire(),
            "source": original.source,
            "capture": capture,
            "input_mode": "coder_reapply",
            "context_capacity_input": original.capacity_input,
            "permissions": original.permissions,
            "denied_paths": original.denied_paths,
            "target_branch_name": original.task.branch_name + "-recovery",
        }
    )
    verifier = NativeRecoveryFactsVerifier(capacity.reader.config, {})
    monkeypatch.setattr(
        "ai_software_engineer.recovery.current.LegacyContextCapacitySourceReader",
        Mock(return_value=capacity.reader),
    )
    # Source dispatch and binding are real. Only independent target Git/compiler
    # ports are offline; this test does not claim to exercise target admission.
    target = cast(_RecoveryTargetPreflight, object())
    facts = NativeRecoveryFacts(
        original,
        original.preparation,
        cast(RepositoryProfile, object()),
        cast(ProjectSpecBaseline, object()),
    )
    monkeypatch.setattr(verifier, "_target_preflight", Mock(return_value=target))
    monkeypatch.setattr(verifier, "_target_facts", Mock(return_value=facts))
    with recovery_record_read_scope() as owner:
        assert verifier.inspect(plan) == facts
        assert owner.retained_entries > 0
        wire = plan.to_wire()
        source_wire = wire["source"]
        assert isinstance(source_wire, dict)
        if fault == "source":
            source_wire["task_sha256"] = "f" * 64
        elif fault == "receipt":
            source_wire["context_capacity_receipt_sha256"] = "f" * 64
        elif fault == "policy":
            wire["denied_paths"] = ["src/private/**"]
        else:
            path = capacity.journal.directory("delivery_multi_retired_snapshot") / "000001.json"
            payload = path.read_bytes()
            path.write_bytes(payload.replace(b"Prepare the repository", b"Changed input content!"))
        changed = RecoveryPlan.create(**wire)
        with pytest.raises(RecoveryRejected):
            verifier.inspect(changed)
    assert owner.retained_entries == owner.retained_bytes == 0
