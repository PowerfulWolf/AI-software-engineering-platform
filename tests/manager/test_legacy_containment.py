"""Legacy rescue keeps UNKNOWN honest and requires independently observed OS containment."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from subprocess import SubprocessError

import pytest

from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, ModelRouteAttempt
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.domain import AgentRole, Task, WorkItemStatus
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.execution_baseline import BaselinePurpose
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_models import BaselineExecutionReservation
from ai_software_engineer.manager.baseline_production import (
    BaselineExecuteCommand,
    BaselineProposeCommand,
    ProductionBaselineFactCollector,
)
from ai_software_engineer.manager.legacy_containment import (
    LegacyExecutionContainment,
    LocalBootObservation,
    TrustedLocalBootObserver,
)
from ai_software_engineer.manager.legacy_local_execution import (
    LegacyLocalExecutionSurvey,
    LegacyRescuePrerequisiteError,
)
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.recovery.models import digest
from ai_software_engineer.work_queue.execution_store import MySqlRoleQueue, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import DeliveryInvocationStart
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from tests.manager.test_execution_baseline import setup
from tests.manager.test_execution_baseline_invocations import _allocation, _claim
from tests.manager.test_execution_baseline_reservation import reservation_fixture

STARTED = datetime(2026, 10, 6, 14, 30, tzinfo=UTC)
BOOT = LocalBootObservation(
    machine_sha256="a" * 64,
    boot_session_sha256="b" * 64,
    booted_at=STARTED + timedelta(days=1),
)


def legacy_fixture(
    tmp_path: Path,
) -> tuple[ProductionBaselineFactCollector, Task, QueuedWorkItem, LegacyExecutionContainment]:
    collector, task, item, receipt = reservation_fixture(tmp_path)
    task = task.model_copy(update={"id": receipt.request.task_id})
    item = item.model_copy(update={"repository_scopes": (task.repository,)})
    # Use a separate temporary root rather than rewriting an immutable old start.
    collector.state = tmp_path / "legacy"
    records = KnowledgeRecordStore(collector.state / "invocations")
    start = DeliveryInvocationStart(
        work_item_id=item.id,
        checkpoint_sequence=item.checkpoint_sequence,
        request=receipt.request,
        lease_id=receipt.claim_lease_id,
        started_at=STARTED,
        start_sha256="0" * 64,
    )
    start = start.model_copy(
        update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
    )
    records.put("invocation-starts", item.id, start)
    claim = _claim(item, start.lease_id)
    claim = claim.model_copy(
        update={
            "model_selection": claim.model_selection.model_copy(update={"route_kind": "codex_cli"})
        }
    )
    collector.scope = EngineeringScope(
        team_id="team_baseline",
        project_id="project_baseline",
        repository_id=item.repository_id,
        repository_root=task.repository,
    )
    collector.requirement_id = "delivery_baseline"
    collector.allocation = _allocation(task, "d" * 64)
    collector.permissions = receipt.request.permissions
    collector.purpose = BaselinePurpose.LEGACY_WORKSPACE_RESCUE
    collector.route_root = None
    collector.inputs = None  # type: ignore[assignment]
    item = item.model_copy(
        update={
            "status": WorkItemStatus.WAITING_HUMAN,
            "wait_reason": "unknown original execution",
            "wait_disposition": decide_delivery_disposition(
                DeliveryFailureFacts(
                    task_id=task.id,
                    work_item_id=item.id,
                    role=AgentRole.CODER,
                    classification="EXECUTION_UNCERTAIN",
                    source_revision=start.request.source_revision,
                    task_intent_sha256=task_intent_sha256(task),
                    checkpoint_sequence=item.checkpoint_sequence,
                    budget_available=True,
                )
            ),
        }
    )
    step = QueuedRoleStep(
        work_item=item,
        boundary=RoleRunBoundary(
            task.id,
            AgentRole.CODER,
            item.attempt,
            item.checkpoint_sequence,
            start.request.source_revision,
        ),
        allocation_sha256=collector.allocation.dispatch_sha256,
    )

    class Queue(MySqlRoleQueue):
        def __init__(self) -> None:
            pass

        def original_claim(self, lease_id: str) -> QueueClaim:
            assert lease_id == claim.lease.id
            return claim

        def claims_for_work_item(self, identity: str) -> tuple[QueueClaim, ...]:
            assert identity == item.id
            return (claim,)

        def step_for_invocation(self, identity: str, baseline: str | None) -> QueuedRoleStep:
            assert identity == item.id and baseline is None
            return step

    class Observer:
        def observe(self) -> LocalBootObservation:
            return BOOT

    collector.queue, collector.observer = Queue(), Observer()
    containment = collector._legacy_containment(task, item)
    return collector, task, item, containment


def test_exact_new_observation_preserves_original_unknown_and_complete_claim(
    tmp_path: Path,
) -> None:
    collector, task, item, containment = legacy_fixture(tmp_path)
    containment.validate_integrity()
    assert containment.original_claim.lease.id == containment.original_start.lease_id
    assert "process_stop" not in containment.to_wire()
    before = {path: path.read_bytes() for path in collector.state.rglob("*.json")}
    (proof,) = collector._invocations(task, (item,), (), (), legacy=containment)
    assert proof.proof_kind == "legacy_execution_contained"
    assert proof.legacy_containment == containment
    assert proof.outcome_sha256 is None and proof.interruption_receipt_sha256 is None
    assert before == {path: path.read_bytes() for path in collector.state.rglob("*.json")}


def test_legacy_unknown_consumes_next_work_and_cannot_refund_or_infer_already_reserved(
    tmp_path: Path,
) -> None:
    collector, task, item, containment = legacy_fixture(tmp_path)
    reservation = collector._reservation(task, item, (), legacy=containment)
    assert reservation.retry_cause == "legacy_execution_abandoned"
    assert reservation.next_execution_attempt == task.attempts + 1
    assert reservation.retry_failure is None and not reservation.reservation_already_applied
    assert reservation.current_invocation_outcome_sha256 is None
    assert reservation.interruption_receipt_sha256 is None
    with pytest.raises(ValueError, match="工作额度"):
        collector._reservation(
            task.model_copy(update={"attempts": 2}), item, (), legacy=containment
        )
    with pytest.raises(ValueError, match="consume new work"):
        BaselineExecutionReservation.model_validate(
            {**reservation.to_wire(), "reservation_already_applied": True}
        )


@pytest.mark.parametrize("booted_at", [STARTED, STARTED - timedelta(seconds=1)])
def test_service_restart_expired_lease_and_old_boot_cannot_contain_legacy_run(
    tmp_path: Path, booted_at: datetime
) -> None:
    _, _, _, containment = legacy_fixture(tmp_path)
    values = containment.to_wire()
    values["boot"] = BOOT.model_copy(update={"booted_at": booted_at}).to_wire()
    with pytest.raises(ValueError, match="整台电脑"):
        LegacyExecutionContainment.model_validate(values)


@pytest.mark.parametrize("route", [None, "responses"])
def test_non_native_or_unrecorded_route_cannot_use_boot_containment(
    tmp_path: Path, route: str | None
) -> None:
    _, _, _, containment = legacy_fixture(tmp_path)
    claim = containment.original_claim
    claim = claim.model_copy(
        update={"model_selection": claim.model_selection.model_copy(update={"route_kind": route})}
    )
    with pytest.raises(ValueError, match="本机 Coder"):
        LegacyExecutionContainment.create(
            **containment.model_dump(
                mode="python", exclude={"original_claim", "containment_sha256"}
            ),
            original_claim=claim,
        )


def test_mac_observer_uses_stable_hashed_identity_without_raw_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ai_software_engineer.manager.legacy_containment.sys.platform", "darwin")
    machine = "00000000-0000-4000-8000-000000000001"
    session = "00000000-0000-4000-8000-000000000002"
    calls: list[tuple[str, ...]] = []

    class Observer(TrustedLocalBootObserver):
        def _command(self, argv: tuple[str, ...]) -> str:
            calls.append(argv)
            if argv[-1] == "kern.bootsessionuuid":
                return session
            if argv[-1] == "kern.boottime":
                return "{ sec = 1750000000, usec = 0 }"
            return f'"IOPlatformUUID" = "{machine}"'

    observer = Observer()
    first, second = observer.observe(), observer.observe()
    assert first.same_boot(second) and first == second
    assert machine not in first.model_dump_json() and session not in first.model_dump_json()
    assert calls[0] == ("/usr/sbin/sysctl", "-n", "kern.bootsessionuuid")
    assert first.booted_at == datetime.fromtimestamp(1750000000, UTC)
    assert not first.same_boot(first.model_copy(update={"boot_session_sha256": "c" * 64}))


def test_unreadable_or_ambiguous_os_identity_returns_clear_prerequisite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ai_software_engineer.manager.legacy_containment.sys.platform", "darwin")

    class Observer(TrustedLocalBootObserver):
        def _command(self, argv: tuple[str, ...]) -> str:
            return "invalid OS identity, no user-controlled fallback"

    with pytest.raises(ValueError, match="仅重启 ASE 服务不能"):
        Observer().observe()


def test_linux_observer_reads_only_bounded_fixed_os_identity_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ai_software_engineer.manager.legacy_containment.sys.platform", "linux")
    paths: list[str] = []

    class Observer(TrustedLocalBootObserver):
        def _file(self, path: str) -> str:
            paths.append(path)
            return {
                "/etc/machine-id": "0" * 32,
                "/proc/sys/kernel/random/boot_id": "00000000-0000-4000-8000-000000000002",
                "/proc/stat": "cpu 1 2 3\nbtime 1750000000\nprocesses 12",
            }[path]

        def _command(self, argv: tuple[str, ...]) -> str:
            raise AssertionError("Linux uses its bounded native OS files")

    observation = Observer().observe()
    assert observation.booted_at == datetime.fromtimestamp(1750000000, UTC)
    assert paths == ["/etc/machine-id", "/proc/sys/kernel/random/boot_id", "/proc/stat"]
    assert "0" * 32 not in observation.model_dump_json()


@pytest.mark.parametrize("problem", ["start_digest", "claim_identity", "claim_route"])
def test_containment_rejects_altered_original_run_claim_or_digest(
    tmp_path: Path,
    problem: str,
) -> None:
    _, _, _, containment = legacy_fixture(tmp_path)
    values = containment.model_dump(mode="python", exclude={"containment_sha256"})
    if problem == "start_digest":
        values["original_start"] = containment.original_start.model_copy(
            update={"start_sha256": "f" * 64}
        )
    else:
        claim = containment.original_claim
        if problem == "claim_identity":
            values["original_claim"] = claim.model_copy(
                update={
                    "work_item": claim.work_item.model_copy(update={"id": "work_other_original"})
                }
            )
        else:
            values["original_claim"] = claim.model_copy(
                update={
                    "model_selection": claim.model_selection.model_copy(update={"route_kind": None})
                }
            )
    with pytest.raises(ValueError):
        LegacyExecutionContainment.create(**values)


def test_default_source_purpose_and_confirmation_keep_old_command_wire_bytes(
    tmp_path: Path,
) -> None:
    f = setup(tmp_path)
    plan = f.service.propose(f.target)
    assert "purpose" not in plan.to_wire()
    assert "legacy_containment" not in plan.facts.to_wire()
    assert plan.plan_sha256 == digest(plan.model_dump(mode="json", exclude={"plan_sha256"}))
    command = BaselineProposeCommand(
        delivery_id="delivery_legacy_fixture",
        task_id=plan.facts.task.id,
        expected_task_intent_sha256=task_intent_sha256(plan.facts.task),
        expected_task_revision=plan.facts.task_revision,
        expected_work_item_id=plan.facts.work_item_id,
        expected_source_revision=plan.dirty_capture.source_revision,
        target_base_ref=plan.target_base_ref,
    )
    command.require_plan(plan)
    assert "purpose" not in command.to_wire()
    execute = BaselineExecuteCommand(
        delivery_id=command.delivery_id,
        task_id=command.task_id,
        expected_plan_sha256=plan.plan_sha256,
        reference="fixture legacy wire preservation",
    )
    execute.require_plan(plan)
    assert "confirm_legacy_containment" not in execute.to_wire()
    with pytest.raises(ValueError, match="旧执行救援"):
        execute.model_copy(update={"confirm_legacy_containment": True}).require_plan(plan)


@pytest.mark.parametrize("fallback", [False, True])
def test_saved_final_or_unknown_successor_route_refuses_legacy_abandonment(
    tmp_path: Path,
    fallback: bool,
) -> None:
    collector, task, item, containment = legacy_fixture(tmp_path)
    start = containment.original_start
    result = AgentResult(
        run_id=start.request.run_id,
        task_id=task.id,
        role=AgentRole.CODER,
        attempt=start.request.attempt,
        source_revision=start.request.source_revision,
        context_manifest_id=start.request.context_manifest_id,
        status=AgentRunStatus.FAILED,
        error=AgentFailure(
            code=AgentErrorCode.PROVIDER_UNAVAILABLE, message="fixture failure", transient=True
        ),
    )
    collector.route_root = tmp_path / "model-routes"
    route = ModelRouteAttempt.create(
        request=start.request,
        route_index=1,
        provider="codex",
        model="fixture native",
        route_kind="codex_cli",
        started_at=start.started_at,
        completed_at=start.started_at + timedelta(seconds=1),
        result=result,
        fallback=fallback,
    )
    FileModelRouteAttemptStore(collector.route_root).append(route)
    before = {path: path.read_bytes() for path in collector.state.rglob("*.json")}
    with pytest.raises(ValueError, match="模型切换" if fallback else "封存最终结果"):
        collector._legacy_containment(task, item)
    assert before == {path: path.read_bytes() for path in collector.state.rglob("*.json")}


@pytest.mark.parametrize("kind", ["capture-start", "capture-stop", "receipt"])
def test_existing_original_runner_record_keeps_native_fact_handling_path(
    tmp_path: Path,
    kind: str,
) -> None:
    collector, task, item, containment = legacy_fixture(tmp_path)
    root = collector.state / "continuations" / task.id
    root.mkdir(parents=True)
    marker = root / f"{kind}-{containment.original_start.request.run_id}.json"
    marker.write_text("existing original record must not be overwritten")
    with pytest.raises(ValueError, match="已有现场或停止记录"):
        collector._legacy_containment(task, item)
    assert marker.read_text() == "existing original record must not be overwritten"


def test_local_operator_prerequisite_can_use_the_existing_boot_without_faking_old_stop(
    tmp_path: Path,
) -> None:
    _, _, _, original = legacy_fixture(tmp_path)
    boot = BOOT.model_copy(update={"booted_at": STARTED - timedelta(days=1)})
    survey = LegacyLocalExecutionSurvey.create(
        worktree_path=str(tmp_path.resolve()),
        machine_sha256=boot.machine_sha256,
        boot_session_sha256=boot.boot_session_sha256,
        account_sha256="c" * 64,
        observed_at=STARTED + timedelta(days=1),
        scanner_version="local-execution-v1",
        blockers=(),
    )
    value = LegacyExecutionContainment.create(
        **original.model_dump(mode="python", exclude={"boot", "containment_sha256"}),
        boot=boot,
        method="operator_confirmed_local_stop",
        local_execution_survey=survey,
    )
    value.validate_integrity()
    assert value.method == "operator_confirmed_local_stop"
    assert value.original_start == original.original_start
    assert "process_stop" not in value.to_wire()
    assert "outcome" not in value.to_wire()


@pytest.mark.parametrize("drift", ["missing", "machine", "boot", "observed_before", "digest"])
def test_local_operator_prerequisite_rejects_missing_or_drifted_current_survey(
    tmp_path: Path, drift: str
) -> None:
    _, _, _, original = legacy_fixture(tmp_path)
    values: dict[str, object] = {
        "worktree_path": str(tmp_path.resolve()),
        "machine_sha256": BOOT.machine_sha256,
        "boot_session_sha256": BOOT.boot_session_sha256,
        "account_sha256": "c" * 64,
        "observed_at": STARTED + timedelta(days=1),
        "scanner_version": "local-execution-v1",
        "blockers": (),
    }
    if drift in {"machine", "boot"}:
        values["machine_sha256" if drift == "machine" else "boot_session_sha256"] = "d" * 64
    elif drift == "observed_before":
        values["observed_at"] = STARTED - timedelta(seconds=1)
    survey = LegacyLocalExecutionSurvey.create(**values)
    if drift == "digest":
        survey = survey.model_copy(update={"survey_sha256": "e" * 64})
    with pytest.raises(ValueError):
        LegacyExecutionContainment.create(
            **original.model_dump(mode="python", exclude={"containment_sha256"}),
            method="operator_confirmed_local_stop",
            local_execution_survey=None if drift == "missing" else survey,
        )


def test_os_reboot_default_keeps_exact_old_wire_digest(tmp_path: Path) -> None:
    _, _, _, original = legacy_fixture(tmp_path)
    wire = original.to_wire()
    assert "method" not in wire and "local_execution_survey" not in wire
    assert original.containment_sha256 == digest(
        original.model_dump(mode="json", exclude={"containment_sha256"})
    )
    assert LegacyExecutionContainment.model_validate(wire) == original


@pytest.mark.parametrize("error_type", [ValueError, OSError, SubprocessError])
@pytest.mark.parametrize("failure_read", [0, 1, 2, 3])
def test_os_observation_failure_preserves_initial_and_sealed_recovery_scene(
    tmp_path: Path, error_type: type[Exception], failure_read: int
) -> None:
    collector, task, item, containment = legacy_fixture(tmp_path)
    # Zero represents preparation before any observation is sealed. Later
    # reads exercise both preflight and final rechecks of the same sealed plan.
    if failure_read == 0:
        collector._sealed_legacy_observation = None
    else:
        collector.bind_legacy_observation(containment)
    original_sealed = collector._sealed_legacy_observation
    draft = collector.state / "preserved-draft.txt"
    draft.write_bytes(b"complete retained progress\nno destructive fallback\n")
    before = {path: path.read_bytes() for path in collector.state.rglob("*") if path.is_file()}
    original_task, original_item = task.to_wire(), item.to_wire()

    class Observer:
        calls = 0

        def observe(self) -> LocalBootObservation:
            self.calls += 1
            if self.calls == max(1, failure_read):
                raise error_type("private OS query payload must not be published")
            return BOOT

    observer = Observer()
    collector.observer = observer
    with pytest.raises(LegacyRescuePrerequisiteError) as failure:
        collector._legacy_containment(task, item)
    assert failure.value.code == "LEGACY_LOCAL_OBSERVATION_UNAVAILABLE"
    assert failure.value.safe_message == (
        "平台暂时无法读取可靠的本机身份和启动记录，不能准备旧执行恢复。"  # noqa: RUF001
    )
    assert failure.value.next_action == (
        "请让平台维护者检查当前系统的只读查询能力和权限，修复后重新检查恢复前提；"  # noqa: RUF001
        "不要清空工作区。"
    )
    assert "private OS query payload" not in str(failure.value)
    assert "整机重启" not in failure.value.next_action
    assert "整台电脑" not in failure.value.next_action
    assert observer.calls == max(1, failure_read)
    assert collector._sealed_legacy_observation == original_sealed
    assert task.to_wire() == original_task and item.to_wire() == original_item
    assert before == {
        path: path.read_bytes() for path in collector.state.rglob("*") if path.is_file()
    }
    assert draft.read_bytes() == b"complete retained progress\nno destructive fallback\n"
    assert not (collector.state / "invocations" / "invocation-outcomes").exists()
    assert "process_stop" not in containment.to_wire()
    assert "outcome" not in containment.to_wire()
