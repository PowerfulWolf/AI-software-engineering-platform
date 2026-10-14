"""Crash-safe rollover of fixed maintenance anchors with all history retained."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter

from ai_software_engineer.domain.artifact import Sha256

from .fault_retirement import (
    _ERROR,
    MARKER_NAME,
    FaultRetirementError,
    FaultRetirementPlan,
    FaultRetirementReceipt,
    InspectionMarker,
    _directory,
    _kernel,
    _load,
    _publish,
    _read,
    _Record,
    _require_host_executable,
    _save,
    _sha,
    _verified_marker,
)
from .maintenance_completion import (
    MaintenanceCompletionPlan,
    MaintenanceNormalAdmission,
    verified_completion,
)
from .maintenance_epoch_models import (
    MaintenanceCompletionFile,
    MaintenanceControlFile,
    MaintenanceControlName,
    PreviousMaintenanceEpoch,
)
from .maintenance_names import NORMAL_ADMISSION_NAME

COMPLETIONS = "console-maintenance-completions"
CONTROLS: tuple[MaintenanceControlName, ...] = (
    "console-inspection.json",
    "console-maintenance-completed.json",
    "console-maintenance-admitted.json",
)


class MaintenanceEpochTransition(_Record):
    kind: Literal["pending_console_maintenance_epoch"] = "pending_console_maintenance_epoch"
    plan_sha256: Sha256
    previous_marker_sha256: Sha256
    successor_mode: Literal["inspection"] = "inspection"


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _completion_inventory(
    root: Path, *, marker: InspectionMarker | None = None
) -> tuple[MaintenanceCompletionFile, ...]:
    base = root / COMPLETIONS
    marker = marker or _load(root, MARKER_NAME, InspectionMarker)
    refs: list[MaintenanceCompletionFile] = []
    with _directory(base, private=True):
        paths = tuple(sorted(base.iterdir()))
        if len(paths) > 1024:
            raise FaultRetirementError(_ERROR)
        for directory in paths:
            if len(directory.name) != 64 or any(
                c not in "0123456789abcdef" for c in directory.name
            ):
                raise FaultRetirementError(_ERROR)
            with _directory(directory, private=True):
                names = tuple(sorted(path.name for path in directory.iterdir()))
                if names not in (("plan.json",), ("plan.json", "receipt.json")):
                    raise FaultRetirementError(_ERROR)
                plan = _load(directory, "plan.json", MaintenanceCompletionPlan)
                if (
                    plan.record_sha256 != directory.name
                    or plan.marker_sha256 != marker.record_sha256
                    or plan.retirement_plan_sha256 != marker.plan_sha256
                    or plan.retirement_receipt_sha256 != marker.receipt_sha256
                ):
                    raise FaultRetirementError(_ERROR)
                for name in names:
                    body = _read(directory, name)
                    refs.append(
                        MaintenanceCompletionFile(
                            plan_sha256=directory.name,
                            name="plan.json" if name == "plan.json" else "receipt.json",
                            sha256=_sha(body),
                            byte_count=len(body),
                        )
                    )
    return tuple(refs)


def collect_previous_epoch(root: Path) -> PreviousMaintenanceEpoch | None:
    if not _exists(root / MARKER_NAME):
        if any(_exists(root / name) for name in (*CONTROLS[1:], COMPLETIONS)):
            raise FaultRetirementError(_ERROR)
        return None
    marker = _load(root, MARKER_NAME, InspectionMarker)
    completed = verified_completion(root)
    if completed is None or not _exists(root / NORMAL_ADMISSION_NAME):
        raise FaultRetirementError(_ERROR)
    admission = _load(root, NORMAL_ADMISSION_NAME, MaintenanceNormalAdmission)
    refs = tuple(
        MaintenanceControlFile(
            name=name, sha256=_sha(_read(root, name)), byte_count=len(_read(root, name))
        )
        for name in CONTROLS
    )
    return PreviousMaintenanceEpoch(
        marker_sha256=marker.record_sha256,
        completion_sha256=completed[1].record_sha256,
        admission_sha256=admission.record_sha256,
        controls=refs,
        completion_files=_completion_inventory(root),
    )


def _previous_root(archive: Path, *, create: bool = False) -> Path:
    path = archive / "previous-maintenance"
    with _directory(archive, private=True) as descriptor:
        if create and not _exists(path):
            path.mkdir(mode=0o700)
            os.fsync(descriptor)
    with _directory(path, private=True):
        return path


def _require_control(root: Path, ref: MaintenanceControlFile) -> bytes:
    body = _read(root, ref.name)
    if _sha(body) != ref.sha256 or len(body) != ref.byte_count:
        raise FaultRetirementError(_ERROR)
    return body


def save_previous_controls(
    root: Path, archive: Path, previous: PreviousMaintenanceEpoch | None
) -> None:
    if previous is None:
        return
    if collect_previous_epoch(root) != previous:
        raise FaultRetirementError(_ERROR)
    target = _previous_root(archive, create=True)
    for ref in previous.controls:
        _publish(target, ref.name, _require_control(root, ref))


def verify_previous_epoch(archive: Path, previous: PreviousMaintenanceEpoch) -> InspectionMarker:
    target = _previous_root(archive)
    for ref in previous.controls:
        _require_control(target, ref)
    if collect_previous_epoch(target) != previous:
        raise FaultRetirementError(_ERROR)
    return _load(target, MARKER_NAME, InspectionMarker)


def _replace_marker(root: Path, expected: bytes, replacement: _Record) -> None:
    """Only an exact active pointer changes; immutable bytes are archived first."""
    replacement.validate_integrity()
    body = replacement.model_dump_json().encode()
    temporary = ".epoch-" + uuid.uuid4().hex
    with _directory(root) as descriptor:
        _publish(root, temporary, body)
        try:
            if _read(root, MARKER_NAME) != expected:
                raise FaultRetirementError(_ERROR)
            os.replace(temporary, MARKER_NAME, src_dir_fd=descriptor, dst_dir_fd=descriptor)
            os.fsync(descriptor)
        finally:
            if _exists(root / temporary):
                os.unlink(temporary, dir_fd=descriptor)
                os.fsync(descriptor)


def begin_epoch(root: Path, archive: Path, plan: FaultRetirementPlan) -> None:
    previous = plan.previous_maintenance
    assert previous is not None
    target = _previous_root(archive)
    for ref in previous.controls:
        _require_control(target, ref)
    body = _read(root, MARKER_NAME)
    current: InspectionMarker | MaintenanceEpochTransition = TypeAdapter(
        InspectionMarker | MaintenanceEpochTransition
    ).validate_json(body)
    current.validate_integrity()
    if isinstance(current, InspectionMarker) and current.plan_sha256 == plan.record_sha256:
        verify_previous_epoch(archive, previous)
        return  # already finalized; never touch this epoch's completion/admission
    pending_path = archive / "epoch-transition.json"
    if _exists(pending_path):
        pending = _load(archive, pending_path.name, MaintenanceEpochTransition)
        if (
            pending.plan_sha256 != plan.record_sha256
            or pending.previous_marker_sha256 != previous.marker_sha256
        ):
            raise FaultRetirementError(_ERROR)
    else:
        if collect_previous_epoch(root) != previous:
            raise FaultRetirementError(_ERROR)
        _require_host_executable(root, plan)
        _kernel(plan)
        pending = MaintenanceEpochTransition.create(
            plan_sha256=plan.record_sha256,
            previous_marker_sha256=previous.marker_sha256,
            recorded_at=datetime.now(UTC),
        )
        _save(archive, pending_path.name, pending)
    expected = _require_control(target, previous.controls[0])
    _verified_marker(root, marker=_load(target, MARKER_NAME, InspectionMarker), reserved_epochs=1)
    if body == expected:
        if collect_previous_epoch(root) != previous:
            raise FaultRetirementError(_ERROR)
        _require_host_executable(root, plan)
        _kernel(plan)
        _replace_marker(root, body, pending)
    elif _load(root, MARKER_NAME, MaintenanceEpochTransition) != pending:
        raise FaultRetirementError(_ERROR)
    # Pending marker intentionally cannot pass any startup authority parser.
    for ref in previous.controls[1:]:
        if _exists(root / ref.name):
            _require_control(root, ref)
            _require_control(target, ref)
            with _directory(root) as descriptor:
                os.unlink(ref.name, dir_fd=descriptor)
                os.fsync(descriptor)
    live, archived = root / COMPLETIONS, target / COMPLETIONS
    if _exists(live):
        if (
            _exists(archived)
            or _completion_inventory(root, marker=_load(target, MARKER_NAME, InspectionMarker))
            != previous.completion_files
        ):
            raise FaultRetirementError(_ERROR)
        with _directory(root) as source, _directory(target, private=True) as dest:
            os.rename(COMPLETIONS, COMPLETIONS, src_dir_fd=source, dst_dir_fd=dest)
            os.fsync(source)
            os.fsync(dest)
    verify_previous_epoch(archive, previous)


def finalize_epoch(
    root: Path, archive: Path, plan: FaultRetirementPlan, receipt: FaultRetirementReceipt
) -> None:
    previous = plan.previous_maintenance
    assert previous is not None
    verify_previous_epoch(archive, previous)
    if _exists(archive / "marker.json"):
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
    body = _read(root, MARKER_NAME)
    if body == marker.model_dump_json().encode():
        return
    pending = _load(archive, "epoch-transition.json", MaintenanceEpochTransition)
    if _load(root, MARKER_NAME, MaintenanceEpochTransition) != pending:
        raise FaultRetirementError(_ERROR)
    _replace_marker(root, body, marker)
