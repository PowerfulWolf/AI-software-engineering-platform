"""Reviewable one-use delegated K1 maintenance; prepare never writes production.

This is an external MODIFY_TESTS intervention, not an Agent run or recovery grant.
Only ``apply --approved-plan-sha256 ... --authorization-ref ...`` writes the
exact stopped test file. Public baseline proposal can then collect the complete
receipt without starting a model; a separate exact decision authorizes delivery.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import AwareDatetime, Field, StrictInt
from pymysql.cursors import DictCursor

from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.config.runtime_environment import LocalRuntimeEnvironmentStore
from ai_software_engineer.domain import Task, TaskStatus, WorkItemStatus
from ai_software_engineer.domain.artifact import CommitSha
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.evaluation import (
    CaseStartedEvent,
    FileEvaluationEventStore,
    HumanAction,
    HumanActionEvent,
)
from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.git.mutation import (
    WorkspaceMutationInventory,
    capture_mutation_inventory,
    changed_mutation_paths,
)
from ai_software_engineer.git.policy import WorkspacePolicy
from ai_software_engineer.git.ports import WorktreeSpec
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.orchestration.capture_reconciliation import validate_capture_stop
from ai_software_engineer.orchestration.continuation_capture import CapturedMutations
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRecordMissing,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.orchestration.continuation_store import (
    FileContinuationStore,
    _open_directory,
)
from ai_software_engineer.recovery.models import canonical_bytes, digest
from ai_software_engineer.redaction import redact_text, source_secret_occurrences
from ai_software_engineer.store.mysql_repository import _decode_task
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard

TASK_ID: Final = "task_recovery_8ca06fa0aec236ab940597ad1482bfc8"
RUN_ID: Final = "run_1b8ce9675c6b4f1fbafe51b3cd2cb50f"
WORK_ID: Final = "work_6bbbcd2f142d64efbd83f17ec50a992fd7ef552414dd997361bc793bc3c57025"
ROOT = Path("/Users/zhangjunshuai/workspace/code/.ase")
SIDECAR = ROOT / (
    "projects/project_ai-project_034252eb3595/repositories/"
    "repository_c78e1680f621ff06c808aa9559666412444fbd7b"
)
CONFIG = ROOT / "config/self-iteration-ai.json"
TARGET: Final = "tests/learning/test_bounds_retry.py"
BEFORE = "737b0d716c72823f9eace6a4fb683a8c8005e2bd7adb815fc1ab244cc1c8ba52"
FILES = Path(__file__).resolve().parent


def require(value: bool) -> None:
    if not value:
        raise RuntimeError("精确维护前提不一致; 未授权的后续操作已拒绝")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def corrected_source(original: bytes) -> bytes:
    """Preserve nonempty foreign-token, empty-token and stale-fence coverage."""
    require(sha256(original) == BEFORE)
    lines = original.decode("utf-8").splitlines(keepends=True)
    require(len(lines) == 251 and lines[231].lstrip().startswith("for wrong in ("))
    lines[231:232] = [
        '        _, foreign_claim = _ledger(tmp_path / "foreign")\n',
        "        assert foreign_claim.token and foreign_claim.token != claim.token\n",
        "        for wrong in (\n",
        "            replace(claim, token=foreign_claim.token),\n",
        '            replace(claim, token=""),\n',
        "        ):\n",
    ]
    corrected = "".join(lines).encode("utf-8")
    require(not source_secret_occurrences(corrected.decode(), source_path=TARGET))
    return corrected


def correction_diff(original: bytes, corrected: bytes) -> bytes:
    return "".join(
        difflib.unified_diff(
            original.decode().splitlines(keepends=True),
            corrected.decode().splitlines(keepends=True),
            fromfile="a/" + TARGET,
            tofile="b/" + TARGET,
            n=3,
        )
    ).encode()


class MaintenancePlan(DomainModel):
    kind: Literal["delegated_external_test_maintenance"] = "delegated_external_test_maintenance"
    schema_version: Literal["v1"] = "v1"
    action: Literal["MODIFY_TESTS"] = "MODIFY_TESTS"
    task_id: Literal["task_recovery_8ca06fa0aec236ab940597ad1482bfc8"] = TASK_ID
    run_id: Literal["run_1b8ce9675c6b4f1fbafe51b3cd2cb50f"] = RUN_ID
    work_item_id: Literal[
        "work_6bbbcd2f142d64efbd83f17ec50a992fd7ef552414dd997361bc793bc3c57025"
    ] = WORK_ID
    path: Literal["tests/learning/test_bounds_retry.py"] = TARGET
    requirement_id: NonEmptyStr
    case_id: NonEmptyStr
    task_revision: Annotated[StrictInt, Field(ge=1)]
    attempt: Annotated[StrictInt, Field(ge=1)]
    task_sha256: StageSha256
    task_intent_sha256: StageSha256
    work_item_sha256: StageSha256
    step_sha256: StageSha256
    invocation_start_sha256: StageSha256
    capture_start_sha256: StageSha256
    process_stop_sha256: StageSha256
    before_sha256: StageSha256
    after_sha256: StageSha256
    diff_sha256: StageSha256
    inventory_before_sha256: StageSha256
    inventory_after_sha256: StageSha256
    head_revision: CommitSha
    branch: NonEmptyStr
    index_sha256: StageSha256
    mode: Literal[420] = 0o644
    created_at: AwareDatetime
    plan_sha256: StageSha256

    def validate_integrity(self) -> None:
        require(self.plan_sha256 == digest(self.model_dump(mode="json", exclude={"plan_sha256"})))


class MaintenanceAuthorization(DomainModel):
    plan_sha256: StageSha256
    authorization_ref: NonEmptyStr
    submitted_at: AwareDatetime
    action: Literal["MODIFY_TESTS"] = "MODIFY_TESTS"


class MaintenanceCompletion(DomainModel):
    plan_sha256: StageSha256
    action: Literal["MODIFY_TESTS"] = "MODIFY_TESTS"
    status: Literal["completed"] = "completed"
    after_sha256: StageSha256
    inventory_after_sha256: StageSha256
    evaluation_event_id: NonEmptyStr
    completed_at: AwareDatetime


class ExistingQueue(MySqlRoleQueue):
    """Open existing facts/fences without running queue schema initialization."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._external_lock = None
        self._capacity_reader = None
        self._clock = lambda: datetime.now(UTC)


