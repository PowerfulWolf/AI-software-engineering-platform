"""Exact delegated maintenance, not an ASE role run or a recovery authorization.

Only the stopped K1 invalid-token test is changed. All authority/state/verdict
records remain unchanged; the intervention is recorded as MODIFY_TESTS.
"""

import hashlib
import json
import os
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from ai_software_engineer.config import (
    LocalRuntimeEnvironmentStore,
    ProductionConfig,
    runtime_environment_path,
)
from ai_software_engineer.domain import Task
from ai_software_engineer.evaluation import FileEvaluationEventStore, HumanAction, HumanActionEvent
from ai_software_engineer.git.mutation import capture_mutation_inventory, changed_mutation_paths
from ai_software_engineer.git.policy import WorkspacePolicy
from ai_software_engineer.orchestration.capture_reconciliation import validate_capture_stop
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard

TASK_ID = "task_dc5cf0aee44e5ffe0cb600557204e0d0"
RUN_ID = "run_ace680664bb14ad8abadc70f967d9d2a"
WORK_ID = "work_1a09d8b41082a0e328cbc484b09f5ac6604d5491a85e0cc6c1d6efe405bdf446"
ROOT = Path("/Users/zhangjunshuai/workspace/code/.ase")
SIDECAR = (
    ROOT
    / "projects/project_ai-project_034252eb3595/repositories"
    / "repository_c78e1680f621ff06c808aa9559666412444fbd7b"
)
CONFIG = ROOT / "config/self-iteration-ai.json"
TARGET = "tests/learning/test_recovery.py"
BEFORE = "769f4b99e1034fb60ae88f8d9c82c010d40d185bd032391a63ea3d07c9ef6467"
AFTER = "25aa6a22377dad832cdb762af17bfc805ef10924c1283ed2479685288304f7df"
EVIDENCE = Path(__file__).resolve().parent


class ExistingQueue(MySqlRoleQueue):
    def __init__(self, dsn: str) -> None:
        # Existing production schema only. Ordinary queue construction initializes
        # tables; this maintenance action uses just its existing read/fence ports.
        self._dsn = dsn
        self._external_lock = None
        self._capacity_reader = None
        self._clock = lambda: datetime.now(UTC)


