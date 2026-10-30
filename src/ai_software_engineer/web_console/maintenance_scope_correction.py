"""Audited local correction of a retired Host's diagnostic catalog scope.

The retirement and its UNKNOWN outcome remain immutable. A correction only
selects the workspace whose durable Operation was named by the retired log.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from ai_software_engineer.config.production import ProductionConfig
from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.identity import ProjectId, TeamId
from ai_software_engineer.domain.model import NonEmptyStr
from ai_software_engineer.manager.delivery_checkpoint import DeliveryId
from ai_software_engineer.project_workspace import ProjectWorkspaceRegistry
from ai_software_engineer.team_workspace import discover_team_workspaces

from .fault_retirement import (
    MARKER_NAME,
    FaultRetirementPlan,
    FaultRetirementReceipt,
    InspectionMarker,
    _archive_root,
    _directory,
    _load,
    _read,
    _Record,
    _save,
    _sha,
    _verified_marker,
    replacement_lock,
)
from .maintenance_names import COMPLETION_RECEIPT_NAME, NORMAL_ADMISSION_NAME
from .service_lifecycle import ServiceLifecycleError, ServiceLifecycleStore
from .store import ConsoleOperationNotFound, FileConsoleOperationStore

_ERROR = "维护作用域纠错无法核验; 保留检查模式、原记录和需求。"
_PLAN_NAME = "scope-correction-plan.json"
_DECISION_NAME = "scope-correction.json"
AuthorityReference = Annotated[str, StringConstraints(min_length=8, max_length=300)]


class MaintenanceScopeCorrectionError(ServiceLifecycleError):
    """Fixed refusal; never disclose a config, log or Operation body."""


class MaintenanceScopeCorrectionPlan(_Record):
    kind: Literal["maintenance_scope_correction_plan"] = "maintenance_scope_correction_plan"
    retirement_plan_sha256: Sha256
    retirement_receipt_sha256: Sha256
    marker_sha256: Sha256
    principal_uid: Annotated[int, Field(ge=0, strict=True)]
    observed_catalog_root: NonEmptyStr
    observed_config_sha256: Sha256
    previous_admitted_marker_sha256: Sha256
    previous_admitted_platform_root: NonEmptyStr
    target_platform_root: NonEmptyStr
    target_team_id: TeamId
    target_config_sha256: Sha256
    target_team_manifest_sha256: Sha256
    target_operation_id: NonEmptyStr
    target_operation_sha256: Sha256
    target_project_id: ProjectId
    target_delivery_id: DeliveryId
    archived_log_sha256: Sha256
    authority_reference: AuthorityReference
    assessment: Literal["EVIDENCE_BASED_RUNTIME_SCOPE"] = "EVIDENCE_BASED_RUNTIME_SCOPE"
    historical_execution_outcome: Literal["UNKNOWN"] = "UNKNOWN"
    requirement_action: Literal["NONE"] = "NONE"

    @model_validator(mode="after")
    def distinct_roots(self) -> Self:
        if (
            self.observed_catalog_root == self.target_platform_root
            or self.previous_admitted_platform_root != self.target_platform_root
        ):
            raise ValueError(_ERROR)
        return self


class MaintenanceScopeCorrection(_Record):
    kind: Literal["maintenance_scope_correction"] = "maintenance_scope_correction"
    plan_sha256: Sha256
    retirement_plan_sha256: Sha256
    marker_sha256: Sha256
    principal_uid: Annotated[int, Field(ge=0, strict=True)]
    authority_reference: AuthorityReference
    target_platform_root: NonEmptyStr
    target_team_id: TeamId
    target_config_sha256: Sha256
    historical_execution_outcome: Literal["UNKNOWN"] = "UNKNOWN"
    requirement_action: Literal["NONE"] = "NONE"


def _exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _log_mentions_operation(archive: Path, operation_id: str, expected: str, size: int) -> None:
    needle = f"Console operation {operation_id} failed with ".encode("ascii")
    digest = hashlib.sha256()
    found = False
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
                or before.st_size != size
                or stat.S_IMODE(before.st_mode) != 0o600
            ):
                raise MaintenanceScopeCorrectionError(_ERROR)
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                tail = b""
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    found |= needle in tail + chunk
                    tail = chunk[-(len(needle) - 1) :]
                after = os.fstat(stream.fileno())
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise MaintenanceScopeCorrectionError(_ERROR)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    if digest.hexdigest() != expected or not found:
        raise MaintenanceScopeCorrectionError(_ERROR)


def _operation_facts(config: ProductionConfig, operation_id: str) -> tuple[str, str, str, str]:
    teams = discover_team_workspaces(config.platform_root)
    if len(teams) != 1 or teams[0].manifest.team_id != config.team_id:
        raise MaintenanceScopeCorrectionError(_ERROR)
    team = teams[0]
    operation = FileConsoleOperationStore(
        team.directory("work-items") / "console-operations",
        team_id=config.team_id,
        read_only=True,
    ).get(operation_id)
    if (
        not operation.terminal
        or operation.team_id != config.team_id
        or operation.delivery_id is None
    ):
        raise MaintenanceScopeCorrectionError(_ERROR)
    project_id = getattr(operation.intent, "project_id", None)
    if project_id is None:
        raise MaintenanceScopeCorrectionError(_ERROR)
    return (
        team.manifest.manifest_sha256,
        operation.operation_sha256,
        project_id,
        operation.delivery_id,
    )


def _observe(
    environment: Mapping[str, str],
    *,
    operation_id: str,
    authority_reference: str,
    allow_completion: bool = False,
) -> MaintenanceScopeCorrectionPlan:
    root = ServiceLifecycleStore.from_environment(environment).root
    retirement, receipt = _verified_marker(root)
    marker = _load(root, MARKER_NAME, InspectionMarker)
    if not allow_completion and (
        _exists(root / COMPLETION_RECEIPT_NAME) or _exists(root / NORMAL_ADMISSION_NAME)
    ):
        raise MaintenanceScopeCorrectionError(_ERROR)
    source = ProductionConfig.path_from_environment(environment)
    body = _read(source.parent, source.name, bound=1_000_000, private=False)
    config = ProductionConfig.model_validate_json(body)
    if config.platform_root == retirement.scope.platform_root:
        raise MaintenanceScopeCorrectionError(_ERROR)
    archive = _archive_root(root, retirement.record_sha256)
    previous = retirement.previous_maintenance
    if previous is None:
        raise MaintenanceScopeCorrectionError(_ERROR)
    prior_marker = _load(archive / "previous-maintenance", MARKER_NAME, InspectionMarker)
    if prior_marker.record_sha256 != previous.marker_sha256:
        raise MaintenanceScopeCorrectionError(_ERROR)
    prior_retirement = _load(
        _archive_root(root, prior_marker.plan_sha256), "plan.json", FaultRetirementPlan
    )
    if prior_retirement.scope.platform_root != config.platform_root:
        raise MaintenanceScopeCorrectionError(_ERROR)
    _log_mentions_operation(archive, operation_id, receipt.log_sha256, receipt.log_byte_count)
    team_sha, operation_sha, project_id, delivery_id = _operation_facts(config, operation_id)
    target_teams = discover_team_workspaces(config.platform_root)
    project = ProjectWorkspaceRegistry(target_teams[0]).open(project_id)
    # The Operation's exact Requirement must exist in that Project. This is a
    # scope witness, never permission to change the Requirement.
    requirement = project.requirements_root / delivery_id
    with _directory(requirement):
        pass
    old_teams = discover_team_workspaces(retirement.scope.platform_root)
    if len(old_teams) != 1 or old_teams[0].manifest.team_id != config.team_id:
        raise MaintenanceScopeCorrectionError(_ERROR)
    old_store = FileConsoleOperationStore(
        old_teams[0].directory("work-items") / "console-operations",
        team_id=old_teams[0].manifest.team_id,
        read_only=True,
    )
    try:
        old_store.get(operation_id)
    except ConsoleOperationNotFound:
        pass
    else:
        raise MaintenanceScopeCorrectionError(_ERROR)
    return MaintenanceScopeCorrectionPlan.create(
        recorded_at=datetime.now(UTC),
        retirement_plan_sha256=retirement.record_sha256,
        retirement_receipt_sha256=receipt.record_sha256,
        marker_sha256=marker.record_sha256,
        principal_uid=os.getuid(),
        observed_catalog_root=retirement.scope.platform_root,
        observed_config_sha256=retirement.scope.config_sha256,
        previous_admitted_marker_sha256=previous.marker_sha256,
        previous_admitted_platform_root=prior_retirement.scope.platform_root,
        target_platform_root=config.platform_root,
        target_team_id=config.team_id,
        target_config_sha256=_sha(body),
        target_team_manifest_sha256=team_sha,
        target_operation_id=operation_id,
        target_operation_sha256=operation_sha,
        target_project_id=project_id,
        target_delivery_id=delivery_id,
        archived_log_sha256=receipt.log_sha256,
        authority_reference=authority_reference,
    )


def revalidate_scope_correction(
    environment: Mapping[str, str], plan: MaintenanceScopeCorrectionPlan
) -> None:
    """Recheck the original log and target journal before completion/admission."""
    fresh = _observe(
        environment,
        operation_id=plan.target_operation_id,
        authority_reference=plan.authority_reference,
        allow_completion=True,
    )
    if fresh.model_dump(exclude={"recorded_at", "record_sha256"}) != plan.model_dump(
        exclude={"recorded_at", "record_sha256"}
    ):
        raise MaintenanceScopeCorrectionError(_ERROR)


def prepare_scope_correction(
    environment: Mapping[str, str], *, operation_id: str, authority_reference: str
) -> MaintenanceScopeCorrectionPlan:
    """Persist an unapproved exact proposal under the current retirement archive."""
    root = ServiceLifecycleStore.from_environment(environment).root
    with replacement_lock(root):
        plan = _observe(
            environment, operation_id=operation_id, authority_reference=authority_reference
        )
        archive = _archive_root(root, plan.retirement_plan_sha256)
        if _exists(archive / _PLAN_NAME):
            existing = _load(archive, _PLAN_NAME, MaintenanceScopeCorrectionPlan)
            if existing.model_dump(exclude={"recorded_at", "record_sha256"}) != plan.model_dump(
                exclude={"recorded_at", "record_sha256"}
            ):
                raise MaintenanceScopeCorrectionError(_ERROR)
            return existing
        _save(archive, _PLAN_NAME, plan)
        return plan


def verified_scope_correction(
    root: Path, retirement_plan_sha256: str
) -> tuple[MaintenanceScopeCorrectionPlan, MaintenanceScopeCorrection] | None:
    # During a later maintenance epoch the completion records move under
    # previous-maintenance, while the retirement archives remain at the state
    # root. Resolve that fixed lineage without accepting a caller path.
    state_root = root
    for parent in (root, *root.parents):
        if parent.name == "console-fault-retirements":
            state_root = parent.parent
            break
    archive = _archive_root(state_root, retirement_plan_sha256)
    if not _exists(archive / _DECISION_NAME):
        if _exists(archive / _PLAN_NAME):
            raise MaintenanceScopeCorrectionError(_ERROR)
        return None
    plan = _load(archive, _PLAN_NAME, MaintenanceScopeCorrectionPlan)
    decision = _load(archive, _DECISION_NAME, MaintenanceScopeCorrection)
    marker = _load(root, MARKER_NAME, InspectionMarker)
    retirement = _load(archive, "plan.json", FaultRetirementPlan)
    receipt = _load(archive, "receipt.json", FaultRetirementReceipt)
    if (
        plan.retirement_plan_sha256 != retirement_plan_sha256
        or retirement.record_sha256 != retirement_plan_sha256
        or plan.retirement_receipt_sha256 != receipt.record_sha256
        or plan.marker_sha256 != marker.record_sha256
        or plan.principal_uid != os.getuid()
        or plan.observed_catalog_root != retirement.scope.platform_root
        or plan.observed_config_sha256 != retirement.scope.config_sha256
        or retirement.previous_maintenance is None
        or plan.previous_admitted_marker_sha256 != retirement.previous_maintenance.marker_sha256
        or plan.previous_admitted_platform_root != plan.target_platform_root
        or plan.archived_log_sha256 != receipt.log_sha256
        or decision.plan_sha256 != plan.record_sha256
        or decision.retirement_plan_sha256 != retirement_plan_sha256
        or decision.marker_sha256 != marker.record_sha256
        or decision.principal_uid != plan.principal_uid
        or decision.authority_reference != plan.authority_reference
        or decision.target_platform_root != plan.target_platform_root
        or decision.target_team_id != plan.target_team_id
        or decision.target_config_sha256 != plan.target_config_sha256
        or decision.recorded_at < plan.recorded_at
    ):
        raise MaintenanceScopeCorrectionError(_ERROR)
    return plan, decision


def execute_scope_correction(
    environment: Mapping[str, str], *, plan_sha256: str, confirm_scope_correction: bool
) -> MaintenanceScopeCorrection:
    """Append a local engineering decision; never edit the original retirement."""
    if not confirm_scope_correction:
        raise MaintenanceScopeCorrectionError(_ERROR)
    root = ServiceLifecycleStore.from_environment(environment).root
    with replacement_lock(root):
        retirement, _ = _verified_marker(root)
        archive = _archive_root(root, retirement.record_sha256)
        plan = _load(archive, _PLAN_NAME, MaintenanceScopeCorrectionPlan)
        if plan.record_sha256 != plan_sha256:
            raise MaintenanceScopeCorrectionError(_ERROR)
        existing = (
            verified_scope_correction(root, retirement.record_sha256)
            if _exists(archive / _DECISION_NAME)
            else None
        )
        if existing is not None:
            if existing[0] != plan:
                raise MaintenanceScopeCorrectionError(_ERROR)
            return existing[1]
        fresh = _observe(
            environment,
            operation_id=plan.target_operation_id,
            authority_reference=plan.authority_reference,
        )
        if fresh.model_dump(exclude={"recorded_at", "record_sha256"}) != plan.model_dump(
            exclude={"recorded_at", "record_sha256"}
        ):
            raise MaintenanceScopeCorrectionError(_ERROR)
        decision = MaintenanceScopeCorrection.create(
            recorded_at=datetime.now(UTC),
            plan_sha256=plan.record_sha256,
            retirement_plan_sha256=retirement.record_sha256,
            marker_sha256=plan.marker_sha256,
            principal_uid=os.getuid(),
            authority_reference=plan.authority_reference,
            target_platform_root=plan.target_platform_root,
            target_team_id=plan.target_team_id,
            target_config_sha256=plan.target_config_sha256,
        )
        _save(archive, _DECISION_NAME, decision)
        verified_scope_correction(root, retirement.record_sha256)
        return decision
