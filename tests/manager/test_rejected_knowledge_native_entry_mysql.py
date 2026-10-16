"""Real native/SQL legacy proof, public reentry, owner carry and exact resolution.

Only the previously sealed preparation/allocation composition is supplied here;
claims, Contexts, native receipts, task facts, Git and queue mutations are real.
"""

import os
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from types import SimpleNamespace
from typing import Self, cast
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents.execution import bind_execution_guard
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context import ContextSource
from ai_software_engineer.domain import TaskStatus, WorkItemStatus
from ai_software_engineer.domain.delivery_resolution import HandleDeliveryWait
from ai_software_engineer.knowledge.assessment_rejection import KnowledgeAssessmentRejected
from ai_software_engineer.knowledge.models import KnowledgeError
from ai_software_engineer.manager import production_backend as module
from ai_software_engineer.manager import rejected_knowledge_preparation as rejected_module
from ai_software_engineer.manager.delivery import (
    ProjectDeliveryCheckpointCatalog,
    ProjectDeliveryResult,
    ResumeProjectDelivery,
    UnifiedProjectEntryService,
)
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryFailureCode,
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.production_backend import ProductionProjectDeliveryBackend
from ai_software_engineer.manager.rejected_knowledge_preparation import carry_rejected_knowledge
from ai_software_engineer.orchestration.retry import RetryingOrchestrator
from ai_software_engineer.work_queue.dispatcher import DispatcherTickStatus
from ai_software_engineer.work_queue.worker import (
    DeliveryWaiting,
    WorkerDeliveryFailureControl,
    WorkerExecutionGuard,
    WorkerLease,
)
from tests.work_queue.test_rejected_knowledge_mysql import (
    RejectedKnowledgeWaiting,
)
from tests.work_queue.test_rejected_knowledge_mysql import (
    rejected_waiting as rejected_waiting,
)
from tests.work_queue.test_worker_mysql import ALLOCATION_SHA, TOKEN, dispatcher

pytestmark = pytest.mark.mysql


