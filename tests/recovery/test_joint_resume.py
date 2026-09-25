"""Joint continuation must retain the native approval and the parent cursor."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_software_engineer.manager.delivery import ResumeProjectDelivery
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.multi_directory.models import (
    ChildDelivery,
    JointCheckpoint,
    JointDeliveryResult,
    JointStage,
)
from ai_software_engineer.multi_directory.production import ProductionJointBackend
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit
from ai_software_engineer.recovery.resume import (
    DeliveryResumeOutcome,
    DeliveryResumeResult,
    JointDeliveryResumeResult,
)
from ai_software_engineer.web_console.manager import _summarize


@pytest.mark.parametrize("gate", ["verification", "recovery", "scope"])
def test_joint_resume_preserves_child_approval_after_parent_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gate: str
) -> None:
    now = datetime(2026, 9, 25, tzinfo=UTC)
    child = ProjectDeliveryCheckpoint.create(
        delivery_id="delivery_child",
        sequence=1,
        previous_checkpoint_sha256=None,
        repository_id="repository_test",
        repository_root=str(tmp_path),
        stage=DeliveryStage.BLOCKED,
        stage_attempts=DeliveryStageAttempts(),
        next_action=DeliveryNextAction.REQUEST_HUMAN,
        failure_code=DeliveryFailureCode.VERIFICATION_INCONCLUSIVE,
        failure_summary="Independent verification requires approval.",
        checkpointed_at=now,
    )
    parent = JointCheckpoint.seal(
        {
            "delivery_id": "delivery_multi_joint_approval",
            "team_id": "team_test",
            "team_manifest_sha256": "1" * 64,
            "project_id": "project_test",
            "project_manifest_sha256": "2" * 64,
            "sequence": 1,
            "stage": JointStage.BLOCKED,
            "scope": DirectoryScope(
                units=(
                    DirectoryUnit(
                        id="unit_1111111111111111",
                        root=str(tmp_path),
                        selected_paths=(".",),
                        base_revision="3" * 40,
                    ),
                )
            ),
            "children": (ChildDelivery(unit_id="unit_1111111111111111", checkpoint=child),),
            "title": "Retained candidate",
            "submitted_at": now,
            "next_action": "Continue the blocked child.",
        }
    )
    successor = JointCheckpoint.seal(
        {**parent.to_wire(), "sequence": 2, "previous_checkpoint_sha256": parent.checkpoint_sha256}
    )
    fields: dict[str, object]
    if gate == "verification":
        fields = {
            "outcome": DeliveryResumeOutcome.VERIFICATION_APPROVAL_REQUIRED,
            "verification_plan_sha256": "4" * 64,
            "verification_plan_file": str(tmp_path / "verification.json"),
        }
    elif gate == "recovery":
        fields = {
            "outcome": DeliveryResumeOutcome.RECOVERY_APPROVAL_REQUIRED,
            "recovery_plan_sha256": "5" * 64,
            "recovery_plan_file": str(tmp_path / "recovery.json"),
        }
    else:
        fields = {
            "outcome": DeliveryResumeOutcome.SCOPE_APPROVAL_REQUIRED,
            "scope_supplement_sha256": "6" * 64,
            "scope_supplement_paths": ("src/new.py",),
        }
    pending = DeliveryResumeResult.model_validate(
        {**fields, "checkpoint": child, "next_action": "Approve the exact child plan."}
    )
    calls: list[str] = []

    def resume_parent(command: ResumeProjectDelivery) -> JointDeliveryResult:
        calls.append("parent")
        return JointDeliveryResult(checkpoint=successor)

    def resume_child(command: ResumeProjectDelivery) -> DeliveryResumeResult:
        calls.append("child")
        assert command.delivery_id == child.delivery_id
        return pending

    backend = object.__new__(ProductionJointBackend)
    monkeypatch.setattr(backend, "delivery_runtime", lambda cp, unit_id: (None, None))
    requirements = SimpleNamespace(
        backend=backend,
        status=lambda delivery_id: SimpleNamespace(checkpoint=parent),
        resume=resume_parent,
    )
    runtime = SimpleNamespace(requirements=requirements)
    controller = SimpleNamespace(resume=resume_child)
    host = object.__new__(TeamHost)
    monkeypatch.setattr(
        host, "_resolve_project_id", lambda project_id, delivery_id=None: "project_test"
    )
    monkeypatch.setattr(host, "_runtime", lambda project_id: runtime)
    monkeypatch.setattr(host, "_resume_controller", lambda runtime, **kwargs: controller)

    result = host.resume_delivery(ResumeProjectDelivery(delivery_id=parent.delivery_id))

    assert result.checkpoint == successor
    assert calls == ["child", "parent"]
    assert isinstance(result, JointDeliveryResumeResult)
    assert result.continuation == pending
    assert result.to_wire()["continuation"] == pending.to_wire()
    if gate == "scope":
        console = _summarize(result, project_id="project_test")
        assert console.delivery_id == parent.delivery_id
        assert console.checkpoint_sha256 == successor.checkpoint_sha256
        assert console.approval is not None
        assert console.approval.kind == "coder_scope"
        assert console.approval.plan_sha256 == pending.scope_supplement_sha256
    with pytest.raises(ValueError, match="refreshed child checkpoint"):
        JointDeliveryResumeResult(
            checkpoint=successor,
            continuation=pending.model_copy(
                update={"checkpoint": child.model_copy(update={"delivery_id": "delivery_foreign"})}
            ),
        )
