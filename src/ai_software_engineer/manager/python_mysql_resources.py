"""Exact, short-lived MySQL resources for the approved deterministic executor."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import subprocess
import tempfile
import time
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Literal

import pymysql
from pydantic import BaseModel, ConfigDict

from ai_software_engineer.manager.python_verification import PythonMysqlSandboxCapability
from ai_software_engineer.manager.verification_process import bounded_verification_command
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.recovery.python_mysql_records import (
    MysqlResourceIntent,
    MysqlResourceRecord,
)


class MysqlResourceUnavailable(RuntimeError):
    """Stable prerequisite error; never contains Docker diagnostics or credentials."""


def container_argv(
    capability: PythonMysqlSandboxCapability, intent: MysqlResourceIntent
) -> tuple[str, ...]:
    intent.validate_integrity()
    if capability != intent.capability:
        raise ValueError("container capability differs from intent")
    return (
        "run",
        "-d",
        "--rm",
        "--pull=never",
        "--network",
        "none",
        "--name",
        intent.container_name,
        "--label",
        "ase.verification.resource=" + intent.resource_id,
        "--memory",
        "512m",
        "--cpus",
        "1",
        "--pids-limit",
        "128",
        "--env",
        "MYSQL_ALLOW_EMPTY_PASSWORD=1",
        "--env",
        "MYSQL_ROOT_HOST=localhost",
        "--entrypoint",
        "/usr/bin/timeout",
        capability.mysql_image_id,
        "--kill-after=5",
        "1195",
        "/usr/local/bin/docker-entrypoint.sh",
        "mysqld",
        "--mysqlx=0",
        "--bind-address=127.0.0.1",
        "--skip-name-resolve",
        "--innodb-buffer-pool-size=64M",
    )


class _Config(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    Image: str
    Labels: dict[str, str]
    Entrypoint: list[str]
    Cmd: list[str]
    Env: list[str]


class _RestartPolicy(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    Name: str
    MaximumRetryCount: int


class _HostConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    NetworkMode: str
    PortBindings: dict[str, object]
    Memory: int
    NanoCpus: int
    PidsLimit: int
    AutoRemove: bool
    Binds: list[str] | None
    RestartPolicy: _RestartPolicy


class _Mount(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    Type: str
    Destination: str
    Name: str | None = None


class DockerDescription(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    Id: str
    Name: str
    Image: str
    Config: _Config
    HostConfig: _HostConfig
    Mounts: list[_Mount]

    def require_owned(self, intent: MysqlResourceIntent) -> None:
        h = self.HostConfig
        if (
            re.fullmatch(r"[a-f0-9]{64}", self.Id) is None
            or self.Name != "/" + intent.container_name
            or self.Config.Labels.get("ase.verification.resource") != intent.resource_id
            or self.Image != intent.capability.mysql_image_id
            or self.Config.Image != intent.capability.mysql_image_id
            or self.Config.Entrypoint != ["/usr/bin/timeout"]
            or self.Config.Cmd != list(container_argv(intent.capability, intent)[-8:])
            or "MYSQL_ALLOW_EMPTY_PASSWORD=1" not in self.Config.Env
            or "MYSQL_ROOT_HOST=localhost" not in self.Config.Env
            or any(
                v.startswith(
                    (
                        "MYSQL_ROOT_PASSWORD=",
                        "MYSQL_ROOT_PASSWORD_FILE=",
                        "MYSQL_DATABASE=",
                        "MYSQL_USER=",
                        "MYSQL_PASSWORD=",
                    )
                )
                for v in self.Config.Env
            )
            or (h.RestartPolicy.Name, h.RestartPolicy.MaximumRetryCount) != ("no", 0)
            or h.NetworkMode != "none"
            or h.PortBindings
            or h.Binds
            or (h.Memory, h.NanoCpus, h.PidsLimit, h.AutoRemove)
            != (536870912, 1000000000, 128, True)
            or any(m.Type != "volume" or m.Destination != "/var/lib/mysql" for m in self.Mounts)
        ):
            raise MysqlResourceUnavailable("MySQL resource ownership or isolation differs")


class IsolatedMysqlResource:
    """Secrets stay in memory/stdin; publish intent before every external creation."""

    def __init__(
        self,
        intent: MysqlResourceIntent,
        publish: Callable[[MysqlResourceRecord], MysqlResourceRecord],
        *,
        clock: Callable[[], datetime],
    ) -> None:
        intent.validate_integrity()
        self.intent, self._publish, self._clock = intent, publish, clock
        self._docker_config = tempfile.TemporaryDirectory(prefix="ase-docker-private-")
        self.container_id: str | None = None
        self._intent_published = False
        self.configuration_sha256: str | None = None
        self.password = secrets.token_hex(24)
        self._root_password = secrets.token_hex(24)

    @classmethod
    def for_cleanup(
        cls,
        intent: MysqlResourceIntent,
        publish: Callable[[MysqlResourceRecord], MysqlResourceRecord],
        *,
        clock: Callable[[], datetime],
        created: MysqlResourceRecord | None = None,
    ) -> IsolatedMysqlResource:
        if created is not None and (created.intent != intent or created.phase != "CREATED"):
            raise MysqlResourceUnavailable("cleanup observation belongs to another intent")
        resource = cls(intent, publish, clock=clock)
        resource._intent_published = True
        if created is not None:
            resource.container_id = created.container_id
            resource.configuration_sha256 = created.configuration_sha256
        return resource

    @property
    def secrets(self) -> tuple[str, str]:
        return self.password, self._root_password

    @property
    def docker_prefix(self) -> tuple[str, ...]:
        cap = self.intent.capability
        return (
            cap.docker_executable,
            "--config",
            self._docker_config.name,
            "--host",
            "unix://" + cap.docker_socket,
        )

    def command(self, *arguments: str, stdin: bytes | None = None, timeout: int = 20) -> bytes:
        try:
            return bounded_verification_command(
                (*self.docker_prefix, *arguments),
                stdin=stdin,
                environment={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            raise MysqlResourceUnavailable("MySQL resource command failed") from error

    def _record(self, phase: Literal["INTENT", "CREATED", "CLEANED", "CLEANUP_FAILED"]) -> None:
        self._publish(
            MysqlResourceRecord.create(
                phase=phase,
                intent=self.intent,
                container_id=self.container_id if phase != "INTENT" else None,
                configuration_sha256=self.configuration_sha256 if phase != "INTENT" else None,
                recorded_at=self._clock(),
            )
        )

    def require_daemon(self) -> None:
        cap = self.intent.capability
        try:
            with Path(cap.docker_executable).open("rb") as binary:
                if (
                    hashlib.file_digest(binary, "sha256").hexdigest()
                    != cap.docker_executable_sha256
                ):
                    raise MysqlResourceUnavailable("approved Docker executable changed")
            if self.command("info", "--format", "{{.ID}}").decode().strip() != cap.docker_daemon_id:
                raise MysqlResourceUnavailable("approved Docker daemon changed")
        except (OSError, ValueError) as error:
            raise MysqlResourceUnavailable("approved Docker capability is unavailable") from error

    def start(self, check_owner: Callable[[], None]) -> None:
        check_owner()
        self.require_daemon()
        cap = self.intent.capability
        self._record("INTENT")
        self._intent_published = True
        check_owner()
        raw = self.command(*container_argv(cap, self.intent), timeout=30).decode().strip()
        if re.fullmatch(r"[a-f0-9]{64}", raw) is None:
            raise MysqlResourceUnavailable("MySQL resource did not return an exact identity")
        self.container_id = raw
        description = self.inspect(raw)
        description.require_owned(self.intent)
        self.configuration_sha256 = digest(description.model_dump(mode="json"))
        self._record("CREATED")
        for _ in range(100):
            check_owner()
            try:
                readiness = self.command(
                    "exec",
                    raw,
                    "mysql",
                    "--protocol=socket",
                    "-uroot",
                    "-N",
                    "-B",
                    "-e",
                    "SELECT @@GLOBAL.skip_networking",
                    timeout=5,
                )
                if readiness.strip() == b"0":
                    break
                time.sleep(0.5)
            except MysqlResourceUnavailable:
                time.sleep(0.5)
        else:
            raise MysqlResourceUnavailable("isolated MySQL did not become ready")
        # No proxy exists until root has been rotated; root localhost only is fixed at creation.
        sql = (
            "CREATE DATABASE ase_verify_test; CREATE USER 'ase_verify'@'127.0.0.1' IDENTIFIED BY '"
            + self.password
            + "'; GRANT ALL PRIVILEGES ON ase_verify_test.* TO "
            "'ase_verify'@'127.0.0.1'; ALTER USER 'root'@'localhost' IDENTIFIED BY '"
            + self._root_password
            + "';"
        )
        self.command("exec", "-i", raw, "mysql", "--protocol=socket", "-uroot", stdin=sql.encode())
        check_owner()

    def inspect(self, identity: str) -> DockerDescription:
        try:
            value = json.loads(self.command("inspect", identity))
            if not isinstance(value, list) or len(value) != 1:
                raise ValueError("one exact resource required")
            return DockerDescription.model_validate(value[0])
        except ValueError as error:
            raise MysqlResourceUnavailable("MySQL resource description is invalid") from error

    def verify_principal(self, endpoint: Path) -> None:
        try:
            with (
                closing(
                    pymysql.connect(
                        unix_socket=str(endpoint),
                        user="ase_verify",
                        password=self.password,
                        database="ase_verify_test",
                        connect_timeout=5,
                        read_timeout=10,
                        write_timeout=10,
                    )
                ) as connection,
                connection.cursor() as cursor,
            ):
                cursor.execute("SELECT CURRENT_USER(), DATABASE()")
                if cursor.fetchone() != ("ase_verify@127.0.0.1", "ase_verify_test"):
                    raise MysqlResourceUnavailable("MySQL verification principal differs")
                cursor.execute("SHOW GRANTS")
                grants = tuple(row[0] for row in cursor.fetchall())
                principal = " TO `ase_verify`@`127.0.0.1`"
                if len(grants) != 2 or set(grants) != {
                    "GRANT ALL PRIVILEGES ON `ase_verify_test`.*" + principal,
                    "GRANT USAGE ON *.*" + principal,
                }:
                    raise MysqlResourceUnavailable("MySQL verification grants differ")
            try:
                root = pymysql.connect(
                    unix_socket=str(endpoint),
                    user="root",
                    password="",
                    connect_timeout=5,
                    read_timeout=5,
                )
            except pymysql.MySQLError as error:
                if not error.args or error.args[0] not in (1045, 1698):
                    raise MysqlResourceUnavailable(
                        "MySQL root exclusion could not be verified"
                    ) from error
            else:
                root.close()
                raise MysqlResourceUnavailable("uncredentialed root is reachable")
        except pymysql.MySQLError as error:
            raise MysqlResourceUnavailable("MySQL principal prerequisite failed") from error

    def close(self) -> None:
        try:
            if not self._intent_published:
                return
            self.require_daemon()
            # Successful exact-name enumeration distinguishes absence from daemon failure.
            # The full intent-bound name is escaped; no label/prefix bulk deletion.
            raw = (
                self.command(
                    "ps",
                    "-a",
                    "--no-trunc",
                    "--filter",
                    "name=^/" + self.intent.container_name + "$",
                    "--format",
                    "{{.ID}}\t{{.Names}}",
                )
                .decode()
                .strip()
            )
            if raw:
                parts = raw.split("\t")
                if len(parts) != 2 or parts[1] != self.intent.container_name:
                    raise MysqlResourceUnavailable("MySQL cleanup inventory differs")
                description = self.inspect(parts[0])
                description.require_owned(self.intent)
                if self.container_id is not None and description.Id != self.container_id:
                    raise MysqlResourceUnavailable("MySQL cleanup identity differs")
                if (
                    self.configuration_sha256 is not None
                    and digest(description.model_dump(mode="json")) != self.configuration_sha256
                ):
                    raise MysqlResourceUnavailable("MySQL cleanup configuration differs")
                if self.container_id is None or self.configuration_sha256 is None:
                    self.container_id = description.Id
                    self.configuration_sha256 = digest(description.model_dump(mode="json"))
                    self._record("CREATED")
                self.command("rm", "-f", self.container_id)
            self._record("CLEANED")
        except MysqlResourceUnavailable:
            self._record("CLEANUP_FAILED")
            raise
        finally:
            self._docker_config.cleanup()
