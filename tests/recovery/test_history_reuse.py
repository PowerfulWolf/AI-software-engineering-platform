"""Recovery retirement and parent ownership share one fresh verified prefix."""

import os
import weakref
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_software_engineer.domain import ProductApprovalDecision, ProductSpecApproval
from ai_software_engineer.manager.delivery_checkpoint import ProjectDeliveryCheckpoint
from ai_software_engineer.multi_directory.models import JointCheckpoint
from ai_software_engineer.multi_directory.retirement import (
    RequirementRetiredError,
    RequirementRetirement,
    RequirementRetirementError,
)
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.recovery.native import (
    _NativeRequirementHistory,
    _parent,
    _require_native_active,
)
from ai_software_engineer.team_workspace import _read_regular
from tests.manager.test_requirement_deletion import _delivery
from tests.manager.test_requirement_retirement import NOW


def _approval(repository_id: str) -> ProductSpecApproval:
    return ProductSpecApproval(
        id="product_approval_" + "a" * 64,
        request_id="request_history_reuse",
        repository_id=repository_id,
        product_spec_id="product_spec_history_reuse",
        product_spec_sha256="a" * 64,
        decision=ProductApprovalDecision.APPROVED,
        operator_id="human",
        rationale="fixture",
        decided_at=NOW,
        approval_sha256="b" * 64,
    )


def test_retirement_observation_reads_each_complete_history_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, blocked, _, _, _ = _delivery(tmp_path, monkeypatch)
    service.retirements.retire(blocked, reason="deleted", retired_at=NOW)
    paths = set(service.journal.directory(blocked.delivery_id).glob("*.json"))
    before = {path: path.read_bytes() for path in paths}
    with patch.object(Path, "read_bytes", autospec=True, side_effect=Path.read_bytes) as reads:
        _require_native_active(service.project, "delivery_unrelated_child")
    counts = Counter(call.args[0] for call in reads.call_args_list if call.args[0] in paths)
    assert counts == Counter({path: 1 for path in paths})
    assert {path: path.read_bytes() for path in paths} == before


def test_parent_observation_reuses_retirement_prefix_and_keeps_bounded_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, blocked, _, _, _ = _delivery(tmp_path, monkeypatch)
    service.retirements.retire(blocked, reason="deleted", retired_at=NOW)
    source = blocked.children[0].checkpoint
    unrelated = ProjectDeliveryCheckpoint.create(
        **{**source.to_wire(), "delivery_id": "delivery_unrelated_child"}
    )
    paths = set(service.journal.directory(blocked.delivery_id).glob("*.json"))
    from ai_software_engineer.recovery import native

    with (
        patch.object(Path, "read_bytes", autospec=True, side_effect=Path.read_bytes) as reads,
        patch.object(native, "_read_regular", wraps=_read_regular) as preflight,
    ):
        assert _parent(service.team, unrelated, _approval(source.repository_id)) == (None, None)
    counts = Counter(call.args[0] for call in reads.call_args_list if call.args[0] in paths)
    assert counts == Counter({path: 1 for path in paths})
    bounded = Counter(call.args[0] for call in preflight.call_args_list if call.args[0] in paths)
    assert bounded == Counter({path: 1 for path in paths})
    assert all(call.args[1] == 8_000_000 for call in preflight.call_args_list)


def test_deleted_parent_membership_in_an_older_checkpoint_is_not_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, blocked, _, _, _ = _delivery(tmp_path, monkeypatch)
    source = blocked.children[0].checkpoint
    latest = service._save(blocked, children=(), next_action="Children retained in history")
    service.retirements.retire(latest, reason="deleted", retired_at=NOW)
    with pytest.raises(RequirementRetiredError):
        _require_native_active(service.project, source.delivery_id)
    with pytest.raises(RequirementRetiredError):
        _parent(service.team, source, _approval(source.repository_id))


