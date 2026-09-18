from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.manager.delivery import (
    ApproveProductSpec,
    ReplyToProduct,
    ResumeProjectDelivery,
    UnifiedProjectEntryService,
)
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.multi_directory.errors import RequirementSourceRevisionDrift
from ai_software_engineer.multi_directory.models import (
    Candidate,
    IntegrationRetryProposal,
    JointCheckpoint,
    JointDeliveryResult,
    JointStage,
    digest,
)
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit
from ai_software_engineer.multi_directory.service import (
    CloseRequirement,
    CreateRequirement,
    DeleteRequirement,
    JointDeliveryService,
    RestartRequirement,
    UpdateRequirement,
)
from ai_software_engineer.recovery import FileRecoveryStore, RecoveryPlan, RecoveryScope
from ai_software_engineer.recovery.resume import DeliveryResumeOutcome, DeliveryResumeResult
from ai_software_engineer.recovery.verification_records import (
    AcceptedQaReport,
    CandidateVerificationInputs,
    CandidateVerificationPlan,
)
from ai_software_engineer.team_workspace import TeamWorkspace
from ai_software_engineer.web_console import (
    CloseRequirementIntent,
    ConsoleCommandRejected,
    ContinueDeliveryIntent,
    CreateProjectIntent,
    CreateRequirementIntent,
    DeleteRequirementIntent,
    ManagerConsoleAdapter,
    ProductApprovalIntent,
    ProductReplyIntent,
    RestartRequirementIntent,
    UpdateRequirementIntent,
)
from ai_software_engineer.web_console.manager import TeamConsoleHost
from tests.orchestration.test_runner import _definitions
from tests.recovery.test_authorization import make_plan

DELIVERY_ID = "delivery_multi_" + "a" * 40
PROJECT_ID = "project_web"


def _checkpoint(
    tmp_path: Path,
    *,
    project_manifest_sha256: str,
    sequence: int = 1,
) -> JointCheckpoint:
    return JointCheckpoint.seal(
        {
            "delivery_id": DELIVERY_ID,
            "team_id": "team_test",
            "team_manifest_sha256": "1" * 64,
            "project_id": PROJECT_ID,
            "project_manifest_sha256": project_manifest_sha256,
            "sequence": sequence,
            "previous_checkpoint_sha256": None,
            "stage": JointStage.READY_FOR_DISCUSSION,
            "scope": DirectoryScope(
                units=(
                    DirectoryUnit(
                        id="unit_" + "2" * 16,
                        root=str(tmp_path),
                        selected_paths=(".",),
                        base_revision="3" * 40,
                    ),
                )
            ),
            "title": "Web delivery",
            "submitted_at": datetime(2026, 9, 12, tzinfo=UTC),
            "next_action": "Discuss the requirement.",
        }
    )


class _Entry:
    def __init__(self, checkpoint: JointCheckpoint) -> None:
        self.checkpoint = checkpoint
        self.commands: list[object] = []

    def create(self, command: CreateRequirement) -> JointDeliveryResult:
        self.commands.append(command)
        return JointDeliveryResult(checkpoint=self.checkpoint)

    def update_requirement(self, command: UpdateRequirement) -> JointDeliveryResult:
        self.commands.append(command)
        return JointDeliveryResult(checkpoint=self.checkpoint)

    def delete_requirement(self, command: DeleteRequirement) -> JointDeliveryResult:
        self.commands.append(command)
        return JointDeliveryResult(checkpoint=self.checkpoint)

    def close_requirement(self, command: CloseRequirement) -> JointDeliveryResult:
        self.commands.append(command)
        return JointDeliveryResult(
            checkpoint=self.checkpoint.model_copy(update={"stage": JointStage.CLOSED})
        )

    def restart_requirement(self, command: RestartRequirement) -> JointDeliveryResult:
        self.commands.append(command)
        return JointDeliveryResult(
            checkpoint=self.checkpoint.model_copy(update={"stage": JointStage.BLOCKED})
        )

    def reply(self, command: ReplyToProduct) -> JointDeliveryResult:
        self.commands.append(command)
        return JointDeliveryResult(checkpoint=self.checkpoint)

    def approve(self, command: ApproveProductSpec) -> JointDeliveryResult:
        self.commands.append(command)
        return JointDeliveryResult(checkpoint=self.checkpoint)

    def resume(self, command: ResumeProjectDelivery) -> JointDeliveryResult:
        self.commands.append(command)
        return JointDeliveryResult(checkpoint=self.checkpoint)

    def status(self, delivery_id: str) -> JointDeliveryResult:
        assert delivery_id == self.checkpoint.delivery_id
        return JointDeliveryResult(checkpoint=self.checkpoint)


