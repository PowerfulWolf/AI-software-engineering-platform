"""Exact retirement of stopped, pre-execution Projects without erasing their audit."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Protocol, Self

from pydantic import (
    AwareDatetime,
    Field,
    StrictInt,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal, OperatorDuty
from ai_software_engineer.domain.identity import ProjectId, TeamId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.project_workspace import ProjectManifest, ProjectWorkspace
from ai_software_engineer.team_workspace import TeamWorkspace

Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
_MAX_FILES = 10_000
_MAX_FILE_BYTES = 64_000_000
_MAX_TREE_BYTES = 256_000_000
_MAX_RECEIPT_BYTES = 4_000_000


class ProjectRetirementRejected(ValueError):
    """The exact empty-Project archive cannot be safely authorized or replayed."""


class ProjectRetiredError(ProjectRetirementRejected):
    """A permanently retired identity cannot acquire a new execution workspace."""


class RetireEmptyProject(DomainModel):
    project_id: ProjectId
    expected_manifest_sha256: Sha256
    reason: Annotated[str, StringConstraints(min_length=1, max_length=1_000)]
    submitted_at: AwareDatetime


class ProjectArchiveEntry(DomainModel):
    path: NonEmptyStr
    kind: Literal["file", "directory"]
    mode: Annotated[StrictInt, Field(ge=0, le=0o7777)]
    bytes: Annotated[StrictInt, Field(ge=0, le=_MAX_FILE_BYTES)]
    sha256: Sha256 | None = None

    @model_validator(mode="after")
    def safe_path_and_body(self) -> Self:
        path = PurePosixPath(self.path)
        if (
            path.is_absolute()
            or self.path == "."
            or path.as_posix() != self.path
            or any(part in {"", ".", ".."} for part in path.parts)
            or "\\" in self.path
            or any(ord(value) < 32 for value in self.path)
        ):
            raise ValueError("archive inventory path is not canonical and relative")
        if (self.kind == "file") != (self.sha256 is not None):
            raise ValueError("archive inventory digest does not match its file kind")
        if self.kind == "directory" and self.bytes != 0:
            raise ValueError("archive directory cannot declare file bytes")
        return self


class ProjectRetirementReceipt(DomainModel):
    kind: Literal["empty_project_retirement"] = "empty_project_retirement"
    schema_version: Literal["v1"] = "v1"
    team_id: TeamId
    team_manifest_sha256: Sha256
    project_manifest: ProjectManifest
    principal: LocalOperatorPrincipal
    reason: Annotated[str, StringConstraints(min_length=1, max_length=1_000)]
    retired_at: AwareDatetime
    archive_root: NonEmptyStr
    inventory: Annotated[
        tuple[ProjectArchiveEntry, ...], Field(min_length=1, max_length=_MAX_FILES)
    ]
    inventory_sha256: Sha256
    retirement_sha256: Sha256

    @model_validator(mode="after")
    def validate_inventory(self) -> Self:
        self.principal.require_duty(OperatorDuty.PRODUCT)
        self.project_manifest.validate_integrity()
        if (
            self.project_manifest.team_id != self.team_id
            or self.project_manifest.team_manifest_sha256 != self.team_manifest_sha256
        ):
            raise ValueError("Project retirement changed its Team lineage")
        paths = tuple(item.path for item in self.inventory)
        if (
            paths != tuple(sorted(set(paths)))
            or sum(item.bytes for item in self.inventory) > _MAX_TREE_BYTES
        ):
            raise ValueError("Project retirement inventory is unordered, duplicated or too large")
        if self.inventory_sha256 != _inventory_digest(self.inventory):
            raise ValueError("Project retirement inventory digest mismatch")
        return self

    def validate_integrity(self) -> None:
        if self.retirement_sha256 != _digest(self, "retirement_sha256"):
            raise ProjectRetirementRejected("项目退休记录摘要不一致")


class ProjectRetirementGuard(Protocol):
    def protect(self, project: ProjectWorkspace) -> AbstractContextManager[None]:
        """Hold real service/Operation exclusion; reject unproven or live work.

        Trusted local composition supplies this guard, never request/model data.
        Keep it held through both the durable retirement publication and archive.
        """
        ...


def _digest(value: DomainModel, field: str) -> str:
    body = json.dumps(
        value.model_dump(mode="json", exclude={field}),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(body).hexdigest()


def _inventory_digest(values: tuple[ProjectArchiveEntry, ...]) -> str:
    return hashlib.sha256(
        json.dumps(
            [value.to_wire() for value in values], sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _safe(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise ProjectRetirementRejected("项目退休路径必须是精确绝对路径")
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ProjectRetirementRejected("项目退休路径不能经过符号链接")


def _receipt_root(team: TeamWorkspace) -> Path:
    return team.root / "project-retirements"


def _archive_root(team: TeamWorkspace, project_id: str) -> Path:
    return Path(team.manifest.platform_root) / "project-archives" / project_id


@contextmanager
def project_catalog_lock(team: TeamWorkspace) -> Iterator[None]:
    """Shared by registration and retirement; catalog mutation cannot revive an ID."""
    team.validate_current()
    root = _receipt_root(team)
    _safe(root)
    root.mkdir(exist_ok=True)
    descriptor = os.open(root / "catalog.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ProjectRetirementRejected("项目目录锁不是普通文件")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ProjectRetirementRejected("项目目录正在被其他操作使用, 请等待操作结束") from error
        yield
    finally:
        os.close(descriptor)


def read_project_retirement(
    team: TeamWorkspace, project_id: str
) -> ProjectRetirementReceipt | None:
    identity = TypeAdapter(ProjectId).validate_python(project_id)
    root = _receipt_root(team)
    _safe(root)
    if not root.exists():
        return None
    if not root.is_dir():
        raise ProjectRetirementRejected("项目退休目录已损坏")
    path = root / f"{identity}.json"
    _safe(path)
    if not path.exists():
        return None
    from ai_software_engineer.project_workspace import _read_regular

    receipt = ProjectRetirementReceipt.model_validate_json(_read_regular(path, _MAX_RECEIPT_BYTES))
    receipt.validate_integrity()
    manifest = receipt.project_manifest
    if (
        receipt.team_id != team.manifest.team_id
        or receipt.team_manifest_sha256 != team.manifest.manifest_sha256
        or manifest.project_id != identity
        or Path(manifest.project_root) != Path(team.manifest.platform_root) / "projects" / identity
        or Path(receipt.archive_root) != _archive_root(team, identity)
    ):
        raise ProjectRetirementRejected("项目退休记录与当前 Team、身份或归档位置不一致")
    return receipt


def require_project_active(team: TeamWorkspace, project_id: str) -> None:
    if read_project_retirement(team, project_id) is not None:
        raise ProjectRetiredError("该 Project 已永久删除, 原身份不能重新注册或执行")


def project_archive_inventory(root: Path) -> tuple[ProjectArchiveEntry, ...]:
    """Seal the whole sidecar without following symlinks or special file readers."""
    _safe(root)
    entries: list[ProjectArchiveEntry] = []
    total = 0

    def walk(descriptor: int, prefix: str) -> None:
        nonlocal total
        with os.scandir(descriptor) as children:
            names = sorted(child.name for child in children)
        for name in names:
            relative = f"{prefix}/{name}" if prefix else name
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode) and not stat.S_ISDIR(metadata.st_mode):
                raise ProjectRetirementRejected("项目归档拒绝符号链接或特殊文件")
            is_directory = stat.S_ISDIR(metadata.st_mode)
            child = os.open(
                name,
                os.O_RDONLY
                | os.O_NOFOLLOW
                | os.O_NONBLOCK
                | (os.O_DIRECTORY if is_directory else 0),
                dir_fd=descriptor,
            )
            try:
                before = os.fstat(child)
                if (before.st_dev, before.st_ino) != (metadata.st_dev, metadata.st_ino):
                    raise ProjectRetirementRejected("项目归档节点在读取前已变化")
                if is_directory:
                    entries.append(
                        ProjectArchiveEntry(
                            path=relative,
                            kind="directory",
                            mode=stat.S_IMODE(before.st_mode),
                            bytes=0,
                        )
                    )
                    walk(child, relative)
                else:
                    if before.st_nlink != 1 or before.st_size > _MAX_FILE_BYTES:
                        raise ProjectRetirementRejected("项目归档文件有外部硬链接或超过预算")
                    sha = hashlib.sha256()
                    size = 0
                    while block := os.read(child, 65_536):
                        size += len(block)
                        total += len(block)
                        if size > _MAX_FILE_BYTES or total > _MAX_TREE_BYTES:
                            raise ProjectRetirementRejected("项目归档文件超过字节预算")
                        sha.update(block)
                    after = os.fstat(child)
                    if (
                        before.st_size,
                        before.st_mtime_ns,
                        before.st_ctime_ns,
                        before.st_mode,
                    ) != (
                        after.st_size,
                        after.st_mtime_ns,
                        after.st_ctime_ns,
                        after.st_mode,
                    ) or size != before.st_size:
                        raise ProjectRetirementRejected("项目归档文件在读取期间已变化")
                    entries.append(
                        ProjectArchiveEntry(
                            path=relative,
                            kind="file",
                            mode=stat.S_IMODE(before.st_mode),
                            bytes=size,
                            sha256=sha.hexdigest(),
                        )
                    )
                if len(entries) > _MAX_FILES:
                    raise ProjectRetirementRejected("项目归档条目超过预算")
            finally:
                os.close(child)

    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        walk(descriptor, "")
    finally:
        os.close(descriptor)
    return tuple(sorted(entries, key=lambda entry: entry.path))


def _require_empty_project(project: ProjectWorkspace) -> None:
    from ai_software_engineer.multi_directory.models import JointStage
    from ai_software_engineer.multi_directory.retirement import RequirementRetirementStore
    from ai_software_engineer.multi_directory.store import JointJournal
    from ai_software_engineer.repository_workspace import WORKSPACE_DIRECTORIES, WorkspaceDirectory

    project.validate_current()
    journal = JointJournal(project.requirements_root, read_only=True)
    retirements = RequirementRetirementStore(
        project.requirements_root,
        team_id=project.team.manifest.team_id,
        team_manifest_sha256=project.team.manifest.manifest_sha256,
        project_id=project.manifest.project_id,
        project_manifest_sha256=project.manifest.manifest_sha256,
        read_only=True,
    )
    retired = retirements.retired_delivery_ids(journal)
    retired_entries = {entry.delivery_id: entry for entry in retirements.retirement().entries}
    allowed_stages = {
        JointStage.PREPARING,
        JointStage.READY_FOR_DISCUSSION,
        JointStage.PRODUCT_DISCOVERY,
        JointStage.WAITING_PRODUCT_REPLY,
        JointStage.WAITING_PRODUCT_APPROVAL,
        JointStage.WAITING_HUMAN,
        JointStage.BLOCKED,
        JointStage.CLOSED,
    }
    for path in project.requirements_root.iterdir():
        if path.name in {"retirement.json", ".retirement.lock"} and path.is_file():
            continue
        if not path.is_dir() or not path.name.startswith("delivery_multi_"):
            raise ProjectRetirementRejected("项目包含未识别的需求事实, 不能证明没有执行历史")
        history = journal.history(path.name)
        if (
            not history
            or path.name not in retired
            or retired_entries[path.name].reason != "deleted"
        ):
            raise ProjectRetirementRejected("项目仍有未永久删除的需求")
        known_entries = {
            *(f"{checkpoint.sequence:06d}.json" for checkpoint in history),
            "operation.lock",
            "knowledge",
        }
        if any(entry.name not in known_entries for entry in path.iterdir()):
            raise ProjectRetirementRejected("需求包含未识别的事实, 不能按空项目退休")
        for checkpoint in history:
            if (
                checkpoint.team_id != project.team.manifest.team_id
                or checkpoint.team_manifest_sha256 != project.team.manifest.manifest_sha256
                or checkpoint.project_id != project.manifest.project_id
                or checkpoint.project_manifest_sha256 != project.manifest.manifest_sha256
                or checkpoint.stage not in allowed_stages
                or checkpoint.approval is not None
                or checkpoint.design is not None
                or checkpoint.design_feedback is not None
                or checkpoint.plan is not None
                or checkpoint.children
                or checkpoint.planning_decision is not None
                or checkpoint.planning_upgrade is not None
                or checkpoint.planning_feedback is not None
                or checkpoint.knowledge_rechecks
                or checkpoint.knowledge_wait_stage not in {None, *allowed_stages}
                or checkpoint.integration is not None
                or checkpoint.single_repository_acceptance is not None
                or checkpoint.integration_retry_approval is not None
                or any(
                    key.startswith(("design", "plan", "integration")) for key in checkpoint.attempts
                )
            ):
                raise ProjectRetirementRejected("项目有批准或工程执行历史, 不支持空项目退休")
    execution_directories: tuple[WorkspaceDirectory, ...] = (
        "assignments",
        "state",
        "artifacts",
        "contexts",
        "evidence",
        "evaluations",
        "handoffs",
        "runs",
        "locks",
        "logs",
        "spec-conflicts",
    )
    preinitialized_empty_children: dict[WorkspaceDirectory, frozenset[str]] = {
        "state": frozenset({"product", "design", "planning"}),
        "spec-conflicts": frozenset({"project-baseline-compilations"}),
    }
    if {path.name for path in project.root.iterdir()} != {
        "project.json",
        "knowledge",
        "repositories",
        "requirements",
        "specs",
    }:
        raise ProjectRetirementRejected("项目包含未识别的顶层事实, 不能按空项目退休")
    if any(
        not path.is_dir() or not path.name.startswith("repository_")
        for path in (project.root / "repositories").iterdir()
    ):
        raise ProjectRetirementRejected("项目包含未识别的仓库事实, 不能按空项目退休")
    for repository in project.repository_registry().discover():
        if {path.name for path in repository.root.iterdir()} != {
            "workspace.json",
            *WORKSPACE_DIRECTORIES,
        }:
            raise ProjectRetirementRejected("仓库包含未识别的事实, 不能按空项目退休")
        for name in execution_directories:
            allowed = preinitialized_empty_children.get(name, frozenset())
            for path in repository.directory(name).iterdir():
                if (
                    path.name not in allowed
                    or path.is_symlink()
                    or not path.is_dir()
                    or any(path.iterdir())
                ):
                    raise ProjectRetirementRejected("仓库保留执行或未知运行事实, 不支持空项目退休")
        if (
            Path(project.team.manifest.platform_root) / "worktrees" / repository.repository_id
        ).exists():
            raise ProjectRetirementRejected("项目仓库存在角色 worktree, 保留现场并拒绝退休")


def _publish(team: TeamWorkspace, receipt: ProjectRetirementReceipt) -> None:
    from ai_software_engineer.project_workspace import _sync_directory

    root = _receipt_root(team)
    path = root / f"{receipt.project_manifest.project_id}.json"
    payload = receipt.model_dump_json(indent=2).encode()
    if len(payload) > _MAX_RECEIPT_BYTES:
        raise ProjectRetirementRejected("项目退休记录超过读取预算, 未发布退休记录")
    descriptor, temporary = tempfile.mkstemp(prefix=".retirement-", dir=root)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path, follow_symlinks=False)
        _sync_directory(root)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _complete_archive(team: TeamWorkspace, receipt: ProjectRetirementReceipt) -> None:
    from ai_software_engineer.project_workspace import _sync_directory

    source = Path(receipt.project_manifest.project_root)
    archive = Path(receipt.archive_root)
    _safe(source)
    _safe(archive)
    if source.exists() and archive.exists():
        raise ProjectRetirementRejected("原项目和归档同时存在, 保留现场并拒绝猜测")
    if source.exists():
        if project_archive_inventory(source) != receipt.inventory:
            raise ProjectRetirementRejected("原项目内容已偏离精确退休记录, 保留现场")
        archive.parent.mkdir(exist_ok=True)
        source.rename(archive)
        _sync_directory(source.parent)
        _sync_directory(archive.parent)
    if not archive.is_dir() or project_archive_inventory(archive) != receipt.inventory:
        raise ProjectRetirementRejected("项目归档缺失或完整性不一致, 退休记录仍保留")


def retire_empty_project(
    team: TeamWorkspace,
    command: RetireEmptyProject,
    *,
    principal: LocalOperatorPrincipal,
    guard: ProjectRetirementGuard,
) -> ProjectRetirementReceipt:
    principal.require_duty(OperatorDuty.PRODUCT)
    with project_catalog_lock(team):
        prior = read_project_retirement(team, command.project_id)
        if prior is not None:
            if (
                prior.project_manifest.manifest_sha256 != command.expected_manifest_sha256
                or prior.principal != principal
                or prior.reason != command.reason
                or prior.retired_at != command.submitted_at
            ):
                raise ProjectRetirementRejected("项目退休重放必须匹配原精确命令和可信主体")
            project = ProjectWorkspace(team, prior.project_manifest)
            with guard.protect(project):
                _complete_archive(team, prior)
            return prior
        project = team.project_registry().open(command.project_id)
        if project.manifest.manifest_sha256 != command.expected_manifest_sha256:
            raise ProjectRetirementRejected("项目 manifest 已变化, 请重新核验精确身份")
        archive = _archive_root(team, command.project_id)
        _safe(archive)
        if archive.exists() or (archive.parent.exists() and not archive.parent.is_dir()):
            raise ProjectRetirementRejected("项目归档位置已有内容或不是目录, 未发布退休记录")
        with guard.protect(project):
            _require_empty_project(project)
            inventory = project_archive_inventory(project.root)
            provisional = ProjectRetirementReceipt(
                team_id=team.manifest.team_id,
                team_manifest_sha256=team.manifest.manifest_sha256,
                project_manifest=project.manifest,
                principal=principal,
                reason=command.reason,
                retired_at=command.submitted_at,
                archive_root=str(_archive_root(team, command.project_id)),
                inventory=inventory,
                inventory_sha256=_inventory_digest(inventory),
                retirement_sha256="0" * 64,
            )
            receipt = provisional.model_copy(
                update={"retirement_sha256": _digest(provisional, "retirement_sha256")}
            )
            _require_empty_project(project)
            if project_archive_inventory(project.root) != inventory:
                raise ProjectRetirementRejected("项目事实在授权期间变化, 未写入退休记录")
            _publish(team, receipt)
            _complete_archive(team, receipt)
            return receipt
