"""Local runtime-variable persistence for the trusted single-user console."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.config.production import EnvVarName

_ENV_NAME_ADAPTER = TypeAdapter(EnvVarName)
_MAX_FILE_BYTES = 64_000
_MAX_VALUE_CHARACTERS = 8_192
_HEADER = "# Managed by ai-software-engineer. Local single-user runtime values.\n"


class RuntimeEnvironmentError(RuntimeError):
    """Raised when the managed runtime environment cannot be trusted or saved."""


def runtime_environment_path(config_path: str | Path) -> Path:
    """Derive the runtime-variable file from the selected production config."""
    source = Path(config_path).expanduser().absolute()
    return source.parent / "runtime.env"


@dataclass(frozen=True, slots=True)
class LocalRuntimeEnvironmentStore:
    """Read and atomically replace the small allowlisted runtime environment file."""

    path: Path

    def __post_init__(self) -> None:
        normalized = self.path.expanduser().absolute()
        if normalized.name != "runtime.env":
            raise RuntimeEnvironmentError("runtime environment file must be named runtime.env")
        object.__setattr__(self, "path", normalized)

    def load(self) -> dict[str, str]:
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise RuntimeEnvironmentError("runtime environment path is not a regular file")
        if not self.path.exists():
            return {}
        try:
            raw = self.path.read_bytes()
        except OSError as error:
            raise RuntimeEnvironmentError("runtime environment could not be read") from error
        if len(raw) > _MAX_FILE_BYTES:
            raise RuntimeEnvironmentError("runtime environment exceeds the size limit")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RuntimeEnvironmentError("runtime environment is not UTF-8") from error
        values: dict[str, str] = {}
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            name, separator, encoded = line.partition("=")
            try:
                validated_name = _ENV_NAME_ADAPTER.validate_python(name)
            except ValidationError as error:
                raise RuntimeEnvironmentError(
                    "runtime environment contains an invalid name"
                ) from error
            if not separator or validated_name in values:
                raise RuntimeEnvironmentError("runtime environment contains an invalid entry")
            value = _decode_value(encoded)
            _validate_value(value)
            values[validated_name] = value
        return values

    def save(self, values: Mapping[str, str]) -> None:
        validated: dict[str, str] = {}
        for name, value in values.items():
            try:
                validated_name = _ENV_NAME_ADAPTER.validate_python(name)
            except ValidationError as error:
                raise RuntimeEnvironmentError(
                    "runtime environment contains an invalid name"
                ) from error
            _validate_value(value)
            validated[validated_name] = value
        body = _HEADER + "".join(
            f"{name}={_encode_value(validated[name])}\n" for name in sorted(validated)
        )
        encoded = body.encode("utf-8")
        if len(encoded) > _MAX_FILE_BYTES:
            raise RuntimeEnvironmentError("runtime environment exceeds the size limit")
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise RuntimeEnvironmentError("runtime environment path is not a regular file")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".ase-runtime-env-", dir=self.path.parent
            )
            temporary = Path(temporary_name)
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                os.chmod(self.path, 0o600)
                directory = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        except OSError as error:
            raise RuntimeEnvironmentError("runtime environment could not be saved") from error


def _validate_value(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_VALUE_CHARACTERS
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise RuntimeEnvironmentError("runtime environment value is invalid")


def _encode_value(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _decode_value(value: str) -> str:
    if len(value) < 2 or not value.startswith("'") or not value.endswith("'"):
        raise RuntimeEnvironmentError("runtime environment entry is not canonically quoted")
    decoded = value[1:-1].replace("'\\''", "'")
    if _encode_value(decoded) != value:
        raise RuntimeEnvironmentError("runtime environment entry is not canonically quoted")
    return decoded


__all__ = [
    "LocalRuntimeEnvironmentStore",
    "RuntimeEnvironmentError",
    "runtime_environment_path",
]
