"""Local maintenance completion; no Requirement execution or historical repair."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, model_validator
from pymysql import MySQLError

from ai_software_engineer.config.production import ProductionConfig
from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.owned_sessions import observe_current_process

from .fault_retirement import (
    MARKER_NAME,
    InspectionMarker,
    _directory,
    _load,
    _read,
    _Record,
    _save,
    _sha,
    _verified_marker,
    replacement_lock,
)
from .maintenance_names import COMPLETION_RECEIPT_NAME as RECEIPT_NAME
from .maintenance_names import NORMAL_ADMISSION_NAME as ADMISSION_NAME
from .maintenance_queue import MaintenanceQueueInventory, observe_maintenance_queue
from .service_lifecycle import (
    ServiceInstance,
    ServiceLifecycleError,
    ServiceLifecycleStore,
    ServiceShutdownAction,
    ServiceShutdownRequest,
    ServiceShutdownResult,
    ServiceState,
)

_ERROR = "维护完成记录无法核验; 保留维护限制、故障归档和原需求。"
_STOP = "当前服务尚未完成可验证的安全退出; 请先使用服务脚本 stop 安全收尾, 再准备完成维护。"
_DRIFT = "维护方案已过期: 服务、配置或队列发生变化; 请重新准备完成维护, 原需求保持暂停。"


class MaintenanceCompletionError(ServiceLifecycleError):
    """Fixed operator-facing refusal without record contents or credentials."""


class MaintenanceCompletionPlan(_Record):
    kind: Literal["maintenance_completion_plan"] = "maintenance_completion_plan"
    marker_sha256: Sha256
    retirement_plan_sha256: Sha256
    retirement_receipt_sha256: Sha256
    config_sha256: Sha256
    scope_correction_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    principal_uid: Annotated[StrictInt, Field(ge=0)]
    instance: ServiceInstance
    request: ServiceShutdownRequest
    result: ServiceShutdownResult
    inventory: MaintenanceQueueInventory
    historical_execution_outcome: Literal["UNKNOWN"] = "UNKNOWN"
    requirement_action: Literal["NONE"] = "NONE"

    @model_validator(mode="after")
    def exact_ready(self) -> Self:
        if (
            self.instance.state is not ServiceState.READY
            or self.result.state is not ServiceState.READY
            or self.request.action is not ServiceShutdownAction.SHUTDOWN
            or not self.request.matches(self.instance)
            or not self.result.matches(self.request)
            or self.instance.started_at > self.request.requested_at
            or self.request.requested_at > self.result.recorded_at
            or self.result.recorded_at != self.instance.updated_at
            or self.result.recorded_at > self.recorded_at
            or not self.inventory.idle
        ):
            raise ValueError(_ERROR)
        return self


class MaintenanceCompletionReceipt(_Record):
    kind: Literal["maintenance_completion_receipt"] = "maintenance_completion_receipt"
    plan_sha256: Sha256
    marker_sha256: Sha256
    principal_uid: Annotated[StrictInt, Field(ge=0)]
    supersedes_receipt_sha256: Sha256 | None = None
    successor_mode: Literal["normal"] = "normal"
    historical_execution_outcome: Literal["UNKNOWN"] = "UNKNOWN"
    requirement_action: Literal["NONE"] = "NONE"


class MaintenanceNormalAdmission(_Record):
    kind: Literal["maintenance_normal_admission"] = "maintenance_normal_admission"
    receipt_sha256: Sha256
    plan_sha256: Sha256
    inventory_sha256: Sha256
    principal_uid: Annotated[StrictInt, Field(ge=0)]
    requirement_action: Literal["NONE"] = "NONE"


def _exists(root: Path, name: str) -> bool:
    try:
        (root / name).lstat()
    except FileNotFoundError:
        return False
    return True


def _plan_root(root: Path, digest: str, *, create: bool = False) -> Path:
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise MaintenanceCompletionError(_ERROR)
    base = root / "console-maintenance-completions"
    with _directory(root) as fd:
        if create and not _exists(root, base.name):
            base.mkdir(mode=0o700)
            os.fsync(fd)
    with _directory(base, private=True) as fd:
        target = base / digest
        if create and not _exists(base, digest):
            target.mkdir(mode=0o700)
            os.fsync(fd)
    with _directory(target, private=True):
        return target


def _observe(environment: Mapping[str, str]) -> MaintenanceCompletionPlan:
    root = ServiceLifecycleStore.from_environment(environment).root
    predecessor, receipt = _verified_marker(root)
    marker = _load(root, MARKER_NAME, InspectionMarker)
    store = ServiceLifecycleStore(root)
    instance, request, result = store.read_instance(), store.read_request(), store.read_result()
    if (
        instance is None
        or request is None
        or result is None
        or instance.instance_id == predecessor.instance.instance_id
        or instance.started_at < marker.recorded_at
        or instance.state is not ServiceState.READY
        or result.state is not ServiceState.READY
        or request.action is not ServiceShutdownAction.SHUTDOWN
        or not request.matches(instance)
        or not result.matches(request)
        or result.recorded_at != instance.updated_at
        or result.recorded_at < request.requested_at
    ):
        raise MaintenanceCompletionError(_STOP)
    _, current = observe_current_process(instance.pid)
    if current is not None:
        raise MaintenanceCompletionError(_STOP)
    if _exists(root, "ase-console-supervisor.pid") or _exists(root, "configuration-apply.request"):
        raise MaintenanceCompletionError(
            "服务监督器或配置应用尚未安全收尾; 请先用服务脚本 stop, 保留维护限制。"
        )
    source = ProductionConfig.path_from_environment(environment)
    body = _read(source.parent, source.name, bound=1_000_000, private=False)
    config = ProductionConfig.model_validate_json(body)
    # A correction is a separate, explicit engineering decision. The original
    # retirement's diagnostic scope remains byte-identical and UNKNOWN.
    from .maintenance_scope_correction import (
        revalidate_scope_correction,
        verified_scope_correction,
    )

    correction = verified_scope_correction(root, predecessor.record_sha256)
    if correction is None:
        if config.platform_root != predecessor.scope.platform_root:
            raise MaintenanceCompletionError(_ERROR)
        correction_sha256 = None
    else:
        correction_plan, decision = correction
        if (
            config.platform_root != decision.target_platform_root
            or _sha(body) != decision.target_config_sha256
        ):
            raise MaintenanceCompletionError(_ERROR)
        revalidate_scope_correction(environment, correction_plan)
        correction_sha256 = decision.record_sha256
    try:
        inventory = observe_maintenance_queue(config, environment)
    except (OSError, ValueError, RuntimeError, MySQLError) as error:
        raise MaintenanceCompletionError(
            "无法完整读取待执行队列; 维护限制保留, 请检查数据库和已有执行记录后重试。"
        ) from error
    if not inventory.idle:
        raise MaintenanceCompletionError(
            f"待执行队列尚未清空: {len(inventory.blocked_operation_ids)} 个未结束操作、"
            f"{len(inventory.blocked_work_item_ids)} 个待执行工作、"
            f"{len(inventory.active_lease_ids)} 个活动执行租约。请核实原工作, 维护限制保留。"
        )
    return MaintenanceCompletionPlan.create(
        recorded_at=datetime.now(UTC),
        marker_sha256=marker.record_sha256,
        retirement_plan_sha256=predecessor.record_sha256,
        retirement_receipt_sha256=receipt.record_sha256,
        principal_uid=os.getuid(),
        config_sha256=_sha(body),
        scope_correction_sha256=correction_sha256,
        instance=instance,
        request=request,
        result=result,
        inventory=inventory,
    )


def _same_facts(left: MaintenanceCompletionPlan, right: MaintenanceCompletionPlan) -> bool:
    return left.model_dump(exclude={"recorded_at", "record_sha256"}) == right.model_dump(
        exclude={"recorded_at", "record_sha256"}
    )


def _receipt_plan(root: Path, receipt: MaintenanceCompletionReceipt) -> MaintenanceCompletionPlan:
    plan = _load(_plan_root(root, receipt.plan_sha256), "plan.json", MaintenanceCompletionPlan)
    marker = _load(root, MARKER_NAME, InspectionMarker)
    from .maintenance_scope_correction import verified_scope_correction

    correction = verified_scope_correction(root, marker.plan_sha256)
    if (
        plan.record_sha256 != receipt.plan_sha256
        or plan.marker_sha256 != marker.record_sha256
        or receipt.marker_sha256 != marker.record_sha256
        or plan.retirement_plan_sha256 != marker.plan_sha256
        or plan.retirement_receipt_sha256 != marker.receipt_sha256
        or receipt.principal_uid != plan.principal_uid
        or plan.principal_uid != os.getuid()
        or receipt.recorded_at < plan.recorded_at
        or plan.scope_correction_sha256
        != (correction[1].record_sha256 if correction is not None else None)
    ):
        raise MaintenanceCompletionError(_ERROR)
    return plan


def verified_completion(
    root: Path,
) -> tuple[MaintenanceCompletionPlan, MaintenanceCompletionReceipt] | None:
    """Verify the entire append-only completion chain, including abandoned plans."""
    if not _exists(root, RECEIPT_NAME):
        if _exists(root, ADMISSION_NAME):
            raise MaintenanceCompletionError(_ERROR)
        return None
    anchor = _load(root, RECEIPT_NAME, MaintenanceCompletionReceipt)
    return _verify_chain(root, anchor, _completion_records(root))


def _completion_records(
    root: Path,
) -> dict[str, tuple[MaintenanceCompletionPlan, MaintenanceCompletionReceipt]]:
    base = root / "console-maintenance-completions"
    records = {}
    with _directory(base, private=True):
        for path in sorted(base.iterdir()):
            directory = _plan_root(root, path.name)
            if not _exists(directory, "receipt.json"):
                continue  # unapproved prepared plan
            value = _load(directory, "receipt.json", MaintenanceCompletionReceipt)
            if value.plan_sha256 != path.name or value.record_sha256 in records:
                raise MaintenanceCompletionError(_ERROR)
            records[value.record_sha256] = (_receipt_plan(root, value), value)
    return records


def _verify_chain(
    root: Path,
    anchor: MaintenanceCompletionReceipt,
    records: dict[str, tuple[MaintenanceCompletionPlan, MaintenanceCompletionReceipt]],
) -> tuple[MaintenanceCompletionPlan, MaintenanceCompletionReceipt]:
    if anchor.supersedes_receipt_sha256 is not None:
        raise MaintenanceCompletionError(_ERROR)
    if anchor.record_sha256 not in records or records[anchor.record_sha256][1] != anchor:
        raise MaintenanceCompletionError(_ERROR)
    visited = {anchor.record_sha256}
    current = records[anchor.record_sha256]
    while True:
        successors = [
            entry
            for entry in records.values()
            if entry[1].supersedes_receipt_sha256 == current[1].record_sha256
        ]
        if not successors:
            break
        if len(successors) != 1 or successors[0][1].recorded_at < current[1].recorded_at:
            raise MaintenanceCompletionError(_ERROR)
        current = successors[0]
        if current[1].record_sha256 in visited:
            raise MaintenanceCompletionError(_ERROR)
        visited.add(current[1].record_sha256)
    if len(visited) != len(records):
        raise MaintenanceCompletionError(_ERROR)
    plan, receipt = current
    if _exists(root, ADMISSION_NAME):
        admission = _load(root, ADMISSION_NAME, MaintenanceNormalAdmission)
        if (
            admission.receipt_sha256 != receipt.record_sha256
            or admission.plan_sha256 != plan.record_sha256
            or admission.inventory_sha256 != plan.inventory.inventory_sha256
            or admission.principal_uid != plan.principal_uid
            or admission.recorded_at < receipt.recorded_at
        ):
            raise MaintenanceCompletionError(_ERROR)
    return plan, receipt


def _recover_anchor(root: Path) -> None:
    """Finalize an already explicitly confirmed root after interrupted publication."""
    if _exists(root, RECEIPT_NAME) or not _exists(root, "console-maintenance-completions"):
        return
    records = _completion_records(root)
    if not records:
        return
    roots = [value[1] for value in records.values() if value[1].supersedes_receipt_sha256 is None]
    if len(roots) != 1:
        raise MaintenanceCompletionError(_ERROR)
    _verify_chain(root, roots[0], records)
    _save(root, RECEIPT_NAME, roots[0])


def prepare_maintenance_completion(environment: Mapping[str, str]) -> MaintenanceCompletionPlan:
    root = ServiceLifecycleStore.from_environment(environment).root
    with replacement_lock(root):
        _verified_marker(root)
        _recover_anchor(root)
        if _exists(root, ADMISSION_NAME):
            raise MaintenanceCompletionError(
                "已完成普通模式启动核验; 请使用服务脚本 start, 勿重复准备。"
            )
        if _exists(root, RECEIPT_NAME):
            _verified_marker(root)
            verified_completion(root)
        plan = _observe(environment)
        _save(_plan_root(root, plan.record_sha256, create=True), "plan.json", plan)
        return plan


def complete_maintenance(
    environment: Mapping[str, str], *, plan_sha256: str, confirm_restore_normal: bool
) -> MaintenanceCompletionReceipt:
    if not confirm_restore_normal or environment.get("ASE_CONSOLE_MODE", "normal") != "normal":
        raise MaintenanceCompletionError(
            "请明确确认恢复普通模式, 并取消显式 ASE_CONSOLE_MODE=inspection; 原需求不会自动继续。"
        )
    root = ServiceLifecycleStore.from_environment(environment).root
    with replacement_lock(root):
        plan = _load(_plan_root(root, plan_sha256), "plan.json", MaintenanceCompletionPlan)
        if plan.record_sha256 != plan_sha256:
            raise MaintenanceCompletionError(_ERROR)
        _verified_marker(root)
        _recover_anchor(root)
        existing = verified_completion(root)
        if existing is not None and existing[0] == plan:
            return existing[1]
        if _exists(root, ADMISSION_NAME):
            raise MaintenanceCompletionError(_ERROR)
        if not _same_facts(plan, _observe(environment)):
            raise MaintenanceCompletionError(_DRIFT)
        directory = _plan_root(root, plan_sha256)
        previous = existing[1].record_sha256 if existing is not None else None
        if _exists(directory, "receipt.json"):
            receipt = _load(directory, "receipt.json", MaintenanceCompletionReceipt)
            if (
                receipt.supersedes_receipt_sha256 != previous
                or _receipt_plan(root, receipt) != plan
            ):
                raise MaintenanceCompletionError(_ERROR)
        else:
            receipt = MaintenanceCompletionReceipt.create(
                recorded_at=datetime.now(UTC),
                plan_sha256=plan.record_sha256,
                marker_sha256=plan.marker_sha256,
                principal_uid=os.getuid(),
                supersedes_receipt_sha256=previous,
            )
            _save(directory, "receipt.json", receipt)
        if existing is None:
            _save(root, RECEIPT_NAME, receipt)
        return receipt


def admit_completed_maintenance(environment: Mapping[str, str]) -> None:
    """Fresh first-normal-start check before any writer constructor, never an Agent skill."""
    root = ServiceLifecycleStore.from_environment(environment).root
    if not _exists(root, MARKER_NAME):
        if _exists(root, RECEIPT_NAME) or _exists(root, ADMISSION_NAME):
            raise MaintenanceCompletionError(_ERROR)
        return
    # The service launcher already owns this lock. Host launch inherits its FD.
    # Direct host composition takes the same lock itself.
    from .maintenance_lock import maintenance_start_lock

    with maintenance_start_lock(root, environment):
        _verified_marker(root)
        existing = verified_completion(root)
        if existing is None:
            raise MaintenanceCompletionError(_ERROR)
        plan, receipt = existing
        if _exists(root, ADMISSION_NAME):
            if plan.scope_correction_sha256 is not None:
                from .maintenance_scope_correction import verified_scope_correction

                correction = verified_scope_correction(root, plan.retirement_plan_sha256)
                if correction is None:
                    raise MaintenanceCompletionError(_ERROR)
                selected = ProductionConfig.from_file(
                    ProductionConfig.path_from_environment(environment)
                )
                if (
                    selected.platform_root != correction[0].target_platform_root
                    or selected.team_id != correction[0].target_team_id
                ):
                    raise MaintenanceCompletionError(_ERROR)
            return
        current = _observe(environment)
        if not _same_facts(plan, current):
            raise MaintenanceCompletionError(_DRIFT)
        admission = MaintenanceNormalAdmission.create(
            recorded_at=datetime.now(UTC),
            receipt_sha256=receipt.record_sha256,
            plan_sha256=plan.record_sha256,
            inventory_sha256=current.inventory.inventory_sha256,
            principal_uid=os.getuid(),
        )
        _save(root, ADMISSION_NAME, admission)
