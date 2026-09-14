"""Immutable Team/Project engineering Specs and atomic activation records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, TypeAdapter, model_validator

from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.domain.identity import ProjectId, RepositoryId, TeamId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.team_workspace import TeamWorkspace

SpecDocumentId = Annotated[str, StringConstraints(pattern=r"^spec_document_[a-f0-9]{32}$")]
SpecKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{1,63}$")]
SpecStage = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{1,63}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
SpecScope = Literal["team", "project"]
_MAX_SPEC_BYTES = 256_000
_MAX_RECORD_BYTES = 512_000
_MAX_ACTIVATION_BYTES = 128_000
_MAX_RETIREMENT_BYTES = 64_000
_SAFE_KEY = re.compile(r"[^a-z0-9_.-]+")


class SpecDocumentError(RuntimeError):
    """Raised when a Spec record or activation cannot be trusted."""


class CreateSpecDocument(DomainModel):
    """Human-authored strict engineering contract before owner/version binding."""

    spec_key: SpecKey
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    body_markdown: Annotated[str, StringConstraints(min_length=1, max_length=_MAX_SPEC_BYTES)]
    roles: Annotated[tuple[TeamRole, ...], Field(min_length=1, max_length=7)] = tuple(TeamRole)
    stages: Annotated[tuple[SpecStage, ...], Field(min_length=1, max_length=16)] = (
        "implementing",
        "qa",
        "review",
    )
    repository_ids: Annotated[tuple[RepositoryId, ...], Field(max_length=32)] = ()
    path_globs: Annotated[tuple[NonEmptyStr, ...], Field(max_length=64)] = ("*",)
    verification: Annotated[str, StringConstraints(max_length=8_000)]

    @model_validator(mode="after")
    def validate_applicability(self) -> Self:
        ensure_unique(self.roles, "Spec roles")
        ensure_unique(self.stages, "Spec stages")
        ensure_unique(self.repository_ids, "Spec repository IDs")
        ensure_unique(self.path_globs, "Spec path globs")
        if tuple(sorted(self.repository_ids)) != self.repository_ids:
            raise ValueError("Spec repository IDs must be sorted")
        for value in self.path_globs:
            _validate_path_glob(value)
        if not self.body_markdown.strip():
            raise ValueError("Spec body cannot be blank")
        return self


class SpecDocument(DomainModel):
    """One immutable version of a Team- or Project-owned engineering Spec."""

    schema_version: Literal["v0.1"] = "v0.1"
    spec_id: SpecDocumentId
    scope: SpecScope
    team_id: TeamId
    project_id: ProjectId | None = None
    spec_key: SpecKey
    version: Annotated[int, Field(ge=1)]
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    body_markdown: Annotated[str, StringConstraints(min_length=1, max_length=_MAX_SPEC_BYTES)]
    roles: Annotated[tuple[TeamRole, ...], Field(min_length=1, max_length=7)]
    stages: Annotated[tuple[SpecStage, ...], Field(min_length=1, max_length=16)]
    repository_ids: Annotated[tuple[RepositoryId, ...], Field(max_length=32)] = ()
    path_globs: Annotated[tuple[NonEmptyStr, ...], Field(max_length=64)]
    verification: Annotated[str, StringConstraints(max_length=8_000)]
    created_at: AwareDatetime
    spec_sha256: Digest

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        CreateSpecDocument(
            spec_key=self.spec_key,
            title=self.title,
            body_markdown=self.body_markdown,
            roles=self.roles,
            stages=self.stages,
            repository_ids=self.repository_ids,
            path_globs=self.path_globs,
            verification=self.verification,
        )
        if (self.scope == "project") != (self.project_id is not None):
            raise ValueError("Spec scope and Project identity do not match")
        return self

    def recompute_digest(self) -> str:
        return _sha256(self.model_dump(mode="json", exclude={"spec_sha256"}))

    def validate_integrity(self) -> None:
        identity = _identity_digest(self)
        if self.spec_id != f"spec_document_{identity[:32]}":
            raise SpecDocumentError("Spec document identity mismatch")
        if self.spec_sha256 != self.recompute_digest():
            raise SpecDocumentError("Spec document digest mismatch")

    @property
    def applies_to_all_repositories(self) -> bool:
        return not self.repository_ids


class ActiveSpecRef(DomainModel):
    spec_key: SpecKey
    spec_id: SpecDocumentId
    version: Annotated[int, Field(ge=1)]
    spec_sha256: Digest


class SpecActivation(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    scope: SpecScope
    team_id: TeamId
    project_id: ProjectId | None = None
    active: Annotated[tuple[ActiveSpecRef, ...], Field(max_length=128)] = ()
    activation_sha256: Digest

    @model_validator(mode="after")
    def validate_activation(self) -> Self:
        if (self.scope == "project") != (self.project_id is not None):
            raise ValueError("Spec activation scope and Project identity do not match")
        ensure_unique((item.spec_key for item in self.active), "active Spec keys")
        ensure_unique((item.spec_id for item in self.active), "active Spec IDs")
        if tuple(sorted(self.active, key=lambda item: item.spec_key)) != self.active:
            raise ValueError("active Specs must be sorted by key")
        return self

    def recompute_digest(self) -> str:
        return _sha256(self.model_dump(mode="json", exclude={"activation_sha256"}))

    def validate_integrity(self) -> None:
        if self.activation_sha256 != self.recompute_digest():
            raise SpecDocumentError("Spec activation digest mismatch")


class SpecRetirement(DomainModel):
    """Logical Specs excluded from future context while old revisions remain immutable."""

    schema_version: Literal["v0.1"] = "v0.1"
    scope: SpecScope
    team_id: TeamId
    project_id: ProjectId | None = None
    retired_spec_keys: Annotated[tuple[SpecKey, ...], Field(max_length=128)] = ()
    retirement_sha256: Digest

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        if (self.scope == "project") != (self.project_id is not None):
            raise ValueError("Spec retirement scope and Project identity do not match")
        ensure_unique(self.retired_spec_keys, "retired Spec keys")
        if tuple(sorted(self.retired_spec_keys)) != self.retired_spec_keys:
            raise ValueError("retired Spec keys must be sorted")
        return self

    def recompute_digest(self) -> str:
        return _sha256(self.model_dump(mode="json", exclude={"retirement_sha256"}))

    def validate_integrity(self) -> None:
        if self.retirement_sha256 != self.recompute_digest():
            raise SpecDocumentError("Spec retirement digest mismatch")


class UpdateSpecActivation(DomainModel):
    spec_ids: Annotated[tuple[SpecDocumentId, ...], Field(max_length=128)] = ()

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        ensure_unique(self.spec_ids, "Spec activation IDs")
        return self


class _SpecDocumentStore:
    @property
    def root(self) -> Path:
        raise NotImplementedError

    @property
    def scope(self) -> SpecScope:
        raise NotImplementedError

    @property
    def team_id(self) -> TeamId:
        raise NotImplementedError

    @property
    def project_id(self) -> ProjectId | None:
        raise NotImplementedError

    def _validate_workspace(self) -> None:
        raise NotImplementedError

    def _validate_command(self, command: CreateSpecDocument) -> None:
        del command

    def list(self) -> tuple[SpecDocument, ...]:
        self._validate_workspace()
        retired = set(self.retirement().retired_spec_keys)
        return tuple(item for item in self._list_all() if item.spec_key not in retired)

    def _list_all(self) -> tuple[SpecDocument, ...]:
        documents = self.root / "documents"
        if not documents.exists():
            return ()
        _require_directory(documents)
        values = tuple(
            self._read(path)
            for path in sorted(documents.iterdir())
            if path.is_dir() and not path.name.startswith(".spec-")
        )
        return tuple(sorted(values, key=lambda value: (value.spec_key, value.version)))

    def retirement(self) -> SpecRetirement:
        self._validate_workspace()
        path = self.root / "retirement.json"
        if not path.exists():
            return self._new_retirement(())
        try:
            retirement = SpecRetirement.model_validate_json(
                _read_regular(path, _MAX_RETIREMENT_BYTES)
            )
        except ValueError as error:
            raise SpecDocumentError("Spec retirement is invalid") from error
        retirement.validate_integrity()
        if (
            retirement.scope != self.scope
            or retirement.team_id != self.team_id
            or retirement.project_id != self.project_id
        ):
            raise SpecDocumentError("Spec retirement owner mismatch")
        known = {document.spec_key for document in self._list_all()}
        if not set(retirement.retired_spec_keys).issubset(known):
            raise SpecDocumentError("Spec retirement references an unknown key")
        return retirement

    def retire(self, spec_key: str) -> SpecRetirement:
        self._validate_workspace()
        key = TypeAdapter(SpecKey).validate_python(spec_key)
        if key not in {document.spec_key for document in self._list_all()}:
            raise SpecDocumentError("Spec was not found")
        if any(reference.spec_key == key for reference in self.activation().active):
            raise SpecDocumentError("active Spec must be deactivated before deletion")
        current = self.retirement()
        return self._save_retirement((*current.retired_spec_keys, key))

    def restore(self, spec_key: str) -> SpecRetirement:
        self._validate_workspace()
        key = TypeAdapter(SpecKey).validate_python(spec_key)
        current = self.retirement()
        if key not in current.retired_spec_keys:
            return current
        return self._save_retirement(
            tuple(item for item in current.retired_spec_keys if item != key)
        )

    def create(
        self,
        command: CreateSpecDocument,
        *,
        created_at: datetime | None = None,
    ) -> SpecDocument:
        self._validate_workspace()
        self._validate_command(command)
        existing = self._list_all()
        fingerprint = _draft_digest(command)
        for document in existing:
            if (
                document.spec_key == command.spec_key
                and _document_draft_digest(document) == fingerprint
            ):
                self.restore(document.spec_key)
                return document
        version = 1 + max(
            (document.version for document in existing if document.spec_key == command.spec_key),
            default=0,
        )
        timestamp = created_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise SpecDocumentError("Spec timestamp must include a timezone")
        provisional = SpecDocument(
            spec_id="spec_document_" + "0" * 32,
            scope=self.scope,
            team_id=self.team_id,
            project_id=self.project_id,
            version=version,
            created_at=timestamp,
            spec_sha256="0" * 64,
            **command.model_dump(),
        )
        identity = _identity_digest(provisional)
        identified = provisional.model_copy(update={"spec_id": f"spec_document_{identity[:32]}"})
        document = identified.model_copy(update={"spec_sha256": identified.recompute_digest()})
        target = self.root / "documents" / document.spec_id
        if target.exists() or target.is_symlink():
            persisted = self._read(target)
            if persisted == document:
                return persisted
            raise SpecDocumentError("Spec document identity collision")
        documents = target.parent
        documents.mkdir(parents=True, exist_ok=True)
        _require_directory(documents)
        staging = Path(tempfile.mkdtemp(prefix=".spec-", dir=documents))
        try:
            _write_new(staging / "spec.json", document.model_dump_json(indent=2).encode())
            _sync_directory(staging)
            staging.rename(target)
            _sync_directory(documents)
        except OSError as error:
            raise SpecDocumentError("Spec document could not be published") from error
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        persisted = self._read(target)
        self.restore(persisted.spec_key)
        return persisted

    def activation(self) -> SpecActivation:
        self._validate_workspace()
        path = self.root / "activation.json"
        if not path.exists():
            return self._new_activation(())
        payload = _read_regular(path, _MAX_ACTIVATION_BYTES)
        try:
            activation = SpecActivation.model_validate_json(payload)
        except ValueError as error:
            raise SpecDocumentError("Spec activation is invalid") from error
        activation.validate_integrity()
        self._validate_activation_owner(activation)
        documents = {document.spec_id: document for document in self.list()}
        for reference in activation.active:
            document = documents.get(reference.spec_id)
            if document is None or (
                document.spec_key != reference.spec_key
                or document.version != reference.version
                or document.spec_sha256 != reference.spec_sha256
            ):
                raise SpecDocumentError("Spec activation references a missing or changed document")
        return activation

    def activate(self, spec_ids: tuple[str, ...]) -> SpecActivation:
        self._validate_workspace()
        ensure_unique(spec_ids, "Spec activation IDs")
        documents = {document.spec_id: document for document in self.list()}
        try:
            selected = tuple(
                documents[TypeAdapter(SpecDocumentId).validate_python(value)] for value in spec_ids
            )
        except (KeyError, ValueError) as error:
            raise SpecDocumentError("Spec activation references an unknown document") from error
        try:
            ensure_unique((document.spec_key for document in selected), "active Spec keys")
        except ValueError as error:
            raise SpecDocumentError(str(error)) from error
        refs = tuple(
            ActiveSpecRef(
                spec_key=document.spec_key,
                spec_id=document.spec_id,
                version=document.version,
                spec_sha256=document.spec_sha256,
            )
            for document in sorted(selected, key=lambda document: document.spec_key)
        )
        activation = self._new_activation(refs)
        self.root.mkdir(parents=True, exist_ok=True)
        _require_directory(self.root)
        _atomic_write(self.root / "activation.json", activation.model_dump_json(indent=2).encode())
        return self.activation()

    def active(self) -> tuple[SpecDocument, ...]:
        activation = self.activation()
        documents = {document.spec_id: document for document in self.list()}
        return tuple(documents[item.spec_id] for item in activation.active)

    def _new_activation(self, refs: tuple[ActiveSpecRef, ...]) -> SpecActivation:
        provisional = SpecActivation(
            scope=self.scope,
            team_id=self.team_id,
            project_id=self.project_id,
            active=refs,
            activation_sha256="0" * 64,
        )
        return provisional.model_copy(update={"activation_sha256": provisional.recompute_digest()})

    def _new_retirement(self, spec_keys: tuple[str, ...]) -> SpecRetirement:
        provisional = SpecRetirement(
            scope=self.scope,
            team_id=self.team_id,
            project_id=self.project_id,
            retired_spec_keys=tuple(sorted(set(spec_keys))),
            retirement_sha256="0" * 64,
        )
        return provisional.model_copy(update={"retirement_sha256": provisional.recompute_digest()})

    def _save_retirement(self, spec_keys: tuple[str, ...]) -> SpecRetirement:
        retirement = self._new_retirement(spec_keys)
        self.root.mkdir(parents=True, exist_ok=True)
        _require_directory(self.root)
        _atomic_write(
            self.root / "retirement.json",
            retirement.model_dump_json(indent=2).encode(),
        )
        return self.retirement()

    def _validate_activation_owner(self, activation: SpecActivation) -> None:
        if (
            activation.scope != self.scope
            or activation.team_id != self.team_id
            or activation.project_id != self.project_id
        ):
            raise SpecDocumentError("Spec activation owner mismatch")

    def _read(self, directory: Path) -> SpecDocument:
        _require_directory(directory)
        try:
            document = SpecDocument.model_validate_json(
                _read_regular(directory / "spec.json", _MAX_RECORD_BYTES)
            )
        except ValueError as error:
            raise SpecDocumentError("Spec document is invalid") from error
        document.validate_integrity()
        if directory.name != document.spec_id:
            raise SpecDocumentError("Spec document directory identity mismatch")
        if (
            document.scope != self.scope
            or document.team_id != self.team_id
            or document.project_id != self.project_id
        ):
            raise SpecDocumentError("Spec document owner mismatch")
        return document


@dataclass(frozen=True, slots=True)
class TeamSpecDocumentStore(_SpecDocumentStore):
    team: TeamWorkspace

    @property
    def root(self) -> Path:
        return self.team.root / "specs"

    @property
    def scope(self) -> SpecScope:
        return "team"

    @property
    def team_id(self) -> TeamId:
        return self.team.manifest.team_id

    @property
    def project_id(self) -> None:
        return None

    def _validate_workspace(self) -> None:
        self.team.validate_current()

    def _validate_command(self, command: CreateSpecDocument) -> None:
        known = {
            repository.repository_id
            for project in self.team.project_registry().discover()
            for repository in project.repository_registry().discover()
        }
        _reject_unknown_repositories(command.repository_ids, known)


@dataclass(frozen=True, slots=True)
class ProjectSpecDocumentStore(_SpecDocumentStore):
    project: ProjectWorkspace

    @property
    def root(self) -> Path:
        return self.project.root / "specs"

    @property
    def scope(self) -> SpecScope:
        return "project"

    @property
    def team_id(self) -> TeamId:
        return self.project.manifest.team_id

    @property
    def project_id(self) -> ProjectId:
        return self.project.manifest.project_id

    def _validate_workspace(self) -> None:
        self.project.validate_current()

    def _validate_command(self, command: CreateSpecDocument) -> None:
        known = {
            repository.repository_id for repository in self.project.repository_registry().discover()
        }
        _reject_unknown_repositories(command.repository_ids, known)


def suggested_spec_key(filename: str) -> SpecKey:
    """Return a stable UI default without interpreting document semantics."""
    stem = Path(filename).stem.lower()
    value = _SAFE_KEY.sub("-", stem).strip("-._")
    if len(value) < 2 or not value[0:1].isalpha():
        value = f"spec-{value or 'rule'}"
    return TypeAdapter(SpecKey).validate_python(value[:64])


def _validate_path_glob(value: str) -> None:
    if (
        not value
        or len(value) > 300
        or value.startswith("/")
        or "\\" in value
        or any(part == ".." for part in PurePosixPath(value).parts)
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("Spec path glob is unsafe")


def _reject_unknown_repositories(
    selected: tuple[RepositoryId, ...], known: set[RepositoryId]
) -> None:
    unknown = tuple(identity for identity in selected if identity not in known)
    if unknown:
        raise SpecDocumentError("Spec references a Repository outside its owner scope")


def _identity_digest(document: SpecDocument) -> str:
    payload = document.model_dump(mode="json", exclude={"spec_id", "created_at", "spec_sha256"})
    return _sha256(payload)


def _draft_digest(command: CreateSpecDocument) -> str:
    return _sha256(command.model_dump(mode="json"))


def _document_draft_digest(document: SpecDocument) -> str:
    payload = document.model_dump(
        mode="json",
        include={
            "spec_key",
            "title",
            "body_markdown",
            "roles",
            "stages",
            "repository_ids",
            "path_globs",
            "verification",
        },
    )
    return _sha256(payload)


def _sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _read_regular(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise SpecDocumentError("Spec record path is not a regular file")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise SpecDocumentError("Spec record is not a regular file")
            payload = stream.read(maximum + 1)
    except OSError as error:
        raise SpecDocumentError("Spec record could not be read") from error
    if len(payload) > maximum:
        raise SpecDocumentError("Spec record exceeds its size limit")
    return payload


def _require_directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise SpecDocumentError("Spec store cannot traverse a symlink")


def _write_new(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_write(path: Path, payload: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        _sync_directory(path.parent)
    except OSError as error:
        raise SpecDocumentError("Spec activation could not be published") from error
    finally:
        temporary_path.unlink(missing_ok=True)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "ActiveSpecRef",
    "CreateSpecDocument",
    "ProjectSpecDocumentStore",
    "SpecActivation",
    "SpecDocument",
    "SpecDocumentError",
    "SpecDocumentId",
    "SpecKey",
    "SpecRetirement",
    "TeamSpecDocumentStore",
    "UpdateSpecActivation",
    "suggested_spec_key",
]
