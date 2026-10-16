"""Record engineering recovery's human evidence in ordinary ADR evaluation."""

from pathlib import Path

from ai_software_engineer.domain import Task
from ai_software_engineer.domain.execution_baseline import BaselinePurpose
from ai_software_engineer.evaluation import (
    EvaluationCaseId,
    EvaluationEventStore,
    HumanAction,
    HumanActionEvent,
)
from ai_software_engineer.knowledge.audit import KnowledgeHumanActionRecorder
from ai_software_engineer.manager.baseline_models import BaselineOperatorAuthorization
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore


class EngineeringHumanActionRecorder:
    def __init__(self, knowledge: KnowledgeHumanActionRecorder, baseline_root: Path) -> None:
        self.knowledge, self.baseline_root = knowledge, baseline_root

    def record(self, task: Task, case_id: EvaluationCaseId, events: EvaluationEventStore) -> None:
        self.knowledge.record(task, case_id, events)
        root = self.baseline_root / task.id
        if not root.exists():
            return
        store = FileExecutionBaselineStore(root, read_only=True)
        for binding in store.bindings_for_task(task.id):
            if binding.purpose not in {
                BaselinePurpose.LEGACY_WORKSPACE_RESCUE,
                BaselinePurpose.STOPPED_EXECUTION_RESCUE,
                BaselinePurpose.STOPPED_FAILURE_RETRY,
            }:
                continue
            binding.require_task(task)
            authority = store.records.get(
                "baseline-authorities", binding.plan_sha256, BaselineOperatorAuthorization
            )
            plan = store.plan(binding.plan_sha256)
            authority.validate_integrity()
            authority.require_plan_confirmation(plan)
            if binding.purpose is BaselinePurpose.STOPPED_FAILURE_RETRY:
                plan.validate_integrity()
                failure = plan.facts.stopped_failure
                if (
                    failure is None
                    or plan.purpose is not binding.purpose
                    or failure.proof_sha256 != binding.stopped_failure_sha256
                    or authority.authorization_sha256 != binding.authority_sha256
                    or authority.plan_sha256 != binding.plan_sha256
                    or authority.facts_sha256 != binding.facts_sha256
                    or authority.task_id != binding.task_id
                    or authority.task_intent_sha256 != binding.task_intent_sha256
                    or authority.continuation_mode != binding.continuation_mode
                ):
                    raise ValueError("原执行失败恢复缺少精确原执行证明或人工工程决定")
                failure.validate_integrity()
                events.append(
                    HumanActionEvent(
                        event_id="evalevt_failure_" + binding.binding_sha256[:32],
                        case_id=case_id,
                        task_id=task.id,
                        occurred_at=authority.submitted_at,
                        action=HumanAction.SUPPLY_EVIDENCE,
                        evidence_uri=(
                            store.root
                            / store.records._name("baseline-authorities", binding.plan_sha256)
                        )
                        .absolute()
                        .as_uri(),
                        note=(
                            "工程人员精确批准原执行失败后保留完整合法草稿另行执行; "
                            "原失败原因仍未知, 本次消耗一次剩余普通工作额度。"
                        ),
                    )
                )
                continue
            if binding.purpose is BaselinePurpose.STOPPED_EXECUTION_RESCUE:
                proof = plan.facts.stopped_execution
                if proof is None or proof.proof_sha256 != binding.stopped_execution_sha256:
                    raise ValueError("未知结果停止恢复缺少精确原执行证明")
                proof.validate_integrity()
                events.append(
                    HumanActionEvent(
                        event_id="evalevt_stopped_" + binding.binding_sha256[:32],
                        case_id=case_id,
                        task_id=task.id,
                        occurred_at=authority.submitted_at,
                        action=HumanAction.SUPPLY_EVIDENCE,
                        evidence_uri=(
                            store.root
                            / store.records._name("baseline-authorities", binding.plan_sha256)
                        )
                        .absolute()
                        .as_uri(),
                        note=(
                            "工程人员精确批准已真实停止但结果未知的原执行保留完整草稿另行执行; "
                            "原结果和原因保持未知, 本次消耗普通工作额度。"
                        ),
                    )
                )
                continue
            containment = plan.facts.legacy_containment
            assert containment is not None
            local = containment.method == "operator_confirmed_local_stop"
            event = HumanActionEvent(
                event_id="evalevt_legacy_" + binding.binding_sha256[:32],
                case_id=case_id,
                task_id=task.id,
                occurred_at=authority.submitted_at,
                action=HumanAction.SUPPLY_EVIDENCE,
                evidence_uri=(
                    (store.root / store.records._name("baseline-authorities", binding.plan_sha256))
                    .absolute()
                    .as_uri()
                    if local
                    else store.patch_uri(binding.plan_sha256)
                ),
                note=(
                    "工程人员补充证据: 原调用及全部派生工具已在同机同账户本地结束, "
                    "不会再修改现场; 平台完成当前本机检查并保留完整草稿后另行执行, "
                    "原结果仍未知。"
                    if local
                    else "工程人员确认原未知执行在本机且之后已整机重启, "
                    "平台保留完整现场后另行执行; 原结果仍未知。"
                ),
            )
            events.append(event)
