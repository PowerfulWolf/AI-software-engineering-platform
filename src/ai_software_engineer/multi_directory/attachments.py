"""Immutable screenshot attachments owned by one Project Requirement."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, TypeAdapter

from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId

RequirementAttachmentId = Annotated[
    str, StringConstraints(pattern=r"^requirement_attachment_[a-f0-9]{40}$")
]
AttachmentDigest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
MAX_REQUIREMENT_SCREENSHOT_BYTES = 10_000_000
MAX_REQUIREMENT_SCREENSHOTS = 12
ScreenshotMediaType = Literal["image/png", "image/jpeg", "image/webp"]


class RequirementAttachmentError(RuntimeError):
    """Raised when an attachment cannot be safely stored or verified."""


class RequirementScreenshot(DomainModel):
    kind: Literal["requirement_screenshot"] = "requirement_screenshot"
    schema_version: Literal["v0.1"] = "v0.1"
    id: RequirementAttachmentId
    project_id: ProjectId
    delivery_id: DeliveryId
    source_name: NonEmptyStr
    media_type: ScreenshotMediaType
    source_bytes: Annotated[int, Field(ge=1, le=MAX_REQUIREMENT_SCREENSHOT_BYTES)]
    source_sha256: AttachmentDigest
    source_relative_path: NonEmptyStr
    uploaded_at: AwareDatetime
    manifest_sha256: AttachmentDigest

    def recompute_digest(self) -> str:
        return _digest(self.model_dump(mode="json", exclude={"manifest_sha256"}))

    def validate_integrity(self) -> None:
        if self.manifest_sha256 != self.recompute_digest():
            raise RequirementAttachmentError("Requirement screenshot manifest digest changed")


class RequirementAttachmentStore:
    """Content-addressed attachment storage below one Requirement journal."""

    def __init__(self, requirements_root: Path, *, project_id: ProjectId | str) -> None:
        self._root = requirements_root.absolute()
        self._project_id = str(project_id)
        _reject_symlink_chain(self._root)

    def put(
        self,
        delivery_id: DeliveryId | str,
        *,
        filename: str,
        content: bytes,
        uploaded_at: datetime | None = None,
    ) -> RequirementScreenshot:
        identity = str(delivery_id)
        name = _safe_filename(filename)
        media_type, suffix = _image_type(content)
        source_sha256 = hashlib.sha256(content).hexdigest()
        attachment_id = (
            "requirement_attachment_"
            + hashlib.sha256(
                f"{self._project_id}\n{identity}\n{name}\n{source_sha256}".encode()
            ).hexdigest()[:40]
        )
        relative = f"attachments/{attachment_id}/source{suffix}"
        now = uploaded_at or datetime.now(UTC)
        provisional = RequirementScreenshot(
            id=attachment_id,
            project_id=self._project_id,
            delivery_id=identity,
            source_name=name,
            media_type=media_type,
            source_bytes=len(content),
            source_sha256=source_sha256,
            source_relative_path=relative,
            uploaded_at=now,
            manifest_sha256="0" * 64,
        )
        manifest = provisional.model_copy(
            update={"manifest_sha256": provisional.recompute_digest()}
        )
        delivery_root = self._delivery_root(identity)
        attachments_root = delivery_root / "attachments"
        attachments_root.mkdir(parents=True, exist_ok=True)
        _reject_symlink_chain(attachments_root)
        target = attachments_root / attachment_id
        if target.exists() or target.is_symlink():
            existing = self.get(identity, attachment_id)
            if not _same_source(existing, manifest):
                raise RequirementAttachmentError("Requirement screenshot identity conflicts")
            return existing
        staging = Path(tempfile.mkdtemp(prefix=".attachment-", dir=attachments_root))
        try:
            source = staging / f"source{suffix}"
            source.write_bytes(content)
            (staging / "manifest.json").write_text(
                manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
            for path in (source, staging / "manifest.json"):
                descriptor = os.open(path, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            with suppress(FileExistsError):
                staging.rename(target)
            _sync_directory(attachments_root)
        finally:
            if staging.exists():
                for path in staging.iterdir():
                    path.unlink()
                staging.rmdir()
        stored = self.get(identity, attachment_id)
        if not _same_source(stored, manifest):
            raise RequirementAttachmentError("Requirement screenshot publication conflicted")
        return stored

    def get(
        self,
        delivery_id: DeliveryId | str,
        attachment_id: RequirementAttachmentId | str,
    ) -> RequirementScreenshot:
        delivery_root = self._delivery_root(str(delivery_id))
        root = delivery_root / "attachments" / str(attachment_id)
        _reject_symlink_chain(root)
        try:
            manifest = RequirementScreenshot.model_validate_json(
                (root / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValueError) as error:
            raise RequirementAttachmentError("Requirement screenshot is unavailable") from error
        manifest.validate_integrity()
        expected_relative = f"attachments/{manifest.id}/{Path(manifest.source_relative_path).name}"
        if (
            manifest.id != str(attachment_id)
            or manifest.delivery_id != str(delivery_id)
            or manifest.project_id != self._project_id
            or manifest.source_relative_path != expected_relative
        ):
            raise RequirementAttachmentError("Requirement screenshot binding changed")
        source = delivery_root / manifest.source_relative_path
        _reject_symlink_chain(source)
        try:
            content = source.read_bytes()
        except OSError as error:
            raise RequirementAttachmentError(
                "Requirement screenshot source is unavailable"
            ) from error
        if (
            len(content) != manifest.source_bytes
            or hashlib.sha256(content).hexdigest() != manifest.source_sha256
        ):
            raise RequirementAttachmentError("Requirement screenshot source digest changed")
        media_type, _ = _image_type(content)
        if media_type != manifest.media_type:
            raise RequirementAttachmentError("Requirement screenshot media type changed")
        return manifest

    def source_path(self, manifest: RequirementScreenshot) -> Path:
        verified = self.get(manifest.delivery_id, manifest.id)
        if verified != manifest:
            raise RequirementAttachmentError("Requirement screenshot reference changed")
        return self._delivery_root(manifest.delivery_id) / manifest.source_relative_path

    def _delivery_root(self, delivery_id: str) -> Path:
        identity = TypeAdapter(DeliveryId).validate_python(delivery_id)
        if not identity.startswith("delivery_multi_"):
            raise RequirementAttachmentError("Screenshots require a multi-directory Requirement")
        root = self._root / identity
        _reject_symlink_chain(root)
        if not root.is_dir():
            raise RequirementAttachmentError("Requirement was not found")
        return root


def _safe_filename(value: str) -> str:
    if (
        not value
        or len(value) > 200
        or Path(value).name != value
        or value in {".", ".."}
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise RequirementAttachmentError("Screenshot filename is invalid")
    return value


def _image_type(content: bytes) -> tuple[ScreenshotMediaType, str]:
    if not content or len(content) > MAX_REQUIREMENT_SCREENSHOT_BYTES:
        raise RequirementAttachmentError("Screenshot exceeds the upload limit")
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp", ".webp"
    raise RequirementAttachmentError("Only PNG, JPEG and WebP screenshots are supported")


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _same_source(left: RequirementScreenshot, right: RequirementScreenshot) -> bool:
    return left.model_dump(exclude={"uploaded_at", "manifest_sha256"}) == right.model_dump(
        exclude={"uploaded_at", "manifest_sha256"}
    )


def _reject_symlink_chain(path: Path) -> None:
    if any(candidate.is_symlink() for candidate in (path, *path.parents)):
        raise RequirementAttachmentError("Requirement screenshot path cannot traverse symlinks")


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "MAX_REQUIREMENT_SCREENSHOTS",
    "MAX_REQUIREMENT_SCREENSHOT_BYTES",
    "RequirementAttachmentError",
    "RequirementAttachmentId",
    "RequirementAttachmentStore",
    "RequirementScreenshot",
]
