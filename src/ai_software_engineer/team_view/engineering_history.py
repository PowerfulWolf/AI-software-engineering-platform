"""Read-only, complete engineering journals for the current native Task."""

import hashlib
import os
import stat
from pathlib import Path

from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
    DeliveryWaitHandling,
    DeliveryWaitInvestigation,
    EngineeringDispositionRecord,
)
from ai_software_engineer.domain.engineering_authority import EngineeringAdmission, EngineeringScope
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode, BaselinePurpose
from ai_software_engineer.domain.model import JsonValue
from ai_software_engineer.domain.task import Task
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_models import (
    BaselineContinueAuthorization,
    BaselineOperationStart,
    BaselineOperatorAuthorization,
)
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.delivery_preflight import DeliveryPreflightReceipt
from ai_software_engineer.manager.engineering_authority import EngineeringAuthority
from ai_software_engineer.manager.native_verification_store import NativeRoleVerificationBinding
from ai_software_engineer.manager.verifier_preparation import (
    VerifierPreparationCheckpoint,
    VerifierPreparationIntent,
)
from ai_software_engineer.projection.models import ProjectionEventKind, TimelineEntry
from ai_software_engineer.recovery.verification_records import VerificationExecutionRecord
from ai_software_engineer.redaction import redact_text


def _read(path: Path) -> bytes:
    if any(value.is_symlink() for value in (path, *path.parents)):
        raise ValueError("engineering history contains a symlink")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("engineering history requires a regular record")
        value = stream.read(8_000_001)
    if len(value) > 8_000_000:
        raise ValueError("engineering record exceeds its read bound")
    return value


def _safe(value: JsonValue) -> JsonValue:
    """Sanitize only the projection; immutable records and their hashes stay intact."""
    if isinstance(value, str):
        return redact_text(value).text
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, dict):
        return {redact_text(key).text: _safe(item) for key, item in value.items()}
    return value


def _decision_matches_proof(decision: DeliveryResolution, proof: DeliveryWaitInvestigation) -> None:
    if (
        decision.task_id,
        decision.work_item_id,
        decision.expected_disposition_sha256,
        decision.expected_task_intent_sha256,
        decision.expected_source_revision,
        decision.expected_checkpoint_sequence,
        decision.task_revision,
        decision.task_snapshot_sha256,
        decision.step_sha256,
        decision.proof_sha256,
    ) != (
        proof.task_id,
        proof.work_item_id,
        proof.disposition_sha256,
        proof.task_intent_sha256,
        proof.source_revision,
        proof.checkpoint_sequence,
        proof.task_revision,
        proof.task_snapshot_sha256,
        proof.step_sha256,
        proof.proof_sha256,
    ) or (
        proof.missing
        or decision.resolution_kind not in proof.permitted_resolutions
        or decision.submitted_at < proof.inspected_at
        or (
            decision.resolution_kind is DeliveryResolutionKind.REPLAY_RECORDED_RESULT
            and decision.original_authority != proof.original_authority
        )
        or (
            decision.resolution_kind is DeliveryResolutionKind.REVERIFY_CANDIDATE
            and decision.verification_retry != proof.verification_retry
        )
        or (
            decision.resolution_kind is DeliveryResolutionKind.RETRY_FROM_CHECKPOINT
            and decision.retry_cause != proof.retry_cause
        )
        or decision.verifier_preparation != proof.verifier_preparation
    ):
        raise ValueError("engineering decision has another exact investigation")