def test_each_parent_observation_reads_tail_and_retirement_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, blocked, _, _, _ = _delivery(tmp_path, monkeypatch)
    source = blocked.children[0].checkpoint
    journals: dict[Path, JointJournal] = {}
    assert _parent(service.team, source, _approval(source.repository_id), journals=journals) == (
        None,
        None,
    )
    # A new tail and its tombstone must not inherit the earlier active conclusion.
    latest = service._save(blocked, children=(), next_action="Later observed tail")
    service.retirements.retire(latest, reason="deleted", retired_at=NOW)
    paths = set(service.journal.directory(blocked.delivery_id).glob("*.json"))
    with (
        patch.object(Path, "read_bytes", autospec=True, side_effect=Path.read_bytes) as reads,
        pytest.raises(RequirementRetiredError),
    ):
        _parent(service.team, source, _approval(source.repository_id), journals=journals)
    counts = Counter(call.args[0] for call in reads.call_args_list if call.args[0] in paths)
    assert counts == Counter({path: 1 for path in paths})


@pytest.mark.parametrize("change", ["body", "missing-initial", "symlink", "fifo"])
def test_next_parent_observation_rejects_changed_historical_bytes_and_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    service, blocked, _, _, _ = _delivery(tmp_path, monkeypatch)
    source = blocked.children[0].checkpoint
    unrelated = ProjectDeliveryCheckpoint.create(
        **{**source.to_wire(), "delivery_id": "delivery_unrelated_child"}
    )
    journals: dict[Path, JointJournal] = {}
    assert _parent(service.team, unrelated, _approval(source.repository_id), journals=journals) == (
        None,
        None,
    )
    path = service.journal.directory(blocked.delivery_id) / "000001.json"
    if change == "body":
        before = path.stat()
        payload = path.read_bytes()
        path.write_bytes(payload.replace(b'"K1"', b'"K2"'))
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    elif change == "missing-initial":
        path.unlink()
    elif change == "symlink":
        outside = tmp_path / "outside.json"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
    else:
        path.unlink()
        os.mkfifo(path)
    with pytest.raises(ValueError):
        _parent(service.team, unrelated, _approval(source.repository_id), journals=journals)


def test_shared_journal_still_rereads_bytes_and_isolates_private_return_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, blocked, _, _, _ = _delivery(tmp_path, monkeypatch)
    source = blocked.children[0].checkpoint
    unrelated = ProjectDeliveryCheckpoint.create(
        **{**source.to_wire(), "delivery_id": "delivery_unrelated_child"}
    )
    service.retirements.retire(blocked, reason="deleted", retired_at=NOW)
    paths = set(service.journal.directory(blocked.delivery_id).glob("*.json"))
    journal = JointJournal(service.project.requirements_root, read_only=True)
    journals = {service.project.requirements_root: journal}
    with patch.object(
        JointCheckpoint, "model_validate_json", wraps=JointCheckpoint.model_validate_json
    ) as decode:
        assert _parent(
            service.team, unrelated, _approval(source.repository_id), journals=journals
        ) == (
            None,
            None,
        )
        assert decode.call_count == len(paths)
        returned = journal.current(blocked.delivery_id)
        assert returned is not None
        returned.attempts["coder"] = 99
        with patch.object(Path, "read_bytes", autospec=True, side_effect=Path.read_bytes) as reads:
            assert _parent(
                service.team, unrelated, _approval(source.repository_id), journals=journals
            ) == (None, None)
        assert decode.call_count == len(paths)
    counts = Counter(call.args[0] for call in reads.call_args_list if call.args[0] in paths)
    assert counts == Counter({path: 1 for path in paths})
    assert journal.current(blocked.delivery_id) == blocked


