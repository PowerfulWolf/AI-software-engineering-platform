"""Bounded provider fallback with immutable, replayable route-attempt evidence."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Protocol, Self

from pydantic import AwareDatetime, Field, StrictBool, StrictInt, StringConstraints, model_validator

from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.agents.ports import AgentAdapter, AgentRequestConflict
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, WirePayload, ensure_unique
from ai_software_engineer.domain.task import TaskId

Clock = Callable[[], datetime]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
_UNSEALED = "0" * 64


class RouteAttemptOutcome(StrEnum):
    """Whether a provider route completed, switched, or ended the run."""

    SUCCEEDED = "SUCCEEDED"
    FALLBACK = "FALLBACK"
    FAILED = "FAILED"


class ModelRouteAttempt(DomainModel):
    """Immutable evidence for one provider/model attempt within an Agent Run."""

    kind: str = "model_route_attempt"
    run_id: RunId
    task_id: TaskId
    role: AgentRole
    route_index: Annotated[StrictInt, Field(ge=1, le=16)]
    provider: NonEmptyStr
    model: NonEmptyStr
    request_sha256: Sha256
    started_at: AwareDatetime
    completed_at: AwareDatetime
    outcome: RouteAttemptOutcome
    error_code: AgentErrorCode | None = None
    transient: StrictBool | None = None
    result: AgentResult
    attempt_sha256: Sha256

    @model_validator(mode="after")
    def validate_attempt(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("route attempt cannot complete before it starts")
        if self.outcome is RouteAttemptOutcome.SUCCEEDED:
            if self.error_code is not None or self.transient is not None:
                raise ValueError("successful route attempt cannot carry an error")
        elif self.error_code is None or self.transient is None:
            raise ValueError("failed route attempt requires typed error facts")
        if (
            self.result.run_id != self.run_id
            or self.result.task_id != self.task_id
            or self.result.role is not self.role
        ):
            raise ValueError("route attempt result identity does not match")
        if (self.outcome is RouteAttemptOutcome.SUCCEEDED) != (
            self.result.status is AgentRunStatus.SUCCEEDED
        ):
            raise ValueError("route attempt outcome does not match result")
        if self.result.error is not None and (
            self.result.error.code != self.error_code
            or self.result.error.transient != self.transient
        ):
            raise ValueError("route attempt error facts do not match result")
        if self.attempt_sha256 != _UNSEALED and self.attempt_sha256 != _digest_attempt(self):
            raise ValueError("route attempt digest does not match content")
        return self

    @classmethod
    def create(
        cls,
        *,
        request: AgentRequest,
        route_index: int,
        provider: str,
        model: str,
        started_at: datetime,
        completed_at: datetime,
        result: AgentResult,
        fallback: bool,
    ) -> ModelRouteAttempt:
        error = result.error
        outcome = (
            RouteAttemptOutcome.SUCCEEDED
            if result.status is AgentRunStatus.SUCCEEDED
            else RouteAttemptOutcome.FALLBACK
            if fallback
            else RouteAttemptOutcome.FAILED
        )
        unsealed = cls(
            run_id=request.run_id,
            task_id=request.task_id,
            role=request.role,
            route_index=route_index,
            provider=provider,
            model=model,
            request_sha256=_digest_request(request),
            started_at=started_at,
            completed_at=completed_at,
            outcome=outcome,
            error_code=error.code if error is not None else None,
            transient=error.transient if error is not None else None,
            result=result,
            attempt_sha256=_UNSEALED,
        )
        return unsealed.model_copy(update={"attempt_sha256": _digest_attempt(unsealed)})

    def validate_integrity(self) -> None:
        if self.attempt_sha256 != _digest_attempt(self):
            raise ValueError("route attempt digest does not match content")


class ModelRouteAttemptStore(Protocol):
    """Append-only storage used by fallback routing and operational replay."""

    def append(self, attempt: ModelRouteAttempt) -> ModelRouteAttempt: ...

    def list_for_run(self, run_id: RunId) -> tuple[ModelRouteAttempt, ...]: ...


class ModelRouteAttemptStoreError(RuntimeError):
    """Base class for route-attempt persistence failures."""


class ModelRouteAttemptConflict(ModelRouteAttemptStoreError):
    """Raised when an immutable route slot is reused with changed facts."""


class ModelRouteAttemptCorruption(ModelRouteAttemptStoreError):
    """Raised when durable route evidence fails validation or integrity checks."""


class FileModelRouteAttemptStore:
    """Persist one digest-protected JSON record per route slot."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve(strict=False)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ModelRouteAttemptStoreError("cannot initialize model route store") from error

    def append(self, attempt: ModelRouteAttempt) -> ModelRouteAttempt:
        attempt.validate_integrity()
        target = self._path(attempt.run_id, attempt.route_index)
        if target.exists():
            existing = self._read(target)
            if existing == attempt:
                return existing
            raise ModelRouteAttemptConflict(
                f"route slot {attempt.run_id}/{attempt.route_index} already has different facts"
            )
        _atomic_write(target, _canonical_json(attempt.to_wire()))
        return self._read(target)

    def list_for_run(self, run_id: RunId) -> tuple[ModelRouteAttempt, ...]:
        directory = self._run_directory(run_id)
        if not directory.exists():
            return ()
        try:
            attempts = tuple(self._read(path) for path in sorted(directory.glob("*.json")))
        except OSError as error:
            raise ModelRouteAttemptStoreError("cannot list model route attempts") from error
        if any(attempt.run_id != run_id for attempt in attempts):
            raise ModelRouteAttemptCorruption("model route attempt run identity mismatch")
        indices = tuple(attempt.route_index for attempt in attempts)
        ensure_unique(indices, "model route attempt indices")
        return tuple(sorted(attempts, key=lambda attempt: attempt.route_index))

    def _path(self, run_id: RunId, route_index: int) -> Path:
        return self._run_directory(run_id) / f"{route_index:02d}.json"

    def _run_directory(self, run_id: RunId) -> Path:
        if not run_id.startswith("run_") or not run_id.replace("_", "").isalnum():
            raise ModelRouteAttemptStoreError("invalid model route run ID")
        target = self._root / run_id
        if target.is_symlink():
            raise ModelRouteAttemptStoreError("model route directory cannot be a symlink")
        return target

    @staticmethod
    def _read(path: Path) -> ModelRouteAttempt:
        try:
            attempt = ModelRouteAttempt.model_validate_json(path.read_text(encoding="utf-8"))
            attempt.validate_integrity()
            if path.stem != f"{attempt.route_index:02d}":
                raise ValueError("route slot filename mismatch")
            return attempt
        except (OSError, ValueError) as error:
            raise ModelRouteAttemptCorruption("cannot decode model route attempt") from error


