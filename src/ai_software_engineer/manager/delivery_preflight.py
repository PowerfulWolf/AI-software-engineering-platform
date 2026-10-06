"""Read-only delivery prerequisites, never a test verdict or new authority.

Call only from trusted composition with validated plan requirements and actual
role routes. Candidate source is not executed. Controlled capability facts must
come from a registered provider that performs current discovery, never a model.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from ai_software_engineer.domain.agent import AgentDefinition
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.execution_window import PlannedVerificationRequirement
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.native_verification import (
    NativeVerificationCapabilityDetail,
    NativeVerificationWaitReason,
)
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git import WorkspacePolicy, WorkspacePolicyError
from ai_software_engineer.manager.verification_process import bounded_verification_command

Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class DeliveryPreflightScope(DomainModel):
    team_id: NonEmptyStr
    project_id: NonEmptyStr
    repository_id: NonEmptyStr
    requirement_id: NonEmptyStr


class DiscoveredControlledCapability(DomainModel):
    kind: NonEmptyStr
    role: Literal[AgentRole.QA, AgentRole.REVIEWER]
    source_revision: NonEmptyStr
    discovery_sha256: Sha256
    # The registered executor reports the exact requirement IDs it can execute,
    # after checking current tools, policy and (when applicable) immutable images.
    requirement_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


class DeliveryPreflightObservation(DomainModel):
    requirement_id: NonEmptyStr
    status: Literal["READY", "WAIT_ENGINEERING"]
    reason_code: NonEmptyStr
    executable: NonEmptyStr | None = None
    executable_sha256: Sha256 | None = None
    controlled_discovery_sha256: Sha256 | None = None
    native_wait_reason: NativeVerificationWaitReason | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    native_wait_detail: NativeVerificationCapabilityDetail | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def validate_native_wait(self) -> DeliveryPreflightObservation:
        if self.native_wait_reason is not None and (
            self.status != "WAIT_ENGINEERING"
            or self.reason_code != "CONTROLLED_VERIFICATION_CAPABILITY_REQUIRED"
        ):
            raise ValueError("native discovery failure requires a controlled capability wait")
        if (
            self.native_wait_detail is not None
            and self.native_wait_reason is not NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE
        ):
            raise ValueError("capability detail requires a capability unavailable wait")
        return self


class DeliveryPreflightReceipt(DomainModel):
    kind: Literal["delivery_preflight_v1"] = "delivery_preflight_v1"
    scope: DeliveryPreflightScope
    task_id: NonEmptyStr
    source_revision: NonEmptyStr
    plan_sha256: Sha256
    frozen_policy_sha256: Sha256
    requirements_sha256: Sha256
    observations: tuple[DeliveryPreflightObservation, ...]
    status: Literal["READY", "WAIT_ENGINEERING"]
    checked_at: AwareDatetime
    receipt_sha256: Sha256

    def validate_integrity(self) -> None:
        if self.receipt_sha256 != _digest(self.model_dump(mode="json", exclude={"receipt_sha256"})):
            raise ValueError("delivery preflight receipt changed")


class DeliveryPreflightCheckpoint(DomainModel):
    """A real claimed preflight gate stopped before publishing an invocation start."""

    kind: Literal["delivery_preflight_checkpoint"] = "delivery_preflight_checkpoint"
    work_item_id: NonEmptyStr
    lease_id: NonEmptyStr
    task_id: NonEmptyStr
    task_snapshot_sha256: Sha256
    checkpoint_sequence: int
    source_revision: NonEmptyStr
    receipt_sha256: Sha256
    checked_at: AwareDatetime
    checkpoint_sha256: Sha256

    def validate_integrity(self) -> None:
        if self.checkpoint_sha256 != _digest(
            self.model_dump(mode="json", exclude={"checkpoint_sha256"})
        ):
            raise ValueError("preflight checkpoint integrity mismatch")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _resolve_executable(root: Path, argv: tuple[str, ...], environment: Mapping[str, str]) -> Path:
    name = argv[0]
    if "/" in name:
        candidate = Path(name)
        if not candidate.is_absolute():
            candidate = root / candidate
    else:
        # Resolve the exact executor PATH. A .venv's existence does not mean the
        # executor uses it; trusted composition must bind that PATH or exact argv.
        candidate = Path(shutil.which(name, path=environment.get("PATH", os.defpath)) or "")
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise ValueError("VERIFICATION_EXECUTABLE_UNAVAILABLE")
    resolved = candidate.resolve(strict=True)
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise ValueError("VERIFICATION_EXECUTABLE_UNAVAILABLE")
    return resolved


def inspect_delivery_prerequisites(
    *,
    scope: DeliveryPreflightScope,
    task: Task,
    plan_sha256: str,
    requirements: tuple[PlannedVerificationRequirement, ...],
    definitions: Mapping[AgentRole, AgentDefinition],
    route_kinds: Mapping[AgentRole, Literal["codex_cli", "responses"]],
    environment: Mapping[str, str],
    controlled_capabilities: tuple[DiscoveredControlledCapability, ...] = (),
    controlled_discovery_failure: NativeVerificationWaitReason | None = None,
    controlled_discovery_detail: NativeVerificationCapabilityDetail | None = None,
    checked_at: datetime,
    source_revision: str | None = None,
) -> DeliveryPreflightReceipt:
    source = source_revision or task.base_ref
    root = Path(task.repository)
    if root.resolve(strict=True) != root or not root.is_dir():
        raise ValueError("preflight requires the exact canonical registered repository")
    revision = (
        bounded_verification_command(
            (
                "/usr/bin/git",
                "-c",
                "core.fsmonitor=false",
                "rev-parse",
                "--verify",
                "--end-of-options",
                source + "^{commit}",
            ),
            cwd=root,
            environment={
                "PATH": "/usr/bin:/bin",
                "LANG": "C",
                "GIT_NO_REPLACE_OBJECTS": "1",
                "GIT_NO_LAZY_FETCH": "1",
            },
            limit=256,
        )
        .decode()
        .strip()
    )
    if revision != source:
        raise ValueError("preflight requires the Task's exact pinned source commit")
    tracked = bounded_verification_command(
        ("/usr/bin/git", "-c", "core.fsmonitor=false", "ls-tree", "-rz", source),
        cwd=root,
        environment={
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_NO_LAZY_FETCH": "1",
        },
        limit=2_000_000,
    )
    regular_files = set()
    for raw in tracked.split(b"\0"):
        if raw:
            metadata, filename = raw.split(b"\t", 1)
            mode, kind, _ = metadata.split()
            if mode in {b"100644", b"100755"} and kind == b"blob":
                regular_files.add(filename.decode("utf-8"))
    ensure_unique((item.id for item in requirements), "preflight requirements")
    ensure_unique(
        ((item.kind, item.role) for item in controlled_capabilities), "controlled discoveries"
    )
    expected = {criterion.id for criterion in task.acceptance_criteria}
    covered = {
        criterion
        for item in requirements
        if item.role is AgentRole.QA
        for criterion in item.criterion_ids
    }
    if not covered <= expected:
        raise ValueError("preflight verification references a foreign acceptance criterion")
    observations: list[DeliveryPreflightObservation] = []
    if covered != expected:
        observations.append(
            DeliveryPreflightObservation(
                requirement_id="approved_acceptance_coverage",
                status="WAIT_ENGINEERING",
                reason_code="VERIFICATION_ENTRYPOINTS_REQUIRED",
            )
        )
    for requirement in requirements:
        definition = definitions[requirement.role]
        policy = WorkspacePolicy(
            root,
            definition.permissions,
            denied_paths=task.constraints.denied_paths if task.constraints else (),
            require_focused_tests=True,
        )
        if requirement.inspection is not None:
            inspection = requirement.inspection
            try:
                for path in (*inspection.paths, *requirement.planned_new_files):
                    policy.authorize_read(path)
                for path in requirement.planned_new_files:
                    WorkspacePolicy(
                        root,
                        definitions[AgentRole.CODER].permissions,
                        denied_paths=task.constraints.denied_paths if task.constraints else (),
                    ).authorize_write(path)
            except WorkspacePolicyError:
                observations.append(
                    DeliveryPreflightObservation(
                        requirement_id=requirement.id,
                        status="WAIT_ENGINEERING",
                        reason_code="VERIFICATION_INSPECTION_AUTHORIZATION_REQUIRED",
                    )
                )
                continue
            if any(
                path not in regular_files and path not in requirement.planned_new_files
                for path in inspection.paths
            ):
                observations.append(
                    DeliveryPreflightObservation(
                        requirement_id=requirement.id,
                        status="WAIT_ENGINEERING",
                        reason_code="VERIFICATION_INSPECTION_FILE_MISSING",
                    )
                )
                continue
            if inspection.kind == "native_ui":
                capability = next(
                    (
                        item
                        for item in controlled_capabilities
                        if item.kind == requirement.controlled_capability_kind
                        and item.role is requirement.role
                        and item.source_revision == source
                        and requirement.id in item.requirement_ids
                    ),
                    None,
                )
                observations.append(
                    DeliveryPreflightObservation(
                        requirement_id=requirement.id,
                        status="READY" if capability else "WAIT_ENGINEERING",
                        reason_code="CONTROLLED_CAPABILITY_DISCOVERED"
                        if capability
                        else "CONTROLLED_VERIFICATION_CAPABILITY_REQUIRED",
                        controlled_discovery_sha256=capability.discovery_sha256
                        if capability
                        else None,
                        native_wait_reason=controlled_discovery_failure
                        if capability is None
                        else None,
                        native_wait_detail=controlled_discovery_detail
                        if capability is None
                        else None,
                    )
                )
            else:
                observations.append(
                    DeliveryPreflightObservation(
                        requirement_id=requirement.id,
                        status="READY",
                        reason_code="AUTHORIZED_INSPECTION_TARGETS_PRESENT",
                    )
                )
            continue
        assert requirement.argv is not None
        try:
            # A broad interpreter allowlist is not a verification entry point.
            # Reuse the same typed command predicate advertised to joint Planner.
            from ai_software_engineer.multi_directory.integration_commands import (
                TEST_PREFIXES,
                is_test_command,
            )
            from ai_software_engineer.swift_verification import is_restricted_swift_command

            normalized = (Path(requirement.argv[0]).name, *requirement.argv[1:])
            filtered_swift = (
                normalized[:2] == ("swift", "test")
                and "--filter" in normalized
                and is_restricted_swift_command(normalized)
            )
            if (
                not is_test_command(requirement.argv)
                and not is_test_command(normalized)
                and not filtered_swift
            ):
                raise WorkspacePolicyError("验证计划必须使用已支持的测试入口")
            if normalized in TEST_PREFIXES or any(
                token
                in {
                    "tests",
                    "tests/",
                    ".",
                    "./",
                    "./...",
                    "...",
                    "discover",
                    "--all",
                    "--all-packages",
                    "*",
                    ".*",
                }
                for token in normalized
            ):
                raise WorkspacePolicyError("验证计划必须提供明确的增量测试范围")
            policy.authorize_command(requirement.argv)
            for token in requirement.argv:
                if token.startswith("tests/"):
                    policy.authorize_read(token.split("::", 1)[0])
            for path in requirement.planned_new_files:
                policy.authorize_read(path)
                WorkspacePolicy(
                    root,
                    definitions[AgentRole.CODER].permissions,
                    denied_paths=task.constraints.denied_paths if task.constraints else (),
                ).authorize_write(path)
        except WorkspacePolicyError:
            observations.append(
                DeliveryPreflightObservation(
                    requirement_id=requirement.id,
                    status="WAIT_ENGINEERING",
                    reason_code="VERIFICATION_COMMAND_AUTHORIZATION_REQUIRED",
                )
            )
            continue
        selectors = tuple(
            token.split("::", 1)[0] for token in requirement.argv if token.startswith("tests/")
        )
        if any(
            path not in regular_files and path not in requirement.planned_new_files
            for path in selectors
        ):
            observations.append(
                DeliveryPreflightObservation(
                    requirement_id=requirement.id,
                    status="WAIT_ENGINEERING",
                    reason_code="VERIFICATION_SELECTED_FILE_MISSING",
                )
            )
            continue
        if (
            requirement.controlled_capability_kind is not None
            or route_kinds[requirement.role] == "codex_cli"
        ):
            capability = next(
                (
                    item
                    for item in controlled_capabilities
                    if item.kind == requirement.controlled_capability_kind
                    and item.role is requirement.role
                    and item.source_revision == source
                    and requirement.id in item.requirement_ids
                ),
                None,
            )
            if capability is None:
                observations.append(
                    DeliveryPreflightObservation(
                        requirement_id=requirement.id,
                        status="WAIT_ENGINEERING",
                        reason_code="CONTROLLED_VERIFICATION_CAPABILITY_REQUIRED",
                        native_wait_reason=controlled_discovery_failure,
                        native_wait_detail=controlled_discovery_detail,
                    )
                )
            else:
                observations.append(
                    DeliveryPreflightObservation(
                        requirement_id=requirement.id,
                        status="READY",
                        reason_code="CONTROLLED_CAPABILITY_DISCOVERED",
                        controlled_discovery_sha256=capability.discovery_sha256,
                    )
                )
            continue
        try:
            executable = _resolve_executable(root, requirement.argv, environment)
            with executable.open("rb") as stream:
                executable_sha = hashlib.file_digest(stream, "sha256").hexdigest()
            observations.append(
                DeliveryPreflightObservation(
                    requirement_id=requirement.id,
                    status="READY",
                    reason_code="AUTHORIZED_TOOL_PRESENT",
                    executable=str(executable),
                    executable_sha256=executable_sha,
                )
            )
        except (OSError, ValueError):
            observations.append(
                DeliveryPreflightObservation(
                    requirement_id=requirement.id,
                    status="WAIT_ENGINEERING",
                    reason_code="VERIFICATION_EXECUTABLE_UNAVAILABLE",
                )
            )
    policy_sha = _digest(
        {
            "permissions": {
                role.value: definition.permissions.to_wire()
                for role, definition in definitions.items()
            },
            "constraints": task.constraints.to_wire() if task.constraints else None,
            "route_kinds": {role.value: kind for role, kind in route_kinds.items()},
        }
    )
    receipt = DeliveryPreflightReceipt(
        scope=scope,
        task_id=task.id,
        source_revision=source,
        plan_sha256=plan_sha256,
        frozen_policy_sha256=policy_sha,
        requirements_sha256=_digest([item.to_wire() for item in requirements]),
        observations=tuple(observations),
        status="WAIT_ENGINEERING"
        if any(item.status == "WAIT_ENGINEERING" for item in observations)
        else "READY",
        checked_at=checked_at,
        receipt_sha256="0" * 64,
    )
    return receipt.model_copy(
        update={
            "receipt_sha256": _digest(receipt.model_dump(mode="json", exclude={"receipt_sha256"}))
        }
    )
