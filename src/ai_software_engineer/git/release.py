"""Full private worktree preservation before an explicitly requested resource release."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import tarfile
import tempfile
from pathlib import Path
from typing import IO, TYPE_CHECKING, Literal, Self

from pydantic import Field, model_validator

from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.git.ports import WorktreeRef
from ai_software_engineer.safe_files import _read_regular, _reject_symlinks

if TYPE_CHECKING:
    from ai_software_engineer.git.worktree import GitWorktreeManager

_MAX_RECORD_BYTES = 32 * 1024 * 1024
_MAX_FILES = 100_000
_MAX_BYTES = 2 * 1024 * 1024 * 1024


class WorktreeReleaseRejected(ValueError):
    """No resource is removed when its saved original cannot be proven."""


class ArchivedEntry(DomainModel):
    path: str
    kind: Literal["file", "directory", "symlink"]
    mode: int = Field(ge=0, le=0o7777)
    byte_count: int = Field(ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    link_target: str | None = None


class ArchivedIndexObject(DomainModel):
    object_id: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    byte_count: int = Field(ge=0, le=32 * 1024 * 1024)


class _WorktreeReleaseArchiveContent(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    owner_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    repository_root: str
    worktree_path: str
    task_id: TaskId
    role: Literal["coder", "qa", "reviewer"]
    attempt: int = Field(ge=1, le=400)
    head_revision: str = Field(pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")
    branch: str | None
    entries: tuple[ArchivedEntry, ...] = Field(max_length=_MAX_FILES)
    index_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    index_objects: tuple[ArchivedIndexObject, ...] = Field(max_length=_MAX_FILES)
    archive_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    retained_ref: str = Field(pattern=r"^refs/ase/retained/[a-f0-9]{64}/[a-f0-9]{64}$")


class WorktreeReleaseArchive(_WorktreeReleaseArchiveContent):
    record_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    def recompute_digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json", exclude={"record_sha256"}),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    @model_validator(mode="after")
    def validate_integrity(self) -> Self:
        if self.record_sha256 != self.recompute_digest():
            raise ValueError("worktree resource archive digest differs")
        return self

    @classmethod
    def seal(cls, **values: object) -> WorktreeReleaseArchive:
        content = _WorktreeReleaseArchiveContent.model_validate(values)
        payload = content.model_dump(mode="json")
        payload["record_sha256"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return cls.model_validate(payload)


def _stream_sha(stream: IO[bytes]) -> str:
    value = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        value.update(chunk)
    return value.hexdigest()


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return _stream_sha(stream)


def _inventory(root: Path) -> tuple[ArchivedEntry, ...]:
    entries = []
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted((*dirs, *files)):
            path = Path(directory) / name
            info = path.lstat()
            relative = path.relative_to(root).as_posix()
            if relative in {"saved-git-index", "saved-index-objects"} or (
                relative != ".git" and (name == ".git" or path.name == ".gitmodules")
            ):
                raise WorktreeReleaseRejected("嵌套 Git 工作区须人工保全, 暂未释放。")
            values = {"path": relative, "mode": stat.S_IMODE(info.st_mode), "byte_count": 0}
            if stat.S_ISLNK(info.st_mode):
                entry = ArchivedEntry.model_validate(
                    {**values, "kind": "symlink", "link_target": os.readlink(path)}
                )
            elif stat.S_ISDIR(info.st_mode):
                entry = ArchivedEntry.model_validate({**values, "kind": "directory"})
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
                if total > _MAX_BYTES:
                    raise WorktreeReleaseRejected("工作区超出完整保全大小限制, 原文件仍保留。")
                entry = ArchivedEntry.model_validate(
                    {**values, "byte_count": info.st_size, "kind": "file", "sha256": _sha(path)}
                )
            else:
                raise WorktreeReleaseRejected("工作区含无法完整保全的特殊文件, 原文件仍保留。")
            entries.append(entry)
            if len(entries) > _MAX_FILES:
                raise WorktreeReleaseRejected("工作区超出完整保全文件限制, 原文件仍保留。")
    return tuple(sorted(entries, key=lambda entry: entry.path))


def _publish(path: Path, body: bytes) -> None:
    if len(body) > _MAX_RECORD_BYTES:
        raise WorktreeReleaseRejected("资源保全记录超过大小限制, 原文件仍保留。")
    _reject_symlinks(path)
    if path.exists():
        if _read_regular(path, _MAX_RECORD_BYTES) != body:
            raise WorktreeReleaseRejected("资源释放记录与原保全不同。")
        return
    fd, name = tempfile.mkstemp(prefix=".release-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, path)
        _sync(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def _sync(root: Path) -> None:
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _verify_archive(path: Path, manifest: WorktreeReleaseArchive) -> None:
    if _sha(path) != manifest.archive_sha256:
        raise WorktreeReleaseRejected("工作区保全压缩包校验失败, 原文件仍保留。")
    with tarfile.open(path, "r:gz") as archive:
        members = {member.name: member for member in archive.getmembers()}
        if set(members) != (
            {entry.path for entry in manifest.entries}
            | {"saved-git-index"}
            | {"saved-index-objects/" + item.object_id for item in manifest.index_objects}
        ):
            raise WorktreeReleaseRejected("工作区保全内容不完整。")
        for entry in manifest.entries:
            member = members[entry.path]
            if member.mode != entry.mode:
                raise WorktreeReleaseRejected("工作区保全权限不同。")
            if entry.kind == "file":
                stream = archive.extractfile(member)
                if stream is None or not member.isfile() or member.size != entry.byte_count:
                    raise WorktreeReleaseRejected("工作区保全文件不同。")
                with stream:
                    actual_sha = _stream_sha(stream)
                if actual_sha != entry.sha256:
                    raise WorktreeReleaseRejected("工作区保全文件摘要不同。")
            elif entry.kind == "symlink":
                if not member.issym() or member.linkname != entry.link_target:
                    raise WorktreeReleaseRejected("工作区保全链接不同。")
            elif not member.isdir():
                raise WorktreeReleaseRejected("工作区保全目录不同。")
        stream = archive.extractfile(members["saved-git-index"])
        if stream is None or hashlib.sha256(stream.read()).hexdigest() != manifest.index_sha256:
            raise WorktreeReleaseRejected("工作区 Git index 保全校验失败。")
        for item in manifest.index_objects:
            stream = archive.extractfile(members["saved-index-objects/" + item.object_id])
            if stream is None or _stream_sha(stream) != item.sha256:
                raise WorktreeReleaseRejected("工作区 Git 暂存对象保全校验失败。")


def _index_objects(manager: GitWorktreeManager, root: Path) -> tuple[ArchivedIndexObject, ...]:
    raw = manager._run_git_bytes(("ls-files", "--stage", "-z"), cwd=root)
    identities = set()
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        fields = entry.split(b"\t", 1)[0].split()
        if len(fields) != 3 or fields[0] == b"160000":
            raise WorktreeReleaseRejected("嵌套 Git 或暂存身份无法完整保全。")
        identities.add(fields[1].decode("ascii"))
    if len(identities) > _MAX_FILES:
        raise WorktreeReleaseRejected("Git 暂存对象超过完整保全上限。")
    objects = []
    total = 0
    for identity in sorted(identities):
        size = int(manager._run_git(("cat-file", "-s", identity), cwd=root))
        total += size
        if size > 32 * 1024 * 1024 or total > _MAX_BYTES:
            raise WorktreeReleaseRejected("Git 暂存对象超过完整保全上限。")
        body = manager._run_git_bytes(("cat-file", "blob", identity), cwd=root)
        objects.append(
            ArchivedIndexObject(
                object_id=identity, byte_count=len(body), sha256=hashlib.sha256(body).hexdigest()
            )
        )
    return tuple(objects)


def _verify_reset_image(
    manager: GitWorktreeManager,
    root: Path,
    manifest: WorktreeReleaseArchive,
    inventory: tuple[ArchivedEntry, ...],
) -> None:
    flags = manager._run_git_bytes(("ls-files", "-v", "-z"), cwd=root)
    if any(entry and entry[:1] != b"H" for entry in flags.split(b"\0")):
        raise WorktreeReleaseRejected("资源释放期间 Git index flags 已变化, 原文件仍保留。")
    expected: dict[str, tuple[str, str]] = {}
    for value in manager._run_git_bytes(("ls-tree", "-r", "-z", "HEAD"), cwd=root).split(b"\0"):
        if not value:
            continue
        header, raw_path = value.split(b"\t", 1)
        mode, kind, identity = header.decode("ascii").split()
        if kind != "blob" or mode not in {"100644", "100755", "120000"}:
            raise WorktreeReleaseRejected("工作区 HEAD 类型无法核验, 原文件仍保留。")
        expected[raw_path.decode("utf-8")] = (mode, identity)
    actual_index = {}
    for value in manager._run_git_bytes(("ls-files", "--stage", "-z"), cwd=root).split(b"\0"):
        if value:
            header, raw_path = value.split(b"\t", 1)
            mode, identity, stage = header.decode("ascii").split()
            if stage != "0":
                raise WorktreeReleaseRejected("资源释放期间 Git 暂存区已变化, 原文件仍保留。")
            actual_index[raw_path.decode("utf-8")] = (mode, identity)
    if actual_index != expected:
        raise WorktreeReleaseRejected("资源释放期间 Git 暂存区已变化, 原文件仍保留。")
    current = {entry.path: entry for entry in inventory}
    for path, (mode, identity) in expected.items():
        entry = current.get(path)
        body = manager._run_git_bytes(("cat-file", "blob", identity), cwd=root)
        if (
            entry is None
            or (
                mode == "120000"
                and (entry.kind != "symlink" or entry.link_target != body.decode("utf-8"))
            )
            or (
                mode != "120000"
                and (
                    entry.kind != "file"
                    or entry.sha256 != hashlib.sha256(body).hexdigest()
                    or bool(entry.mode & 0o111) != (mode == "100755")
                )
            )
        ):
            raise WorktreeReleaseRejected("资源释放期间出现未保全的修改, 原文件仍保留。")
    original = {entry.path: entry for entry in manifest.entries}
    tracked_directories = {
        str(parent) for path in expected for parent in Path(path).parents if str(parent) != "."
    }
    if any(
        entry.path not in expected
        and original.get(entry.path) != entry
        and not (entry.kind == "directory" and entry.path in tracked_directories)
        for entry in inventory
    ):
        raise WorktreeReleaseRejected("资源释放期间出现新文件, 原文件仍保留。")


def archive_and_remove(
    manager: GitWorktreeManager, worktree: WorktreeRef, *, archive_root: Path, owner_sha256: str
) -> WorktreeReleaseArchive:
    """Caller owns the Requirement and every Task process lock and proves no live Lease."""
    _reject_symlinks(archive_root)
    archive_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    identity = hashlib.sha256(str(worktree.path).encode()).hexdigest()
    root = archive_root / identity
    _reject_symlinks(root)
    root.mkdir(exist_ok=True, mode=0o700)
    retained_ref = "refs/ase/retained/" + owner_sha256 + "/" + identity
    manifest_path, archive_path = root / "archive.json", root / "worktree.tar.gz"
    _reject_symlinks(manifest_path)
    _reject_symlinks(archive_path)
    if manifest_path.exists():
        manifest = WorktreeReleaseArchive.model_validate_json(
            _read_regular(manifest_path, _MAX_RECORD_BYTES)
        )
        if (
            manifest.owner_sha256,
            manifest.repository_root,
            manifest.worktree_path,
            manifest.task_id,
            manifest.role,
            manifest.attempt,
            manifest.head_revision,
            manifest.branch,
            manifest.retained_ref,
        ) != (
            owner_sha256,
            str(manager._repository),
            str(worktree.path),
            worktree.task_id,
            worktree.role.value,
            worktree.attempt,
            worktree.head_revision,
            worktree.branch,
            retained_ref,
        ):
            raise WorktreeReleaseRejected("资源保全归属已变化。")
        # DELETE may follow a CLOSED checkpoint. Original CLOSE archive remains immutable.
        _verify_archive(archive_path, manifest)
        if not worktree.path.exists():
            if (
                _read_regular(root / "release-intent.json", _MAX_RECORD_BYTES)
                != manifest.model_dump_json().encode()
                or manager._run_git(("rev-parse", retained_ref), cwd=manager._repository)
                != manifest.head_revision
            ):
                raise WorktreeReleaseRejected("缺失工作区的释放依据无法核验。")
            _publish(root / "released.json", manifest.model_dump_json().encode())
            return manifest
    else:
        manager._validate_owned_worktree(worktree)
        if manager._run_git(("rev-parse", "--shared-index-path"), cwd=worktree.path):
            raise WorktreeReleaseRejected(
                "split-index 工作区须先完整保全其共享 index, 原文件仍保留。"
            )
        entries = _inventory(worktree.path)
        index = Path(
            manager._run_git(
                ("rev-parse", "--path-format=absolute", "--git-path", "index"), cwd=worktree.path
            )
        )
        _reject_symlinks(index)
        index_sha = _sha(index)
        index_objects = _index_objects(manager, worktree.path)
        fd, name = tempfile.mkstemp(prefix=".archive-", dir=root)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                with tarfile.open(fileobj=stream, mode="w:gz", dereference=False) as archive:
                    for entry in entries:
                        member = tarfile.TarInfo(entry.path)
                        member.mode = entry.mode
                        if entry.kind == "file":
                            member.size = entry.byte_count
                            with (worktree.path / entry.path).open("rb") as content:
                                archive.addfile(member, content)
                        elif entry.kind == "symlink":
                            member.type = tarfile.SYMTYPE
                            member.linkname = entry.link_target or ""
                            archive.addfile(member)
                        else:
                            member.type = tarfile.DIRTYPE
                            archive.addfile(member)
                    archive.add(index, arcname="saved-git-index", recursive=False)
                    for item in index_objects:
                        body = manager._run_git_bytes(
                            ("cat-file", "blob", item.object_id), cwd=worktree.path
                        )
                        if hashlib.sha256(body).hexdigest() != item.sha256:
                            raise WorktreeReleaseRejected("Git 暂存对象保全期间已变化。")
                        member = tarfile.TarInfo("saved-index-objects/" + item.object_id)
                        member.mode, member.size = 0o600, len(body)
                        archive.addfile(member, io.BytesIO(body))
                stream.flush()
                os.fsync(stream.fileno())
            manifest = WorktreeReleaseArchive.seal(
                owner_sha256=owner_sha256,
                repository_root=str(manager._repository),
                worktree_path=str(worktree.path),
                task_id=worktree.task_id,
                role=worktree.role.value,
                attempt=worktree.attempt,
                head_revision=worktree.head_revision,
                branch=worktree.branch,
                entries=entries,
                index_sha256=index_sha,
                index_objects=index_objects,
                archive_sha256=_sha(temporary),
                retained_ref=retained_ref,
            )
            if len(manifest.model_dump_json().encode()) > _MAX_RECORD_BYTES:
                raise WorktreeReleaseRejected("资源保全记录超过大小限制, 原文件仍保留。")
            _verify_archive(temporary, manifest)
            if _inventory(worktree.path) != entries or _sha(index) != index_sha:
                raise WorktreeReleaseRejected("保全过程中工作区已变化, 暂未释放。")
            if archive_path.exists():
                # Retain an interrupted unsealed copy, then publish a freshly
                # verified full archive while the original worktree still exists.
                previous = root / ("unsealed-" + _sha(archive_path) + ".tar.gz")
                _reject_symlinks(previous)
                if previous.exists():
                    if _sha(previous) != _sha(archive_path):
                        raise WorktreeReleaseRejected("未封存保全归属不同, 原文件仍保留。")
                    archive_path.unlink()
                else:
                    archive_path.rename(previous)
                _sync(root)
            os.link(temporary, archive_path)
            _sync(root)
            _publish(manifest_path, manifest.model_dump_json().encode())
        finally:
            temporary.unlink(missing_ok=True)
    manager._validate_owned_worktree(worktree)
    if manager.inspect(worktree).head_revision != manifest.head_revision:
        raise WorktreeReleaseRejected("资源释放前工作区 HEAD 已变化。")
    inventory = _inventory(worktree.path)
    intent = root / "release-intent.json"
    index = Path(
        manager._run_git(
            ("rev-parse", "--path-format=absolute", "--git-path", "index"), cwd=worktree.path
        )
    )
    _reject_symlinks(index)
    if inventory != manifest.entries or _sha(index) != manifest.index_sha256:
        # Normal reset can change only the index (staged-only edits). Verify the
        # actual HEAD bytes as well as the index; Git diff alone trusts hidden flags.
        if (
            not intent.exists()
            or _read_regular(intent, _MAX_RECORD_BYTES) != manifest.model_dump_json().encode()
        ):
            raise WorktreeReleaseRejected("资源释放前工作区已变化, 原文件仍保留。")
        _verify_reset_image(manager, worktree.path, manifest, inventory)
    # Keep detached candidate commits and their complete ancestry reachable after GC.
    existing = manager._run_git(
        ("for-each-ref", "--format=%(objectname)", retained_ref), cwd=manager._repository
    )
    if existing and existing != manifest.head_revision:
        raise WorktreeReleaseRejected("成果保留引用已变化, 原文件仍保留。")
    if not existing:
        manager._run_git(
            ("update-ref", retained_ref, manifest.head_revision, "0" * len(manifest.head_revision)),
            cwd=manager._repository,
        )
    _publish(intent, manifest.model_dump_json().encode())
    # Explicit product withdrawal permits removing the saved draft, never the branch.
    manager._validate_repository_filters()
    manager._run_git(("reset", "--hard", manifest.head_revision), cwd=worktree.path)
    manager._run_git(("clean", "-fdx"), cwd=worktree.path)
    manager.remove(worktree)
    _publish(root / "released.json", manifest.model_dump_json().encode())
    return manifest
