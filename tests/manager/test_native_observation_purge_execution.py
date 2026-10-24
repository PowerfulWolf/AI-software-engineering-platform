"""Real scoped purge execution removes private counters and rejects late drift."""

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.domain import Task, TaskStatus
from ai_software_engineer.multi_directory.deletion import ProductionRequirementDeletionGuard
from ai_software_engineer.multi_directory.purge import (
    RequirementPurgePlan,
    RequirementPurger,
    RequirementPurgeRejected,
    read_purge_completion,
)
from ai_software_engineer.multi_directory.service import CreateRequirement
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationScope,
    ExecutionCaptureStart,
    ExecutionCaptureStop,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.orchestration.native_observation import NativeExecutionObservation
from ai_software_engineer.store import MySqlTaskRepository
from tests.evaluation.test_handoff import _persist_trace
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.manager.test_requirement_cancellation import _Repository
from tests.manager.test_requirement_deletion import _Queue
from tests.manager.test_requirement_resource_release import _persist_physical_delete_facts
from tests.manager.test_requirement_retirement import _service
from tests.orchestration.test_continuation_records import NOW, make_receipt
from tests.orchestration.test_native_continuation import claim
from tests.orchestration.test_native_observation_store import output_observation


@dataclass(frozen=True)
class NativePurgeCase:
    purger: RequirementPurger
    plan: RequirementPurgePlan
    task: Task
    store: FileContinuationStore
    observation: NativeExecutionObservation
    continuation: Path
    journal: Path
    foreign: Path

    @property
    def observation_path(self) -> Path:
        return self.continuation / f"native-observation-{self.observation.run_id}.json"


def _case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dsn: str,
    *,
    include_observation: bool,
) -> NativePurgeCase:
    # Reuse the terminal trace and protected SQL preparation used by the real
    # handoff purge test. No production config or provider is involved.
    trace = tmp_path / "trace"
    trace.mkdir()
    repository, _ = _persist_trace(trace, terminal=TaskStatus.BLOCKED)
    try:
        owned_task = repository.get("task_domain_001")
    finally:
        repository.close()
    service, root = _service(tmp_path / "platform", monkeypatch)
    checkpoint = service.create(
        CreateRequirement(name="native observation purge", repository_roots=(str(root),))
    ).checkpoint
    repo = service.project.repository_registry().discover()[0]
    task = Task.model_validate({**owned_task.to_wire(), "repository": str(repo.repository_root)})
    service.deletion_guard = ProductionRequirementDeletionGuard(service.project, _Queue(), dsn)
    _persist_physical_delete_facts(service, _Repository(task), dsn, tmp_path)

    receipt = make_receipt(tmp_path)
    request = receipt.request.model_copy(
        update={"task_id": task.id, "source_revision": task.base_ref}
    )
    original_claim = claim(task, request.attempt)
    original_claim = original_claim.model_copy(
        update={
            "work_item": original_claim.work_item.model_copy(
                update={"repository_id": repo.repository_id}
            ),
            "assignment": original_claim.assignment.model_copy(
                update={"repository_id": repo.repository_id}
            ),
        }
    )
    start = ExecutionCaptureStart.create(
        scope=ContinuationScope(
            team_id=checkpoint.team_id,
            project_id=checkpoint.project_id,
            repository_id=repo.repository_id,
            requirement_id=checkpoint.delivery_id,
            dispatch_sha256=receipt.scope.dispatch_sha256,
        ),
        request=request,
        claim=original_claim,
        task_intent_sha256=receipt.task_intent_sha256,
        task_revision=receipt.task_revision,
        policy_sha256=receipt.policy_sha256,
        worktree_path=str(tmp_path / "stopped-worktree"),
        inventory_before=receipt.inventory_before,
        started_at=NOW - timedelta(seconds=2),
    )
    stop = ExecutionCaptureStop.create(
        task_id=task.id,
        run_id=request.run_id,
        capture_start_sha256=start.start_sha256,
        process_stop=receipt.process_stop,
        output_present=False,
        cause=receipt.cause,
        original_error_code=receipt.original_error_code,
    )
    parent = repo.root / "state/continuations"
    parent.mkdir()
    continuation = parent / task.id
    store = FileContinuationStore.initialize(continuation, task_id=task.id)
    store.put_capture_start(start)
    store.put_capture_stop(stop)
    observation = NativeExecutionObservation.from_capture(
        start=start,
        stop=stop,
        output=output_observation(),
        recorded_at=stop.process_stop.stopped_at,
    )
    if include_observation:
        store.put_native_observation(observation)
    foreign = parent / "task_foreign_001"
    foreign.mkdir()
    (foreign / "retained.txt").write_text("other Task data")
    purger = RequirementPurger(service.project, dsn)
    plan = purger.prepare(
        checkpoint, {task.id: (repo.root, str(repo.repository_root))}, native_ids={}
    )
    assert ("project", continuation.relative_to(service.project.root).as_posix()) in (
        plan.directories
    )
    return NativePurgeCase(
        purger=purger,
        plan=plan,
        task=task,
        store=store,
        observation=observation,
        continuation=continuation,
        journal=service.journal.directory(checkpoint.delivery_id),
        foreign=foreign,
    )


def _bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.mysql
@pytest.mark.parametrize("case", ["delete", "late-add", "tamper"])
def test_real_native_observation_purge_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mysql_dsn: str,
    case: str,
) -> None:
    fixture = _case(tmp_path, monkeypatch, mysql_dsn, include_observation=case != "late-add")
    observation = fixture.observation_path
    planned_paths = {item.path for item in fixture.plan.files}
    relative = observation.relative_to(fixture.purger.project.root).as_posix()
    assert (relative in planned_paths) == (case != "late-add")
    foreign_before = _bytes(fixture.foreign)

    if case == "delete":
        completion = fixture.purger.execute(fixture.plan)
        assert not observation.exists()
        assert not fixture.continuation.exists()
        assert not fixture.journal.exists()
        assert _bytes(fixture.foreign) == foreign_before
        assert fixture.purger.pending(fixture.plan.delivery_id) is None
        assert (
            read_purge_completion(
                fixture.purger.project.requirements_root, fixture.plan.delivery_id
            )
            == completion
        )
        return

    if case == "late-add":
        fixture.store.put_native_observation(fixture.observation)
        reason = "新增文件"
    else:
        original = observation.read_bytes()
        changed = original.replace(b'"raw_bytes":12', b'"raw_bytes":13', 1)
        assert changed != original and len(changed) == len(original)
        observation.write_bytes(changed)
        reason = "已变化"

    continuation_before = _bytes(fixture.continuation)
    journal_before = _bytes(fixture.journal)
    with pytest.raises(RequirementPurgeRejected, match=reason):
        fixture.purger.execute(fixture.plan)
    assert _bytes(fixture.continuation) == continuation_before
    assert _bytes(fixture.journal) == journal_before
    assert _bytes(fixture.foreign) == foreign_before
    assert observation.exists() and fixture.continuation.exists() and fixture.journal.exists()
    assert fixture.purger.pending(fixture.plan.delivery_id) == fixture.plan
    assert (
        read_purge_completion(fixture.purger.project.requirements_root, fixture.plan.delivery_id)
        is None
    )
    with MySqlTaskRepository(mysql_dsn) as repository:
        assert repository.get(fixture.task.id) == fixture.task