class _Host:
    def __init__(self, entry: _Entry, project: object) -> None:
        self.entry = entry
        self.project = project
        self.resume_commands: list[ResumeProjectDelivery] = []
        self.resume_result: DeliveryResumeResult | JointDeliveryResult | None = None
        self.recovery_plan: RecoveryPlan | None = None
        self.verification_plan: CandidateVerificationPlan | None = None
        self.opened_plan_paths: list[Path] = []

    def create_project(self, *, name: str, project_id: str | None = None) -> object:
        assert name == "Web Project"
        assert project_id in {None, PROJECT_ID}
        return self.project

    def project_entry(self, project_id: str | None = None) -> UnifiedProjectEntryService:
        assert project_id == PROJECT_ID
        return cast(UnifiedProjectEntryService, self.entry)

    def requirement_entry(self, project_id: str | None = None) -> JointDeliveryService:
        assert project_id == PROJECT_ID
        return cast(JointDeliveryService, self.entry)

    def resume_delivery(
        self, command: ResumeProjectDelivery, *, project_id: str | None = None
    ) -> DeliveryResumeResult | JointDeliveryResult:
        assert project_id == PROJECT_ID
        self.resume_commands.append(command)
        if self.resume_result is not None:
            return self.resume_result
        return JointDeliveryResult(checkpoint=self.entry.checkpoint)

    def recovery_entry(self, project_id: str | None = None) -> object:
        assert project_id == PROJECT_ID
        host = self

        class _RecoveryPlanReader:
            def open_plan(self, path: Path) -> tuple[object, RecoveryPlan]:
                assert host.recovery_plan is not None
                host.opened_plan_paths.append(path)
                return object(), host.recovery_plan

        return _RecoveryPlanReader()

    def verification_entry(self, project_id: str | None = None) -> object:
        assert project_id == PROJECT_ID
        host = self

        class _VerificationPlanReader:
            def open_plan(self, path: Path) -> tuple[object, CandidateVerificationPlan]:
                assert host.verification_plan is not None
                host.opened_plan_paths.append(path)
                return object(), host.verification_plan

        return _VerificationPlanReader()


def _adapter(tmp_path: Path) -> tuple[ManagerConsoleAdapter, _Host, _Entry]:
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test Team")
    project = team.project_registry().register(
        project_id=PROJECT_ID,
        name="Web Project",
    )
    entry = _Entry(
        _checkpoint(
            tmp_path,
            project_manifest_sha256=project.manifest.manifest_sha256,
        )
    )
    host = _Host(entry, project)
    return ManagerConsoleAdapter(cast(TeamConsoleHost, host)), host, entry


def test_create_project_delegates_to_the_team_host(tmp_path: Path) -> None:
    adapter, _, _ = _adapter(tmp_path)

    result = adapter.execute(CreateProjectIntent(name="Web Project", project_id=PROJECT_ID))

    assert result.project_id == PROJECT_ID
    assert result.delivery_id is None
    assert result.stage == "PROJECT_READY"


def test_create_requirement_delegates_and_returns_small_cursor(tmp_path: Path) -> None:
    adapter, _, entry = _adapter(tmp_path)

    result = adapter.execute(
        CreateRequirementIntent(
            project_id=PROJECT_ID,
            name="Web delivery",
            repository_roots=(str(tmp_path),),
        )
    )

    assert isinstance(entry.commands[0], CreateRequirement)
    assert entry.commands[0].repository_roots == (str(tmp_path),)
    assert result.delivery_id == DELIVERY_ID
    assert result.project_id == PROJECT_ID
    assert result.stage == "READY_FOR_DISCUSSION"
    assert result.checkpoint_sha256 == entry.checkpoint.checkpoint_sha256


