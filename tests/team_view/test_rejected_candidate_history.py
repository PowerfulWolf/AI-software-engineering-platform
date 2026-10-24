"""Read-side history describes preserved candidates without claiming acceptance."""

from datetime import UTC, datetime
from pathlib import Path

from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode, BaselinePurpose
from ai_software_engineer.git.baseline import GitExecutionBaselineAdapter
from ai_software_engineer.manager.baseline_models import BaselineOperatorAuthorization
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.execution_baseline import ExecutionBaselineService
from ai_software_engineer.team_view.engineering_history import engineering_history
from tests.manager.test_execution_baseline import Collector
from tests.manager.test_rejected_candidate_baseline_production import (
    RejectedCandidateProductionFixture,
)
from tests.manager.test_rejected_candidate_baseline_production import (
    rejected_candidate_production as rejected_candidate_production,
)


def test_candidate_history_preserves_original_base_and_separates_pause_from_delivery(
    tmp_path: Path,
    rejected_candidate_production: RejectedCandidateProductionFixture,
) -> None:
    fixture = rejected_candidate_production
    sidecar = tmp_path / "history-sidecar"
    store = FileExecutionBaselineStore(sidecar / "state" / "execution-baselines" / fixture.task.id)
    service = ExecutionBaselineService(
        store=store,
        git=GitExecutionBaselineAdapter(fixture.native.git),
        facts=Collector(fixture.facts(), fixture.native.worktree),
    )
    plan = service.propose(None, purpose=BaselinePurpose.REJECTED_CANDIDATE_RESCUE)
    binding = service.execute(
        plan.plan_sha256,
        authority=BaselineOperatorAuthorization.for_plan(
            plan,
            principal=LocalOperatorPrincipal.trusted_local(),
            reference="exact history test candidate report decision",
            submitted_at=datetime.now(UTC),
            continuation_mode=BaselineContinuationMode.PAUSE,
        ),
    )
    before = {path: path.read_bytes() for path in sidecar.rglob("*.json")}
    entries = engineering_history(
        sidecar, fixture.task, fixture.collector.scope, "delivery_fixture"
    )
    assert len(entries) == 3
    accepted = next(entry for entry in entries if entry.details.get("kind") == binding.kind)
    assert "已有代码候选与工程决定已保存" in accepted.summary
    assert "原产品与代码基线保持" in accepted.summary
    assert "需单独明确继续" in accepted.summary
    assert "独立 QA 和 Review" in accepted.summary
    assert (
        accepted.details["rejected_candidate_output_sha256"]
        == binding.rejected_candidate_output_sha256
    )
    assert accepted.details["execution_source_revision"] == binding.execution_source_revision
    assert accepted.details["execution_base_ref"] == fixture.task.base_ref
    assert all(
        "已通过" not in entry.summary and "已完成需求" not in entry.summary for entry in entries
    )
    assert before == {path: path.read_bytes() for path in sidecar.rglob("*.json")}
