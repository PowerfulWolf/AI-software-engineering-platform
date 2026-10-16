"""Unknown failure history records the exact human decision without claiming a repair."""

from datetime import UTC, datetime

import pytest

from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode, BaselinePurpose
from ai_software_engineer.manager.baseline_models import BaselineOperatorAuthorization
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.team_view.engineering_history import engineering_history
from tests.manager.test_completed_output_checkpoint import CompletedFixture
from tests.manager.test_completed_output_checkpoint import completed as completed_fixture
from tests.manager.test_stopped_failure_retry import service_for

completed = completed_fixture


@pytest.mark.parametrize("completed", ["stopped_failure"], indirect=True)
def test_stopped_failure_history_preserves_unknown_cause_and_independent_continue(
    completed: CompletedFixture,
) -> None:
    fixture = completed
    service = service_for(fixture)
    sidecar = fixture.root / "history-sidecar"
    service.store = FileExecutionBaselineStore(
        sidecar / "state" / "execution-baselines" / fixture.task.id
    )
    plan = service.propose(None, purpose=BaselinePurpose.STOPPED_FAILURE_RETRY)
    authority = BaselineOperatorAuthorization.for_plan(
        plan,
        principal=LocalOperatorPrincipal.trusted_local(),
        reference="接受原失败原因未知和一次普通工作额度",
        submitted_at=datetime.now(UTC),
        continuation_mode=BaselineContinuationMode.PAUSE,
        confirm_stopped_failure_retry=True,
    )
    service.execute(plan.plan_sha256, authority=authority)
    before = fixture.sealed_bytes()
    history = engineering_history(
        sidecar, fixture.task, fixture.collector.scope, "delivery_history"
    )
    assert len(history) == 3
    assert "原失败原因未知" in history[0].summary
    assert "普通工作额度" in history[0].summary
    assert "尚未启动新的开发执行" in history[1].summary
    assert "原因仍未知" in history[2].summary
    assert "单独明确继续" in history[2].summary
    assert all("前提已" not in item.summary for item in history)
    assert fixture.sealed_bytes() == before
