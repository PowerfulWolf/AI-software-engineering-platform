"""Product status follows typed execution facts without assigning engineering to product."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.domain.enums import AgentRole, WorkItemStatus
from ai_software_engineer.knowledge.gaps import GapRoute, KnowledgeGapService
from ai_software_engineer.knowledge.models import KnowledgeSearchRequest
from ai_software_engineer.knowledge.retrieval import MarkdownKnowledgeRetrieval
from ai_software_engineer.knowledge.skills import KnowledgeSkillRegistry
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.knowledge.views import KnowledgeGapView
from ai_software_engineer.team_view.models import RequestView, RoleQueueView, ScopeView, TaskView
from ai_software_engineer.team_view.reader import (
    _knowledge_route,
    _request_with_current_work,
    _with_execution_state,
)
from tests.knowledge.test_retrieval_contract import binding, snapshot


def _task(*, status: WorkItemStatus, **queue_changes: object) -> TaskView:
    now = datetime.now(UTC)
    step = RoleQueueView(
        work_item_id="work_product_execution",
        role=AgentRole.CODER,
        attempt=1,
        status=status,
    ).model_copy(update=queue_changes)
    return TaskView(
        id="delivery_product_execution",
        project_id="project_test",
        request_id="delivery_multi_product_execution",
        task_id="task_product_execution",
        title="Delivery",
        scope=ScopeView(root="/workspace/repository", selected_paths=(".",)),
        status="IMPLEMENTING",
        checkpoint_stage="DELIVERING",
        terminal=False,
        last_activity=now,
        next_action="Old generic recovery advice",
        role_queue=(step,),
    )


@pytest.mark.parametrize(
    ("status", "state", "reason_code", "reason"),
    [
        ("VERIFIED", "COMPLETED", "CANDIDATE_VERIFIED", "候选验证已通过"),
        (
            "VERIFICATION_SUPERSEDED",
            "SUPERSEDED",
            "VERIFICATION_SUPERSEDED",
            "已由后续计划替代",
        ),
    ],
)
def test_terminal_candidate_verification_is_not_an_engineering_failure(
    status: str, state: str, reason_code: str, reason: str
) -> None:
    task = _task(status=WorkItemStatus.CLOSED).model_copy(
        update={"status": status, "terminal": True, "work_kind": "candidate_verification"}
    )
    projected = _with_execution_state(task)
    assert projected.status == status
    assert projected.execution is not None
    assert projected.execution.state == state
    assert projected.execution.reason_code == reason_code
    assert projected.execution.responsibility == "team"
    assert reason in projected.execution.reason
    assert "恢复" not in projected.execution.next_action
    assert not projected.execution.action_required


def test_interrupted_candidate_verification_still_reports_engineering_stop() -> None:
    task = _task(status=WorkItemStatus.CLOSED).model_copy(
        update={
            "status": "VERIFICATION_INTERRUPTED",
            "terminal": True,
            "work_kind": "candidate_verification",
        }
    )
    projected = _with_execution_state(task)
    assert projected.execution is not None
    assert projected.execution.state == "STOPPED"
    assert projected.execution.responsibility == "engineering"


@pytest.mark.parametrize(
    "status", [WorkItemStatus.WAITING_HUMAN, WorkItemStatus.WAITING_DEPENDENCY]
)
def test_engineering_wait_does_not_request_product_approval(status: WorkItemStatus) -> None:
    task = _task(status=status, wait_reason="Please approve this technical hash")
    projected = _with_execution_state(task)
    assert projected.status == "IMPLEMENTING"
    assert projected.execution is not None
    assert projected.execution.state == "WAITING"
    assert projected.execution.responsibility == "engineering"
    assert not projected.execution.action_required
    assert "工程" in projected.next_action
    assert "批准" not in projected.next_action
    assert "继续交付" not in projected.next_action


def test_retry_uses_real_available_time_and_is_not_terminal_blocker() -> None:
    available_at = datetime.now(UTC) + timedelta(seconds=45)
    task = _task(
        status=WorkItemStatus.RETRY_SCHEDULED,
        available_at=available_at,
        wait_reason="provider_transient",
    )
    projected = _with_execution_state(task)
    assert projected.execution is not None
    assert projected.execution.state == "RETRY_SCHEDULED"
    assert projected.execution.responsibility == "team"
    assert projected.execution.available_at == available_at
    assert projected.blocker is None
    assert not projected.execution.action_required
    assert task.next_action == "Old generic recovery advice"


def test_expired_claim_does_not_prove_process_stopped() -> None:
    projected = _with_execution_state(
        _task(status=WorkItemStatus.RUNNING, lease_liveness="LEASE_EXPIRED")
    )
    assert projected.execution is not None
    assert projected.execution.state == "UNKNOWN"
    assert projected.execution.responsibility == "engineering"
    assert "已中断" not in projected.execution.reason
    assert "确认" in projected.execution.reason
    assert "租约" not in projected.next_action


def test_running_requires_current_role_and_valid_execution_claim() -> None:
    task = _task(status=WorkItemStatus.RUNNING, lease_liveness="LEASE_VALID")
    projected = _with_execution_state(task)
    assert projected.execution is not None
    assert projected.execution.state == "RUNNING"
    assert projected.execution.responsibility == "team"
    assert "租约" not in projected.next_action
    for changes in ({"lease_liveness": "UNKNOWN"}, {"role": AgentRole.QA}):
        changed = task.model_copy(
            update={"role_queue": (task.role_queue[0].model_copy(update=changes),)}
        )
        execution = _with_execution_state(changed).execution
        assert execution is not None and execution.state == "UNKNOWN"


def test_requirement_keeps_phase_separate_from_execution_wait() -> None:
    task = _task(status=WorkItemStatus.WAITING_HUMAN, wait_reason="engineering")
    request = RequestView(
        id=task.request_id,
        project_id=task.project_id,
        title=task.title,
        stage="DELIVERING",
        scopes=(task.scope,),
        next_action="Old generic recovery advice",
        checkpoint_sha256="a" * 64,
    )
    projected = _request_with_current_work(request, [task])
    assert projected.stage == "DELIVERING"
    assert projected.execution is not None
    assert projected.execution.state == "WAITING"
    assert projected.execution.responsibility == "engineering"
    assert projected.coordination is None


@pytest.mark.parametrize("stage", ["WAITING_PRODUCT_REPLY", "WAITING_PRODUCT_APPROVAL"])
def test_only_explicit_product_decision_assigns_product_action(stage: str) -> None:
    task = _task(status=WorkItemStatus.READY)
    request = RequestView(
        id=task.request_id,
        project_id=task.project_id,
        title=task.title,
        stage=stage,
        scopes=(task.scope,),
        next_action="Please confirm the business decision",
        checkpoint_sha256="a" * 64,
    )
    projected = _request_with_current_work(request, [])
    assert projected.execution is not None
    assert projected.execution.responsibility == "product"
    assert projected.execution.action_required


@pytest.mark.parametrize(
    ("route", "responsibility"),
    [
        ("USER", "product"),
        ("ACCEPT_RISK", "product"),
        ("PRODUCT", "team"),
        ("DESIGNER", "team"),
        ("RESEARCH", "team"),
        ("WAITING_HUMAN", "engineering"),
    ],
)
def test_knowledge_responsibility_comes_from_sealed_route(
    tmp_path: Path,
    route: GapRoute,
    responsibility: str,
) -> None:
    records = KnowledgeRecordStore(tmp_path)
    frozen = snapshot()
    bound = binding(frozen)
    skills = KnowledgeSkillRegistry(bound, frozen, MarkdownKnowledgeRetrieval(), records)
    skills.search_knowledge(
        KnowledgeSearchRequest(
            operation_id="search_route", binding=bound, query="expected behavior"
        )
    )
    gaps = KnowledgeGapService(records)
    gap = gaps.report(
        manifest=skills.manifest(),
        question="Which behavior is expected?",
        required_decision="Confirm facts",
        reason="MISSING",
        severity="BLOCKING",
        impact="Execution paused",
        risk="medium",
    )
    assert _knowledge_route(records, gap) is None
    gaps.route(gap.gap_id, route, "Typed route")
    readonly = KnowledgeRecordStore(tmp_path, read_only=True)
    recorded = _knowledge_route(readonly, gap)
    assert recorded == route
    task = _task(status=WorkItemStatus.WAITING_HUMAN)
    request = RequestView(
        id=task.request_id,
        project_id=task.project_id,
        title=task.title,
        stage="WAITING_HUMAN",
        scopes=(task.scope,),
        next_action="Confirm the question",
        checkpoint_sha256="a" * 64,
        knowledge_gap=KnowledgeGapView(gap=gap, is_current=True),
        knowledge_route=recorded,
    )
    projected = _request_with_current_work(request, [task])
    assert projected.execution is not None
    assert projected.execution.responsibility == responsibility
    assert projected.execution.action_required == (responsibility == "product")