@dataclass(frozen=True)
class Facts:
    task: Task
    revision: int
    item: QueuedWorkItem
    step: QueuedRoleStep
    claim: QueueClaim
    start: ExecutionCaptureStart
    stop: ExecutionCaptureStop
    invocation: DeliveryInvocationStart
    inventory: WorkspaceMutationInventory
    original: bytes
    case: CaseStartedEvent
    head_revision: str
    branch: str
    index_sha256: str


def queue_from_config() -> ExistingQueue:
    config = ProductionConfig.from_file(CONFIG)
    environment = dict(os.environ)
    environment.update(LocalRuntimeEnvironmentStore(CONFIG.parent / "runtime.env").load())
    return ExistingQueue(config.require_mysql_dsn(environment))


def load_facts(queue: ExistingQueue, cursor: DictCursor) -> Facts:
    cursor.execute("SELECT id,payload_json,revision FROM tasks WHERE id=%s", (TASK_ID,))
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("原任务不存在")
    task = _decode_task(row["id"], row["payload_json"])
    revision = row["revision"]
    require(type(revision) is int and revision == 8)
    store = FileContinuationStore(SIDECAR / "state/continuations" / TASK_ID, task_id=TASK_ID)
    start, stop = store.capture_start(RUN_ID), store.capture_stop(RUN_ID)
    start.validate_integrity()
    stop.validate_integrity()
    item, step = queue.get(WORK_ID), queue.step(WORK_ID)
    require(task.status is TaskStatus.IMPLEMENTING and task.attempts == 6)
    require(item.status is WorkItemStatus.WAITING_DEPENDENCY)
    if item.wait_disposition is None:
        raise RuntimeError("原等待事实不存在")
    require(item.wait_disposition.facts.classification == "EXECUTION_UNCERTAIN")
    require(step.work_item.id == item.id and step.boundary.task_id == task.id)
    require(step.boundary.attempt == task.attempts)
    require(step.boundary.source_revision == start.request.source_revision)
    require(step.boundary.checkpoint_sequence == revision)
    require(not stop.output_present and stop.cause == "local_execution_limit")
    require(all(accepted.run_id != RUN_ID for accepted in queue.accepted(TASK_ID)))
    records = KnowledgeRecordStore(SIDECAR / "state/invocations", read_only=True)
    invocation = records.get("invocation-starts", WORK_ID, DeliveryInvocationStart)
    invocation.validate_integrity()
    require(invocation.request == start.request)
    require(invocation.lease_id == start.claim.lease.id)
    require(records.find("invocation-outcomes", WORK_ID, DeliveryInvocationOutcome) is None)
    try:
        store.get_receipt(RUN_ID)
    except ContinuationRecordMissing:
        pass
    else:
        raise RuntimeError("原执行已封存; 此精确维护计划不再适用")
    root = Path(start.worktree_path)
    require(root == ROOT / "worktrees" / item.repository_id / TASK_ID / "coder-attempt-01")
    policy = WorkspacePolicy(
        root,
        start.request.permissions,
        denied_paths=task.constraints.denied_paths if task.constraints else (),
    )
    policy.authorize_read(TARGET)
    policy.authorize_write(TARGET)
    original = read_target(root)
    inventory = capture_mutation_inventory(root)
    require(inventory == capture_mutation_inventory(root))
    events = FileEvaluationEventStore(SIDECAR / "evaluations", read_only=True)
    paths = tuple(sorted((SIDECAR / "evaluations").glob("evalevt_*.json")))
    require(len(paths) <= 512)
    cases = tuple(
        event
        for path in paths
        if isinstance(event := events.get(path.stem), CaseStartedEvent) and event.task_id == TASK_ID
    )
    require(len(cases) == 1)
    manager = GitWorktreeManager(
        task.repository, root.parent.parent, branch_names={task.id: task.branch_name}
    )
    reference = manager.recover(
        WorktreeSpec(
            task_id=TASK_ID,
            role=start.request.role,
            attempt=1,
            source_revision=start.request.source_revision,
        )
    )
    require(reference.path == root and not reference.detached)
    if reference.branch is None:
        raise RuntimeError("原 Coder 分支不存在")
    index_path = Path(
        manager._run_git(("rev-parse", "--path-format=absolute", "--git-path", "index"), cwd=root)
    )
    index_bytes = read_regular(index_path, maximum=16 * 1024 * 1024)
    return Facts(
        task,
        revision,
        item,
        step,
        queue.original_claim(start.claim.lease.id),
        start,
        stop,
        invocation,
        inventory,
        original,
        cases[0],
        reference.head_revision,
        reference.branch,
        sha256(index_bytes),
    )


