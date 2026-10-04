"""First context compilation failure must not require an invented Coder identity."""

import json
from datetime import UTC, datetime, timedelta
from itertools import groupby
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ai_software_engineer.context import ContextBudget, FileContextStore
from ai_software_engineer.domain import AgentRole, TaskStatus
from ai_software_engineer.domain.retry_policy import TransientRetryPolicy
from ai_software_engineer.evaluation import CaseStartedEvent, FileEvaluationEventStore
from ai_software_engineer.manager import production_backend
from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    ProjectDeliveryResult,
    ReplyToProduct,
    ResumeProjectDelivery,
    UnifiedProjectEntryService,
)
from ai_software_engineer.manager.dispatch import ContinuationDispatchRecord
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.manager.queue_capacity import production_role_queue
from ai_software_engineer.multi_directory.models import JointDeliveryResult
from ai_software_engineer.multi_directory.service import CreateRequirement
from ai_software_engineer.recovery.models import RecoveryAuthorization, RecoveryScope
from ai_software_engineer.recovery.native import NativeRecoverySourceReader
from ai_software_engineer.recovery.restart_records import PreExecutionRestartPlan
from ai_software_engineer.recovery.resume import JointDeliveryResumeResult
from ai_software_engineer.recovery.verification_native import NativeCandidateSourceReader
from ai_software_engineer.runtime import _default_case_id
from ai_software_engineer.store import MySqlTaskRepository
from ai_software_engineer.team_view.reader import ProductionTeamReader
from ai_software_engineer.web_console.manager import _summarize
from tests.e2e.test_joint_delivery import setup_host
from tests.manager.test_production_backend import _git, _git_output
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.recovery.test_resume import _ResumeFactory


