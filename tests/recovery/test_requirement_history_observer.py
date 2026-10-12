"""Complete original history facts remain fresh under compact decoding reuse."""

import asyncio
import os
import weakref
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_software_engineer.context import FileContextStore
from ai_software_engineer.multi_directory.history_observation import (
    NativeHistoryJournal,
    observe_native_requirement_prefix,
)
from ai_software_engineer.multi_directory.models import ChildDelivery, JointCheckpoint
from ai_software_engineer.multi_directory.retirement import (
    RequirementRetirement,
    RequirementRetirementStore,
)
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.read_record_scope import (
    current_recovery_record_reads,
    finish_recovery_record_reads,
    recovery_record_read_scope,
)
from ai_software_engineer.recovery.native import _NativeRequirementHistory
from tests.context.test_store import _bundle
from tests.e2e.test_delivery_checkpoint import _checkpoint
from tests.team_view.test_joint_history_snapshot import _fixture


def test_complete_bytes_repeated_heads_private_copies_and_cold_next_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, project, journal, _ = _fixture(tmp_path)
    delivery_id = "delivery_multi_retired_snapshot"
    paths = sorted(journal.directory(delivery_id).glob("*.json"))
    counts: Counter[Path] = Counter()
    original_read = Path.read_bytes

    def read(path: Path) -> bytes:
        if path in paths:
            counts[path] += 1
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    original = JointCheckpoint.model_validate_json
    decodes: Counter[int] = Counter()

    def decode(payload: str | bytes | bytearray, **kwargs: object) -> JointCheckpoint:
        checkpoint = original(payload, **kwargs)  # type: ignore[arg-type]
        decodes[checkpoint.sequence] += 1
        return checkpoint

    with patch.object(JointCheckpoint, "model_validate_json", side_effect=decode):
        with recovery_record_read_scope() as owner:
            first = observe_native_requirement_prefix(project.requirements_root, delivery_id)
            assert first.current is not None
            first.current.attempts["coder"] = 99
            second = observe_native_requirement_prefix(project.requirements_root, delivery_id)
            assert second.current is not None and "coder" not in second.current.attempts
            assert first.records == second.records and first.records[0] is not second.records[0]
            assert counts == {path: 2 for path in paths}
            assert decodes == {1: 1, 2: 2}, "head always decodes, exact ancestor only once"
            assert owner.retained_entries == 2
        assert owner.retained_entries == owner.retained_bytes == 0
        with recovery_record_read_scope():
            observe_native_requirement_prefix(project.requirements_root, delivery_id)
        assert decodes == {1: 2, 2: 3}


@pytest.mark.parametrize("fault", ["body", "first", "middle", "symlink", "resealed", "filename"])
def test_warm_complete_prefix_rejects_changed_ancestor_and_path(tmp_path: Path, fault: str) -> None:
    _, project, journal, _ = _fixture(tmp_path)
    delivery_id = "delivery_multi_retired_snapshot"
    root = journal.directory(delivery_id)
    head = journal.current(delivery_id)
    assert head is not None
    appended = JointCheckpoint.seal(
        {
            **head.to_wire(),
            "sequence": 3,
            "previous_checkpoint_sha256": head.checkpoint_sha256,
            "next_action": "Third complete record",
        }
    )
    journal.append(appended, expected=head.checkpoint_sha256)
    with recovery_record_read_scope():
        observe_native_requirement_prefix(project.requirements_root, delivery_id)
        path = root / "000001.json"
        before = path.stat()
        if fault == "body":
            payload = path.read_bytes()
            changed = payload.replace(b"Prepare the repository", b"Changed input content!")
            assert len(payload) == len(changed) and payload != changed
            path.write_bytes(changed)
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        elif fault == "first":
            path.unlink()
        elif fault == "middle":
            (root / "000002.json").unlink()
        elif fault == "symlink":
            alternative = tmp_path / "elsewhere.json"
            path.rename(alternative)
            path.symlink_to(alternative)
        elif fault == "filename":
            path.rename(root / "wrong.json")
        else:
            first = JointCheckpoint.model_validate_json(path.read_bytes())
            changed_first = JointCheckpoint.seal(
                {**first.to_wire(), "next_action": "Changed prior"}
            )
            path.write_text(changed_first.model_dump_json())
        with pytest.raises(ValueError):
            observe_native_requirement_prefix(project.requirements_root, delivery_id)


