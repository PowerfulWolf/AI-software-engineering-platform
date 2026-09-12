from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.multi_directory.models import (
    JointCheckpoint,
    JointDeliveryResult,
    JointStage,
)
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit
from ai_software_engineer.multi_directory.service import (
    CreateRequirementProject,
    JointDeliveryService,
)
from ai_software_engineer.project_manager.delivery import (
    ApproveProductSpec,
    ReplyToProduct,
    ResumeProjectDelivery,
    UnifiedProjectEntryService,
)
from ai_software_engineer.web_console import (
    ConsoleCommandRejected,
    ContinueDeliveryIntent,
    CreateRequirementProjectIntent,
    ProductApprovalIntent,
    ProductReplyIntent,
    ProjectManagerConsoleAdapter,
)
from ai_software_engineer.web_console.project_manager import OrganizationTeamConsoleHost

DELIVERY_ID = "delivery_multi_" + "a" * 40


def _checkpoint(tmp_path: Path, *, sequence: int = 1) -> JointCheckpoint:
    return JointCheckpoint.seal(
        {
            "delivery_id": DELIVERY_ID,
            "company_id": "company_test",
            "company_manifest_sha256": "1" * 64,
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

    def create(self, command: CreateRequirementProject) -> JointDeliveryResult:
        self.commands.append(command)
        return JointDeliveryResult(checkpoint=self.checkpoint)

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
    def __init__(self, entry: _Entry) -> None:
        self.entry = entry
        self.resume_commands: list[ResumeProjectDelivery] = []

    def project_entry(self) -> UnifiedProjectEntryService:
        return cast(UnifiedProjectEntryService, self.entry)

    def requirement_entry(self) -> JointDeliveryService:
        return cast(JointDeliveryService, self.entry)

    def resume_delivery(self, command: ResumeProjectDelivery) -> JointDeliveryResult:
        self.resume_commands.append(command)
        return JointDeliveryResult(checkpoint=self.entry.checkpoint)


def _adapter(tmp_path: Path) -> tuple[ProjectManagerConsoleAdapter, _Host, _Entry]:
    entry = _Entry(_checkpoint(tmp_path))
    host = _Host(entry)
    return ProjectManagerConsoleAdapter(cast(OrganizationTeamConsoleHost, host)), host, entry


def test_create_requirement_project_delegates_and_returns_small_cursor(tmp_path: Path) -> None:
    adapter, _, entry = _adapter(tmp_path)

    result = adapter.execute(
        CreateRequirementProjectIntent(name="Web delivery", project_roots=(str(tmp_path),))
    )

    assert isinstance(entry.commands[0], CreateRequirementProject)
    assert entry.commands[0].project_roots == (str(tmp_path),)
    assert result.delivery_id == DELIVERY_ID
    assert result.stage == "READY_FOR_DISCUSSION"
    assert result.checkpoint_sha256 == entry.checkpoint.checkpoint_sha256


def test_reply_and_approval_bind_the_displayed_checkpoint(tmp_path: Path) -> None:
    adapter, _, entry = _adapter(tmp_path)
    checkpoint = entry.checkpoint.checkpoint_sha256

    adapter.execute(
        ProductReplyIntent(
            delivery_id=DELIVERY_ID,
            expected_checkpoint_sha256=checkpoint,
            message="Keep the company sidecar outside the repository.",
        )
    )
    adapter.execute(
        ProductApprovalIntent(
            delivery_id=DELIVERY_ID,
            expected_checkpoint_sha256=checkpoint,
        )
    )

    reply = cast(ReplyToProduct, entry.commands[0])
    approval = cast(ApproveProductSpec, entry.commands[1])
    assert reply.expected_checkpoint_sha256 == checkpoint
    assert approval.expected_checkpoint_sha256 == checkpoint
    assert approval.approval_reference == "web-console-product:" + checkpoint


def test_continue_rejects_a_stale_browser_without_resuming(tmp_path: Path) -> None:
    adapter, host, _ = _adapter(tmp_path)

    with pytest.raises(ConsoleCommandRejected) as captured:
        adapter.execute(
            ContinueDeliveryIntent(
                delivery_id=DELIVERY_ID,
                expected_checkpoint_sha256="f" * 64,
            )
        )

    assert captured.value.code == "STALE_CHECKPOINT"
    assert host.resume_commands == []


def test_continue_hides_the_plan_reference_inside_project_manager_command(
    tmp_path: Path,
) -> None:
    adapter, host, entry = _adapter(tmp_path)
    checkpoint = entry.checkpoint.checkpoint_sha256

    adapter.execute(
        ContinueDeliveryIntent(
            delivery_id=DELIVERY_ID,
            expected_checkpoint_sha256=checkpoint,
            approved_plan_sha256="4" * 64,
        )
    )

    command = host.resume_commands[0]
    assert command.approved_plan_sha256 == "4" * 64
    assert command.approval_reference == "web-console-plan:" + "4" * 64
