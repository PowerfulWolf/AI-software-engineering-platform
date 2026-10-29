"""One fixed owned interpreter runs the complete bounded current-account survey."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Never, Self

from pydantic import Field, StrictInt, StrictStr, model_validator

from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.manager.legacy_containment import LocalBootObservation
from ai_software_engineer.manager.legacy_local_execution import (
    LegacyLocalExecutionSurvey,
    TrustedLegacyLocalExecutionObserver,
)
from ai_software_engineer.owned_processes import finish_owned_process
from ai_software_engineer.owned_sessions import OwnedProcessIdentity, observe_current_process
from ai_software_engineer.owned_spawn import spawn_owned_query

_MAX_REQUEST_BYTES = 64 * 1024
_MAX_RESULT_BYTES = 64 * 1024
_MAX_COMPLETE_SURVEY_ATTEMPTS = 3
_ENVIRONMENT = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C", "LC_ALL": "C"}
_LOGGER = logging.getLogger(__name__)
type _Pid = Annotated[StrictInt, Field(ge=1, le=2147483647)]
type _Digest = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
type LocalSurveyPhase = Literal[
    "platform_boundary",
    "process_inventory_before",
    "desktop_attribution_before",
    "paths_before",
    "process_inventory_after",
    "desktop_attribution_after",
    "paths_after",
    "process_identity_final",
]


class LocalSurveyObservationError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("isolated local execution survey incomplete")


def _remaining(deadline: float) -> float:
    if not math.isfinite(deadline):
        raise LocalSurveyObservationError
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LocalSurveyObservationError
    return remaining


def _canonical(model: DomainModel, *, exclude_digest: bool = False) -> bytes:
    return json.dumps(
        model.model_dump(mode="json", exclude={"request_sha256"} if exclude_digest else set()),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LocalSurveyObservationError
        result[key] = value
    return result


def _invalid_constant(value: str) -> Never:
    raise LocalSurveyObservationError


def _decode_model[ModelT: DomainModel](raw: bytes, model: type[ModelT]) -> ModelT:
    try:
        payload: object = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
        value = model.model_validate(payload)
        if value.model_fields_set != set(model.model_fields):
            raise LocalSurveyObservationError
        return value
    except (ValueError, TypeError, RecursionError):
        raise LocalSurveyObservationError from None


class LocalSurveyRequest(DomainModel):
    protocol: Literal["ase-local-survey-request-v1"] = "ase-local-survey-request-v1"
    root: StrictStr
    boot: LocalBootObservation
    uid: Annotated[StrictInt, Field(ge=0, le=4294967295)]
    parent_boot_identity: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    parent_identity: OwnedProcessIdentity
    started: Annotated[float, Field(strict=True, allow_inf_nan=False)]
    deadline: Annotated[float, Field(strict=True, allow_inf_nan=False)]
    request_sha256: _Digest

    @model_validator(mode="after")
    def exact_boundary(self) -> Self:
        root = PurePosixPath(self.root)
        if (
            not root.is_absolute()
            or str(root) != self.root
            or ".." in root.parts
            or "\0" in self.root
            or self.deadline != self.started + TrustedLegacyLocalExecutionObserver.MAX_SCAN_SECONDS
            or self.parent_identity.process_id > 2147483647
            or self.boot.model_fields_set != set(type(self.boot).model_fields)
            or self.parent_identity.model_fields_set != set(type(self.parent_identity).model_fields)
            or "\0" in self.parent_boot_identity
        ):
            raise ValueError("invalid isolated survey boundary")
        return self

    @classmethod
    def create(
        cls,
        root: Path,
        boot: LocalBootObservation,
        uid: int,
        parent_boot_identity: str,
        parent_identity: OwnedProcessIdentity,
        started: float,
        deadline: float,
    ) -> Self:
        value = cls(
            root=str(root),
            boot=boot,
            uid=uid,
            parent_boot_identity=parent_boot_identity,
            parent_identity=parent_identity,
            started=started,
            deadline=deadline,
            request_sha256="0" * 64,
        )
        return value.model_copy(update={"request_sha256": value.digest()})

    def digest(self) -> str:
        return hashlib.sha256(_canonical(self, exclude_digest=True)).hexdigest()

    def encode(self) -> bytes:
        raw = _canonical(self)
        if len(raw) > _MAX_REQUEST_BYTES or self.request_sha256 != self.digest():
            raise LocalSurveyObservationError
        return raw

    @classmethod
    def decode(cls, raw: bytes) -> Self:
        if len(raw) > _MAX_REQUEST_BYTES:
            raise LocalSurveyObservationError
        value = _decode_model(raw, cls)
        if value.request_sha256 != value.digest():
            raise LocalSurveyObservationError
        return value


class LocalSurveyResult(DomainModel):
    protocol: Literal["ase-local-survey-result-v1"] = "ase-local-survey-result-v1"
    request_sha256: _Digest
    worker_pid: _Pid
    survey: LegacyLocalExecutionSurvey
    incomplete_phase: LocalSurveyPhase | None

    @model_validator(mode="after")
    def exact_survey(self) -> Self:
        self.survey.validate_integrity()
        if self.survey.model_fields_set != set(type(self.survey).model_fields) or (
            (self.incomplete_phase is not None)
            != ("PROCESS_SCAN_INCOMPLETE" in self.survey.blockers)
        ):
            raise ValueError("invalid isolated survey result")
        return self

    def require_request(self, request: LocalSurveyRequest, worker_pid: int) -> None:
        self.survey.validate_integrity()
        if (
            self.request_sha256 != request.request_sha256
            or self.worker_pid != worker_pid
            or self.survey.worktree_path != request.root
            or self.survey.machine_sha256 != request.boot.machine_sha256
            or self.survey.boot_session_sha256 != request.boot.boot_session_sha256
            or self.survey.account_sha256 != _account_digest(request.boot, request.uid)
            or self.survey.scanner_version != "local-execution-v1"
        ):
            raise LocalSurveyObservationError

    def encode(self) -> bytes:
        raw = _canonical(self)
        if len(raw) > _MAX_RESULT_BYTES:
            raise LocalSurveyObservationError
        return raw

    @classmethod
    def decode(cls, raw: bytes) -> Self:
        if len(raw) > _MAX_RESULT_BYTES:
            raise LocalSurveyObservationError
        return _decode_model(raw, cls)


def _account_digest(boot: LocalBootObservation, uid: int) -> str:
    return hashlib.sha256(f"{boot.machine_sha256}:uid:{uid}".encode()).hexdigest()


class IsolatedLegacyLocalExecutionObserver:
    """No caller-selected process, command, exclusion or timeout is accepted."""

    def observe(
        self, *, worktree_root: Path, boot: LocalBootObservation
    ) -> LegacyLocalExecutionSurvey:
        for attempt in range(_MAX_COMPLETE_SURVEY_ATTEMPTS):
            survey, retryable = self._observe_once(worktree_root=worktree_root, boot=boot)
            if not retryable or attempt + 1 == _MAX_COMPLETE_SURVEY_ATTEMPTS:
                return survey
        raise AssertionError("bounded survey loop has no final result")

    def _observe_once(
        self, *, worktree_root: Path, boot: LocalBootObservation
    ) -> tuple[LegacyLocalExecutionSurvey, bool]:
        """Retry only a validated child result after its owned session has stopped."""
        started = time.monotonic()
        deadline = started + TrustedLegacyLocalExecutionObserver.MAX_SCAN_SECONDS
        root = worktree_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("本机执行调查的工作区不存在")
        uid = os.getuid()
        phase: LocalSurveyPhase | None = None
        retryable = False
        try:
            _remaining(deadline)
            if uid != os.geteuid():
                raise LocalSurveyObservationError
            parent_pid = os.getpid()
            native_boot, parent_identity = observe_current_process(parent_pid)
            if parent_identity is None or parent_identity.process_id != parent_pid:
                raise LocalSurveyObservationError
            request = LocalSurveyRequest.create(
                root, boot, uid, native_boot, parent_identity, started, deadline
            )
            result = _observe_survey_worker(request)
            phase = result.incomplete_phase
            if phase is None:
                return result.survey, False
            survey = result.survey
            retryable = survey.blockers == ("PROCESS_SCAN_INCOMPLETE",)
        except Exception:
            survey = LegacyLocalExecutionSurvey.create(
                worktree_path=str(root),
                machine_sha256=boot.machine_sha256,
                boot_session_sha256=boot.boot_session_sha256,
                account_sha256=_account_digest(boot, uid),
                observed_at=datetime.now(UTC),
                scanner_version="local-execution-v1",
                blockers=("PROCESS_SCAN_INCOMPLETE",),
            )
        elapsed = round(time.monotonic() - started, 3)
        _LOGGER.warning(
            "Local execution survey incomplete: phase=%s reason=%s elapsed_seconds=%.3f",
            phase or "isolated_survey",
            "LocalSurveyObservationError",
            elapsed,
            extra={
                "phase": phase or "isolated_survey",
                "reason": "LocalSurveyObservationError",
                "elapsed_seconds": elapsed,
            },
        )
        return survey, retryable


def _observe_survey_worker(request: LocalSurveyRequest) -> LocalSurveyResult:
    try:
        _remaining(request.deadline)
        raw_request = request.encode()
        with (
            tempfile.TemporaryFile() as source,
            tempfile.TemporaryFile() as output,
            tempfile.TemporaryFile() as errors,
        ):
            source.write(raw_request)
            source.seek(0)
            _remaining(request.deadline)
            spawned = spawn_owned_query(
                (
                    sys.executable,
                    "-I",
                    "-S",
                    "-B",
                    str(Path(__file__).with_name("local_survey_worker.py")),
                ),
                environment=_ENVIRONMENT,
                cwd=Path("/"),
                stdin=source.fileno(),
                stdout=output,
                stderr=errors,
            )
            process, original = spawned.process, spawned.observation
            try:
                process.wait(timeout=_remaining(request.deadline))
                _remaining(request.deadline)
                if process.returncode or errors.tell() or output.tell() > _MAX_RESULT_BYTES:
                    raise LocalSurveyObservationError
                output.seek(0)
                result = LocalSurveyResult.decode(output.read(_MAX_RESULT_BYTES + 1))
                result.require_request(request, process.pid)
                _remaining(request.deadline)
            finally:
                finish_owned_process(process, original, output_drained=True)
            _remaining(request.deadline)
            return result
    except Exception:
        raise LocalSurveyObservationError from None
