"""Versioned, exact Python/MySQL verification capability; never model shell authority.

Discovery and execution must separately validate the fingerprints. This module only
defines the approval contract and a pure command encoding for receipt verification.
"""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import AcceptanceCriterionId
from ai_software_engineer.manager.python_verification_runner import PYTEST_NODE_PATTERN

PytestNodeId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=512,
        pattern=PYTEST_NODE_PATTERN,
    ),
]


class PytestSelection(DomainModel):
    """A specific test function/class method, possibly parametrized; never a suite root."""

    node_id: PytestNodeId
    criterion_ids: tuple[AcceptanceCriterionId, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_criteria(self) -> Self:
        ensure_unique(self.criterion_ids, "pytest criterion IDs")
        return self


class PythonMysqlSandboxCapability(DomainModel):
    kind: Literal["codex_sandbox_pytest_mysql_v1"] = "codex_sandbox_pytest_mysql_v1"
    sandbox_executable: NonEmptyStr
    sandbox_executable_sha256: Sha256
    python_executable: NonEmptyStr
    python_executable_sha256: Sha256
    python_runtime_root: NonEmptyStr
    python_runtime_sha256: Sha256
    dependency_root: NonEmptyStr
    dependency_sha256: Sha256
    runner_path: NonEmptyStr
    runner_sha256: Sha256
    docker_executable: NonEmptyStr
    docker_executable_sha256: Sha256
    docker_socket: NonEmptyStr
    docker_daemon_id: str = Field(min_length=1, max_length=256)
    mysql_image_id: Annotated[str, StringConstraints(pattern=r"^sha256:[a-f0-9]{64}$")]
    selections: tuple[PytestSelection, ...] = Field(min_length=1, max_length=32)
    max_cases: Literal[256] = 256
    resource_timeout_seconds: Literal[1200] = 1200
    transport: Literal["pymysql_unix_proxy_docker_exec_loopback"] = (
        "pymysql_unix_proxy_docker_exec_loopback"
    )

    @field_validator(
        "sandbox_executable",
        "python_executable",
        "python_runtime_root",
        "dependency_root",
        "runner_path",
        "docker_executable",
        "docker_socket",
    )
    @classmethod
    def safe_path(cls, value: str) -> str:
        path = Path(value)
        if (
            not path.is_absolute()
            or str(path) != value
            or ".." in path.parts
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("capability paths must be safe absolute paths")
        return value

    @model_validator(mode="after")
    def fixed_selection(self) -> Self:
        ensure_unique((selection.node_id for selection in self.selections), "pytest node IDs")
        if not Path(self.python_executable).is_relative_to(self.python_runtime_root):
            raise ValueError("Python executable must belong to the approved runtime")
        return self


def python_mysql_sandbox_command(
    capability: PythonMysqlSandboxCapability,
    source: Path,
    scratch: Path,
    private: Path,
) -> tuple[str, ...]:
    """Pure argv reconstruction; private holds an immutable config and protected proxy."""
    for path in (source, scratch, private):
        PythonMysqlSandboxCapability.safe_path(str(path))
    for left, right in combinations((source, scratch, private), 2):
        if left.is_relative_to(right) or right.is_relative_to(left):
            raise ValueError("source, scratch and private proxy paths must not overlap")
    readonly = (
        capability.python_runtime_root,
        capability.dependency_root,
        capability.runner_path,
        str(source),
        str(private / "connection.json"),
    )
    for readonly_path in readonly:
        if Path(readonly_path).is_relative_to(scratch) or scratch.is_relative_to(readonly_path):
            raise ValueError("scratch must not overlap a trusted readonly path")
    filesystem = {
        ":root": "none",
        ":minimal": "read",
        ":slash_tmp": "none",
        ":tmpdir": "none",
        **{path: "read" for path in readonly},
        str(scratch): "write",
    }
    profile = (
        'permissions.ase_python_mysql_verification={extends=":read-only",filesystem={'
        + ",".join(json.dumps(path) + "=" + json.dumps(mode) for path, mode in filesystem.items())
        + "},network={enabled=false}}"
    )
    return (
        capability.sandbox_executable,
        "sandbox",
        "--include-managed-config",
        "-P",
        "ase_python_mysql_verification",
        "-c",
        profile,
        "-C",
        str(source),
        "--allow-unix-socket",
        str(private / "mysql.sock"),
        "--",
        capability.python_executable,
        "-I",
        "-S",
        "-B",
        capability.runner_path,
        capability.dependency_root,
        str(source),
        str(scratch),
        str(private / "connection.json"),
        str(capability.max_cases),
    )
