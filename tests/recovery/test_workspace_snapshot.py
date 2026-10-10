"""Terminal recovery audits complete stopped workspaces without changing old facts."""

import fcntl
import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pymysql.cursors import DictCursor

from ai_software_engineer.agents import FileModelRouteAttemptStore
from ai_software_engineer.agents.fallback import ModelRouteAttempt, model_route_root
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.domain import (
    AgentPermissions,
    AgentRole,
    NetworkAccess,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.recovery.models import (
    CapturedChanges,
    RecoveryRejected,
    RecoveryScopeSupplement,
    RecoverySource,
    digest,
)
from ai_software_engineer.recovery.native import NativeRecoverySource
from ai_software_engineer.recovery.scope import expanded_recovery_permissions
from ai_software_engineer.recovery.workspace_records import (
    RecoveryWorkspaceScope,
    RecoveryWorkspaceSnapshot,
)
from ai_software_engineer.recovery.workspace_snapshot import (
    TerminalWorkspaceFacts,
    TerminalWorkspaceObservation,
    read_terminal_workspace_snapshot,
    validate_terminal_workspace_snapshot,
)
from ai_software_engineer.work_queue.execution_store import (
    MySqlRoleQueue,
    QueuedRoleStep,
    RoleQueueAdmission,
    record_digest,
)
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.mysql import _RISK_RANK
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.domain.factories import make_coder_progress_artifact
from tests.git.test_worktree import _git
from tests.orchestration.test_native_continuation import NOW, Fixture, Guard
from tests.recovery.test_authorization import make_plan


@dataclass(frozen=True)
class AuditFixture:
    native: Fixture
    source: RecoverySource
    capture: CapturedChanges
    facts: TerminalWorkspaceFacts
    observation: TerminalWorkspaceObservation

    def validate(self) -> RecoveryWorkspaceSnapshot:
        return validate_terminal_workspace_snapshot(
            source=self.source,
            permissions=self.native.request.permissions,
            denied_paths=(),
            capture=self.capture,
            facts=self.facts,
            observation=self.observation,
        )


def _audit(native: Fixture, *, inherited: bool = False, environment: bool = True) -> AuditFixture:
    root = native.worktree.path
    _git(root, "rev-parse", "HEAD")
    git_root = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    (git_root / "info" / "exclude").write_text(".venv/\nignored.tmp\n", encoding="utf-8")
    native.claim = native.claim.model_copy(
        update={"work_item": native.claim.work_item.model_copy(update={"checkpoint_sequence": 2})}
    )
    if inherited:
        (root / "src/app.py").write_text("VALUE = 4\n", encoding="utf-8")
    service = native.service()
    service.started(native.request, root)
    start = native.store.capture_start(native.request.run_id)
    if not inherited:
        (root / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")
    if environment:
        (root / ".venv/bin").mkdir(parents=True)
        (root / ".venv/.gitignore").write_text("*\n", encoding="utf-8")
        (root / ".venv/bin/python").symlink_to("/not-followed/unknown-python")
    stopped = native.stopped(local=False)
    stopped = stopped.model_copy(update={"stopped_at": NOW + timedelta(seconds=1)})
    stopped = stopped.model_copy(update={"stop_sha256": stopped.recompute_sha256()})
    service.record_native_stop(
        native.request,
        root,
        process_stop=stopped,
        output_present=False,
        cause=None,
        original_error_code=AgentErrorCode.WORK_INTERRUPTED,
    )
    stop = native.store.capture_stop(native.request.run_id)
    original_task = native.repository.get(native.task.id)
    native.repository.append_event(
        build_event(
            original_task,
            TaskStatus.BLOCKED,
            event_id="evt_terminal_audit",
            reason="WORK_INTERRUPTED: retained workspace needs explicit recovery",
            source_revision=native.request.source_revision,
            occurred_at=NOW + timedelta(seconds=2),
        )
    )
    task = native.repository.get(native.task.id)
    source = make_plan(Path(task.repository)).source.model_copy(
        update={
            "scope": make_plan(Path(task.repository)).source.scope.model_copy(
                update={
                    "team_id": native.scope.team_id,
                    "repository_id": native.scope.repository_id,
                    "delivery_id": native.scope.requirement_id,
                }
            ),
            "task_id": task.id,
            "task_revision": native.repository.current_revision(task.id),
            "task_sha256": digest(task.to_wire()),
            "dispatch_sha256": native.scope.dispatch_sha256,
            "failed_run_id": native.request.run_id,
            "failed_context_id": native.request.context_manifest_id,
            "base_revision": native.request.source_revision,
        }
    )
    invocation = DeliveryInvocationStart(
        work_item_id=native.claim.work_item.id,
        checkpoint_sequence=2,
        request=native.request,
        lease_id=native.claim.lease.id,
        started_at=NOW,
        start_sha256="0" * 64,
    )
    invocation = invocation.model_copy(
        update={
            "start_sha256": digest(invocation.model_dump(mode="json", exclude={"start_sha256"}))
        }
    )
    outcome = DeliveryInvocationOutcome(
        start=invocation, result=native.result(), outcome_sha256="0" * 64
    )
    outcome = outcome.model_copy(
        update={
            "outcome_sha256": digest(outcome.model_dump(mode="json", exclude={"outcome_sha256"}))
        }
    )
    route = ModelRouteAttempt.create(
        request=native.request,
        route_index=1,
        provider="fixture",
        model="fixture",
        started_at=NOW,
        completed_at=stop.process_stop.stopped_at,
        result=outcome.result,
        fallback=False,
    )
    step = QueuedRoleStep(
        work_item=native.claim.work_item,
        boundary=RoleRunBoundary(task.id, AgentRole.CODER, 1, 2, native.request.source_revision),
        allocation_sha256=source.dispatch_sha256,
    )
    facts = TerminalWorkspaceFacts(
        scope=RecoveryWorkspaceScope.model_validate(native.scope.to_wire()),
        task=task,
        task_revision=source.task_revision,
        events=tuple(native.repository.list_events(task.id)),
        start=start,
        stop=stop,
        invocation_start=invocation,
        invocation_outcome=outcome,
        historical_claim=native.claim,
        step=step,
        current_item=native.claim.work_item.model_copy(update={"status": WorkItemStatus.CLOSED}),
        routes=(route,),
    )
    capture = CapturedChanges.from_capture(
        native.git.capture_changes(
            native.worktree, native.request.permissions, base_revision=task.base_ref
        )
    )
    observation = TerminalWorkspaceObservation(
        inventory_after=capture_mutation_inventory(root),
        ignored_paths=(".venv/.gitignore", ".venv/bin/python") if environment else (),
        tracked_environment_paths=(),
        task_lock_held=True,
        process_group_stopped=True,
        observed_at=NOW + timedelta(seconds=3),
    )
    return AuditFixture(native, source, capture, facts, observation)


@pytest.fixture
def native(tmp_path: Path) -> Iterator[Fixture]:
    descriptor = os.open(tmp_path / "task.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    fixture = Fixture(tmp_path, Guard(descriptor))
    try:
        yield fixture
    finally:
        fixture.repository.close()
        os.close(descriptor)


def test_terminal_audit_preserves_legal_patch_and_complete_ignored_environment(
    native: Fixture,
) -> None:
    audit = _audit(native)
    before_task = native.repository.get(native.task.id)
    before_events = native.repository.list_events(native.task.id)
    snapshot = audit.validate()
    snapshot.validate_integrity()
    assert snapshot.capture_sha256 == audit.capture.capture_sha256
    assert snapshot.task_intent_sha256 == task_intent_sha256(before_task)
    assert snapshot.inventory_after == audit.observation.inventory_after
    assert tuple(item.path for item in snapshot.excluded_paths) == (
        ".venv/.gitignore",
        ".venv/bin/python",
    )
    assert snapshot.excluded_paths[1].kind == "symlink"
    assert "VALUE = 2" in audit.capture.patch
    assert ".venv" not in audit.capture.patch
    assert (native.worktree.path / ".venv/bin/python").is_symlink()
    assert native.repository.get(native.task.id) == before_task
    assert native.repository.list_events(native.task.id) == before_events
    assert native.store.receipts_for_task(native.task.id) == ()


def test_inherited_legal_dirty_file_remains_in_recovery_capture(native: Fixture) -> None:
    audit = _audit(native, inherited=True)
    assert audit.facts.start.inventory_before != audit.observation.inventory_after
    assert "VALUE = 4" in audit.capture.patch
    assert audit.validate().capture_sha256 == audit.capture.capture_sha256


@pytest.mark.parametrize(
    "problem",
    [
        "no_lock",
        "live_process",
        "active_item",
        "claim",
        "step",
        "terminal_revision",
        "stop_time",
        "run",
        "outcome",
        "baseline",
    ],
)
def test_terminal_execution_proof_drift_is_rejected(native: Fixture, problem: str) -> None:
    audit = _audit(native)
    if problem == "no_lock":
        audit = replace(audit, observation=replace(audit.observation, task_lock_held=False))
    elif problem == "live_process":
        audit = replace(audit, observation=replace(audit.observation, process_group_stopped=False))
    elif problem == "active_item":
        audit = replace(
            audit,
            facts=replace(
                audit.facts,
                current_item=audit.facts.current_item.model_copy(
                    update={"status": WorkItemStatus.RUNNING}
                ),
            ),
        )
    elif problem == "claim":
        claim = audit.facts.historical_claim.model_copy(update={"worker_id": "worker_other"})
        audit = replace(audit, facts=replace(audit.facts, historical_claim=claim))
    elif problem == "step":
        step = audit.facts.step.model_copy(update={"allocation_sha256": "a" * 64})
        audit = replace(audit, facts=replace(audit.facts, step=step))
    elif problem == "terminal_revision":
        audit = replace(audit, facts=replace(audit.facts, task_revision=4))
    elif problem == "stop_time":
        stop = audit.facts.stop.model_copy(
            update={
                "process_stop": audit.facts.stop.process_stop.model_copy(
                    update={"stopped_at": NOW - timedelta(seconds=1)}
                )
            }
        )
        audit = replace(audit, facts=replace(audit.facts, stop=stop))
    elif problem == "run":
        audit = replace(
            audit, source=audit.source.model_copy(update={"failed_run_id": "run_other"})
        )
    elif problem == "outcome":
        outcome = audit.facts.invocation_outcome.model_copy(update={"outcome_sha256": "e" * 64})
        audit = replace(audit, facts=replace(audit.facts, invocation_outcome=outcome))
    else:
        audit = replace(
            audit,
            source=audit.source.model_copy(
                update={"execution_baseline_sha256": "e" * 64, "execution_base_revision": "f" * 40}
            ),
        )
    with pytest.raises((RecoveryRejected, ValueError)):
        audit.validate()


@pytest.mark.parametrize(
    "problem",
    [
        "not_ignored",
        "tracked",
        "prior_environment",
        "hidden",
        "ignored_other",
        "uncovered_legal",
        "permission",
    ],
)
def test_only_first_created_ignored_environment_can_be_retained_separately(
    native: Fixture, problem: str
) -> None:
    audit = _audit(native)
    if problem == "not_ignored":
        audit = replace(audit, observation=replace(audit.observation, ignored_paths=()))
    elif problem == "tracked":
        audit = replace(
            audit,
            observation=replace(audit.observation, tracked_environment_paths=(".venv/.gitignore",)),
        )
    elif problem == "prior_environment":
        start = audit.facts.start.model_copy(
            update={"inventory_before": audit.observation.inventory_after}
        )
        start = start.model_copy(update={"start_sha256": start.recompute_sha256()})
        stop = audit.facts.stop.model_copy(update={"capture_start_sha256": start.start_sha256})
        stop = stop.model_copy(update={"observation_sha256": stop.recompute_sha256()})
        audit = replace(audit, facts=replace(audit.facts, start=start, stop=stop))
    elif problem in {"hidden", "ignored_other", "uncovered_legal"}:
        path = {
            "hidden": ".hidden",
            "ignored_other": "ignored.tmp",
            "uncovered_legal": "src/uncovered.py",
        }[problem]
        (native.worktree.path / path).write_text("unknown\n", encoding="utf-8")
        audit = replace(
            audit,
            observation=replace(
                audit.observation, inventory_after=capture_mutation_inventory(native.worktree.path)
            ),
        )
    else:
        native.request = native.request.model_copy(
            update={
                "permissions": AgentPermissions(
                    read_paths=("src/**",),
                    write_paths=("tests/**",),
                    commands=(),
                    network=NetworkAccess.NONE,
                )
            }
        )
    with pytest.raises((RecoveryRejected, ValueError)):
        audit.validate()


def _admission_failure(audit: AuditFixture) -> AuditFixture:
    process = audit.facts.stop.process_stop.model_copy(update={"kind": "local_execution_limit"})
    process = process.model_copy(update={"stop_sha256": process.recompute_sha256()})
    stop = audit.facts.stop.model_copy(
        update={
            "process_stop": process,
            "cause": "local_execution_limit",
            "original_error_code": AgentErrorCode.TIMEOUT,
        }
    )
    stop = stop.model_copy(update={"observation_sha256": stop.recompute_sha256()})
    result = audit.facts.invocation_outcome.result.model_copy(
        update={
            "error": AgentFailure(
                code=AgentErrorCode.POLICY_VIOLATION,
                message="完整现场包含本轮首次新增的 ignored 环境文件; 原现场保留",
                transient=False,
            )
        }
    )
    outcome = audit.facts.invocation_outcome.model_copy(update={"result": result})
    outcome = outcome.model_copy(
        update={
            "outcome_sha256": digest(outcome.model_dump(mode="json", exclude={"outcome_sha256"}))
        }
    )
    route = ModelRouteAttempt.create(
        request=audit.facts.start.request,
        route_index=1,
        provider="fixture",
        model="fixture",
        started_at=NOW,
        completed_at=process.stopped_at,
        result=result,
        fallback=False,
    )
    return replace(
        audit, facts=replace(audit.facts, stop=stop, invocation_outcome=outcome, routes=(route,))
    )


def test_actual_timeout_and_later_policy_admission_failure_remain_separate(native: Fixture) -> None:
    audit = _admission_failure(_audit(native))
    snapshot = audit.validate()
    assert audit.facts.stop.original_error_code is AgentErrorCode.TIMEOUT
    assert audit.facts.invocation_outcome.result.error is not None
    assert audit.facts.invocation_outcome.result.error.code is AgentErrorCode.POLICY_VIOLATION
    assert snapshot.capture_stop_sha256 == audit.facts.stop.observation_sha256
    assert snapshot.invocation_outcome_sha256 == audit.facts.invocation_outcome.outcome_sha256
    # A typed outcome is insufficient unless the exact final route corroborates it.
    original_route = ModelRouteAttempt.create(
        request=native.request,
        route_index=1,
        provider="fixture",
        model="fixture",
        started_at=NOW,
        completed_at=audit.facts.stop.process_stop.stopped_at,
        result=native.result(),
        fallback=False,
    )
    with pytest.raises((RecoveryRejected, ValueError)):
        replace(audit, facts=replace(audit.facts, routes=(original_route,))).validate()


def test_fresh_recheck_uses_stable_terminal_fact_anchor(native: Fixture) -> None:
    audit = _audit(native, environment=False)
    first = audit.validate()
    later = replace(
        audit, observation=replace(audit.observation, observed_at=NOW + timedelta(days=1))
    )
    assert later.validate() == first
    assert first.created_at == audit.facts.task.updated_at


@pytest.mark.parametrize(
    "change",
    [
        "digest",
        "control_path",
        "excluded_mode",
        "missing_inventory",
        "coerced_mode",
        "unknown_metadata",
    ],
)
def test_snapshot_wire_tampering_is_rejected(native: Fixture, change: str) -> None:
    snapshot = _audit(native).validate()
    wire = snapshot.to_wire()
    if change == "digest":
        wire["snapshot_sha256"] = "f" * 64
    elif change == "control_path":
        inventory = cast(dict[str, object], wire["inventory_after"])
        files = cast(list[dict[str, object]], inventory["files"])
        files[-1]["path"] = "src/unsafe\n.py"
    elif change == "excluded_mode":
        excluded = cast(list[dict[str, object]], wire["excluded_paths"])
        excluded[0]["mode"] = 0
    elif change == "missing_inventory":
        inventory = cast(dict[str, object], wire["inventory_after"])
        files = cast(list[dict[str, object]], inventory["files"])
        files.pop()
    elif change == "coerced_mode":
        inventory = cast(dict[str, object], wire["inventory_after"])
        files = cast(list[dict[str, object]], inventory["files"])
        files[0]["mode"] = "420"
    else:
        inventory = cast(dict[str, object], wire["inventory_after"])
        files = cast(list[dict[str, object]], inventory["files"])
        files[0]["unknown_body"] = "not allowed"
    with pytest.raises(ValueError):
        RecoveryWorkspaceSnapshot.model_validate(wire).validate_integrity()


def test_exact_scope_supplement_authorizes_audit_without_rewriting_original_request(
    native: Fixture,
) -> None:
    audit = _audit(native)
    tests_root = native.worktree.path / "tests"
    tests_root.mkdir()
    (tests_root / "regression.py").write_text("assert True\n", encoding="utf-8")
    supplement = RecoveryScopeSupplement.create(
        scope=audit.source.scope,
        task_id=audit.source.task_id,
        task_revision=audit.source.task_revision,
        checkpoint_sha256=audit.source.checkpoint_sha256,
        base_revision=audit.source.effective_base_revision,
        permissions_sha256=digest(native.request.permissions.to_wire()),
        denied_paths_sha256=digest(()),
        paths=("tests/regression.py",),
    )
    approved = expanded_recovery_permissions(native.request.permissions, supplement)
    capture = CapturedChanges.from_capture(native.git.capture_changes(native.worktree, approved))
    observation = replace(
        audit.observation, inventory_after=capture_mutation_inventory(native.worktree.path)
    )
    snapshot = validate_terminal_workspace_snapshot(
        source=audit.source,
        permissions=approved,
        denied_paths=(),
        capture=capture,
        facts=audit.facts,
        observation=observation,
        scope_supplement=supplement,
    )
    assert snapshot.capture_sha256 == capture.capture_sha256
    assert audit.facts.start.request.permissions == native.request.permissions
    with pytest.raises(RecoveryRejected):
        validate_terminal_workspace_snapshot(
            source=audit.source,
            permissions=approved,
            denied_paths=(),
            capture=capture,
            facts=audit.facts,
            observation=observation,
        )
    widened = approved.model_copy(update={"write_paths": (*approved.write_paths, "**")})
    with pytest.raises(RecoveryRejected):
        validate_terminal_workspace_snapshot(
            source=audit.source,
            permissions=widened,
            denied_paths=(),
            capture=capture,
            facts=audit.facts,
            observation=observation,
            scope_supplement=supplement,
        )


def _composition(
    audit: AuditFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ProductionConfig, NativeRecoverySource, Path]:
    import ai_software_engineer.recovery.workspace_snapshot as module

    sidecar = audit.native.worktree.path.parent.parent / "audit-sidecar"
    locks = sidecar / "state/queue-worker-locks"
    locks.mkdir(parents=True)
    lock = locks / (hashlib.sha256(audit.source.task_id.encode()).hexdigest() + ".lock")
    lock.touch(mode=0o600)
    config = ProductionConfig.model_validate(
        {
            "platform_root": str(sidecar.parent),
            "team_id": audit.source.scope.team_id,
            "model_routes": [{"provider": "codex", "model": "gpt-6.1-sol", "kind": "codex_cli"}],
        }
    )
    original = cast(
        NativeRecoverySource,
        SimpleNamespace(
            source=audit.source,
            task=audit.facts.task,
            permissions=audit.native.request.permissions,
            denied_paths=(),
            accepted_progress=None,
            worktree_revision=audit.native.request.source_revision,
        ),
    )
    registry = SimpleNamespace(
        locate_repository=lambda _identity: (
            SimpleNamespace(manifest=SimpleNamespace(project_id=audit.facts.scope.project_id)),
            SimpleNamespace(root=sidecar),
        )
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.workspace_snapshot.TeamWorkspace.initialize",
        lambda *args, **kwargs: SimpleNamespace(project_registry=lambda: registry),
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.native.NativeRecoverySourceReader.inspect",
        lambda *args, **kwargs: original,
    )
    monkeypatch.setattr(module, "_read_facts", lambda *args: audit.facts)
    monkeypatch.setattr(module, "_read_routes", lambda *args: audit.facts.routes)
    monkeypatch.setattr(
        "ai_software_engineer.recovery.workspace_snapshot.GitWorktreeManager.verify_capture",
        lambda *args, **kwargs: None,
    )
    return config, original, lock


def test_outer_recovery_fence_audit_never_initializes_or_relocks_queue(
    native: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit = _audit(native)
    config, original, lock = _composition(audit, monkeypatch)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("read-only terminal audit must not initialize or acquire queue authority")

    for method in ("__init__", "_initialize_schema", "_lock_authority", "idle_task_scope"):
        monkeypatch.setattr(MySqlRoleQueue, method, forbidden)
    monkeypatch.setattr(WorkerExecutionGuard, "task_scope", forbidden)
    before = lock.stat()
    snapshot = read_terminal_workspace_snapshot(config, {}, original, audit.capture)
    assert snapshot == audit.validate()
    assert (lock.stat().st_dev, lock.stat().st_ino) == (before.st_dev, before.st_ino)


@pytest.mark.parametrize("problem", ["missing_stop", "race", "no_lock", "busy_lock", "project"])
def test_modern_composition_missing_facts_or_live_workspace_is_rejected(
    native: Fixture, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    import ai_software_engineer.recovery.workspace_snapshot as module

    audit = _audit(native)
    config, original, lock = _composition(audit, monkeypatch)
    descriptor = -1
    if problem == "missing_stop":

        def missing(*args: object) -> TerminalWorkspaceFacts:
            raise RecoveryRejected("capture stop is missing")

        monkeypatch.setattr(module, "_read_facts", missing)
    elif problem == "race":
        calls = 0

        def drift(*args: object) -> TerminalWorkspaceFacts:
            nonlocal calls
            calls += 1
            if calls == 2:
                (native.worktree.path / "src/app.py").write_text("VALUE = 99\n", encoding="utf-8")
            return audit.facts

        monkeypatch.setattr(module, "_read_facts", drift)
    elif problem == "no_lock":
        lock.unlink()
    elif problem == "busy_lock":
        descriptor = os.open(lock, os.O_RDWR)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        monkeypatch.setattr(
            module,
            "_read_facts",
            lambda *args: replace(
                audit.facts,
                scope=audit.facts.scope.model_copy(update={"project_id": "project_other"}),
            ),
        )
    try:
        with pytest.raises(RecoveryRejected):
            read_terminal_workspace_snapshot(config, {}, original, audit.capture)
        if problem == "no_lock":
            assert not lock.exists()
        assert native.repository.get(native.task.id).status is TaskStatus.BLOCKED
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def test_legacy_task_skips_modern_audit_without_touching_existing_facts(native: Fixture) -> None:
    audit = _audit(native)
    legacy = cast(
        NativeRecoverySource,
        SimpleNamespace(
            task=audit.facts.task.model_copy(update={"interruption_continuation_policy": None})
        ),
    )
    config = ProductionConfig.model_validate(
        {"model_routes": [{"provider": "codex", "model": "gpt-6.1-sol", "kind": "codex_cli"}]}
    )
    assert read_terminal_workspace_snapshot(config, {}, legacy, audit.capture) is None


class ReadCursor:
    """Deliberately lacks write/fence APIs; returns a single queued SQL snapshot."""

    def __init__(self, answers: list[list[dict[str, object]]]) -> None:
        self.answers = answers
        self.current: list[dict[str, object]] = []
        self.queries: list[str] = []

    def execute(self, query: str, params: object = None) -> None:
        assert not any(
            token in query for token in ("FOR UPDATE", "CREATE", "INSERT", "UPDATE ", "DELETE")
        )
        assert query.startswith(("SELECT ", "SET TRANSACTION ", "START TRANSACTION "))
        self.queries.append(query)
        self.current = self.answers.pop(0)

    def fetchone(self) -> dict[str, object] | None:
        return self.current[0] if self.current else None

    def fetchall(self) -> list[dict[str, object]]:
        return self.current

    def __enter__(self) -> "ReadCursor":
        return self

    def __exit__(self, *args: object) -> None:
        pass


class ReadConnection:
    def __init__(self, cursor: ReadCursor) -> None:
        self.reader = cursor
        self.closed = False

    def cursor(self, kind: object) -> ReadCursor:
        assert kind is DictCursor
        return self.reader

    def close(self) -> None:
        self.closed = True


def _sql_answers(audit: AuditFixture) -> list[list[dict[str, object]]]:
    facts, source = audit.facts, audit.source
    admission = RoleQueueAdmission(
        task_id=source.task_id,
        repository_id=source.scope.repository_id,
        allocation_sha256=source.dispatch_sha256,
        legacy_artifacts=(),
    )
    claim = facts.historical_claim
    return [
        [
            {
                "id": source.task_id,
                "payload_json": facts.task.model_dump_json(),
                "status": "BLOCKED",
                "revision": facts.task_revision,
                "created_at": facts.task.created_at.isoformat(),
                "updated_at": facts.task.updated_at.isoformat(),
            }
        ],
        [
            {
                "payload_json": event.model_dump_json(),
                "event_id": event.event_id,
                "revision": index,
                "task_id": source.task_id,
            }
            for index, event in enumerate(facts.events, 1)
        ],
        [],
        [
            {
                "id": source.task_id,
                "task_id": source.task_id,
                "payload_json": admission.model_dump_json(),
                "sha256": record_digest(admission),
            }
        ],
        [
            {
                "lease_id": claim.lease.id,
                "task_id": source.task_id,
                "work_item_id": claim.work_item.id,
                "agent_id": claim.lease.agent_id,
                "capacity_units": claim.lease.capacity_units,
                "state": "RELEASED",
                "owner_token_sha256": "5" * 64,
                "acquired_at": claim.lease.acquired_at.isoformat(),
                "expires_at": claim.lease.expires_at.isoformat(),
                "last_heartbeat_at": claim.lease.acquired_at.isoformat(),
                "ended_at": facts.task.updated_at.isoformat(),
                "assignment_json": claim.assignment.model_dump_json(),
                "lease_json": claim.lease.model_dump_json(),
                "model_selection_json": claim.model_selection.model_dump_json(),
                "worker_id": claim.worker_id,
            }
        ],
        [
            {
                "work_item_id": claim.work_item.id,
                "lease_id": claim.lease.id,
                "event_type": "CLAIMED",
                "from_status": "READY",
                "to_status": "LEASED",
                "payload_json": json.dumps({"work_item": claim.work_item.to_wire()}),
                "occurred_at": claim.claimed_at.isoformat(),
                "sequence": 4,
            }
        ],
        [
            {
                "id": facts.current_item.id,
                "task_id": facts.current_item.task_id,
                "repository_id": facts.current_item.repository_id,
                "status": facts.current_item.status.value,
                "role": facts.current_item.role.value,
                "attempt": facts.current_item.attempt,
                "checkpoint_sequence": facts.current_item.checkpoint_sequence,
                "priority": facts.current_item.priority,
                "risk_rank": _RISK_RANK[facts.current_item.risk.value],
                "available_at": None,
                "created_at": facts.current_item.created_at.isoformat(),
                "updated_at": facts.current_item.updated_at.isoformat(),
                "payload_json": facts.current_item.model_dump_json(),
            }
        ],
        [
            {
                "id": facts.step.work_item.id,
                "task_id": source.task_id,
                "payload_json": facts.step.model_dump_json(),
                "sha256": record_digest(facts.step),
            }
        ],
        [],
        [],
        [],
    ]


def test_formal_fact_collector_is_one_read_only_consistent_snapshot(
    native: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ai_software_engineer.recovery.workspace_snapshot as module

    audit = _audit(native)
    sidecar = native.worktree.path.parent.parent / "readonly-sql-sidecar"
    continuation_root = sidecar / "state/continuations"
    continuation_root.mkdir(parents=True)
    continuation = FileContinuationStore.initialize(
        continuation_root / audit.source.task_id, task_id=audit.source.task_id
    )
    continuation.put_capture_start(audit.facts.start)
    continuation.put_capture_stop(audit.facts.stop)
    records = KnowledgeRecordStore(sidecar / "state/invocations")
    records.put("invocation-starts", audit.facts.current_item.id, audit.facts.invocation_start)
    records.put("invocation-outcomes", audit.facts.current_item.id, audit.facts.invocation_outcome)
    routes = FileModelRouteAttemptStore(model_route_root(sidecar))
    for route in audit.facts.routes:
        routes.append(route)
    config = ProductionConfig.model_validate(
        {"model_routes": [{"provider": "codex", "model": "gpt-6.1-sol", "kind": "codex_cli"}]}
    )
    original = cast(NativeRecoverySource, SimpleNamespace(source=audit.source))
    cursor = ReadCursor([[], [], *_sql_answers(audit)])
    connection = ReadConnection(cursor)
    monkeypatch.setattr(module, "open_mysql_connection", lambda _dsn: connection)
    observed = module._read_facts(
        config,
        {"ASE_MYSQL_DSN": "mysql://test:test@localhost/test"},
        original,
        sidecar,
        audit.facts.scope,
    )
    assert replace(observed, claim_record_sha256=None) == audit.facts
    assert observed.claim_record_sha256 is not None
    assert connection.closed
    assert cursor.answers == []
    assert cursor.queries[:2] == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ",
        "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY",
    ]


def test_sql_terminal_snapshot_rejects_a_live_role_claim(native: Fixture) -> None:
    import ai_software_engineer.recovery.workspace_snapshot as module

    audit = _audit(native)
    answers = _sql_answers(audit)
    answers[2] = [{"lease_id": "lease_active"}]
    cursor = ReadCursor(answers)
    with pytest.raises(RecoveryRejected):
        module._terminal_sql_facts(cast(DictCursor, cursor), audit.source, audit.facts.start)


@pytest.mark.parametrize(
    "problem",
    [
        "item_status",
        "item_task",
        "item_repository",
        "item_role",
        "item_attempt",
        "claim_state",
        "claim_agent",
        "claim_owner_hash",
        "claim_lease",
        "event_item",
        "event_status",
        "state_event_task",
    ],
)
def test_raw_sql_indexes_cannot_disagree_with_valid_payload(native: Fixture, problem: str) -> None:
    import ai_software_engineer.recovery.workspace_snapshot as module

    audit = _audit(native)
    answers = _sql_answers(audit)
    if problem.startswith("item_"):
        key = problem.removeprefix("item_")
        key = {"task": "task_id", "repository": "repository_id"}.get(key, key)
        answers[6][0][key] = {
            "status": "RUNNING",
            "task_id": "task_other",
            "repository_id": "repository_other",
            "role": "qa",
            "attempt": 99,
        }[key]
    elif problem.startswith("claim_"):
        key = {
            "state": "state",
            "agent": "agent_id",
            "owner_hash": "owner_token_sha256",
            "lease": "lease_id",
        }[problem.removeprefix("claim_")]
        answers[4][0][key] = {
            "state": "ACTIVE",
            "agent_id": "agent_other",
            "owner_token_sha256": "invalid",
            "lease_id": "lease_other",
        }[key]
    elif problem == "state_event_task":
        answers[1][0]["task_id"] = "task_other"
    else:
        key = "work_item_id" if problem == "event_item" else "to_status"
        answers[5][0][key] = "work_other" if problem == "event_item" else "RUNNING"
    with pytest.raises((RecoveryRejected, ValueError)):
        module._terminal_sql_facts(
            cast(DictCursor, ReadCursor(answers)), audit.source, audit.facts.start
        )


@pytest.mark.parametrize("case", ["accepted", "prior_only", "stop_unknown", "reader_rejected"])
def test_successful_progress_keeps_verified_existing_recovery_contract(
    native: Fixture, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    import ai_software_engineer.recovery.workspace_snapshot as module

    audit = _audit(native)
    config, original, _lock = _composition(audit, monkeypatch)
    progress = make_coder_progress_artifact().model_copy(
        update={
            "task_id": native.request.task_id,
            "source_revision": native.request.source_revision,
            "context_manifest_id": native.request.context_manifest_id,
            "producer": make_coder_progress_artifact().producer.model_copy(
                update={"run_id": native.request.run_id}
            ),
        }
    )
    original = cast(
        NativeRecoverySource, SimpleNamespace(**{**vars(original), "accepted_progress": progress})
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.native.NativeRecoverySourceReader.inspect",
        lambda *args, **kwargs: original,
    )
    route = ModelRouteAttempt.create(
        request=native.request,
        route_index=1,
        provider="fixture",
        model="fixture",
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        fallback=False,
        result=AgentResult(
            run_id=native.request.run_id,
            task_id=native.request.task_id,
            role=native.request.role,
            attempt=native.request.attempt,
            source_revision=native.request.source_revision,
            context_manifest_id=native.request.context_manifest_id,
            status=AgentRunStatus.SUCCEEDED,
            artifact=progress,
        ),
    )
    stopped_calls: list[str] = []

    def stopped(*args: object) -> None:
        if case == "stop_unknown":
            raise ValueError("progress stop is unknown")
        stopped_calls.append("verified")

    monkeypatch.setattr(
        "ai_software_engineer.recovery.progress_source.require_stopped_progress", stopped
    )
    if case == "reader_rejected":

        def rejected(*args: object, **kwargs: object) -> NativeRecoverySource:
            raise RecoveryRejected("accepted lineage is not verified")

        monkeypatch.setattr(
            "ai_software_engineer.recovery.native.NativeRecoverySourceReader.inspect", rejected
        )
    if case != "prior_only":
        monkeypatch.setattr(module, "_read_routes", lambda *args: (route,))

        def no_failure_audit(*args: object) -> TerminalWorkspaceFacts:
            pytest.fail("accepted final progress must not require a native failure capture-stop")

        monkeypatch.setattr(module, "_read_facts", no_failure_audit)
    if case == "accepted":
        assert read_terminal_workspace_snapshot(config, {}, original, audit.capture) is None
        assert stopped_calls == ["verified"]
    elif case == "prior_only":
        # Prior progress exists, but the actual selected Run FAILED: audit remains mandatory.
        assert (
            read_terminal_workspace_snapshot(config, {}, original, audit.capture)
            == audit.validate()
        )
        assert stopped_calls == []
    else:
        with pytest.raises(RecoveryRejected):
            read_terminal_workspace_snapshot(config, {}, original, audit.capture)


def test_actual_run_source_and_approved_baseline_base_can_be_distinct(native: Fixture) -> None:
    audit = _audit(native, environment=False)
    baseline = "a" * 64
    execution_base = "b" * 40
    request = audit.facts.start.request.model_copy(
        update={"execution_baseline_sha256": baseline, "execution_base_ref": execution_base}
    )
    start = audit.facts.start.model_copy(update={"request": request})
    start = start.model_copy(update={"start_sha256": start.recompute_sha256()})
    stop = audit.facts.stop.model_copy(update={"capture_start_sha256": start.start_sha256})
    stop = stop.model_copy(update={"observation_sha256": stop.recompute_sha256()})
    invocation = audit.facts.invocation_start.model_copy(update={"request": request})
    invocation = invocation.model_copy(
        update={
            "start_sha256": digest(invocation.model_dump(mode="json", exclude={"start_sha256"}))
        }
    )
    outcome = audit.facts.invocation_outcome.model_copy(update={"start": invocation})
    outcome = outcome.model_copy(
        update={
            "outcome_sha256": digest(outcome.model_dump(mode="json", exclude={"outcome_sha256"}))
        }
    )
    route = ModelRouteAttempt.create(
        request=request,
        route_index=1,
        provider="fixture",
        model="fixture",
        started_at=NOW,
        completed_at=stop.process_stop.stopped_at,
        result=outcome.result,
        fallback=False,
    )
    source = audit.source.model_copy(
        update={"execution_baseline_sha256": baseline, "execution_base_revision": execution_base}
    )
    # Rebuild capture with the exact approved base while retaining the real input HEAD.
    raw_capture = replace(audit.capture.to_capture(), base_revision=execution_base)
    capture = CapturedChanges.from_capture(raw_capture)
    facts = replace(
        audit.facts,
        start=start,
        stop=stop,
        invocation_start=invocation,
        invocation_outcome=outcome,
        routes=(route,),
    )
    snapshot = validate_terminal_workspace_snapshot(
        source=source,
        permissions=native.request.permissions,
        denied_paths=(),
        capture=capture,
        facts=facts,
        observation=audit.observation,
    )
    assert snapshot.source_revision == native.request.source_revision
    assert snapshot.effective_capture_base == execution_base
    assert snapshot.source_revision != snapshot.effective_capture_base
