"""A bounded input file cannot become execution authority without SQL consumption."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from ai_software_engineer.agents.fallback import (
    FileModelRouteAttemptStore,
    ModelRouteAttempt,
    model_route_root,
)
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.context import FileContextBuilder, FileContextStore
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
    PreContextRecoveryInputEvidence,
    ResolveDeliveryWait,
)
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.task import Task
from ai_software_engineer.evaluation import (
    HumanAction,
    HumanActionEvent,
    InMemoryEvaluationEventStore,
)
from ai_software_engineer.knowledge.audit import KnowledgeHumanActionRecorder
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.legacy_audit import EngineeringHumanActionRecorder
from ai_software_engineer.manager.recovery_input_schedule import (
    RecoveryInputScheduleDecision,
    _require_no_coder_start,
    get_recovery_input_schedule,
    require_consumed_recovery_input_schedule,
)
from ai_software_engineer.recovery.bounded_input import RecoveryInputSourceRef
from ai_software_engineer.web_console import (
    ConsoleCommandRejected,
    InMemoryConsoleOperationStore,
    ManagerConsoleAdapter,
    ProjectConsole,
    ResolveDeliveryWaitIntent,
)
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from tests.agents.test_openai_compatible import _coder_request
from tests.domain.factories import make_agent, make_task

PLAN = "a" * 64
BASE = "b" * 40
NOW = datetime(2026, 10, 28, 10, tzinfo=UTC)
AUTHORIZATION_REFERENCE = (
    "web-console-operation:operation_" + "1" * 32 + ":" + "2" * 64 + ":" + "3" * 64
)


def test_pre_context_recovery_allows_exact_orchestrator_preparation_context(
    tmp_path: Path,
) -> None:
    """A sealed orchestration Context is not a Coder invocation or Coder Context."""
    sidecar = tmp_path / "sidecar"
    state = sidecar / "state"
    task = make_task().model_copy(
        update={"repository": str(tmp_path), "base_ref": BASE, "attempts": 1}
    )
    context = FileContextBuilder(tmp_path, make_agent().permissions).build(
        task, AgentRole.ORCHESTRATOR, attempt=1
    )
    FileContextStore(sidecar / "contexts").put(context)

    _require_no_coder_start(state, task, 1)


@pytest.mark.parametrize(
    ("role", "attempt", "source_revision"),
    [
        (AgentRole.CODER, 1, BASE),
        (AgentRole.QA, 1, BASE),
        (AgentRole.REVIEWER, 1, BASE),
        (AgentRole.ORCHESTRATOR, 2, BASE),
        (AgentRole.ORCHESTRATOR, 1, "c" * 40),
    ],
)
def test_pre_context_recovery_rejects_other_same_task_contexts(
    tmp_path: Path, role: AgentRole, attempt: int, source_revision: str
) -> None:
    sidecar = tmp_path / "sidecar"
    task = make_task().model_copy(
        update={"repository": str(tmp_path), "base_ref": BASE, "attempts": 1}
    )
    observed = task.model_copy(update={"base_ref": source_revision})
    context = FileContextBuilder(tmp_path, make_agent().permissions).build(
        observed, role, attempt=attempt
    )
    FileContextStore(sidecar / "contexts").put(context)

    with pytest.raises(ValueError, match="非本次编排准备"):
        _require_no_coder_start(sidecar / "state", task, 1)


@pytest.mark.parametrize("record_kind", ["invocation", "route"])
def test_pre_context_recovery_does_not_mask_started_model_records(
    tmp_path: Path, record_kind: str
) -> None:
    sidecar = tmp_path / "sidecar"
    state = sidecar / "state"
    task = make_task().model_copy(
        update={"repository": str(tmp_path), "base_ref": BASE, "attempts": 1}
    )
    context = FileContextBuilder(tmp_path, make_agent().permissions).build(
        task, AgentRole.ORCHESTRATOR, attempt=1
    )
    FileContextStore(sidecar / "contexts").put(context)
    request = _coder_request().model_copy(
        update={
            "task_id": task.id,
            "source_revision": BASE,
            "context_manifest_id": context.context_id,
        }
    )
    if record_kind == "invocation":
        start = DeliveryInvocationStart(
            work_item_id="work_started_coder",
            checkpoint_sequence=2,
            request=request,
            lease_id="lease_started_coder",
            started_at=NOW,
            start_sha256="0" * 64,
        )
        start = start.model_copy(
            update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
        )
        KnowledgeRecordStore(state / "invocations").put(
            "invocation-starts", start.work_item_id, start
        )
        expected = "模型调用开始"
    else:
        result = AgentResult(
            run_id=request.run_id,
            task_id=request.task_id,
            role=request.role,
            attempt=request.attempt,
            source_revision=request.source_revision,
            context_manifest_id=request.context_manifest_id,
            status=AgentRunStatus.FAILED,
            error=AgentFailure(
                code=AgentErrorCode.PROVIDER_ERROR,
                message="provider failed",
                transient=False,
            ),
        )
        route = ModelRouteAttempt.create(
            request=request,
            route_index=1,
            provider="test",
            model="test",
            started_at=NOW,
            completed_at=NOW,
            result=result,
            fallback=False,
        )
        FileModelRouteAttemptStore(model_route_root(sidecar)).append(route)
        expected = "模型路由执行"

    with pytest.raises(ValueError, match=expected):
        _require_no_coder_start(state, task, 1)


def _sources() -> tuple[RecoveryInputSourceRef, ...]:
    return tuple(
        RecoveryInputSourceRef(
            source_id=f"recovery.inherited_patch.{index}" if index < 2 else "recovery.patch",
            uri=f"recovery://source/{index}",
            sha256=hex(index + 1)[2:] * 64,
            bytes=index + 1,
        )
        for index in range(3)
    )


def _fixture() -> tuple[Task, RecoveryInputScheduleDecision, DeliveryResolution]:
    initial = make_task()
    task = Task.model_validate(
        {
            **initial.to_wire(),
            "id": f"task_recovery_{PLAN[:32]}",
            "base_ref": BASE,
            "metadata": {**initial.metadata, "recovery_plan_sha256": PLAN},
        }
    )
    sources = _sources()
    actor = LocalOperatorPrincipal.trusted_local()
    schedule = RecoveryInputScheduleDecision(
        plan_sha256=PLAN,
        task_id=task.id,
        task_intent_sha256=task_intent_sha256(task),
        target_base_revision=BASE,
        authorization_sha256="c" * 64,
        task_record_sha256="d" * 64,
        dispatch_sha256="e" * 64,
        seed_record_sha256="f" * 64,
        work_item_id="work_recovery_input_1",
        disposition_sha256="1" * 64,
        task_revision=2,
        task_snapshot_sha256=digest(task.to_wire()),
        step_sha256="2" * 64,
        original_claim_sha256="3" * 64,
        original_lease_id="lease_recovery_input_1",
        sources=sources,
        engineering_actor=actor,
        authorization_reference=AUTHORIZATION_REFERENCE,
        decided_at=NOW,
        schedule_sha256="0" * 64,
    )
    schedule = schedule.model_copy(update={"schedule_sha256": schedule.recompute_sha256()})
    proof = PreContextRecoveryInputEvidence(
        plan_sha256=PLAN,
        authorization_sha256=schedule.authorization_sha256,
        task_record_sha256=schedule.task_record_sha256,
        dispatch_sha256=schedule.dispatch_sha256,
        seed_record_sha256=schedule.seed_record_sha256,
        source_inventory_sha256=digest(tuple(source.to_wire() for source in sources)),
        original_claim_sha256=schedule.original_claim_sha256,
        original_lease_id=schedule.original_lease_id,
        worktree_head_revision=BASE,
    )
    resolution = DeliveryResolution(
        task_id=task.id,
        work_item_id=schedule.work_item_id,
        expected_disposition_sha256=schedule.disposition_sha256,
        expected_task_intent_sha256=schedule.task_intent_sha256,
        expected_source_revision=BASE,
        expected_checkpoint_sequence=2,
        task_revision=schedule.task_revision,
        task_snapshot_sha256=schedule.task_snapshot_sha256,
        step_sha256=schedule.step_sha256,
        resolution_kind=DeliveryResolutionKind.SCHEDULE_RECOVERY_INPUT,
        proof_sha256="4" * 64,
        operator_principal=actor,
        submitted_at=NOW,
        resolution_sha256="0" * 64,
        authorization_reference=schedule.authorization_reference,
        recovery_input_schedule_sha256=schedule.schedule_sha256,
        pre_context_recovery_input=proof,
    )
    resolution = resolution.model_copy(update={"resolution_sha256": resolution.recompute_sha256()})
    return task, schedule, resolution


def test_schedule_file_requires_consumed_wait_and_exact_complete_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task, schedule, resolution = _fixture()
    records = KnowledgeRecordStore(tmp_path)
    records.put("recovery-input-schedules", PLAN, schedule)
    assert get_recovery_input_schedule(records, PLAN) == schedule
    queue = SimpleNamespace(consumed_recovery_input_resolution=lambda _task_id: None)
    plan = SimpleNamespace(
        plan_sha256=PLAN,
        target_base_revision=BASE,
        validate_integrity=lambda: None,
    )
    dispatch = SimpleNamespace(
        dispatch_sha256=schedule.dispatch_sha256,
        recovery_plan_sha256=PLAN,
        task_id=task.id,
        task=task,
        validate_integrity=lambda: None,
    )
    monkeypatch.setattr(
        "ai_software_engineer.manager.recovery_input_schedule.complete_reapply_source_refs",
        lambda _plan: schedule.sources,
    )
    assert (
        require_consumed_recovery_input_schedule(
            cast("Any", queue), records, cast("Any", plan), cast("Any", dispatch), task
        )
        is None
    )
    queue.consumed_recovery_input_resolution = lambda _task_id: resolution
    assert (
        require_consumed_recovery_input_schedule(
            cast("Any", queue), records, cast("Any", plan), cast("Any", dispatch), task
        )
        == schedule
    )
    changed = resolution.model_copy(update={"recovery_input_schedule_sha256": "9" * 64})
    changed = changed.model_copy(update={"resolution_sha256": changed.recompute_sha256()})
    queue.consumed_recovery_input_resolution = lambda _task_id: changed
    with pytest.raises(ValueError, match="已消费"):
        require_consumed_recovery_input_schedule(
            cast("Any", queue), records, cast("Any", plan), cast("Any", dispatch), task
        )


def test_schedule_requires_human_reference_and_engineering_actor() -> None:
    _, schedule, resolution = _fixture()
    with pytest.raises(ValidationError, match="人工工程授权引用"):
        ResolveDeliveryWait(
            work_item_id=schedule.work_item_id,
            expected_disposition_sha256=schedule.disposition_sha256,
            expected_task_intent_sha256=schedule.task_intent_sha256,
            expected_source_revision=BASE,
            expected_checkpoint_sequence=2,
            resolution_kind=DeliveryResolutionKind.SCHEDULE_RECOVERY_INPUT,
            proof_sha256="4" * 64,
            submitted_at=NOW,
        )
    with pytest.raises(ValidationError, match="独立工程决定"):
        DeliveryResolution.model_validate(
            {**resolution.to_wire(), "recovery_input_schedule_sha256": None}
        )
    with pytest.raises(ValueError, match="digest mismatch"):
        schedule.model_copy(update={"schedule_sha256": "9" * 64}).validate_integrity()


def test_schedule_rejects_incomplete_source_inventory() -> None:
    _, schedule, _ = _fixture()
    with pytest.raises(ValidationError, match="at least 3 items"):
        RecoveryInputScheduleDecision.model_validate(
            {**schedule.to_wire(), "sources": schedule.to_wire()["sources"][:2]}
        )


def test_schedule_and_wait_resolution_static_schemas_match_the_typed_decision() -> None:
    import json

    _, schedule, resolution = _fixture()
    schemas = Path(__file__).parents[2] / "schemas"
    schedule_schema = json.loads(
        (schemas / "recovery-input-schedule.schema.json").read_text(encoding="utf-8")
    )
    wait_schema = json.loads(
        (schemas / "engineering-wait-resolution.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schedule_schema).validate(schedule.to_wire())
    Draft202012Validator(wait_schema).validate(resolution.to_wire())
    bad = resolution.to_wire()
    bad.pop("recovery_input_schedule_sha256")
    with pytest.raises(SchemaValidationError):
        Draft202012Validator(wait_schema).validate(bad)
    bad_reference = resolution.to_wire()
    bad_reference["authorization_reference"] = "web-console-recovery-input:proof_1"
    with pytest.raises(SchemaValidationError):
        Draft202012Validator(wait_schema).validate(bad_reference)


def test_console_schedule_uses_the_claimed_operation_and_blocks_direct_intent() -> None:
    _, _, resolution = _fixture()
    checkpoint_sha256 = "5" * 64
    intent = ResolveDeliveryWaitIntent(
        project_id="project_test",
        delivery_id="delivery_test",
        expected_checkpoint_sha256=checkpoint_sha256,
        work_item_id=resolution.work_item_id,
        expected_disposition_sha256=resolution.expected_disposition_sha256,
        expected_task_intent_sha256=resolution.expected_task_intent_sha256,
        expected_source_revision=resolution.expected_source_revision,
        expected_checkpoint_sequence=resolution.expected_checkpoint_sequence,
        resolution_kind=DeliveryResolutionKind.SCHEDULE_RECOVERY_INPUT,
        proof_sha256=resolution.proof_sha256,
    )

    class _Host:
        command: ResolveDeliveryWait | None = None

        def project_entry(self, project_id: str) -> SimpleNamespace:
            assert project_id == intent.project_id
            return SimpleNamespace(
                status=lambda _delivery_id: SimpleNamespace(
                    checkpoint=SimpleNamespace(checkpoint_sha256=checkpoint_sha256)
                )
            )

        def resolve_delivery_wait(
            self, command: ResolveDeliveryWait, *, project_id: str, delivery_id: str
        ) -> DeliveryResolution:
            assert project_id == intent.project_id and delivery_id == intent.delivery_id
            self.command = command
            return resolution

    host = _Host()
    store = InMemoryConsoleOperationStore("team_test")
    adapter = ManagerConsoleAdapter(cast("Any", host), operation_store=store)
    with pytest.raises(ConsoleCommandRejected, match="当前操作记录"):
        adapter.execute(intent)
    console = ProjectConsole(store=store, executor=adapter)
    submitted = console.submit(intent, idempotency_key="recovery-input-approval")
    completed = console.run_once()
    assert completed is not None and completed.status == "SUCCEEDED"
    assert host.command is not None
    assert host.command.authorization_reference == (
        "web-console-operation:"
        + submitted.operation_id
        + ":"
        + submitted.intent_sha256
        + ":"
        + str(completed.previous_operation_sha256)
    )


def test_consumed_schedule_records_one_human_action_and_orphan_records_none(
    tmp_path: Path,
) -> None:
    task, schedule, resolution = _fixture()
    records = KnowledgeRecordStore(tmp_path / "state" / "delivery-waits")
    records.put("recovery-input-schedules", PLAN, schedule)
    consumed: DeliveryResolution | None = None
    recorder = EngineeringHumanActionRecorder(
        KnowledgeHumanActionRecorder(()),
        tmp_path / "state" / "execution-baselines",
        recovery_input_root=records.root,
        recovery_input_resolution_reader=cast(
            "Any", SimpleNamespace(consumed_recovery_input_resolution=lambda _task_id: consumed)
        ),
    )
    events = InMemoryEvaluationEventStore()
    recorder.record(task, "case_recovery_input_test", events)
    assert events.list_for_case("case_recovery_input_test") == ()
    consumed = resolution
    recorder.record(task, "case_recovery_input_test", events)
    recorder.record(task, "case_recovery_input_test", events)
    actions = events.list_for_case("case_recovery_input_test")
    assert len(actions) == 1 and isinstance(actions[0], HumanActionEvent)
    assert actions[0].action is HumanAction.SUPPLY_EVIDENCE
    assert schedule.authorization_reference in (actions[0].note or "")
    assert actions[0].evidence_uri.endswith(records._name("recovery-input-schedules", PLAN))