def build_plan(facts: Facts, created_at: datetime) -> MaintenancePlan:
    corrected = corrected_source(facts.original)
    inventory_after = WorkspaceMutationInventory(
        tuple(
            replace(item, sha256=sha256(corrected), size=len(corrected))
            if item.path == TARGET
            else item
            for item in facts.inventory.files
        )
    )
    provisional = MaintenancePlan(
        requirement_id=facts.start.scope.requirement_id,
        case_id=facts.case.case_id,
        task_revision=facts.revision,
        attempt=facts.task.attempts,
        task_sha256=digest(facts.task.to_wire()),
        task_intent_sha256=task_intent_sha256(facts.task),
        work_item_sha256=digest(facts.item.to_wire()),
        step_sha256=digest(facts.step.to_wire()),
        invocation_start_sha256=facts.invocation.start_sha256,
        capture_start_sha256=facts.start.start_sha256,
        process_stop_sha256=facts.stop.process_stop.stop_sha256,
        before_sha256=sha256(facts.original),
        after_sha256=sha256(corrected),
        diff_sha256=sha256(correction_diff(facts.original, corrected)),
        inventory_before_sha256=facts.inventory.sha256,
        inventory_after_sha256=inventory_after.sha256,
        head_revision=facts.head_revision,
        branch=facts.branch,
        index_sha256=facts.index_sha256,
        created_at=created_at,
        plan_sha256="0" * 64,
    )
    return provisional.model_copy(
        update={
            "plan_sha256": digest(provisional.model_dump(mode="json", exclude={"plan_sha256"})),
        }
    )