def test_update_and_delete_requirement_bind_the_displayed_draft(tmp_path: Path) -> None:
    adapter, _, entry = _adapter(tmp_path)
    checkpoint = entry.checkpoint.checkpoint_sha256

    updated = adapter.execute(
        UpdateRequirementIntent(
            project_id=PROJECT_ID,
            delivery_id=DELIVERY_ID,
            expected_checkpoint_sha256=checkpoint,
            name="Renamed delivery",
            repository_roots=(str(tmp_path),),
        )
    )
    deleted = adapter.execute(
        DeleteRequirementIntent(
            project_id=PROJECT_ID,
            delivery_id=DELIVERY_ID,
            expected_checkpoint_sha256=checkpoint,
        )
    )

    update_command = cast(UpdateRequirement, entry.commands[0])
    delete_command = cast(DeleteRequirement, entry.commands[1])
    assert update_command.expected_checkpoint_sha256 == checkpoint
    assert update_command.name == "Renamed delivery"
    assert delete_command.expected_checkpoint_sha256 == checkpoint
    assert updated.delivery_id == DELIVERY_ID
    assert deleted.delivery_id is None
    assert deleted.stage == "REQUIREMENT_DELETED"


def test_close_requirement_binds_the_displayed_blocker(tmp_path: Path) -> None:
    adapter, _, entry = _adapter(tmp_path)
    checkpoint = entry.checkpoint.checkpoint_sha256

    closed = adapter.execute(
        CloseRequirementIntent(
            project_id=PROJECT_ID,
            delivery_id=DELIVERY_ID,
            expected_checkpoint_sha256=checkpoint,
        )
    )

    command = cast(CloseRequirement, entry.commands[0])
    assert command.expected_checkpoint_sha256 == checkpoint
    assert closed.delivery_id == DELIVERY_ID
    assert closed.stage == "CLOSED"


def test_restart_requirement_binds_the_displayed_closed_checkpoint(tmp_path: Path) -> None:
    adapter, _, entry = _adapter(tmp_path)
    checkpoint = entry.checkpoint.checkpoint_sha256

    restarted = adapter.execute(
        RestartRequirementIntent(
            project_id=PROJECT_ID,
            delivery_id=DELIVERY_ID,
            expected_checkpoint_sha256=checkpoint,
        )
    )

    command = cast(RestartRequirement, entry.commands[0])
    assert command.expected_checkpoint_sha256 == checkpoint
    assert restarted.delivery_id == DELIVERY_ID
    assert restarted.stage == "BLOCKED"


def test_reply_and_approval_bind_the_displayed_checkpoint(tmp_path: Path) -> None:
    adapter, _, entry = _adapter(tmp_path)
    checkpoint = entry.checkpoint.checkpoint_sha256

    adapter.execute(
        ProductReplyIntent(
            project_id=PROJECT_ID,
            delivery_id=DELIVERY_ID,
            expected_checkpoint_sha256=checkpoint,
            message="Keep the team sidecar outside the repository.",
        )
    )
    adapter.execute(
        ProductApprovalIntent(
            project_id=PROJECT_ID,
            delivery_id=DELIVERY_ID,
            expected_checkpoint_sha256=checkpoint,
        )
    )

    reply = cast(ReplyToProduct, entry.commands[0])
    approval = cast(ApproveProductSpec, entry.commands[1])
    assert reply.expected_checkpoint_sha256 == checkpoint
    assert approval.expected_checkpoint_sha256 == checkpoint
    assert approval.approval_reference == "web-console-product:" + checkpoint


def test_source_revision_drift_has_a_dedicated_browser_error_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, _, entry = _adapter(tmp_path)

    def reject_reply(command: ReplyToProduct) -> JointDeliveryResult:
        del command
        raise RequirementSourceRevisionDrift(
            "source revision changed after Requirement preparation; create a new Requirement"
        )

    monkeypatch.setattr(entry, "reply", reject_reply)
    with pytest.raises(ConsoleCommandRejected) as captured:
        adapter.execute(
            ProductReplyIntent(
                project_id=PROJECT_ID,
                delivery_id=DELIVERY_ID,
                expected_checkpoint_sha256=entry.checkpoint.checkpoint_sha256,
                message="Continue",
            )
        )

    assert captured.value.code == "SOURCE_REVISION_DRIFT"
    assert "source revision changed" in captured.value.safe_summary


