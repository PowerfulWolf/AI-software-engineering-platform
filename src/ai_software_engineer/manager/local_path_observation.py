"""Private bounded lsof parsing isolated from the service's Python threads."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
import time
from pathlib import Path
from typing import Annotated, Literal, Never, Self

from pydantic import Field, StrictInt, StrictStr, model_validator

from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.owned_processes import finish_owned_process
from ai_software_engineer.owned_spawn import spawn_owned_query

_MAX_PROCESSES = 4096
_MAX_FILES = 65536
_MAX_BODY_BYTES = 8 * 1024 * 1024
_MAX_REQUEST_BYTES = 64 * 1024 * 1024
_MAX_RESULT_BYTES = 256 * 1024
_ENVIRONMENT = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C", "LC_ALL": "C"}
type PathBlocker = Literal["WORKTREE_PROCESS_ACTIVE"]
type _Pid = Annotated[StrictInt, Field(ge=0)]
type _Digest = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]


class LocalPathObservationError(RuntimeError):
    """A bounded complete observation was unavailable; contains no raw data."""

    def __init__(self) -> None:
        super().__init__("local path observation incomplete")


def _remaining(deadline: float) -> float:
    if not math.isfinite(deadline):
        raise LocalPathObservationError
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LocalPathObservationError
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
    value: dict[str, object] = {}
    for name, item in pairs:
        if name in value:
            raise LocalPathObservationError
        value[name] = item
    return value


def _invalid_constant(value: str) -> Never:
    raise LocalPathObservationError


def _decode_model[ModelT: DomainModel](raw: bytes, model: type[ModelT]) -> ModelT:
    try:
        payload: object = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
        value = model.model_validate(payload)
        if value.model_fields_set != set(model.model_fields):
            raise LocalPathObservationError
        return value
    except (ValueError, TypeError, RecursionError):
        raise LocalPathObservationError from None


class MacPathObservationRequest(DomainModel):
    """Internal exact input, never a persisted or Agent-facing contract."""

    protocol: Literal["ase-mac-path-request-v1"] = "ase-mac-path-request-v1"
    body: StrictStr
    root: StrictStr
    ignored_pids: Annotated[tuple[_Pid, ...], Field(max_length=_MAX_PROCESSES)]
    cwd_blocker_pids: Annotated[tuple[_Pid, ...], Field(max_length=_MAX_PROCESSES)]
    deadline: Annotated[float, Field(strict=True, allow_inf_nan=False)]
    request_sha256: _Digest

    @model_validator(mode="after")
    def bounded_input(self) -> Self:
        if (
            len(self.body.encode("utf-8", errors="strict")) > _MAX_BODY_BYTES
            or not Path(self.root).is_absolute()
            or "\0" in self.root
            or tuple(sorted(set(self.ignored_pids))) != self.ignored_pids
            or tuple(sorted(set(self.cwd_blocker_pids))) != self.cwd_blocker_pids
        ):
            raise ValueError("invalid bounded path input")
        return self

    @classmethod
    def create(
        cls,
        body: bytes,
        root: Path,
        ignored_pids: frozenset[int],
        cwd_blocker_pids: frozenset[int],
        deadline: float,
    ) -> Self:
        if len(body) > _MAX_BODY_BYTES:
            raise LocalPathObservationError
        value = cls(
            body=body.decode("utf-8", errors="strict"),
            root=str(root),
            ignored_pids=tuple(sorted(ignored_pids)),
            cwd_blocker_pids=tuple(sorted(cwd_blocker_pids)),
            deadline=deadline,
            request_sha256="0" * 64,
        )
        return value.model_copy(update={"request_sha256": value.digest()})

    def digest(self) -> str:
        return hashlib.sha256(_canonical(self, exclude_digest=True)).hexdigest()

    def encode(self) -> bytes:
        raw = _canonical(self)
        if len(raw) > _MAX_REQUEST_BYTES or self.request_sha256 != self.digest():
            raise LocalPathObservationError
        return raw

    @classmethod
    def decode(cls, raw: bytes) -> Self:
        if len(raw) > _MAX_REQUEST_BYTES:
            raise LocalPathObservationError
        value = _decode_model(raw, cls)
        if value.request_sha256 != value.digest():
            raise LocalPathObservationError
        return value


class MacPathObservationResult(DomainModel):
    """Only complete coverage and the existing blocker cross the child boundary."""

    protocol: Literal["ase-mac-path-result-v1"] = "ase-mac-path-result-v1"
    request_sha256: _Digest
    covered_pids: Annotated[tuple[_Pid, ...], Field(max_length=_MAX_PROCESSES)]
    blockers: Annotated[tuple[PathBlocker, ...], Field(max_length=1)]

    @model_validator(mode="after")
    def unique_coverage(self) -> Self:
        if tuple(sorted(set(self.covered_pids))) != self.covered_pids:
            raise ValueError("invalid path coverage")
        return self

    def encode(self) -> bytes:
        raw = _canonical(self)
        if len(raw) > _MAX_RESULT_BYTES:
            raise LocalPathObservationError
        return raw

    @classmethod
    def decode(cls, raw: bytes) -> Self:
        if len(raw) > _MAX_RESULT_BYTES:
            raise LocalPathObservationError
        return _decode_model(raw, cls)


def _covers(path: str, root: Path, deadline: float) -> bool:
    if not path.startswith("/"):
        return False
    if path.endswith(" (deleted)"):
        path = path.removesuffix(" (deleted)")
    _remaining(deadline)
    resolved = Path(path).resolve(strict=False)
    _remaining(deadline)
    return resolved == root or root in resolved.parents


def inspect_mac_paths(
    body: bytes,
    root: Path,
    ignored_pids: frozenset[int],
    cwd_blocker_pids: frozenset[int],
    deadline: float,
) -> tuple[set[int], set[PathBlocker]]:
    """Preserve the complete original lsof field/path interpretation and bounds."""
    try:
        _remaining(deadline)
        if len(body) > _MAX_BODY_BYTES or not body.endswith((b"\0", b"\0\n")):
            raise LocalPathObservationError
        covered: set[int] = set()
        blockers: set[PathBlocker] = set()
        pid: int | None = None
        descriptor: str | None = None
        file_type: str | None = None
        process_count, file_count = 0, 0
        for raw in body.split(b"\0"):
            _remaining(deadline)
            field = raw.removeprefix(b"\n")
            if not field:
                continue
            tag, value = chr(field[0]), field[1:].decode("utf-8", errors="strict")
            if tag == "p":
                if not value.isdigit() or process_count >= _MAX_PROCESSES:
                    raise LocalPathObservationError
                process_count += 1
                pid, descriptor, file_type = int(value), None, None
            elif tag == "f":
                if pid is None or file_count >= _MAX_FILES:
                    raise LocalPathObservationError
                file_count += 1
                descriptor, file_type = value, None
            elif tag == "t":
                file_type = value
            elif tag == "n":
                if pid is None or descriptor is None:
                    raise LocalPathObservationError
                if "(stat:" in value or "(readlink:" in value:
                    raise LocalPathObservationError
                if descriptor == "cwd":
                    if not value.startswith("/") or file_type != "DIR":
                        raise LocalPathObservationError
                    covered.add(pid)
                if (
                    pid not in ignored_pids
                    and _covers(value, root, deadline)
                    and (descriptor != "cwd" or pid in cwd_blocker_pids)
                ):
                    blockers.add("WORKTREE_PROCESS_ACTIVE")
            else:
                raise LocalPathObservationError
        _remaining(deadline)
        return covered, blockers
    except (OSError, ValueError, RuntimeError):
        raise LocalPathObservationError from None


def observe_mac_paths_in_process(
    body: bytes,
    root: Path,
    ignored_pids: frozenset[int],
    cwd_blocker_pids: frozenset[int],
    deadline: float,
) -> tuple[set[int], set[PathBlocker]]:
    """Run only the fixed parser child; uncertainty is never an empty observation."""
    try:
        _remaining(deadline)
        request = MacPathObservationRequest.create(
            body, root, ignored_pids, cwd_blocker_pids, deadline
        )
        raw_request = request.encode()
        _remaining(deadline)
        with (
            tempfile.TemporaryFile() as source,
            tempfile.TemporaryFile() as output,
            tempfile.TemporaryFile() as errors,
        ):
            source.write(raw_request)
            source.seek(0)
            _remaining(deadline)
            spawned = spawn_owned_query(
                (
                    sys.executable,
                    "-I",
                    "-S",
                    "-B",
                    str(Path(__file__).with_name("local_path_worker.py")),
                ),
                environment=_ENVIRONMENT,
                cwd=Path("/"),
                stdin=source.fileno(),
                stdout=output,
                stderr=errors,
            )
            process, original = spawned.process, spawned.observation
            try:
                process.wait(timeout=_remaining(deadline))
                _remaining(deadline)
                if process.returncode or errors.tell() or output.tell() > _MAX_RESULT_BYTES:
                    raise LocalPathObservationError
                output.seek(0)
                result = MacPathObservationResult.decode(output.read(_MAX_RESULT_BYTES + 1))
                if result.request_sha256 != request.request_sha256:
                    raise LocalPathObservationError
                _remaining(deadline)
            finally:
                # The complete streams are private files, never inherited pipes.
                # Always finalize the exact ownership captured before target exec.
                finish_owned_process(process, original, output_drained=True)
            _remaining(deadline)
            return set(result.covered_pids), set(result.blockers)
    except Exception:
        raise LocalPathObservationError from None
