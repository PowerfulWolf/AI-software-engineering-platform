"""Native Requirement checks retain only a fully evidenced legacy verifier scope."""

from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.knowledge.gaps import KnowledgeGapRaised
from ai_software_engineer.knowledge.legacy_scope import (
    legacy_delivery_gaps,
    require_delivery_requirement_scope,
)
from ai_software_engineer.knowledge.models import KnowledgeError, KnowledgeRunBinding
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from tests.knowledge.test_delivery_context import _builder
from tests.orchestration.test_runner import _definitions


def _legacy_binding(
    tmp_path: Path, role: AgentRole = AgentRole.QA
) -> tuple[KnowledgeRunBinding, KnowledgeRecordStore]:
    task, _, records, builder = _builder(tmp_path, enabled=False)
    task = task.model_copy(update={"id": "task_continue_scope"})
    with pytest.raises(KnowledgeGapRaised) as original:
        builder.build(task, _definitions()[role], attempt=1)
    return original.value.gap.binding, records


@pytest.mark.parametrize("role", [AgentRole.QA, AgentRole.REVIEWER])
def test_exact_legacy_gap_scope_is_usable_by_a_new_run_of_its_native_parent(
    tmp_path: Path, role: AgentRole
) -> None:
    bound, records = _legacy_binding(tmp_path, role)
    current = bound.model_copy(
        update={"run_id": "run_knowledge_scope_successor", "context_manifest_id": "ctx_" + "a" * 64}
    )
    require_delivery_requirement_scope(current, "delivery_multi_parent", records=records)
    assert (
        legacy_delivery_gaps(
            records,
            task_id=current.task_id or "",
            role=current.role,
            team_id=current.team_id,
            project_id=current.project_id,
            repository_id=current.repository_ids[0],
            source_revision=current.source_revision,
        )[0].binding
        == bound
    )


@pytest.mark.parametrize(
    "changed",
    [
        {"task_id": "task_continue_unproven", "requirement_id": "task_continue_unproven"},
        {"requirement_id": "delivery_multi_unrelated"},
        {"team_id": "team_unrelated"},
        {"project_id": "project_unrelated"},
        {"repository_ids": ("repository_unrelated",)},
        {"source_revision": "f" * 40},
        {"snapshot_sha256": "f" * 64},
        {"role": "coder"},
    ],
)
def test_task_name_cannot_replace_exact_legacy_scope_evidence(
    tmp_path: Path, changed: dict[str, object]
) -> None:
    bound, records = _legacy_binding(tmp_path)
    current = KnowledgeRunBinding.model_validate({**bound.to_wire(), **changed})
    with pytest.raises(KnowledgeError, match="LEGACY_KNOWLEDGE_SCOPE_CHANGED"):
        require_delivery_requirement_scope(current, "delivery_multi_parent", records=records)


@pytest.mark.parametrize("missing", ["gap_key", "snapshot"])
def test_legacy_scope_rechecks_independent_gap_key_and_snapshot(
    tmp_path: Path, missing: str
) -> None:
    bound, records = _legacy_binding(tmp_path)
    if missing == "gap_key":
        original = next(records.root.glob("gaps-*.json"))
        original.rename(records.root / records._name("gaps", "wrong-independent-key"))
    else:
        (records.root / records._name("snapshots", bound.snapshot_sha256)).unlink()
    with pytest.raises(KnowledgeError):
        require_delivery_requirement_scope(bound, "delivery_multi_parent", records=records)


def test_legacy_task_scope_is_not_accepted_as_an_unrelated_single_requirement(
    tmp_path: Path,
) -> None:
    bound, records = _legacy_binding(tmp_path)
    with pytest.raises(KnowledgeError, match="LEGACY_KNOWLEDGE_SCOPE_CHANGED"):
        require_delivery_requirement_scope(bound, "requirement_unrelated", records=records)


def test_exact_current_requirement_needs_no_legacy_exception(tmp_path: Path) -> None:
    bound, records = _legacy_binding(tmp_path)
    current = bound.model_copy(update={"requirement_id": "delivery_multi_parent"})
    require_delivery_requirement_scope(current, "delivery_multi_parent", records=records)
