"""Record engineering recovery's human evidence in ordinary ADR evaluation."""

from pathlib import Path

from ai_software_engineer.domain import Task
from ai_software_engineer.domain.contained_unknown_budget import ContainedUnknownBudgetSettlement
from ai_software_engineer.domain.execution_baseline import BaselinePurpose
from ai_software_engineer.evaluation import (
    EvaluationCaseId,
    EvaluationEventStore,
    HumanAction,
    HumanActionEvent,
)
from ai_software_engineer.knowledge.audit import KnowledgeHumanActionRecorder
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_models import BaselineOperatorAuthorization
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.workspace_admission_contract import (
    WorkspaceAdmissionAdapterContractStore,
)


def contained_unknown_human_event(
    settlement: ContainedUnknownBudgetSettlement,
    case_id: EvaluationCaseId,
    records: KnowledgeRecordStore,
) -> HumanActionEvent:
    """Bind the auditable human action to its immutable resolution artifact."""
    settlement.validate_integrity()
    confirmation = settlement.human_confirmation
    confirmation.validate_integrity()
    return HumanActionEvent(
        event_id="evalevt_contained_unknown_" + settlement.settlement_sha256[:32],
        case_id=case_id,
        task_id=settlement.task.id,
        occurred_at=confirmation.confirmed_at,
        action=HumanAction.SUPPLY_EVIDENCE,
        evidence_uri=(
            records.root
            / records._name("contained-unknown-budget-settlements", settlement.settlement_sha256)
        ).absolute().as_uri(),
        note=(
            "工程主体根据用户精确答复 "
            + confirmation.reference
            + " 确认旧 Coder 始终本机同账户、未远迁, 全部派生工具已结束且不会再写现场; "
            "原结果与停止记录保持 UNKNOWN, 已消耗普通工作额度。"
        ),
    )


class EngineeringHumanActionRecorder:
    def __init__(self, knowledge: KnowledgeHumanActionRecorder, baseline_root: Path) -> None:
        self.knowledge, self.baseline_root = knowledge, baseline_root

    def record(self, task: Task, case_id: EvaluationCaseId, events: EvaluationEventStore) -> None:
        self.knowledge.record(task, case_id, events)
        self._record_workspace_admission_declarations(task, case_id, events)
        root = self.baseline_root / task.id
        if not root.exists():
            return
        store = FileExecutionBaselineStore(root, read_only=True)
        for binding in store.bindings_for_task(task.id):
            if binding.purpose not in {
                BaselinePurpose.LEGACY_WORKSPACE_RESCUE,
                BaselinePurpose.STOPPED_EXECUTION_RESCUE,
                BaselinePurpose.STOPPED_FAILURE_RETRY,
                BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION,
            }:
                continue
            binding.require_task(task)
            authority = store.records.get(
                "baseline-authorities", binding.plan_sha256, BaselineOperatorAuthorization
            )
            plan = store.plan(binding.plan_sha256)
            authority.validate_integrity()
            authority.require_plan_confirmation(plan)
            if binding.purpose is BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION:
                from ai_software_engineer.manager.baseline_models import (
                    require_knowledge_isolation_binding,
                )

                require_knowledge_isolation_binding(plan, binding)
                if (
                    authority.authorization_sha256 != binding.authority_sha256
                    or authority.task_id != binding.task_id
                    or authority.task_intent_sha256 != binding.task_intent_sha256
                    or authority.facts_sha256 != binding.facts_sha256
                ):
                    raise ValueError("当前知识隔离缺少精确真实工程决定")
                events.append(
                    HumanActionEvent(
                        event_id="evalevt_knowledge_isolation_" + binding.binding_sha256[:32],
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
                            "ENGINEERING 主体根据当前双重本机检查批准精确知识执行隔离; "
                            "旧知识传输历史保留 UNKNOWN, 保留完整进度并消耗一次普通工作额度。"
                        ),
                    )
                )
                continue
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

    def _record_workspace_admission_declarations(
        self, task: Task, case_id: EvaluationCaseId, events: EvaluationEventStore
    ) -> None:
        store = WorkspaceAdmissionAdapterContractStore(self.baseline_root.parent, task.id)
        for record in store.list_for_task():
            declaration = record.declaration
            if declaration.scope.repository_root != task.repository or (
                task.engineering_policy is not None
                and declaration.scope != task.engineering_policy.scope
            ):
                raise ValueError("工作区适配器部署声明不属于当前仓库")
            assert store.records is not None
            events.append(
                HumanActionEvent(
                    event_id="evalevt_wsadmission_" + record.contract_sha256[:32],
                    case_id=case_id,
                    task_id=task.id,
                    occurred_at=record.submitted_at,
                    action=HumanAction.SUPPLY_EVIDENCE,
                    evidence_uri=(
                        store.root / store.records._name("adapter-declarations", declaration.run_id)
                    )
                    .absolute()
                    .as_uri(),
                    note=(
                        "工程人员现在补充原工作区准入拒绝时的历史平台部署声明; "
                        "原调用没有自动版本回执, 原失败结果和缺失事实均保留。"
                        "本声明独立于完整可信准入证明, 不证明native进程停止或交付通过。"
                    ),
                )
            )
