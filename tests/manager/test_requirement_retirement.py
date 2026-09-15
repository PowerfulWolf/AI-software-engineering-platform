"""Requirement draft replacement and logical retirement contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn

import pytest

from ai_software_engineer.agents import StructuredModelClient
from ai_software_engineer.domain import TeamRole
from ai_software_engineer.domain.project_delivery import ProjectPreparation
from ai_software_engineer.manager.delivery import DeliveryCheckpointStale
from ai_software_engineer.manager.preparation import PrepareProjectResult, PrepareProjectStatus
from ai_software_engineer.manager.production_agents import (
    AcceptanceDraft,
    ProductDraft,
    RequirementDraft,
)
from ai_software_engineer.multi_directory.models import (
    DialogueMessage,
    JointApproval,
    JointCheckpoint,
    JointExecutionPlan,
    JointProductSpec,
    JointStage,
    PreparedUnit,
    digest,
)
from ai_software_engineer.multi_directory.retirement import (
    RequirementRetirementError,
    RequirementRetirementStore,
)
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit
from ai_software_engineer.multi_directory.service import (
    CloseRequirement,
    CreateRequirement,
    DeleteRequirement,
    JointDeliveryService,
    UpdateRequirement,
)
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.team_workspace import TeamWorkspace

NOW = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)


class _PreparationBackend:
    def __init__(self, team: TeamWorkspace, project: ProjectWorkspace) -> None:
        self.team = team
        self.project = project

    def prepare(self, unit: DirectoryUnit) -> PreparedUnit:
        repository = self.project.repository_registry().register(unit.root)
        preparation = ProjectPreparation.create(
            team_id=self.team.manifest.team_id,
            project_id=self.project.manifest.project_id,
            project_manifest_sha256=self.project.manifest.manifest_sha256,
            repository_id=repository.repository_id,
            repository_root=unit.root,
            repository_workspace_root=str(repository.root),
            team_root=str(self.team.root),
            repository_profile_sha256="1" * 64,
            runtime_binding_sha256="2" * 64,
            baseline_spec_sha256="3" * 64,
            prepared_at=NOW,
        )
        return PreparedUnit(
            unit_id=unit.id,
            result=PrepareProjectResult(
                status=PrepareProjectStatus.PREPARED,
                repository_id=repository.repository_id,
                baseline_compilation_sha256="4" * 64,
                preparation=preparation,
            ),
        )

    def reconcile(self, checkpoint: JointCheckpoint) -> None:
        del checkpoint

    def client(self, scope: DirectoryScope, role: TeamRole) -> StructuredModelClient:
        del scope, role
        raise AssertionError("draft mutation must not invoke a model")

    def deliver(self, checkpoint: JointCheckpoint, unit_id: str) -> NoReturn:
        del checkpoint, unit_id
        raise AssertionError("draft mutation must not deliver")

    def integrate(self, checkpoint: JointCheckpoint) -> NoReturn:
        del checkpoint
        raise AssertionError("draft mutation must not integrate")

    def validate_plan(self, checkpoint: JointCheckpoint, plan: JointExecutionPlan) -> None:
        del checkpoint, plan


def _service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[JointDeliveryService, Path]:
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    project = team.project_registry().register(project_id="project_test", name="Project")
    repository = tmp_path / "code"
    repository.mkdir()

    def git_read(root: Path, *args: str) -> str | None:
        if "--show-toplevel" in args:
            return str(root)
        if "--git-common-dir" in args:
            return None
        if "HEAD^{commit}" in args:
            return "a" * 40
        return None

    monkeypatch.setattr("ai_software_engineer.multi_directory.scope.git_read", git_read)
    return (
        JointDeliveryService(
            backend=_PreparationBackend(team, project),
            team=team,
            project=project,
        ),
        repository,
    )


def _product_spec(checkpoint: JointCheckpoint) -> JointProductSpec:
    return JointProductSpec(
        scope_sha256=digest(checkpoint.scope),
        version=1,
        product=ProductDraft(
            action="ready",
            summary="Ready for approval",
            goals=("Ship safely",),
            requirements=(
                RequirementDraft(
                    statement="Implement the requested behavior",
                    rationale="The user requested it",
                    acceptance=(
                        AcceptanceDraft(
                            description="The behavior works",
                            verification="Run the focused regression",
                        ),
                    ),
                ),
            ),
        ),
    )


def test_edit_replaces_exact_draft_and_preserves_original_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, repository = _service(tmp_path, monkeypatch)
    original = service.create(
        CreateRequirement(name="Original", repository_roots=(str(repository),), submitted_at=NOW)
    ).checkpoint

    replacement = service.update_requirement(
        UpdateRequirement(
            delivery_id=original.delivery_id,
            expected_checkpoint_sha256=original.checkpoint_sha256,
            name="Renamed",
            repository_roots=(str(repository),),
            submitted_at=NOW,
        )
    ).checkpoint

    assert replacement.title == "Renamed"
    assert replacement.delivery_id != original.delivery_id
    assert service.journal.current(original.delivery_id) == original
    retired = service.retirements.entry(original.delivery_id)
    assert retired is not None
    assert retired.reason == "replaced"
    assert retired.replacement_delivery_id == replacement.delivery_id
    with pytest.raises(ValueError, match="retired"):
        service.status(original.delivery_id)


def test_delete_is_logical_and_exact_checkpoint_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, repository = _service(tmp_path, monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="Disposable", repository_roots=(str(repository),), submitted_at=NOW)
    ).checkpoint

    with pytest.raises(DeliveryCheckpointStale):
        service.delete_requirement(
            DeleteRequirement(
                delivery_id=checkpoint.delivery_id,
                expected_checkpoint_sha256="f" * 64,
                submitted_at=NOW,
            )
        )
    service.delete_requirement(
        DeleteRequirement(
            delivery_id=checkpoint.delivery_id,
            expected_checkpoint_sha256=checkpoint.checkpoint_sha256,
            submitted_at=NOW,
        )
    )

    assert service.journal.current(checkpoint.delivery_id) == checkpoint
    retired = service.retirements.entry(checkpoint.delivery_id)
    assert retired is not None and retired.reason == "deleted"


def test_started_requirement_cannot_be_edited_but_can_be_deleted_before_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, repository = _service(tmp_path, monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="Draft", repository_roots=(str(repository),), submitted_at=NOW)
    ).checkpoint
    with pytest.raises(ValueError, match="did not change"):
        service.update_requirement(
            UpdateRequirement(
                delivery_id=checkpoint.delivery_id,
                expected_checkpoint_sha256=checkpoint.checkpoint_sha256,
                name=checkpoint.title,
                repository_roots=(str(repository),),
                submitted_at=NOW,
            )
        )

    started = service._save(
        checkpoint,
        stage=JointStage.WAITING_PRODUCT_REPLY,
        dialogue=(DialogueMessage(speaker="user", text="Start"),),
    )
    with pytest.raises(ValueError, match="before Product discussion"):
        service.update_requirement(
            UpdateRequirement(
                delivery_id=started.delivery_id,
                expected_checkpoint_sha256=started.checkpoint_sha256,
                name="Too late to edit",
                repository_roots=(str(repository),),
                submitted_at=NOW,
            )
        )
    service.delete_requirement(
        DeleteRequirement(
            delivery_id=started.delivery_id,
            expected_checkpoint_sha256=started.checkpoint_sha256,
            submitted_at=NOW,
        )
    )
    assert service.retirements.entry(started.delivery_id) is not None


def test_requirement_cannot_be_deleted_after_product_approval_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, repository = _service(tmp_path, monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="Delivering", repository_roots=(str(repository),), submitted_at=NOW)
    ).checkpoint
    product_spec = _product_spec(checkpoint)
    awaiting_approval = service._save(
        checkpoint,
        stage=JointStage.WAITING_PRODUCT_APPROVAL,
        dialogue=(DialogueMessage(speaker="user", text="Start"),),
        product_spec=product_spec,
    )
    delivering = service._save(
        awaiting_approval,
        stage=JointStage.DESIGNING,
        approval=JointApproval(
            product_spec_sha256=digest(product_spec),
            checkpoint_sha256=awaiting_approval.checkpoint_sha256,
            reference="human:test",
            approved_at=NOW,
        ),
    )

    with pytest.raises(ValueError, match="before ProductSpec approval"):
        service.delete_requirement(
            DeleteRequirement(
                delivery_id=delivering.delivery_id,
                expected_checkpoint_sha256=delivering.checkpoint_sha256,
                submitted_at=NOW,
            )
        )


def test_blocked_requirement_can_be_closed_then_logically_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, repository = _service(tmp_path, monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="Blocked", repository_roots=(str(repository),), submitted_at=NOW)
    ).checkpoint
    blocked = service._save(
        checkpoint,
        stage=JointStage.BLOCKED,
        next_action="Inspect the retained checkpoint.",
    )

    closed = service.close_requirement(
        CloseRequirement(
            delivery_id=blocked.delivery_id,
            expected_checkpoint_sha256=blocked.checkpoint_sha256,
            submitted_at=NOW,
        )
    ).checkpoint

    assert closed.stage is JointStage.CLOSED
    assert closed.previous_checkpoint_sha256 == blocked.checkpoint_sha256
    assert service.journal.current(blocked.delivery_id) == closed
    assert service.retirements.entry(blocked.delivery_id) is None

    service.delete_requirement(
        DeleteRequirement(
            delivery_id=closed.delivery_id,
            expected_checkpoint_sha256=closed.checkpoint_sha256,
            submitted_at=NOW,
        )
    )
    assert service.retirements.entry(closed.delivery_id) is not None


def test_only_blocked_requirement_can_be_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, repository = _service(tmp_path, monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="Active", repository_roots=(str(repository),), submitted_at=NOW)
    ).checkpoint

    with pytest.raises(ValueError, match="only be closed while blocked"):
        service.close_requirement(
            CloseRequirement(
                delivery_id=checkpoint.delivery_id,
                expected_checkpoint_sha256=checkpoint.checkpoint_sha256,
                submitted_at=NOW,
            )
        )


def test_blocked_requirement_can_be_logically_deleted_directly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, repository = _service(tmp_path, monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="Blocked", repository_roots=(str(repository),), submitted_at=NOW)
    ).checkpoint
    blocked = service._save(
        checkpoint,
        stage=JointStage.BLOCKED,
        next_action="Inspect the retained checkpoint.",
    )

    service.delete_requirement(
        DeleteRequirement(
            delivery_id=blocked.delivery_id,
            expected_checkpoint_sha256=blocked.checkpoint_sha256,
            submitted_at=NOW,
        )
    )

    assert service.retirements.entry(blocked.delivery_id) is not None
    assert service.journal.current(blocked.delivery_id) == blocked


def test_unapproved_product_spec_can_be_logically_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, repository = _service(tmp_path, monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="Unapproved", repository_roots=(str(repository),), submitted_at=NOW)
    ).checkpoint
    awaiting_approval = service._save(
        checkpoint,
        stage=JointStage.WAITING_PRODUCT_APPROVAL,
        dialogue=(DialogueMessage(speaker="user", text="Start"),),
        product_spec=_product_spec(checkpoint),
    )

    service.delete_requirement(
        DeleteRequirement(
            delivery_id=awaiting_approval.delivery_id,
            expected_checkpoint_sha256=awaiting_approval.checkpoint_sha256,
            submitted_at=NOW,
        )
    )

    assert service.retirements.entry(awaiting_approval.delivery_id) is not None


def test_edit_cannot_converge_on_an_existing_started_requirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, repository = _service(tmp_path, monkeypatch)
    original = service.create(
        CreateRequirement(name="Original", repository_roots=(str(repository),), submitted_at=NOW)
    ).checkpoint
    existing = service.create(
        CreateRequirement(name="Existing", repository_roots=(str(repository),), submitted_at=NOW)
    ).checkpoint
    service._save(
        existing,
        stage=JointStage.WAITING_PRODUCT_REPLY,
        dialogue=(DialogueMessage(speaker="user", text="Already started"),),
    )

    with pytest.raises(ValueError, match="before Product discussion"):
        service.update_requirement(
            UpdateRequirement(
                delivery_id=original.delivery_id,
                expected_checkpoint_sha256=original.checkpoint_sha256,
                name="Existing",
                repository_roots=(str(repository),),
                submitted_at=NOW,
            )
        )

    assert service.retirements.entry(original.delivery_id) is None


def test_failed_replacement_stays_out_of_current_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, repository = _service(tmp_path, monkeypatch)
    original = service.create(
        CreateRequirement(name="Original", repository_roots=(str(repository),), submitted_at=NOW)
    ).checkpoint

    def failed_prepare(unit: DirectoryUnit) -> NoReturn:
        del unit
        raise RuntimeError("preparation failed")

    monkeypatch.setattr(service.backend, "prepare", failed_prepare)
    replacement_id = service._delivery_id(original.scope, "Renamed", None)

    with pytest.raises(RuntimeError, match="preparation failed"):
        service.update_requirement(
            UpdateRequirement(
                delivery_id=original.delivery_id,
                expected_checkpoint_sha256=original.checkpoint_sha256,
                name="Renamed",
                repository_roots=(str(repository),),
                submitted_at=NOW,
            )
        )

    assert service.retirements.entry(original.delivery_id) is None
    hidden_replacement = service.retirements.entry(replacement_id)
    assert hidden_replacement is not None and hidden_replacement.reason == "deleted"


def test_retirement_record_detects_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, repository = _service(tmp_path, monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="Draft", repository_roots=(str(repository),), submitted_at=NOW)
    ).checkpoint
    service.delete_requirement(
        DeleteRequirement(
            delivery_id=checkpoint.delivery_id,
            expected_checkpoint_sha256=checkpoint.checkpoint_sha256,
            submitted_at=NOW,
        )
    )
    path = service.project.requirements_root / "retirement.json"
    payload = json.loads(path.read_text())
    payload["entries"][0]["reason"] = "replaced"
    path.write_text(json.dumps(payload))

    read_only = RequirementRetirementStore(
        service.project.requirements_root,
        team_id=service.team.manifest.team_id,
        team_manifest_sha256=service.team.manifest.manifest_sha256,
        project_id=service.project.manifest.project_id,
        project_manifest_sha256=service.project.manifest.manifest_sha256,
        read_only=True,
    )
    with pytest.raises(RequirementRetirementError):
        read_only.retirement()


def test_retirement_retry_ignores_timestamp_and_replacement_must_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, repository = _service(tmp_path, monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="Draft", repository_roots=(str(repository),), submitted_at=NOW)
    ).checkpoint
    first = service.retirements.retire(
        checkpoint,
        reason="deleted",
        retired_at=NOW,
    )
    retried = service.retirements.retire(
        checkpoint,
        reason="deleted",
        retired_at=NOW + timedelta(seconds=1),
    )
    assert retried == first

    service.retirements.restore(checkpoint.delivery_id)
    service.retirements.retire(
        checkpoint,
        reason="replaced",
        replacement_delivery_id="delivery_multi_" + "f" * 40,
        retired_at=NOW,
    )
    with pytest.raises(RequirementRetirementError, match="replacement journal is missing"):
        service.retirements.retired_delivery_ids(service.journal)
