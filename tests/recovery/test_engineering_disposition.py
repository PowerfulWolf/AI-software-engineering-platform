"""Terminal recovery explanations are durable typed facts, never invented queue waits."""

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_resolution import EngineeringDispositionRecord
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.engineering_authority import (
    EngineeringAuthorityRejected,
    EngineeringRejectionKind,
)
from ai_software_engineer.recovery.models import RecoveryScope
from ai_software_engineer.recovery.resume import DeliveryResumeController, DeliveryResumeOutcome
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.recovery.verification_native import NativeCandidateSource
from tests.domain.factories import NOW, make_task


@pytest.mark.parametrize(
    ("kind", "classification", "budget"),
    (
        (EngineeringRejectionKind.LEGACY_AUTHORITY, "ENGINEERING_AUTHORIZATION", True),
        (EngineeringRejectionKind.FROZEN_INPUT_CHANGED, "SOURCE_PREPARATION_DRIFT", True),
        (EngineeringRejectionKind.CAPABILITY_UNAVAILABLE, "ENGINEERING_AUTHORIZATION", True),
        (EngineeringRejectionKind.BUDGET_EXHAUSTED, "BUDGET_EXHAUSTED", False),
        (EngineeringRejectionKind.SCOPE_CHANGE, "ENGINEERING_AUTHORIZATION", True),
    ),
)
def test_typed_rejection_seals_disposition_without_reopening_terminal_task(
    tmp_path: Path,
    kind: EngineeringRejectionKind,
    classification: str,
    budget: bool,
) -> None:
    task = make_task().model_copy(
        update={"repository": str(tmp_path / "project"), "status": TaskStatus.BLOCKED}
    )
    scope = RecoveryScope(
        team_id="team_test",
        repository_id="repository_test",
        delivery_id="delivery_test",
        repository_root=task.repository,
    )
    store = FileRecoveryStore.initialize(tmp_path / "recovery", scope=scope)
    values: dict[str, object] = {
        "delivery_id": scope.delivery_id,
        "sequence": 1,
        "repository_id": scope.repository_id,
        "repository_root": task.repository,
        "task_id": task.id,
        "task_revision": 5,
        "task_status": task.status,
        "candidate_revision": "a" * 40,
        "stage": DeliveryStage.BLOCKED,
        "stage_attempts": DeliveryStageAttempts(),
        "next_action": DeliveryNextAction.REQUEST_HUMAN,
        "failure_code": DeliveryFailureCode.RESOURCE_UNAVAILABLE,
        "failure_summary": "工程资源暂不可用",
        "checkpointed_at": NOW,
    }
    for prefix in (
        "product_spec",
        "approval",
        "technical_design",
        "execution_plan",
        "planning_preview",
        "dispatch_commit",
    ):
        values[prefix + "_id"] = prefix + "_test"
        values[prefix + "_sha256"] = "b" * 64
    checkpoint = ProjectDeliveryCheckpoint.create(**values)
    source = cast(
        NativeCandidateSource,
        SimpleNamespace(
            runtime=SimpleNamespace(task=task),
            scope=scope,
            inputs=SimpleNamespace(candidate_revision="a" * 40, task_revision=5),
        ),
    )
    controller = object.__new__(DeliveryResumeController)
    result = controller._engineering_wait(
        checkpoint,
        EngineeringAuthorityRejected(kind, "相同原因文字不参与路由"),
        source=source,
        store=store,
        plan_sha256="c" * 64,
        role=AgentRole.QA,
    )
    assert result.outcome is DeliveryResumeOutcome.WAITING_HUMAN
    assert result.checkpoint == checkpoint and task.status is TaskStatus.BLOCKED
    record = result.engineering_disposition
    assert isinstance(record, EngineeringDispositionRecord)
    assert record.compatibility_mode == "terminal_recovery"
    assert record.disposition.facts.work_item_id is None
    assert "work_item_id" not in record.disposition.facts.to_wire()
    assert record.disposition.facts.classification == classification
    assert record.disposition.facts.budget_available is budget
    assert record.disposition.facts.task_intent_sha256 == task_intent_sha256(task)
    reopened = FileRecoveryStore(store._root, scope=scope)
    assert reopened.get_engineering_disposition(record.record_sha256) == record
    assert reopened.list_engineering_dispositions() == (record,)