def test_joint_integration_retry_uses_exact_console_approval(tmp_path: Path) -> None:
    adapter, host, entry = _adapter(tmp_path)
    proposal = IntegrationRetryProposal(
        checkpoint_sha256=entry.checkpoint.checkpoint_sha256,
        candidates=(Candidate(unit_id="unit_" + "2" * 16, revision="a" * 40),),
    )
    host.resume_result = JointDeliveryResult(
        checkpoint=entry.checkpoint, integration_retry_proposal=proposal
    )
    intent = ContinueDeliveryIntent(
        project_id=PROJECT_ID,
        delivery_id=DELIVERY_ID,
        expected_checkpoint_sha256=entry.checkpoint.checkpoint_sha256,
    )
    result = adapter.execute(intent)
    assert result.approval is not None
    assert result.approval.kind == "joint_integration"
    assert result.approval.plan_sha256 == digest(proposal)
    assert "1 次" in result.approval.facts[0]
    assert "a" * 40 in result.approval.facts[-1]
    adapter.execute(intent.model_copy(update={"approved_plan_sha256": digest(proposal)}))
    assert host.resume_commands[-1].approved_plan_sha256 == digest(proposal)
    assert host.resume_commands[-1].approval_reference is not None


def test_continue_rejects_a_stale_browser_without_resuming(tmp_path: Path) -> None:
    adapter, host, _ = _adapter(tmp_path)

    with pytest.raises(ConsoleCommandRejected) as captured:
        adapter.execute(
            ContinueDeliveryIntent(
                project_id=PROJECT_ID,
                delivery_id=DELIVERY_ID,
                expected_checkpoint_sha256="f" * 64,
            )
        )

    assert captured.value.code == "STALE_CHECKPOINT"
    assert host.resume_commands == []


def test_continue_hides_the_plan_reference_inside_manager_command(
    tmp_path: Path,
) -> None:
    adapter, host, entry = _adapter(tmp_path)
    checkpoint = entry.checkpoint.checkpoint_sha256

    adapter.execute(
        ContinueDeliveryIntent(
            project_id=PROJECT_ID,
            delivery_id=DELIVERY_ID,
            expected_checkpoint_sha256=checkpoint,
            approved_plan_sha256="4" * 64,
        )
    )

    command = host.resume_commands[0]
    assert command.approved_plan_sha256 == "4" * 64
    assert command.approval_reference == "web-console-plan:" + "4" * 64


def test_continue_sends_an_exact_scope_approval_separately_from_plan_approval(
    tmp_path: Path,
) -> None:
    adapter, host, entry = _adapter(tmp_path)

    adapter.execute(
        ContinueDeliveryIntent(
            project_id=PROJECT_ID,
            delivery_id=DELIVERY_ID,
            expected_checkpoint_sha256=entry.checkpoint.checkpoint_sha256,
            approved_scope_sha256="5" * 64,
        )
    )

    command = host.resume_commands[0]
    assert command.approved_scope_sha256 == "5" * 64
    assert command.approved_plan_sha256 is None
    assert command.approval_reference == "web-console-scope:" + "5" * 64