def test_retirement_replacement_prefix_is_verified_once_and_owner_is_not_borrowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.multi_directory.service import CreateRequirement

    service, blocked, _, _, _ = _delivery(tmp_path, monkeypatch)
    source = blocked.children[0].checkpoint
    unrelated = ProjectDeliveryCheckpoint.create(
        **{**source.to_wire(), "delivery_id": "delivery_unrelated_child"}
    )
    replacement = service.create(
        CreateRequirement(name="Replacement", repository_roots=(source.repository_root,))
    ).checkpoint
    service.retirements.retire(
        blocked, reason="replaced", replacement_delivery_id=replacement.delivery_id, retired_at=NOW
    )
    paths = set(service.project.requirements_root.glob("delivery_multi_*/*.json"))
    journals: dict[Path, JointJournal] = {}
    with patch.object(Path, "read_bytes", autospec=True, side_effect=Path.read_bytes) as reads:
        assert _parent(
            service.team, unrelated, _approval(source.repository_id), journals=journals
        ) == (
            None,
            None,
        )
    counts = Counter(call.args[0] for call in reads.call_args_list if call.args[0] in paths)
    assert counts == Counter({path: 1 for path in paths})
    # A fully sealed, schema-valid wrong Project cannot inherit the other prefix's owner.
    directory = service.journal.directory(replacement.delivery_id)
    for path in sorted(directory.glob("*.json")):
        path.unlink()
    foreign = JointCheckpoint.seal(
        {
            **replacement.to_wire(),
            "sequence": 1,
            "previous_checkpoint_sha256": None,
            "project_id": "project_other",
        }
    )
    (directory / "000001.json").write_text(foreign.model_dump_json())
    with pytest.raises(RequirementRetirementError, match="replacement owner mismatch"):
        _parent(service.team, unrelated, _approval(source.repository_id), journals=journals)


@pytest.mark.parametrize("warm", [False, True])
def test_active_parent_copies_only_latest_even_with_many_historical_checkpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, warm: bool
) -> None:
    service, blocked, _, _, _ = _delivery(tmp_path, monkeypatch)
    source = blocked.children[0].checkpoint
    latest = blocked
    for _ in range(32):
        latest = service._save(latest, next_action="Retained complete active history")
    journal = JointJournal(service.project.requirements_root, read_only=True)
    if warm:
        assert journal.current(blocked.delivery_id) == latest
    journals = {service.project.requirements_root: journal}
    paths = set(service.journal.directory(blocked.delivery_id).glob("*.json"))
    assert len(paths) > 32
    with (
        patch.object(
            JointCheckpoint, "model_copy", autospec=True, side_effect=JointCheckpoint.model_copy
        ) as copies,
        patch.object(Path, "read_bytes", autospec=True, side_effect=Path.read_bytes) as reads,
    ):
        assert _parent(
            service.team, source, _approval(source.repository_id), journals=journals
        ) == (
            None,
            None,
        )
    assert copies.call_count == 1
    counts = Counter(call.args[0] for call in reads.call_args_list if call.args[0] in paths)
    assert counts == Counter({path: 1 for path in paths})


@pytest.mark.parametrize("reverse", [False, True])
def test_retired_replacement_chain_reads_each_prefix_once_independent_of_id_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reverse: bool
) -> None:
    service, blocked, _, _, _ = _delivery(tmp_path, monkeypatch)
    source = blocked.children[0].checkpoint
    unrelated = ProjectDeliveryCheckpoint.create(
        **{**source.to_wire(), "delivery_id": "delivery_unrelated_child"}
    )
    other = JointCheckpoint.seal(
        {
            **blocked.to_wire(),
            "delivery_id": "delivery_multi_zzzz",
            "sequence": 1,
            "previous_checkpoint_sha256": None,
            "children": (),
        }
    )
    service.journal.append(other, expected=None)
    first, replacement = (other, blocked) if reverse else (blocked, other)
    service.retirements.retire(
        first, reason="replaced", replacement_delivery_id=replacement.delivery_id, retired_at=NOW
    )
    service.retirements.retire(replacement, reason="deleted", retired_at=NOW)
    paths = set(service.project.requirements_root.glob("delivery_multi_*/*.json"))
    with patch.object(Path, "read_bytes", autospec=True, side_effect=Path.read_bytes) as reads:
        assert _parent(service.team, unrelated, _approval(source.repository_id)) == (None, None)
    counts = Counter(call.args[0] for call in reads.call_args_list if call.args[0] in paths)
    assert counts == Counter({path: 1 for path in paths})