@pytest.mark.parametrize(
    ("rejected_waiting", "mutation"),
    [
        ("legacy", "none"),
        ("legacy", "live"),
        ("legacy", "draft"),
        ("legacy", "corrupt_raw_artifact"),
        ("legacy", "crash"),
        ("legacy_parent", "none"),
        ("legacy_parent", "foreign_parent"),
        ("legacy_exhausted", "exhausted"),
    ],
    indirect=["rejected_waiting"],
)
def test_legacy_public_reentry_proves_before_append_then_fresh_owner_waits_without_model_call(
    rejected_waiting: RejectedKnowledgeWaiting,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    waiting = rejected_waiting
    before = waiting.repository.get(waiting.claim.work_item.task_id)
    sequence = waiting.repository.current_revision(before.id)
    original_bytes = waiting.immutable_bytes()
    scope = waiting.entry.scope
    sidecar = waiting.records.root.parent.parent
    registry = tmp_path / "registry"
    (registry / scope.repository_id / "state").mkdir(parents=True)
    catalog = ProjectDeliveryCheckpointCatalog(registry)
    store = catalog.for_project(scope.repository_id)
    checkpoint = ProjectDeliveryCheckpoint.create(
        delivery_id="delivery_legacy_knowledge",
        sequence=1,
        repository_id=scope.repository_id,
        repository_root=before.repository,
        preparation_sha256="1" * 64,
        request_id="request_legacy_knowledge",
        request_revision=1,
        product_checkpoint_sha256="2" * 64,
        product_spec_id="product_spec_alpha",
        product_spec_sha256="3" * 64,
        approval_id="product_approval_" + "4" * 64,
        approval_sha256="5" * 64,
        technical_design_id="technical_design_alpha",
        technical_design_sha256="6" * 64,
        execution_plan_id="execution_plan_alpha",
        execution_plan_sha256="7" * 64,
        planning_preview_id="planning_preview_" + "8" * 64,
        planning_preview_sha256="9" * 64,
        dispatch_commit_id="dispatch_legacy_knowledge",
        dispatch_commit_sha256=ALLOCATION_SHA,
        task_id=before.id,
        task_revision=sequence,
        task_status=TaskStatus.IMPLEMENTING,
        stage_attempts=DeliveryStageAttempts(delivering=1),
        stage=DeliveryStage.BLOCKED,
        next_action=DeliveryNextAction.REQUEST_HUMAN,
        failure_code=DeliveryFailureCode.INVARIANT_VIOLATION,
        failure_summary="legacy knowledge semantic rejection",
        failed_stage=DeliveryStage.DELIVERING,
        checkpointed_at=datetime.now(UTC),
    )
    store.put(checkpoint)
    old_journal = {path: path.read_bytes() for path in store._root.rglob("*.json")}
    backend = ProductionProjectDeliveryBackend.__new__(ProductionProjectDeliveryBackend)
    backend._config = cast(
        ProductionConfig, SimpleNamespace(team_id=scope.team_id, platform_root=str(tmp_path))
    )
    backend._dsn = os.environ["ASE_TEST_MYSQL_DSN"]
    backend._role_queue = waiting.queue
    knowledge_requirement = waiting.observation.binding.requirement_id
    waiting.entry.knowledge_requirement_id = knowledge_requirement
    backend._delivery_context_sources = (
        (
            ContextSource(
                source_id="joint.product",
                uri="joint://"
                + (
                    "delivery_multi_foreign"
                    if mutation == "foreign_parent"
                    else knowledge_requirement
                )
                + "/product",
                content="frozen parent context",
                required=True,
            ),
        )
        if knowledge_requirement != before.id
        else ()
    )
    workspace = SimpleNamespace(
        root=sidecar,
        repository_root=Path(before.repository),
        manifest=SimpleNamespace(project_id=scope.project_id),
        directory=lambda name: sidecar / name,
    )
    monkeypatch.setattr(
        backend,
        "_sealed_facts_for_checkpoint",
        lambda _: SimpleNamespace(
            workspace=workspace,
            product=None,
            planning=None,
        ),
    )
    allocation = SimpleNamespace(
        task_id=before.id,
        repository_id=scope.repository_id,
        dispatch_sha256=ALLOCATION_SHA,
        task=before,
    )
    authority = Mock()
    authority.get_allocation.return_value = allocation
    monkeypatch.setattr(module, "MySqlDispatchAuthority", lambda *args, **kwargs: authority)
    monkeypatch.setattr(backend, "reconcile", lambda _: None)
    clock = waiting.claim.lease.expires_at + timedelta(seconds=1)

    class AfterExpiry(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return cls.fromtimestamp(clock.timestamp(), tz=tz)

    class CarryTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return cls.fromtimestamp((clock + timedelta(seconds=3)).timestamp(), tz=tz)

    if mutation != "live":
        monkeypatch.setattr(module, "datetime", AfterExpiry)
        monkeypatch.setattr(rejected_module, "datetime", CarryTime)
    if mutation == "draft":
        (waiting.worktree / "src/unexpected.py").write_text("# unsealed draft\n")
    service = UnifiedProjectEntryService(backend=backend, catalog=catalog)
    dispatched = False
    crashed = False

    def dispatch(command: ResumeProjectDelivery) -> ProjectDeliveryResult:
        nonlocal dispatched, clock, crashed
        dispatched = True
        assert store.current(command.delivery_id).stage is DeliveryStage.DELIVERING
        reclaimed = waiting.queue.reclaim_expired(now=clock, retry_at=clock + timedelta(seconds=1))
        assert len(reclaimed) == 1
        waiting.queue.make_ready(reclaimed[0].id, now=clock + timedelta(seconds=2))
        tick = dispatcher(waiting.queue).tick(
            now=clock + timedelta(seconds=2), work_item_id=reclaimed[0].id
        )
        assert tick.status is DispatcherTickStatus.DISPATCHED and tick.claim is not None
        fresh = tick.claim
        assert fresh.lease.id != waiting.claim.lease.id
        if mutation == "crash" and not crashed:
            assert waiting.entry.artifacts is not None
            crash_lease = WorkerLease(waiting.queue, fresh, TOKEN)
            crash_guard = WorkerExecutionGuard()
            crash_guard.lease = crash_lease
            crash_lease.start()
            try:
                with pytest.raises(KnowledgeAssessmentRejected), bind_execution_guard(crash_guard):
                    carry_rejected_knowledge(
                        task=before,
                        step=waiting.queue.step(fresh.work_item.id),
                        claim=fresh,
                        records=waiting.records,
                        state=sidecar / "state",
                        queue=waiting.queue,
                        artifacts=waiting.entry.artifacts,
                        git=waiting.entry.git,
                        scope=scope,
                        requirement_id=knowledge_requirement,
                    )
            finally:
                crash_lease.stop()
                crash_guard.lease = None
            # Model a failed operation publishing a blocked Requirement cursor
            # after carry was durable but before waiting. Reenter the public
            # service again so its proof scope sees the intermediate claim.
            crashed = True
            cursor = store.current(command.delivery_id)
            store.put(
                ProjectDeliveryCheckpoint.create(
                    **{
                        **cursor.to_wire(),
                        "sequence": cursor.sequence + 1,
                        "previous_checkpoint_sha256": cursor.checkpoint_sha256,
                        "stage": DeliveryStage.BLOCKED,
                        "failure_code": checkpoint.failure_code,
                        "failure_summary": checkpoint.failure_summary,
                        "failed_stage": checkpoint.failed_stage,
                    }
                )
            )
            clock = fresh.lease.expires_at + timedelta(seconds=1)
            return service.retry_rejected_knowledge_preparation(
                command, proof_scope=backend.rejected_knowledge_retry_scope
            )
        lease = WorkerLease(waiting.queue, fresh, TOKEN)
        guard = WorkerExecutionGuard()
        guard.lease = lease
        lease.start()
        assert waiting.entry.artifacts is not None
        try:
            with pytest.raises(DeliveryWaiting), bind_execution_guard(guard):
                if mutation == "corrupt_raw_artifact":
                    artifact_root = sidecar / "artifacts"
                    artifact_root.mkdir(exist_ok=True)
                    (artifact_root / "art_corrupt.json").write_text("{broken artifact")
                    with pytest.raises(KnowledgeError, match="CARRY_UNAVAILABLE"):
                        carry_rejected_knowledge(
                            task=before,
                            step=waiting.queue.step(fresh.work_item.id),
                            claim=fresh,
                            records=waiting.records,
                            state=sidecar / "state",
                            queue=waiting.queue,
                            artifacts=waiting.entry.artifacts,
                            git=waiting.entry.git,
                            scope=scope,
                            requirement_id=knowledge_requirement,
                        )
                    WorkerDeliveryFailureControl(guard).wait(
                        before,
                        classification="PLATFORM_BUG",
                        reason="知识准备记录无法通过平台校验",
                        source_revision=waiting.source,
                        artifact_ids=(),
                    )
                with pytest.raises(KnowledgeAssessmentRejected) as failure:
                    carry_rejected_knowledge(
                        task=before,
                        step=waiting.queue.step(fresh.work_item.id),
                        claim=fresh,
                        records=waiting.records,
                        state=sidecar / "state",
                        queue=waiting.queue,
                        artifacts=waiting.entry.artifacts,
                        git=waiting.entry.git,
                        scope=scope,
                        requirement_id=knowledge_requirement,
                    )
                runner = RetryingOrchestrator.__new__(RetryingOrchestrator)
                runner._repository = waiting.repository
                runner._delivery_failure_control = WorkerDeliveryFailureControl(guard)
                runner._knowledge_failure(before, failure.value)
        finally:
            lease.stop()
            guard.lease = None
        return ProjectDeliveryResult(checkpoint=store.current(command.delivery_id))

    monkeypatch.setattr(service, "resume", dispatch)
    command = ResumeProjectDelivery(delivery_id=checkpoint.delivery_id)
    if mutation in {"live", "draft", "exhausted"}:
        with pytest.raises((ValueError, OSError)):
            service.retry_rejected_knowledge_preparation(
                command, proof_scope=backend.rejected_knowledge_retry_scope
            )
        assert not dispatched and store.current(checkpoint.delivery_id) == checkpoint
        assert waiting.queue.get(waiting.claim.work_item.id).status is WorkItemStatus.RUNNING
    elif mutation == "foreign_parent":
        result = service.retry_rejected_knowledge_preparation(
            command, proof_scope=backend.rejected_knowledge_retry_scope
        )
        assert result.checkpoint == checkpoint and not dispatched
    else:
        service.retry_rejected_knowledge_preparation(
            command, proof_scope=backend.rejected_knowledge_retry_scope
        )
        assert dispatched
        item = waiting.queue.get(waiting.claim.work_item.id)
        assert item.status is WorkItemStatus.WAITING_DEPENDENCY
        assert len(waiting.queue.claims_for_work_item(item.id)) == (3 if mutation == "crash" else 2)
        assert not waiting.queue.list_active_leases(now=datetime.min.replace(tzinfo=UTC))
        proof = waiting.entry.inspect(waiting.command())
        if mutation == "corrupt_raw_artifact":
            assert item.wait_disposition is not None
            assert item.wait_disposition.facts.classification == "PLATFORM_BUG"
            assert proof.rejected_knowledge is None and not proof.permitted_resolutions
            assert waiting.repository.get(before.id) == before
            assert waiting.call_log.read_text().splitlines() == [
                "KnowledgeIntent",
                "KnowledgeAssessment",
            ]
            assert all(Path(path).read_bytes() == data for path, data in original_bytes.items())
            return
        assert proof.rejected_knowledge is not None
        assert proof.rejected_knowledge.carry_refusal_sha256 is not None
        assert len(proof.rejected_knowledge.carry_history_sha256s) == (
            2 if mutation == "crash" else 1
        )
        handling = waiting.entry.handle(
            HandleDeliveryWait.model_validate(waiting.command().to_wire())
        )
        assert handling.resolution is not None and handling.status == "RESOLVED"
        successor = waiting.queue.resolve_wait(handling.resolution)
        assert waiting.queue.resolve_wait(handling.resolution) == successor
        after = waiting.repository.get(before.id)
        assert after.work_attempt == before.work_attempt + 1
        assert after.retry_failures == before.retry_failures
        assert after.base_ref == before.base_ref and after.status is before.status
        assert waiting.queue.get(item.id).status is WorkItemStatus.CLOSED
        assert successor.id != item.id and successor.parent_work_item_id == item.id
    assert waiting.call_log.read_text().splitlines() == ["KnowledgeIntent", "KnowledgeAssessment"]
    assert all(path.read_bytes() == data for path, data in old_journal.items())
    assert all(Path(path).read_bytes() == data for path, data in original_bytes.items())
