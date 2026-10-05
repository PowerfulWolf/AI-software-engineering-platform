"""Exact, pre-execution Project retirement retains audit and fences the old identity."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.design.store import FileDesignRecordStore
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal, OperatorDuty
from ai_software_engineer.manager.baseline import (
    FileProjectBaselineCompilationStore,
    ProjectBaselineRecordNotFound,
)
from ai_software_engineer.multi_directory.models import DialogueMessage, JointCheckpoint, JointStage
from ai_software_engineer.multi_directory.retirement import (
    RequirementRetirementError,
    RequirementRetirementStore,
)
from ai_software_engineer.multi_directory.scope import DirectoryScope, DirectoryUnit
from ai_software_engineer.multi_directory.store import JointJournal
from ai_software_engineer.planning.store import FileExecutionPlanStore
from ai_software_engineer.product.store import FileProductRecordStore
from ai_software_engineer.project_retirement import (
    ProjectRetiredError,
    ProjectRetirementReceipt,
    ProjectRetirementRejected,
    RetireEmptyProject,
    project_archive_inventory,
    read_project_retirement,
)
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.repository_workspace import RepositoryWorkspace
from ai_software_engineer.team_workspace import TeamWorkspace

NOW = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
PRINCIPAL = LocalOperatorPrincipal.trusted_local()


class _Guard:
    """Fake trusted composition proves exclusion without passing idle request data."""

    def __init__(self, *, refused: bool = False) -> None:
        self.refused = refused
        self.protected: list[Path] = []
        self.active = False

    @contextmanager
    def protect(self, project: ProjectWorkspace) -> Iterator[None]:
        if self.refused:
            raise ProjectRetirementRejected("真实执行器或 Operation 尚未停止")
        self.protected.append(project.root)
        self.active = True
        try:
            yield
        finally:
            self.active = False


def _project(tmp_path: Path) -> ProjectWorkspace:
    team = TeamWorkspace.initialize(tmp_path / "platform", team_id="team_test", name="Test")
    return team.project_registry().create(name="Self Validation")


def _command(project: ProjectWorkspace) -> RetireEmptyProject:
    return RetireEmptyProject(
        project_id=project.manifest.project_id,
        expected_manifest_sha256=project.manifest.manifest_sha256,
        reason="用户删除无工程执行历史的自验证项目",
        submitted_at=NOW,
    )


def _retire(project: ProjectWorkspace, guard: _Guard | None = None) -> ProjectRetirementReceipt:
    return project.team.project_registry().retire_empty(
        _command(project), principal=PRINCIPAL, guard=guard if guard is not None else _Guard()
    )


def _repository(project: ProjectWorkspace, tmp_path: Path) -> RepositoryWorkspace:
    root = tmp_path / "source"
    root.mkdir()
    (root / "code.txt").write_text("original repository bytes\n")
    return project.repository_registry().register(root)


def _retirements(project: ProjectWorkspace) -> RequirementRetirementStore:
    return RequirementRetirementStore(
        project.requirements_root,
        team_id=project.team.manifest.team_id,
        team_manifest_sha256=project.team.manifest.manifest_sha256,
        project_id=project.manifest.project_id,
        project_manifest_sha256=project.manifest.manifest_sha256,
    )


def _draft(
    project: ProjectWorkspace, *, stage: JointStage = JointStage.PREPARING
) -> JointCheckpoint:
    checkpoint = JointCheckpoint.seal(
        {
            "delivery_id": "delivery_multi_product_only",
            "team_id": project.team.manifest.team_id,
            "team_manifest_sha256": project.team.manifest.manifest_sha256,
            "project_id": project.manifest.project_id,
            "project_manifest_sha256": project.manifest.manifest_sha256,
            "sequence": 1,
            "stage": stage,
            "scope": DirectoryScope(
                units=(
                    DirectoryUnit(
                        id="unit_" + "a" * 16,
                        root=str(project.root.parent.parent.parent / "source"),
                        selected_paths=(".",),
                        base_revision=None,
                    ),
                )
            ),
            "title": "Product-only discussion",
            "submitted_at": NOW,
            "next_action": "请回复 Product 提出的问题",
        }
    )
    JointJournal(project.requirements_root).append(checkpoint, expected=None)
    return checkpoint


def _delete_draft(project: ProjectWorkspace, checkpoint: JointCheckpoint) -> None:
    _retirements(project).retire(checkpoint, reason="deleted", retired_at=NOW)


def _receipt_path(project: ProjectWorkspace) -> Path:
    return project.team.root / "project-retirements" / f"{project.manifest.project_id}.json"


def test_empty_project_archive_keeps_manifests_source_and_unrelated_project(tmp_path: Path) -> None:
    project = _project(tmp_path)
    other = project.team.project_registry().create(name="Active Project")
    repository = _repository(project, tmp_path)
    (repository.directory("profile") / "profile.json").write_text('{"original":true}')
    (repository.directory("policy") / "policy.json").write_text('{"original":true}')
    before = project_archive_inventory(project.root)
    project_manifest = (project.root / "project.json").read_bytes()
    repository_manifest = (repository.root / "workspace.json").read_bytes()
    source = (tmp_path / "source" / "code.txt").read_bytes()
    guard = _Guard()

    receipt = _retire(project, guard)

    archive = Path(receipt.archive_root)
    assert not project.root.exists()
    assert archive == tmp_path / "platform" / "project-archives" / project.manifest.project_id
    assert project_archive_inventory(archive) == receipt.inventory == before
    assert (archive / "project.json").read_bytes() == project_manifest
    assert (
        archive / "repositories" / repository.repository_id / "workspace.json"
    ).read_bytes() == repository_manifest
    assert (tmp_path / "source" / "code.txt").read_bytes() == source
    assert guard.protected == [project.root] and not guard.active
    assert read_project_retirement(project.team, project.manifest.project_id) == receipt
    assert project.team.project_registry().discover() == (other,)
    assert _retire(project) == receipt


def test_deleted_product_discussion_retains_all_journal_and_tombstone_bytes(tmp_path: Path) -> None:
    project = _project(tmp_path)
    first = _draft(project)
    current = JointCheckpoint.seal(
        {
            **first.model_dump(),
            "sequence": 2,
            "previous_checkpoint_sha256": first.checkpoint_sha256,
            "stage": JointStage.WAITING_PRODUCT_REPLY,
            "dialogue": (DialogueMessage(speaker="product", text="如何验收该功能?"),),
        }
    )
    journal = JointJournal(project.requirements_root)
    journal.append(current, expected=first.checkpoint_sha256)
    _delete_draft(project, current)
    before = project_archive_inventory(project.root)

    receipt = _retire(project)

    archive = Path(receipt.archive_root)
    assert project_archive_inventory(archive) == before
    archived_journal = JointJournal(archive / "requirements", read_only=True)
    assert archived_journal.history(first.delivery_id) == (first, current)
    archived_retirements = RequirementRetirementStore(
        archive / "requirements",
        team_id=project.team.manifest.team_id,
        team_manifest_sha256=project.team.manifest.manifest_sha256,
        project_id=project.manifest.project_id,
        project_manifest_sha256=project.manifest.manifest_sha256,
        read_only=True,
    )
    assert archived_retirements.retired_delivery_ids(archived_journal) == {first.delivery_id}
    assert archived_retirements.entry(first.delivery_id) is not None


def test_retired_identity_cannot_be_reopened_registered_or_created_by_same_name(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    repository = _repository(project, tmp_path)
    registry = project.team.project_registry()
    stale_repository_registry = project.repository_registry()
    _retire(project)

    with pytest.raises(ProjectRetiredError, match="永久删除"):
        registry.open(project.manifest.project_id)
    with pytest.raises(ProjectRetiredError, match="永久删除"):
        registry.register(project_id=project.manifest.project_id, name=project.manifest.name)
    with pytest.raises(ProjectRetiredError, match="永久删除"):
        registry.create(name=project.manifest.name)
    with pytest.raises(ProjectRetiredError):
        stale_repository_registry.register(repository.repository_root)
    with pytest.raises(ProjectRetiredError):
        project.validate_current()
    assert not project.root.exists()
    assert registry.discover() == ()


def test_receipt_read_and_catalog_discovery_without_receipt_directory_are_read_only(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    retirement_root = project.team.root / "project-retirements"
    (retirement_root / "catalog.lock").unlink()
    retirement_root.rmdir()
    before = project_archive_inventory(Path(project.team.manifest.platform_root))

    assert read_project_retirement(project.team, project.manifest.project_id) is None
    assert project.team.project_registry().discover() == (project,)

    assert not retirement_root.exists()
    assert project_archive_inventory(Path(project.team.manifest.platform_root)) == before


def test_stale_manifest_and_wrong_product_duty_refuse_before_guard(tmp_path: Path) -> None:
    project = _project(tmp_path)
    guard = _Guard()
    command = _command(project).model_copy(update={"expected_manifest_sha256": "b" * 64})
    with pytest.raises(ProjectRetirementRejected, match="manifest 已变化"):
        project.team.project_registry().retire_empty(command, principal=PRINCIPAL, guard=guard)
    engineer = LocalOperatorPrincipal(operator_id="engineer", duties=(OperatorDuty.ENGINEERING,))
    with pytest.raises(ValueError, match="PRODUCT"):
        project.team.project_registry().retire_empty(
            _command(project), principal=engineer, guard=guard
        )
    assert not guard.protected
    assert project.root.exists() and not _receipt_path(project).exists()


def test_mandatory_guard_refuses_live_or_unproven_work_without_receipt(tmp_path: Path) -> None:
    project = _project(tmp_path)
    before = project_archive_inventory(project.root)
    with pytest.raises(ProjectRetirementRejected, match="尚未停止"):
        _retire(project, _Guard(refused=True))
    assert project_archive_inventory(project.root) == before
    assert not _receipt_path(project).exists()


def test_catalog_process_lock_prevents_registration_and_retirement(tmp_path: Path) -> None:
    project = _project(tmp_path)
    path = project.team.root / "project-retirements" / "catalog.lock"
    with path.open("r+") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ProjectRetirementRejected, match="其他操作"):
            _retire(project)
        with pytest.raises(ProjectRetirementRejected, match="其他操作"):
            project.team.project_registry().create(name="New Project")
    assert project.root.exists() and not _receipt_path(project).exists()


def test_live_requirement_cannot_be_hidden_by_project_retirement(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _draft(project)
    with pytest.raises(ProjectRetirementRejected, match="未永久删除"):
        _retire(project)
    assert project.root.exists() and not _receipt_path(project).exists()


@pytest.mark.parametrize(
    "stage", [JointStage.DESIGNING, JointStage.DELIVERING, JointStage.INTEGRATING]
)
def test_advanced_history_is_refused_even_when_current_checkpoint_is_closed(
    tmp_path: Path, stage: JointStage
) -> None:
    project = _project(tmp_path)
    first = _draft(project, stage=stage)
    current = JointCheckpoint.seal(
        {
            **first.model_dump(),
            "sequence": 2,
            "previous_checkpoint_sha256": first.checkpoint_sha256,
            "stage": JointStage.CLOSED,
        }
    )
    JointJournal(project.requirements_root).append(current, expected=first.checkpoint_sha256)
    _delete_draft(project, current)
    with pytest.raises(ProjectRetirementRejected, match="工程执行历史"):
        _retire(project)
    assert not _receipt_path(project).exists()


@pytest.mark.parametrize("key", ["design", "design_transient", "plan", "integration"])
def test_hidden_engineering_attempt_history_is_refused(tmp_path: Path, key: str) -> None:
    project = _project(tmp_path)
    draft = _draft(project)
    checkpoint = JointCheckpoint.seal({**draft.model_dump(), "attempts": {key: 1}})
    (project.requirements_root / draft.delivery_id / "000001.json").write_text(
        checkpoint.model_dump_json()
    )
    _delete_draft(project, checkpoint)
    with pytest.raises(ProjectRetirementRejected, match="工程执行历史"):
        _retire(project)


@pytest.mark.parametrize(
    "store", ["state", "artifacts", "contexts", "assignments", "logs", "runs", "locks"]
)
def test_any_native_execution_fact_is_preserved_and_refused(tmp_path: Path, store: str) -> None:
    project = _project(tmp_path)
    repository = _repository(project, tmp_path)
    fact = repository.root / store / "orphan-history.json"
    fact.write_text("durable existing fact")
    with pytest.raises(ProjectRetirementRejected, match="执行或未知运行事实"):
        _retire(project)
    assert fact.read_text() == "durable existing fact"
    assert not _receipt_path(project).exists()


def _initialize_preexecution_stores(repository: RepositoryWorkspace) -> None:
    state = repository.directory("state")
    FileProductRecordStore(state / "product")
    FileDesignRecordStore(state / "design")
    FileExecutionPlanStore(state / "planning")
    with pytest.raises(ProjectBaselineRecordNotFound):
        FileProjectBaselineCompilationStore().get(repository, "a" * 64)


def test_production_preinitialized_empty_stores_are_preserved_and_can_retire(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    repository = _repository(project, tmp_path)
    _initialize_preexecution_stores(repository)
    assert {path.name for path in repository.directory("state").iterdir()} == {
        "product",
        "design",
        "planning",
    }
    assert {path.name for path in repository.directory("spec-conflicts").iterdir()} == {
        "project-baseline-compilations",
    }
    before = project_archive_inventory(project.root)

    receipt = _retire(project)

    assert receipt.inventory == before
    assert project_archive_inventory(Path(receipt.archive_root)) == before
    assert not project.root.exists()


@pytest.mark.parametrize(
    ("relative", "kind"),
    [
        ("state/product/dialogue.json", "file"),
        ("state/design/unknown", "directory"),
        ("state/planning/run.json", "file"),
        ("state/unknown", "directory"),
        ("spec-conflicts/project-baseline-compilations/conflict.json", "file"),
        ("spec-conflicts/project-baseline-compilations/unknown", "directory"),
        ("spec-conflicts/unknown", "directory"),
        ("logs/unknown", "directory"),
        ("state/product", "symlink"),
    ],
)
def test_preinitialized_stores_with_actual_or_unknown_facts_still_refuse(
    tmp_path: Path, relative: str, kind: str
) -> None:
    project = _project(tmp_path)
    repository = _repository(project, tmp_path)
    _initialize_preexecution_stores(repository)
    fact = repository.root / relative
    if kind == "directory":
        fact.mkdir()
    elif kind == "symlink":
        fact.rmdir()
        fact.symlink_to(tmp_path, target_is_directory=True)
    else:
        fact.write_text("preserved execution fact")
    with pytest.raises(ProjectRetirementRejected, match="执行或未知运行事实"):
        _retire(project)
    assert fact.exists() and project.root.exists() and not _receipt_path(project).exists()


@pytest.mark.parametrize(
    "place", ["project", "repository", "requirements", "repositories", "requirement"]
)
@pytest.mark.parametrize("directory", [False, True])
def test_unknown_fact_roots_are_refused(tmp_path: Path, place: str, directory: bool) -> None:
    project = _project(tmp_path)
    repository = _repository(project, tmp_path)
    draft = _draft(project)
    _delete_draft(project, draft)
    root = {
        "project": project.root,
        "repository": repository.root,
        "requirements": project.requirements_root,
        "repositories": project.root / "repositories",
        "requirement": project.requirements_root / draft.delivery_id,
    }[place]
    fact = root / "orphan-task"
    if directory:
        fact.mkdir()
        (fact / "task.json").write_text("existing task")
    else:
        fact.write_text("existing task")
    with pytest.raises(ProjectRetirementRejected, match="未识别"):
        _retire(project)
    assert fact.exists() and project.root.exists() and not _receipt_path(project).exists()


def test_existing_role_worktree_is_not_deleted_or_accepted_as_empty(tmp_path: Path) -> None:
    project = _project(tmp_path)
    repository = _repository(project, tmp_path)
    worktree = tmp_path / "platform" / "worktrees" / repository.repository_id
    worktree.mkdir(parents=True)
    (worktree / "dirty.txt").write_text("work in progress")
    with pytest.raises(ProjectRetirementRejected, match="worktree"):
        _retire(project)
    assert (worktree / "dirty.txt").read_text() == "work in progress"
    assert not _receipt_path(project).exists()


@pytest.mark.parametrize("kind", ["symlink", "fifo", "hardlink"])
def test_archive_refuses_symlinks_special_files_and_external_hardlinks(
    tmp_path: Path, kind: str
) -> None:
    project = _project(tmp_path)
    path = project.root / "knowledge" / "unsafe"
    outside = tmp_path / "outside"
    outside.write_text("external bytes")
    if kind == "symlink":
        path.symlink_to(outside)
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        os.link(outside, path)
    with pytest.raises(ProjectRetirementRejected, match=r"符号链接|特殊文件|硬链接"):
        _retire(project)
    assert outside.read_text() == "external bytes"
    assert project.root.exists() and not _receipt_path(project).exists()


def test_receipt_crash_fences_catalog_then_exact_replay_completes_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    with monkeypatch.context() as fault:

        def crash(team: TeamWorkspace, receipt: ProjectRetirementReceipt) -> None:
            del team, receipt
            raise OSError("injected crash before rename")

        fault.setattr("ai_software_engineer.project_retirement._complete_archive", crash)
        with pytest.raises(OSError, match="injected crash"):
            _retire(project)
    assert project.root.exists() and _receipt_path(project).exists()
    assert project.team.project_registry().discover() == ()
    with pytest.raises(ProjectRetiredError):
        project.team.project_registry().register(
            project_id=project.manifest.project_id, name=project.manifest.name
        )
    original = _receipt_path(project).read_bytes()

    receipt = _retire(project)

    assert not project.root.exists()
    assert project_archive_inventory(Path(receipt.archive_root)) == receipt.inventory
    assert _receipt_path(project).read_bytes() == original


def test_crash_after_rename_replays_without_recreating_original_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    with monkeypatch.context() as fault:

        def crash(path: Path) -> None:
            if path == project.root.parent:
                raise OSError("injected crash after rename")

        fault.setattr("ai_software_engineer.project_workspace._sync_directory", crash)
        with pytest.raises(OSError, match="after rename"):
            _retire(project)
    assert not project.root.exists() and _receipt_path(project).exists()
    original = _receipt_path(project).read_bytes()
    receipt = _retire(project)
    assert not project.root.exists() and Path(receipt.archive_root).is_dir()
    assert _receipt_path(project).read_bytes() == original


@pytest.mark.parametrize("change", ["timestamp", "reason", "principal", "manifest"])
def test_replay_requires_the_original_exact_command_and_principal(
    tmp_path: Path, change: str
) -> None:
    project = _project(tmp_path)
    receipt = _retire(project)
    command = _command(project)
    principal = PRINCIPAL
    if change == "timestamp":
        command = command.model_copy(update={"submitted_at": NOW + timedelta(seconds=1)})
    elif change == "reason":
        command = command.model_copy(update={"reason": "different reason"})
    elif change == "manifest":
        command = command.model_copy(update={"expected_manifest_sha256": "c" * 64})
    else:
        principal = LocalOperatorPrincipal(
            operator_id="another-product", duties=(OperatorDuty.PRODUCT,)
        )
    guard = _Guard()
    with pytest.raises(ProjectRetirementRejected, match="精确命令"):
        project.team.project_registry().retire_empty(command, principal=principal, guard=guard)
    assert not guard.protected
    assert read_project_retirement(project.team, project.manifest.project_id) == receipt


@pytest.mark.parametrize("corruption", ["source-drift", "archive-drift", "both-present"])
def test_replay_preserves_changed_or_ambiguous_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    project = _project(tmp_path)
    if corruption == "source-drift":
        with monkeypatch.context() as fault:

            def crash(team: TeamWorkspace, receipt: ProjectRetirementReceipt) -> None:
                del team, receipt
                raise OSError("injected crash")

            fault.setattr("ai_software_engineer.project_retirement._complete_archive", crash)
            with pytest.raises(OSError):
                _retire(project)
        (project.root / "knowledge" / "new.md").write_text("unexpected change")
    else:
        receipt = _retire(project)
        if corruption == "archive-drift":
            (Path(receipt.archive_root) / "knowledge" / "new.md").write_text("unexpected change")
        else:
            project.root.mkdir()
    with pytest.raises(ProjectRetirementRejected, match=r"偏离|不一致|同时存在"):
        _retire(project)
    assert _receipt_path(project).exists()


def test_preexisting_archive_refuses_before_permanent_receipt(tmp_path: Path) -> None:
    project = _project(tmp_path)
    archive = tmp_path / "platform" / "project-archives" / project.manifest.project_id
    archive.mkdir(parents=True)
    (archive / "forensics.txt").write_text("existing archive")
    with pytest.raises(ProjectRetirementRejected, match="归档位置已有"):
        _retire(project)
    assert project.root.exists() and not _receipt_path(project).exists()
    assert (archive / "forensics.txt").read_text() == "existing archive"


def test_serialized_receipt_budget_is_checked_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    monkeypatch.setattr("ai_software_engineer.project_retirement._MAX_RECEIPT_BYTES", 100)
    with pytest.raises(ProjectRetirementRejected, match="超过读取预算"):
        _retire(project)
    assert project.root.exists() and not _receipt_path(project).exists()
    assert not tuple((_receipt_path(project).parent).glob(".retirement-*"))


def test_tampered_receipt_or_requirement_tombstone_fails_closed(tmp_path: Path) -> None:
    project = _project(tmp_path)
    draft = _draft(project)
    _delete_draft(project, draft)
    path = _retirements(project).path
    original = path.read_bytes()
    data = json.loads(original)
    data["retirement_sha256"] = "d" * 64
    path.write_text(json.dumps(data))
    with pytest.raises(RequirementRetirementError, match="digest"):
        _retire(project)
    assert project.root.exists() and not _receipt_path(project).exists()
    path.write_bytes(original)
    _retire(project)
    data = json.loads(_receipt_path(project).read_bytes())
    data["retirement_sha256"] = "e" * 64
    _receipt_path(project).write_text(json.dumps(data))
    with pytest.raises(ProjectRetirementRejected, match="摘要"):
        project.team.project_registry().open(project.manifest.project_id)
