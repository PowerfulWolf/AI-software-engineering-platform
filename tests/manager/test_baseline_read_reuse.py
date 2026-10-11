"""Complete binding reads reuse only their own freshly validated plan."""

import json
from collections import Counter
from pathlib import Path

import pytest

from ai_software_engineer.domain.execution_baseline import (
    BaselineInputMode,
    ExecutionBaselineBinding,
)
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.models import KnowledgeError, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from tests.manager.test_execution_baseline import authorize, setup


def test_complete_binding_read_reads_plan_once_but_context_remains_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = setup(tmp_path)
    plan = fixture.service.propose(fixture.target)
    binding = fixture.service.execute(plan.plan_sha256, authority=authorize(plan))
    store = FileExecutionBaselineStore(fixture.service.store.root, read_only=True)
    expected_context = store.required_context(binding)
    before = {path.name: path.read_bytes() for path in store.root.iterdir()}
    calls: Counter[str] = Counter()
    original = KnowledgeRecordStore._read_name

    def counted[T: DomainModel](
        records: KnowledgeRecordStore, name: str, model: type[T]
    ) -> T | None:
        if records.root == store.root:
            for namespace in ("baseline-plans", "baseline-starts", "baseline-authorities"):
                if name.startswith(namespace + "-"):
                    calls[namespace] += 1
        return original(records, name, model)

    monkeypatch.setattr(KnowledgeRecordStore, "_read_name", counted)
    assert store.bindings_for_task(binding.task_id) == (binding,)
    assert calls == Counter({"baseline-plans": 1, "baseline-starts": 1, "baseline-authorities": 1})
    for expected_reads in (2, 3):
        assert store.required_context(binding) == expected_context
        assert calls["baseline-plans"] == expected_reads
    assert plan.complete_capture.patch in expected_context
    assert before == {path.name: path.read_bytes() for path in store.root.iterdir()}


@pytest.mark.parametrize("change", ["uri", "sha256", "bytes", "task_id", "input_mode"])
def test_standalone_context_still_checks_complete_patch_and_binding_identity(
    tmp_path: Path, change: str
) -> None:
    fixture = setup(tmp_path)
    plan = fixture.service.propose(fixture.target)
    binding = fixture.service.execute(plan.plan_sha256, authority=authorize(plan))
    values = binding.to_wire()
    if change in ("uri", "sha256", "bytes"):
        retained = binding.retained_patch.model_copy(
            update={
                change: {
                    "uri": "file:///wrong-baseline.json#complete_capture.patch",
                    "sha256": "e" * 64,
                    "bytes": binding.retained_patch.bytes + 1,
                }[change]
            }
        )
        values["retained_patch"] = retained.to_wire()
    elif change == "task_id":
        values["task_id"] = "task_other_baseline"
    else:
        values["input_mode"] = BaselineInputMode.CODER_REAPPLY.value
        values["execution_source_revision"] = binding.execution_base_ref
    changed = ExecutionBaselineBinding.create(**values)
    changed.validate_integrity()
    with pytest.raises(ValueError, match="complete retained baseline patch body changed"):
        fixture.service.store.required_context(changed)


def test_binding_read_does_not_supply_a_cached_plan_to_a_later_context(
    tmp_path: Path,
) -> None:
    fixture = setup(tmp_path)
    plan = fixture.service.propose(fixture.target)
    binding = fixture.service.execute(plan.plan_sha256, authority=authorize(plan))
    store = FileExecutionBaselineStore(fixture.service.store.root, read_only=True)
    assert store.bindings_for_task(binding.task_id) == (binding,)
    path = store.root / store.records._name("baseline-plans", plan.plan_sha256)
    envelope = json.loads(path.read_text())
    envelope["record"]["plan_sha256"] = "e" * 64
    envelope["sha256"] = digest(envelope["record"])
    path.write_text(json.dumps(envelope))
    with pytest.raises((ValueError, KnowledgeError)):
        store.required_context(binding)
