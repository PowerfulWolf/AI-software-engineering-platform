"""Local retention of retired diagnostic logs, independent of service authority."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field, StrictInt

from ai_software_engineer.domain.artifact import Sha256

from .fault_retirement import (
    _archive_root,
    _directory,
    _load,
    _Record,
    _require_archived_log,
    _require_no_log_writers,
    _save,
    _verified_marker,
    replacement_lock,
)
from .service_lifecycle import ServiceLifecycleError, ServiceLifecycleStore

_INTENT = "log-purge-intent.json"
_RECEIPT = "log-purge-receipt.json"
_ERROR = "归档日志清理无法核验; 保留当前服务日志与控制记录。"


class ArchivedLogPurgeIntent(_Record):
    kind: Literal["archived_console_log_purge_intent"] = "archived_console_log_purge_intent"
    plan_sha256: Sha256
    retirement_receipt_sha256: Sha256
    principal_uid: Annotated[StrictInt, Field(ge=0)]
    log_sha256: Sha256
    log_byte_count: Annotated[StrictInt, Field(ge=0)]
    initial_observation: Literal["PRESENT", "ALREADY_ABSENT"]
    requirement_action: Literal["NONE"] = "NONE"


class ArchivedLogPurgeReceipt(_Record):
    kind: Literal["archived_console_log_purge_receipt"] = "archived_console_log_purge_receipt"
    intent_sha256: Sha256
    final_observation: Literal["ABSENT"] = "ABSENT"
    requirement_action: Literal["NONE"] = "NONE"


def purge_archived_log(
    environment: Mapping[str, str], *, confirm_delete_archived_log: bool
) -> ArchivedLogPurgeReceipt:
    """Delete only the exact marker-bound retired log; preserve all control facts."""
    if confirm_delete_archived_log is not True:
        raise ServiceLifecycleError("请明确确认删除已退休归档日志; 当前日志与交付记录保留。")
    try:
        return _purge_archived_log(environment)
    except (OSError, ValueError) as error:
        raise ServiceLifecycleError(_ERROR) from error


def _purge_archived_log(environment: Mapping[str, str]) -> ArchivedLogPurgeReceipt:
    root = ServiceLifecycleStore.from_environment(environment).root
    with replacement_lock(root):
        plan, retirement = _verified_marker(root)
        archive = _archive_root(root, plan.record_sha256)
        with _directory(archive, private=True) as directory:
            try:
                os.stat("ase-console.log", dir_fd=directory, follow_symlinks=False)
                present = True
            except FileNotFoundError:
                present = False
            if present:
                _require_archived_log(archive, plan)
                _require_no_log_writers(archive)
            try:
                intent = _load(archive, _INTENT, ArchivedLogPurgeIntent)
            except FileNotFoundError:
                intent = ArchivedLogPurgeIntent.create(
                    recorded_at=datetime.now(UTC),
                    plan_sha256=plan.record_sha256,
                    retirement_receipt_sha256=retirement.record_sha256,
                    principal_uid=os.getuid(),
                    log_sha256=retirement.log_sha256,
                    log_byte_count=retirement.log_byte_count,
                    initial_observation="PRESENT" if present else "ALREADY_ABSENT",
                )
                _save(archive, _INTENT, intent)
            if (
                intent.plan_sha256 != plan.record_sha256
                or intent.retirement_receipt_sha256 != retirement.record_sha256
                or intent.principal_uid != os.getuid()
                or intent.log_sha256 != retirement.log_sha256
                or intent.log_byte_count != retirement.log_byte_count
                or intent.recorded_at < retirement.recorded_at
                or (present and intent.initial_observation != "PRESENT")
            ):
                raise ServiceLifecycleError(_ERROR)
            try:
                receipt = _load(archive, _RECEIPT, ArchivedLogPurgeReceipt)
            except FileNotFoundError:
                receipt = None
            if receipt is not None:
                if (
                    present
                    or receipt.intent_sha256 != intent.record_sha256
                    or receipt.recorded_at < intent.recorded_at
                ):
                    raise ServiceLifecycleError(_ERROR)
                return receipt
            if present:
                # Recheck the exact inode just before unlink; never follow links or
                # select the live state-directory log. The sealed digest is historical.
                _require_archived_log(archive, plan)
                os.unlink("ase-console.log", dir_fd=directory)
                os.fsync(directory)
            try:
                os.stat("ase-console.log", dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ServiceLifecycleError(_ERROR)
            receipt = ArchivedLogPurgeReceipt.create(
                recorded_at=datetime.now(UTC), intent_sha256=intent.record_sha256
            )
            _save(archive, _RECEIPT, receipt)
            return receipt
