"""Knowledge lanes retain an exact approved parent, never an arbitrary scope hint."""

from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from ai_software_engineer.domain import TaskStatus
from ai_software_engineer.domain.project_delivery import (
    ProjectPreparation,
    ProjectRequest,
    _stage_digest,
)
from ai_software_engineer.manager.baseline_knowledge_scope import _require_retained_parent
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.dispatch import DispatchCommitRecord, _record_digest
from ai_software_engineer.multi_directory.models import ChildDelivery, JointCheckpoint
from ai_software_engineer.recovery.models import RecoveryPlan, RecoveryRejected, RecoveryScope
from tests.e2e.test_delivery_checkpoint import _checkpoint, _full_fields
from tests.manager.test_dispatch import RecordingDispatchStore, _facts, _service
from tests.manager.test_joint_contracts import checkpoint
from tests.recovery.test_authorization import make_plan


@dataclass(frozen=True)
class Lineage:
    plan: RecoveryPlan
    native: ProjectDeliveryCheckpoint
    parents: tuple[JointCheckpoint, ...]
    history: tuple[ProjectDeliveryCheckpoint, ...]
    source_allocation: DispatchCommitRecord
    source_request: ProjectRequest
    source_preparation: ProjectPreparation

    def read(self) -> str:
        return _require_retained_parent(
            self.plan,
            self.native,
            parents=self.parents,
            history=self.history,
            team_id="team_test",
            team_manifest_sha256="0" * 64,
            project_id="project_test",
            project_manifest_sha256="1" * 64,
            source_allocation=self.source_allocation,
            source_request=self.source_request,
            source_preparation=self.source_preparation,
        )


def _lineage(tmp_path: Path) -> Lineage:
    parent = checkpoint(tmp_path)
    root = Path(parent.scope.units[0].root)
    request, workforce = _facts(tmp_path)
    allocation = _service(RecordingDispatchStore(), workforce, request).commit_dispatch(request)
    source_task = allocation.task.model_copy(
        update={
            "id": "task_original",
            "repository": str(root),
            "metadata": {**allocation.task.metadata, "repository_id": "repository_contract_1"},
        }
    )
    allocation = allocation.model_copy(
        update={
            "repository_id": "repository_contract_1",
            "task_id": source_task.id,
            "task": source_task,
            "phases": tuple(
                phase.model_copy(
                    update={
                        "assignment": phase.assignment.model_copy(
                            update={
                                "task_id": source_task.id,
                                "repository_id": "repository_contract_1",
                            }
                        ),
                        "lease": phase.lease.model_copy(update={"task_id": source_task.id}),
                    }
                )
                for phase in allocation.phases
            ),
        }
    )
    allocation = allocation.model_copy(update={"dispatch_sha256": _record_digest(allocation)})
    preparation = ProjectPreparation.create(
        team_id=parent.team_id,
        project_id=parent.project_id,
        project_manifest_sha256=parent.project_manifest_sha256,
        repository_id="repository_contract_1",
        repository_root=str(root),
        repository_workspace_root=request.preparation.repository_workspace_root,
        team_root=request.preparation.team_root,
        repository_profile_sha256=request.preparation.repository_profile_sha256,
        runtime_binding_sha256=request.preparation.runtime_binding_sha256,
        baseline_spec_sha256=request.preparation.baseline_spec_sha256,
        prepared_at=request.preparation.prepared_at,
    )
    approved_request = request.project_request.model_copy(
        update={
            "repository_id": "repository_contract_1",
            "preparation_sha256": preparation.preparation_sha256,
        }
    )
    approved_request = approved_request.model_copy(
        update={"request_sha256": _stage_digest(approved_request, "request_sha256")}
    )
    old = _checkpoint(
        root,
        **{
            **_full_fields(),
            "repository_id": "repository_contract_1",
            "preparation_sha256": preparation.preparation_sha256,
            "dispatch_commit_id": allocation.id,
            "dispatch_commit_sha256": allocation.dispatch_sha256,
            "request_id": approved_request.id,
            "task_id": "task_original",
            "task_status": TaskStatus.BLOCKED,
            "candidate_revision": None,
            "stage": DeliveryStage.BLOCKED,
            "next_action": DeliveryNextAction.REQUEST_HUMAN,
            "failed_stage": DeliveryStage.DELIVERING,
            "failure_code": DeliveryFailureCode.RETRY_BUDGET_EXHAUSTED,
            "failure_summary": "Preserve original work",
        },
    )
    old_parent = JointCheckpoint.seal(
        {
            **parent.to_wire(),
            "children": (ChildDelivery(unit_id=parent.scope.units[0].id, checkpoint=old),),
        }
    )
    original = make_plan(root)
    source = original.source.model_copy(
        update={
            "scope": RecoveryScope(
                team_id=old_parent.team_id,
                repository_id=old.repository_id,
                delivery_id=old.delivery_id,
                repository_root=old.repository_root,
            ),
            "task_revision": old.task_revision,
            "checkpoint_sha256": old.checkpoint_sha256,
            "preparation_sha256": old.preparation_sha256,
            "dispatch_sha256": old.dispatch_commit_sha256,
            "product_spec_sha256": old.product_spec_sha256,
            "approval_sha256": old.approval_sha256,
            "technical_design_sha256": old.technical_design_sha256,
            "execution_plan_sha256": old.execution_plan_sha256,
            "parent_delivery_id": old_parent.delivery_id,
            "parent_checkpoint_sha256": old_parent.checkpoint_sha256,
        }
    )
    plan = RecoveryPlan.create(**{**original.to_wire(), "source": source})
    native = ProjectDeliveryCheckpoint.create(
        **{
            **old.to_wire(),
            "sequence": 2,
            "previous_checkpoint_sha256": old.checkpoint_sha256,
            "task_id": plan.new_task_id,
            "task_status": TaskStatus.IMPLEMENTING,
            "stage": DeliveryStage.DELIVERING,
            "next_action": DeliveryNextAction.RUN_DELIVERY,
            "failure_code": None,
            "failure_summary": None,
            "failed_stage": None,
        }
    )
    current_parent = JointCheckpoint.seal(
        {
            **old_parent.to_wire(),
            "sequence": 2,
            "previous_checkpoint_sha256": old_parent.checkpoint_sha256,
            "children": (ChildDelivery(unit_id=old_parent.children[0].unit_id, checkpoint=native),),
        }
    )
    return Lineage(
        plan,
        native,
        (old_parent, current_parent),
        (old, native),
        allocation,
        approved_request,
        preparation,
    )


