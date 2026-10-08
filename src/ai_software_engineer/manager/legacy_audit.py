"""Record legacy rescue's supplied human evidence in ordinary ADR evaluation."""

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
            if binding.purpose is not BaselinePurpose.LEGACY_WORKSPACE_RESCUE:
                continue
            binding.require_task(task)
            authority = store.records.get(
                "baseline-authorities", binding.plan_sha256, BaselineOperatorAuthorization
            )
            event = HumanActionEvent(
                event_id="evalevt_legacy_" + binding.binding_sha256[:32],
                case_id=case_id,
                task_id=task.id,
                occurred_at=authority.submitted_at,
                action=HumanAction.SUPPLY_EVIDENCE,
                evidence_uri=store.patch_uri(binding.plan_sha256),
                note=(
                    "工程人员确认原未知执行在本机且之后已整机重启, "
                    "平台保留完整现场后另行执行; 原结果仍未知。"
                ),
            )
            events.append(event)
