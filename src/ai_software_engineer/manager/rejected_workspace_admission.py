"""Current exact observation of a trusted pre-provider workspace refusal.

This module never publishes a native start/stop receipt or rewrites an outcome.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import JsonValue, TypeAdapter

from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, RouteAttemptOutcome
from ai_software_engineer.agents.models import AgentErrorCode, AgentRequest, AgentRunStatus
from ai_software_engineer.artifacts import ArtifactStore, FileArtifactStore, artifact_digest
from ai_software_engineer.artifacts.ordering import latest_accepted_artifact
from ai_software_engineer.context import ContextBundle, FileContextStore
from ai_software_engineer.context.execution_baseline import (
    ExecutionBaselineContext,
    PreservedWorktreeBaselineContext,
    execution_baseline_from_context,
    parse_execution_baseline_context,
)
from ai_software_engineer.domain.artifact import CoderProgressArtifact, ImplementationReportArtifact
from ai_software_engineer.domain.delivery_resolution import RejectedWorkspaceAdmissionEvidence
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.enums import AgentRole, TaskStatus
from ai_software_engineer.domain.task import Task, task_matches_dispatch
from ai_software_engineer.evidence.models import RunEvidenceManifest, validate_evidence_record
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.knowledge.claim_identity import claim_identity_sha256
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_admission import require_preserved_progress_capture
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.capacity_input_reader import (
    CapacityInputReader,
    UninvokedClaimBoundary,
)
from ai_software_engineer.manager.execution_baseline import StoredCoderExecutionInputResolver
from ai_software_engineer.manager.workspace_admission_contract import (
    WorkspaceAdmissionAdapterContractStore,
    require_supported_adapter_contract,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.orchestration.retry import _active_progress
from ai_software_engineer.team_workspace import _read_regular, _reject_symlinks
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem

_REFUSAL_MESSAGE = "恢复工作区准入校验未通过。未调用模型。现场已保留。请查看平台恢复检查结果。"


class RejectedWorkspaceAdmissionQueue(Protocol):
    def original_claim(self, lease_id: str) -> QueueClaim: ...
    def claims_for_work_item(self, work_item_id: str) -> tuple[QueueClaim, ...]: ...
    def accepted(self, task_id: str) -> tuple[AcceptedRoleArtifact, ...]: ...
    def step_for_invocation(
        self, work_item_id: str, baseline_sha256: str | None
    ) -> QueuedRoleStep: ...


def rejected_workspace_admission_evidence(
    *,
    task: Task,
    item: QueuedWorkItem,
    step: QueuedRoleStep,
    scope: EngineeringScope,
    requirement_id: str,
    state: Path,
    route_root: Path,
    queue: RejectedWorkspaceAdmissionQueue,
    artifacts: ArtifactStore,
    git: GitWorktreeManager,
) -> RejectedWorkspaceAdmissionEvidence:
    """Reopen positive trusted adapter facts; absence alone grants no authority."""
    records = KnowledgeRecordStore(state / "invocations", read_only=True)
    start = records.get("invocation-starts", item.id, DeliveryInvocationStart)
    outcome = records.get("invocation-outcomes", item.id, DeliveryInvocationOutcome)
    start.validate_integrity()
    outcome.validate_integrity()
    request, result = start.request, outcome.result
    error = result.error
    if (
        task.status is not TaskStatus.IMPLEMENTING
        or item.role is not AgentRole.CODER
        or request.role is not AgentRole.CODER
        or task.attempts != item.attempt
        or outcome.start != start
        or outcome.service_pause is not None
        or result.status is not AgentRunStatus.FAILED
        or error is None
        or error.code is not AgentErrorCode.WORK_INTERRUPTED
        or error.transient
        or error.message != _REFUSAL_MESSAGE
        or result.artifact is not None
        or result.usage is not None
        or scope.repository_root != task.repository
        or (task.engineering_policy is not None and task.engineering_policy.scope != scope)
        or item.repository_scopes != (task.repository,)
        or item.repository_id != scope.repository_id
        or (
            start.work_item_id,
            start.checkpoint_sequence,
            request.task_id,
            request.attempt,
            request.source_revision,
        )
        != (
            item.id,
            item.checkpoint_sequence,
            task.id,
            item.attempt,
            step.boundary.source_revision,
        )
        or (
            step.boundary.task_id,
            step.boundary.role,
            step.boundary.attempt,
            step.boundary.checkpoint_sequence,
        )
        != (task.id, item.role, item.attempt, item.checkpoint_sequence)
        or queue.step_for_invocation(item.id, request.execution_baseline_sha256).boundary
        != step.boundary
    ):
        raise ValueError("原结果不属于完整可信的 Coder 工作区准入拒绝")
    claim = queue.original_claim(start.lease_id)
    claims = queue.claims_for_work_item(item.id)
    if (
        len(claims) != 1
        or claims[0] != claim
        or claim.lease.id != start.lease_id
        or (
            claim.work_item.id,
            claim.work_item.task_id,
            claim.work_item.role,
            claim.work_item.attempt,
            claim.work_item.checkpoint_sequence,
            claim.work_item.dispatch_sequence,
            claim.work_item.repository_id,
            claim.work_item.repository_scopes,
        )
        != (
            item.id,
            task.id,
            item.role,
            item.attempt,
            item.checkpoint_sequence,
            item.dispatch_sequence,
            item.repository_id,
            (task.repository,),
        )
        or claim.claimed_at > start.started_at
    ):
        raise ValueError("原准入拒绝没有唯一精确的真实 Worker claim")
    routes = FileModelRouteAttemptStore(route_root, read_only=True).list_for_run(request.run_id)
    if len(routes) != 1:
        raise ValueError("原准入拒绝没有唯一的已封存模型路由")
    route = routes[0]
    route.validate_integrity()
    if (
        route.route_index != 1
        or route.route_kind != "codex_cli"
        or route.provider != "codex"
        or route.outcome is not RouteAttemptOutcome.FAILED
        or route.result != result
        or route.request_sha256 != digest(request.to_wire())
        or route.started_at < start.started_at
    ):
        raise ValueError("原准入拒绝的实际路由和完整请求不一致")
    contract = WorkspaceAdmissionAdapterContractStore(
        state, task_id=task.id, read_only=True
    ).for_run(request.run_id)
    if contract is None:
        raise ValueError("原准入拒绝缺少当前可信维护主体的精确部署契约声明")
    contract.validate_integrity()
    require_supported_adapter_contract(contract)
    declaration = contract.declaration
    if (
        declaration.scope != scope
        or declaration.requirement_id != requirement_id
        or declaration.task_id != task.id
        or declaration.work_item_id != item.id
        or declaration.lease_id != claim.lease.id
        or declaration.claim_sha256 != claim_identity_sha256(claim)
        or declaration.run_id != request.run_id
        or declaration.source_revision != request.source_revision
        or declaration.invocation_start_sha256 != start.start_sha256
        or declaration.invocation_outcome_sha256 != outcome.outcome_sha256
        or declaration.route_attempt_sha256 != route.attempt_sha256
        or declaration.deployment_observed_at > start.started_at
        or contract.submitted_at < route.completed_at
    ):
        raise ValueError("维护主体的当前声明没有绑定原调用的精确部署和不可变事实")
    inputs = StoredCoderExecutionInputResolver(
        FileExecutionBaselineStore(state / "execution-baselines" / task.id, read_only=True)
    )
    baseline_source = inputs.current(task, implementation=None, progress=None)
    accepted = artifacts.list_for_task(task.id)
    implementation = latest_accepted_artifact(
        accepted,
        ImplementationReportArtifact,
        excluded_artifact_ids=baseline_source.superseded_artifact_ids,
    )
    progress = _active_progress(
        latest_accepted_artifact(
            accepted,
            CoderProgressArtifact,
            excluded_artifact_ids=baseline_source.superseded_artifact_ids,
        ),
        implementation,
        accepted,
    )
    source = inputs.current(task, implementation=implementation, progress=progress)
    binding = source.baseline
    if (
        binding is None
        or binding.scope != scope
        or source.active_progress is None
        or inputs.store is None
    ):
        raise ValueError("原准入拒绝缺少当前可信保留草稿或已接纳进度")
    plan = inputs.store.plan(binding.plan_sha256)
    if plan.facts.denied_paths != (task.constraints.denied_paths if task.constraints else ()):
        raise ValueError("原准入拒绝改变了冻结的禁止路径")
    _require_context(state, task, request, claim, inputs)
    publications = queue.accepted(task.id)
    if any(value.work_item_id == item.id for value in publications) or not any(
        value.receipt.artifact_id == source.active_progress.artifact_id
        and value.receipt.sha256 == artifact_digest(source.active_progress)
        and value.run_id == source.active_progress.producer.run_id
        and value.context_manifest_id == source.active_progress.context_manifest_id
        and value.source_revision == source.active_progress.source_revision
        for value in publications
    ):
        raise ValueError("原准入拒绝的进度没有精确接纳或原调用已有其他产出")
    worktree = git.recover(
        WorktreeSpec(
            task_id=task.id,
            role=AgentRole.CODER,
            attempt=1,
            source_revision=request.source_revision,
        )
    )
    if str(worktree.path) != binding.worktree_path:
        raise ValueError("原准入拒绝不在精确的原隔离工作区")
    retained = inputs.retained_source_paths(
        task, workspace_root=worktree.path, permissions=request.permissions
    )
    capture = git.capture_mutations(
        worktree,
        request.permissions,
        denied_paths=plan.facts.denied_paths,
        retained_source_paths=retained,
    )
    progress_paths = tuple(
        sorted(value.path for value in source.active_progress.content.changed_files)
    )
    if not set(progress_paths) < set(capture.changed_paths):
        raise ValueError("原拒绝不是旧进度声明与完整批准草稿的精确路径差异")
    require_preserved_progress_capture(
        request=request,
        source=source,
        plan=plan,
        capture=capture,
        git=git,
        retained_source_paths=retained,
    )
    _require_no_contradictions(
        state=state,
        route_root=route_root,
        task=task,
        item=item,
        claim=claim,
        start=start,
        outcome=outcome,
        queue=queue,
        artifacts=artifacts,
    )
    context = FileContextStore(state.parent / "contexts", read_only=True).get(
        request.context_manifest_id
    )
    evidence = RejectedWorkspaceAdmissionEvidence(
        scope=scope,
        requirement_id=requirement_id,
        task_id=task.id,
        work_item_id=item.id,
        role=AgentRole.CODER,
        checkpoint_sequence=item.checkpoint_sequence,
        attempt=item.attempt,
        dispatch_sequence=item.dispatch_sequence,
        lease_id=claim.lease.id,
        claim_sha256=claim_identity_sha256(claim),
        run_id=request.run_id,
        context_manifest_id=request.context_manifest_id,
        source_revision=request.source_revision,
        invocation_start_sha256=start.start_sha256,
        invocation_outcome_sha256=outcome.outcome_sha256,
        route_attempt_sha256=route.attempt_sha256,
        context_sha256=digest(context.to_wire()),
        baseline_binding_sha256=binding.binding_sha256,
        baseline_plan_sha256=plan.plan_sha256,
        progress_artifact_id=source.active_progress.artifact_id,
        progress_sha256=artifact_digest(source.active_progress),
        workspace_inventory_sha256=capture_mutation_inventory(worktree.path).sha256,
        workspace_capture_sha256=capture.capture_sha256,
        adapter_contract_sha256=contract.contract_sha256,
        observation_sha256="0" * 64,
    )
    evidence = evidence.model_copy(update={"observation_sha256": evidence.recompute_sha256()})
    evidence.validate_integrity()
    return evidence


def _section(context: ContextBundle, name: str) -> str:
    sections = tuple(value for value in context.sections if value.name == name)
    if (
        len(sections) != 1
        or sections[0].truncated
        or hashlib.sha256(sections[0].content.encode()).hexdigest() != sections[0].sha256
    ):
        raise ValueError("原 Context 缺少完整唯一的 " + name)
    return sections[0].content


def _require_context(
    state: Path,
    task: Task,
    request: AgentRequest,
    claim: QueueClaim,
    inputs: StoredCoderExecutionInputResolver,
) -> None:
    root = state.parent / "contexts"
    _reject_symlinks(root / f"{request.context_manifest_id}.json")
    context = FileContextStore(root, read_only=True).get(request.context_manifest_id)
    original = Task.model_validate_json(_section(context, "task"))
    if not task_matches_dispatch(original, task) or (original.status, original.attempts) != (
        TaskStatus.IMPLEMENTING,
        request.attempt,
    ):
        raise ValueError("原 Context 不匹配冻结 Task 和执行身份")
    policy = TypeAdapter(dict[str, JsonValue]).validate_json(_section(context, "policy"))
    if policy != {
        **request.permissions.to_wire(),
        "denied_paths": list(task.constraints.denied_paths if task.constraints else ()),
    }:
        raise ValueError("原 Context 不匹配完整冻结执行权限")
    sealed = TypeAdapter(dict[str, JsonValue]).validate_json(
        _section(context, "source:execution.claim")
    )
    if next(
        section for section in context.sections if section.name == "source:execution.claim"
    ).uri != "claim://" + claim.lease.id or any(
        sealed.get(field) != expected
        for field, expected in {
            "task_id": task.id,
            "work_item_id": claim.work_item.id,
            "lease_id": claim.lease.id,
            "assignment_id": claim.assignment.id,
            "dispatch_sequence": claim.work_item.dispatch_sequence,
            "role": request.role.value,
            "attempt": request.attempt,
            "checkpoint_sequence": claim.work_item.checkpoint_sequence,
        }.items()
    ):
        raise ValueError("原 Context 不匹配真实 claim")
    binding = execution_baseline_from_context(context, request, original, verifier=inputs)
    if binding is None:
        raise ValueError("原 Context 没有可信执行基线")
    complete = (
        ExecutionBaselineContext.from_required_context(
            binding, inputs.store.required_context(binding)
        )
        if inputs.store is not None
        else None
    )
    value = parse_execution_baseline_context(_section(context, "execution.baseline"))
    if complete is None or value not in (
        complete,
        PreservedWorktreeBaselineContext.from_complete(complete),
    ):
        raise ValueError("原 Context 的基线正文或投影与完整可信计划不一致")


def _require_no_contradictions(
    *,
    state: Path,
    route_root: Path,
    task: Task,
    item: QueuedWorkItem,
    claim: QueueClaim,
    start: DeliveryInvocationStart,
    outcome: DeliveryInvocationOutcome,
    queue: RejectedWorkspaceAdmissionQueue,
    artifacts: ArtifactStore,
) -> None:
    request = start.request
    marker = UninvokedClaimBoundary(
        task_id=task.id,
        work_item_id=item.id,
        lease_id=claim.lease.id,
        role=item.role,
        attempt=item.attempt,
        checkpoint_sequence=item.checkpoint_sequence,
        dispatch_sequence=item.dispatch_sequence,
        observed_at=datetime.now(UTC),
        run_id=request.run_id,
        context_manifest_id=request.context_manifest_id,
    )
    reader = CapacityInputReader(
        state=state,
        queue=queue,
        artifacts=artifacts,
        route_root=route_root,
        baselines=None,
    )
    records = KnowledgeRecordStore(state / "invocations", read_only=True)
    starts = records.list("invocation-starts", DeliveryInvocationStart)
    outcomes = records.list("invocation-outcomes", DeliveryInvocationOutcome)
    CapacityInputReader.require_record_keys(
        records, "invocation-starts", tuple((v.work_item_id, v) for v in starts)
    )
    CapacityInputReader.require_record_keys(
        records, "invocation-outcomes", tuple((v.start.work_item_id, v) for v in outcomes)
    )
    for value in starts:
        value.validate_integrity()
        if value != start and reader._conflicts_with_claim(
            marker, value.request, value.work_item_id, value.lease_id, allow_later_claims=False
        ):
            raise ValueError("原准入拒绝出现其他调用开始事实")
    for completed in outcomes:
        completed.validate_integrity()
        if completed.start not in starts:
            raise ValueError("原准入拒绝出现没有完整开始记录的结果")
        if completed.start == start and completed != outcome:
            raise ValueError("原准入拒绝出现不同的调用结果")
    if not CapacityInputReader._capacity_ledger_exists(route_root):
        raise ValueError("原准入拒绝的完整路由目录缺失")
    routes = FileModelRouteAttemptStore(route_root, read_only=True)
    for directory in route_root.iterdir():
        if not CapacityInputReader._capacity_ledger_exists(directory):
            raise ValueError("原准入拒绝调查的路由目录不可读取")
        for path in directory.glob("*.json"):
            _reject_symlinks(path)
            _read_regular(path, 8_000_000)
        for route in routes.list_for_run(directory.name):
            if route.task_id != task.id or route.run_id == request.run_id:
                continue
            reader._require_other_model_fact(
                marker,
                run_id=route.run_id,
                context_id=route.result.context_manifest_id,
                role=route.role,
                source_revision=route.result.source_revision,
                starts=starts,
                attempt=route.result.attempt,
                allow_later_claims=False,
            )
    native_root = state / "continuations" / task.id
    if CapacityInputReader._capacity_ledger_exists(native_root):
        native = FileContinuationStore(native_root, task_id=task.id)
        for path in native_root.iterdir():
            if path.name == "workspace-admission-contracts":
                WorkspaceAdmissionAdapterContractStore(
                    state, task_id=task.id, read_only=True
                ).list_for_task()
                continue
            _reject_symlinks(path)
            if not path.name.endswith(".json") or not (
                path.name in {"receipt.json", "admission.json"}
                or path.name.startswith(
                    ("capture-start-", "capture-stop-", "receipt-", "admission-")
                )
            ):
                raise ValueError("原准入拒绝调查发现未知的原生执行记录")
            _read_regular(path, 8_000_000)
            for prefix in ("capture-start-", "capture-stop-"):
                if not path.name.startswith(prefix):
                    continue
                run_id = path.name.removeprefix(prefix).removesuffix(".json")
                captured = native.capture_start(run_id)
                if prefix == "capture-stop-":
                    native.capture_stop(run_id)
                if reader._conflicts_with_claim(
                    marker,
                    captured.request,
                    captured.claim.work_item.id,
                    captured.claim.lease.id,
                    allow_later_claims=False,
                ):
                    raise ValueError("原准入拒绝出现原生执行开始或结束事实")
        for receipt in native.receipts_for_task(task.id):
            if reader._conflicts_with_claim(
                marker,
                receipt.request,
                receipt.original_work_item_id,
                receipt.claim_lease_id,
                allow_later_claims=False,
            ):
                raise ValueError("原准入拒绝出现原生执行恢复事实")
        for admission in native.admissions_for_task(task.id):
            if admission.interrupted_run_id == request.run_id or reader._conflicts_with_claim(
                marker,
                admission.new_request,
                admission.next_work_item_id,
                admission.next_lease_id,
                allow_later_claims=False,
            ):
                raise ValueError("原准入拒绝出现原生执行准入事实")
    artifact_root = state.parent / "artifacts"
    if not CapacityInputReader._capacity_ledger_exists(artifact_root):
        raise ValueError("原准入拒绝缺少完整原始产出目录")
    for path in artifact_root.glob("*.json"):
        _reject_symlinks(path)
        if not path.name.startswith("art_"):
            raise ValueError("原准入拒绝调查发现未知的原始产出文件")
        _read_regular(path, 8_000_000)
    raw_artifacts = FileArtifactStore(artifact_root, read_only=True).list_for_task(task.id)
    for artifact in raw_artifacts:
        reader._require_other_model_fact(
            marker,
            run_id=artifact.producer.run_id,
            context_id=artifact.context_manifest_id,
            role=artifact.producer.role,
            source_revision=artifact.source_revision,
            starts=starts,
            allow_later_claims=False,
            outcomes=outcomes,
            candidate=artifact if isinstance(artifact, ImplementationReportArtifact) else None,
        )
    _require_no_execution_evidence(state.parent, request)


def _require_no_execution_evidence(root: Path, request: AgentRequest) -> None:
    evidence_root, runs_root = root / "evidence", root / "runs"
    if CapacityInputReader._capacity_ledger_exists(evidence_root):
        for path in evidence_root.glob("*.json"):
            _reject_symlinks(path)
            record = validate_evidence_record(
                TypeAdapter(dict[str, JsonValue]).validate_json(_read_regular(path, 8_000_000))
            )
            record.validate_integrity()
            if path.stem != record.evidence_id or (
                record.identity.run_id == request.run_id
                or record.identity.context_manifest_id == request.context_manifest_id
            ):
                raise ValueError("原准入拒绝出现工具、命令、diff、测试或usage执行事实")
    if CapacityInputReader._capacity_ledger_exists(runs_root):
        for path in runs_root.glob("*.json"):
            _reject_symlinks(path)
            manifest = RunEvidenceManifest.model_validate_json(_read_regular(path, 8_000_000))
            manifest.validate_integrity()
            if path.stem != manifest.identity.run_id or (
                manifest.identity.run_id == request.run_id
                or manifest.identity.context_manifest_id == request.context_manifest_id
            ):
                raise ValueError("原准入拒绝出现执行evidence清单")
