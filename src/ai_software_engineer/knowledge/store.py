"""Content-verified exclusive publication for knowledge run records."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from contextlib import suppress
from pathlib import Path

from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.knowledge.models import KnowledgeError, digest

_MAX_BYTES = 20_000_000


class KnowledgeRecordStore:
    """Application-owned store; Agents only receive registry operations.

    Every filename derives from a trusted namespace and hashed key. O_NOFOLLOW,
    directory FDs and inode checks prevent symlink substitution. Publication links a
    fully fsynced temporary inode exclusively, so concurrent changed replay cannot win.
    """

    def __init__(self, root: Path, *, read_only: bool = False) -> None:
        self.root = root.absolute()
        self._read_only = read_only
        self._check_ancestry()
        if not read_only:
            self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise KnowledgeError("STORE_PATH")
        info = self.root.stat()
        self._identity = (info.st_dev, info.st_ino)

    def _check_ancestry(self) -> None:
        if any(path.is_symlink() for path in (self.root, *self.root.parents)):
            raise KnowledgeError("STORE_PATH")

    def _open(self) -> int:
        self._check_ancestry()
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != self._identity:
            os.close(fd)
            raise KnowledgeError("STORE_ROOT_CHANGED")
        return fd

    @staticmethod
    def _name(namespace: str, key: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,40}", namespace):
            raise KnowledgeError("STORE_NAMESPACE")
        return f"{namespace}-{digest(key)}.json"

    def put[T: DomainModel](self, namespace: str, key: str, record: T) -> T:
        if self._read_only:
            raise KnowledgeError("STORE_READ_ONLY")
        name = self._name(namespace, key)
        wire = record.to_wire()
        payload = json.dumps(
            {"record": wire, "sha256": digest(wire)},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if len(payload) > _MAX_BYTES:
            raise KnowledgeError("STORE_LIMIT")
        fd = self._open()
        temporary = ".knowledge-" + secrets.token_hex(16)
        try:
            output = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
            )
            with os.fdopen(output, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
                os.fsync(fd)
            except FileExistsError:
                pass
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=fd)
            os.close(fd)
        found = self.get(namespace, key, type(record))
        if found != record:
            raise KnowledgeError("RECORD_CONFLICT")
        return found

    def get[T: DomainModel](self, namespace: str, key: str, model: type[T]) -> T:
        result = self.find(namespace, key, model)
        if result is None:
            raise KnowledgeError("RECORD_NOT_FOUND")
        return result

    def find[T: DomainModel](self, namespace: str, key: str, model: type[T]) -> T | None:
        return self._read_name(self._name(namespace, key), model)

    def _read_name[T: DomainModel](self, name: str, model: type[T]) -> T | None:
        fd = self._open()
        try:
            try:
                source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            except FileNotFoundError:
                return None
            with os.fdopen(source, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise KnowledgeError("STORE_PATH")
                payload = stream.read(_MAX_BYTES + 1)
            if len(payload) > _MAX_BYTES:
                raise KnowledgeError("STORE_LIMIT")
            envelope = json.loads(payload)
            if not isinstance(envelope, dict) or set(envelope) != {"record", "sha256"}:
                raise KnowledgeError("STORE_CORRUPT")
            if envelope["sha256"] != digest(envelope["record"]):
                raise KnowledgeError("STORE_CORRUPT")
            return model.model_validate(envelope["record"])
        except (OSError, ValueError) as error:
            raise KnowledgeError("STORE_CORRUPT") from error
        finally:
            os.close(fd)

    def list[T: DomainModel](self, namespace: str, model: type[T]) -> tuple[T, ...]:
        self._name(namespace, "")
        fd = self._open()
        try:
            names = sorted(
                name
                for name in os.listdir(fd)
                if name.startswith(namespace + "-") and name.endswith(".json")
            )
        finally:
            os.close(fd)
        return tuple(
            record for name in names if (record := self._read_name(name, model)) is not None
        )
