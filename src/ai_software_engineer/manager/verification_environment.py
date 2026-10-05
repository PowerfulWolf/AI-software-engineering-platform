"""Manager prerequisites and a versioned, explicitly approved Swift executor contract.

The capability never becomes an AgentPermissions entry. Models cannot choose its
executable, sandbox profile, environment, paths or inner-sandbox exception.
"""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, field_validator

from ai_software_engineer.domain.artifact import ArtifactId, Sha256
from ai_software_engineer.domain.engineering_authority import EngineeringAdmission
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.project_delivery import _stage_digest
from ai_software_engineer.manager.delivery_checkpoint import CommitSha
from ai_software_engineer.manager.leader_recovery import (
    ManagerCapabilityKind,
    ManagerIncident,
    ManagerIncidentKind,
    ManagerLeaderRecovery,
    ManagerRepairCapability,
    ManagerRepairDisposition,
    ManagerRepairExecution,
    ManagerRepairMode,
    ManagerRepairResult,
    ManagerRepairSubmission,
)


@dataclass
class _VerificationRefreshExecutor:
    incident: ManagerIncident
    admit: Callable[[], EngineeringAdmission]
    admission: EngineeringAdmission | None = None

    def execute(self, incident: ManagerIncident) -> ManagerRepairExecution:
        if incident != self.incident:
            raise ValueError("verification refresh targets another exact incident")
        record = self.admit()
        self.admission = record
        return ManagerRepairExecution(
            repaired=False,
            summary="精确候选验证已获冻结工程授权；环境修复和验收结果仍须真实执行确认。",  # noqa: RUF001
            evidence_sha256=record.admission_sha256,
            engineering_admission_sha256=record.admission_sha256,
        )


def admit_registered_verification_refresh(
    *, incident: ManagerIncident, admit: Callable[[], EngineeringAdmission]
) -> EngineeringAdmission:
    """Register the real receipt service; never infer environment health from NOT_TESTED."""
    capability = ManagerRepairCapability(
        id="manager_capability_verification_refresh",
        kind=ManagerCapabilityKind.BUILTIN,
        incident_kinds=(ManagerIncidentKind.ENVIRONMENT, ManagerIncidentKind.WORKFLOW),
        mode=ManagerRepairMode.VERIFICATION_REFRESH,
        max_attempts=3,
    )
    executor = _VerificationRefreshExecutor(incident, admit)
    result = ManagerLeaderRecovery(
        capabilities=(capability,),
        executors={capability.id: executor},
        task_submitter=_NoAutomaticRepairTasks(),
    ).recover(incident)
    if (
        result.disposition is not ManagerRepairDisposition.VERIFICATION_ADMITTED
        or executor.admission is None
        or result.engineering_admission_sha256 != executor.admission.admission_sha256
    ):
        raise ValueError("verification refresh was not admitted")
    return executor.admission