def seal(path: Path, facts: dict[str, object]) -> None:
    payload = (json.dumps(facts, sort_keys=True, indent=2) + "\n").encode()
    if path.exists():
        if path.read_bytes() != payload:
            raise RuntimeError("maintenance evidence conflict")
        return
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def main() -> None:
    config = ProductionConfig.from_file(CONFIG)
    environment = {
        **os.environ,
        **LocalRuntimeEnvironmentStore(runtime_environment_path(CONFIG)).load(),
    }
    queue = ExistingQueue(config.require_mysql_dsn(environment))
    store = FileContinuationStore(SIDECAR / "state/continuations" / TASK_ID, task_id=TASK_ID)
    start, stop = store.capture_start(RUN_ID), store.capture_stop(RUN_ID)
    guard = WorkerExecutionGuard()
    with (
        guard.task_scope(SIDECAR / "state/queue-worker-locks", TASK_ID),
        queue.idle_task_scope(TASK_ID) as cursor,
    ):
        cursor.execute("SELECT payload_json,revision FROM tasks WHERE id=%s", (TASK_ID,))
        row = cursor.fetchone()
        assert row is not None
        task = Task.model_validate_json(row["payload_json"])
        item, step = queue.get(WORK_ID), queue.step(WORK_ID)
        claim = queue.original_claim(start.claim.lease.id)
        assert item.status.value == "WAITING_DEPENDENCY"
        assert (step.work_item.id, step.boundary.task_id, step.boundary.attempt) == (
            item.id,
            task.id,
            task.attempts,
        )
        assert step.boundary.source_revision == start.request.source_revision
        assert step.boundary.checkpoint_sequence == row["revision"]
        assert row["revision"] == 17 and task.attempts == 7
        assert start.scope.requirement_id == "delivery_dc5cf0aee44e5ffe0cb600557204e0d0"
        assert not stop.output_present
        assert all(a.run_id != RUN_ID for a in queue.accepted(TASK_ID))

        def validate_inputs(request: object) -> None:
            assert request == start.request
            assert queue.get(WORK_ID) == item and queue.step(WORK_ID) == step
            cursor.execute("SELECT payload_json,revision FROM tasks WHERE id=%s", (TASK_ID,))
            assert cursor.fetchone() == row

        validate_capture_stop(
            start=start,
            stop=stop,
            task=task,
            task_revision=row["revision"],
            historical_claim=claim,
            task_lock=guard,
            validate_inputs=validate_inputs,
        )
        worktree = Path(start.worktree_path)
        assert (
            worktree
            == ROOT
            / "worktrees/repository_c78e1680f621ff06c808aa9559666412444fbd7b"
            / TASK_ID
            / "coder-attempt-01"
        )
        WorkspacePolicy(
            worktree,
            start.request.permissions,
            denied_paths=task.constraints.denied_paths if task.constraints else (),
        ).authorize_write(TARGET)
        source = worktree / TARGET
        assert not source.is_symlink() and stat.S_ISREG(source.stat(follow_symlinks=False).st_mode)
        original = source.read_bytes()
        assert hashlib.sha256(original).hexdigest() == BEFORE
        old, new = b'token="wrong"', b'token=""'
        assert original.count(old) == 1
        corrected = original.replace(old, new)
        assert hashlib.sha256(corrected).hexdigest() == AFTER
        before_inventory = capture_mutation_inventory(worktree)
        assert before_inventory == capture_mutation_inventory(worktree)
        plan = {
            "task_id": TASK_ID,
            "run_id": RUN_ID,
            "work_item_id": WORK_ID,
            "path": TARGET,
            "before_sha256": BEFORE,
            "after_sha256": AFTER,
            "mode": "delegated_external_maintenance",
            "action": "MODIFY_TESTS",
            "description": (
                "无效令牌负向测试改用空值; 保留拒绝断言, 仍须独立 QA 和 Review; 不算 ASE 自主产出"
            ),
            "task_revision": row["revision"],
            "inventory_before_sha256": before_inventory.sha256,
            "process_stop_sha256": stop.process_stop.stop_sha256,
        }
        plan_path = EVIDENCE / "fixture-correction-plan.json"
        seal(plan_path, plan)
        events = FileEvaluationEventStore(SIDECAR / "evaluations")
        event_id = "evalevt_maintenance_k1_fixture_20261010"
        if events.find(event_id) is None:
            events.append(
                HumanActionEvent(
                    event_id=event_id,
                    case_id="case_9111d9a237dfeb4aa20acd654da15106",
                    task_id=TASK_ID,
                    occurred_at=datetime.now(UTC),
                    action=HumanAction.MODIFY_TESTS,
                    evidence_uri=plan_path.as_uri(),
                    note=(
                        "用户委托的外部平台维护介入: 已准备尝试修正无效凭证测试样例, "
                        "实际结果以完成记录为准。非 ASE Manager/Coder 自主修复, "
                        "不能归为自主 ADR。没有修改验收、预算、候选或 verdict。"
                    ),
                )
            )
        assert source.read_bytes() == original
        mode = stat.S_IMODE(source.stat(follow_symlinks=False).st_mode)
        fd, temporary = tempfile.mkstemp(dir=source.parent, prefix=".maintenance-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(corrected)
                os.fchmod(stream.fileno(), mode)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, source)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        after_inventory = capture_mutation_inventory(worktree)
        assert changed_mutation_paths(before_inventory, after_inventory) == (TARGET,)
        assert queue.get(WORK_ID) == item and queue.step(WORK_ID) == step
        cursor.execute("SELECT payload_json,revision FROM tasks WHERE id=%s", (TASK_ID,))
        assert cursor.fetchone() == row
        seal(
            EVIDENCE / "fixture-correction-completion.json",
            {
                **plan,
                "inventory_after_sha256": after_inventory.sha256,
                "evaluation_event_id": event_id,
                "status": "completed",
            },
        )
        print(
            "Exact fixture maintenance recorded; one test file changed; "
            "Task/queue/budgets/verdicts unchanged."
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Maintenance stopped:", type(error).__name__)
        raise SystemExit(1) from None