def read_regular(path: Path, *, maximum: int = 1_000_000) -> bytes:
    directory = _open_directory(path.parent)
    try:
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        try:
            before = os.fstat(descriptor)
            require(stat.S_ISREG(before.st_mode) and before.st_size <= maximum)
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                payload = stream.read(maximum + 1)
            after = os.fstat(descriptor)
            named = os.stat(path.name, dir_fd=directory, follow_symlinks=False)

            def identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
                return (
                    value.st_dev,
                    value.st_ino,
                    value.st_mode,
                    value.st_size,
                    value.st_mtime_ns,
                    value.st_ctime_ns,
                )

            require(
                identity(before) == identity(after) == identity(named)
                and len(payload) == before.st_size
            )
            return payload
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


def read_target(root: Path) -> bytes:
    path = root / TARGET
    payload = read_regular(path)
    require(stat.S_IMODE(path.lstat().st_mode) == 0o644)
    return payload


def seal(path: Path, payload: bytes) -> None:
    """Publish immutable complete audit bytes, never a partial formal record."""
    directory = _open_directory(path.parent)
    temporary = ".maintenance-" + uuid.uuid4().hex
    try:
        if path.exists() or path.is_symlink():
            require(read_regular(path, maximum=16 * 1024 * 1024) == payload)
            return
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(
                temporary,
                path.name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
        except FileExistsError:
            require(read_regular(path, maximum=16 * 1024 * 1024) == payload)
        os.fsync(directory)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory)
        os.close(directory)


@contextmanager
def read_facts(queue: ExistingQueue) -> Iterator[Facts]:
    guard = WorkerExecutionGuard()
    require((SIDECAR / "state/queue-worker-locks").is_dir())
    with (
        guard.task_scope(SIDECAR / "state/queue-worker-locks", TASK_ID),
        queue.idle_task_scope(TASK_ID) as cursor,
    ):
        facts = load_facts(queue, cursor)

        def validate_inputs(request: object) -> None:
            require(request == facts.start.request and load_facts(queue, cursor) == facts)

        validate_capture_stop(
            start=facts.start,
            stop=facts.stop,
            task=facts.task,
            task_revision=facts.revision,
            historical_claim=facts.claim,
            task_lock=guard,
            validate_inputs=validate_inputs,
        )
        yield facts


def prepare() -> None:
    """Only the isolated task directory receives plan/diff; production is read-only."""
    with read_facts(queue_from_config()) as facts:
        path = FILES / "plan.json"
        old = MaintenancePlan.model_validate_json(path.read_bytes()) if path.exists() else None
        plan = build_plan(facts, old.created_at if old else datetime.now(UTC))
        plan.validate_integrity()
        if old is not None:
            require(old == plan)
        seal(path, canonical_bytes(plan.to_wire()) + b"\n")
        seal(
            FILES / "correction.patch",
            redact_text(
                correction_diff(facts.original, corrected_source(facts.original)).decode()
            ).text.encode(),
        )
        print(json.dumps({"prepared_plan_sha256": plan.plan_sha256, "production_written": False}))


