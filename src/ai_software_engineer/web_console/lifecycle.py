"""Controlled file handshake for applying saved Web Console configuration."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Annotated, Protocol

from pydantic import Field, StringConstraints, model_validator

from ai_software_engineer.domain.model import DomainModel, NonEmptyStr

ConfigurationApplyRequestId = Annotated[
    str, StringConstraints(pattern=r"^configuration_apply_[a-f0-9]{32}$")
]


class ConfigurationApplyError(RuntimeError):
    """A configuration apply request could not be recorded safely."""


class ConfigurationApplyStatus(StrEnum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ApplyConfigurationRequest(DomainModel):
    """An intentionally empty browser command."""


class ConfigurationApplyState(DomainModel):
    request_id: ConfigurationApplyRequestId
    status: ConfigurationApplyStatus
    safe_summary: NonEmptyStr

    @model_validator(mode="after")
    def fixed_summary(self) -> ConfigurationApplyState:
        expected = {
            ConfigurationApplyStatus.PENDING: "Configuration apply is in progress.",
            ConfigurationApplyStatus.SUCCEEDED: "Configuration was applied.",
            ConfigurationApplyStatus.FAILED: (
                "Configuration remains saved but the Console could not be restarted. "
                "Use the service script to inspect status and retry safely."
            ),
        }
        if self.safe_summary != expected[self.status]:
            raise ValueError("configuration apply summary must use the safe fixed text")
        return self


class ConfigurationApplyView(ConfigurationApplyState):
    """Browser-safe lifecycle state plus the server-selected reconnect port."""

    effective_console_port: Annotated[int, Field(ge=1, le=65535)]

    @classmethod
    def from_state(
        cls, state: ConfigurationApplyState, *, effective_console_port: int
    ) -> ConfigurationApplyView:
        return cls(**state.model_dump(), effective_console_port=effective_console_port)


class ConfigurationLifecycle(Protocol):
    def request(self, token_sha256: str) -> ConfigurationApplyState: ...
    def current(self) -> ConfigurationApplyState | None: ...


class SupervisorProcessProbe(Protocol):
    def matches(self, pid: int, script: Path) -> bool: ...


class PsSupervisorProcessProbe:
    """Verify the live supervisor command without invoking a shell."""

    def matches(self, pid: int, script: Path) -> bool:
        try:
            result = subprocess.run(
                ("ps", "-p", str(pid), "-o", "command="),
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode != 0:
                return False
            arguments = shlex.split(result.stdout.strip())
        except (OSError, subprocess.SubprocessError, ValueError):
            return False
        return len(arguments) >= 2 and arguments[-2:] == [str(script), "supervise"]


class FileConfigurationLifecycle:
    """Persist one idempotent request for the fixed local service supervisor."""

    def __init__(
        self,
        state_directory: Path,
        *,
        supervisor_process_probe: SupervisorProcessProbe | None = None,
    ) -> None:
        self._root = state_directory.expanduser().absolute()
        self._state = self._root / "configuration-apply.json"
        self._request = self._root / "configuration-apply.request"
        self._supervisor_pid = self._root / "ase-console-supervisor.pid"
        self._supervisor_process_probe = supervisor_process_probe or PsSupervisorProcessProbe()
        self._lock = Lock()

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> FileConfigurationLifecycle:
        configured = environment.get("ASE_SERVICE_STATE_DIR")
        if configured is not None:
            root = Path(configured)
        else:
            state_home = environment.get("XDG_STATE_HOME")
            if state_home is None:
                home = environment.get("HOME")
                if home is None:
                    raise ConfigurationApplyError("Configuration apply service is unavailable.")
                state_home = str(Path(home) / ".local" / "state")
            root = Path(state_home) / "ai-software-engineer"
        if not root.is_absolute() or root == Path("/"):
            raise ConfigurationApplyError("Configuration apply service is unavailable.")
        return cls(root)

    def request(self, token_sha256: str) -> ConfigurationApplyState:
        if len(token_sha256) != 64 or any(
            value not in "0123456789abcdef" for value in token_sha256
        ):
            raise ConfigurationApplyError("Configuration apply request is invalid.")
        with self._lock:
            self._require_supervisor()
            current = self._load_state()
            request_id = f"configuration_apply_{token_sha256[:32]}"
            if current is not None and current.request_id == request_id:
                if current.status is ConfigurationApplyStatus.PENDING:
                    self._publish_request(current)
                return current
            if current is not None and current.status is ConfigurationApplyStatus.PENDING:
                self._publish_request(current)
                return current
            if self._request.exists() or self._request.is_symlink():
                if self._request.is_symlink() or not self._request.is_file():
                    raise ConfigurationApplyError("Configuration apply service is unavailable.")
                if current is not None:
                    return current
                raise ConfigurationApplyError("Configuration apply service is unavailable.")
            state = ConfigurationApplyState(
                request_id=request_id,
                status=ConfigurationApplyStatus.PENDING,
                safe_summary="Configuration apply is in progress.",
            )
            self._write_state(state)
            self._publish_request(state)
            return state

    def _publish_request(self, state: ConfigurationApplyState) -> None:
        if self._request.exists() or self._request.is_symlink():
            if self._request.is_symlink() or not self._request.is_file():
                raise ConfigurationApplyError("Configuration apply service is unavailable.")
            try:
                recorded_request = self._request.read_text(encoding="ascii")
            except OSError as error:
                raise ConfigurationApplyError(
                    "Configuration apply service is unavailable."
                ) from error
            if recorded_request == state.request_id + "\n":
                return
            raise ConfigurationApplyError("Configuration apply service is unavailable.")
        try:
            descriptor = os.open(
                self._request,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                stream.write(state.request_id + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            try:
                recorded_request = self._request.read_text(encoding="ascii")
            except OSError as error:
                raise ConfigurationApplyError(
                    "Configuration apply service is unavailable."
                ) from error
            if recorded_request != state.request_id + "\n":
                raise ConfigurationApplyError(
                    "Configuration apply service is unavailable."
                ) from None
        except OSError as error:
            failed = ConfigurationApplyState(
                request_id=state.request_id,
                status=ConfigurationApplyStatus.FAILED,
                safe_summary=(
                    "Configuration remains saved but the Console could not be restarted. "
                    "Use the service script to inspect status and retry safely."
                ),
            )
            self._write_state(failed)
            raise ConfigurationApplyError("Configuration apply service is unavailable.") from error

    def current(self) -> ConfigurationApplyState | None:
        with self._lock:
            self._require_safe_root()
            return self._load_state()

    def _require_supervisor(self) -> None:
        try:
            self._require_safe_root()
            if self._supervisor_pid.is_symlink() or not self._supervisor_pid.is_file():
                raise OSError("unsafe supervisor PID file")
            lines = self._supervisor_pid.read_text(encoding="utf-8").splitlines()
            if len(lines) != 2 or not lines[0].isdecimal() or int(lines[0]) <= 1:
                raise OSError("invalid supervisor PID")
            script = Path(lines[1])
            if (
                not script.is_absolute()
                or script.name != "ase-console-service.sh"
                or script.is_symlink()
                or not script.is_file()
            ):
                raise OSError("invalid supervisor identity")
            pid = int(lines[0])
            os.kill(pid, 0)
            if not self._supervisor_process_probe.matches(pid, script):
                raise OSError("live process does not match supervisor identity")
        except (OSError, ValueError) as error:
            raise ConfigurationApplyError("Configuration apply service is unavailable.") from error

    def _require_safe_root(self) -> None:
        if self._root == Path("/") or self._root.is_symlink() or not self._root.is_dir():
            raise ConfigurationApplyError("Configuration apply service is unavailable.")

    def _load_state(self) -> ConfigurationApplyState | None:
        try:
            if not self._state.exists():
                return None
            if self._state.is_symlink() or not self._state.is_file():
                raise OSError("unsafe lifecycle state")
            return ConfigurationApplyState.model_validate_json(
                self._state.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            raise ConfigurationApplyError("Configuration apply state is unavailable.") from error

    def _write_state(self, state: ConfigurationApplyState) -> None:
        try:
            descriptor, temporary = tempfile.mkstemp(prefix=".configuration-apply-", dir=self._root)
            temporary_path = Path(temporary)
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(state.model_dump(mode="json"), stream, sort_keys=True)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary_path.replace(self._state)
            finally:
                temporary_path.unlink(missing_ok=True)
        except OSError as error:
            raise ConfigurationApplyError("Configuration apply state is unavailable.") from error


__all__ = [
    "ApplyConfigurationRequest",
    "ConfigurationApplyError",
    "ConfigurationApplyState",
    "ConfigurationApplyStatus",
    "ConfigurationApplyView",
    "ConfigurationLifecycle",
    "FileConfigurationLifecycle",
    "PsSupervisorProcessProbe",
    "SupervisorProcessProbe",
]