def test_complete_retired_prefix_copies_release_before_the_next_prefix_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, blocked, _, _, _ = _delivery(tmp_path, monkeypatch)
    other = JointCheckpoint.seal(
        {
            **blocked.to_wire(),
            "delivery_id": "delivery_multi_zzzz",
            "sequence": 1,
            "previous_checkpoint_sha256": None,
            "children": (),
        }
    )
    service.journal.append(other, expected=None)
    for parent in (blocked, other):
        service.retirements.retire(parent, reason="deleted", retired_at=NOW)
    journal = JointJournal(service.project.requirements_root, read_only=True)
    snapshot = _NativeRequirementHistory(journal)
    history_reader = JointJournal.history
    nonlatest: list[weakref.ReferenceType[JointCheckpoint]] = []

    def history(reader: JointJournal, delivery_id: str) -> tuple[JointCheckpoint, ...]:
        # Journal keeps its own isolated validation models, not these returned copies.
        assert all(reference() is None for reference in nonlatest)
        result = history_reader(reader, delivery_id)
        nonlatest.extend(weakref.ref(item) for item in result[:-1])
        return result

    with patch.object(JointJournal, "history", autospec=True, side_effect=history):
        _require_native_active(service.project, "delivery_unrelated_child", history=snapshot)
    assert nonlatest and all(reference() is None for reference in nonlatest)
    assert set(snapshot._currents) == {blocked.delivery_id, other.delivery_id}
    assert snapshot.current(blocked.delivery_id) == blocked


@pytest.mark.parametrize("problem", ["missing-replacement", "foreign-replacement", "entry-digest"])
def test_retired_child_match_cannot_hide_later_retirement_corruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    service, blocked, _, _, _ = _delivery(tmp_path, monkeypatch)
    source = blocked.children[0].checkpoint
    service.retirements.retire(blocked, reason="deleted", retired_at=NOW)
    later = JointCheckpoint.seal(
        {
            **blocked.to_wire(),
            "delivery_id": "delivery_multi_zzzz",
            "sequence": 1,
            "previous_checkpoint_sha256": None,
            "children": (),
        }
    )
    service.journal.append(later, expected=None)
    record = service.retirements.retire(
        later,
        reason="replaced",
        replacement_delivery_id="delivery_multi_replacement",
        retired_at=NOW,
    )
    if problem == "foreign-replacement":
        foreign = JointCheckpoint.seal(
            {
                **later.to_wire(),
                "delivery_id": "delivery_multi_replacement",
                "project_id": "project_other",
            }
        )
        service.journal.append(foreign, expected=None)
        expected = "replacement owner mismatch"
    elif problem == "entry-digest":
        entries = tuple(
            item.model_copy(update={"checkpoint_sha256": "0" * 64})
            if item.delivery_id == later.delivery_id
            else item
            for item in record.entries
        )
        changed = RequirementRetirement.seal(**{**record.to_wire(), "entries": entries})
        service.retirements.path.write_text(changed.model_dump_json())
        expected = "retirement does not match immutable journal"
    else:
        expected = "replacement journal is missing"
    with pytest.raises(RequirementRetirementError, match=expected):
        _require_native_active(service.project, source.delivery_id)


def test_early_native_retirement_gate_rejects_fifo_before_journal_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, blocked, _, _, _ = _delivery(tmp_path, monkeypatch)
    service.retirements.retire(blocked, reason="deleted", retired_at=NOW)
    path = service.journal.directory(blocked.delivery_id) / "000001.json"
    path.unlink()
    os.mkfifo(path)
    with (
        patch.object(Path, "read_bytes", autospec=True, side_effect=Path.read_bytes) as reads,
        pytest.raises(ValueError, match="regular file"),
    ):
        _require_native_active(service.project, "delivery_unrelated_child")
    assert all(call.args[0] != path for call in reads.call_args_list)