@pytest.mark.mysql
def test_worktree_collision_with_bootstrap_queue_restarts_on_unused_branch(
    tmp_path: Path, mysql_dsn: str
) -> None:
    config, environment, models, projects = setup_host(tmp_path)
    routes = _ResumeFactory(verification_fails=False)
    host = TeamHost(
        config=config,
        environment=environment,
        structured_clients=models,
        delivery_route_adapters=routes,
    )
    entry = host.requirement_entry()
    entry.coordinator = None
    created = entry.create(
        CreateRequirement(
            name="Restart with retained branch",
            repository_roots=tuple(map(str, projects)),
        )
    ).checkpoint
    product = entry.reply(
        ReplyToProduct(
            delivery_id=created.delivery_id,
            expected_checkpoint_sha256=created.checkpoint_sha256,
            message="Update both greetings.",
        )
    ).checkpoint
    branch = "ai/feature/restart-with-retained-branch"
    # Both refs belong to a retained old execution. Never rename or remove them
    # to make the new Coder startup succeed.
    for name in (branch, branch + "-recovery"):
        _git("branch", name, "HEAD", cwd=projects[0])
    retained = tmp_path / "retained-old-coder"
    _git("worktree", "add", str(retained), branch + "-recovery", cwd=projects[0])
    (retained / "unsaved.txt").write_text("preserve this old work")
    blocked = entry.approve(
        ApproveProductSpec(
            delivery_id=product.delivery_id,
            expected_checkpoint_sha256=product.checkpoint_sha256,
            approval_reference="original-product-approval",
        )
    ).checkpoint
    source = blocked.children[0].checkpoint
    assert source.failure_summary == "Delivery stopped safely (WorktreeAlreadyExists)"
    assert source.task_id is not None
    assert not routes.requests
    queue = production_role_queue(mysql_dsn)
    leases = tuple(
        lease
        for lease in queue.list_active_leases(now=datetime.now(UTC))
        if lease.task_id == source.task_id
    )
    assert leases
    with MySqlTaskRepository(mysql_dsn) as repository:
        before = repository.get(source.task_id), repository.list_events(source.task_id)
    # An ACTIVE claim cannot become absence merely because recovery needs it.
    denied = host.resume_delivery(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    assert isinstance(denied, JointDeliveryResumeResult)
    assert denied.continuation.outcome.value == "WAITING_HUMAN"
    assert "role claim" in denied.continuation.next_action
    expired_at = max(lease.expires_at for lease in leases) + timedelta(seconds=1)
    queue.reclaim_expired(now=expired_at, retry_at=expired_at + timedelta(seconds=1))
    proposed = host.resume_delivery(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    assert isinstance(proposed, JointDeliveryResumeResult)
    assert proposed.continuation.outcome.value == "RESTART_APPROVAL_REQUIRED", proposed
    plan = proposed.continuation.restart_plan
    assert plan is not None and plan.restart_kind == "pre_agent_worktree_conflict"
    assert plan.target_branch_name == branch + "-recovery-2"
    completed = host.resume_delivery(
        ResumeProjectDelivery(
            delivery_id=blocked.delivery_id,
            approved_plan_sha256=plan.plan_sha256,
            approval_reference="exact-unused-branch-restart",
        )
    )
    assert isinstance(completed, JointDeliveryResult)
    assert completed.checkpoint.stage.value == "DONE", completed
    with MySqlTaskRepository(mysql_dsn) as repository:
        assert before == (repository.get(source.task_id), repository.list_events(source.task_id))
    assert (retained / "unsaved.txt").read_text() == "preserve this old work"
    assert _git_output("rev-parse", "HEAD", cwd=retained) == before[0].base_ref
    roles = tuple(
        request.role
        for request in routes.requests
        if request.task_id == f"task_continue_{plan.plan_sha256[:32]}"
    )
    assert [role for role, _ in groupby(roles)] == [
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ]


@pytest.mark.mysql
@pytest.mark.parametrize(
    "interruption",
    [
        None,
        "before_attachment",
        "after_attachment",
        "coder_failure",
        "qa_failure",
    ],
)
def test_initial_context_failure_has_exact_restart_and_preserves_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mysql_dsn: str, interruption: str | None
) -> None:
    config, environment, models, projects = setup_host(tmp_path)
    if interruption == "qa_failure":
        config = config.model_copy(
            update={
                "execution_retry_policy": config.execution_retry_policy.model_copy(
                    update={
                        "qa": TransientRetryPolicy(max_transient_failures=1),
                    }
                ),
            }
        )
    routes = _ResumeFactory(
        transient_qa_failures=1 if interruption == "qa_failure" else 0,
        remediation_no_candidate=interruption == "coder_failure",
        verification_fails=False,
    )

    def reopen() -> TeamHost:
        reopened = TeamHost(
            config=config,
            environment=environment,
            structured_clients=models,
            delivery_route_adapters=routes,
        )
        # Isolate deterministic recovery, not unrelated Manager advice.
        reopened.requirement_entry().coordinator = None
        return reopened

    host = reopen()
    entry = host.requirement_entry()
    created = entry.create(
        CreateRequirement(
            name="Restart before first Coder",
            repository_roots=tuple(map(str, projects)),
        )
    ).checkpoint
    product = entry.reply(
        ReplyToProduct(
            delivery_id=created.delivery_id,
            expected_checkpoint_sha256=created.checkpoint_sha256,
            message="Update both greetings.",
        )
    ).checkpoint
    with monkeypatch.context() as patch:
        patch.setattr(
            production_backend,
            "PRODUCTION_DELIVERY_CONTEXT_BUDGET",
            ContextBudget(max_input_tokens=100, reserved_output_tokens=10),
        )
        blocked = entry.approve(
            ApproveProductSpec(
                delivery_id=product.delivery_id,
                expected_checkpoint_sha256=product.checkpoint_sha256,
                approval_reference="original-product-approval",
            )
        ).checkpoint
    assert blocked.stage.value == "BLOCKED"
    source = blocked.children[0].checkpoint
    assert source.task_id is not None and source.candidate_revision is None
    with MySqlTaskRepository(mysql_dsn) as repository:
        before = repository.get(source.task_id), repository.list_events(source.task_id)
    assert before[0].attempts == 1 and before[0].status is TaskStatus.BLOCKED
    assert [(e.from_status, e.to_status) for e in before[1]] == [
        (TaskStatus.NEW, TaskStatus.PLANNING),
        (TaskStatus.PLANNING, TaskStatus.BLOCKED),
    ]
    assert not routes.requests
    proposed = host.resume_delivery(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    assert isinstance(proposed, JointDeliveryResumeResult)
    assert proposed.continuation.outcome.value == "RESTART_APPROVAL_REQUIRED", (
        proposed.continuation.next_action
    )
    plan = proposed.continuation.restart_plan
    assert plan is not None
    schema = json.loads(Path("schemas/pre-execution-restart.schema.json").read_text())
    Draft202012Validator(schema).validate(plan.to_wire())
    public = _summarize(proposed, project_id="project_test")
    assert public.delivery_id == blocked.delivery_id
    assert public.checkpoint_sha256 == blocked.checkpoint_sha256
    assert public.approval is not None and public.approval.kind == "pre_execution_restart"
    assert public.approval.plan_sha256 == plan.plan_sha256
    assert "Coder 尚未启动" in " ".join(public.approval.facts)
    host = reopen()
    for command in (
        ResumeProjectDelivery(delivery_id=blocked.delivery_id),
        ResumeProjectDelivery(
            delivery_id=blocked.delivery_id,
            approved_plan_sha256="0" * 64,
            approval_reference="wrong-plan",
        ),
    ):
        assert host.resume_delivery(command) == proposed
    assert not routes.requests
    if interruption is None:
        # A different budget produces a different plan. The old digest is never a
        # standing permission to start with whatever policy happens to be current.
        with monkeypatch.context() as patch:
            patch.setattr(
                production_backend,
                "PRODUCTION_DELIVERY_CONTEXT_BUDGET",
                ContextBudget(max_input_tokens=127_000, reserved_output_tokens=4000),
            )
            changed = host.resume_delivery(
                ResumeProjectDelivery(
                    delivery_id=blocked.delivery_id,
                    approved_plan_sha256=plan.plan_sha256,
                    approval_reference="stale-context-policy",
                )
            )
            assert isinstance(changed, JointDeliveryResumeResult)
            assert changed.continuation.restart_plan is not None
            assert changed.continuation.restart_plan.plan_sha256 != plan.plan_sha256
            assert not routes.requests
        retained = Path(config.platform_root) / "worktrees" / source.repository_id / source.task_id
        retained.mkdir(parents=True)
        (retained / "user-work.txt").write_text("must not be discarded")
        rejected = host.resume_delivery(
            ResumeProjectDelivery(
                delivery_id=blocked.delivery_id,
                approved_plan_sha256=plan.plan_sha256,
                approval_reference="must-not-override-workspace",
            )
        )
        assert isinstance(rejected, JointDeliveryResumeResult)
        assert rejected.continuation.outcome.value == "WAITING_HUMAN"
        assert "retained workspace" in rejected.continuation.next_action
        assert (retained / "user-work.txt").read_text() == "must not be discarded"
        assert not routes.requests
        (retained / "user-work.txt").unlink()
        retained.rmdir()
    approved = ResumeProjectDelivery(
        delivery_id=blocked.delivery_id,
        approved_plan_sha256=plan.plan_sha256,
        approval_reference="exact-pre-execution-restart-approval",
    )
    if interruption in {"before_attachment", "after_attachment"}:
        original = UnifiedProjectEntryService.begin_pre_execution_restart

        def crash(
            self: UnifiedProjectEntryService,
            restart: PreExecutionRestartPlan,
            dispatch: ContinuationDispatchRecord,
            authorization: RecoveryAuthorization,
            *,
            at: datetime,
        ) -> ProjectDeliveryResult:
            if interruption == "after_attachment":
                original(self, restart, dispatch, authorization, at=at)
            raise RuntimeError("offline crash at restart boundary")

        with monkeypatch.context() as patch:
            patch.setattr(UnifiedProjectEntryService, "begin_pre_execution_restart", crash)
            with pytest.raises(RuntimeError, match="offline crash"):
                host.resume_delivery(approved)
        assert not routes.requests
        host = reopen()
        if interruption == "after_attachment":
            approved = ResumeProjectDelivery(delivery_id=blocked.delivery_id)
    completed = host.resume_delivery(approved)
    assert isinstance(completed, JointDeliveryResult)
    if interruption in {"coder_failure", "qa_failure"}:
        assert completed.checkpoint.stage.value == "BLOCKED"
        child = completed.checkpoint.children[0].checkpoint
        assert child.task_id != source.task_id
        scope = RecoveryScope(
            team_id=config.team_id,
            repository_id=child.repository_id,
            repository_root=child.repository_root,
            delivery_id=child.delivery_id,
        )
        if interruption == "coder_failure":
            failed_coder = NativeRecoverySourceReader(config, environment).discover_failed_coder(
                scope
            )
            assert failed_coder.task.id == child.task_id
        else:
            candidate = NativeCandidateSourceReader(config, environment).inspect(scope)
            assert candidate.runtime.task.id == child.task_id
            assert candidate.inputs.candidate_revision == child.candidate_revision
        with MySqlTaskRepository(mysql_dsn) as repository:
            assert (
                repository.get(source.task_id),
                repository.list_events(source.task_id),
            ) == before
        return
    assert completed.checkpoint.stage.value == "DONE"
    assert completed.checkpoint.children[0].checkpoint.task_id != source.task_id
    assert [r.role for r in routes.requests] == [
        AgentRole.CODER,
        AgentRole.QA,
        AgentRole.REVIEWER,
    ] * 2
    with MySqlTaskRepository(mysql_dsn) as repository:
        assert (repository.get(source.task_id), repository.list_events(source.task_id)) == before
        successor_id = completed.checkpoint.children[0].checkpoint.task_id
        assert successor_id is not None
        successor = repository.get(successor_id)
        assert successor.acceptance_criteria == before[0].acceptance_criteria
        assert successor.constraints == before[0].constraints
        assert successor.retry_policy == before[0].retry_policy
        assert successor.max_attempts == before[0].max_attempts
        assert successor.base_ref == before[0].base_ref
    sidecar = (
        Path(config.platform_root) / "projects/project_test/repositories" / source.repository_id
    )
    context = FileContextStore(sidecar / "contexts").get(routes.requests[0].context_manifest_id)
    starts = [
        event
        for event in FileEvaluationEventStore(sidecar / "evaluations").list_for_case(
            _default_case_id(successor.id)
        )
        if isinstance(event, CaseStartedEvent)
    ]
    assert len(starts) == 1 and starts[0].included is False
    assert all(not section.truncated for section in context.sections)
    assert all(
        any(section.uri == original.uri for section in context.sections)
        for original in plan.context_sources
    )
    replay = reopen().resume_delivery(ResumeProjectDelivery(delivery_id=blocked.delivery_id))
    assert replay.checkpoint == completed.checkpoint
    assert len(routes.requests) == 6
    snapshot = ProductionTeamReader(config, environment).snapshot("project_test")
    current = next(task for task in snapshot.tasks if task.task_id == successor.id)
    assert current.work_kind == "delivery" and current.source_task_id == source.task_id