class SwiftSandboxCapability(DomainModel):
    """A proposal, not authority: its exact containing plan still needs approval."""

    kind: Literal["codex_sandbox_swiftpm_v1"] = "codex_sandbox_swiftpm_v1"
    sandbox_executable: NonEmptyStr
    sandbox_executable_sha256: Sha256
    developer_directory: NonEmptyStr
    swift_version: str = Field(min_length=1, max_length=2000)
    build_system: Literal["native"] = "native"

    @field_validator("sandbox_executable", "developer_directory")
    @classmethod
    def absolute_safe_path(cls, value: str) -> str:
        if (
            not Path(value).is_absolute()
            or ".." in Path(value).parts
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("capability paths must be absolute safe paths")
        return value


def discover_swift_sandbox_capability(executable: str) -> SwiftSandboxCapability | None:
    """Read host facts only; no package evaluation, sandbox exception or model call."""
    if platform.system() != "Darwin":
        return None
    resolved = shutil.which(executable)
    if resolved is None:
        return None
    binary = Path(resolved).resolve(strict=True)
    try:
        developer = subprocess.run(
            ("/usr/bin/xcode-select", "-p"),
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
            env={"PATH": "/usr/bin:/bin", "LANG": "C"},
        ).stdout.strip()
        if not (Path(developer) / "usr/bin/xctest").is_file():
            return None
        version = subprocess.run(
            ("/usr/bin/swift", "--version"),
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
            env={"PATH": "/usr/bin:/bin", "LANG": "C", "DEVELOPER_DIR": developer},
        ).stdout.strip()
        with binary.open("rb") as stream:
            binary_sha = hashlib.file_digest(stream, "sha256").hexdigest()
        return SwiftSandboxCapability(
            sandbox_executable=str(binary),
            sandbox_executable_sha256=binary_sha,
            developer_directory=developer,
            swift_version=version,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class _NoAutomaticRepairTasks:
    def submit(
        self, incident: ManagerIncident, capability: ManagerRepairCapability
    ) -> ManagerRepairSubmission:
        raise ValueError("verification prerequisites cannot create implicit repair Tasks")


class VerificationEnvironmentIncident(DomainModel):
    """Durable Manager decision bound to an inconclusive independent QA completion."""

    kind: Literal["verification_environment_incident"] = "verification_environment_incident"
    source_plan_sha256: Sha256
    completion_sha256: Sha256
    candidate_revision: CommitSha
    qa_artifact_id: ArtifactId
    not_tested: int = Field(ge=0)
    errors: int = Field(ge=0)
    incident: ManagerIncident
    decision: ManagerRepairResult
    incident_sha256: Sha256

    @classmethod
    def create(
        cls,
        *,
        source_plan_sha256: str,
        completion_sha256: str,
        candidate_revision: str,
        qa_artifact_id: str,
        delivery_id: str,
        repository_root: str,
        not_tested: int,
        errors: int,
    ) -> Self:
        incident = ManagerIncident(
            id=f"manager_incident_{completion_sha256[:32]}",
            kind=ManagerIncidentKind.ENVIRONMENT,
            summary=f"Independent QA incomplete: {not_tested} NOT_TESTED, {errors} ERROR",
            delivery_id=delivery_id,
            repository_root=repository_root,
        )
        decision = ManagerLeaderRecovery(
            capabilities=(), executors={}, task_submitter=_NoAutomaticRepairTasks()
        ).recover(incident)
        provisional = cls(
            source_plan_sha256=source_plan_sha256,
            completion_sha256=completion_sha256,
            candidate_revision=candidate_revision,
            qa_artifact_id=qa_artifact_id,
            not_tested=not_tested,
            errors=errors,
            incident=incident,
            decision=decision,
            incident_sha256="0" * 64,
        )
        return provisional.model_copy(update={"incident_sha256": provisional.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return _stage_digest(self, "incident_sha256")

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.incident_sha256 != self.recompute_sha256():
            raise ValueError("verification environment incident digest mismatch")


def swift_sandbox_argv(
    capability: SwiftSandboxCapability,
    source: Path,
    scratch: Path,
    action: Literal["build", "test"],
) -> tuple[str, ...]:
    """Build one fixed argv; never accept model-provided flags or writable roots."""
    if action not in {"build", "test"}:
        raise ValueError("unsupported Swift verification action")
    for path in (source, scratch):
        if not path.is_absolute() or path.resolve(strict=True) != path or not path.is_dir():
            raise ValueError("verification paths must be canonical real directories")
    if scratch.is_relative_to(source) or source.is_relative_to(scratch):
        raise ValueError("verification scratch must not overlap candidate source")
    return swift_sandbox_command(capability, source, scratch, action)


def swift_sandbox_command(
    capability: SwiftSandboxCapability,
    source: Path,
    scratch: Path,
    action: Literal["build", "test"],
) -> tuple[str, ...]:
    """Pure argv encoding, also used to validate receipts after scratch is removed."""
    # Replace the complete named profile, not individual fields that could inherit an
    # operator's wider profile. Built-in read-only protections and managed policy remain.
    profile = (
        'permissions.ase_swift_verification={extends=":read-only",filesystem={'
        + json.dumps(str(scratch))
        + '="write"},network={enabled=false}}'
    )
    return (
        capability.sandbox_executable,
        "sandbox",
        "--include-managed-config",
        "-P",
        "ase_swift_verification",
        "-c",
        profile,
        "-C",
        str(source),
        "--",
        "/usr/bin/swift",
        action,
        "--disable-sandbox",
        "--disable-automatic-resolution",
        "--skip-update",
        "--build-system",
        capability.build_system,
        "--disable-netrc",
        "--scratch-path",
        str(scratch / "build"),
        "--cache-path",
        str(scratch / "cache"),
        "--config-path",
        str(scratch / "config"),
        "--security-path",
        str(scratch / "security"),
    )