def test_continue_reads_the_persisted_recovery_envelope_through_the_recovery_entry(
    tmp_path: Path,
) -> None:
    adapter, host, entry = _adapter(tmp_path)
    plan = make_plan(tmp_path / "project")
    store = FileRecoveryStore.initialize(tmp_path / "recovery", scope=plan.source.scope)
    store.put_plan(plan)
    plan_path = tmp_path / "recovery" / f"plan-{plan.plan_sha256}.json"
    child_checkpoint = ProjectDeliveryCheckpoint.create(
        delivery_id="delivery_child",
        sequence=1,
        previous_checkpoint_sha256=None,
        repository_id=plan.source.scope.repository_id,
        repository_root=plan.source.scope.repository_root,
        stage=DeliveryStage.BLOCKED,
        stage_attempts=DeliveryStageAttempts(),
        next_action=DeliveryNextAction.REQUEST_HUMAN,
        failure_code=DeliveryFailureCode.PERMISSION_DENIED,
        failure_summary="Retained Coder work requires recovery approval.",
        checkpointed_at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    host.recovery_plan = plan
    host.resume_result = DeliveryResumeResult(
        outcome=DeliveryResumeOutcome.RECOVERY_APPROVAL_REQUIRED,
        checkpoint=child_checkpoint,
        next_action="Review the recovery plan.",
        recovery_plan_file=str(plan_path),
        recovery_plan_sha256=plan.plan_sha256,
    )

    result = adapter.execute(
        ContinueDeliveryIntent(
            project_id=PROJECT_ID,
            delivery_id=DELIVERY_ID,
            expected_checkpoint_sha256=entry.checkpoint.checkpoint_sha256,
        )
    )

    assert result.approval is not None
    assert result.approval.kind == "coder_recovery"
    assert result.approval.plan_sha256 == plan.plan_sha256
    assert host.opened_plan_paths == [plan_path]


def test_reviewer_only_approval_explains_that_qa_will_be_reused(tmp_path: Path) -> None:
    adapter, host, entry = _adapter(tmp_path)
    child_delivery_id = "delivery_child"
    plan = CandidateVerificationPlan.create(
        scope=RecoveryScope(
            team_id="team_test",
            repository_id="repository_test",
            repository_root=str(tmp_path / "project"),
            delivery_id=child_delivery_id,
        ),
        inputs=CandidateVerificationInputs(
            task_id="task_verification_source",
            task_revision=7,
            task_sha256="1" * 64,
            plan_id="art_plan_source",
            plan_sha256="2" * 64,
            implementation_id="art_impl_source",
            implementation_sha256="3" * 64,
            candidate_revision="4" * 40,
            accepted_qa=AcceptedQaReport(
                artifact_id="art_qa_source",
                artifact_sha256="5" * 64,
            ),
        ),
        native_checkpoint_sha256="6" * 64,
        dispatch_sha256="7" * 64,
        approved_stage_chain_sha256="8" * 64,
        current_policy_sha256="9" * 64,
        definitions=tuple(_definitions().values()),
        created_at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    plan_path = tmp_path / "reviewer-only-plan.json"
    checkpoint = ProjectDeliveryCheckpoint.create(
        delivery_id=child_delivery_id,
        sequence=1,
        previous_checkpoint_sha256=None,
        repository_id=plan.scope.repository_id,
        repository_root=plan.scope.repository_root,
        stage=DeliveryStage.BLOCKED,
        stage_attempts=DeliveryStageAttempts(),
        next_action=DeliveryNextAction.REQUEST_HUMAN,
        failure_code=DeliveryFailureCode.TRANSIENT_PROVIDER_FAILURE,
        failure_summary="Reviewer provider quota was exhausted.",
        checkpointed_at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    host.verification_plan = plan
    host.resume_result = DeliveryResumeResult(
        outcome=DeliveryResumeOutcome.VERIFICATION_APPROVAL_REQUIRED,
        checkpoint=checkpoint,
        next_action="Review the verification plan.",
        verification_plan_file=str(plan_path),
        verification_plan_sha256=plan.plan_sha256,
    )

    result = adapter.execute(
        ContinueDeliveryIntent(
            project_id=PROJECT_ID,
            delivery_id=DELIVERY_ID,
            expected_checkpoint_sha256=entry.checkpoint.checkpoint_sha256,
        )
    )

    assert result.approval is not None
    assert result.approval.title == "复用已通过 QA 并只重新执行 Reviewer"
    assert result.approval.facts == (
        "候选提交 " + "4" * 40,
        "复用已封存 QA PASS art_qa_source",
        "reviewer: local / fake-reviewer",
    )
    assert result.next_action == "请检查并批准仅重新执行 Reviewer 的精确验证计划。"
    assert host.opened_plan_paths == [plan_path]