def engineering_history(
    sidecar: Path,
    task: Task,
    scope: EngineeringScope,
    requirement_id: str,
) -> tuple[TimelineEntry, ...]:
    entries: list[TimelineEntry] = []
    if scope.repository_root != task.repository:
        raise ValueError("engineering history is outside the registered Task repository")
    intent = task_intent_sha256(task)
    waits = sidecar / "state" / "delivery-waits"
    if waits.exists():
        records = KnowledgeRecordStore(waits, read_only=True)
        for proof in records.list("wait-investigations", DeliveryWaitInvestigation):
            proof.validate_integrity()
            if (
                records.get("wait-investigations", proof.proof_sha256, DeliveryWaitInvestigation)
                != proof
            ):
                raise ValueError("engineering investigation changed its immutable store key")
            if proof.task_id != task.id:
                continue
            if proof.task_intent_sha256 != intent:
                raise ValueError("engineering investigation changed approved Task intent")
            entries.append(
                TimelineEntry(
                    id="investigation_" + proof.proof_sha256,
                    kind=ProjectionEventKind.EVIDENCE,
                    occurred_at=proof.inspected_at,
                    task_id=task.id,
                    run_id=proof.original_run_id,
                    role=proof.disposition.facts.role,
                    summary=proof.next_action,
                    source_uri=(
                        waits / records._name("wait-investigations", proof.proof_sha256)
                    ).as_uri(),
                    source_sha256=proof.proof_sha256,
                    details={
                        "kind": proof.kind,
                        "responsibility": "ENGINEERING",
                        "missing": [item.value for item in proof.missing],
                        "permitted_resolutions": [
                            item.value for item in proof.permitted_resolutions
                        ],
                        "work_item_id": proof.work_item_id,
                        "source_revision": proof.source_revision,
                    },
                )
            )
        for decision in records.list("wait-resolutions", DeliveryResolution):
            decision.validate_integrity()
            if (
                records.get(
                    "wait-resolutions",
                    decision.work_item_id + ":" + decision.expected_disposition_sha256,
                    DeliveryResolution,
                )
                != decision
            ):
                raise ValueError("engineering resolution changed its immutable store key")
            if decision.task_id != task.id:
                continue
            if decision.expected_task_intent_sha256 != intent:
                raise ValueError("engineering resolution changed approved Task intent")
            proof = records.get(
                "wait-investigations", decision.proof_sha256, DeliveryWaitInvestigation
            )
            proof.validate_integrity()
            _decision_matches_proof(decision, proof)
            if decision.engineering_admission is not None:
                EngineeringAuthority.validate(task=task, record=decision.engineering_admission)
                if decision.engineering_admission.policy.scope != scope:
                    raise ValueError("engineering resolution policy changed the Project scope")
            entries.append(
                TimelineEntry(
                    id="resolution_" + decision.resolution_sha256,
                    kind=ProjectionEventKind.EVIDENCE,
                    occurred_at=decision.submitted_at,
                    task_id=task.id,
                    summary=(
                        "平台按冻结工程策略记录了自动处理。执行结果以之后的角色记录为准。"
                        if decision.engineering_admission is not None
                        else "工程负责人记录了精确处置决定。执行结果以之后的角色记录为准。"
                    ),
                    source_uri=(
                        waits
                        / records._name(
                            "wait-resolutions",
                            decision.work_item_id + ":" + decision.expected_disposition_sha256,
                        )
                    ).as_uri(),
                    source_sha256=decision.resolution_sha256,
                    details={
                        "kind": decision.kind,
                        "authorization_source": decision.authorization_source,
                        **(
                            {"operator_id": decision.operator_principal.operator_id}
                            if decision.operator_principal is not None
                            else {}
                        ),
                        **(
                            {"admission_sha256": decision.engineering_admission.admission_sha256}
                            if decision.engineering_admission is not None
                            else {}
                        ),
                        "resolution_kind": decision.resolution_kind.value,
                        "work_item_id": decision.work_item_id,
                        "proof_sha256": decision.proof_sha256,
                    },
                )
            )
        for handling in records.list("wait-handlings", DeliveryWaitHandling):
            handling.validate_integrity()
            if records.get("wait-handlings", handling.record_key, DeliveryWaitHandling) != handling:
                raise ValueError("platform handling changed its immutable store key")
            if handling.task_id != task.id:
                continue
            if handling.task_intent_sha256 != intent:
                raise ValueError("platform handling changed approved Task intent")
            proof = records.get(
                "wait-investigations",
                handling.investigation.proof_sha256,
                DeliveryWaitInvestigation,
            )
            if proof != handling.investigation:
                raise ValueError("platform handling changed its sealed investigation")
            proof.validate_integrity()
            if handling.resolution is not None:
                decision = handling.resolution
                decision.validate_integrity()
                _decision_matches_proof(decision, proof)
                if (
                    records.get(
                        "wait-resolutions",
                        decision.work_item_id + ":" + decision.expected_disposition_sha256,
                        DeliveryResolution,
                    )
                    != decision
                ):
                    raise ValueError("platform handling changed its sealed resolution")
                if decision.engineering_admission is not None:
                    EngineeringAuthority.validate(task=task, record=decision.engineering_admission)
                    if decision.engineering_admission.policy.scope != scope:
                        raise ValueError("platform handling policy changed the Project scope")
            entries.append(
                TimelineEntry(
                    id="handling_" + handling.handling_sha256,
                    kind=ProjectionEventKind.EVIDENCE,
                    occurred_at=handling.handled_at,
                    task_id=task.id,
                    run_id=proof.original_run_id,
                    role=proof.disposition.facts.role,
                    summary=handling.summary,
                    source_uri=(
                        waits / records._name("wait-handlings", handling.record_key)
                    ).as_uri(),
                    source_sha256=handling.handling_sha256,
                    details={
                        "kind": handling.kind,
                        "status": handling.status,
                        "user_action": handling.user_action,
                        "recheck_when": handling.recheck_when,
                        "manual_resolution_allowed": handling.manual_resolution_allowed,
                        "collection_failed": handling.collection_failed,
                        "proof_sha256": proof.proof_sha256,
                        "work_item_id": handling.work_item_id,
                    },
                )
            )
    preflight = sidecar / "state" / "delivery-preflight"
    if preflight.exists():
        records = KnowledgeRecordStore(preflight, read_only=True)
        for receipt in records.list("preflight-receipts", DeliveryPreflightReceipt):
            receipt.validate_integrity()
            if (
                records.get("preflight-receipts", receipt.receipt_sha256, DeliveryPreflightReceipt)
                != receipt
            ):
                raise ValueError("preflight history changed its immutable store key")
            if receipt.task_id != task.id:
                continue
            if (
                receipt.scope.team_id,
                receipt.scope.project_id,
                receipt.scope.repository_id,
                receipt.scope.requirement_id,
            ) != (scope.team_id, scope.project_id, scope.repository_id, requirement_id):
                raise ValueError("preflight history is outside the current Requirement")
            entries.append(
                TimelineEntry(
                    id="preflight_" + receipt.receipt_sha256,
                    kind=ProjectionEventKind.EVIDENCE,
                    occurred_at=receipt.checked_at,
                    task_id=task.id,
                    summary="实施前验证前提检查通过。"
                    if receipt.status == "READY"
                    else "实施前验证前提尚未满足, 等待工程处理。",
                    source_uri=(
                        preflight / records._name("preflight-receipts", receipt.receipt_sha256)
                    ).as_uri(),
                    source_sha256=receipt.receipt_sha256,
                    details={
                        "kind": receipt.kind,
                        "status": receipt.status,
                        "source_revision": receipt.source_revision,
                        "observations": [item.to_wire() for item in receipt.observations],
                    },
                )
            )
        for preparation_intent in records.list(
            "verifier-preparation-intents", VerifierPreparationIntent
        ):
            preparation_intent.validate_integrity()
            if preparation_intent.task_id != task.id:
                continue
            key = (
                f"{preparation_intent.work_item_id}:{preparation_intent.checkpoint_sequence}:"
                f"{preparation_intent.dispatch_sequence}"
            )
            if (
                records.get("verifier-preparation-intents", key, VerifierPreparationIntent)
                != preparation_intent
            ):
                raise ValueError("preparation intent history changed its immutable store key")
            entries.append(
                TimelineEntry(
                    id="preparation_intent_" + preparation_intent.intent_sha256,
                    kind=ProjectionEventKind.EVIDENCE,
                    occurred_at=preparation_intent.started_at,
                    task_id=task.id,
                    run_id=preparation_intent.request.run_id,
                    role=preparation_intent.request.role,
                    summary="独立角色验证准备的原执行身份已封存, 命令执行与模型调用须另有记录。",
                    source_uri=(
                        preflight / records._name("verifier-preparation-intents", key)
                    ).as_uri(),
                    source_sha256=preparation_intent.intent_sha256,
                    details={
                        "kind": preparation_intent.kind,
                        "work_item_id": preparation_intent.work_item_id,
                        "lease_id": preparation_intent.lease_id,
                        "dispatch_sequence": preparation_intent.dispatch_sequence,
                        "source_revision": preparation_intent.request.source_revision,
                    },
                )
            )
        for marker in records.list("verifier-preparations", VerifierPreparationCheckpoint):
            marker.validate_integrity()
            if (
                records.get(
                    "verifier-preparations", marker.checkpoint_sha256, VerifierPreparationCheckpoint
                )
                != marker
            ):
                raise ValueError("preparation history changed its immutable store key")
            if marker.task_id != task.id:
                continue
            preparation_intent = records.get(
                "verifier-preparation-intents",
                f"{marker.work_item_id}:{marker.checkpoint_sequence}:{marker.dispatch_sequence}",
                VerifierPreparationIntent,
            )
            preparation_intent.validate_integrity()
            if (
                (
                    preparation_intent.work_item_id,
                    preparation_intent.lease_id,
                    preparation_intent.task_id,
                    preparation_intent.task_snapshot_sha256,
                    preparation_intent.checkpoint_sequence,
                    preparation_intent.dispatch_sequence,
                    preparation_intent.request,
                    preparation_intent.request_sha256,
                    preparation_intent.intent_sha256,
                )
                != (
                    marker.work_item_id,
                    marker.lease_id,
                    marker.task_id,
                    marker.task_snapshot_sha256,
                    marker.checkpoint_sequence,
                    marker.dispatch_sequence,
                    marker.request,
                    marker.request_sha256,
                    marker.intent_sha256,
                )
                or marker.dispatch_sequence > marker.wait_dispatch_sequence
                or preparation_intent.started_at > marker.checked_at
            ):
                raise ValueError("preparation history has no exact original claimed intent")
            entries.append(
                TimelineEntry(
                    id="preparation_" + marker.checkpoint_sha256,
                    kind=ProjectionEventKind.EVIDENCE,
                    occurred_at=marker.checked_at,
                    task_id=task.id,
                    run_id=marker.run_id,
                    role=marker.role,
                    summary="独立角色模型调用前的验证准备已完成。"
                    if marker.result == "READY"
                    else "独立角色验证准备暂停, 等待工程核验实际执行记录与当前前提。",
                    source_uri=(
                        preflight
                        / records._name(
                            "verifier-preparations",
                            marker.checkpoint_sha256,
                        )
                    ).as_uri(),
                    source_sha256=marker.checkpoint_sha256,
                    details={
                        "kind": marker.kind,
                        "result": marker.result,
                        "native_execution_state": marker.observation.native_execution_state,
                        "failure_reason": marker.failure_reason.value
                        if marker.failure_reason
                        else None,
                        "work_item_id": marker.work_item_id,
                        "intent_sha256": marker.intent_sha256,
                        "dispatch_sequence": marker.dispatch_sequence,
                        "wait_dispatch_sequence": marker.wait_dispatch_sequence,
                        "source_revision": marker.source_revision,
                    },
                )
            )
    baselines = sidecar / "state" / "execution-baselines" / task.id
    if baselines.exists():
        store = FileExecutionBaselineStore(baselines, read_only=True)
        for start in store.records.list("baseline-starts", BaselineOperationStart):
            start.validate_integrity()
            baseline_plan = start.plan
            if baseline_plan.facts.task.id != task.id:
                continue
            if (
                baseline_plan.facts.scope != scope
                or task_intent_sha256(baseline_plan.facts.task) != intent
            ):
                raise ValueError("baseline start history changed its approved Task or scope")
            if store.plan(baseline_plan.plan_sha256) != baseline_plan:
                raise ValueError("baseline start history has another immutable plan")
            authority: EngineeringAdmission | BaselineOperatorAuthorization
            if start.authority_source == "engineering_operator_decision":
                authority = store.records.get(
                    "baseline-authorities",
                    baseline_plan.plan_sha256,
                    BaselineOperatorAuthorization,
                )
                operator_id: str | None = authority.principal.operator_id
                occurred_at = authority.submitted_at
                authority_sha256 = authority.authorization_sha256
            else:
                authority = store.records.get(
                    "baseline-authorities",
                    baseline_plan.plan_sha256,
                    EngineeringAdmission,
                )
                if authority.policy.scope != scope:
                    raise ValueError("baseline start history changed its organization authority")
                operator_id = None
                occurred_at = authority.admitted_at
                authority_sha256 = authority.admission_sha256
            authority.validate_integrity()
            if (
                authority.task_id,
                authority.task_intent_sha256,
                authority.plan_sha256,
                authority.facts_sha256,
                authority_sha256,
            ) != (
                task.id,
                intent,
                baseline_plan.plan_sha256,
                baseline_plan.facts.facts_sha256,
                start.authority_sha256,
            ):
                raise ValueError("baseline start history has no exact engineering authority")
            if occurred_at > start.started_at:
                raise ValueError("baseline start precedes its exact engineering authority")
            entries.extend(
                (
                    TimelineEntry(
                        id="baseline_authority_" + authority_sha256,
                        kind=ProjectionEventKind.EVIDENCE,
                        occurred_at=occurred_at,
                        task_id=task.id,
                        summary=(
                            "工程人员确认原未知调用及全部派生工具已在同机同账户结束, "
                            "批准保留完整草稿继续; 平台本机检查不是历史停止记录。"
                            if baseline_plan.facts.legacy_containment is not None
                            and baseline_plan.facts.legacy_containment.method
                            == "operator_confirmed_local_stop"
                            else (
                                "工程人员确认原未知执行在本机且之后已整机重启, "
                                "批准保留完整草稿继续。"
                            )
                            if baseline_plan.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE
                            else "原分支执行基线更新的精确工程授权已记录。"
                        ),
                        source_uri=(
                            baselines
                            / store.records._name(
                                "baseline-authorities",
                                baseline_plan.plan_sha256,
                            )
                        ).as_uri(),
                        source_sha256=authority_sha256,
                        details={
                            "kind": authority.kind,
                            "authorization_source": start.authority_source,
                            "operator_id": operator_id,
                            "plan_sha256": baseline_plan.plan_sha256,
                        },
                    ),
                    TimelineEntry(
                        id="baseline_start_" + start.start_sha256,
                        kind=ProjectionEventKind.EVIDENCE,
                        occurred_at=start.started_at,
                        task_id=task.id,
                        summary=(
                            "原需求完整现场救援已开始, 原执行结果仍记为未知。"
                            if baseline_plan.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE
                            else "原需求分支执行基线更新已开始, 完成结果以后续绑定记录为准。"
                        ),
                        source_uri=(
                            baselines
                            / store.records._name(
                                "baseline-starts",
                                baseline_plan.plan_sha256,
                            )
                        ).as_uri(),
                        source_sha256=start.start_sha256,
                        details={
                            "kind": start.kind,
                            "authorization_source": start.authority_source,
                            "plan_sha256": baseline_plan.plan_sha256,
                            "input_mode": baseline_plan.input_mode.value,
                        },
                    ),
                )
            )
        for binding in store.bindings_for_task(task.id):
            binding.require_task(task)
            if binding.scope != scope:
                raise ValueError("baseline history belongs to another registered repository")
            entries.append(
                TimelineEntry(
                    id="baseline_" + binding.binding_sha256,
                    kind=ProjectionEventKind.EVIDENCE,
                    occurred_at=binding.completed_at,
                    task_id=task.id,
                    summary=(
                        "完整进度和工程决定已保存, 原需求保持暂停; 可先更新基线, 再明确继续。"
                        if binding.continuation_mode is BaselineContinuationMode.PAUSE
                        else (
                            "完整草稿已保留, 原未知执行历史不变, 下一轮使用原任务剩余工作额度继续。"
                        )
                        if binding.purpose is BaselinePurpose.LEGACY_WORKSPACE_RESCUE
                        else "已在原需求分支更新代码执行基线, 保留原候选和草稿记录。"
                    ),
                    source_uri=binding.retained_patch.uri,
                    source_sha256=binding.binding_sha256,
                    details={
                        "kind": binding.kind,
                        "purpose": binding.purpose.value,
                        "authorization_source": binding.authority_source,
                        "input_mode": binding.input_mode.value,
                        "branch_name": binding.branch_name,
                        "approved_base_ref": binding.approved_base_ref,
                        "execution_base_ref": binding.execution_base_ref,
                        "execution_source_revision": binding.execution_source_revision,
                        "continuation_mode": binding.continuation_mode.value,
                        "native_rule_epoch_sha256": binding.native_rule_epoch_sha256,
                    },
                )
            )
        bindings_by_sha = {
            binding.binding_sha256: binding for binding in store.bindings_for_task(task.id)
        }
        for continuation in store.records.list(
            "baseline-continuations", BaselineContinueAuthorization
        ):
            continuation.validate_integrity()
            continued_binding = bindings_by_sha.get(continuation.execution_baseline_sha256)
            if (
                continued_binding is None
                or continued_binding.continuation_mode is not BaselineContinuationMode.PAUSE
                or continuation.scope != scope
                or continuation.task_id != task.id
                or continuation.task_intent_sha256 != intent
                or continuation.expected_source_revision
                != continued_binding.execution_source_revision
                or continuation.inventory_sha256 != continued_binding.after_inventory_sha256
            ):
                raise ValueError("基线继续记录与精确保留进度不同")
            entries.append(
                TimelineEntry(
                    id="baseline_continue_" + continuation.authorization_sha256,
                    kind=ProjectionEventKind.EVIDENCE,
                    occurred_at=continuation.submitted_at,
                    task_id=task.id,
                    summary="工程授权者已明确继续原需求的保留进度; 后续执行记录确认启动与验收。",
                    source_uri=(
                        baselines
                        / store.records._name(
                            "baseline-continuations", continuation.execution_baseline_sha256
                        )
                    ).as_uri(),
                    source_sha256=continuation.authorization_sha256,
                    details={
                        "kind": continuation.kind,
                        "operator_id": continuation.principal.operator_id,
                        "execution_baseline_sha256": continuation.execution_baseline_sha256,
                        "work_item_id": continuation.work_item_id,
                        "source_revision": continuation.expected_source_revision,
                    },
                )
            )
    native = sidecar / "native-role-verification" / hashlib.sha256(task.id.encode()).hexdigest()
    if native.exists():
        for directory in sorted(native.iterdir()):
            if not directory.is_dir() or directory.is_symlink():
                raise ValueError("native verification history has an invalid Run directory")
            path = directory / "binding.json"
            native_binding = NativeRoleVerificationBinding.model_validate_json(_read(path))
            native_binding.validate_integrity()
            plan = native_binding.plan
            if (
                plan.task_id != task.id
                or plan.task_intent_sha256 != intent
                or plan.scope != scope
                or plan.requirement_id != requirement_id
                or directory.name != hashlib.sha256(plan.run_id.encode()).hexdigest()
            ):
                raise ValueError("native role verification history changed its Task or authority")
            for name in ("started", "finished"):
                record_path = directory / (name + ".json")
                if not record_path.exists():
                    continue
                record = VerificationExecutionRecord.model_validate_json(_read(record_path))
                record.validate_integrity()
                if (
                    record.plan_sha256,
                    record.authorization_sha256,
                    record.invocation_sha256,
                    record.candidate_revision,
                ) != (
                    plan.plan_sha256,
                    native_binding.admission.admission_sha256,
                    plan.request_sha256,
                    plan.candidate_revision,
                ) or (
                    record.role is not plan.role
                    or record.source_root != plan.workspace_root
                    or record.capability != native_binding.capability
                    or record.native_ui is not None
                    or (record.phase == "STARTED") != (name == "started")
                    or (name == "finished" and not (directory / "started.json").is_file())
                ):
                    raise ValueError("native verification execution has no exact binding")
                entries.append(
                    TimelineEntry(
                        id="verification_" + record.record_sha256,
                        kind=ProjectionEventKind.EVIDENCE,
                        occurred_at=record.recorded_at,
                        task_id=task.id,
                        run_id=plan.run_id,
                        role=plan.role,
                        summary="独立角色受控验证已开始。"
                        if name == "started"
                        else "独立角色受控验证已封存执行证据, 验收结论以角色报告为准。",
                        source_uri=record_path.as_uri(),
                        source_sha256=record.record_sha256,
                        details={
                            "kind": record.kind,
                            "phase": record.phase,
                            "failure_code": record.effective_failure_code,
                            "candidate_revision": plan.candidate_revision,
                        },
                    )
                )
    for root in (sidecar / "state").glob("*"):
        if not root.is_dir():
            continue
        for path in root.glob("engineering-disposition-*.json"):
            terminal_record = EngineeringDispositionRecord.model_validate_json(_read(path))
            terminal_record.validate_integrity()
            if path.name != "engineering-disposition-" + terminal_record.record_sha256 + ".json":
                raise ValueError("terminal engineering record changed its immutable store key")
            if terminal_record.source_task_id != task.id:
                continue
            if (
                terminal_record.delivery_id != requirement_id
                or terminal_record.repository_root != task.repository
                or terminal_record.disposition.facts.task_intent_sha256 != intent
                or terminal_record.source_task_status != task.status
                or terminal_record.source_task_snapshot_sha256 != digest(task.to_wire())
            ):
                raise ValueError("terminal engineering history changed source Task facts")
            entries.append(
                TimelineEntry(
                    id="engineering_" + terminal_record.record_sha256,
                    kind=ProjectionEventKind.EVIDENCE,
                    occurred_at=terminal_record.recorded_at,
                    task_id=task.id,
                    summary=terminal_record.disposition.reason,
                    source_uri=path.as_uri(),
                    source_sha256=terminal_record.record_sha256,
                    details={
                        "kind": terminal_record.kind,
                        "rejection_code": terminal_record.rejection_code,
                        "responsibility": terminal_record.disposition.responsibility.value,
                        "reason_code": terminal_record.disposition.facts.classification,
                        "source_task_status": terminal_record.source_task_status.value,
                        "source_task_snapshot_sha256": terminal_record.source_task_snapshot_sha256,
                        "next_action": terminal_record.disposition.next_action,
                    },
                )
            )
    return tuple(
        entry.model_copy(
            update={
                "summary": redact_text(entry.summary).text,
                "source_uri": redact_text(entry.source_uri).text,
                "details": {
                    redact_text(key).text: _safe(value) for key, value in entry.details.items()
                },
            }
        )
        for entry in sorted(entries, key=lambda item: (item.occurred_at, item.id))
    )