def apply(approved: str, authorization_ref: str) -> None:
    plan = MaintenancePlan.model_validate_json((FILES / "plan.json").read_bytes())
    plan.validate_integrity()
    require(approved == plan.plan_sha256 and bool(authorization_ref.strip()))
    queue, guard = queue_from_config(), WorkerExecutionGuard()
    with (
        guard.task_scope(SIDECAR / "state/queue-worker-locks", TASK_ID),
        queue.idle_task_scope(TASK_ID) as cursor,
    ):
        facts = load_facts(queue, cursor)
        audit = SIDECAR / "state/external-test-maintenance" / plan.plan_sha256
        authority_path = audit / "authorization.json"
        event_id = "evalevt_external_tests_" + approved[:32]
        already_changed = sha256(facts.original) == plan.after_sha256
        before_facts = facts
        if already_changed:
            # A crash after replacement may recover only from previously sealed
            # authority, audit and complete exact before/after bodies.
            authority = MaintenanceAuthorization.model_validate_json(read_regular(authority_path))
            require(
                authority.plan_sha256 == approved
                and authority.authorization_ref == authorization_ref
            )
            before_bytes, after_bytes = (
                read_regular(audit / "before.py"),
                read_regular(audit / "after.py"),
            )
            require(sha256(before_bytes) == plan.before_sha256 and facts.original == after_bytes)
            require(corrected_source(before_bytes) == after_bytes)
            require(read_regular(audit / "plan.json") == canonical_bytes(plan.to_wire()) + b"\n")
            require(sha256(read_regular(audit / "correction.patch")) == plan.diff_sha256)
            existing_event = FileEvaluationEventStore(SIDECAR / "evaluations", read_only=True).get(
                event_id
            )
            if not isinstance(existing_event, HumanActionEvent):
                raise RuntimeError("原外部测试修改授权审计不存在")
            require(existing_event.action is HumanAction.MODIFY_TESTS)
            require(
                existing_event.task_id == TASK_ID and existing_event.case_id == facts.case.case_id
            )
            require(existing_event.occurred_at == authority.submitted_at)
            require(existing_event.evidence_uri == (audit / "plan.json").as_uri())
            before_inventory = WorkspaceMutationInventory(
                tuple(
                    replace(item, sha256=sha256(before_bytes), size=len(before_bytes))
                    if item.path == TARGET
                    else item
                    for item in facts.inventory.files
                )
            )
            before_facts = replace(facts, original=before_bytes, inventory=before_inventory)
            require(facts.inventory.sha256 == plan.inventory_after_sha256)
        require(build_plan(before_facts, plan.created_at) == plan)

        def validate_inputs(request: object) -> None:
            require(request == facts.start.request)
            require(load_facts(queue, cursor) == facts)

        validate_capture_stop(
            start=facts.start,
            stop=facts.stop,
            task=facts.task,
            task_revision=facts.revision,
            historical_claim=facts.claim,
            task_lock=guard,
            validate_inputs=validate_inputs,
        )
        corrected = corrected_source(before_facts.original)
        patch = correction_diff(before_facts.original, corrected)
        require(
            sha256(patch) == plan.diff_sha256
            and (FILES / "correction.patch").read_bytes()
            == redact_text(patch.decode()).text.encode()
        )
        require(not any(path.is_symlink() for path in (audit, *audit.parents)))
        audit.mkdir(parents=True, exist_ok=True, mode=0o700)
        seal(audit / "plan.json", canonical_bytes(plan.to_wire()) + b"\n")
        seal(audit / "correction.patch", patch)
        seal(audit / "before.py", before_facts.original)
        seal(audit / "after.py", corrected)
        if authority_path.exists():
            authority = MaintenanceAuthorization.model_validate_json(authority_path.read_bytes())
            require(
                authority.plan_sha256 == approved
                and authority.authorization_ref == authorization_ref
            )
        else:
            authority = MaintenanceAuthorization(
                plan_sha256=approved,
                authorization_ref=authorization_ref,
                submitted_at=datetime.now(UTC),
            )
        seal(authority_path, canonical_bytes(authority.to_wire()) + b"\n")
        events = FileEvaluationEventStore(SIDECAR / "evaluations")
        event = HumanActionEvent(
            event_id=event_id,
            case_id=facts.case.case_id,
            task_id=TASK_ID,
            occurred_at=authority.submitted_at,
            action=HumanAction.MODIFY_TESTS,
            evidence_uri=(audit / "plan.json").as_uri(),
            note=(
                "用户委托的外部工程维护: 准备修改已停止执行的一处测试输入表达; "
                "保留非空未知令牌与空值及过期拒绝覆盖。实际修改以完成记录为准; "
                "不属于 ASE 自主产出, 不修改状态、预算、停止事实、产物或 verdict。"
            ),
        )
        events.append(event)
        validate_inputs(facts.start.request)
        target = Path(facts.start.worktree_path) / TARGET
        if not already_changed:
            require(read_target(Path(facts.start.worktree_path)) == facts.original)
            directory = _open_directory(target.parent)
            temporary = ".maintenance-" + uuid.uuid4().hex
            try:
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    plan.mode,
                    dir_fd=directory,
                )
                with os.fdopen(descriptor, "wb") as stream:
                    os.fchmod(stream.fileno(), plan.mode)
                    stream.write(corrected)
                    stream.flush()
                    os.fsync(stream.fileno())
                require(read_target(Path(facts.start.worktree_path)) == facts.original)
                # The only additional file is our own unpublished temporary.
                # The final inventory is checked after its atomic rename.
                os.replace(temporary, target.name, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=directory)
                os.close(directory)
        after = capture_mutation_inventory(Path(facts.start.worktree_path))
        require(changed_mutation_paths(before_facts.inventory, after) == (TARGET,))
        require(
            after.sha256 == plan.inventory_after_sha256
            and sha256(read_target(Path(facts.start.worktree_path))) == plan.after_sha256
        )
        manager = GitWorktreeManager(
            facts.task.repository,
            Path(facts.start.worktree_path).parent.parent,
            branch_names={facts.task.id: facts.task.branch_name},
        )
        worktree = manager.recover(
            WorktreeSpec(
                task_id=TASK_ID,
                role=facts.start.request.role,
                attempt=1,
                source_revision=facts.start.request.source_revision,
            )
        )
        denied = facts.task.constraints.denied_paths if facts.task.constraints else ()
        captured = manager.capture_mutations(
            worktree, facts.start.request.permissions, denied_paths=denied
        )
        stored = CapturedMutations.from_capture(captured)
        require(CapturedMutations.model_validate(stored.to_wire()).to_capture() == captured)
        manager.verify_mutations(captured, facts.start.request.permissions, denied_paths=denied)
        after_facts = load_facts(queue, cursor)
        require(
            (after_facts.head_revision, after_facts.branch, after_facts.index_sha256)
            == (plan.head_revision, plan.branch, plan.index_sha256)
        )
        require(queue.get(WORK_ID) == facts.item and queue.step(WORK_ID) == facts.step)
        cursor.execute("SELECT id,payload_json,revision FROM tasks WHERE id=%s", (TASK_ID,))
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("原任务不存在")
        require(row["revision"] == facts.revision)
        require(_decode_task(row["id"], row["payload_json"]) == facts.task)
        completion_path = audit / "completion.json"
        old_completion = (
            MaintenanceCompletion.model_validate_json(read_regular(completion_path))
            if completion_path.exists()
            else None
        )
        completion = MaintenanceCompletion(
            plan_sha256=approved,
            after_sha256=plan.after_sha256,
            inventory_after_sha256=after.sha256,
            evaluation_event_id=event_id,
            completed_at=old_completion.completed_at if old_completion else datetime.now(UTC),
        )
        if old_completion is not None:
            require(old_completion == completion)
        seal(completion_path, canonical_bytes(completion.to_wire()) + b"\n")
        seal(FILES / "completion.json", canonical_bytes(completion.to_wire()) + b"\n")
        print(json.dumps({"status": "completed", "plan_sha256": approved, "task_unchanged": True}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    execute = sub.add_parser("apply")
    execute.add_argument("--approved-plan-sha256", required=True)
    execute.add_argument("--authorization-ref", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    else:
        apply(args.approved_plan_sha256, args.authorization_ref)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"maintenance_failed": type(error).__name__}))
        raise SystemExit(1) from None
