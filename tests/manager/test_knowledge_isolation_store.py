"""Isolation Context and persisted binding readers reopen the exact approved proof."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.execution_baseline import (
    BaselineContinuationMode,
    BaselinePurpose,
    ExecutionBaselineBinding,
)
from ai_software_engineer.manager.baseline_models import BaselineOperatorAuthorization
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.recovery.models import digest
from tests.manager.test_knowledge_isolation import isolation_fixture


@pytest.mark.parametrize("entry", ["authority", "reopen", "context"])
def test_isolation_store_rejects_another_positive_proof_even_with_recomputed_digests(
    tmp_path: Path, entry: str
) -> None:
    fixture, _ = isolation_fixture(tmp_path)
    store = fixture.service.store
    plan = fixture.service.propose(None, purpose=BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="exact current isolation fixture decision",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
        confirm_current_knowledge_execution_isolated=True,
    )
    binding = fixture.service.execute(plan.plan_sha256, authority=authority)
    changed = ExecutionBaselineBinding.create(
        **{
            **binding.model_dump(mode="python", exclude={"binding_sha256"}),
            "knowledge_isolation_sha256": "f" * 64,
        }
    )
    changed.validate_integrity()
    if entry == "authority":
        with pytest.raises(ValueError, match="知识隔离"):
            store._require_authorized_binding(changed, plan, None)
    elif entry == "context":
        with pytest.raises(ValueError, match="知识隔离"):
            store.required_context(changed)
    else:
        path = store.root / store.records._name(
            "baseline-bindings", f"{binding.task_id}:{binding.sequence}"
        )
        envelope = json.loads(path.read_text())
        envelope["record"] = changed.to_wire()
        envelope["sha256"] = digest(changed.to_wire())
        path.write_text(json.dumps(envelope))
        reopened = FileExecutionBaselineStore(store.root, read_only=True)
        with pytest.raises(ValueError, match="知识隔离"):
            reopened.bindings_for_task(binding.task_id)


def test_isolation_context_keeps_unknown_history_and_the_complete_patch(tmp_path: Path) -> None:
    fixture, _ = isolation_fixture(tmp_path)
    plan = fixture.service.propose(None, purpose=BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="exact current isolation fixture decision",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
        confirm_current_knowledge_execution_isolated=True,
    )
    binding = fixture.service.execute(plan.plan_sha256, authority=authority)
    context = fixture.service.store.required_context(binding)
    assert "当前知识执行" in context and "UNKNOWN" in context
    assert "普通工作额度" in context and "独立 QA" in context and "Review" in context
    assert plan.complete_capture.patch in context
