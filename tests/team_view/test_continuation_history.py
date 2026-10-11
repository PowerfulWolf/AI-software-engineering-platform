"""Interruption history is read-only and cannot replace current scheduling facts."""

from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.domain.continuation import (
    InterruptionContinuationPolicy,
    task_intent_sha256,
)
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.enums import AgentRole, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.task import Task
from ai_software_engineer.git.mutation_capture import (
    FileMutationCapture,
    MutationTextBody,
    WorktreeMutationCapture,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import ExecutionInterruptionReceipt
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.projection.models import TimelineEntry
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.team_view.models import (
    DeliveryExecutionView,
    RequestView,
    RoleQueueView,
    ScopeView,
    TaskView,
)
from ai_software_engineer.team_view.reader import (
    _continuation_history,
    _request_with_current_work,
    _with_execution_state,
)
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from tests.domain.factories import make_task
from tests.orchestration.test_continuation_records import make_admission, make_receipt


def test_receipt_and_policy_admission_are_complete_read_only_history(tmp_path: Path) -> None:
    receipt = make_receipt(tmp_path)
    task = make_task().model_copy(
        update={
            "id": receipt.request.task_id,
            "base_ref": receipt.request.source_revision,
            "status": TaskStatus.IMPLEMENTING,
            "attempts": 1,
            "interruption_continuation_policy": InterruptionContinuationPolicy(),
        }
    )
    receipt = ExecutionInterruptionReceipt.create(
        **{**receipt.to_wire(), "task_intent_sha256": task_intent_sha256(task)}
    )
    sidecar = tmp_path / "sidecar"
    parent = sidecar / "state" / "continuations"
    parent.mkdir(parents=True, mode=0o700)
    store = FileContinuationStore.initialize(parent / task.id, task_id=task.id)
    store.put_receipt(receipt)
    store.put_admission(make_admission(receipt))
    before = {path: path.read_bytes() for path in sidecar.rglob("*") if path.is_file()}
    history, observed = _continuation_history(sidecar, task, receipt.scope)
    assert observed is None  # History alone is not a current execution receipt.
    assert len(history) == 2
    assert history[0].details["is_progress_or_candidate"] is False
    assert history[1].details["authorization_source"] == "authorized_by_policy"
    assert history[0].task_id == history[1].task_id == task.id
    assert history[0].run_id != history[1].run_id
    assert before == {path: path.read_bytes() for path in sidecar.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="delivery facts"):
        _continuation_history(
            sidecar, task, receipt.scope.model_copy(update={"project_id": "project_foreign"})
        )
    with pytest.raises(ValueError, match="delivery facts"):
        _continuation_history(
            sidecar, task.model_copy(update={"title": "changed scope"}), receipt.scope
        )
    with pytest.raises(ValueError, match="delivery facts"):
        _continuation_history(
            sidecar,
            task.model_copy(update={"interruption_continuation_policy": None}),
            receipt.scope,
        )


def test_missing_continuation_history_creates_no_directory(tmp_path: Path) -> None:
    receipt = make_receipt(tmp_path)
    task = make_task().model_copy(update={"id": receipt.request.task_id})
    sidecar = tmp_path / "missing-sidecar"
    assert _continuation_history(sidecar, task, receipt.scope) == ((), None)
    assert not sidecar.exists()


def test_old_receipt_references_do_not_mask_the_current_qa_claim() -> None:
    now = make_task().created_at
    task = TaskView(
        id="delivery_history",
        project_id="project_history",
        request_id="delivery_multi_history",
        task_id="task_history",
        title="history",
        scope=ScopeView(root="/repo", selected_paths=(".",)),
        status="QA",
        checkpoint_stage="DELIVERING",
        terminal=False,
        last_activity=now,
        next_action="old interruption guidance",
        execution=DeliveryExecutionView(
            state="WAITING",
            responsibility="engineering",
            reason_code="WORK_INTERRUPTED",
            reason="Old interruption",
            next_action="Old recovery",
            policy_id="a" * 64,
            receipt_uri="receipt://old-coder",
        ),
        role_queue=(
            RoleQueueView(
                work_item_id="work_qa_history",
                role=AgentRole.QA,
                attempt=2,
                status=WorkItemStatus.RUNNING,
                lease_liveness="LEASE_VALID",
                execution_phase="ROLE_EXECUTION",
            ),
        ),
    )
    projected = _with_execution_state(task)
    assert projected.execution is not None and projected.execution.state == "RUNNING"
    assert projected.execution.responsibility == "team"
    assert projected.blocker is None
    assert projected.next_action.startswith("QA 正在执行")
    assert projected.execution.receipt_uri is None
    assert projected.execution.policy_id is None


def _published(
    tmp_path: Path, *, v2: bool = False
) -> tuple[Path, Task, ExecutionInterruptionReceipt, FileContinuationStore, RoleQueueView]:
    receipt = make_receipt(tmp_path)
    policy = (
        InterruptionContinuationPolicy.for_retry_budget(
            max_work_attempts=10, max_coder_transient_failures=5
        )
        if v2
        else InterruptionContinuationPolicy()
    )
    if v2:
        capture = receipt.capture.to_capture()
        receipt = ExecutionInterruptionReceipt.create(
            **{
                **receipt.to_wire(),
                "schema_version": "v2",
                "capture": CapturedMutations.from_capture(
                    WorktreeMutationCapture(
                        worktree=capture.worktree,
                        patch=capture.patch,
                        index_diff_sha256=capture.index_diff_sha256,
                        mutations=(
                            FileMutationCapture(
                                "src/work.py", None, MutationTextBody("draft\n", 0o644)
                            ),
                        ),
                    )
                ),
            }
        )
    original = make_task()
    assert original.constraints is not None
    task = original.model_copy(
        update={
            "id": receipt.request.task_id,
            "base_ref": receipt.request.source_revision,
            "status": TaskStatus.IMPLEMENTING,
            "attempts": 1,
            "max_attempts": 40,
            "constraints": original.constraints.model_copy(update={"max_attempts": 40}),
            "interruption_continuation_policy": policy,
        }
    )
    receipt = ExecutionInterruptionReceipt.create(
        **{
            **receipt.to_wire(),
            "task_intent_sha256": task_intent_sha256(task),
            "policy_sha256": policy.policy_sha256,
        }
    )
    sidecar = tmp_path / "sidecar"
    parent = sidecar / "state" / "continuations"
    parent.mkdir(parents=True, mode=0o700)
    store = FileContinuationStore.initialize(parent / task.id, task_id=task.id)
    store.put_receipt(receipt)
    current = RoleQueueView(
        work_item_id=receipt.original_work_item_id,
        role=AgentRole.CODER,
        attempt=receipt.request.attempt,
        status=WorkItemStatus.WAITING_DEPENDENCY,
    )
    return sidecar, task, receipt, store, current


def _start(
    sidecar: Path, receipt: ExecutionInterruptionReceipt, *, corrupt_digest: bool = False
) -> DeliveryInvocationStart:
    start = DeliveryInvocationStart(
        work_item_id=receipt.original_work_item_id,
        checkpoint_sequence=1,
        request=receipt.request,
        lease_id=receipt.claim_lease_id,
        started_at=receipt.created_at - timedelta(seconds=2),
        start_sha256="0" * 64,
    )
    start = start.model_copy(
        update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
    )
    if corrupt_digest:
        start = start.model_copy(update={"start_sha256": "f" * 64})
    KnowledgeRecordStore(sidecar / "state" / "invocations").put(
        "invocation-starts", start.work_item_id, start
    )
    return start


def _view(
    task_id: str,
    queue: tuple[RoleQueueView, ...],
    history: tuple[TimelineEntry, ...] = (),
) -> TaskView:
    return TaskView(
        id="delivery_projection",
        project_id="project_continuation",
        request_id="delivery_joint_projection",
        task_id=task_id,
        title="Projection",
        scope=ScopeView(root="/repo", selected_paths=(".",)),
        status="IMPLEMENTING",
        checkpoint_stage="DELIVERING",
        terminal=False,
        last_activity=make_task().created_at,
        next_action="Existing wait",
        role_queue=queue,
        timeline=history,
    )


def test_later_wait_without_its_own_receipt_retains_history_only(tmp_path: Path) -> None:
    sidecar, task, receipt, _, current = _published(tmp_path)
    task = task.model_copy(update={"attempts": 8})
    _start(sidecar, receipt)
    later = current.model_copy(update={"work_item_id": "work_interrupted_008", "attempt": 8})
    queue = (current.model_copy(update={"status": WorkItemStatus.CLOSED}), later)
    before = {p: p.read_bytes() for p in sidecar.rglob("*") if p.is_file()}
    history, observed = _continuation_history(sidecar, task, receipt.scope, role_queue=queue)
    assert observed is None and len(history) == 1
    view = _with_execution_state(_view(task.id, queue, history))
    assert view.execution is not None and view.execution.state == "WAITING"
    assert view.execution.receipt_uri is None and view.execution.policy_id is None
    request = _request_with_current_work(
        RequestView(
            id=view.request_id,
            project_id=view.project_id,
            title=view.title,
            stage="DELIVERING",
            scopes=(view.scope,),
            next_action="Existing wait",
            checkpoint_sha256="e" * 64,
        ),
        [view],
    )
    assert request.execution == view.execution
    assert request.execution.receipt_uri is None
    assert before == {p: p.read_bytes() for p in sidecar.rglob("*") if p.is_file()}


def test_current_receipt_requires_actual_start_and_survives_projection_recomputation(
    tmp_path: Path,
) -> None:
    sidecar, task, receipt, _, current = _published(tmp_path)
    history, observed = _continuation_history(sidecar, task, receipt.scope, role_queue=(current,))
    assert observed is None
    assert not (sidecar / "state" / "invocations").exists()
    _start(sidecar, receipt)
    history, observed = _continuation_history(sidecar, task, receipt.scope, role_queue=(current,))
    assert observed == receipt
    view = _with_execution_state(_view(task.id, (current,), history))
    assert view.execution is not None
    assert view.execution.receipt_uri == history[0].source_uri
    assert view.execution.policy_id == receipt.policy_sha256
    assert _with_execution_state(view) == view
    changed = view.model_copy(
        update={"role_queue": (current.model_copy(update={"work_item_id": "work_later"}),)}
    )
    execution = _with_execution_state(changed).execution
    assert execution is not None and execution.receipt_uri is None


@pytest.mark.parametrize(
    "changed", ["source_revision", "run_id", "context_manifest_id", "lease", "digest"]
)
def test_current_receipt_rejects_changed_invocation_binding(tmp_path: Path, changed: str) -> None:
    sidecar, task, receipt, _, current = _published(tmp_path)
    altered = receipt
    if changed == "lease":
        altered = receipt.model_copy(update={"claim_lease_id": "lease_different"})
    elif changed != "digest":
        value = {
            "source_revision": "e" * 40,
            "run_id": "run_different",
            "context_manifest_id": "ctx_" + "e" * 64,
        }[changed]
        altered = receipt.model_copy(
            update={"request": receipt.request.model_copy(update={changed: value})}
        )
    _start(sidecar, altered, corrupt_digest=changed == "digest")
    before = {p: p.read_bytes() for p in sidecar.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match=r"identity|integrity"):
        _continuation_history(sidecar, task, receipt.scope, role_queue=(current,))
    assert before == {p: p.read_bytes() for p in sidecar.rglob("*") if p.is_file()}


def test_paused_baseline_does_not_borrow_a_previous_receipt(tmp_path: Path) -> None:
    sidecar, task, receipt, _, current = _published(tmp_path)
    _start(sidecar, receipt)
    history, _ = _continuation_history(sidecar, task, receipt.scope, role_queue=(current,))
    previous = _with_execution_state(_view(task.id, (current,), history))
    facts = DeliveryFailureFacts(
        task_id=task.id,
        work_item_id="work_baseline_paused",
        role=AgentRole.CODER,
        classification="EXECUTION_BASELINE_PAUSED",
        source_revision="e" * 40,
        task_intent_sha256=task_intent_sha256(task),
        checkpoint_sequence=2,
        budget_available=True,
        execution_baseline_sha256="b" * 64,
    )
    paused = current.model_copy(
        update={
            "work_item_id": facts.work_item_id,
            "attempt": 2,
            "status": WorkItemStatus.WAITING_HUMAN,
            "wait_disposition": decide_delivery_disposition(facts),
        }
    )
    view = _with_execution_state(previous.model_copy(update={"role_queue": (paused,)}))
    assert view.execution is not None
    assert view.execution.reason_code == "EXECUTION_BASELINE_PAUSED"
    assert view.execution.action_required
    assert view.execution.receipt_uri is None and view.execution.policy_id is None
    assert view.timeline == previous.timeline


def test_new_current_v2_receipt_appears_without_replacing_historical_receipts(
    tmp_path: Path,
) -> None:
    sidecar, task, old, store, current = _published(tmp_path, v2=True)
    task = task.model_copy(update={"attempts": 8})
    receipt = ExecutionInterruptionReceipt.create(
        **{
            **old.to_wire(),
            "original_work_item_id": "work_interrupted_008",
            "claim_lease_id": "lease_interrupted_008",
            "request": old.request.model_copy(
                update={"run_id": "run_interrupted_008", "attempt": 8}
            ),
        }
    )
    queue = (
        current.model_copy(update={"work_item_id": receipt.original_work_item_id, "attempt": 8}),
    )
    _start(sidecar, receipt)
    history, observed = _continuation_history(sidecar, task, old.scope, role_queue=queue)
    assert observed is None and len(history) == 1
    old_path = sidecar / "state" / "continuations" / task.id / f"receipt-{old.request.run_id}.json"
    saved = old_path.read_bytes()
    store.put_receipt(receipt)
    history, observed = _continuation_history(sidecar, task, old.scope, role_queue=queue)
    assert observed == receipt and len(history) == 2
    execution = _with_execution_state(_view(task.id, queue, history)).execution
    assert execution is not None
    assert execution.receipt_uri is not None
    assert execution.receipt_uri.endswith(f"receipt-{receipt.request.run_id}.json")
    assert old_path.read_bytes() == saved


@pytest.mark.parametrize("status", ["QA", "REVIEW", "DONE"])
def test_current_coder_receipt_cannot_follow_a_later_stage(tmp_path: Path, status: str) -> None:
    sidecar, task, receipt, _, current = _published(tmp_path)
    _start(sidecar, receipt)
    history, _ = _continuation_history(sidecar, task, receipt.scope, role_queue=(current,))
    view = _with_execution_state(_view(task.id, (current,), history))
    changed = view.model_copy(update={"status": status, "terminal": status == "DONE"})
    execution = _with_execution_state(changed).execution
    assert execution is not None
    assert execution.receipt_uri is None and execution.policy_id is None
    assert changed.timeline == view.timeline


@pytest.mark.parametrize("started", [False, True])
def test_policy_admitted_successor_does_not_borrow_original_receipt(
    tmp_path: Path, started: bool
) -> None:
    sidecar, task, receipt, store, current = _published(tmp_path)
    admission = make_admission(receipt)
    store.put_admission(admission)
    successor = current.model_copy(
        update={
            "work_item_id": admission.next_work_item_id,
            "attempt": admission.new_request.attempt,
        }
    )
    if started:
        successor_receipt = receipt.model_copy(
            update={
                "original_work_item_id": admission.next_work_item_id,
                "request": admission.new_request,
                "claim_lease_id": admission.next_lease_id,
            }
        )
        _start(sidecar, successor_receipt)
    history, observed = _continuation_history(sidecar, task, receipt.scope, role_queue=(successor,))
    assert observed is None and len(history) == 2
    assert history[1].details["next_work_item_id"] == successor.work_item_id
    execution = _with_execution_state(_view(task.id, (successor,), history)).execution
    assert execution is not None and execution.receipt_uri is None
