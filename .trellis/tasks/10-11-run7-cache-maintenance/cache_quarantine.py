"""Exact delegated cache preservation; no Task/queue/result/approval is changed."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, cast

from pydantic import AwareDatetime, model_validator
from pymysql.cursors import DictCursor

from ai_software_engineer.agents.models import AgentErrorCode, AgentRunStatus
from ai_software_engineer.domain import AgentRole, Task, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.evaluation import (
    CaseStartedEvent,
    FileEvaluationEventStore,
    HumanAction,
    HumanActionEvent,
)
from ai_software_engineer.git import GitWorktreeManager, WorktreeSpec
from ai_software_engineer.git.mutation import (
    MutationFile,
    WorkspaceMutationInventory,
    capture_mutation_inventory,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.orchestration.capture_reconciliation import validate_capture_stop
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.orchestration.continuation_store import (
    FileContinuationStore,
    _open_directory,
)
from ai_software_engineer.recovery.models import canonical_bytes, digest
from ai_software_engineer.store.mysql_repository import _decode_task
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard


class MaintenanceHelpers(Protocol):
    def queue_from_config(self) -> MySqlRoleQueue: ...
    def require(self, condition: bool) -> None: ...
    def read_regular(self, path: Path, *, maximum: int = 1_000_000) -> bytes: ...
    def seal(self, path: Path, payload: bytes) -> None: ...


def helpers() -> MaintenanceHelpers:
    """Reuse the already reviewed no-init queue and immutable no-follow audit I/O."""
    path = Path(__file__).parents[1] / "10-11-run6-fixture-maintenance/fixture_correction.py"
    spec = importlib.util.spec_from_file_location("_ase_k1_maintenance_io", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("已审查的维护 I/O 不可用")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast(MaintenanceHelpers, module)


IO = helpers()
TASK_ID = "task_recovery_8ca06fa0aec236ab940597ad1482bfc8"
RUN_ID = "run_a711050bf6384b73b588491472001fcd"
WORK_ID = "work_5d81e7201146a9c300a5badc3376a2677ee6ddcbc508ce0530828eb7948638e0"
SIDECAR = Path(
    "/Users/zhangjunshuai/workspace/code/.ase/projects/project_ai-project_034252eb3595"
) / ("repositories/repository_c78e1680f621ff06c808aa9559666412444fbd7b")
FILES = Path(__file__).resolve().parent
LARGE = MutationFile(
    ".mypy_cache/3.12/cache.db",
    "file",
    "b30ebe4a1d658a3ed3bbbee39c9da0fe7dbd39731238b920543cc1c238561888",
    0o644,
    22_716_416,
)
CACHE_PATHS = (
    ".mypy_cache/.gitignore",
    ".mypy_cache/3.12/cache.db",
    ".mypy_cache/CACHEDIR.TAG",
    ".mypy_cache/missing_stubs",
)


def require_absent_original_session() -> None:
    """Additional local observation; not a new or upgraded original stop receipt."""
    result = subprocess.run(
        ("ps", "-axo", "pid="), capture_output=True, text=True, timeout=5, check=True
    )
    pids = tuple(int(token) for token in result.stdout.split())
    IO.require(len(pids) <= 20_000)
    for pid in pids:
        try:
            sid = os.getsid(pid)
        except ProcessLookupError:
            continue
        IO.require(sid != 75117)


class MaintenancePlan(DomainModel):
    kind: Literal["exact_run7_cache_preservation"] = "exact_run7_cache_preservation"
    task: Task
    task_revision: Literal[8] = 8
    work: QueuedWorkItem
    step: QueuedRoleStep
    claim: QueueClaim
    start: ExecutionCaptureStart
    stop: ExecutionCaptureStop
    outcome: DeliveryInvocationOutcome
    case_id: NonEmptyStr
    source_capture: CapturedMutations
    index_sha256: Sha256
    before_inventory: WorkspaceMutationInventory
    cache_files: tuple[MutationFile, ...]
    created_at: AwareDatetime
    plan_sha256: Sha256

    @model_validator(mode="after")
    def exact_cache(self) -> MaintenancePlan:
        if (
            tuple(item.path for item in self.cache_files) != CACHE_PATHS
            or LARGE not in self.cache_files
            or any(item.kind != "file" for item in self.cache_files)
            or tuple(
                item for item in self.before_inventory.files if item.path.startswith(".mypy_cache/")
            )
            != self.cache_files
        ):
            raise ValueError("维护计划不是精确完整的缓存现场")
        return self

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        IO.require(
            self.plan_sha256 == digest(self.model_dump(mode="json", exclude={"plan_sha256"}))
        )


class MaintenanceAuthorization(DomainModel):
    plan_sha256: Sha256
    reference: NonEmptyStr
    submitted_at: AwareDatetime
    authorization_source: Literal["delegated_external_engineering_maintenance"] = (
        "delegated_external_engineering_maintenance"
    )


class MaintenanceCompletion(DomainModel):
    plan_sha256: Sha256
    completed_at: AwareDatetime
    after_inventory_sha256: Sha256
    archive_inventory_sha256: Sha256
    source_capture_sha256: Sha256
    original_outcome_sha256: Sha256
    original_stop_sha256: Sha256
    task_unchanged: Literal[True] = True
    budget_refund: Literal[False] = False


@dataclass(frozen=True)
class Observed:
    task: Task
    work: QueuedWorkItem
    step: QueuedRoleStep
    claim: QueueClaim
    start: ExecutionCaptureStart
    stop: ExecutionCaptureStop
    outcome: DeliveryInvocationOutcome
    capture: CapturedMutations
    index_sha256: str
    inventory: WorkspaceMutationInventory
    case_id: str


def observe(queue: MySqlRoleQueue, cursor: DictCursor, *, after: bool = False) -> Observed:
    cursor.execute("SELECT id,payload_json,revision FROM tasks WHERE id=%s", (TASK_ID,))
    row = cursor.fetchone()
    IO.require(row is not None)
    assert row is not None
    task = _decode_task(row["id"], row["payload_json"])
    IO.require(
        row["revision"] == 8 and task.status is TaskStatus.IMPLEMENTING and task.attempts == 7
    )
    work, step = queue.get(WORK_ID), queue.step(WORK_ID)
    IO.require(
        work.status is WorkItemStatus.WAITING_DEPENDENCY and work.wait_disposition is not None
    )
    IO.require(work.role is AgentRole.CODER and work.attempt == 7 and work.checkpoint_sequence == 8)
    IO.require(
        step.work_item.id == WORK_ID
        and step.boundary.source_revision == "8d494027bbbc3a97198dc410601fed11f5f9f91d"
    )
    IO.require(
        (
            step.boundary.task_id,
            step.boundary.role,
            step.boundary.attempt,
            step.boundary.checkpoint_sequence,
        )
        == (TASK_ID, AgentRole.CODER, 7, 8)
    )
    store = FileContinuationStore(SIDECAR / "state/continuations" / TASK_ID, task_id=TASK_ID)
    start, stop = store.capture_start(RUN_ID), store.capture_stop(RUN_ID)
    start.validate_integrity()
    stop.validate_integrity()
    records = KnowledgeRecordStore(SIDECAR / "state/invocations", read_only=True)
    outcome = records.get("invocation-outcomes", WORK_ID, DeliveryInvocationOutcome)
    outcome.validate_integrity()
    IO.require(
        outcome.start.request == start.request and outcome.start.lease_id == start.claim.lease.id
    )
    IO.require(
        outcome.start.work_item_id == start.claim.work_item.id == work.id == WORK_ID
        and start.request.task_id == TASK_ID
        and start.request.run_id == RUN_ID
        and start.request.role is AgentRole.CODER
        and start.request.attempt == 7
        and outcome.start.checkpoint_sequence == start.task_revision == 8
        and start.scope.repository_id == work.repository_id
        and start.scope.project_id == "project_ai-project_034252eb3595"
        and start.scope.requirement_id == "delivery_dc5cf0aee44e5ffe0cb600557204e0d0"
    )
    IO.require(outcome.result.status is AgentRunStatus.FAILED and outcome.result.artifact is None)
    error = outcome.result.error
    IO.require(error is not None)
    assert error is not None
    IO.require(error.code is AgentErrorCode.WORK_INTERRUPTED and not error.transient)
    IO.require(stop.process_stop.kind == "completed" and stop.process_stop.returncode == 0)
    IO.require(stop.output_present and stop.cause is None and stop.original_error_code is None)
    IO.require(all(item.run_id != RUN_ID for item in queue.accepted(TASK_ID)))
    claim = queue.original_claim(start.claim.lease.id)
    root = Path(start.worktree_path)
    IO.require(
        root == SIDECAR.parents[3] / "worktrees" / work.repository_id / TASK_ID / "coder-attempt-01"
    )
    manager = GitWorktreeManager(
        task.repository, root.parent.parent, branch_names={task.id: task.branch_name}
    )
    ref = manager.recover(
        WorktreeSpec(
            task_id=TASK_ID,
            role=AgentRole.CODER,
            attempt=1,
            source_revision=start.request.source_revision,
        )
    )
    IO.require(ref.path == root and ref.branch == task.branch_name and not ref.detached)
    tracked = manager._run_git(("ls-files", "--", ".mypy_cache"), cwd=root)
    IO.require(not tracked)
    if not after:
        IO.require(not (root / ".mypy_cache").is_symlink() and (root / ".mypy_cache").is_dir())
        IO.require(
            manager._run_git(("check-ignore", "--", ".mypy_cache/3.12/cache.db"), cwd=root)
            == LARGE.path
        )
    inventory = capture_mutation_inventory(root, known_oversized_file=None if after else LARGE)
    capture = CapturedMutations.from_capture(
        manager.capture_mutations(
            ref,
            start.request.permissions,
            denied_paths=task.constraints.denied_paths if task.constraints else (),
        )
    )
    index = Path(
        manager._run_git(("rev-parse", "--path-format=absolute", "--git-path", "index"), cwd=root)
    )
    index_sha = hashlib.sha256(IO.read_regular(index, maximum=16_000_000)).hexdigest()
    events = FileEvaluationEventStore(SIDECAR / "evaluations", read_only=True)
    paths = tuple(sorted((SIDECAR / "evaluations").glob("evalevt_*.json")))
    IO.require(len(paths) <= 512)
    cases = tuple(
        event
        for path in paths
        if isinstance(event := events.get(path.stem), CaseStartedEvent) and event.task_id == TASK_ID
    )
    IO.require(len(cases) == 1)
    require_absent_original_session()
    return Observed(
        task,
        work,
        step,
        claim,
        start,
        stop,
        outcome,
        capture,
        index_sha,
        inventory,
        cases[0].case_id,
    )


@contextmanager
def locked() -> Iterator[tuple[MySqlRoleQueue, DictCursor, WorkerExecutionGuard]]:
    queue, guard = IO.queue_from_config(), WorkerExecutionGuard()
    with (
        guard.task_scope(SIDECAR / "state/queue-worker-locks", TASK_ID),
        queue.idle_task_scope(TASK_ID) as cursor,
    ):
        yield queue, cursor, guard


def plan_from(facts: Observed, created_at: datetime) -> MaintenancePlan:
    values = MaintenancePlan(
        task=facts.task,
        work=facts.work,
        step=facts.step,
        claim=facts.claim,
        start=facts.start,
        stop=facts.stop,
        outcome=facts.outcome,
        case_id=facts.case_id,
        source_capture=facts.capture,
        index_sha256=facts.index_sha256,
        before_inventory=facts.inventory,
        cache_files=tuple(
            item for item in facts.inventory.files if item.path.startswith(".mypy_cache/")
        ),
        created_at=created_at,
        plan_sha256="0" * 64,
    )
    return values.model_copy(
        update={"plan_sha256": digest(values.model_dump(mode="json", exclude={"plan_sha256"}))}
    )


def validate_stop(facts: Observed, guard: WorkerExecutionGuard) -> None:
    validate_capture_stop(
        start=facts.start,
        stop=facts.stop,
        task=facts.task,
        task_revision=8,
        historical_claim=facts.claim,
        task_lock=guard,
        validate_inputs=lambda request: IO.require(request == facts.start.request),
    )


def prepare() -> None:
    with locked() as (queue, cursor, guard):
        facts = observe(queue, cursor)
        validate_stop(facts, guard)
        old = (
            MaintenancePlan.model_validate_json(
                IO.read_regular(FILES / "plan.json", maximum=16_000_000)
            )
            if (FILES / "plan.json").exists()
            else None
        )
        plan = plan_from(facts, old.created_at if old else datetime.now(UTC))
        plan.validate_integrity()
        IO.require(observe(queue, cursor) == facts and (old is None or old == plan))
        IO.seal(FILES / "plan.json", canonical_bytes(plan.to_wire()) + b"\n")
        print(
            json.dumps(
                {
                    "prepared_plan_sha256": plan.plan_sha256,
                    "cache_files": len(plan.cache_files),
                    "production_written": False,
                }
            )
        )


def apply(approved: str, reference: str) -> None:
    plan = MaintenancePlan.model_validate_json(
        IO.read_regular(FILES / "plan.json", maximum=16_000_000)
    )
    plan.validate_integrity()
    IO.require(plan.plan_sha256 == approved and bool(reference))
    with locked() as (queue, cursor, guard):
        audit = SIDECAR / "state/external-maintenance" / approved
        source = Path(plan.start.worktree_path)
        destination = audit / "mypy-cache"
        source_present = (source / ".mypy_cache").exists() or (source / ".mypy_cache").is_symlink()
        archive_present = destination.exists() or destination.is_symlink()
        IO.require(source_present != archive_present)
        if archive_present:
            IO.require((audit / "authorization.json").is_file())
        facts = observe(queue, cursor, after=archive_present)
        validate_stop(facts, guard)
        expected_after = WorkspaceMutationInventory(
            tuple(item for item in plan.before_inventory.files if item.path not in CACHE_PATHS)
        )
        if archive_present:
            IO.require(facts.inventory == expected_after)
            original = replace(facts, inventory=plan.before_inventory)
        else:
            original = facts
        IO.require(plan_from(original, plan.created_at) == plan)
        audit.mkdir(mode=0o700, parents=True, exist_ok=True)
        IO.require(
            not audit.is_symlink()
            and audit.is_dir()
            and stat.S_IMODE(audit.lstat().st_mode) == 0o700
        )
        IO.seal(audit / "plan.json", canonical_bytes(plan.to_wire()) + b"\n")
        authority_path = audit / "authorization.json"
        authority = (
            MaintenanceAuthorization.model_validate_json(IO.read_regular(authority_path))
            if authority_path.exists()
            else MaintenanceAuthorization(
                plan_sha256=approved, reference=reference, submitted_at=datetime.now(UTC)
            )
        )
        IO.require(authority.plan_sha256 == approved and authority.reference == reference)
        IO.seal(authority_path, canonical_bytes(authority.to_wire()) + b"\n")
        FileEvaluationEventStore(SIDECAR / "evaluations").append(
            HumanActionEvent(
                event_id="evalevt_external_cache_" + approved[:32],
                case_id=plan.case_id,
                task_id=TASK_ID,
                occurred_at=authority.submitted_at,
                action=HumanAction.SUPPLY_EVIDENCE,
                evidence_uri=(audit / "plan.json").as_uri(),
                note=(
                    "用户委托的外部工程维护: 完整保留已停止第7轮执行的mypy缓存并移出代码工作区。"
                    "原报告内容未知, 不接纳结果、不修改状态或预算, 不属于ASE自主交付; "
                    "实际完成以封存记录为准。"
                ),
            )
        )
        IO.require(observe(queue, cursor, after=archive_present) == facts)
        if source_present:
            IO.require(not (audit / "completion.json").exists())
            source_fd, destination_fd = _open_directory(source), _open_directory(audit)
            try:
                IO.require(os.fstat(source_fd).st_dev == os.fstat(destination_fd).st_dev)
                IO.require(not destination.exists() and not destination.is_symlink())
                os.rename(
                    ".mypy_cache", "mypy-cache", src_dir_fd=source_fd, dst_dir_fd=destination_fd
                )
                os.fsync(source_fd)
                os.fsync(destination_fd)
            finally:
                os.close(source_fd)
                os.close(destination_fd)
        archive_large = replace(LARGE, path="3.12/cache.db")
        archive = capture_mutation_inventory(destination, known_oversized_file=archive_large)
        IO.require(
            archive.files
            == tuple(
                replace(item, path=item.path.removeprefix(".mypy_cache/"))
                for item in plan.cache_files
            )
        )
        after = observe(queue, cursor, after=True)
        IO.require(after == replace(original, inventory=expected_after))
        validate_stop(after, guard)
        completion_path = audit / "completion.json"
        prior = (
            MaintenanceCompletion.model_validate_json(IO.read_regular(completion_path))
            if completion_path.exists()
            else None
        )
        completion = MaintenanceCompletion(
            plan_sha256=approved,
            completed_at=prior.completed_at if prior else datetime.now(UTC),
            after_inventory_sha256=after.inventory.sha256,
            archive_inventory_sha256=archive.sha256,
            source_capture_sha256=after.capture.capture_sha256,
            original_outcome_sha256=after.outcome.outcome_sha256,
            original_stop_sha256=after.stop.observation_sha256,
        )
        IO.require(prior is None or prior == completion)
        IO.seal(completion_path, canonical_bytes(completion.to_wire()) + b"\n")
        print(
            json.dumps(
                {
                    "completed_plan_sha256": approved,
                    "after_inventory_sha256": after.inventory.sha256,
                    "original_outcome": "FAILED",
                    "original_report": "UNKNOWN",
                    "delivery_started": False,
                    "replayed": prior is not None,
                }
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "apply"))
    parser.add_argument("--approved-plan-sha256")
    parser.add_argument("--authorization-ref")
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            prepare()
        elif args.approved_plan_sha256 and args.authorization_ref:
            apply(args.approved_plan_sha256, args.authorization_ref)
        else:
            parser.error("apply requires the exact plan digest and authorization reference")
    except Exception as error:
        print(
            json.dumps(
                {
                    "maintenance_failed": type(error).__name__,
                    "cache_may_be_in_worktree_or_private_audit": True,
                    "original_delivery_result_not_changed": True,
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
