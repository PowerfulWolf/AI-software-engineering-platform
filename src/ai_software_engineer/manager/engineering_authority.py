"""Deterministic bounded engineering admissions over frozen organization policy."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath

from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.engineering_authority import (
    EngineeringAdmission,
    EngineeringCapability,
)
from ai_software_engineer.domain.prerequisite_repair import PrerequisiteRepairPlan
from ai_software_engineer.domain.task import Task
from ai_software_engineer.recovery.models import RecoveryRejected, digest
from ai_software_engineer.recovery.store import FileRecoveryStore


class EngineeringRejectionKind(StrEnum):
    LEGACY_AUTHORITY = "LEGACY_AUTHORITY"
    FROZEN_INPUT_CHANGED = "FROZEN_INPUT_CHANGED"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    SCOPE_CHANGE = "SCOPE_CHANGE"


class EngineeringAuthorityRejected(RecoveryRejected):
    """Stable engineering responsibility; caller does not classify error prose."""

    def __init__(self, kind: EngineeringRejectionKind, message: str) -> None:
        self.kind = kind
        super().__init__(message)


class EngineeringAuthority:
    """Shared Task ledger; a crash never loses a consumed policy admission.

    Only composition provides the existing private Team directory. Model and
    request text never choose this path, scope, policy, or an operator identity.
    Callers must still validate authoritative current plan facts before and after
    admission and use the existing queue/executor fences for actual work.
    """

    def __init__(self, ledger_root: Path) -> None:
        self.ledger_root = ledger_root

    def admit(
        self,
        *,
        task: Task,
        store: FileRecoveryStore,
        plan_sha256: str,
        facts_sha256: str,
        capabilities: tuple[EngineeringCapability, ...],
        at: datetime,
    ) -> EngineeringAdmission:
        policy = task.engineering_policy
        if policy is None:
            raise EngineeringAuthorityRejected(
                EngineeringRejectionKind.LEGACY_AUTHORITY,
                "旧任务没有冻结工程预授权，需工程负责人处理",  # noqa: RUF001
            )
        scope = policy.scope
        if (
            task.repository != scope.repository_root
            or scope.team_id != store._scope.team_id
            or scope.repository_id != store._scope.repository_id
            or scope.repository_root != store._scope.repository_root
        ):
            raise EngineeringAuthorityRejected(
                EngineeringRejectionKind.FROZEN_INPUT_CHANGED,
                "工程预授权与当前团队、仓库或任务不一致",
            )
        if (
            not capabilities
            or len(set(capabilities)) != len(capabilities)
            or any(policy.allowance(capability) == 0 for capability in capabilities)
        ):
            raise EngineeringAuthorityRejected(
                EngineeringRejectionKind.CAPABILITY_UNAVAILABLE,
                "所需能力未获组织工程授权",
            )
        identity = digest({"repository_id": scope.repository_id, "task_id": task.id})
        ledger = FileRecoveryStore.initialize(self.ledger_root / identity, scope=store._scope)
        with ledger.execution_lock():
            previous = ledger.list_engineering_admissions()
            for record in previous:
                self.validate(task=task, record=record)
                if record.plan_sha256 == plan_sha256:
                    if record.facts_sha256 != facts_sha256 or record.capabilities != capabilities:
                        raise EngineeringAuthorityRejected(
                            EngineeringRejectionKind.FROZEN_INPUT_CHANGED,
                            "已封存工程动作的事实或能力发生变化",
                        )
                    return store.put_engineering_admission(record)
            if sorted(record.admission_number for record in previous) != list(
                range(1, len(previous) + 1)
            ):
                raise RecoveryRejected("工程授权预算记录不完整")
            if len(previous) >= policy.max_total_admissions or any(
                sum(capability in record.capabilities for record in previous)
                >= policy.allowance(capability)
                for capability in capabilities
            ):
                raise EngineeringAuthorityRejected(
                    EngineeringRejectionKind.BUDGET_EXHAUSTED,
                    "组织工程恢复预算已耗尽，需工程负责人决定",  # noqa: RUF001
                )
            record = EngineeringAdmission.create(
                task_id=task.id,
                task_intent_sha256=task_intent_sha256(task),
                policy=policy,
                policy_sha256=policy.policy_sha256,
                plan_sha256=plan_sha256,
                facts_sha256=facts_sha256,
                capabilities=capabilities,
                admission_number=len(previous) + 1,
                admitted_at=at,
            )
            # Publish the shared budget first. If the local copy fails, replay
            # restores this exact record rather than issuing a fresh authority.
            return store.put_engineering_admission(ledger.put_engineering_admission(record))

    @staticmethod
    def validate(*, task: Task, record: EngineeringAdmission) -> None:
        record.validate_integrity()
        if (
            task.engineering_policy is None
            or task.engineering_policy != record.policy
            or task.id != record.task_id
            or task_intent_sha256(task) != record.task_intent_sha256
        ):
            raise EngineeringAuthorityRejected(
                EngineeringRejectionKind.FROZEN_INPUT_CHANGED,
                "工程动作不再匹配任务的冻结范围与授权",
            )

    @staticmethod
    def require_in_scope_repair(task: Task, plan: PrerequisiteRepairPlan) -> None:
        """Containment, not pattern expansion; partial glob overlap fails closed."""
        constraints = task.constraints
        if constraints is None or not constraints.allowed_paths:
            raise EngineeringAuthorityRejected(
                EngineeringRejectionKind.SCOPE_CHANGE, "原任务没有可核验的源码修复范围"
            )
        for path in plan.request.write_paths:
            root = path.removesuffix("/**")
            allowed = any(
                path == value
                or (
                    value.endswith("/**")
                    and PurePosixPath(root).is_relative_to(PurePosixPath(value.removesuffix("/**")))
                )
                for value in constraints.allowed_paths
            )
            # Conservative overlap handling also rejects directory requests
            # containing a denied descendant; a model cannot narrow after approval.
            denied = any(
                PurePosixPath(root).match(value)
                or PurePosixPath(value.removesuffix("/**")).is_relative_to(PurePosixPath(root))
                or (
                    value.endswith("/**")
                    and PurePosixPath(root).is_relative_to(PurePosixPath(value.removesuffix("/**")))
                )
                for value in constraints.denied_paths
            )
            if not allowed or denied:
                raise EngineeringAuthorityRejected(
                    EngineeringRejectionKind.SCOPE_CHANGE,
                    "源码前提修复超出原任务范围，需产品或工程精确决定",  # noqa: RUF001
                )
