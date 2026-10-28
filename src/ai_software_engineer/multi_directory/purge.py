"""Scope-exact, restartable physical deletion after verified execution stop."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
from typing import Literal

from pydantic import Field, TypeAdapter
from pymysql.cursors import DictCursor

from ai_software_engineer.domain.model import DomainModel, WirePayload
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId, Sha256
from ai_software_engineer.multi_directory.models import JointCheckpoint
from ai_software_engineer.multi_directory.purge_git import (
    PurgeGitRef,
    collect_git_resources,
    delete_git_refs,
    verify_git_refs,
)
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.safe_files import _read_regular, _reject_symlinks
from ai_software_engineer.store.mysql_repository import open_mysql_connection

_MAX_FILE = 64 * 1024 * 1024
_MAX_PLAN = 32 * 1024 * 1024
_MAX_PURGE_FILE = 2 * 1024 * 1024 * 1024 + 128 * 1024 * 1024
type PurgeScope = Literal["project", "operations", "preparations", "worktrees", "team-records"]
_OWNER_KEYS = frozenset(
    {
        "task_id",
        "source_task_id",
        "execution_task_id",
        "delivery_id",
        "parent_delivery_id",
        "source_delivery_id",
        "request_id",
        "requirement_id",
    }
)
_RUN_KEYS = frozenset(
    {"run_id", "context_id", "context_manifest_id", "case_id", "evidence_id", "artifact_id"}
)
# Exact table names, never supplied by a client or inferred from arbitrary SQL.
_TABLE_KEYS: Mapping[str, tuple[str, ...]] = {
    "work_queue_events": ("sequence",),
    "work_queue_claims": ("lease_id",),
    "work_queue_items": ("id",),
    "work_queue_admissions": ("id",),
    "work_queue_steps": ("id",),
    "work_queue_accepted_artifacts": ("id",),
    "work_queue_execution_baselines": ("id",),
    "work_queue_baseline_releases": ("id",),
    "dispatch_commits": ("id",),
    "dispatch_workforce_snapshots": ("repository_id", "task_id"),
    "verification_reservations": ("plan_sha256",),
    "state_events": ("event_id",),
    "manager_coordination_records": ("team_id", "namespace", "record_key"),
    "tasks": ("id",),
    "work_queue_events_legacy_project_v01": ("sequence",),
    "work_queue_claims_legacy_project_v01": ("lease_id",),
    "work_queue_items_legacy_project_v01": ("id",),
    "dispatch_commits_legacy_project_v01": ("id",),
    "dispatch_workforce_snapshots_legacy_project_v01": ("project_id", "task_id"),
}


class RequirementPurgeRejected(ValueError):
    """Deletion did not finish; retain the exact technical plan for retry."""


class PurgeFile(DomainModel):
    scope: PurgeScope
    path: str
    sha256: Sha256
    size: int = Field(ge=0, le=_MAX_PURGE_FILE)


class PurgeRow(DomainModel):
    table: str
    key: WirePayload
    sha256: Sha256


class RequirementPurgePlan(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    team_id: str
    team_manifest_sha256: Sha256
    project_id: str
    project_manifest_sha256: Sha256
    delivery_id: DeliveryId
    checkpoint_sha256: Sha256
    native_delivery_ids: tuple[DeliveryId, ...] = Field(max_length=1024)
    native_repositories: WirePayload
    task_ids: tuple[str, ...]
    task_repositories: WirePayload
    files: tuple[PurgeFile, ...] = Field(max_length=100_000)
    directories: tuple[tuple[PurgeScope, str], ...]
    rows: tuple[PurgeRow, ...] = Field(max_length=100_000)
    git_refs: tuple[PurgeGitRef, ...] = ()
    plan_sha256: Sha256

    def validate_integrity(self) -> None:
        if self.plan_sha256 != _digest(self.model_dump(mode="json", exclude={"plan_sha256"})):
            raise RequirementPurgeRejected("需求清理计划校验失败, 原资源保留。")


class RequirementPurgeCompletion(DomainModel):
    """Body-free revocation; no product/plan/artifact/log or SQL payload is retained."""

    schema_version: Literal["v0.1"] = "v0.1"
    team_id: str
    team_manifest_sha256: Sha256
    project_id: str
    project_manifest_sha256: Sha256
    delivery_id: DeliveryId
    checkpoint_sha256: Sha256
    native_delivery_ids: tuple[DeliveryId, ...] = Field(max_length=1024)
    plan_sha256: Sha256
    completion_sha256: Sha256

    def validate_integrity(self) -> None:
        if self.completion_sha256 != _digest(
            self.model_dump(mode="json", exclude={"completion_sha256"})
        ):
            raise RequirementPurgeRejected("需求删除标记校验失败。")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _references(payload: WirePayload) -> set[str]:
    record = payload
    for envelope in ("record", "event", "artifact", "bundle"):
        nested = payload.get(envelope)
        if isinstance(nested, dict):
            record = nested
            break
    result = {value for key, value in record.items() if key in _RUN_KEYS and isinstance(value, str)}
    identity = record.get("identity")
    if isinstance(identity, dict):
        result.update(
            value for key, value in identity.items() if key in _RUN_KEYS and isinstance(value, str)
        )
    return result


def _owners(payload: WirePayload) -> set[str]:
    # Ownership follows declared envelope/identity/scope positions, never nested
    # descriptions, evidence references or model output containing another ID.
    record = payload
    for envelope in ("record", "event", "artifact", "bundle"):
        nested = payload.get(envelope)
        if isinstance(nested, dict):
            record = nested
            break
    result = {item for key, item in record.items() if key in _OWNER_KEYS and isinstance(item, str)}
    for envelope, keys in (
        ("identity", _OWNER_KEYS),
        ("scope", _OWNER_KEYS),
        ("binding", _OWNER_KEYS),
        ("previous_binding", _OWNER_KEYS),
        ("new_binding", _OWNER_KEYS),
    ):
        nested = record.get(envelope)
        if isinstance(nested, dict):
            result.update(
                item for key, item in nested.items() if key in keys and isinstance(item, str)
            )
    if record.get("kind") == "rejected_coder_output_checkpoint":
        capture = record.get("capture")
        if isinstance(capture, dict):
            task_id = capture.get("task_id")
            if isinstance(task_id, str):
                result.add(task_id)
    if record.get("kind") in {
        "stopped_failure_budget_settlement",
        "stopped_unknown_budget_settlement",
        "contained_unknown_budget_settlement",
    }:
        task = record.get("task")
        task_id = task.get("id") if isinstance(task, dict) else None
        if isinstance(task_id, str):
            result.add(task_id)
    intent = record.get("intent")
    if record.get("kind") == "knowledge_invocation_outcome" and isinstance(intent, dict):
        result.update(_owners(intent))
    return result


def _file_sha(path: Path) -> tuple[int, str]:
    _reject_symlinks(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_PURGE_FILE:
            raise RequirementPurgeRejected("需求清理文件类型或大小不合法。")
        digest = hashlib.sha256()
        size = 0
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > _MAX_PURGE_FILE:
                raise RequirementPurgeRejected("需求文件超出清理容量。")
            digest.update(chunk)
        return size, digest.hexdigest()


@contextmanager
def _deletion_lock(path: Path) -> Iterator[None]:
    _reject_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RequirementPurgeRejected("需求数据正在清理, 请等待完成。") from error
        yield
    finally:
        os.close(fd)


@contextmanager
def _parent_fd(base: Path, relative: str) -> Iterator[tuple[int, str]]:
    _reject_symlinks(base)
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or ".." in parts:
        raise RequirementPurgeRejected("需求清理路径超出范围。")
    with ExitStack() as stack:
        fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, fd)
        for part in parts[:-1]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            stack.callback(os.close, fd)
        yield fd, parts[-1]


def _unlink_sealed(base: Path, item: PurgeFile) -> None:
    try:
        with _parent_fd(base, item.path) as (parent, name):
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            except FileNotFoundError:
                return
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise RequirementPurgeRejected("需求清理文件类型不合法。")
                digest = hashlib.sha256()
                size = 0
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > item.size:
                        raise RequirementPurgeRejected("需求文件已变化, 清理被拒绝。")
                    digest.update(chunk)
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if (
                    size != item.size
                    or info.st_size != item.size
                    or digest.hexdigest() != item.sha256
                    or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)
                ):
                    raise RequirementPurgeRejected("需求文件已变化, 清理被拒绝。")
                os.unlink(name, dir_fd=parent)
                os.fsync(parent)
    except FileNotFoundError:
        return


def _rmdir_sealed(base: Path, relative: str) -> None:
    try:
        with _parent_fd(base, relative) as (parent, name):
            if not stat.S_ISDIR(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode):
                raise RequirementPurgeRejected("需求清理目录类型不合法。")
            os.rmdir(name, dir_fd=parent)
            os.fsync(parent)
    except FileNotFoundError:
        return


def _wire(data: bytes) -> WirePayload:
    return TypeAdapter(WirePayload).validate_json(data)


def _publish(path: Path, record: DomainModel) -> None:
    _reject_symlinks(path)
    payload = record.model_dump_json(indent=2).encode()
    if len(payload) > _MAX_PLAN:
        raise RequirementPurgeRejected("需求清理计划超出容量。")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        if _read_regular(path, _MAX_PLAN) != payload:
            raise RequirementPurgeRejected("需求清理记录发生冲突。")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".purge-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if _read_regular(path, _MAX_PLAN) != payload:
                raise RequirementPurgeRejected("需求清理记录发生冲突。") from None
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        os.unlink(temporary)


def read_purge_completion(root: Path, delivery_id: str) -> RequirementPurgeCompletion | None:
    TypeAdapter(DeliveryId).validate_python(delivery_id)
    path = root / "purged" / (delivery_id + ".json")
    _reject_symlinks(path)
    if not path.exists():
        return None
    value = RequirementPurgeCompletion.model_validate_json(_read_regular(path, 256_000))
    value.validate_integrity()
    if value.delivery_id != delivery_id:
        raise RequirementPurgeRejected("需求删除标记身份不一致。")
    return value


class RequirementPurger:
    def __init__(self, project: ProjectWorkspace, dsn: str | None = None) -> None:
        self.project, self._dsn = project, dsn
        self.operations = project.team.directory("work-items") / "console-operations"

    def _root(self, scope: PurgeScope) -> Path:
        return {
            "project": self.project.root,
            "operations": self.operations,
            "preparations": self.project.team.directory("work-items")
            / "console-preparation-progress",
            "worktrees": Path(self.project.team.manifest.platform_root) / "worktrees",
            "team-records": self.project.team.directory("work-items"),
        }[scope]

    def plan_path(self, delivery_id: str) -> Path:
        TypeAdapter(DeliveryId).validate_python(delivery_id)
        return self.project.requirements_root / "purge-pending" / (delivery_id + ".json")

    def pending(self, delivery_id: str) -> RequirementPurgePlan | None:
        path = self.plan_path(delivery_id)
        _reject_symlinks(path)
        if not path.exists():
            return None
        plan = RequirementPurgePlan.model_validate_json(_read_regular(path, _MAX_PLAN))
        plan.validate_integrity()
        self._owner(plan)
        if plan.delivery_id != delivery_id:
            raise RequirementPurgeRejected("需求清理计划身份不一致。")
        return plan

    def finish_completed(self, completion: RequirementPurgeCompletion) -> None:
        """Remove a matching leftover inventory after the completion publication window."""
        self._owner(completion)
        completion.validate_integrity()
        with _deletion_lock(self.plan_path(completion.delivery_id).with_suffix(".lock")):
            pending = self.pending(completion.delivery_id)
            if pending is None:
                return
            if self._completion(pending) != completion:
                raise RequirementPurgeRejected("需求清理计划与完成标记不一致。")
            self.plan_path(completion.delivery_id).unlink()

    def _owner(self, plan: RequirementPurgePlan | RequirementPurgeCompletion) -> None:
        self.project.validate_current()
        if (
            plan.team_id,
            plan.team_manifest_sha256,
            plan.project_id,
            plan.project_manifest_sha256,
        ) != (
            self.project.team.manifest.team_id,
            self.project.team.manifest.manifest_sha256,
            self.project.manifest.project_id,
            self.project.manifest.manifest_sha256,
        ):
            raise RequirementPurgeRejected("需求清理计划不属于当前团队或项目。")
        if isinstance(plan, RequirementPurgePlan):
            repositories = {
                repo.repository_id for repo in self.project.repository_registry().discover()
            }
            allowed_sidecars = {
                "artifacts",
                "contexts",
                "evaluations",
                "handoffs",
                "evidence",
                "runs",
                "logs",
                "knowledge",
                "state",
                "native-role-verification",
            }
            for scope, relative in [(item.scope, item.path) for item in plan.files] + list(
                plan.directories
            ):
                parts = Path(relative).parts
                self._path(scope, relative)
                if scope == "project":
                    requirement = len(parts) >= 2 and parts[:2] == (
                        "requirements",
                        plan.delivery_id,
                    )
                    sidecar = (
                        len(parts) >= 3
                        and parts[0] == "repositories"
                        and parts[1] in repositories
                        and parts[2] in allowed_sidecars
                    )
                    if not (requirement or sidecar) or (
                        sidecar
                        and parts[2] == "knowledge"
                        and (len(parts) < 4 or parts[3] != "runs")
                    ):
                        raise RequirementPurgeRejected("需求清理计划包含未授权数据路径。")
                elif scope in {"operations", "preparations"}:
                    from ai_software_engineer.web_console.models import OperationId

                    TypeAdapter(OperationId).validate_python(parts[0])
                elif scope == "team-records":
                    if parts[0] == "manager-model-runs":
                        if len(parts) != 2 or not parts[1].startswith(
                            ("manager-start-", "manager-final-", "manager-context-")
                        ):
                            raise RequirementPurgeRejected("无关 Manager 文件路径。")
                        continue
                    from ai_software_engineer.knowledge.models import digest

                    keys = {
                        digest({"repository_id": repo_id, "task_id": task_id})
                        for task_id in plan.task_ids
                        for repo_id in repositories
                    }
                    if parts[0] not in keys:
                        raise RequirementPurgeRejected("需求清理计划包含无关团队执行记录。")
                elif not (
                    (len(parts) >= 2 and parts[0] in repositories and parts[1] in plan.task_ids)
                    or (len(parts) >= 2 and parts[:2] == ("requirements", plan.delivery_id))
                ):
                    raise RequirementPurgeRejected("需求清理计划包含无关工作区。")
            for row in plan.rows:
                if row.table not in _TABLE_KEYS or set(row.key) != set(_TABLE_KEYS[row.table]):
                    raise RequirementPurgeRejected("需求清理计划包含未授权 SQL 索引。")

    def _path(self, scope: PurgeScope, relative: str) -> Path:
        base = self._root(scope)
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            raise RequirementPurgeRejected("需求清理路径超出范围。")
        path = base / rel
        _reject_symlinks(path)
        return path

    def prepare(
        self,
        checkpoint: JointCheckpoint,
        targets: Mapping[str, tuple[Path, str]],
        *,
        native_ids: Mapping[str, str],
        persist: bool = True,
    ) -> RequirementPurgePlan:
        existing = self.pending(checkpoint.delivery_id)
        if existing is not None:
            if existing.checkpoint_sha256 != checkpoint.checkpoint_sha256:
                raise RequirementPurgeRejected("需求清理记录已变化。")
            return existing
        identities = {checkpoint.delivery_id, *native_ids, *targets}
        files: dict[tuple[str, str], PurgeFile] = {}
        directories: set[tuple[PurgeScope, str]] = set()

        def add(path: Path, scope: PurgeScope) -> None:
            base = self._root(scope)
            _reject_symlinks(path)
            if not path.exists():
                return
            if path.is_dir():
                directories.add((scope, path.relative_to(base).as_posix()))
                for item in sorted(path.iterdir()):
                    add(item, scope)
            else:
                size, sha256 = _file_sha(path)
                relative = path.relative_to(base).as_posix()
                files[(scope, relative)] = PurgeFile(
                    scope=scope, path=relative, size=size, sha256=sha256
                )

        add(self.project.requirements_root / checkpoint.delivery_id, "project")
        repositories = self.project.repository_registry().discover()
        # Only an exactly owned native journal or Task/run record selects sidecar files.
        for repo in repositories:
            for native_id in native_ids:
                native_path = repo.root / "state/project-deliveries" / native_id
                if native_ids[native_id] != repo.repository_id:
                    if native_path.exists() or native_path.is_symlink():
                        raise RequirementPurgeRejected("子交付被放置在其他仓库, 清理被拒绝。")
                    continue
                for path in (
                    repo.root / "state/project-deliveries" / native_id,
                    repo.root / "state/project-deliveries/intakes" / (native_id + ".json"),
                ):
                    add(path, "project")
                state = repo.root / "state"
                if state.exists():
                    for path in sorted(state.iterdir()):
                        if path.name in {
                            prefix + "-" + native_id
                            for prefix in ("recovery", "candidate-verification", "pre-execution")
                        }:
                            add(path, "project")
            from ai_software_engineer.multi_directory.purge_state import (
                StateDeletionScope,
                rejected_knowledge_files,
                task_state_directories,
                upstream_files,
            )

            owned_tasks = {
                task_id for task_id, (sidecar, _) in targets.items() if sidecar == repo.root
            }
            state_scope = StateDeletionScope(
                team_id=checkpoint.team_id,
                project_id=checkpoint.project_id,
                repository_id=repo.repository_id,
                repository_root=str(repo.repository_root),
                requirement_ids=frozenset({checkpoint.delivery_id, *native_ids}),
                task_ids=frozenset(owned_tasks),
            )
            for path in rejected_knowledge_files(repo.root, state_scope):
                add(path, "project")
            for directory in task_state_directories(repo.root, state_scope):
                add(directory, "project")
            for path in upstream_files(
                repo.root,
                {key for key, value in native_ids.items() if value == repo.repository_id},
                repo.repository_id,
            ):
                add(path, "project")
            from ai_software_engineer.domain.engineering_authority import EngineeringScope
            from ai_software_engineer.multi_directory.purge_resources import native_stores
            from ai_software_engineer.recovery.store import RecoveryRecordMissing

            for store in native_stores(
                repo.root,
                owned_tasks,
                EngineeringScope(
                    team_id=checkpoint.team_id,
                    project_id=checkpoint.project_id,
                    repository_id=repo.repository_id,
                    repository_root=str(repo.repository_root),
                ),
            ):
                for resource in store.list_mysql_resource_intents():
                    try:
                        store.get_mysql_resource(resource.intent.resource_id, "CLEANED")
                    except RecoveryRecordMissing as error:
                        raise RequirementPurgeRejected(
                            "原生验证的隔离数据库资源尚未清理。"
                        ) from error
                add(store.root.parent, "project")
            run_ids: set[str] = set()
            shared: list[Path] = []
            for name in (
                "artifacts",
                "contexts",
                "evaluations",
                "handoffs",
                "evidence",
                "runs",
                "logs",
                "state",
            ):
                base = repo.root / name
                _reject_symlinks(base)
                if not base.exists():
                    continue
                for path in _regular_files(base):
                    if ("project", path.relative_to(self.project.root).as_posix()) in files:
                        continue
                    if path.suffix != ".json":
                        shared.append(path)
                        continue
                    if path.is_relative_to(repo.root / "state/invocations") or path.is_relative_to(
                        repo.root / "state/external-test-maintenance"
                    ):
                        continue
                    payload = _wire(_read_regular(path, _MAX_FILE))
                    owners = _owners(payload)
                    if owners & identities:
                        from ai_software_engineer.multi_directory.purge_records import (
                            verified_record,
                        )

                        payload = verified_record(
                            path,
                            repo.root,
                            payload,
                            state_scope,
                        )
                        owners = _owners(payload)
                        if not owners & identities:
                            raise RequirementPurgeRejected("执行记录归属在正式校验后变化。")
                        if any(
                            task_id in owners and targets[task_id][0] != repo.root
                            for task_id in targets
                        ):
                            raise RequirementPurgeRejected("需求执行记录位于其他仓库, 清理被拒绝。")
                        add(path, "project")
                        if name == "handoffs":
                            add(path.with_suffix(".md"), "project")
                        run_ids.update(_references(payload))
            from ai_software_engineer.multi_directory.purge_knowledge import (
                select_delivery_invocations,
                select_knowledge,
            )

            task_repository_ids = {
                task_id: candidate.repository_id
                for task_id, (sidecar, _) in targets.items()
                for candidate in repositories
                if sidecar == candidate.root
            }
            for path in select_knowledge(
                repo.root / "knowledge/runs",
                checkpoint,
                identities=identities,
                task_repositories=task_repository_ids,
                repository_id=repo.repository_id,
            ):
                add(path, "project")
            for path in select_delivery_invocations(
                repo.root / "state/invocations",
                {key for key, value in task_repository_ids.items() if value == repo.repository_id},
            ):
                add(path, "project")
            for path in shared:
                # Plain runner logs are selected only by IDs from owned typed manifests.
                if path.suffix != ".json" and any(
                    part in identities | run_ids or Path(part).stem in identities | run_ids
                    for part in path.relative_to(repo.root).parts
                ):
                    add(path, "project")
        target_roots = {key: value[1] for key, value in targets.items()}
        git_refs, markers = collect_git_resources(self.project, checkpoint, target_roots, self._dsn)
        verify_git_refs(self.project, git_refs)
        for marker in markers:
            add(marker, "worktrees")
        for repo in repositories:
            for task_id, (sidecar, _) in targets.items():
                if sidecar != repo.root:
                    continue
                add(
                    repo.root
                    / "state/queue-worker-locks"
                    / (hashlib.sha256(task_id.encode()).hexdigest() + ".lock"),
                    "project",
                )
                directory = self._root("worktrees") / repo.repository_id / task_id
                if directory.exists():
                    directories.add(
                        ("worktrees", directory.relative_to(self._root("worktrees")).as_posix())
                    )
        baseline_root = self._root("worktrees") / "requirements" / checkpoint.delivery_id
        if baseline_root.exists():
            _reject_symlinks(baseline_root)
            for directory in (baseline_root, *baseline_root.rglob("*")):
                _reject_symlinks(directory)
                if directory.is_dir():
                    directories.add(
                        ("worktrees", directory.relative_to(self._root("worktrees")).as_posix())
                    )
        if self._dsn is not None and targets:
            from ai_software_engineer.knowledge.models import digest
            from ai_software_engineer.manager.engineering_authority import EngineeringAuthority
            from ai_software_engineer.recovery.models import RecoveryScope
            from ai_software_engineer.recovery.store import FileRecoveryStore
            from ai_software_engineer.store.mysql_repository import _decode_task

            with (
                closing(open_mysql_connection(self._dsn)) as ledger_connection,
                ledger_connection.cursor(DictCursor) as ledger_cursor,
            ):
                for repo in repositories:
                    for task_id, (sidecar, _) in targets.items():
                        if sidecar != repo.root:
                            continue
                        ledger = self._root("team-records") / digest(
                            {"repository_id": repo.repository_id, "task_id": task_id}
                        )
                        if not ledger.exists():
                            continue
                        scope_paths = (
                            (ledger / "scope.json",) if (ledger / "scope.json").exists() else ()
                        )
                        if len(scope_paths) != 1:
                            raise RequirementPurgeRejected("团队执行记录缺少完整归属。")
                        envelope = _wire(_read_regular(scope_paths[0], _MAX_FILE))
                        scope = RecoveryScope.model_validate(envelope.get("record"))
                        if (scope.team_id, scope.repository_id, scope.repository_root) != (
                            checkpoint.team_id,
                            repo.repository_id,
                            str(repo.repository_root),
                        ):
                            raise RequirementPurgeRejected("团队执行记录归属不一致。")
                        ledger_store = FileRecoveryStore(ledger, scope=scope)
                        ledger_cursor.execute(
                            "SELECT id,payload_json FROM tasks WHERE id=%s", (task_id,)
                        )
                        task_row = ledger_cursor.fetchone()
                        if task_row is None:
                            raise RequirementPurgeRejected("团队执行记录的任务不存在。")
                        task = _decode_task(task_id, str(task_row["payload_json"]))
                        if scope.delivery_id in native_ids:
                            if native_ids[scope.delivery_id] != repo.repository_id:
                                raise RequirementPurgeRejected(
                                    "团队执行记录的子交付仓库归属不一致。"
                                )
                        else:
                            from ai_software_engineer.domain.engineering_authority import (
                                EngineeringScope,
                            )
                            from ai_software_engineer.manager.delivery_wait import (
                                delivery_wait_recovery_scope,
                            )

                            expected_scope = delivery_wait_recovery_scope(
                                task,
                                EngineeringScope(
                                    team_id=checkpoint.team_id,
                                    project_id=checkpoint.project_id,
                                    repository_id=repo.repository_id,
                                    repository_root=str(repo.repository_root),
                                ),
                            )
                            if scope != expected_scope:
                                raise RequirementPurgeRejected(
                                    "团队执行记录的精确 Task 归属不一致。"
                                )
                        for admission in ledger_store.list_engineering_admissions():
                            EngineeringAuthority.validate(task=task, record=admission)
                        add(ledger, "team-records")
                    for task_id, (sidecar, _) in targets.items():
                        if sidecar != repo.root:
                            continue
                        local = repo.root / "state" / ("delivery-wait-authority-" + digest(task_id))
                        if not local.exists():
                            continue
                        from ai_software_engineer.domain.engineering_authority import (
                            EngineeringScope,
                        )
                        from ai_software_engineer.manager.delivery_wait import (
                            delivery_wait_recovery_scope,
                        )

                        ledger_cursor.execute(
                            "SELECT id,payload_json FROM tasks WHERE id=%s", (task_id,)
                        )
                        task_row = ledger_cursor.fetchone()
                        if task_row is None:
                            raise RequirementPurgeRejected("工程等待记录缺少原任务。")
                        task = _decode_task(task_id, str(task_row["payload_json"]))
                        expected_scope = delivery_wait_recovery_scope(
                            task,
                            EngineeringScope(
                                team_id=checkpoint.team_id,
                                project_id=checkpoint.project_id,
                                repository_id=repo.repository_id,
                                repository_root=str(repo.repository_root),
                            ),
                        )
                        local_store = FileRecoveryStore(local, scope=expected_scope)
                        for admission in local_store.list_engineering_admissions():
                            EngineeringAuthority.validate(task=task, record=admission)
                        add(local, "project")
        from ai_software_engineer.multi_directory.purge_resources import legacy_manager_files

        for path in legacy_manager_files(
            self._root("team-records") / "manager-model-runs",
            identities,
            checkpoint.team_id,
            checkpoint.project_id,
        ):
            add(path, "team-records")
        # Validate histories, including CREATE operations whose identity is in result.
        from ai_software_engineer.web_console.store import FileConsoleOperationStore
        from ai_software_engineer.web_console.summary_models import OperationSummary

        operation_store = FileConsoleOperationStore(
            self.operations, team_id=checkpoint.team_id, read_only=True
        )
        with operation_store._locked(shared=True):
            for operation in operation_store._list_current():
                summary = OperationSummary.from_operation(operation)
                if (
                    summary.project_id != checkpoint.project_id
                    or summary.delivery_id not in identities
                ):
                    continue
                if not operation.terminal:
                    if (
                        operation.intent.action == "DELETE_REQUIREMENT"
                        and operation.delivery_id == checkpoint.delivery_id
                    ):
                        continue  # Worker publishes its small completion, then removes itself.
                    raise RequirementPurgeRejected("需求仍有未结束的操作, 请停止后删除。")
                add(self.operations / operation.operation_id, "operations")
                add(self._root("preparations") / operation.operation_id, "preparations")
        rows: tuple[PurgeRow, ...] = ()
        if targets and self._dsn is None:
            raise RequirementPurgeRejected("需求执行数据缺少清理能力。")
        if self._dsn is not None:
            with (
                closing(open_mysql_connection(self._dsn)) as connection,
                connection.cursor(DictCursor) as cursor,
            ):
                cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                rows = self._rows(
                    cursor, identities, {key: value[1] for key, value in targets.items()}
                )
        values: dict[str, object] = dict(
            team_id=checkpoint.team_id,
            team_manifest_sha256=checkpoint.team_manifest_sha256,
            project_id=checkpoint.project_id,
            project_manifest_sha256=checkpoint.project_manifest_sha256,
            delivery_id=checkpoint.delivery_id,
            checkpoint_sha256=checkpoint.checkpoint_sha256,
            native_delivery_ids=tuple(sorted(native_ids)),
            native_repositories=dict(native_ids),
            task_ids=tuple(sorted(targets)),
            task_repositories={key: root for key, (_, root) in targets.items()},
            files=tuple(files[key] for key in sorted(files)),
            directories=tuple(sorted(directories)),
            rows=rows,
            git_refs=git_refs,
            plan_sha256="0" * 64,
        )
        plan = RequirementPurgePlan.model_validate(values)
        plan = plan.model_copy(
            update={"plan_sha256": _digest(plan.model_dump(mode="json", exclude={"plan_sha256"}))}
        )
        self._owner(plan)
        if len(plan.model_dump_json(indent=2).encode()) > _MAX_PLAN:
            raise RequirementPurgeRejected("需求清理范围过大。")
        if persist:
            _publish(self.plan_path(checkpoint.delivery_id), plan)
        return plan

    def _rows(
        self, cursor: DictCursor, identities: set[str], roots: Mapping[str, str]
    ) -> tuple[PurgeRow, ...]:
        cursor.execute(
            "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()"
        )
        available = {row["TABLE_NAME"] for row in cursor.fetchall()}
        result: list[PurgeRow] = []
        work_ids: dict[str, set[str]] = {}
        for table in ("work_queue_items", "work_queue_items_legacy_project_v01"):
            if table in available:
                cursor.execute(f"SELECT id,task_id FROM {table}")
                work_ids[table] = {
                    row["id"] for row in cursor.fetchall() if row["task_id"] in identities
                }
        from ai_software_engineer.multi_directory.purge_sql import manager_context_keys, verify_row

        repositories = {
            key: repo.repository_id
            for key, root in roots.items()
            for repo in self.project.repository_registry().discover()
            if str(repo.repository_root) == root
        }
        manager_contexts: set[str] = set()
        if "manager_coordination_records" in available:
            cursor.execute("SELECT * FROM manager_coordination_records")
            manager_contexts = manager_context_keys(
                list(cursor.fetchall()),
                identities,
                self.project.team.manifest.team_id,
                self.project.manifest.project_id,
            )
        for table, keys in _TABLE_KEYS.items():
            if table not in available:
                continue
            cursor.execute(f"SELECT * FROM {table}")
            for row in cursor.fetchall():
                raw = row.get("payload_json")
                payload = _wire(raw.encode()) if isinstance(raw, str) else {}
                matched = (
                    row.get("task_id") in identities
                    or (table == "tasks" and row.get("id") in identities)
                    or row.get("work_item_id")
                    in work_ids.get(
                        "work_queue_items_legacy_project_v01"
                        if table.endswith("_legacy_project_v01")
                        else "work_queue_items",
                        set(),
                    )
                    or (
                        table == "manager_coordination_records"
                        and row.get("namespace") == "manager-context"
                        and row.get("record_key") in manager_contexts
                        and row.get("team_id") == self.project.team.manifest.team_id
                    )
                    or (
                        table in {"verification_reservations", "manager_coordination_records"}
                        and bool(_owners(payload) & identities)
                    )
                )
                if not matched:
                    continue
                if (
                    table == "manager_coordination_records"
                    and row["team_id"] != self.project.team.manifest.team_id
                ):
                    raise RequirementPurgeRejected("需求协调记录归属不一致。")
                verify_row(
                    table,
                    row,
                    roots=roots,
                    repositories=repositories,
                    team_id=self.project.team.manifest.team_id,
                    project_id=self.project.manifest.project_id,
                    identities=identities,
                )
                result.append(
                    PurgeRow(
                        table=table,
                        key=TypeAdapter(WirePayload).validate_python(
                            {key: row[key] for key in keys}
                        ),
                        sha256=_digest(row),
                    )
                )
        # FK children first; parents last, also for the legacy tables.
        order = {table: index for index, table in enumerate(_TABLE_KEYS)}
        return tuple(
            sorted(
                result,
                key=lambda item: (
                    item.table == "tasks",
                    item.table.startswith("work_queue_items"),
                    order[item.table],
                    repr(item.key),
                ),
            )
        )

    def execute(
        self, plan: RequirementPurgePlan, *, already_fenced: bool = False
    ) -> RequirementPurgeCompletion:
        self._owner(plan)
        plan.validate_integrity()
        with ExitStack() as stack:
            stack.enter_context(
                _deletion_lock(self.plan_path(plan.delivery_id).with_suffix(".lock"))
            )
            if self.pending(plan.delivery_id) != plan:
                completed = read_purge_completion(self.project.requirements_root, plan.delivery_id)
                if completed is not None and completed.plan_sha256 == plan.plan_sha256:
                    return completed
                raise RequirementPurgeRejected("需求清理计划已变化。")
            from ai_software_engineer.web_console.store import FileConsoleOperationStore

            operation_store = FileConsoleOperationStore(self.operations, team_id=plan.team_id)
            stack.enter_context(operation_store._locked())
            preparation_root = self._root("preparations")
            if preparation_root.exists():
                from ai_software_engineer.web_console.preparation_store import (
                    FilePreparationProgressStore,
                )

                stack.enter_context(
                    FilePreparationProgressStore(preparation_root)._locked(shared=False)
                )
            # Prebuild the exact bounded marker before irreversible deletion.
            completion = self._completion(plan)
            if len(completion.model_dump_json(indent=2).encode()) > 256_000:
                raise RequirementPurgeRejected("需求删除身份标记超出容量。")
            if not already_fenced:
                from ai_software_engineer.multi_directory.deletion import _task_lock

                repositories = {
                    str(repo.repository_root): repo
                    for repo in self.project.repository_registry().discover()
                }
                for task_id in plan.task_ids:
                    root = plan.task_repositories[task_id]
                    if not isinstance(root, str) or root not in repositories:
                        raise RequirementPurgeRejected("需求清理任务仓库归属不一致。")
                    stack.enter_context(
                        _task_lock(repositories[root].root / "state/queue-worker-locks", task_id)
                    )
            verify_git_refs(self.project, plan.git_refs)
            if plan.rows:
                if self._dsn is None:
                    raise RequirementPurgeRejected("需求清理数据库不可用。")
                connection = stack.enter_context(closing(open_mysql_connection(self._dsn)))
                cursor = stack.enter_context(connection.cursor(DictCursor))
                connection.begin()
                if not already_fenced:
                    cursor.execute("SELECT id FROM dispatch_authority_lock WHERE id=1 FOR UPDATE")
                    if cursor.fetchone() is None:
                        raise RequirementPurgeRejected("需求清理分配锁不可用。")
                cursor.execute("SELECT id FROM work_queue_authority_lock WHERE id=1 FOR UPDATE")
                if cursor.fetchone() is None:
                    raise RequirementPurgeRejected("需求清理队列锁不可用。")
                current_rows = self._rows(
                    cursor,
                    {plan.delivery_id, *plan.native_delivery_ids, *plan.task_ids},
                    TypeAdapter(dict[str, str]).validate_python(plan.task_repositories),
                )
                expected = {(row.table, repr(row.key)): row.sha256 for row in plan.rows}
                if any(
                    expected.get((row.table, repr(row.key))) != row.sha256 for row in current_rows
                ):
                    raise RequirementPurgeRejected("需求执行数据已变化, 清理被拒绝。")
                self._verify_files(plan)
                for row in current_rows:
                    keys = _TABLE_KEYS[row.table]
                    predicate = " AND ".join(key + "=%s" for key in keys)
                    cursor.execute(
                        f"DELETE FROM {row.table} WHERE {predicate}",
                        tuple(row.key[key] for key in keys),
                    )
                connection.commit()
            else:
                self._verify_files(plan)
            delete_git_refs(self.project, plan.git_refs)
            operation_store.remove_terminal_operations(
                {Path(item.path).parts[0] for item in plan.files if item.scope == "operations"}
            )
            # Parent journal is removed last. Each unlink rechecks its exact bytes.
            parent = "requirements/" + plan.delivery_id + "/"
            for item in sorted(
                plan.files,
                key=lambda value: value.scope == "project" and value.path.startswith(parent),
            ):
                base = self._root(item.scope)
                _unlink_sealed(base, item)
            for scope, relative in sorted(
                plan.directories, key=lambda item: len(Path(item[1]).parts), reverse=True
            ):
                base = self._root(scope)
                _rmdir_sealed(base, relative)  # New unsealed files make rmdir refuse.
            _publish(
                self.project.requirements_root / "purged" / (plan.delivery_id + ".json"), completion
            )
            self.plan_path(plan.delivery_id).unlink(missing_ok=True)
            return completion

    @staticmethod
    def _completion(plan: RequirementPurgePlan) -> RequirementPurgeCompletion:
        values = plan.model_dump(
            include={
                "team_id",
                "team_manifest_sha256",
                "project_id",
                "project_manifest_sha256",
                "delivery_id",
                "checkpoint_sha256",
                "native_delivery_ids",
                "plan_sha256",
            }
        )
        completion = RequirementPurgeCompletion.model_validate(
            {**values, "completion_sha256": "0" * 64}
        )
        return completion.model_copy(
            update={
                "completion_sha256": _digest(
                    completion.model_dump(mode="json", exclude={"completion_sha256"})
                )
            }
        )

    def _verify_files(self, plan: RequirementPurgePlan) -> None:
        expected = {(item.scope, item.path): item for item in plan.files}
        for item in plan.files:
            path = self._path(item.scope, item.path)
            if path.exists() and _file_sha(path) != (item.size, item.sha256):
                raise RequirementPurgeRejected("需求文件已变化, 清理被拒绝。")
        for scope, relative in plan.directories:
            directory = self._path(scope, relative)
            if directory.exists():
                base = self._root(scope)
                for path in _regular_files(directory):
                    if (scope, path.relative_to(base).as_posix()) not in expected:
                        raise RequirementPurgeRejected("需求新增文件不在清理计划中。")


def _regular_files(root: Path) -> Iterator[Path]:
    _reject_symlinks(root)
    for path in sorted(root.iterdir()):
        _reject_symlinks(path)
        if path.is_dir():
            yield from _regular_files(path)
        else:
            # Calling the bounded reader rejects FIFOs/devices before traversal.
            if not stat.S_ISREG(path.lstat().st_mode):
                raise RequirementPurgeRejected("需求清理目录含特殊文件。")
            yield path