def test_baseline_parent_scope_reads_exact_ancestor_without_replacing_old_context(
    tmp_path: Path,
) -> None:
    lineage = _lineage(tmp_path)
    old_plan = lineage.plan.to_wire()
    assert lineage.plan.source.parent_checkpoint_sha256 != lineage.parents[-1].checkpoint_sha256
    assert lineage.read() == lineage.parents[0].delivery_id
    assert lineage.plan.to_wire() == old_plan


@pytest.mark.parametrize(
    "change",
    [
        "missing_parent",
        "foreign_parent",
        "foreign_team",
        "foreign_project_manifest",
        "changed_approval",
        "changed_plan",
        "wrong_child",
        "ambiguous_child",
        "different_unit",
        "missing_native_prefix",
        "missing_interruption",
        "wrong_task",
        "old_source_reference",
        "wrong_preparation",
        "wrong_request_preparation",
        "wrong_source_allocation",
        "stale_native",
    ],
)
def test_unrelated_or_changed_parent_cannot_grant_knowledge_failure_proof(
    tmp_path: Path, change: str
) -> None:
    lineage = _lineage(tmp_path)
    original, current = lineage.parents
    if change == "missing_parent":
        lineage = replace(lineage, parents=(current,))
    elif change == "foreign_parent":
        source = lineage.plan.source.model_copy(update={"parent_delivery_id": "delivery_other"})
        lineage = replace(lineage, plan=lineage.plan.model_copy(update={"source": source}))
    elif change == "foreign_team":
        lineage = replace(
            lineage, parents=(original.model_copy(update={"team_id": "team_other"}), current)
        )
    elif change == "foreign_project_manifest":
        lineage = replace(
            lineage,
            parents=(original, current.model_copy(update={"project_manifest_sha256": "d" * 64})),
        )
    elif change == "changed_approval":
        assert current.approval is not None
        approval = current.approval.model_copy(update={"reference": "different decision"})
        lineage = replace(
            lineage, parents=(original, current.model_copy(update={"approval": approval}))
        )
    elif change == "changed_plan":
        lineage = replace(lineage, parents=(original, current.model_copy(update={"plan": None})))
    elif change == "wrong_child":
        child = current.children[0]
        wrong = child.checkpoint.model_copy(update={"repository_id": "repository_other"})
        lineage = replace(
            lineage,
            parents=(
                original,
                current.model_copy(
                    update={"children": (child.model_copy(update={"checkpoint": wrong}),)}
                ),
            ),
        )
    elif change == "ambiguous_child":
        lineage = replace(
            lineage,
            parents=(original, current.model_copy(update={"children": current.children * 2})),
        )
    elif change == "different_unit":
        child = current.children[0].model_copy(update={"unit_id": "unit_" + "b" * 16})
        lineage = replace(
            lineage, parents=(original, current.model_copy(update={"children": (child,)}))
        )
    elif change == "missing_native_prefix":
        lineage = replace(lineage, history=(lineage.native,))
    elif change == "missing_interruption":
        source = lineage.plan.source.model_copy(update={"checkpoint_sha256": "a" * 64})
        lineage = replace(lineage, plan=lineage.plan.model_copy(update={"source": source}))
    elif change == "wrong_task":
        lineage = replace(
            lineage, native=lineage.native.model_copy(update={"task_id": "task_other"})
        )
    elif change == "old_source_reference":
        source = lineage.plan.source.model_copy(update={"approval_sha256": "b" * 64})
        lineage = replace(lineage, plan=lineage.plan.model_copy(update={"source": source}))
    elif change == "wrong_preparation":
        source = lineage.plan.source.model_copy(update={"preparation_sha256": "b" * 64})
        lineage = replace(lineage, plan=lineage.plan.model_copy(update={"source": source}))
    elif change == "wrong_request_preparation":
        request = lineage.source_request.model_copy(update={"preparation_sha256": "b" * 64})
        request = request.model_copy(
            update={"request_sha256": _stage_digest(request, "request_sha256")}
        )
        lineage = replace(lineage, source_request=request)
    elif change == "wrong_source_allocation":
        allocation = lineage.source_allocation.model_copy(update={"task_id": "task_other"})
        allocation = allocation.model_copy(update={"dispatch_sha256": _record_digest(allocation)})
        lineage = replace(lineage, source_allocation=allocation)
    else:
        lineage = replace(lineage, native=lineage.history[0])
    with pytest.raises(RecoveryRejected):
        lineage.read()
