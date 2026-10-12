"""Read complete actual no-start capacity inputs without granting execution authority."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import JsonValue, TypeAdapter

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, model_route_root
from ai_software_engineer.artifacts import ArtifactStore
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.context.execution_baseline import (
    ExecutionBaselineContext,
    PreservedWorktreeBaselineContext,
    ReappliedBaselineReferenceContext,
    execution_baseline_from_context,
    parse_execution_baseline_context,
)
from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_resolution import VerifierPreparationEvidence
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.task import Task, task_matches_dispatch
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.context_capacity import ContextCapacityReceipt
from ai_software_engineer.manager.delivery_preflight import DeliveryPreflightReceipt
from ai_software_engineer.manager.verifier_preparation import (
    VerifierPreparationCheckpoint,
    VerifierPreparationIntent,
    observe_verifier_preparation,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.team_workspace import _read_regular, _reject_symlinks
from ai_software_engineer.work_queue.execution_store import QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem


class CapacityInputQueue(Protocol):
    def step_for_invocation(
        self, work_item_id: str, baseline_sha256: str | None
    ) -> QueuedRoleStep: ...

    def original_claim(self, lease_id: str) -> QueueClaim: ...


class VerifierCapacityQueue(CapacityInputQueue, Protocol):
    pass


def claimed_verifier_capacity(
    *,
    item: QueuedWorkItem,
    task: Task,
    step: QueuedRoleStep,
    prerequisites: DeliveryPreflightReceipt,
    state: Path,
    queue: VerifierCapacityQueue,
    artifacts: ArtifactStore,
) -> VerifierPreparationEvidence:
    """Verify actual READY preparation and zero role-model starts for its exact claim."""
    disposition = item.wait_disposition
    prefix = "context-capacity://"
    if (
        disposition is None
        or disposition.facts.classification != "CONTEXT_CAPACITY"
        or len(disposition.facts.evidence_ids) != 1
        or not disposition.facts.evidence_ids[0].startswith(prefix)
        or item.role not in {AgentRole.QA, AgentRole.REVIEWER}
    ):
        raise ValueError("容量恢复没有精确当前验证角色等待记录")
    identity = disposition.facts.evidence_ids[0].removeprefix(prefix)
    records = KnowledgeRecordStore(state / "delivery-preflight", read_only=True)
    receipt = records.get("context-capacity-receipts", identity, ContextCapacityReceipt)
    receipt.validate_integrity()
    request = receipt.request
    if (
        request is None
        or receipt.receipt_sha256 != identity
        or receipt.task_sha256 != digest(task.to_wire())
        or (
            receipt.work_item_id,
            receipt.dispatch_sequence,
            receipt.checkpoint_sequence,
            receipt.task_revision,
            receipt.role,
            receipt.attempt,
        )
        != (
            item.id,
            item.dispatch_sequence,
            item.checkpoint_sequence,
            item.checkpoint_sequence,
            item.role,
            item.attempt,
        )
        or task.attempts != item.attempt
        or task.status is not (TaskStatus.QA if item.role is AgentRole.QA else TaskStatus.REVIEW)
        or disposition.facts.source_revision != receipt.source_revision
        or prerequisites.status != "READY"
        or prerequisites.source_revision != receipt.source_revision
    ):
        raise ValueError("容量停止记录与当前 Task、验证阶段或输入版本不一致")
    claim = queue.original_claim(receipt.lease_id)
    baseline_root = state / "execution-baselines" / task.id
    reader = CapacityInputReader(
        state=state,
        queue=queue,
        artifacts=artifacts,
        route_root=model_route_root(state.parent),
        baselines=(
            FileExecutionBaselineStore(baseline_root, read_only=True)
            if CapacityInputReader._capacity_ledger_exists(baseline_root)
            else None
        ),
    )
    reader.require_identity(task, receipt, claim, step)
    reader.require_context(task, receipt, claim)
    reader.require_not_started(receipt)
    intents = records.list("verifier-preparation-intents", VerifierPreparationIntent)
    reader.require_record_keys(
        records,
        "verifier-preparation-intents",
        tuple(
            (f"{value.work_item_id}:{value.checkpoint_sequence}:{value.dispatch_sequence}", value)
            for value in intents
        ),
    )
    for value in intents:
        value.validate_integrity()
    intent = records.get(
        "verifier-preparation-intents",
        f"{item.id}:{item.checkpoint_sequence}:{item.dispatch_sequence}",
        VerifierPreparationIntent,
    )
    intent.validate_integrity()
    all_markers = records.list("verifier-preparations", VerifierPreparationCheckpoint)
    reader.require_record_keys(
        records,
        "verifier-preparations",
        tuple((value.checkpoint_sha256, value) for value in all_markers),
    )
    for preparation in all_markers:
        preparation.validate_integrity()
    markers = tuple(
        marker
        for marker in all_markers
        if marker.work_item_id == item.id
        and marker.dispatch_sequence == item.dispatch_sequence
        and marker.lease_id == receipt.lease_id
    )
    if len(markers) != 1:
        raise ValueError("容量恢复缺少唯一原验证准备记录, 保留当前等待")
    marker = markers[0]
    marker.validate_integrity()
    if (
        marker.result != "READY"
        or marker.failure_reason is not None
        or marker.request != request
        or marker.task_snapshot_sha256 != receipt.task_sha256
        or marker.checked_at > receipt.observed_at
        or intent.started_at > marker.checked_at
        or (
            intent.work_item_id,
            intent.lease_id,
            intent.task_id,
            intent.task_snapshot_sha256,
            intent.checkpoint_sequence,
            intent.dispatch_sequence,
            intent.request,
            intent.request_sha256,
            intent.intent_sha256,
        )
        != (
            marker.work_item_id,
            marker.lease_id,
            marker.task_id,
            marker.task_snapshot_sha256,
            marker.checkpoint_sequence,
            marker.dispatch_sequence,
            request,
            marker.request_sha256,
            marker.intent_sha256,
        )
    ):
        raise ValueError("容量停止与原 READY 验证准备或真实 claim 不一致")
    observed = observe_verifier_preparation(
        repository_workspace_root=state.parent, request=request, lease_id=receipt.lease_id
    )
    if observed.native_execution_state == "UNCERTAIN":
        raise ValueError("原验证准备是否结束尚未核实, 容量恢复暂不可继续")
    if observed != marker.observation or observed.native_failure_code is not None:
        raise ValueError("原验证准备记录已变化或执行失败, 不能作为未调用容量恢复")
    return VerifierPreparationEvidence(
        candidate_revision=receipt.source_revision,
        preparation_checkpoint_sha256=marker.checkpoint_sha256,
        previous_run_id=request.run_id,
        previous_context_manifest_id=request.context_manifest_id,
        request_sha256=digest(request.to_wire()),
        native_execution_state=observed.native_execution_state,
        native_binding_plan_sha256=observed.native_binding_plan_sha256,
        native_started_sha256=observed.native_started_sha256,
        native_finished_sha256=observed.native_finished_sha256,
        native_failure_code=None,
        prerequisite_facts_sha256=digest(
            prerequisites.model_dump(mode="json", exclude={"checked_at", "receipt_sha256"})
        ),
        budget_source=None,
        context_capacity_receipt_sha256=receipt.receipt_sha256,
        context_capacity_claim_sha256=receipt.claim_sha256,
    )


class _CapacityBaselineVerifier:
    """Verify the full historical epoch preceding one actual no-start claim."""

    def __init__(self, store: FileExecutionBaselineStore | None, claim: QueueClaim) -> None:
        self.store, self.claim = store, claim

    def expected(self, task: Task) -> ExecutionBaselineBinding | None:
        history = self.store.bindings_for_task(task.id) if self.store is not None else ()
        for binding in history:
            binding.require_task(task)
        eligible = tuple(
            binding for binding in history if binding.completed_at <= self.claim.claimed_at
        )
        return eligible[-1] if eligible else None

    def require_current(self, binding: ExecutionBaselineBinding, task: Task) -> None:
        if self.expected(task) != binding:
            raise ValueError("容量停止输入未绑定原 claim 前的最新完整执行基线")


class CapacityInputReader:
    """Shared Coder/verifier read-side proof; the caller retains Task/SQL ownership."""

    def __init__(
        self,
        *,
        state: Path,
        queue: CapacityInputQueue,
        artifacts: ArtifactStore,
        route_root: Path | None,
        baselines: FileExecutionBaselineStore | None,
        permissions: AgentPermissions | None = None,
    ) -> None:
        self.state, self.queue, self.artifacts = state, queue, artifacts
        self.route_root, self.baselines, self.permissions = route_root, baselines, permissions

    def require_identity(
        self, task: Task, marker: ContextCapacityReceipt, claim: QueueClaim, step: QueuedRoleStep
    ) -> None:
        marker.validate_integrity()
        records = KnowledgeRecordStore(self.state / "delivery-preflight", read_only=True)
        receipts = records.list("context-capacity-receipts", ContextCapacityReceipt)
        self.require_record_keys(
            records,
            "context-capacity-receipts",
            tuple((value.receipt_sha256, value) for value in receipts),
        )
        for value in receipts:
            value.validate_integrity()
        request = marker.request
        if (
            marker.origin != "final_input"
            or request is None
            or (
                marker.task_id,
                marker.task_intent_sha256,
                marker.claim_sha256,
                marker.assignment_id,
                marker.work_item_id,
                marker.role,
                marker.attempt,
                marker.dispatch_sequence,
                marker.checkpoint_sequence,
                marker.task_revision,
                marker.source_revision,
            )
            != (
                task.id,
                task_intent_sha256(task),
                digest(claim.to_wire()),
                claim.assignment.id,
                claim.work_item.id,
                claim.work_item.role,
                claim.work_item.attempt,
                claim.work_item.dispatch_sequence,
                claim.work_item.checkpoint_sequence,
                claim.work_item.checkpoint_sequence,
                step.boundary.source_revision,
            )
            or marker.observed_at < claim.claimed_at
            or (self.permissions is not None and request.permissions != self.permissions)
            or self.queue.step_for_invocation(
                claim.work_item.id, request.execution_baseline_sha256
            ).boundary
            != step.boundary
        ):
            raise ValueError("容量停止记录与真实 claim、原权限或工程输入不一致")

    def require_context(
        self, task: Task, marker: ContextCapacityReceipt, claim: QueueClaim
    ) -> None:
        context_root = self.state.parent / "contexts"
        _reject_symlinks(context_root / f"{marker.context_manifest_id}.json")
        context = FileContextStore(context_root, read_only=True).get(marker.context_manifest_id)
        request = marker.request
        assert request is not None
        if digest(context.to_wire()) != marker.context_sha256 or (
            context.task_id,
            context.role,
            context.attempt,
            context.source_revision,
            context.budget.max_input_tokens,
            context.budget.used_input_tokens,
        ) != (
            marker.task_id,
            marker.role,
            marker.attempt,
            marker.source_revision,
            marker.max_input_tokens,
            marker.context_input_tokens,
        ):
            raise ValueError("容量停止上下文身份或完整摘要不一致")
        original_tasks = tuple(section for section in context.sections if section.name == "task")
        if len(original_tasks) != 1 or original_tasks[0].truncated:
            raise ValueError("容量停止缺少完整原 Task 快照")
        original = Task.model_validate_json(original_tasks[0].content)
        if (
            digest(original.to_wire()) != marker.task_sha256
            or not task_matches_dispatch(original, task)
            or original.attempts != marker.attempt
            or original.status
            is not {
                AgentRole.CODER: TaskStatus.IMPLEMENTING,
                AgentRole.QA: TaskStatus.QA,
                AgentRole.REVIEWER: TaskStatus.REVIEW,
            }[marker.role]
        ):
            raise ValueError("容量停止的原 Task 快照与冻结意图或执行身份不一致")
        claim_sections = tuple(
            section for section in context.sections if section.name == "source:execution.claim"
        )
        if len(claim_sections) != 1 or claim_sections[0].truncated:
            raise ValueError("容量停止上下文缺少完整真实 claim")
        sealed_claim = TypeAdapter(dict[str, JsonValue]).validate_json(claim_sections[0].content)
        if claim_sections[0].uri != "claim://" + claim.lease.id or any(
            sealed_claim.get(field) != value
            for field, value in {
                "task_id": claim.work_item.task_id,
                "work_item_id": claim.work_item.id,
                "lease_id": claim.lease.id,
                "assignment_id": claim.assignment.id,
                "dispatch_sequence": claim.work_item.dispatch_sequence,
                "role": claim.work_item.role.value,
                "attempt": claim.work_item.attempt,
                "checkpoint_sequence": claim.work_item.checkpoint_sequence,
            }.items()
        ):
            raise ValueError("容量停止上下文的原 claim 与真实队列身份不一致")
        verifier = _CapacityBaselineVerifier(self.baselines, claim)
        expected = verifier.expected(original)
        if request.execution_baseline_sha256 != (
            expected.binding_sha256 if expected is not None else None
        ):
            raise ValueError("容量停止请求未绑定原 claim 前的最新执行基线")
        binding = execution_baseline_from_context(context, request, original, verifier=verifier)
        if binding is not None:
            store = self.baselines
            if store is None:
                raise ValueError("容量停止缺少完整可信执行基线存储")
            complete = ExecutionBaselineContext.from_required_context(
                binding, store.required_context(binding)
            )
            section = next(
                section for section in context.sections if section.name == "execution.baseline"
            )
            value = parse_execution_baseline_context(section.content)
            reference_matches = isinstance(value, ReappliedBaselineReferenceContext) and (
                value.binding == complete.binding
                and value.retained_patch == complete.binding.retained_patch
                and value.instructions == complete.instructions
            )
            if (
                value != complete
                and value != PreservedWorktreeBaselineContext.from_complete(complete)
                and not reference_matches
            ):
                raise ValueError("容量停止的保留补丁上下文与完整授权记录不一致")

    def require_not_started(
        self, marker: ContextCapacityReceipt, *, allow_later_claims: bool = False
    ) -> None:
        request = marker.request
        assert request is not None
        starts: tuple[DeliveryInvocationStart, ...] = ()
        root = self.state / "invocations"
        if self._capacity_ledger_exists(root):
            records = KnowledgeRecordStore(root, read_only=True)
            starts = records.list("invocation-starts", DeliveryInvocationStart)
            outcomes = records.list("invocation-outcomes", DeliveryInvocationOutcome)
            self.require_record_keys(
                records, "invocation-starts", tuple((start.work_item_id, start) for start in starts)
            )
            self.require_record_keys(
                records,
                "invocation-outcomes",
                tuple((outcome.start.work_item_id, outcome) for outcome in outcomes),
            )
            for start in (*starts, *(outcome.start for outcome in outcomes)):
                start.validate_integrity()
                if self._conflicts_with_claim(
                    marker,
                    start.request,
                    start.work_item_id,
                    start.lease_id,
                    allow_later_claims=allow_later_claims,
                ):
                    raise ValueError("容量停止的原 claim 已有模型开始或结果, 不能证明未调用")
            for outcome in outcomes:
                outcome.validate_integrity()
                if (
                    records.find(
                        "invocation-starts", outcome.start.work_item_id, DeliveryInvocationStart
                    )
                    != outcome.start
                ):
                    raise ValueError("容量停止调查发现结果与完整开始记录不一致")
        if self.route_root is None:
            raise ValueError("容量停止调查缺少真实模型路由位置")
        if self._capacity_ledger_exists(self.route_root):
            routes = FileModelRouteAttemptStore(self.route_root, read_only=True)
            for directory in self.route_root.iterdir():
                if not self._capacity_ledger_exists(directory):
                    raise ValueError("容量停止调查的路由 Run 目录不可验证")
                for path in directory.glob("*.json"):
                    _reject_symlinks(path)
                    if not path.is_file():
                        raise ValueError("容量停止调查的路由必须是 regular 普通文件")
                    _read_regular(path, 8_000_000)
                for route in routes.list_for_run(directory.name):
                    if route.task_id != marker.task_id:
                        continue
                    self._require_other_model_fact(
                        marker,
                        run_id=route.run_id,
                        context_id=route.result.context_manifest_id,
                        role=route.role,
                        source_revision=route.result.source_revision,
                        starts=starts,
                        allow_later_claims=allow_later_claims,
                        attempt=route.result.attempt,
                    )
        native_root = self.state / "continuations" / marker.task_id
        if self._capacity_ledger_exists(native_root):
            native = FileContinuationStore(native_root, task_id=marker.task_id)
            for prefix in ("capture-start", "capture-stop", "receipt", "admission"):
                path = native_root / f"{prefix}-{request.run_id}.json"
                if path.exists() or path.is_symlink():
                    raise ValueError("容量停止的原 Run 已有原生执行记录, 不能证明未调用")
            for path in native_root.iterdir():
                if not path.name.endswith(".json"):
                    continue
                if path.name.startswith("capture-start-"):
                    run_id = path.name.removeprefix("capture-start-").removesuffix(".json")
                    native_start = native.capture_start(run_id)
                    if self._conflicts_with_claim(
                        marker,
                        native_start.request,
                        native_start.claim.work_item.id,
                        native_start.claim.lease.id,
                        allow_later_claims=allow_later_claims,
                    ):
                        raise ValueError("容量停止的原 claim 已有原生执行记录, 不能证明未调用")
                elif path.name.startswith("capture-stop-"):
                    run_id = path.name.removeprefix("capture-stop-").removesuffix(".json")
                    native.capture_stop(run_id)
                    # Reading the matching start also verifies stop/start Run and SHA.
                    native_start = native.capture_start(run_id)
                    if self._conflicts_with_claim(
                        marker,
                        native_start.request,
                        native_start.claim.work_item.id,
                        native_start.claim.lease.id,
                        allow_later_claims=allow_later_claims,
                    ):
                        raise ValueError("容量停止的原 claim 已有原生结束记录, 不能证明未调用")
            if any(
                self._conflicts_with_claim(
                    marker,
                    receipt.request,
                    receipt.original_work_item_id,
                    receipt.claim_lease_id,
                    allow_later_claims=allow_later_claims,
                )
                for receipt in native.receipts_for_task(marker.task_id)
            ) or any(
                request.run_id == admission.interrupted_run_id
                or self._conflicts_with_claim(
                    marker,
                    admission.new_request,
                    admission.next_work_item_id,
                    admission.next_lease_id,
                    allow_later_claims=allow_later_claims,
                )
                for admission in native.admissions_for_task(marker.task_id)
            ):
                raise ValueError("容量停止的原 Run 已有原生恢复记录, 不能证明未调用")
        artifact_root = self.state.parent / "artifacts"
        if self._capacity_ledger_exists(artifact_root):
            for path in artifact_root.glob("art_*.json"):
                _reject_symlinks(path)
                if not path.is_file():
                    raise ValueError("容量停止调查的产出必须是 regular 普通文件")
                _read_regular(path, 8_000_000)
        for artifact in self.artifacts.list_for_task(marker.task_id):
            self._require_other_model_fact(
                marker,
                run_id=artifact.producer.run_id,
                context_id=artifact.context_manifest_id,
                role=artifact.producer.role,
                source_revision=artifact.source_revision,
                starts=starts,
                allow_later_claims=allow_later_claims,
            )

    def _require_other_model_fact(
        self,
        marker: ContextCapacityReceipt,
        *,
        run_id: str,
        context_id: str,
        role: AgentRole,
        source_revision: str,
        starts: tuple[DeliveryInvocationStart, ...],
        allow_later_claims: bool,
        attempt: int | None = None,
    ) -> None:
        assert marker.request is not None
        if run_id == marker.request.run_id or context_id == marker.context_manifest_id:
            raise ValueError("容量停止的原 Run 已有角色产出或提供方路由, 不能证明未调用")
        if role is not marker.role:
            return
        context_root = self.state.parent / "contexts"
        _reject_symlinks(context_root / f"{context_id}.json")
        context = FileContextStore(context_root, read_only=True).get(context_id)
        if (context.task_id, context.role, context.source_revision) != (
            marker.task_id,
            role,
            source_revision,
        ):
            raise ValueError("容量停止调查发现执行事实与完整 Context 身份不一致")
        if attempt is not None and context.attempt != attempt:
            raise ValueError("容量停止调查的路由与完整 Context 执行轮次不一致")
        claims = tuple(
            section for section in context.sections if section.name == "source:execution.claim"
        )
        if len(claims) != 1 or claims[0].truncated:
            raise ValueError("容量停止调查的产出或路由缺少完整原 claim")
        sealed = TypeAdapter(dict[str, JsonValue]).validate_json(claims[0].content)
        work_id, lease_id = sealed.get("work_item_id"), sealed.get("lease_id")
        if not isinstance(work_id, str) or not isinstance(lease_id, str):
            raise ValueError("容量停止调查的产出或路由 claim 身份不可验证")
        if lease_id == marker.lease_id or (
            work_id == marker.work_item_id and not allow_later_claims
        ):
            raise ValueError("容量停止的原 claim 已有产出或路由, 不能证明未调用")
        # A different Context/Run is not proof of a different execution.
        # Require its actual durable start before accepting any historical output.
        output_starts = tuple(start for start in starts if start.request.run_id == run_id)
        if len(output_starts) != 1:
            raise ValueError("容量停止调查的产出或路由缺少唯一完整调用记录")
        output_start = output_starts[0]
        actual_claim = self.queue.original_claim(lease_id)
        if any(
            sealed.get(field) != expected
            for field, expected in {
                "task_id": actual_claim.work_item.task_id,
                "work_item_id": actual_claim.work_item.id,
                "lease_id": actual_claim.lease.id,
                "assignment_id": actual_claim.assignment.id,
                "dispatch_sequence": actual_claim.work_item.dispatch_sequence,
                "role": actual_claim.work_item.role.value,
                "attempt": actual_claim.work_item.attempt,
                "checkpoint_sequence": actual_claim.work_item.checkpoint_sequence,
            }.items()
        ):
            raise ValueError("容量停止调查的产出或路由 Context 与真实 claim 不一致")
        if (
            (
                output_start.work_item_id,
                output_start.lease_id,
                output_start.request.context_manifest_id,
                output_start.request.task_id,
                output_start.request.role,
                output_start.request.attempt,
                output_start.request.source_revision,
            )
            != (
                work_id,
                lease_id,
                context_id,
                context.task_id,
                context.role,
                context.attempt,
                context.source_revision,
            )
            or claims[0].uri != "claim://" + lease_id
            or self._conflicts_with_claim(
                marker,
                output_start.request,
                work_id,
                lease_id,
                allow_later_claims=allow_later_claims,
            )
        ):
            raise ValueError("容量停止调查的产出或路由与原 claim 或完整调用不一致")

    def _conflicts_with_claim(
        self,
        marker: ContextCapacityReceipt,
        request: AgentRequest,
        work_item_id: str,
        lease_id: str,
        *,
        allow_later_claims: bool,
    ) -> bool:
        assert marker.request is not None
        if request.run_id == marker.request.run_id or lease_id == marker.lease_id:
            return True
        if work_item_id != marker.work_item_id:
            return False
        if not allow_later_claims:
            return True
        # Historical Coder receipts can precede a later, independently claimed
        # invocation. Only real queue provenance can distinguish it from an alias.
        claim = self.queue.original_claim(lease_id)
        return not (
            claim.work_item.id == work_item_id
            and claim.work_item.task_id == marker.task_id == request.task_id
            and claim.work_item.role is marker.role is request.role
            and claim.work_item.attempt == marker.attempt == request.attempt
            and claim.work_item.checkpoint_sequence == marker.checkpoint_sequence
            and claim.work_item.dispatch_sequence > marker.dispatch_sequence
            and claim.claimed_at > marker.observed_at
            and self.queue.step_for_invocation(
                work_item_id, request.execution_baseline_sha256
            ).boundary.source_revision
            == request.source_revision
        )

    @staticmethod
    def require_record_keys(
        records: KnowledgeRecordStore,
        namespace: str,
        keyed_records: tuple[tuple[str, DomainModel], ...],
    ) -> None:
        expected = {records._name(namespace, key) for key, _ in keyed_records}
        actual = {
            path.name
            for path in records.root.iterdir()
            if path.name.startswith(namespace + "-") and path.name.endswith(".json")
        }
        if len(expected) != len(keyed_records) or actual != expected:
            raise ValueError("容量停止调查发现执行记录键与完整事实不一致")

    @staticmethod
    def _capacity_ledger_exists(root: Path) -> bool:
        _reject_symlinks(root)
        if root.exists() and not root.is_dir():
            raise ValueError("容量停止调查的执行记录目录不可读取, 不能证明未调用")
        return root.is_dir()
