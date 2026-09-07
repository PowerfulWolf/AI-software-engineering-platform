"""Offline authorization contracts: immutable facts are not execution authority."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.domain import AgentPermissions, AgentRole, NetworkAccess
from ai_software_engineer.git import WorktreeChangeCapture, WorktreeRef
from ai_software_engineer.recovery import (
    CapturedChanges,
    FileRecoveryStore,
    RecoveryApprovalCommand,
    RecoveryAuthorizationService,
    RecoveryConflict,
    RecoveryPlan,
    RecoveryRejected,
    RecoveryScope,
    RecoverySource,
    VerifiedRecoveryDecision,
)

NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)


def make_plan(project: Path) -> RecoveryPlan:
    capture = WorktreeChangeCapture(
        worktree=WorktreeRef(
            task_id="task_original",
            role=AgentRole.CODER,
            attempt=1,
            path=project.parent / "roles/task_original/coder-attempt-01",
            head_revision="a" * 40,
            branch="ai/task_original/attempt-1",
            detached=False,
        ),
        patch=b"",
        index_diff_sha256="0" * 64,
        file_sha256s=(),
    )
    scope = RecoveryScope(
        company_id="company_ai",
        project_id="project_example",
        delivery_id="delivery_example",
        project_root=str(project),
    )
    return RecoveryPlan.create(
        source=RecoverySource(
            scope=scope,
            task_id="task_original",
            task_revision=3,
            task_sha256="1" * 64,
            checkpoint_sha256="2" * 64,
            dispatch_sha256="3" * 64,
            preparation_sha256="4" * 64,
            product_spec_sha256="5" * 64,
            approval_sha256="6" * 64,
            technical_design_sha256="7" * 64,
            execution_plan_sha256="8" * 64,
            failed_run_id="run_original",
            failed_context_id="ctx_" + "9" * 64,
            base_revision="a" * 40,
        ),
        capture=CapturedChanges.from_capture(capture),
        target_base_revision="b" * 40,
        target_preparation_sha256="c" * 64,
        permissions=AgentPermissions(
            read_paths=("src/**",),
            write_paths=("src/**",),
            commands=(),
            network=NetworkAccess.NONE,
        ),
        denied_paths=(),
        created_at=NOW,
    )


class Facts:
    def __init__(self) -> None:
        self.calls = 0
        self.stale = False

    def validate(self, plan: RecoveryPlan) -> None:
        self.calls += 1
        if self.stale:
            raise RecoveryRejected("source or target facts changed")


class Captures:
    def __init__(self) -> None:
        self.calls = 0
        self.stale = False

    def verify_capture(
        self,
        capture: WorktreeChangeCapture,
        permissions: AgentPermissions,
        *,
        denied_paths: tuple[str, ...] = (),
    ) -> None:
        self.calls += 1
        if self.stale:
            raise RecoveryRejected("capture changed")


class Human:
    def __init__(self) -> None:
        self.calls = 0
        self.approved = True
        self.forged = False
        self.fail = False
        self.drift_after: Facts | None = None

    def verify(self, command: RecoveryApprovalCommand) -> VerifiedRecoveryDecision:
        self.calls += 1
        if self.fail:
            raise RuntimeError("verifier offline")
        if self.drift_after is not None:
            self.drift_after.stale = True
        return VerifiedRecoveryDecision(
            plan_sha256="0" * 64 if self.forged else command.plan_sha256,
            approval_reference=command.approval_reference,
            approved=self.approved,
            operator_id="human_operator",
            rationale="explicit recovery",
            decided_at=NOW,
        )


def setup_service(
    tmp_path: Path,
) -> tuple[
    RecoveryAuthorizationService,
    FileRecoveryStore,
    RecoveryPlan,
    Facts,
    Captures,
    Human,
]:
    project = tmp_path / "project"
    project.mkdir()
    plan = make_plan(project)
    store = FileRecoveryStore.initialize(tmp_path / "recovery", scope=plan.source.scope)
    facts, captures, human = Facts(), Captures(), Human()
    service = RecoveryAuthorizationService(store, facts=facts, captures=captures, human=human)
    return service, store, plan, facts, captures, human


def approval(plan: RecoveryPlan) -> RecoveryApprovalCommand:
    return RecoveryApprovalCommand(
        operation_id="approve_recovery_001",
        plan_sha256=plan.plan_sha256,
        approval_reference="trusted-channel:operator-action-001",
        submitted_at=NOW,
    )


def test_restart_replay_is_not_a_fresh_execution_authorization(tmp_path: Path) -> None:
    service, store, plan, facts, captures, human = setup_service(tmp_path)
    assert service.propose(plan) == plan
    result = service.authorize(approval(plan))
    assert human.calls == 1
    assert service.require_current_authorization(plan.plan_sha256) == plan
    assert plan.new_task_id != plan.source.task_id
    reopened = FileRecoveryStore(tmp_path / "recovery", scope=plan.source.scope)
    resumed = RecoveryAuthorizationService(reopened, facts=facts, captures=captures, human=human)
    facts.stale = captures.stale = human.fail = True
    before = facts.calls, captures.calls, human.calls
    assert resumed.authorize(approval(plan)) == result
    assert (facts.calls, captures.calls, human.calls) == before
    with pytest.raises(RecoveryRejected):
        resumed.require_current_authorization(plan.plan_sha256)
    assert store.get_authorization(plan.plan_sha256) == result


@pytest.mark.parametrize("failure", ["facts", "capture", "forged_human", "during_human", "reject"])
def test_failures_cannot_produce_runnable_authorization(tmp_path: Path, failure: str) -> None:
    service, store, plan, facts, captures, human = setup_service(tmp_path)
    service.propose(plan)
    if failure == "facts":
        facts.stale = True
    elif failure == "capture":
        captures.stale = True
    elif failure == "forged_human":
        human.forged = True
    elif failure == "during_human":
        human.drift_after = facts
    else:
        human.approved = False
    if failure == "reject":
        assert not service.authorize(approval(plan)).decision.approved
    else:
        with pytest.raises(RecoveryRejected):
            service.authorize(approval(plan))
        assert store.find_authorization(plan.plan_sha256) is None
    with pytest.raises(RecoveryRejected):
        service.require_current_authorization(plan.plan_sha256)
    assert list((tmp_path / "project").iterdir()) == []


def test_changed_approval_command_cannot_overwrite_first_decision(tmp_path: Path) -> None:
    service, store, plan, _, _, human = setup_service(tmp_path)
    service.propose(plan)
    command = approval(plan)
    first = service.authorize(command)
    with pytest.raises(RecoveryConflict):
        service.authorize(command.model_copy(update={"approval_reference": "another-action"}))
    assert store.get_authorization(plan.plan_sha256) == first
    assert human.calls == 1


def test_capture_wire_round_trip_preserves_identity(tmp_path: Path) -> None:
    plan = make_plan(tmp_path / "project")
    captured = plan.capture.to_capture()
    assert CapturedChanges.model_validate(plan.capture.to_wire()).to_capture() == captured
    altered = replace(captured, patch=b"untrusted different bytes")
    assert altered.capture_sha256 != plan.capture.capture_sha256