@dataclass(frozen=True, slots=True)
class ProviderAgentRoute:
    """One ordered provider/model adapter candidate."""

    provider: str
    model: str
    adapter: AgentAdapter

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.model.strip():
            raise ValueError("provider route requires provider and model")


class FallbackAgentAdapter:
    """Try frozen routes only for typed transient infrastructure failures."""

    def __init__(
        self,
        routes: tuple[ProviderAgentRoute, ...],
        *,
        attempt_store: ModelRouteAttemptStore,
        clock: Clock | None = None,
    ) -> None:
        if not routes:
            raise ValueError("fallback adapter requires at least one route")
        ensure_unique(
            ((route.provider, route.model) for route in routes),
            "fallback provider/model routes",
        )
        self._routes = routes
        self._attempt_store = attempt_store
        self._clock = clock or _utc_now
        self._requests: dict[RunId, AgentRequest] = {}
        self._results: dict[RunId, AgentResult] = {}

    def run(self, request: AgentRequest) -> AgentResult:
        prior = self._requests.get(request.run_id)
        if prior is not None:
            if prior != request:
                raise AgentRequestConflict(
                    f"run ID already used with a different request: {request.run_id}"
                )
            return self._results[request.run_id]
        attempts = self._validated_replay_prefix(request)
        if attempts and attempts[-1].outcome is not RouteAttemptOutcome.FALLBACK:
            terminal_result = attempts[-1].result
            self._requests[request.run_id] = request
            self._results[request.run_id] = terminal_result
            return terminal_result

        result: AgentResult | None = attempts[-1].result if attempts else None
        for index, route in enumerate(self._routes[len(attempts) :], start=len(attempts) + 1):
            started_at = self._clock()
            result = route.adapter.run(request)
            completed_at = self._clock()
            fallback = index < len(self._routes) and _allows_fallback(result)
            self._attempt_store.append(
                ModelRouteAttempt.create(
                    request=request,
                    route_index=index,
                    provider=route.provider,
                    model=route.model,
                    started_at=started_at,
                    completed_at=completed_at,
                    result=result,
                    fallback=fallback,
                )
            )
            if result.status is AgentRunStatus.SUCCEEDED or not fallback:
                break
        assert result is not None
        self._requests[request.run_id] = request
        self._results[request.run_id] = result
        return result

    def _validated_replay_prefix(self, request: AgentRequest) -> tuple[ModelRouteAttempt, ...]:
        attempts = self._attempt_store.list_for_run(request.run_id)
        for index, attempt in enumerate(attempts, start=1):
            if index > len(self._routes):
                raise AgentRequestConflict("durable route attempts exceed configured routes")
            route = self._routes[index - 1]
            result = attempt.result
            if (
                attempt.route_index != index
                or attempt.provider != route.provider
                or attempt.model != route.model
                or attempt.request_sha256 != _digest_request(request)
                or result.run_id != request.run_id
                or result.task_id != request.task_id
                or result.role is not request.role
                or result.attempt != request.attempt
                or result.source_revision != request.source_revision
                or result.context_manifest_id != request.context_manifest_id
            ):
                raise AgentRequestConflict(
                    f"durable route attempts do not match request: {request.run_id}"
                )
            if index < len(attempts) and attempt.outcome is not RouteAttemptOutcome.FALLBACK:
                raise AgentRequestConflict("durable route attempt sequence is not resumable")
        return attempts