def test_valid_append_and_original_retirement_fallback_agree_without_full_cache(
    tmp_path: Path,
) -> None:
    _, project, journal, current = _fixture(tmp_path)
    compact = NativeHistoryJournal(project.requirements_root, read_only=True)
    ordinary = JointJournal(project.requirements_root, read_only=True)
    retirements = RequirementRetirementStore(
        project.requirements_root,
        team_id=project.team.manifest.team_id,
        team_manifest_sha256=project.team.manifest.manifest_sha256,
        project_id=project.manifest.project_id,
        project_manifest_sha256=project.manifest.manifest_sha256,
        read_only=True,
    )
    with recovery_record_read_scope():
        retirements.require_native_active("delivery_unrelated", _NativeRequirementHistory(compact))
        # Ordinary JointJournal is the original full-history fallback port.
        retirements.require_native_active("delivery_unrelated", ordinary)
        assert compact._verified == {}, "native bridge never fills the complete typed Journal cache"
        prefix = compact.native_prefix(current.delivery_id)
        assert prefix.current == current
        appended = JointCheckpoint.seal(
            {
                **current.to_wire(),
                "sequence": 2,
                "previous_checkpoint_sha256": current.checkpoint_sha256,
                "next_action": "New valid tail",
            }
        )
        journal.append(appended, expected=current.checkpoint_sha256)
        assert compact.native_prefix(current.delivery_id).current == appended
        assert compact._verified == {}


@pytest.mark.parametrize("maximum", [0, 1, 512])
def test_context_and_journal_share_entry_and_byte_budgets_with_complete_fallback(
    tmp_path: Path, maximum: int
) -> None:
    _, project, journal, _ = _fixture(tmp_path)
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    bundle = _bundle(bundle_root)
    contexts = FileContextStore(tmp_path / "contexts")
    contexts.put(bundle)
    readonly = FileContextStore(tmp_path / "contexts", read_only=True)
    with recovery_record_read_scope() as owner:
        owner.maximum_entries = maximum
        readonly.get(bundle.context_id)
        first_entries = owner.retained_entries
        first_bytes = owner.retained_bytes
        owner.maximum_bytes = first_bytes + 1
        result = observe_native_requirement_prefix(
            project.requirements_root, "delivery_multi_retired_snapshot"
        )
        assert result.current == journal.current("delivery_multi_retired_snapshot")
        assert len(result.records) == 2
        assert owner.retained_entries == first_entries
        assert owner.retained_bytes == first_bytes
        assert owner.retained_entries <= maximum and owner.retained_bytes <= owner.maximum_bytes
        assert readonly.get(bundle.context_id) == bundle


def test_journal_first_receipts_leave_no_separate_context_entry_pool(tmp_path: Path) -> None:
    _, project, journal, _ = _fixture(tmp_path)
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    bundle = _bundle(bundle_root)
    contexts = FileContextStore(tmp_path / "contexts")
    contexts.put(bundle)
    with recovery_record_read_scope() as owner:
        owner.maximum_entries = 2
        prefix = observe_native_requirement_prefix(
            project.requirements_root, "delivery_multi_retired_snapshot"
        )
        assert prefix.current == journal.current("delivery_multi_retired_snapshot")
        assert owner.retained_entries == 2
        before = owner.retained_bytes
        assert (
            FileContextStore(tmp_path / "contexts", read_only=True).get(bundle.context_id) == bundle
        )
        assert owner.retained_entries == 2 and owner.retained_bytes == before


def test_default_512_entry_limit_is_aggregate_with_context_and_multiple_roots(
    tmp_path: Path,
) -> None:
    _, project, _, current = _fixture(tmp_path)
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    bundle = _bundle(bundle_root)
    contexts = FileContextStore(tmp_path / "contexts")
    contexts.put(bundle)
    with recovery_record_read_scope() as owner:
        FileContextStore(tmp_path / "contexts", read_only=True).get(bundle.context_id)
        assert owner.retained_entries == 1
        # Each root is independent, but all fixed receipts consume the same owner.
        for index in range(512):
            root = project.requirements_root if index % 2 else tmp_path / "other-history"
            cp = JointCheckpoint.seal(
                {**current.to_wire(), "delivery_id": f"delivery_multi_quota_{index}"}
            )
            directory = root / cp.delivery_id
            directory.mkdir(parents=True)
            (directory / "000001.json").write_text(cp.model_dump_json())
            assert observe_native_requirement_prefix(root, cp.delivery_id).current == cp
        assert owner.retained_entries == 512
        assert owner.retained_bytes <= 32 * 1024 * 1024
    assert owner.retained_entries == owner.retained_bytes == 0


