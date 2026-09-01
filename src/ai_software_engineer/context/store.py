"""Typed in-memory and filesystem ContextBundle stores for serial v0.1 execution."""

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.context.models import ContextBundle, ContextId
from ai_software_engineer.context.ports import (
    ContextConflict,
    ContextCorruption,
    ContextIntegrityError,
    ContextNotFound,
    ContextStoreError,
)
from ai_software_engineer.domain.model import WirePayload

_CONTEXT_ID_ADAPTER: Final[TypeAdapter[ContextId]] = TypeAdapter(ContextId)


class InMemoryContextStore:
    """Retain immutable Context manifests for provider prompt resolution.

    ``built_at`` is observation metadata and is excluded from Context identity. Rebuilding an
    otherwise identical manifest therefore returns the first registered value rather than
    replacing evidence used by an in-flight or replayed Agent Run.
    """

    def __init__(self) -> None:
        self._contexts: dict[ContextId, ContextBundle] = {}

    def put(self, context: ContextBundle) -> ContextBundle:
        _validate_context_identity(context, ContextIntegrityError)
        existing = self._contexts.get(context.context_id)
        if existing is None:
            self._contexts[context.context_id] = context
            return context
        if _identity_payload(existing) != _identity_payload(context):
            raise ContextConflict(
                f"Context ID is already registered with different content: {context.context_id}"
            )
        return existing

    def get(self, context_id: ContextId) -> ContextBundle:
        try:
            return self._contexts[context_id]
        except KeyError as error:
            raise ContextNotFound(f"Context manifest not found: {context_id}") from error


class FileContextStore:
    """Persist immutable Context manifests as validated atomic JSON files."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ContextStoreError(f"cannot initialize ContextStore at {self._root}") from error
        if not self._root.is_dir():
            raise ContextStoreError(f"ContextStore root is not a directory: {self._root}")

    def put(self, context: ContextBundle) -> ContextBundle:
        _validate_context_identity(context, ContextIntegrityError)
        path = self._path(context.context_id)
        if path.exists():
            existing = self.get(context.context_id)
            if _identity_payload(existing) != _identity_payload(context):
                raise ContextConflict(
                    f"Context ID is already persisted with different content: {context.context_id}"
                )
            return existing

        encoded = json.dumps(
            context.to_wire(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self._root,
                prefix=f".{context.context_id}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
        except OSError as error:
            raise ContextStoreError(
                f"cannot persist Context manifest: {context.context_id}"
            ) from error
        finally:
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)
        return context

    def get(self, context_id: ContextId) -> ContextBundle:
        path = self._path(context_id)
        if not path.is_file():
            raise ContextNotFound(f"Context manifest not found: {context_id}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            context = ContextBundle.model_validate(payload)
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as error:
            raise ContextCorruption(f"Context manifest is invalid: {context_id}") from error
        if context.context_id != context_id:
            raise ContextCorruption(f"Context manifest ID mismatch: {context_id}")
        _validate_context_identity(context, ContextCorruption)
        return context

    def _path(self, context_id: ContextId) -> Path:
        try:
            validated_id = _CONTEXT_ID_ADAPTER.validate_python(context_id)
        except ValidationError as error:
            raise ContextNotFound(str(context_id)) from error
        return self._root / f"{validated_id}.json"


def _identity_payload(context: ContextBundle) -> dict[str, object]:
    return context.model_dump(mode="python", exclude={"built_at"})


def _manifest_digest(context: ContextBundle) -> str:
    payload: WirePayload = context.to_wire()
    payload.pop("context_id")
    payload.pop("built_at")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_context_identity(
    context: ContextBundle,
    error_type: type[ContextStoreError],
) -> None:
    expected_context_id = f"ctx_{_manifest_digest(context)}"
    if context.context_id != expected_context_id:
        raise error_type(f"Context manifest ID does not match content: {context.context_id}")


__all__ = ["FileContextStore", "InMemoryContextStore"]