_FALLBACK_CODES = frozenset(
    {
        AgentErrorCode.TIMEOUT,
        AgentErrorCode.QUOTA_EXHAUSTED,
        AgentErrorCode.RATE_LIMITED,
        AgentErrorCode.PROVIDER_UNAVAILABLE,
    }
)


def _allows_fallback(result: AgentResult) -> bool:
    return (
        result.status is not AgentRunStatus.SUCCEEDED
        and result.error is not None
        and result.error.transient
        and result.error.code in _FALLBACK_CODES
    )


def _digest_attempt(attempt: ModelRouteAttempt) -> str:
    payload = attempt.to_wire()
    payload.pop("attempt_sha256", None)
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _digest_request(request: AgentRequest) -> str:
    return hashlib.sha256(_canonical_json(request.to_wire())).hexdigest()


def _canonical_json(payload: WirePayload) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _atomic_write(target: Path, payload: bytes) -> None:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".ase-route-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, target)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
    except OSError as error:
        raise ModelRouteAttemptStoreError("cannot persist model route attempt") from error


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "FallbackAgentAdapter",
    "FileModelRouteAttemptStore",
    "ModelRouteAttempt",
    "ModelRouteAttemptConflict",
    "ModelRouteAttemptCorruption",
    "ModelRouteAttemptStore",
    "ModelRouteAttemptStoreError",
    "ProviderAgentRoute",
    "RouteAttemptOutcome",
]
