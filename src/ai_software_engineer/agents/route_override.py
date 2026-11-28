"""Human-approved, Task-scoped model route selection (e.g. after a quota is exhausted).

A route override never adds a model: it only moves one route that the configured
role policy already allows to the front, for one Task and one role. Records are
append-only and digest-protected; the newest sequence wins, so a later decision
(for example returning to the primary model) is a new record, never an edit.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Protocol, Self

from pydantic import AwareDatetime, Field, model_validator

from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ProviderRouteKind


def model_route_override_root(repository_workspace_root: Path) -> Path:
    return repository_workspace_root / "runs" / "model-route-overrides"


class ModelRouteOverrideError(RuntimeError):
    """The override ledger cannot be read or written safely."""


class ModelRouteOverride(DomainModel):
    kind: str = "model_route_override"
    schema_version: str = "v1"
    task_id: NonEmptyStr
    role: AgentRole
    sequence: int = Field(ge=1)
    provider: NonEmptyStr
    model: NonEmptyStr
    route_kind: ProviderRouteKind
    reason: NonEmptyStr
    approval_reference: NonEmptyStr
    approved_at: AwareDatetime
    override_sha256: NonEmptyStr

    @classmethod
    def create(cls, **values: object) -> Self:
        provisional = cls.model_validate({**values, "override_sha256": "0" * 64})
        return provisional.model_copy(update={"override_sha256": _digest(provisional)})

    @model_validator(mode="after")
    def validate_role(self) -> Self:
        if self.role is AgentRole.ORCHESTRATOR:
            raise ValueError("model route overrides apply to delivery roles only")
        return self

    def validate_integrity(self) -> None:
        if self.override_sha256 != _digest(self):
            raise ModelRouteOverrideError("model route override digest mismatch")


class FileModelRouteOverrideStore:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve(strict=False)

    def current(self, task_id: str, role: AgentRole) -> ModelRouteOverride | None:
        records = self.list(task_id, role)
        return records[-1] if records else None

    def list(self, task_id: str, role: AgentRole) -> tuple[ModelRouteOverride, ...]:
        directory = self._directory(task_id, role)
        if not directory.is_dir():
            return ()
        try:
            records = tuple(self._read(path) for path in sorted(directory.glob("*.json")))
        except OSError as error:
            raise ModelRouteOverrideError("cannot list model route overrides") from error
        if [item.sequence for item in records] != list(range(1, len(records) + 1)) or any(
            item.task_id != task_id or item.role is not role for item in records
        ):
            raise ModelRouteOverrideError("model route override ledger is not linear")
        return records

    def append(self, record: ModelRouteOverride) -> ModelRouteOverride:
        record.validate_integrity()
        existing = self.list(record.task_id, record.role)
        if record.sequence != len(existing) + 1:
            raise ModelRouteOverrideError("model route override decision is stale")
        target = self._directory(record.task_id, record.role) / f"{record.sequence:04d}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(record.to_wire(), ensure_ascii=False, sort_keys=True).encode()
        descriptor, temporary = tempfile.mkstemp(prefix=".override-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError as error:
                raise ModelRouteOverrideError("model route override decision is stale") from error
        finally:
            Path(temporary).unlink(missing_ok=True)
        return self._read(target)

    def _directory(self, task_id: str, role: AgentRole) -> Path:
        if not task_id.replace("_", "").isalnum():
            raise ModelRouteOverrideError("invalid Task identity for a model route override")
        return self._root / task_id / role.value

    @staticmethod
    def _read(path: Path) -> ModelRouteOverride:
        record = ModelRouteOverride.model_validate_json(path.read_bytes())
        record.validate_integrity()
        return record


def apply_route_override[R: _ConfiguredRoute](
    ordered: tuple[R, ...], override: ModelRouteOverride | None
) -> tuple[R, ...]:
    """Move the approved, already configured route first; never add a model."""
    if override is None:
        return ordered
    chosen = tuple(
        route
        for route in ordered
        if route.provider == override.provider
        and route.model == override.model
        and route.kind.value == override.route_kind
    )
    if len(chosen) != 1:
        raise ModelRouteOverrideError("approved model route is no longer configured")
    return (chosen[0], *(route for route in ordered if route is not chosen[0]))


class _RouteKind(Protocol):
    @property
    def value(self) -> str: ...


class _ConfiguredRoute(Protocol):
    @property
    def provider(self) -> str: ...
    @property
    def model(self) -> str: ...
    @property
    def kind(self) -> _RouteKind: ...


def _digest(record: ModelRouteOverride) -> str:
    payload = record.to_wire()
    payload.pop("override_sha256", None)
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
