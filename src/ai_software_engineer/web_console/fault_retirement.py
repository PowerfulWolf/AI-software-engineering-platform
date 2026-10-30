"""Trusted local fault termination permits only a durable inspection successor.

This executor kills only the exact frozen Host writer. Historical executions and scope
remain UNKNOWN. No network/role tool imports this authority; records cannot select a PID.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import shlex
import signal
import stat
import subprocess
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictInt, model_validator

from ai_software_engineer.config.production import ProductionConfig
from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.owned_sessions import (
    OwnedProcessIdentity,
    current_process_birth_at,
    current_process_executable,
    observe_current_process,
)
from ai_software_engineer.project_workspace import ProjectManifest
from ai_software_engineer.team_workspace import TeamManifest

from .maintenance_epoch_models import PreviousMaintenanceEpoch
from .maintenance_names import COMPLETION_RECEIPT_NAME, NORMAL_ADMISSION_NAME
from .service_lifecycle import (
    ServiceInstance,
    ServiceInstanceId,
    ServiceLifecycleError,
    ServiceLifecycleStore,
    ServiceShutdownAction,
    ServiceShutdownRequest,
    ServiceShutdownResult,
    ServiceState,
)

_ERROR = "故障服务替换事实无法核验; 保留原记录, 不启动替代服务。"
MARKER_NAME = "console-inspection.json"
type OriginalName = Literal[
    "ase-console.pid",
    "console-service-instance.json",
    "console-service-shutdown.request.json",
    "console-service-shutdown.result.json",
]
_ORIGINALS: tuple[OriginalName, ...] = (
    "ase-console.pid",
    "console-service-instance.json",
    "console-service-shutdown.request.json",
    "console-service-shutdown.result.json",
)
_BOUND = 2 * 1024 * 1024


class FaultRetirementError(ServiceLifecycleError):
    """Fixed safe maintenance refusal, without untrusted bodies or credentials."""


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class _Record(DomainModel):
    schema_version: Literal["v1"] = "v1"
    recorded_at: AwareDatetime
    record_sha256: Sha256

    @classmethod
    def create(cls, **values: object) -> Self:
        value = cls.model_validate({**values, "record_sha256": "0" * 64})
        return value.model_copy(update={"record_sha256": value.digest()})

    def digest(self) -> str:
        return _sha(
            json.dumps(
                self.model_dump(mode="json", exclude={"record_sha256"}),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        )

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.record_sha256 != self.digest():
            raise FaultRetirementError(_ERROR)


class OriginalFile(DomainModel):
    name: Literal[
        "ase-console.pid",
        "console-service-instance.json",
        "console-service-shutdown.request.json",
        "console-service-shutdown.result.json",
    ]
    sha256: Sha256
    byte_count: Annotated[StrictInt, Field(gt=0, le=8192)]


class CatalogScope(DomainModel):
    """Diagnostic discovery only; not current execution absence or delivery authority."""

    platform_root: str
    config_sha256: Sha256
    manifest_sha256s: Annotated[tuple[Sha256, ...], Field(max_length=4096)]
    observation: Literal["CATALOG_OBSERVED", "CATALOG_UNAVAILABLE"]
    execution_completeness: Literal["UNKNOWN"] = "UNKNOWN"


class SupervisorIdentity(DomainModel):
    process: OwnedProcessIdentity
    pid_file_sha256: Sha256
    pid_file_mtime_ns: Annotated[StrictInt, Field(gt=0)]
    script: str


class FaultRetirementPlan(_Record):
    kind: Literal["inspection_fault_retirement_plan"] = "inspection_fault_retirement_plan"
    instance: ServiceInstance
    request: ServiceShutdownRequest
    result: ServiceShutdownResult
    originals: tuple[OriginalFile, ...]
    boot_sha256: Sha256
    process: OwnedProcessIdentity
    principal_uid: Annotated[StrictInt, Field(ge=0)]
    log_device: Annotated[StrictInt, Field(ge=0)]
    log_inode: Annotated[StrictInt, Field(gt=0)]
    log_byte_count: Annotated[StrictInt, Field(ge=0)]
    scope: CatalogScope
    supervisor: SupervisorIdentity | None = None
    previous_maintenance: PreviousMaintenanceEpoch | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    successor_mode: Literal["inspection"] = "inspection"
    historical_execution_outcome: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def exact_fault(self) -> Self:
        if (
            self.instance.state is not ServiceState.REFUSED
            or self.result.state is not ServiceState.REFUSED
            or self.request.action is not ServiceShutdownAction.SHUTDOWN
            or not self.request.matches(self.instance)
            or not self.result.matches(self.request)
            or self.result.recorded_at != self.instance.updated_at
            or self.result.recorded_at < self.request.requested_at
            or self.recorded_at < self.result.recorded_at
            or self.process.process_id != self.instance.pid
            or tuple(f.name for f in self.originals) != _ORIGINALS
            or (
                self.instance.config_path is not None
                and (
                    self.instance.platform_root != self.scope.platform_root
                    or self.instance.config_sha256 != self.scope.config_sha256
                )
            )
        ):
            raise ValueError(_ERROR)
        return self


class FaultRetirementReceipt(_Record):
    kind: Literal["inspection_fault_retirement_receipt"] = "inspection_fault_retirement_receipt"
    plan_sha256: Sha256
    instance_id: ServiceInstanceId
    principal_uid: Annotated[StrictInt, Field(ge=0)]
    signal: Literal["SIGKILL"] = "SIGKILL"
    signal_sent: Literal["CONFIRMED", "UNKNOWN"]
    execution_scope_completeness: Literal["UNKNOWN"] = "UNKNOWN"
    maintenance_started_at: AwareDatetime
    host_absence_observed_at: AwareDatetime
    signal_sent_at: AwareDatetime | None = None
    log_sha256: Sha256
    log_byte_count: Annotated[StrictInt, Field(ge=0)]
    historical_state: Literal["REFUSED"] = "REFUSED"
    historical_execution_outcome: Literal["UNKNOWN"] = "UNKNOWN"
    successor_mode: Literal["inspection"] = "inspection"

    @model_validator(mode="after")
    def action_before_receipt(self) -> Self:
        if (
            self.maintenance_started_at > self.host_absence_observed_at
            or self.host_absence_observed_at > self.recorded_at
            or (self.signal_sent == "CONFIRMED") != (self.signal_sent_at is not None)
            or (
                self.signal_sent_at is not None
                and not self.maintenance_started_at
                <= self.signal_sent_at
                <= self.host_absence_observed_at
            )
        ):
            raise ValueError(_ERROR)
        return self


class InspectionMarker(_Record):
    kind: Literal["persistent_console_inspection"] = "persistent_console_inspection"
    plan_sha256: Sha256
    receipt_sha256: Sha256
    successor_mode: Literal["inspection"] = "inspection"
    historical_execution_outcome: Literal["UNKNOWN"] = "UNKNOWN"


@contextmanager
def _directory(path: Path, *, private: bool = False) -> Iterator[int]:
    before = path.lstat()
    if (
        not stat.S_ISDIR(before.st_mode)
        or before.st_uid != os.getuid()
        or before.st_mode & 0o022
        or (private and stat.S_IMODE(before.st_mode) != 0o700)
    ):
        raise FaultRetirementError(_ERROR)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise FaultRetirementError(_ERROR)
        yield descriptor
        after = path.lstat()
        if (opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino):
            raise FaultRetirementError(_ERROR)
    finally:
        os.close(descriptor)


def _read(root: Path, name: str, *, bound: int = _BOUND, private: bool = True) -> bytes:
    with _directory(root) as directory:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1
                or metadata.st_size > bound
                or metadata.st_mode & 0o022
                or (private and stat.S_IMODE(metadata.st_mode) != 0o600)
            ):
                raise FaultRetirementError(_ERROR)
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                body = stream.read(bound + 1)
            if not body or len(body) > bound:
                raise FaultRetirementError(_ERROR)
            return body
        finally:
            if descriptor >= 0:
                os.close(descriptor)


def _publish(root: Path, name: str, body: bytes) -> None:
    if not body or len(body) > _BOUND:
        raise FaultRetirementError(_ERROR)
    with _directory(root) as directory:
        temporary = ".pending-" + uuid.uuid4().hex
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            with suppress(FileExistsError):
                os.link(
                    temporary,
                    name,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=directory)
            os.fsync(directory)
    if _read(root, name) != body:
        raise FaultRetirementError(_ERROR)


def _save(root: Path, name: str, record: _Record) -> None:
    record.validate_integrity()
    _publish(root, name, record.model_dump_json().encode())


def _load[RecordT: _Record](root: Path, name: str, model: type[RecordT]) -> RecordT:
    value = model.model_validate_json(_read(root, name))
    value.validate_integrity()
    return value


@contextmanager
def replacement_lock(root: Path) -> Iterator[int]:
    """Same nonblocking lock as normal service start/stop/configuration apply."""
    with _directory(root) as directory:
        descriptor = os.open(
            "console-service-replacement.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_nlink != 1
            ):
                raise FaultRetirementError(_ERROR)
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield descriptor
        finally:
            os.close(descriptor)


def _archive_root(root: Path, digest: str, *, create: bool = False) -> Path:
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise FaultRetirementError(_ERROR)
    base = root / "console-fault-retirements"
    with _directory(root) as directory:
        if create and not base.exists():
            base.mkdir(mode=0o700)
            os.fsync(directory)
    with _directory(base, private=True) as directory:
        target = base / digest
        if create and not target.exists():
            target.mkdir(mode=0o700)
            os.fsync(directory)
    with _directory(target, private=True):
        return target


def _kernel(plan: FaultRetirementPlan, *, absent: bool = False) -> None:
    boot, process = observe_current_process(plan.instance.pid)
    if _sha(boot.encode()) != plan.boot_sha256 or (
        process is not None if absent else process != plan.process
    ):
        raise FaultRetirementError(_ERROR)
    if not absent:
        result = subprocess.run(
            ("/bin/ps", "-p", str(plan.instance.pid), "-o", "state="),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": os.defpath, "LC_ALL": "C"},
            shell=False,
            timeout=2,
            check=False,
        )
        if (
            result.returncode != 0
            or len(result.stdout) > 64
            or not result.stdout.strip().startswith(b"T")
        ):
            raise FaultRetirementError(_ERROR)
        after_boot, after_process = observe_current_process(plan.instance.pid)
        if boot != after_boot or process != after_process:
            raise FaultRetirementError(_ERROR)


def _argv(pid: int) -> tuple[str, ...]:
    value = subprocess.run(
        ("/bin/ps", "-p", str(pid), "-o", "command="),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env={"PATH": os.defpath, "LC_ALL": "C"},
        shell=False,
        timeout=2,
        check=False,
    )
    if value.returncode != 0 or value.stderr or len(value.stdout) > 8192:
        raise FaultRetirementError(_ERROR)
    return tuple(shlex.split(value.stdout.decode().strip()))


def _birth_window(process: OwnedProcessIdentity, published_at: datetime) -> None:
    birth = current_process_birth_at(process)
    if not birth <= published_at <= birth + timedelta(seconds=60):
        raise FaultRetirementError(_ERROR)


def _require_host_executable(root: Path, plan: FaultRetirementPlan) -> None:
    lines = _read(root, "ase-console.pid", bound=8192, private=False).decode().splitlines()
    entry = Path(lines[1])
    if entry.is_symlink() or not entry.is_file() or entry.stat().st_mode & 0o022:
        raise FaultRetirementError(_ERROR)
    argv = _argv(plan.instance.pid)
    expected = entry.parent / "python"
    if (
        len(argv) != 2
        or argv[1] != str(entry)
        or Path(argv[0]).resolve() != expected.resolve()
        or current_process_executable(plan.instance.pid).resolve() != expected.resolve()
    ):
        raise FaultRetirementError(_ERROR)
    _birth_window(plan.process, plan.instance.started_at)
    _kernel(plan)


def _collect_supervisor(root: Path) -> SupervisorIdentity | None:
    path = root / "ase-console-supervisor.pid"
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    body = _read(root, path.name, bound=8192, private=False)
    lines = body.decode().splitlines()
    if len(lines) != 2 or not lines[0].isdecimal():
        raise FaultRetirementError(_ERROR)
    pid = int(lines[0])
    script = Path(lines[1])
    if (
        not script.is_absolute()
        or script.is_symlink()
        or not script.is_file()
        or script.name != "ase-console-service.sh"
        or script.stat().st_mode & 0o022
    ):
        raise FaultRetirementError(_ERROR)
    _, process = observe_current_process(pid)
    if process is None:
        raise FaultRetirementError(_ERROR)
    _birth_window(process, datetime.fromtimestamp(metadata.st_mtime_ns / 1_000_000_000, UTC))
    value = SupervisorIdentity(
        process=process,
        pid_file_sha256=_sha(body),
        pid_file_mtime_ns=metadata.st_mtime_ns,
        script=str(script),
    )
    _require_supervisor(value)
    return value


def _require_supervisor(value: SupervisorIdentity) -> None:
    _, current = observe_current_process(value.process.process_id)
    if current != value.process:
        raise FaultRetirementError(_ERROR)
    argv = _argv(value.process.process_id)
    if (
        len(argv) != 3
        or argv[1:] != (value.script, "supervise")
        or Path(argv[0]).resolve() != Path("/bin/sh").resolve()
        or current_process_executable(value.process.process_id).resolve()
        not in (
            {Path("/bin/sh").resolve(), Path("/bin/bash").resolve()}
            if platform.system() == "Darwin"
            else {Path("/bin/sh").resolve()}
        )
    ):
        raise FaultRetirementError(_ERROR)


def _stop_supervisor(archive: Path, plan: FaultRetirementPlan) -> None:
    if plan.supervisor is None:
        return
    value = plan.supervisor
    body = _read(archive, "ase-console-supervisor.pid", bound=8192)
    if _sha(body) != value.pid_file_sha256:
        raise FaultRetirementError(_ERROR)
    boot, current = observe_current_process(value.process.process_id)
    if _sha(boot.encode()) != plan.boot_sha256:
        raise FaultRetirementError(_ERROR)
    if current is None:
        return
    _require_supervisor(value)
    os.kill(value.process.process_id, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        boot, current = observe_current_process(value.process.process_id)
        if _sha(boot.encode()) != plan.boot_sha256 or (
            current is not None and current != value.process
        ):
            raise FaultRetirementError(_ERROR)
        if current is None:
            return
        time.sleep(0.05)
    raise FaultRetirementError(_ERROR)


def _require_no_log_writers(archive: Path) -> None:
    """Complete successful fixed private-directory survey plus observed own sentinel."""
    probe = ".log-writer-survey"
    _publish(archive, probe, b"fixed trusted survey sentinel")
    deadline = time.monotonic() + 3
    with _directory(archive, private=True) as directory:
        descriptor = os.open(probe, os.O_RDWR | os.O_NOFOLLOW, dir_fd=directory)
        try:
            while True:
                value = subprocess.run(
                    ("/usr/sbin/lsof", "-nP", "-Fpan", "+d", str(archive)),
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    env={"PATH": os.defpath, "LC_ALL": "C"},
                    shell=False,
                    timeout=5,
                    check=False,
                )
                # Darwin lsof returns 1 for unmatched (closed) files even
                # with a successful +d survey and positive open sentinel.
                # Neither 0 nor 1 is sufficient without complete parsing below.
                if value.returncode not in {0, 1} or value.stderr or len(value.stdout) > _BOUND:
                    raise FaultRetirementError(_ERROR)
                pid = None
                file_descriptor = None
                access = None
                observed_probe = False
                writer = False
                for line in value.stdout.decode().splitlines():
                    if line.startswith("p"):
                        if not line[1:].isdecimal() or int(line[1:]) <= 1:
                            raise FaultRetirementError(_ERROR)
                        pid = int(line[1:])
                        file_descriptor = None
                        access = None
                    elif line.startswith("f"):
                        if pid is None or not line[1:]:
                            raise FaultRetirementError(_ERROR)
                        file_descriptor = line[1:]
                        access = None
                    elif line.startswith("a"):
                        if (
                            file_descriptor is None
                            or access is not None
                            or line[1:] not in {"r", "w", "u"}
                        ):
                            raise FaultRetirementError(_ERROR)
                        access = line[1:]
                    elif line.startswith("n"):
                        name = line[1:]
                        if pid is None or file_descriptor is None:
                            raise FaultRetirementError(_ERROR)
                        if name == str(archive / probe) and pid == os.getpid():
                            if file_descriptor != str(descriptor) or access != "u":
                                raise FaultRetirementError(_ERROR)
                            observed_probe = True
                        elif name == str(archive / "ase-console.log") and access != "r":
                            writer = True
                    else:
                        raise FaultRetirementError(_ERROR)
                if not observed_probe:
                    raise FaultRetirementError(_ERROR)
                if not writer:
                    return
                if time.monotonic() >= deadline:
                    raise FaultRetirementError(
                        "旧日志仍有写入者, 完整归档尚未封存; 可在其退出后用同一计划重试。"
                    )
                time.sleep(0.1)
        finally:
            os.close(descriptor)


def _original_bytes(root: Path) -> tuple[tuple[OriginalFile, bytes], ...]:
    values = []
    for name in _ORIGINALS:
        body = _read(root, name, bound=8192, private=name != "ase-console.pid")
        values.append((OriginalFile(name=name, sha256=_sha(body), byte_count=len(body)), body))
    return tuple(values)


def _require_originals(root: Path, archive: Path, plan: FaultRetirementPlan) -> None:
    for ref in plan.originals:
        for location in (root, archive):
            body = _read(
                location,
                ref.name,
                bound=8192,
                private=location != root or ref.name != "ase-console.pid",
            )
            if len(body) != ref.byte_count or _sha(body) != ref.sha256:
                raise FaultRetirementError(_ERROR)


def _log(root: Path) -> os.stat_result:
    with _directory(root) as directory:
        descriptor = os.open(
            "ase-console.log", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        try:
            value = os.fstat(descriptor)
            if (
                not stat.S_ISREG(value.st_mode)
                or value.st_uid != os.getuid()
                or value.st_nlink != 1
                or value.st_mode & 0o022
            ):
                raise FaultRetirementError(_ERROR)
            return value
        finally:
            os.close(descriptor)


def _catalog(environment: Mapping[str, str]) -> CatalogScope:
    source = ProductionConfig.path_from_environment(environment)
    body = _read(source.parent, source.name, bound=1_000_000, private=False)
    config = ProductionConfig.model_validate_json(body)
    platform = Path(config.platform_root)
    manifests: list[str] = []
    state: Literal["CATALOG_OBSERVED", "CATALOG_UNAVAILABLE"] = "CATALOG_OBSERVED"
    try:
        team_body = _read(platform / "team", "team.json", bound=16000, private=False)
        team = TeamManifest.model_validate_json(team_body)
        team.validate_integrity()
        if (
            team.team_id != config.team_id
            or team.platform_root != str(platform)
            or team.team_root != str(platform / "team")
        ):
            raise FaultRetirementError(_ERROR)
        manifests.append(_sha(team_body))
        project_root = platform / "projects"
        with _directory(project_root):
            projects = tuple(sorted(project_root.iterdir()))
        if len(projects) > 1024:
            raise FaultRetirementError(_ERROR)
        for path in projects:
            if path.name.startswith("."):
                continue
            project_body = _read(path, "project.json", bound=16000, private=False)
            project = ProjectManifest.model_validate_json(project_body)
            project.validate_integrity()
            if (
                project.team_id != team.team_id
                or project.team_manifest_sha256 != team.manifest_sha256
                or project.project_id != path.name
                or project.project_root != str(path)
            ):
                raise FaultRetirementError(_ERROR)
            manifests.append(_sha(project_body))
    except (OSError, ValueError, ServiceLifecycleError):
        state = "CATALOG_UNAVAILABLE"
    return CatalogScope(
        platform_root=str(platform),
        config_sha256=_sha(body),
        manifest_sha256s=tuple(manifests),
        observation=state,
    )


def _require_bound_config(
    environment: Mapping[str, str], instance: ServiceInstance, scope: CatalogScope
) -> None:
    """New Hosts bind their launch config; legacy instances stay explicit UNKNOWN."""
    if instance.config_path is None:
        return
    selected = ProductionConfig.path_from_environment(environment).expanduser().absolute()
    if (
        str(selected) != instance.config_path
        or scope.platform_root != instance.platform_root
        or scope.config_sha256 != instance.config_sha256
    ):
        raise FaultRetirementError(_ERROR)


def prepare_fault_retirement(environment: Mapping[str, str]) -> FaultRetirementPlan:
    """Collect exact current facts itself; no caller-provided Plan or idle declarations."""
    root = ServiceLifecycleStore.from_environment(environment).root
    with replacement_lock(root):
        if inspection_required(environment):
            raise FaultRetirementError(_ERROR)
        from .maintenance_epoch import collect_previous_epoch, save_previous_controls

        previous = collect_previous_epoch(root)
        if previous is not None:
            _verified_marker(root, reserved_epochs=1)
        values = _original_bytes(root)
        bodies = {ref.name: body for ref, body in values}
        instance = ServiceInstance.model_validate_json(bodies["console-service-instance.json"])
        request = ServiceShutdownRequest.model_validate_json(
            bodies["console-service-shutdown.request.json"]
        )
        result = ServiceShutdownResult.model_validate_json(
            bodies["console-service-shutdown.result.json"]
        )
        pid_lines = bodies["ase-console.pid"].decode().splitlines()
        if (
            len(pid_lines) != 2
            or pid_lines[0] != str(instance.pid)
            or not Path(pid_lines[1]).is_absolute()
            or Path(pid_lines[1]).parts[-3:] != (".venv", "bin", "ase-console")
        ):
            raise FaultRetirementError(_ERROR)
        boot, process = observe_current_process(instance.pid)
        if process is None:
            raise FaultRetirementError(_ERROR)
        log = _log(root)
        scope = _catalog(environment)
        _require_bound_config(environment, instance, scope)
        plan = FaultRetirementPlan.create(
            instance=instance,
            request=request,
            result=result,
            originals=tuple(ref for ref, _ in values),
            boot_sha256=_sha(boot.encode()),
            process=process,
            principal_uid=os.getuid(),
            log_device=log.st_dev,
            log_inode=log.st_ino,
            log_byte_count=log.st_size,
            scope=scope,
            supervisor=_collect_supervisor(root),
            previous_maintenance=previous,
            recorded_at=datetime.now(UTC),
        )
        _require_host_executable(root, plan)
        archive = _archive_root(root, plan.record_sha256, create=True)
        for ref, body in values:
            _publish(archive, ref.name, body)
        if plan.supervisor is not None:
            _publish(
                archive,
                "ase-console-supervisor.pid",
                _read(root, "ase-console-supervisor.pid", bound=8192, private=False),
            )
        _require_originals(root, archive, plan)
        save_previous_controls(root, archive, previous)
        _save(archive, "plan.json", plan)
        return plan


def _require_archived_log(
    archive: Path, plan: FaultRetirementPlan, *, repair_mode: bool = False
) -> None:
    with _directory(archive, private=True) as directory:
        descriptor = os.open(
            "ase-console.log", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        try:
            value = os.fstat(descriptor)
            if (
                not stat.S_ISREG(value.st_mode)
                or value.st_uid != os.getuid()
                or value.st_nlink != 1
                or value.st_mode & 0o022
                or (value.st_dev, value.st_ino, value.st_size)
                != (plan.log_device, plan.log_inode, plan.log_byte_count)
            ):
                raise FaultRetirementError(_ERROR)
            if repair_mode:
                os.fchmod(descriptor, 0o600)
                os.fsync(descriptor)
                os.fsync(directory)
            elif stat.S_IMODE(value.st_mode) != 0o600:
                raise FaultRetirementError(_ERROR)
        finally:
            os.close(descriptor)


def _hash_log(archive: Path, expected_size: int) -> str:
    with _directory(archive, private=True) as directory:
        descriptor = os.open(
            "ase-console.log", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.getuid()
                or before.st_nlink != 1
                or before.st_size != expected_size
                or stat.S_IMODE(before.st_mode) != 0o600
            ):
                raise FaultRetirementError(_ERROR)
            digest = hashlib.sha256()
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                after = os.fstat(stream.fileno())
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise FaultRetirementError(_ERROR)
            return digest.hexdigest()
        finally:
            if descriptor >= 0:
                os.close(descriptor)


class TerminationIntent(_Record):
    kind: Literal["exact_host_fault_termination_intent"] = "exact_host_fault_termination_intent"
    plan_sha256: Sha256
    principal_uid: Annotated[StrictInt, Field(ge=0)]
    signal: Literal["SIGKILL"] = "SIGKILL"
    successor_mode: Literal["inspection"] = "inspection"


class SignalSent(_Record):
    kind: Literal["exact_host_fault_signal_sent"] = "exact_host_fault_signal_sent"
    plan_sha256: Sha256


def _finalize(
    root: Path, archive: Path, plan: FaultRetirementPlan, intent: TerminationIntent
) -> FaultRetirementReceipt:
    _kernel(plan, absent=True)
    _require_originals(root, archive, plan)
    sent_path = archive / "signal-sent.json"
    sent: Literal["CONFIRMED", "UNKNOWN"] = "UNKNOWN"
    signal_at = None
    if sent_path.exists():
        record = _load(archive, "signal-sent.json", SignalSent)
        if record.plan_sha256 != plan.record_sha256 or record.recorded_at < intent.recorded_at:
            raise FaultRetirementError(_ERROR)
        sent = "CONFIRMED"
        signal_at = record.recorded_at
    _require_archived_log(archive, plan, repair_mode=True)
    _stop_supervisor(archive, plan)
    _require_no_log_writers(archive)
    log_sha = _hash_log(archive, plan.log_byte_count)
    if (archive / "receipt.json").exists():
        receipt = _load(archive, "receipt.json", FaultRetirementReceipt)
        if (
            receipt.plan_sha256 != plan.record_sha256
            or receipt.log_sha256 != log_sha
            or receipt.principal_uid != os.getuid()
            or receipt.signal_sent != sent
        ):
            raise FaultRetirementError(_ERROR)
    else:
        receipt = FaultRetirementReceipt.create(
            plan_sha256=plan.record_sha256,
            instance_id=plan.instance.instance_id,
            principal_uid=os.getuid(),
            maintenance_started_at=intent.recorded_at,
            host_absence_observed_at=datetime.now(UTC),
            signal_sent_at=signal_at,
            signal_sent=sent,
            log_sha256=log_sha,
            log_byte_count=plan.log_byte_count,
            recorded_at=datetime.now(UTC),
        )
        _save(archive, "receipt.json", receipt)
    _require_originals(root, archive, plan)
    _kernel(plan, absent=True)
    if plan.previous_maintenance is not None:
        from .maintenance_epoch import finalize_epoch

        finalize_epoch(root, archive, plan, receipt)
    elif (root / MARKER_NAME).exists():
        marker = _load(root, MARKER_NAME, InspectionMarker)
        if (
            marker.plan_sha256 != plan.record_sha256
            or marker.receipt_sha256 != receipt.record_sha256
        ):
            raise FaultRetirementError(_ERROR)
    else:
        if (archive / "marker.json").exists():
            marker = _load(archive, "marker.json", InspectionMarker)
            if (
                marker.plan_sha256 != plan.record_sha256
                or marker.receipt_sha256 != receipt.record_sha256
            ):
                raise FaultRetirementError(_ERROR)
        else:
            marker = InspectionMarker.create(
                plan_sha256=plan.record_sha256,
                receipt_sha256=receipt.record_sha256,
                recorded_at=datetime.now(UTC),
            )
            _save(archive, "marker.json", marker)
        _save(root, MARKER_NAME, marker)
    return receipt


def execute_fault_retirement(
    environment: Mapping[str, str], *, plan_sha256: str, confirm_fault_retirement: bool
) -> FaultRetirementReceipt:
    """Actual local action. Retry finalizes the same archive without signaling another PID."""
    if confirm_fault_retirement is not True:
        raise FaultRetirementError(_ERROR)
    root = ServiceLifecycleStore.from_environment(environment).root
    with replacement_lock(root):
        archive = _archive_root(root, plan_sha256)
        plan = _load(archive, "plan.json", FaultRetirementPlan)
        if plan.record_sha256 != plan_sha256 or plan.principal_uid != os.getuid():
            raise FaultRetirementError(_ERROR)
        _require_originals(root, archive, plan)
        current_scope = _catalog(environment)
        _require_bound_config(environment, plan.instance, current_scope)
        if current_scope.config_sha256 != plan.scope.config_sha256:
            raise FaultRetirementError(_ERROR)
        if plan.previous_maintenance is not None:
            from .maintenance_epoch import begin_epoch

            begin_epoch(root, archive, plan)
        if (archive / "termination-intent.json").exists():
            intent = _load(archive, "termination-intent.json", TerminationIntent)
            if (
                intent.plan_sha256 != plan.record_sha256
                or intent.principal_uid != os.getuid()
                or intent.recorded_at < plan.recorded_at
            ):
                raise FaultRetirementError(_ERROR)
        else:
            _kernel(plan)
            intent = TerminationIntent.create(
                plan_sha256=plan.record_sha256,
                principal_uid=os.getuid(),
                recorded_at=datetime.now(UTC),
            )
            _save(archive, "termination-intent.json", intent)
        boot, current = observe_current_process(plan.instance.pid)
        if _sha(boot.encode()) != plan.boot_sha256:
            raise FaultRetirementError(_ERROR)
        if current is None:
            # A previous exact authorized attempt may have ended before sealing
            # signal acknowledgement. Preserve UNKNOWN if that fact was not saved.
            return _finalize(root, archive, plan, intent)
        _require_host_executable(root, plan)
        if (archive / "ase-console.log").exists() or (archive / "ase-console.log").is_symlink():
            _require_archived_log(archive, plan, repair_mode=True)
        else:
            log = _log(root)
            if (log.st_dev, log.st_ino, log.st_size) != (
                plan.log_device,
                plan.log_inode,
                plan.log_byte_count,
            ):
                raise FaultRetirementError(_ERROR)
        _stop_supervisor(archive, plan)
        _kernel(plan)
        if not (archive / "ase-console.log").exists():
            log = _log(root)
            if (log.st_dev, log.st_ino, log.st_size) != (
                plan.log_device,
                plan.log_inode,
                plan.log_byte_count,
            ):
                raise FaultRetirementError(_ERROR)
            with _directory(root) as source, _directory(archive, private=True) as target:
                os.rename(
                    "ase-console.log", "ase-console.log", src_dir_fd=source, dst_dir_fd=target
                )
                os.chmod("ase-console.log", 0o600, dir_fd=target, follow_symlinks=False)
                os.fsync(source)
                os.fsync(target)
        _require_archived_log(archive, plan, repair_mode=True)
        _require_originals(root, archive, plan)
        _kernel(plan)
        os.kill(plan.instance.pid, signal.SIGKILL)
        sent = SignalSent.create(plan_sha256=plan.record_sha256, recorded_at=datetime.now(UTC))
        _save(archive, "signal-sent.json", sent)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            boot, current = observe_current_process(plan.instance.pid)
            if _sha(boot.encode()) != plan.boot_sha256:
                raise FaultRetirementError(_ERROR)
            if current is None:
                return _finalize(root, archive, plan, intent)
            if current != plan.process:
                raise FaultRetirementError(_ERROR)
            time.sleep(0.05)
        raise FaultRetirementError(_ERROR)


def _verified_marker(
    root: Path,
    *,
    marker: InspectionMarker | None = None,
    visited: tuple[str, ...] = (),
    reserved_epochs: int = 0,
) -> tuple[FaultRetirementPlan, FaultRetirementReceipt]:
    marker = marker or _load(root, MARKER_NAME, InspectionMarker)
    if marker.plan_sha256 in visited or len(visited) + reserved_epochs >= 128:
        raise FaultRetirementError(_ERROR)
    archive = _archive_root(root, marker.plan_sha256)
    plan = _load(archive, "plan.json", FaultRetirementPlan)
    receipt = _load(archive, "receipt.json", FaultRetirementReceipt)
    intent = _load(archive, "termination-intent.json", TerminationIntent)
    if (
        intent.plan_sha256 != plan.record_sha256
        or intent.principal_uid != plan.principal_uid
        or intent.recorded_at != receipt.maintenance_started_at
    ):
        raise FaultRetirementError(_ERROR)
    if receipt.signal_sent == "CONFIRMED":
        ack = _load(archive, "signal-sent.json", SignalSent)
        if ack.plan_sha256 != plan.record_sha256 or ack.recorded_at != receipt.signal_sent_at:
            raise FaultRetirementError(_ERROR)
    if (
        plan.record_sha256 != marker.plan_sha256
        or receipt.record_sha256 != marker.receipt_sha256
        or receipt.plan_sha256 != plan.record_sha256
        or receipt.instance_id != plan.instance.instance_id
        or receipt.principal_uid != plan.principal_uid
        or receipt.maintenance_started_at < plan.recorded_at
        or receipt.recorded_at > marker.recorded_at
        or receipt.log_byte_count != plan.log_byte_count
    ):
        raise FaultRetirementError(_ERROR)
    # Normal launches replace the mutable lifecycle files, but never this archive.
    for ref in plan.originals:
        body = _read(archive, ref.name, bound=8192)
        if len(body) != ref.byte_count or _sha(body) != ref.sha256:
            raise FaultRetirementError(_ERROR)
    if plan.previous_maintenance is not None:
        from .maintenance_epoch import verify_previous_epoch

        prior = verify_previous_epoch(archive, plan.previous_maintenance)
        _verified_marker(
            root,
            marker=prior,
            visited=(*visited, marker.plan_sha256),
            reserved_epochs=reserved_epochs,
        )
    # Logs are diagnostic retention, not startup or delivery authority. Their full
    # digest was sealed at retirement; a separate explicit audit can read them.
    return plan, receipt


def verify_retired_log(environment: Mapping[str, str]) -> FaultRetirementReceipt:
    """Explicit diagnostic audit; never a startup or maintenance-completion gate."""
    root = ServiceLifecycleStore.from_environment(environment).root
    plan, receipt = _verified_marker(root)
    archive = _archive_root(root, plan.record_sha256)
    _require_archived_log(archive, plan)
    if _hash_log(archive, receipt.log_byte_count) != receipt.log_sha256:
        raise FaultRetirementError(_ERROR)
    return receipt


def inspection_required(environment: Mapping[str, str]) -> bool:
    """Persistent inspection only. Malformed markers fail closed before writers exist."""
    root = ServiceLifecycleStore.from_environment(environment).root
    try:
        (root / MARKER_NAME).lstat()
    except FileNotFoundError:
        for name in (COMPLETION_RECEIPT_NAME, NORMAL_ADMISSION_NAME):
            try:
                (root / name).lstat()
            except FileNotFoundError:
                continue
            raise FaultRetirementError(_ERROR) from None
        return False
    try:
        _verified_marker(root)
        from .maintenance_completion import verified_completion

        return verified_completion(root) is None
    except (OSError, ValueError, ServiceLifecycleError) as error:
        raise FaultRetirementError(_ERROR) from error


def require_inspection_retirement(
    environment: Mapping[str, str],
    instance: ServiceInstance,
    request: ServiceShutdownRequest | None,
    result: ServiceShutdownResult | None,
) -> None:
    """Fresh exact old-Host absence plus archive admits only inspection startup."""
    root = ServiceLifecycleStore.from_environment(environment).root
    if not inspection_required(environment):
        raise FaultRetirementError(_ERROR)
    try:
        plan, _ = _verified_marker(root)
        if (instance, request, result) != (plan.instance, plan.request, plan.result):
            raise FaultRetirementError(_ERROR)
        _require_originals(root, _archive_root(root, plan.record_sha256), plan)
        _kernel(plan, absent=True)
    except (OSError, ValueError, RuntimeError) as error:
        raise FaultRetirementError(_ERROR) from error
