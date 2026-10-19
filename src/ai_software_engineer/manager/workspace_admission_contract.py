"""Public engineering evidence sealing; testimony alone grants no execution."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore
from ai_software_engineer.domain.engineering_authority import (
    EngineeringScope,
    LocalOperatorPrincipal,
    OperatorDuty,
)
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.task import Task
from ai_software_engineer.domain.workspace_admission_contract import (
    WorkspaceAdmissionAdapterContract,
    WorkspaceAdmissionAdapterContractRecord,
    WorkspaceAdmissionAdapterSource,
)
from ai_software_engineer.knowledge.claim_identity import claim_identity_sha256
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.work_queue.execution_store import QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem

SUPPORTED_ADAPTER_REVISION = "12caa6e14e47188d45bda9e7264e461acf45db89"
_SOURCE_PREFIX = "src/ai_software_engineer/"
SUPPORTED_ADAPTER_SOURCES = tuple(
    WorkspaceAdmissionAdapterSource(path=_SOURCE_PREFIX + path, sha256=sha256)
    for path, sha256 in (
        ("agents/codex_cli.py", "2dd36fe7ab92f41b6fa18634ff6c31460e5bdc3bbec489877fed16c74b587683"),
        ("agents/execution.py", "7700d52f24041f8bec2e644942db47d06bae516230ec9d71f159bfee389d1f0f"),
        ("agents/fallback.py", "f699d1c0cec0333f80188e307b7edb7efc9b45e1478ce5085ea08458639d2bef"),
        (
            "agents/workspace_admission.py",
            "71e512607b3096305bb649cda4f614ccc355d2c2b2bc51329bfb35871bb168e3",
        ),
        (
            "manager/baseline_admission.py",
            "72de935f75f295013b8d6345d40187adb4ccb9707ace58abb572f863710ff50c",
        ),
        (
            "manager/production_delivery.py",
            "7d0dfb021fd9e246b2e25a5ba739022e7ccba72696c63f1fde3751a14ab79011",
        ),
        (
            "work_queue/invocation.py",
            "8fce1649b9a914ffd80180591806f5b6f550874f43c7a5a3ad0e469a13b38b06",
        ),
    )
)


def require_supported_adapter_contract(record: WorkspaceAdmissionAdapterContractRecord) -> None:
    record.validate_integrity()
    declaration = record.declaration
    if (
        declaration.platform_revision != SUPPORTED_ADAPTER_REVISION
        or declaration.adapter_sources != SUPPORTED_ADAPTER_SOURCES
    ):
        raise ValueError("工作区准入部署声明不是受支持的精确历史适配器契约")


class WorkspaceAdmissionAdapterContractStore:
    def __init__(self, state: Path, task_id: str, *, read_only: bool = True) -> None:
        if not task_id or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for character in task_id
        ):
            raise ValueError("invalid workspace adapter testimony Task identity")
        self.task_id = task_id
        self.root = state / "continuations" / task_id / "workspace-admission-contracts"
        if not read_only:
            # Initialize the existing private Task ledger through its own no-follow
            # writer; never broaden or chmod an unsafe existing directory.
            KnowledgeRecordStore(state / "continuations")
            FileContinuationStore.initialize(self.root.parent, task_id=task_id)
            self.root.mkdir(mode=0o700, exist_ok=True)
        self.records = (
            KnowledgeRecordStore(self.root, read_only=read_only)
            if self.root.exists() or not read_only
            else None
        )

    def for_run(self, run_id: str) -> WorkspaceAdmissionAdapterContractRecord | None:
        if self.records is None:
            return None
        record = self.records.find(
            "adapter-declarations", run_id, WorkspaceAdmissionAdapterContractRecord
        )
        if record is not None:
            require_supported_adapter_contract(record)
            if record.declaration.task_id != self.task_id or record.declaration.run_id != run_id:
                raise ValueError("工作区适配器部署声明归属不一致")
        return record

    def list_for_task(self) -> tuple[WorkspaceAdmissionAdapterContractRecord, ...]:
        if self.records is None:
            return ()
        records = self.records.list(
            "adapter-declarations", WorkspaceAdmissionAdapterContractRecord, limit=128
        )
        for record in records:
            if self.for_run(record.declaration.run_id) != record:
                raise ValueError("工作区适配器部署声明索引不一致")
        return records

    def put(
        self, record: WorkspaceAdmissionAdapterContractRecord
    ) -> WorkspaceAdmissionAdapterContractRecord:
        require_supported_adapter_contract(record)
        if self.records is None or record.declaration.task_id != self.task_id:
            raise ValueError("工作区适配器部署声明不属于当前任务")
        return self.records.put("adapter-declarations", record.declaration.run_id, record)


class WorkspaceAdmissionClaimReader(Protocol):
    def original_claim(self, lease_id: str) -> QueueClaim: ...


def seal_workspace_admission_adapter_contract(
    *,
    state: Path,
    declaration: WorkspaceAdmissionAdapterContract,
    principal: LocalOperatorPrincipal,
    task: Task,
    item: QueuedWorkItem,
    step: QueuedRoleStep,
    scope: EngineeringScope,
    route_root: Path,
    queue: WorkspaceAdmissionClaimReader,
    requirement_id: str,
    at: datetime,
) -> WorkspaceAdmissionAdapterContractRecord:
    """Seal current attributed testimony after exact immutable-boundary checks.

    The caller holds the Task lock. The observer must still independently validate
    the complete refusal/gate/contradiction proof before this can support recovery.
    """
    principal.require_duty(OperatorDuty.ENGINEERING)
    record = WorkspaceAdmissionAdapterContractRecord.create(
        declaration=declaration, operator_principal=principal, submitted_at=at
    )
    require_supported_adapter_contract(record)
    invocations = KnowledgeRecordStore(state / "invocations", read_only=True)
    start = invocations.get("invocation-starts", item.id, DeliveryInvocationStart)
    outcome = invocations.get("invocation-outcomes", item.id, DeliveryInvocationOutcome)
    start.validate_integrity()
    outcome.validate_integrity()
    claim = queue.original_claim(start.lease_id)
    routes = FileModelRouteAttemptStore(route_root, read_only=True).list_for_run(
        start.request.run_id
    )
    if len(routes) != 1:
        raise ValueError("部署声明缺少唯一精确模型路由")
    route = routes[0]
    route.validate_integrity()
    if (
        declaration.scope != scope
        or declaration.requirement_id != requirement_id
        or declaration.task_id != task.id
        or declaration.work_item_id != item.id
        or declaration.lease_id != start.lease_id
        or claim.lease.id != start.lease_id
        or claim.work_item.id != item.id
        or claim.work_item.task_id != task.id
        or declaration.claim_sha256 != claim_identity_sha256(claim)
        or declaration.run_id != start.request.run_id
        or start.request.task_id != task.id
        or start.request.role is not AgentRole.CODER
        or item.role is not AgentRole.CODER
        or start.request.attempt != item.attempt
        or start.request.attempt != task.attempts
        or start.work_item_id != item.id
        or start.checkpoint_sequence != item.checkpoint_sequence
        or (
            step.boundary.task_id,
            step.boundary.role,
            step.boundary.attempt,
            step.boundary.checkpoint_sequence,
        )
        != (task.id, item.role, item.attempt, item.checkpoint_sequence)
        or declaration.source_revision != start.request.source_revision
        or declaration.source_revision != step.boundary.source_revision
        or declaration.invocation_start_sha256 != start.start_sha256
        or declaration.invocation_outcome_sha256 != outcome.outcome_sha256
        or outcome.start != start
        or declaration.route_attempt_sha256 != route.attempt_sha256
        or route.result != outcome.result
        or route.request_sha256 != digest(start.request.to_wire())
        or route.route_index != 1
        or route.route_kind != "codex_cli"
        or route.provider != "codex"
        or declaration.deployment_observed_at > start.started_at
        or at < route.completed_at
    ):
        raise ValueError("部署声明与当前精确任务、原调用、路由或部署时间不一致")
    store = WorkspaceAdmissionAdapterContractStore(state, task.id, read_only=False)
    existing = store.for_run(start.request.run_id)
    if existing is not None:
        if existing.declaration != declaration or existing.operator_principal != principal:
            raise ValueError("已封存部署声明不可改写")
        return existing
    return store.put(record)
