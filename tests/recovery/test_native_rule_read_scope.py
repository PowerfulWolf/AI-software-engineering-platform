"""Full native epoch bytes are reread, while immutable decode is scope bounded."""

import json
from collections import Counter
from pathlib import Path

import pytest

from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.execution_native_rules import NativeRuleEpoch
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.models import KnowledgeError, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_native_rules import load_native_rule_epoch
from ai_software_engineer.read_record_scope import recovery_record_read_scope


def epoch_store(tmp_path: Path) -> tuple[KnowledgeRecordStore, NativeRuleEpoch]:
    epoch = NativeRuleEpoch.create(
        scope=EngineeringScope(
            team_id="team_fixture",
            project_id="project_fixture",
            repository_id="repository_fixture",
            repository_root=str(tmp_path / "code"),
        ),
        task_id="task_fixture",
        source_revision="a" * 40,
        target_base_ref="b" * 40,
        source_rules=(),
        before_bodies=(),
        bodies=(),
    )
    writer = KnowledgeRecordStore(tmp_path / "records")
    writer.put("baseline-native-rules", epoch.epoch_sha256, epoch)
    return KnowledgeRecordStore(writer.root, read_only=True), epoch


def test_epoch_consumers_read_full_bytes_and_release_shared_decode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, epoch = epoch_store(tmp_path)
    calls: Counter[str] = Counter()
    read, decode = KnowledgeRecordStore._read_payload, KnowledgeRecordStore._decode_payload

    def counted_read(records: KnowledgeRecordStore, name: str) -> bytes | None:
        calls["read"] += 1
        return read(records, name)

    def counted_decode[T: DomainModel](payload: bytes, model: type[T]) -> T:
        calls["decode"] += 1
        return decode(payload, model)

    monkeypatch.setattr(KnowledgeRecordStore, "_read_payload", counted_read)
    monkeypatch.setattr(KnowledgeRecordStore, "_decode_payload", staticmethod(counted_decode))
    with recovery_record_read_scope() as scope:
        first = load_native_rule_epoch(store, epoch.epoch_sha256)
        assert first == epoch
        first.__dict__["task_id"] = "task_changed"
        assert load_native_rule_epoch(store, epoch.epoch_sha256) == epoch
        assert calls == {"read": 2, "decode": 1}
        assert scope.retained_entries == 1
    assert scope.retained_entries == scope.retained_bytes == 0
    assert load_native_rule_epoch(store, epoch.epoch_sha256) == epoch
    assert calls == {"read": 3, "decode": 2}


@pytest.mark.parametrize("change", ["body", "key", "symlink", "missing"])
def test_warm_epoch_never_hides_changed_original_bytes_or_path(
    tmp_path: Path,
    change: str,
) -> None:
    store, epoch = epoch_store(tmp_path)
    path = store.root / store._name("baseline-native-rules", epoch.epoch_sha256)
    with recovery_record_read_scope():
        assert load_native_rule_epoch(store, epoch.epoch_sha256) == epoch
        if change in {"body", "key"}:
            envelope = json.loads(path.read_bytes())
            if change == "body":
                envelope["record"]["task_id"] = "task_changed"
            else:
                envelope["record"]["epoch_sha256"] = "f" * 64
            envelope["sha256"] = digest(envelope["record"])
            path.write_text(json.dumps(envelope))
        elif change == "missing":
            path.unlink()
        else:
            target = tmp_path / "external.json"
            path.rename(target)
            path.symlink_to(target)
        with pytest.raises((ValueError, KnowledgeError)):
            load_native_rule_epoch(store, epoch.epoch_sha256)


def test_zero_budget_keeps_complete_epoch_reads_valid(tmp_path: Path) -> None:
    store, epoch = epoch_store(tmp_path)
    with recovery_record_read_scope() as scope:
        scope.maximum_bytes = 0
        assert load_native_rule_epoch(store, epoch.epoch_sha256) == epoch
        assert load_native_rule_epoch(store, epoch.epoch_sha256) == epoch
        assert scope.retained_entries == 0