@pytest.mark.parametrize(
    "fault", ("valid", "retired", "hash", "owner", "replacement", "foreign", "ancestor")
)
def test_compact_and_original_retirement_ports_have_same_complete_history_decisions(
    tmp_path: Path, fault: str
) -> None:
    _, project, journal, current = _fixture(tmp_path)
    native = _checkpoint(Path(current.scope.units[0].root), delivery_id="delivery_hidden_child")
    first = JointCheckpoint.seal(
        {
            **current.to_wire(),
            "delivery_id": "delivery_multi_retired_with_child",
            "children": (ChildDelivery(unit_id=current.scope.units[0].id, checkpoint=native),),
        }
    )
    last = JointCheckpoint.seal(
        {
            **first.to_wire(),
            "sequence": 2,
            "previous_checkpoint_sha256": first.checkpoint_sha256,
            "children": (),
        }
    )
    journal.append(first, expected=None)
    journal.append(last, expected=first.checkpoint_sha256)
    retirements = RequirementRetirementStore(
        project.requirements_root,
        team_id=project.team.manifest.team_id,
        team_manifest_sha256=project.team.manifest.manifest_sha256,
        project_id=project.manifest.project_id,
        project_manifest_sha256=project.manifest.manifest_sha256,
    )
    retirements.retire(last, reason="deleted", retired_at=current.submitted_at)
    compact = _NativeRequirementHistory(
        NativeHistoryJournal(project.requirements_root, read_only=True)
    )
    ordinary = JointJournal(project.requirements_root, read_only=True)
    with recovery_record_read_scope():
        retirements.require_native_active("delivery_unrelated", compact)
        retirements.require_native_active("delivery_unrelated", ordinary)
        record = retirements.retirement()
        wire: dict[str, object] = {**record.to_wire()}
        if fault == "hash":
            wire["entries"] = (
                record.entries[0].model_copy(update={"checkpoint_sha256": "f" * 64}),
                *record.entries[1:],
            )
        elif fault == "owner":
            wire["project_id"] = "project_other"
        elif fault == "replacement":
            replacement = project.requirements_root / current.delivery_id / "000001.json"
            replacement.unlink()
        elif fault == "foreign":
            changed_replacement = JointCheckpoint.seal(
                {**current.to_wire(), "project_id": "project_other"}
            )
            (project.requirements_root / current.delivery_id / "000001.json").write_text(
                changed_replacement.model_dump_json()
            )
        elif fault == "ancestor":
            path = journal.directory(first.delivery_id) / "000001.json"
            path.write_bytes(path.read_bytes().replace(b"Current draft", b"Changed draft"))
        if fault in {"hash", "owner"}:
            retirements.path.write_text(RequirementRetirement.seal(**wire).model_dump_json())
        target = (
            native.delivery_id
            if fault in {"retired", "replacement", "foreign"}
            else "delivery_unrelated"
        )

        def decision(
            reader: JointJournal | _NativeRequirementHistory,
        ) -> tuple[type[Exception], str] | None:
            try:
                retirements.require_native_active(target, reader)
            except Exception as error:
                return type(error), str(error)
            return None

        # New observation-local adapters must reobserve bytes, even within an owner.
        actual = decision(_NativeRequirementHistory(compact.journal))
        expected = decision(ordinary)
        assert actual == expected
        assert (actual is None) == (fault == "valid")


def test_owned_receipts_release_on_retained_exception_and_before_callback(tmp_path: Path) -> None:
    _, project, _, _ = _fixture(tmp_path)
    saved = []
    with pytest.raises(ValueError) as rejected, recovery_record_read_scope() as owner:
        observe_native_requirement_prefix(
            project.requirements_root, "delivery_multi_retired_snapshot"
        )
        saved = [weakref.ref(record.value) for record in owner._records.values()]
        (project.requirements_root / "delivery_multi_retired_snapshot/000001.json").unlink()
        observe_native_requirement_prefix(
            project.requirements_root, "delivery_multi_retired_snapshot"
        )
    assert rejected.value.__traceback__ is not None
    assert saved and all(reference() is None for reference in saved)
    assert owner.retained_entries == owner.retained_bytes == 0
    with recovery_record_read_scope() as fresh:
        observe_native_requirement_prefix(
            project.requirements_root, "delivery_multi_current_snapshot"
        )
        finish_recovery_record_reads()
        assert current_recovery_record_reads() is None
        assert fresh.retained_entries == fresh.retained_bytes == 0


def test_copied_thread_and_async_child_do_not_share_or_close_owner(tmp_path: Path) -> None:
    _, project, _, _ = _fixture(tmp_path)

    def read() -> None:
        observe_native_requirement_prefix(
            project.requirements_root, "delivery_multi_retired_snapshot"
        )

    with recovery_record_read_scope() as owner:
        read()
        copied = copy_context()

        def child() -> None:
            assert current_recovery_record_reads() is None
            finish_recovery_record_reads()
            with recovery_record_read_scope() as independent:
                read()
                assert independent is not owner and independent.retained_entries == 2
            assert independent.retained_entries == 0

        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(copied.run, child).result()
        assert owner.retained_entries == 2 and not owner.closed

    async def parent() -> None:
        with recovery_record_read_scope() as owner:
            read()

            async def child() -> None:
                assert current_recovery_record_reads() is None
                finish_recovery_record_reads()
                with recovery_record_read_scope() as independent:
                    read()
                    assert independent is not owner and independent.retained_entries == 2

            await asyncio.create_task(child())
            assert owner.retained_entries == 2 and not owner.closed

    asyncio.run(parent())
