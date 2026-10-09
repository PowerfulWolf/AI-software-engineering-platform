"""Real stop/Git proof, exact engineering decisions and conservative unknown waits."""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, Never, cast

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai_software_engineer.agents.continuation import InterruptionObservation
from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.domain import AgentDefinition, ArtifactKind, Task
from ai_software_engineer.domain.artifact import (
    ArtifactIntegrity,
    ImplementationReportArtifact,
    QaReportArtifact,
)
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryProofMissing,
    DeliveryResolution,
    DeliveryResolutionKind,
    DeliveryWaitHandling,
    DeliveryWaitInvestigation,
    HandleDeliveryWait,
    InspectDeliveryWait,
    ResolveDeliveryWait,
)
from ai_software_engineer.domain.engineering_authority import (
    EngineeringCapability,
    EngineeringPolicy,
    EngineeringScope,
    LocalOperatorPrincipal,
    OperatorDuty,
)
from ai_software_engineer.domain.enums import (
    AgentRole,
    QaCriterionStatus,
    QaReportStatus,
    QaTestStatus,
    TaskStatus,
    WorkItemStatus,
)
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.domain.native_verification import (
    NativeVerificationCapabilityDetail,
    NativeVerificationWaiting,
    NativeVerificationWaitReason,
)
from ai_software_engineer.domain.retry_policy import DeliveryRetryFailure
from ai_software_engineer.execution import CommandTimedOut, SubprocessCommandExecutor
from ai_software_engineer.git import GitWorktreeManager
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.delivery import ProjectDeliveryResult, UnifiedProjectEntryService
from ai_software_engineer.manager.delivery_checkpoint import (
    DeliveryNextAction,
    DeliveryStage,
    DeliveryStageAttempts,
    ProjectDeliveryCheckpoint,
)
from ai_software_engineer.manager.delivery_preflight import (
    DeliveryPreflightCheckpoint,
    DeliveryPreflightObservation,
    DeliveryPreflightReceipt,
    DeliveryPreflightScope,
    inspect_delivery_prerequisites,
)
from ai_software_engineer.manager.delivery_wait import (
    DeliveryWaitRejected,
    DeliveryWaitService,
    _preflight_detail_action,
)
from ai_software_engineer.manager.engineering_authority import EngineeringAuthority
from ai_software_engineer.manager.production_host import TeamHost
from ai_software_engineer.manager.verifier_preparation import VerifierPreparationCheckpoint
from ai_software_engineer.orchestration.continuation_models import ContinuationRejected
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.orchestration.state_machine import build_event
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.store import SqliteTaskRepository
from ai_software_engineer.web_console import (
    ConsoleCommandRejected,
    HandleDeliveryWaitIntent,
    InspectDeliveryWaitIntent,
    ManagerConsoleAdapter,
    ResolveDeliveryWaitIntent,
    TeamConsoleHost,
)
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueArtifactReceipt, QueueClaim, QueuedWorkItem
from ai_software_engineer.work_queue.ports import QueueLeaseLost
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard
from tests.domain.factories import (
    make_agent,
    make_coder_progress_artifact,
    make_implementation_artifact,
    make_plan_artifact,
    make_qa_artifact,
)
from tests.manager.test_native_verification import (
    _PREFIX,
    _fake_ports,
    _Fixture,
    _fixture,
    _interrupt_native_execution,
)
from tests.manager.test_verifier_preparation import _gate, _marker, _Wait
from tests.orchestration.test_native_continuation import NOW, Fixture, Guard


def _handling_policy(native: Fixture, root: Path, *, grant: bool = True) -> None:
    events = native.repository.list_events(native.task.id)
    native.repository.close()
    policy = EngineeringPolicy.bounded_local(
        scope=EngineeringScope(
            team_id=native.scope.team_id,
            project_id=native.scope.project_id,
            repository_id=native.scope.repository_id,
            repository_root=native.task.repository,
        ),
        principal=LocalOperatorPrincipal.trusted_local(),
    )
    if not grant:
        policy = policy.model_copy(
            update={
                "grants": tuple(
                    g
                    for g in policy.grants
                    if g.capability is not EngineeringCapability.DELIVERY_WAIT_RESOLUTION
                )
            }
        )
    native.task = Task.model_validate(
        {**native.task.to_wire(), "engineering_policy": policy.to_wire()}
    )
    native.repository = SqliteTaskRepository(root / "policy-task.sqlite")
    native.repository.create(native.task)
    native.repository.record_attempt(native.task.id, 1)
    for event in events:
        native.repository.append_event(event)


def test_product_handling_unknown_execution_saves_case_without_fake_stop_or_resolution(
    native: Fixture,
    tmp_path: Path,
) -> None:
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    entry = service(native, queue, tmp_path)
    entry.principal = LocalOperatorPrincipal(
        operator_id="product:fixture", duties=(OperatorDuty.PRODUCT,)
    )
    collected: list[str] = []
    entry.fact_collector = lambda task, step, guard: collected.append(task.id)
    command = HandleDeliveryWait.model_validate(queue.command().to_wire())
    before = native.repository.get(native.task.id)
    handling = entry.handle(command)
    assert handling.status == "PLATFORM_ATTENTION"
    assert handling.resolution is None and not handling.manual_resolution_allowed
    assert handling.investigation.missing == (
        DeliveryProofMissing.OUTCOME_UNKNOWN,
        DeliveryProofMissing.STOP_UNRECORDED,
        DeliveryProofMissing.CHECKPOINT_UNAVAILABLE,
    )
    assert "重复调查不会" in handling.recheck_when
    assert "未自动创建修复任务" in handling.user_action
    assert native.repository.get(native.task.id) == before and queue.consumed == []
    assert service(native, queue, tmp_path).records.list(
        "wait-handlings", DeliveryWaitHandling
    ) == (handling,)
    assert entry.handle(command) == handling
    assert collected == [native.task.id, native.task.id]
    assert len(entry.records.list("wait-handlings", DeliveryWaitHandling)) == 1


def test_handling_real_checkpoint_uses_frozen_policy_without_human_actor_and_replays(
    native: Fixture,
    tmp_path: Path,
) -> None:
    _handling_policy(native, tmp_path)
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    stopped_receipt(native, tmp_path)
    entry = service(native, queue, tmp_path)
    ledger = tmp_path / "authority-ledger"
    ledger.mkdir()
    entry.engineering_authority = EngineeringAuthority(ledger)
    entry.principal = LocalOperatorPrincipal(
        operator_id="product:fixture", duties=(OperatorDuty.PRODUCT,)
    )
    handling = entry.handle(HandleDeliveryWait.model_validate(queue.command().to_wire()))
    assert handling.status == "RESOLVED" and handling.resolution is not None
    decision = handling.resolution
    assert decision.authorization_source == "organization_engineering_policy"
    assert decision.operator_principal is None and "operator_principal" not in decision.to_wire()
    assert decision.engineering_admission is not None
    assert decision.engineering_admission.capabilities == (
        EngineeringCapability.DELIVERY_WAIT_RESOLUTION,
    )
    assert len(queue.consumed) == 1
    schema = json.loads(Path("schemas/engineering-wait-resolution.schema.json").read_text())
    Draft202012Validator(schema).validate(handling.to_wire())
    Draft202012Validator(schema).validate(decision.to_wire())
    with pytest.raises(ValidationError):
        DeliveryResolution.model_validate(
            {
                **decision.to_wire(),
                "operator_principal": LocalOperatorPrincipal.trusted_local().to_wire(),
            }
        )
    with pytest.raises(ValidationError):
        DeliveryResolution.model_validate({**decision.to_wire(), "proof_sha256": "f" * 64})


def test_upgrade_reuses_a_handling_sealed_before_baseline_extension(
    native: Fixture, tmp_path: Path
) -> None:
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    entry = service(native, queue, tmp_path)
    command = HandleDeliveryWait.model_validate(queue.command().to_wire())
    proof = entry.inspect(queue.command())
    status, summary, user_action, recheck_when = entry._handling_presentation(proof)
    handling = entry._handling_record(
        proof, None, status, summary, user_action, recheck_when, at=NOW
    )
    legacy_facts = proof.model_dump(
        mode="json", exclude={"proof_sha256", "inspected_at", "prerequisite_receipt_sha256"}
    )
    legacy_facts["disposition"]["facts"].pop("execution_baseline_sha256", None)
    legacy_key = digest(
        {
            "binding": command.to_wire(),
            "facts": legacy_facts,
            "manual_resolution_allowed": handling.manual_resolution_allowed,
            "collection_failed": handling.collection_failed,
        }
    )
    entry.records.put("wait-handling-proofs", legacy_key, proof)
    entry.records.put("wait-handlings", legacy_key, handling)
    before = {p.name: p.read_bytes() for p in entry.records.root.glob("*.json")}
    entry.clock = lambda: NOW + timedelta(seconds=5)

    assert entry.handle(command) == handling
    assert queue.consumed == []
    assert entry.records.list("wait-handlings", DeliveryWaitHandling) == (handling,)
    assert {p.name: p.read_bytes() for p in entry.records.root.glob("*.json")} == before


def test_handling_reopens_sealed_decision_after_queue_consumption_before_report_publication(
    native: Fixture,
    tmp_path: Path,
) -> None:
    _handling_policy(native, tmp_path)
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    stopped_receipt(native, tmp_path)
    entry = service(native, queue, tmp_path)
    ledger = tmp_path / "authority-ledger"
    ledger.mkdir()
    entry.engineering_authority = EngineeringAuthority(ledger)
    proof = entry.inspect(queue.command())
    decision = entry._resolve(
        ResolveDeliveryWait.model_validate(
            {
                **queue.command().to_wire(),
                "resolution_kind": DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,
                "proof_sha256": proof.proof_sha256,
                "submitted_at": NOW + timedelta(seconds=2),
            }
        ),
        automatic=True,
    )
    command = HandleDeliveryWait.model_validate(queue.command().to_wire())
    queue.item = queue.item.model_copy(update={"status": WorkItemStatus.CLOSED})
    handling = entry.handle(command)
    assert handling.status == "RESOLVED" and handling.resolution == decision
    assert len(queue.consumed) == 1
    assert entry.handle(command) == handling


def test_handling_pins_proof_across_partial_admission_publication_and_clock_change(
    native: Fixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _handling_policy(native, tmp_path)
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    stopped_receipt(native, tmp_path)
    entry = service(native, queue, tmp_path)
    ledger = tmp_path / "authority-ledger"
    ledger.mkdir()
    entry.engineering_authority = EngineeringAuthority(ledger)
    command = HandleDeliveryWait.model_validate(queue.command().to_wire())
    put = entry.records.put

    def fail_decision(namespace: str, key: str, record: DomainModel) -> DomainModel:
        if namespace == "wait-resolutions":
            raise OSError("fixture local decision publication interrupted")
        return put(namespace, key, record)

    monkeypatch.setattr(entry.records, "put", fail_decision)
    with pytest.raises(OSError, match="interrupted"):
        entry.handle(command)
    assert queue.consumed == []
    original = entry.records.list("wait-handling-proofs", DeliveryWaitInvestigation)[0]
    monkeypatch.setattr(entry.records, "put", put)
    entry.clock = lambda: NOW + timedelta(seconds=5)
    handling = entry.handle(command)
    assert handling.status == "RESOLVED" and handling.resolution is not None
    assert handling.investigation == original
    assert handling.resolution.engineering_admission is not None
    assert handling.resolution.engineering_admission.admission_number == 1
    assert handling.resolution.engineering_admission.admitted_at == NOW + timedelta(seconds=1)
    assert len(queue.consumed) == 1
    assert entry.handle(HandleDeliveryWait.model_validate(queue.command().to_wire())) == handling
    assert len(queue.consumed) == 1


@pytest.mark.parametrize("policy", [False, True])
@pytest.mark.parametrize("engineering_actor", [False, True])
def test_handling_does_not_add_wait_grant_to_legacy_task(
    native: Fixture,
    tmp_path: Path,
    policy: bool,
    engineering_actor: bool,
) -> None:
    if policy:
        _handling_policy(native, tmp_path, grant=False)
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    stopped_receipt(native, tmp_path)
    entry = service(native, queue, tmp_path)
    ledger = tmp_path / "authority-ledger"
    ledger.mkdir()
    entry.engineering_authority = EngineeringAuthority(ledger)
    if not engineering_actor:
        entry.principal = LocalOperatorPrincipal(
            operator_id="product:fixture", duties=(OperatorDuty.PRODUCT,)
        )
    before = native.repository.get(native.task.id)
    handling = entry.handle(HandleDeliveryWait.model_validate(queue.command().to_wire()))
    assert handling.status == "NEEDS_AUTHORIZATION"
    assert not handling.investigation.missing
    assert handling.manual_resolution_allowed is engineering_actor
    assert handling.resolution is None
    assert native.repository.get(native.task.id) == before and queue.consumed == []
    assert list(ledger.iterdir()) == []
    assert not (tmp_path / "delivery-wait-authority").exists()
    if not engineering_actor:
        with pytest.raises(ValueError, match="ENGINEERING"):
            entry.resolve(
                ResolveDeliveryWait.model_validate(
                    {
                        **queue.command().to_wire(),
                        "proof_sha256": handling.investigation.proof_sha256,
                        "resolution_kind": DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,
                        "submitted_at": NOW + timedelta(seconds=2),
                    }
                )
            )


def test_handling_stale_input_and_untrusted_claim_fields_are_rejected(
    native: Fixture,
    tmp_path: Path,
) -> None:
    queue = WaitQueue(native)
    entry = service(native, queue, tmp_path)
    command = HandleDeliveryWait.model_validate(queue.command().to_wire())
    for field in ("process_stopped", "operator_principal", "engineering_admission", "command"):
        with pytest.raises(ValidationError):
            HandleDeliveryWait.model_validate({**command.to_wire(), field: True})
    with pytest.raises(DeliveryWaitRejected, match="已变化"):
        entry.handle(command.model_copy(update={"expected_source_revision": "f" * 40}))
    assert queue.consumed == []
    assert not entry.records.list("wait-handlings", DeliveryWaitHandling)


def test_handling_collector_refusal_preserves_actual_proof_without_authorizing_recovery(
    native: Fixture,
    tmp_path: Path,
) -> None:
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    stopped_receipt(native, tmp_path)
    entry = service(native, queue, tmp_path)

    def rejected(task: Task, step: QueuedRoleStep, guard: WorkerExecutionGuard) -> None:
        raise ContinuationRejected("record integrity rejection")

    entry.fact_collector = rejected
    handling = entry.handle(HandleDeliveryWait.model_validate(queue.command().to_wire()))
    assert handling.status == "PLATFORM_ATTENTION" and handling.resolution is None
    assert not handling.investigation.missing
    assert handling.investigation.permitted_resolutions == (
        DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,
    )
    assert "校验失败" in handling.summary
    assert queue.consumed == []


def test_handling_live_claim_fence_does_not_collect_or_authorize_retry(
    native: Fixture,
    tmp_path: Path,
) -> None:
    queue = WaitQueue(native)
    entry = service(native, queue, tmp_path)

    def active_claim(task: Task, step: QueuedRoleStep, guard: WorkerExecutionGuard) -> None:
        raise QueueLeaseLost("active claim blocks collection")

    entry.fact_collector = active_claim
    handling = entry.handle(HandleDeliveryWait.model_validate(queue.command().to_wire()))
    assert handling.status == "WAITING_EXECUTION" and handling.resolution is None
    assert handling.investigation.missing == (DeliveryProofMissing.PROCESS_LIVE_OR_UNKNOWN,)
    assert queue.consumed == []


def test_preflight_detail_action_is_deduplicated_and_chinese() -> None:
    observation = DeliveryPreflightObservation(
        requirement_id="requirement",
        status="WAIT_ENGINEERING",
        reason_code="CONTROLLED_VERIFICATION_CAPABILITY_REQUIRED",
        native_wait_reason=NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE,
        native_wait_detail=NativeVerificationCapabilityDetail.DOCKER_DAEMON_UNAVAILABLE,
    )
    receipt = cast(
        DeliveryPreflightReceipt,
        SimpleNamespace(observations=(observation, observation)),
    )
    action = _preflight_detail_action(receipt)
    assert action is not None
    assert action.count("Docker 服务进程当前不可用") == 1
    assert "重新调查工程等待" in action


class WaitQueue:
    def __init__(self, fixture: Fixture) -> None:
        task = fixture.repository.get(fixture.task.id)
        sequence = fixture.repository.current_revision(task.id)
        base = fixture.claim.work_item.model_copy(update={"checkpoint_sequence": sequence})
        self.original = fixture.claim.model_copy(update={"work_item": base})
        disposition = decide_delivery_disposition(
            DeliveryFailureFacts(
                task_id=task.id,
                work_item_id=base.id,
                role=base.role,
                classification="EXECUTION_UNCERTAIN",
                source_revision=fixture.request.source_revision,
                task_intent_sha256=task_intent_sha256(task),
                checkpoint_sequence=sequence,
                budget_available=True,
            )
        )
        self.item = QueuedWorkItem.model_validate(
            {
                **base.to_wire(),
                "status": WorkItemStatus.WAITING_HUMAN,
                "wait_disposition": disposition.to_wire(),
                "wait_reason": disposition.reason,
            }
        )
        self.bound = QueuedRoleStep(
            work_item=base,
            allocation_sha256="a" * 64,
            boundary=RoleRunBoundary(
                task.id,
                cast(Literal[AgentRole.CODER, AgentRole.QA, AgentRole.REVIEWER], base.role),
                base.attempt,
                sequence,
                fixture.request.source_revision,
            ),
        )
        self.consumed: list[DeliveryResolution] = []
        self.accepted_artifacts: tuple[AcceptedRoleArtifact, ...] = ()

    def get(self, work_item_id: str) -> QueuedWorkItem:
        assert work_item_id == self.item.id
        return self.item

    def step(self, work_item_id: str) -> QueuedRoleStep:
        assert work_item_id == self.item.id
        return self.bound

    def original_claim(self, lease_id: str) -> QueueClaim:
        assert lease_id == self.original.lease.id
        return self.original

    def accepted(self, task_id: str) -> tuple[AcceptedRoleArtifact, ...]:
        assert task_id == self.item.task_id
        return self.accepted_artifacts

    def consume(self, resolution: DeliveryResolution) -> None:
        if resolution not in self.consumed:
            self.consumed.append(resolution)

    def command(self) -> InspectDeliveryWait:
        assert self.item.wait_disposition is not None
        facts = self.item.wait_disposition.facts
        return InspectDeliveryWait(
            work_item_id=self.item.id,
            expected_disposition_sha256=self.item.wait_disposition.disposition_sha256,
            expected_task_intent_sha256=facts.task_intent_sha256,
            expected_source_revision=facts.source_revision,
            expected_checkpoint_sequence=facts.checkpoint_sequence,
        )


@pytest.fixture
def native(tmp_path: Path) -> Iterator[Fixture]:
    descriptor = os.open(tmp_path / "owner.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fixture = Fixture(tmp_path, Guard(descriptor))
    try:
        yield fixture
    finally:
        fixture.repository.close()
        os.close(descriptor)


def service(native: Fixture, queue: WaitQueue, root: Path) -> DeliveryWaitService:
    return DeliveryWaitService(
        repository=native.repository,
        queue=queue,
        scope=EngineeringScope(
            team_id=native.scope.team_id,
            project_id=native.scope.project_id,
            repository_id=native.scope.repository_id,
            repository_root=native.task.repository,
        ),
        sidecar_state=root,
        git=native.git,
        principal=LocalOperatorPrincipal.trusted_local(),
        consume=queue.consume,
        clock=lambda: NOW + timedelta(seconds=1),
    )


def test_generic_wait_actions_cannot_investigate_or_release_manual_baseline_pause(
    native: Fixture,
    tmp_path: Path,
) -> None:
    queue = WaitQueue(native)
    assert queue.item.wait_disposition is not None
    facts = DeliveryFailureFacts.model_validate(
        {
            **queue.item.wait_disposition.facts.to_wire(),
            "classification": "EXECUTION_BASELINE_PAUSED",
            "execution_baseline_sha256": "b" * 64,
        }
    )
    disposition = decide_delivery_disposition(facts)
    queue.item = queue.item.model_copy(
        update={"wait_disposition": disposition, "wait_reason": disposition.reason}
    )
    before = native.repository.get(native.task.id)
    entry = service(native, queue, tmp_path)
    collected: list[str] = []
    entry.fact_collector = lambda task, step, guard: collected.append(task.id)
    command = queue.command()
    actions = (
        lambda: entry.inspect(command),
        lambda: entry.handle(HandleDeliveryWait.model_validate(command.to_wire())),
        lambda: entry.resolve(
            ResolveDeliveryWait.model_validate(
                {
                    **command.to_wire(),
                    "proof_sha256": "c" * 64,
                    "resolution_kind": "RETRY_FROM_CHECKPOINT",
                    "submitted_at": NOW,
                }
            )
        ),
    )
    for action in actions:
        with pytest.raises(DeliveryWaitRejected, match="主动暂停"):
            action()
    assert not collected and not queue.consumed
    assert native.repository.get(native.task.id) == before


def seal_start(native: Fixture, queue: WaitQueue, root: Path) -> DeliveryInvocationStart:
    start = DeliveryInvocationStart(
        work_item_id=queue.item.id,
        checkpoint_sequence=queue.item.checkpoint_sequence,
        request=native.request,
        lease_id=native.claim.lease.id,
        started_at=NOW,
        start_sha256="0" * 64,
    )
    start = start.model_copy(
        update={
            "start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"})),
        }
    )
    KnowledgeRecordStore(root / "invocations").put("invocation-starts", queue.item.id, start)
    return start


def stopped_receipt(native: Fixture, root: Path, *, provider: bool = False) -> None:
    continuation = native.service()
    before = continuation.started(native.request, native.worktree.path)
    assert before is not None
    (native.worktree.path / "src/app.py").write_text("VALUE = 2\n")
    assert (
        continuation.interrupted(
            native.request,
            native.worktree.path,
            before=before,
            cause="provider_transient" if provider else "local_execution_limit",
            original_error_code=AgentErrorCode.PROVIDER_UNAVAILABLE
            if provider
            else AgentErrorCode.TIMEOUT,
            process_stop=native.stopped(local=not provider),
            output_present=False,
        )
        is InterruptionObservation.CAPTURED
    )
    parent = root / "continuations"
    parent.mkdir(mode=0o700)
    FileContinuationStore.initialize(parent / native.task.id, task_id=native.task.id).put_receipt(
        native.store.get_receipt(native.request.run_id),
    )


def test_unknown_invocation_retains_wait_without_fabricated_stop(
    native: Fixture, tmp_path: Path
) -> None:
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    entry = service(native, queue, tmp_path)
    proof = entry.inspect(queue.command())
    assert DeliveryProofMissing.OUTCOME_UNKNOWN in proof.missing
    assert DeliveryProofMissing.STOP_UNRECORDED in proof.missing
    assert not proof.permitted_resolutions
    with pytest.raises(DeliveryWaitRejected):
        entry.resolve(
            ResolveDeliveryWait.model_validate(
                {
                    **queue.command().to_wire(),
                    "proof_sha256": proof.proof_sha256,
                    "resolution_kind": DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,
                    "submitted_at": NOW + timedelta(seconds=2),
                }
            )
        )
    assert queue.consumed == []
    assert native.repository.current_revision(native.task.id) == 2


def test_real_stop_and_complete_checkpoint_seal_exact_engineering_decision(
    native: Fixture,
    tmp_path: Path,
) -> None:
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    stopped_receipt(native, tmp_path)
    entry = service(native, queue, tmp_path)
    proof = entry.inspect(queue.command())
    assert not proof.missing
    assert proof.permitted_resolutions == (DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,)
    command = ResolveDeliveryWait.model_validate(
        {
            **queue.command().to_wire(),
            "proof_sha256": proof.proof_sha256,
            "resolution_kind": DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,
            "submitted_at": NOW + timedelta(seconds=2),
        }
    )
    decision = entry.resolve(command)
    assert decision.retry_cause == "local_execution_limit"
    assert decision.retry_failure is None
    assert decision.authorization_source == "engineering_operator_decision"
    assert len(queue.consumed) == 1
    reopened = service(native, queue, tmp_path)
    assert reopened.resolve(command) == decision
    assert len(queue.consumed) == 1
    assert native.repository.get(native.task.id).attempts == 1
    assert native.repository.current_revision(native.task.id) == 2


def test_provider_interruption_preserves_transient_failure_cause(
    native: Fixture,
    tmp_path: Path,
) -> None:
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    stopped_receipt(native, tmp_path, provider=True)
    entry = service(native, queue, tmp_path)
    proof = entry.inspect(queue.command())
    decision = entry.resolve(
        ResolveDeliveryWait.model_validate(
            {
                **queue.command().to_wire(),
                "proof_sha256": proof.proof_sha256,
                "resolution_kind": DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,
                "submitted_at": NOW + timedelta(seconds=2),
            }
        )
    )
    assert decision.retry_cause == "provider_transient"
    assert decision.retry_failure is not None
    assert decision.retry_failure.run_id == native.request.run_id
    assert decision.retry_failure.code == "PROVIDER_UNAVAILABLE"


def test_workspace_drift_after_investigation_rejects_without_decision(
    native: Fixture,
    tmp_path: Path,
) -> None:
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    stopped_receipt(native, tmp_path)
    entry = service(native, queue, tmp_path)
    proof = entry.inspect(queue.command())
    (native.worktree.path / "src/app.py").write_text("VALUE = 3\n")
    with pytest.raises(DeliveryWaitRejected, match="变化"):
        entry.resolve(
            ResolveDeliveryWait.model_validate(
                {
                    **queue.command().to_wire(),
                    "proof_sha256": proof.proof_sha256,
                    "resolution_kind": DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,
                    "submitted_at": NOW + timedelta(seconds=2),
                }
            )
        )
    assert not queue.consumed


def test_definitive_result_can_replay_without_new_invocation_or_budget(
    native: Fixture,
    tmp_path: Path,
) -> None:
    queue = WaitQueue(native)
    start = seal_start(native, queue, tmp_path)
    outcome = DeliveryInvocationOutcome(
        start=start, result=_successful_progress(native, queue), outcome_sha256="0" * 64
    )
    outcome = outcome.model_copy(
        update={
            "outcome_sha256": digest(outcome.model_dump(mode="json", exclude={"outcome_sha256"})),
        }
    )
    KnowledgeRecordStore(tmp_path / "invocations").put(
        "invocation-outcomes", queue.item.id, outcome
    )
    proof = service(native, queue, tmp_path).inspect(queue.command())
    assert proof.permitted_resolutions == (DeliveryResolutionKind.REPLAY_RECORDED_RESULT,)
    assert proof.invocation_outcome_sha256 == outcome.outcome_sha256
    assert proof.original_authority is not None
    assert proof.original_authority.assignment == queue.original.assignment
    assert proof.original_authority.request_permissions == native.request.permissions
    assert not proof.missing


def _successful_progress(native: Fixture, queue: WaitQueue) -> AgentResult:
    template = make_coder_progress_artifact()
    artifact = template.model_copy(
        update={
            "task_id": native.task.id,
            "source_revision": native.request.source_revision,
            "context_manifest_id": native.request.context_manifest_id,
            "producer": template.producer.model_copy(
                update={
                    "run_id": native.request.run_id,
                    "agent_id": queue.original.assignment.agent_id,
                }
            ),
        }
    )
    return AgentResult.model_validate(
        {
            **native.result().to_wire(),
            "status": AgentRunStatus.SUCCEEDED,
            "error": None,
            "artifact": artifact,
        }
    )


def _outcome(
    native: Fixture, queue: WaitQueue, root: Path, result: AgentResult
) -> DeliveryInvocationOutcome:
    start = seal_start(native, queue, root)
    outcome = DeliveryInvocationOutcome(start=start, result=result, outcome_sha256="0" * 64)
    outcome = outcome.model_copy(
        update={
            "outcome_sha256": digest(outcome.model_dump(mode="json", exclude={"outcome_sha256"}))
        }
    )
    KnowledgeRecordStore(root / "invocations").put("invocation-outcomes", queue.item.id, outcome)
    return outcome


def _reject_wait(queue: WaitQueue, classification: str = "INVALID_OUTPUT") -> None:
    assert queue.item.wait_disposition is not None
    disposition = decide_delivery_disposition(
        DeliveryFailureFacts.model_validate(
            {**queue.item.wait_disposition.facts.to_wire(), "classification": classification}
        )
    )
    queue.item = queue.item.model_copy(
        update={"wait_disposition": disposition, "wait_reason": disposition.reason}
    )


@pytest.mark.parametrize(
    "rejection", ["invalid_failure", "nontransient_failure", "parent", "supersedes", "platform"]
)
def test_rejected_sealed_outcome_never_advertises_an_endless_result_replay(
    native: Fixture,
    tmp_path: Path,
    rejection: str,
) -> None:
    queue = WaitQueue(native)
    if rejection in {"invalid_failure", "nontransient_failure"}:
        result = native.result().model_copy(
            update={
                "error": AgentFailure(
                    code=(
                        AgentErrorCode.INVALID_OUTPUT
                        if rejection == "invalid_failure"
                        else AgentErrorCode.PROVIDER_ERROR
                    ),
                    message="原输出未通过校验。",
                    transient=False,
                )
            }
        )
    else:
        result = _successful_progress(native, queue)
        assert result.artifact is not None
        if rejection != "platform":
            artifact = result.artifact.model_copy(
                update={"parent_artifact_ids": ("art_unexpected_parent",)}
                if rejection == "parent"
                else {"supersedes": "art_unexpected_previous"}
            )
            result = result.model_copy(update={"artifact": artifact})
        _reject_wait(queue, "PLATFORM_BUG" if rejection == "platform" else "INVALID_OUTPUT")
    outcome = _outcome(native, queue, tmp_path, result)
    entry = service(native, queue, tmp_path)
    proof = entry.inspect(queue.command())
    assert not proof.permitted_resolutions and proof.original_authority is None
    assert DeliveryProofMissing.OUTCOME_REJECTED in proof.missing
    assert DeliveryProofMissing.STOP_UNRECORDED in proof.missing
    assert DeliveryProofMissing.OUTCOME_UNKNOWN not in proof.missing
    assert "不能重复接纳" in proof.next_action
    assert proof.invocation_outcome_sha256 == outcome.outcome_sha256
    reopened = service(native, queue, tmp_path)
    assert reopened.inspect(queue.command()) == proof
    with pytest.raises(DeliveryWaitRejected, match="不能重复接纳"):
        reopened.resolve(
            ResolveDeliveryWait.model_validate(
                {
                    **queue.command().to_wire(),
                    "proof_sha256": proof.proof_sha256,
                    "resolution_kind": DeliveryResolutionKind.REPLAY_RECORDED_RESULT,
                    "submitted_at": NOW + timedelta(seconds=2),
                }
            )
        )
    assert not queue.consumed
    assert (
        KnowledgeRecordStore(tmp_path / "invocations").get(
            "invocation-outcomes", queue.item.id, DeliveryInvocationOutcome
        )
        == outcome
    )


@pytest.mark.parametrize("provider, exhausted", [(False, False), (False, True), (True, False)])
def test_rejected_outcome_uses_only_real_checkpoint_work_allowance_without_provider_refund(
    native: Fixture,
    tmp_path: Path,
    provider: bool,
    exhausted: bool,
) -> None:
    queue = WaitQueue(native)
    _reject_wait(queue)
    _outcome(native, queue, tmp_path, _successful_progress(native, queue))
    stopped_receipt(native, tmp_path, provider=provider)
    if exhausted:
        native.repository.record_attempt(native.task.id, 3)
    entry = service(native, queue, tmp_path)
    proof = entry.inspect(queue.command())
    if provider or exhausted:
        assert not proof.permitted_resolutions
        assert DeliveryProofMissing.OUTCOME_REJECTED in proof.missing
        if exhausted:
            assert DeliveryProofMissing.BUDGET_EXHAUSTED in proof.missing
            assert "执行额度已耗尽" in proof.next_action
        assert not queue.consumed
    else:
        assert proof.permitted_resolutions == (DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,)
        assert not proof.missing
        command = ResolveDeliveryWait.model_validate(
            {
                **queue.command().to_wire(),
                "proof_sha256": proof.proof_sha256,
                "resolution_kind": DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,
                "submitted_at": NOW + timedelta(seconds=2),
            }
        )
        decision = entry.resolve(command)
        assert decision.retry_cause == "local_execution_limit" and decision.retry_failure is None
        assert service(native, queue, tmp_path).resolve(command) == decision
        assert queue.consumed == [decision]


def inconclusive_qa(
    native: Fixture,
    root: Path,
    *,
    provisional: bool = False,
    semantic_drift: bool = False,
    exhaust_provider: bool = False,
) -> tuple[WaitQueue, FileArtifactStore, QaReportArtifact]:
    current = native.repository.get(native.task.id)
    native.repository.append_event(
        build_event(
            current,
            TaskStatus.QA,
            event_id="evt_native_qa_inconclusive",
            reason="candidate ready",
            artifact_ids=("art_impl_001",),
            source_revision=native.task.base_ref,
            occurred_at=current.updated_at + timedelta(seconds=1),
        )
    )
    if exhaust_provider:
        assert current.retry_policy is not None
        for attempt in range(1, current.retry_policy.transient_limit(AgentRole.QA) + 1):
            native.repository.record_retry_failure(
                native.task.id,
                DeliveryRetryFailure(
                    role=AgentRole.QA,
                    attempt=attempt,
                    code="PROVIDER_UNAVAILABLE",
                    run_id=f"run_qa_transient_{attempt}",
                ),
            )
        latest = native.repository.get(native.task.id)
        native.repository.record_attempt(native.task.id, latest.attempts + 1)
    attempt = native.repository.get(native.task.id).attempts
    native.request = native.request.model_copy(
        update={
            "role": AgentRole.QA,
            "attempt": attempt,
            "run_id": "run_qa_inconclusive",
            "output_schema": "schemas/qa-report.schema.json",
            "input_artifact_ids": ("art_impl_001",),
        }
    )
    native.claim = QueueClaim.model_validate(
        {
            **native.claim.to_wire(),
            "work_item": {
                **native.claim.work_item.to_wire(),
                "role": AgentRole.QA,
                "attempt": attempt,
            },
            "assignment": {
                **native.claim.assignment.to_wire(),
                "role": AgentRole.QA,
                "agent_id": "agent_native_qa",
                "attempt": attempt,
            },
            "lease": {**native.claim.lease.to_wire(), "agent_id": "agent_native_qa"},
        }
    )
    queue = WaitQueue(native)
    artifacts = FileArtifactStore(root / "artifacts")
    plan = seal_artifact(
        make_plan_artifact().model_copy(
            update={
                "task_id": native.task.id,
                "source_revision": native.task.base_ref,
            }
        ),
        validated_at=NOW,
    )
    artifacts.put(plan)
    template = make_implementation_artifact()
    candidate = cast(
        ImplementationReportArtifact,
        seal_artifact(
            template.model_copy(
                update={
                    "task_id": native.task.id,
                    "source_revision": native.task.base_ref,
                    "content": template.content.model_copy(
                        update={"commit_sha": native.task.base_ref}
                    ),
                }
            ),
            validated_at=NOW,
        ),
    )
    artifacts.put(candidate)
    template_qa = make_qa_artifact()
    qa = cast(
        QaReportArtifact,
        seal_artifact(
            template_qa.model_copy(
                update={
                    "task_id": native.task.id,
                    "source_revision": native.request.source_revision,
                    "context_manifest_id": native.request.context_manifest_id,
                    "producer": template_qa.producer.model_copy(
                        update={
                            "agent_id": queue.original.assignment.agent_id,
                            "run_id": native.request.run_id,
                        }
                    ),
                    "content": template_qa.content.model_copy(
                        update={
                            "status": QaReportStatus.FAIL,
                            "criteria_results": tuple(
                                item.model_copy(update={"status": QaCriterionStatus.NOT_TESTED})
                                for item in template_qa.content.criteria_results
                            ),
                            "tests_run": tuple(
                                item.model_copy(update={"status": QaTestStatus.ERROR})
                                for item in template_qa.content.tests_run
                            ),
                        }
                    ),
                }
            ),
            validated_at=NOW,
        ),
    )
    artifacts.put(qa)
    returned = qa
    if provisional:
        returned = qa.model_copy(
            update={"integrity": ArtifactIntegrity(sha256="0" * 64, validated=False)}
        )
    if semantic_drift:
        returned = returned.model_copy(
            update={
                "content": returned.content.model_copy(
                    update={"environment": {"diagnostic": "原模型返回的不同验收说明"}}
                )
            }
        )
    queue.accepted_artifacts = tuple(
        AcceptedRoleArtifact(
            task_id=native.task.id,
            work_item_id=queue.item.id,
            lease_id=queue.original.lease.id,
            dispatch_sequence=0,
            checkpoint_sequence=queue.item.checkpoint_sequence,
            run_id=native.request.run_id,
            context_manifest_id=native.request.context_manifest_id,
            source_revision=native.request.source_revision,
            receipt=QueueArtifactReceipt(
                artifact_id=artifact.artifact_id, sha256=artifact.integrity.sha256
            ),
        )
        for artifact in (candidate, qa)
    )
    start = seal_start(native, queue, root)
    outcome = DeliveryInvocationOutcome(
        start=start,
        result=AgentResult(
            run_id=native.request.run_id,
            task_id=native.task.id,
            role=AgentRole.QA,
            attempt=native.request.attempt,
            source_revision=native.request.source_revision,
            context_manifest_id=native.request.context_manifest_id,
            status=AgentRunStatus.SUCCEEDED,
            artifact=returned,
        ),
        outcome_sha256="0" * 64,
    )
    outcome = outcome.model_copy(
        update={
            "outcome_sha256": digest(outcome.model_dump(mode="json", exclude={"outcome_sha256"}))
        }
    )
    KnowledgeRecordStore(root / "invocations").put("invocation-outcomes", queue.item.id, outcome)
    return queue, artifacts, qa


def ready_prerequisites(native: Fixture, queue: WaitQueue) -> DeliveryPreflightReceipt:
    receipt = DeliveryPreflightReceipt(
        scope=DeliveryPreflightScope(
            team_id=native.scope.team_id,
            project_id=native.scope.project_id,
            repository_id=native.scope.repository_id,
            requirement_id=native.scope.requirement_id,
        ),
        task_id=native.task.id,
        source_revision=queue.bound.boundary.source_revision,
        plan_sha256="d" * 64,
        frozen_policy_sha256="e" * 64,
        requirements_sha256="f" * 64,
        observations=(
            DeliveryPreflightObservation(
                requirement_id="qa_verification", status="READY", reason_code="FIXTURE_READY"
            ),
        ),
        status="READY",
        checked_at=NOW,
        receipt_sha256="0" * 64,
    )
    return receipt.model_copy(
        update={
            "receipt_sha256": digest(receipt.model_dump(mode="json", exclude={"receipt_sha256"}))
        }
    )


def test_inconclusive_accepted_qa_requires_fresh_verification_instead_of_replaying_old_fail(
    native: Fixture,
    tmp_path: Path,
) -> None:
    queue, artifacts, qa = inconclusive_qa(native, tmp_path)
    entry = service(native, queue, tmp_path)
    entry.artifacts = artifacts
    entry.prerequisite_collector = lambda task, step: ready_prerequisites(native, queue)
    proof = entry.inspect(queue.command())
    assert proof.permitted_resolutions == (DeliveryResolutionKind.REVERIFY_CANDIDATE,)
    assert proof.verification_retry is not None
    assert proof.verification_retry.previous_qa_artifact_id == qa.artifact_id
    assert proof.verification_retry.candidate_revision == qa.source_revision
    assert proof.verification_retry.budget_source == "frozen_work_attempt"
    decision = entry.resolve(
        ResolveDeliveryWait.model_validate(
            {
                **queue.command().to_wire(),
                "proof_sha256": proof.proof_sha256,
                "resolution_kind": DeliveryResolutionKind.REVERIFY_CANDIDATE,
                "submitted_at": NOW + timedelta(seconds=2),
            }
        )
    )
    assert decision.verification_retry == proof.verification_retry
    assert decision.retry_failure is None and decision.original_authority is None
    assert artifacts.get(qa.artifact_id) == qa


@pytest.mark.parametrize("semantic_drift", [False, True])
def test_provisional_qa_binds_exact_accepted_semantics_excluding_only_store_integrity(
    native: Fixture,
    tmp_path: Path,
    semantic_drift: bool,
) -> None:
    queue, artifacts, qa = inconclusive_qa(
        native, tmp_path, provisional=True, semantic_drift=semantic_drift
    )
    entry = service(native, queue, tmp_path)
    entry.artifacts = artifacts
    entry.prerequisite_collector = lambda task, step: ready_prerequisites(native, queue)
    proof = entry.inspect(queue.command())
    if semantic_drift:
        assert not proof.permitted_resolutions and proof.verification_retry is None
        assert DeliveryProofMissing.VERIFICATION_EVIDENCE_UNAVAILABLE in proof.missing
    else:
        assert proof.permitted_resolutions == (DeliveryResolutionKind.REVERIFY_CANDIDATE,)
        assert proof.verification_retry is not None
        assert proof.verification_retry.previous_qa_sha256 == qa.integrity.sha256
        assert artifacts.get(qa.artifact_id) == qa
    assert not queue.consumed


@pytest.mark.parametrize("ready, accepted", [(False, True), (True, False)])
def test_inconclusive_qa_missing_prerequisites_or_acceptance_has_no_replay_path(
    native: Fixture,
    tmp_path: Path,
    ready: bool,
    accepted: bool,
) -> None:
    queue, artifacts, _ = inconclusive_qa(native, tmp_path)
    entry = service(native, queue, tmp_path)
    entry.artifacts = artifacts
    if ready:
        entry.prerequisite_collector = lambda task, step: ready_prerequisites(native, queue)
    if not accepted:
        queue.accepted_artifacts = ()
    proof = entry.inspect(queue.command())
    assert not proof.permitted_resolutions
    assert (
        DeliveryProofMissing.VERIFICATION_EVIDENCE_UNAVAILABLE
        if ready
        else DeliveryProofMissing.PREREQUISITES_UNVERIFIED
    ) in proof.missing
    assert not queue.consumed


def test_fresh_candidate_verification_does_not_create_work_allowance(
    native: Fixture,
    tmp_path: Path,
) -> None:
    queue, artifacts, _ = inconclusive_qa(native, tmp_path)
    native.repository.record_attempt(native.task.id, 3)
    entry = service(native, queue, tmp_path)
    entry.artifacts = artifacts
    entry.prerequisite_collector = lambda task, step: ready_prerequisites(native, queue)
    proof = entry.inspect(queue.command())
    assert proof.permitted_resolutions == ()
    assert DeliveryProofMissing.BUDGET_EXHAUSTED in proof.missing
    assert not queue.consumed


def test_reverification_uses_remaining_work_after_provider_allowance_is_exhausted(
    native: Fixture,
    tmp_path: Path,
) -> None:
    queue, artifacts, _qa = inconclusive_qa(native, tmp_path, exhaust_provider=True)
    current = native.repository.get(native.task.id)
    assert current.retry_policy is not None
    assert current.transient_failures(AgentRole.QA) == current.retry_policy.transient_limit(
        AgentRole.QA
    )
    assert not current.work_budget_exhausted
    assert queue.item.wait_disposition is not None
    disposition = decide_delivery_disposition(
        queue.item.wait_disposition.facts.model_copy(update={"budget_available": False})
    )
    queue.item = queue.item.model_copy(
        update={"wait_disposition": disposition, "wait_reason": disposition.reason}
    )
    entry = service(native, queue, tmp_path)
    entry.artifacts = artifacts
    entry.prerequisite_collector = lambda task, step: ready_prerequisites(native, queue)
    proof = entry.inspect(queue.command())
    assert proof.permitted_resolutions == (DeliveryResolutionKind.REVERIFY_CANDIDATE,)
    assert not proof.missing and proof.verification_retry is not None
    assert proof.verification_retry.budget_source == "frozen_work_attempt"


def test_product_actor_cannot_submit_stop_claims_or_engineering_decisions(
    native: Fixture,
    tmp_path: Path,
) -> None:
    queue = WaitQueue(native)
    entry = service(native, queue, tmp_path)
    entry.principal = LocalOperatorPrincipal(
        operator_id="product:fixture", duties=(OperatorDuty.PRODUCT,)
    )
    with pytest.raises(ValueError, match="ENGINEERING"):
        entry.inspect(queue.command())
    with pytest.raises(ValidationError):
        InspectDeliveryWait.model_validate({**queue.command().to_wire(), "process_stopped": True})
    host = object.__new__(TeamHost)
    host._operator_principal = entry.principal
    with pytest.raises(ValueError, match="ENGINEERING"):
        host.inspect_delivery_wait(
            queue.command(), project_id="project_test", delivery_id="delivery_test"
        )


def test_claimed_uninvoked_preflight_resumes_after_real_facts_refresh_without_clock_drift(
    native: Fixture,
    tmp_path: Path,
) -> None:
    queue = WaitQueue(native)
    task = native.repository.get(native.task.id)
    count = 0

    def collect(ready: bool) -> DeliveryPreflightReceipt:
        nonlocal count
        count += 1
        status: Literal["READY", "WAIT_ENGINEERING"] = "READY" if ready else "WAIT_ENGINEERING"
        receipt = DeliveryPreflightReceipt(
            scope=DeliveryPreflightScope(
                team_id=native.scope.team_id,
                project_id=native.scope.project_id,
                repository_id=native.scope.repository_id,
                requirement_id=native.scope.requirement_id,
            ),
            task_id=task.id,
            source_revision=native.request.source_revision,
            plan_sha256="d" * 64,
            frozen_policy_sha256="e" * 64,
            requirements_sha256="f" * 64,
            observations=(
                DeliveryPreflightObservation(
                    requirement_id="focused_verification",
                    status=status,
                    reason_code="FIXTURE_READINESS",
                ),
            ),
            status=status,
            checked_at=NOW + timedelta(microseconds=count),
            receipt_sha256="0" * 64,
        )
        return receipt.model_copy(
            update={
                "receipt_sha256": digest(
                    receipt.model_dump(mode="json", exclude={"receipt_sha256"})
                ),
            }
        )

    old = collect(False)
    assert queue.item.wait_disposition is not None
    facts = queue.item.wait_disposition.facts.model_copy(
        update={
            "classification": "ENVIRONMENT_UNAVAILABLE",
            "evidence_ids": ("delivery-preflight://" + old.receipt_sha256,),
        }
    )
    disposition = decide_delivery_disposition(facts)
    queue.item = QueuedWorkItem.model_validate(
        {
            **queue.item.to_wire(),
            "wait_disposition": disposition.to_wire(),
            "wait_reason": disposition.reason,
        }
    )
    records = KnowledgeRecordStore(tmp_path / "delivery-preflight")
    records.put("preflight-receipts", old.receipt_sha256, old)
    marker = DeliveryPreflightCheckpoint(
        work_item_id=queue.item.id,
        lease_id=native.claim.lease.id,
        task_id=task.id,
        task_snapshot_sha256=digest(task.to_wire()),
        checkpoint_sequence=queue.item.checkpoint_sequence,
        source_revision=native.request.source_revision,
        receipt_sha256=old.receipt_sha256,
        checked_at=NOW,
        checkpoint_sha256="0" * 64,
    )
    marker = marker.model_copy(
        update={
            "checkpoint_sha256": digest(
                marker.model_dump(mode="json", exclude={"checkpoint_sha256"})
            ),
        }
    )
    records.put("preflight-checkpoints", queue.item.id + ":" + old.receipt_sha256, marker)
    entry = service(native, queue, tmp_path)
    entry.prerequisite_collector = lambda current, step: collect(
        Path(current.repository, "src/app.py").is_file()
    )
    proof = entry.inspect(queue.command())
    assert proof.permitted_resolutions == (DeliveryResolutionKind.RESUME_UNINVOKED,)
    assert proof.original_run_id is None
    decision = entry.resolve(
        ResolveDeliveryWait.model_validate(
            {
                **queue.command().to_wire(),
                "proof_sha256": proof.proof_sha256,
                "resolution_kind": DeliveryResolutionKind.RESUME_UNINVOKED,
                "submitted_at": NOW + timedelta(seconds=2),
            }
        )
    )
    assert decision.retry_failure is None
    assert len(queue.consumed) == 1
    assert native.repository.get(task.id).attempts == 1


def test_console_engineering_actions_bind_displayed_requirement_and_real_investigation(
    native: Fixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = WaitQueue(native)
    seal_start(native, queue, tmp_path)
    stopped_receipt(native, tmp_path)
    engineering = service(native, queue, tmp_path)
    project_id = "project_console_wait"
    checkpoint = ProjectDeliveryCheckpoint.create(
        delivery_id="delivery_console_wait",
        sequence=1,
        repository_id=native.scope.repository_id,
        repository_root=native.task.repository,
        stage=DeliveryStage.PREPARING,
        stage_attempts=DeliveryStageAttempts(),
        next_action=DeliveryNextAction.PREPARE_PROJECT,
        checkpointed_at=NOW,
    )

    class ConsoleEntry:
        def status(self, delivery_id: str) -> ProjectDeliveryResult:
            assert delivery_id == checkpoint.delivery_id
            return ProjectDeliveryResult(checkpoint=checkpoint)

    class ConsoleHost:
        def project_entry(self, requested_project_id: str) -> UnifiedProjectEntryService:
            assert requested_project_id == project_id
            return cast(UnifiedProjectEntryService, ConsoleEntry())

    host = ConsoleHost()
    adapter = ManagerConsoleAdapter(cast(TeamConsoleHost, host))

    def inspect(
        command: InspectDeliveryWait, *, project_id: str, delivery_id: str
    ) -> DeliveryWaitInvestigation:
        assert project_id == "project_console_wait" and delivery_id == checkpoint.delivery_id
        return engineering.inspect(command)

    def resolve(
        command: ResolveDeliveryWait, *, project_id: str, delivery_id: str
    ) -> DeliveryResolution:
        assert project_id == "project_console_wait" and delivery_id == checkpoint.delivery_id
        return engineering.resolve(command)

    def handle(
        command: HandleDeliveryWait, *, project_id: str, delivery_id: str
    ) -> DeliveryWaitHandling:
        assert project_id == "project_console_wait" and delivery_id == checkpoint.delivery_id
        return engineering.handle(command)

    monkeypatch.setattr(host, "inspect_delivery_wait", inspect, raising=False)
    monkeypatch.setattr(host, "resolve_delivery_wait", resolve, raising=False)
    monkeypatch.setattr(host, "handle_delivery_wait", handle, raising=False)
    common = {
        **queue.command().to_wire(),
        "project_id": project_id,
        "delivery_id": checkpoint.delivery_id,
        "expected_checkpoint_sha256": checkpoint.checkpoint_sha256,
    }
    result = adapter.execute(InspectDeliveryWaitIntent.model_validate(common))
    proof = result.engineering_wait_investigation
    assert proof is not None and proof.permitted_resolutions
    handled = adapter.execute(HandleDeliveryWaitIntent.model_validate(common))
    assert handled.engineering_wait_handling is not None
    assert handled.engineering_wait_handling.status == "NEEDS_AUTHORIZATION"
    assert handled.stage == "ENGINEERING_WAIT_HANDLED" and queue.consumed == []
    with pytest.raises(ConsoleCommandRejected, match="Refresh"):
        adapter.execute(
            HandleDeliveryWaitIntent.model_validate(
                {**common, "expected_checkpoint_sha256": "f" * 64}
            )
        )
    resolved = adapter.execute(
        ResolveDeliveryWaitIntent.model_validate(
            {
                **common,
                "proof_sha256": proof.proof_sha256,
                "resolution_kind": DeliveryResolutionKind.RETRY_FROM_CHECKPOINT,
            }
        )
    )
    assert resolved.engineering_wait_resolution == queue.consumed[0]
    with pytest.raises(ConsoleCommandRejected, match="Refresh"):
        adapter.execute(
            InspectDeliveryWaitIntent.model_validate(
                {
                    **common,
                    "expected_checkpoint_sha256": "f" * 64,
                }
            )
        )


@dataclass(frozen=True)
class _PreparationWaitFixture:
    native: _Fixture
    queue: WaitQueue
    entry: DeliveryWaitService
    marker: VerifierPreparationCheckpoint
    repository: SqliteTaskRepository


@contextmanager
def _native_preparation_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    state: Literal["NOT_STARTED", "FINISHED", "FINISHED_SUCCESS", "UNCERTAIN"],
) -> Iterator[_PreparationWaitFixture]:
    native = _fixture(tmp_path)
    _fake_ports(monkeypatch, native)

    def unavailable(request: AgentRequest) -> Never:
        # A genuine admitted native binding exists, but no command has begun.
        assert request == native.request and native.bind() is not None
        raise NativeVerificationWaiting(NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE)

    def timeout(executor: SubprocessCommandExecutor, argv: tuple[str, ...]) -> Never:
        raise CommandTimedOut(argv, duration_ms=1000)

    def completed_before_model(request: AgentRequest) -> Never:
        native.registry.prepare_verifier(
            request=request,
            workspace_root=native.root,
            guard=native.guard,
        )
        raise NativeVerificationWaiting(NativeVerificationWaitReason.FACTS_CHANGED)

    gate, delegate, _failure, records = _gate(
        native,
        tmp_path,
        prepare=(
            unavailable
            if state == "NOT_STARTED"
            else completed_before_model
            if state == "FINISHED_SUCCESS"
            else None
        ),
    )
    if state == "FINISHED":
        monkeypatch.setattr(SubprocessCommandExecutor, "run", timeout)
    elif state == "UNCERTAIN":
        monkeypatch.setattr(
            _PREFIX + "execute_python_mysql_verification",
            _interrupt_native_execution(tmp_path),
        )
        with pytest.raises(KeyboardInterrupt):
            gate.prepare(native.request)
    with pytest.raises(_Wait):
        gate.prepare(native.request)
    assert delegate.calls == 0
    marker = _marker(records)
    assert marker.observation.native_execution_state == (
        "FINISHED" if state == "FINISHED_SUCCESS" else state
    )

    # SQLite stores the real native-role fixture snapshot; the collector and native
    # observer both read durable records. Only queue persistence and low OS/Docker
    # ports are replaced in this non-MySQL contract test.
    repository = SqliteTaskRepository(tmp_path / "sidecar/state/tasks.sqlite")
    repository.create(native.task)
    queue = object.__new__(WaitQueue)
    queue.original = native.claim
    facts = DeliveryFailureFacts(
        task_id=native.task.id,
        work_item_id=native.claim.work_item.id,
        role=native.request.role,
        classification=(
            "EXECUTION_UNCERTAIN"
            if state == "UNCERTAIN"
            else "ENGINEERING_AUTHORIZATION"
            if state == "FINISHED_SUCCESS"
            else "ENVIRONMENT_UNAVAILABLE"
        ),
        source_revision=native.request.source_revision,
        task_intent_sha256=task_intent_sha256(native.task),
        checkpoint_sequence=native.claim.work_item.checkpoint_sequence,
        budget_available=True,
        evidence_ids=("verifier-preparation://" + marker.checkpoint_sha256,),
    )
    disposition = decide_delivery_disposition(facts)
    queue.item = QueuedWorkItem.model_validate(
        {
            **native.claim.work_item.to_wire(),
            "status": WorkItemStatus.WAITING_HUMAN,
            "wait_disposition": disposition.to_wire(),
            "wait_reason": disposition.reason,
        }
    )
    queue.bound = QueuedRoleStep(
        work_item=native.claim.work_item,
        allocation_sha256="a" * 64,
        boundary=RoleRunBoundary(
            native.task.id,
            AgentRole.QA,
            native.request.attempt,
            native.claim.work_item.checkpoint_sequence,
            native.request.source_revision,
        ),
    )
    queue.consumed = []
    queue.accepted_artifacts = ()
    scope = native.registry.scope
    entry = DeliveryWaitService(
        repository=repository,
        queue=queue,
        scope=EngineeringScope(
            team_id=scope.team_id,
            project_id=scope.project_id,
            repository_id=scope.repository_id,
            repository_root=native.task.repository,
        ),
        sidecar_state=tmp_path / "sidecar/state",
        git=GitWorktreeManager(Path(native.task.repository), tmp_path / "unused-managed-worktrees"),
        principal=LocalOperatorPrincipal.trusted_local(),
        consume=queue.consume,
        clock=lambda: NOW + timedelta(seconds=1),
    )
    coder = make_agent().model_copy(update={"permissions": native.request.permissions})
    qa = AgentDefinition.model_validate(
        {
            **coder.to_wire(),
            "id": native.claim.assignment.agent_id,
            "role": AgentRole.QA,
            "input_artifacts": [ArtifactKind.PLAN, ArtifactKind.IMPLEMENTATION_REPORT],
            "output_artifacts": [ArtifactKind.QA_REPORT],
        }
    )
    assert native.plan.content.verification_requirements is not None

    def collect(current: Task, step: QueuedRoleStep) -> DeliveryPreflightReceipt:
        # Re-discovery is read-only: it cannot execute the candidate's failing body.
        capabilities = native.registry.discover(
            current,
            native.plan,
            scope,
            source_revision=step.boundary.source_revision,
        )
        assert native.plan.content.verification_requirements is not None
        return inspect_delivery_prerequisites(
            scope=scope,
            task=current,
            plan_sha256=native.plan.integrity.sha256,
            requirements=native.plan.content.verification_requirements,
            definitions={AgentRole.CODER: coder, AgentRole.QA: qa},
            route_kinds={AgentRole.QA: "codex_cli"},
            environment={"PATH": "/usr/bin:/bin"},
            controlled_capabilities=capabilities,
            checked_at=NOW,
            source_revision=step.boundary.source_revision,
        )

    entry.prerequisite_collector = collect
    try:
        yield _PreparationWaitFixture(native, queue, entry, marker, repository)
    finally:
        repository.close()


def _resolve_preparation(
    fixture: _PreparationWaitFixture,
    proof: DeliveryWaitInvestigation,
) -> DeliveryResolution:
    assert len(proof.permitted_resolutions) == 1
    return fixture.entry.resolve(
        ResolveDeliveryWait.model_validate(
            {
                **fixture.queue.command().to_wire(),
                "proof_sha256": proof.proof_sha256,
                "resolution_kind": proof.permitted_resolutions[0],
                "submitted_at": NOW + timedelta(seconds=2),
            }
        )
    )


def test_native_preparation_unstarted_resolves_only_from_original_claim_and_current_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _native_preparation_wait(tmp_path, monkeypatch, state="NOT_STARTED") as fixture:
        before = fixture.repository.get(fixture.native.task.id)
        proof = fixture.entry.inspect(fixture.queue.command())
        assert proof.permitted_resolutions == (DeliveryResolutionKind.RESUME_UNINVOKED,)
        assert not proof.missing and proof.invocation_start_sha256 is None
        assert proof.original_run_id == fixture.native.request.run_id
        assert proof.verifier_preparation is not None
        assert proof.verifier_preparation.native_execution_state == "NOT_STARTED"
        assert proof.verifier_preparation.native_binding_plan_sha256
        assert proof.verifier_preparation.budget_source is None
        resolution = _resolve_preparation(fixture, proof)
        assert resolution.verifier_preparation == proof.verifier_preparation
        assert resolution.retry_failure is None and resolution.retry_cause is None
        assert fixture.repository.get(before.id) == before
        assert fixture.queue.consumed == [resolution]
        assert _resolve_preparation(fixture, proof) == resolution
        assert fixture.queue.consumed == [resolution]


def test_native_preparation_finished_failure_uses_frozen_work_and_never_provider_transient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _native_preparation_wait(tmp_path, monkeypatch, state="FINISHED") as fixture:
        proof = fixture.entry.inspect(fixture.queue.command())
        assert proof.permitted_resolutions == (DeliveryResolutionKind.RETRY_VERIFIER_PREPARATION,)
        assert not proof.missing and proof.invocation_start_sha256 is None
        assert proof.verifier_preparation is not None
        evidence = proof.verifier_preparation
        assert evidence.native_execution_state == "FINISHED"
        assert evidence.native_failure_code == "COMMAND_TIMEOUT"
        assert evidence.native_started_sha256 and evidence.native_finished_sha256
        assert evidence.budget_source == "frozen_work_attempt"
        resolution = _resolve_preparation(fixture, proof)
        assert resolution.verifier_preparation == evidence
        assert resolution.retry_failure is None and resolution.retry_cause is None
        assert fixture.queue.consumed == [resolution]
        # Collector/operator record a decision; only the queue transaction consumes
        # the work allowance. This non-MySQL fixture does not emulate that mutation.
        assert fixture.repository.get(fixture.native.task.id).attempts == 1


def test_native_started_without_final_has_no_uninvoked_or_retry_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _native_preparation_wait(tmp_path, monkeypatch, state="UNCERTAIN") as fixture:
        proof = fixture.entry.inspect(fixture.queue.command())
        assert DeliveryProofMissing.NATIVE_EXECUTION_UNCERTAIN in proof.missing
        assert not proof.permitted_resolutions and proof.verifier_preparation is None
        for kind in (
            DeliveryResolutionKind.RESUME_UNINVOKED,
            DeliveryResolutionKind.RETRY_VERIFIER_PREPARATION,
        ):
            with pytest.raises(DeliveryWaitRejected):
                fixture.entry.resolve(
                    ResolveDeliveryWait.model_validate(
                        {
                            **fixture.queue.command().to_wire(),
                            "proof_sha256": proof.proof_sha256,
                            "resolution_kind": kind,
                            "submitted_at": NOW + timedelta(seconds=2),
                        }
                    )
                )
        assert fixture.queue.consumed == []


@pytest.mark.parametrize("change", ["marker", "original_claim", "native_records", "intent"])
def test_native_preparation_marker_or_actual_fact_drift_cannot_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    with _native_preparation_wait(tmp_path, monkeypatch, state="NOT_STARTED") as fixture:
        proof = fixture.entry.inspect(fixture.queue.command())
        assert proof.permitted_resolutions
        if change == "marker":
            marker = fixture.marker.model_copy(update={"task_snapshot_sha256": "f" * 64})
            marker = marker.model_copy(update={"checkpoint_sha256": marker.recompute_sha256()})
            records = KnowledgeRecordStore(tmp_path / "sidecar/state/delivery-preflight")
            records.put("verifier-preparations", marker.checkpoint_sha256, marker)
            assert fixture.queue.item.wait_disposition is not None
            facts = fixture.queue.item.wait_disposition.facts.model_copy(
                update={
                    "evidence_ids": ("verifier-preparation://" + marker.checkpoint_sha256,),
                }
            )
            disposition = decide_delivery_disposition(facts)
            fixture.queue.item = fixture.queue.item.model_copy(
                update={
                    "wait_disposition": disposition,
                    "wait_reason": disposition.reason,
                }
            )
        elif change == "original_claim":
            fixture.queue.original = fixture.queue.original.model_copy(
                update={
                    "work_item": fixture.queue.original.work_item.model_copy(update={"attempt": 2}),
                }
            )
        elif change == "native_records":
            provider = fixture.native.bind()
            assert provider is not None
            (provider._store.root / "binding.json").write_text('{"not": "sealed authority"}')
        else:
            records = KnowledgeRecordStore(tmp_path / "sidecar/state/delivery-preflight")
            key = (
                f"{fixture.marker.work_item_id}:{fixture.marker.checkpoint_sequence}:"
                f"{fixture.marker.dispatch_sequence}"
            )
            (records.root / records._name("verifier-preparation-intents", key)).unlink()
        current = fixture.entry.inspect(fixture.queue.command())
        assert not current.permitted_resolutions
        assert (
            DeliveryProofMissing.NATIVE_EXECUTION_UNCERTAIN
            if change == "native_records"
            else DeliveryProofMissing.VERIFIER_PREPARATION_UNAVAILABLE
        ) in current.missing
        assert not fixture.queue.consumed
        if change != "marker":
            with pytest.raises(DeliveryWaitRejected):
                _resolve_preparation(fixture, proof)


def test_reclaimed_preparation_wait_verifies_both_original_and_wait_claim_generations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _native_preparation_wait(tmp_path, monkeypatch, state="NOT_STARTED") as fixture:
        original = fixture.queue.original
        waiting_claim = QueueClaim.model_validate(
            {
                **original.to_wire(),
                "work_item": {
                    **original.work_item.to_wire(),
                    "dispatch_sequence": original.work_item.dispatch_sequence + 1,
                },
                "lease": {
                    **original.lease.to_wire(),
                    "id": "lease_reclaimed_preparation",
                    "assignment_id": "assignment_reclaimed_preparation",
                },
                "assignment": {
                    **original.assignment.to_wire(),
                    "id": "assignment_reclaimed_preparation",
                    "lease_id": "lease_reclaimed_preparation",
                },
            }
        )
        claims = {original.lease.id: original, waiting_claim.lease.id: waiting_claim}
        monkeypatch.setattr(fixture.queue, "original_claim", claims.__getitem__)
        marker = fixture.marker.model_copy(
            update={
                "wait_lease_id": waiting_claim.lease.id,
                "wait_dispatch_sequence": waiting_claim.work_item.dispatch_sequence,
            }
        )
        marker = marker.model_copy(update={"checkpoint_sha256": marker.recompute_sha256()})
        records = KnowledgeRecordStore(tmp_path / "sidecar/state/delivery-preflight")
        records.put("verifier-preparations", marker.checkpoint_sha256, marker)
        assert fixture.queue.item.wait_disposition is not None
        disposition = decide_delivery_disposition(
            fixture.queue.item.wait_disposition.facts.model_copy(
                update={"evidence_ids": ("verifier-preparation://" + marker.checkpoint_sha256,)}
            )
        )
        fixture.queue.item = fixture.queue.item.model_copy(
            update={
                "dispatch_sequence": waiting_claim.work_item.dispatch_sequence,
                "wait_disposition": disposition,
                "wait_reason": disposition.reason,
            }
        )
        proof = fixture.entry.inspect(fixture.queue.command())
        assert proof.permitted_resolutions == (DeliveryResolutionKind.RESUME_UNINVOKED,)
        assert proof.verifier_preparation is not None
        assert proof.verifier_preparation.previous_run_id == fixture.marker.run_id
        claims[waiting_claim.lease.id] = waiting_claim.model_copy(
            update={
                "work_item": waiting_claim.work_item.model_copy(
                    update={"dispatch_sequence": waiting_claim.work_item.dispatch_sequence + 1}
                )
            }
        )
        changed = fixture.entry.inspect(fixture.queue.command())
        assert not changed.permitted_resolutions
        assert DeliveryProofMissing.VERIFIER_PREPARATION_UNAVAILABLE in changed.missing
        assert fixture.repository.get(fixture.native.task.id).attempts == 1


def test_native_preparation_finished_success_before_model_requires_new_work_without_fake_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _native_preparation_wait(tmp_path, monkeypatch, state="FINISHED_SUCCESS") as fixture:
        proof = fixture.entry.inspect(fixture.queue.command())
        assert proof.permitted_resolutions == (DeliveryResolutionKind.RETRY_VERIFIER_PREPARATION,)
        assert not proof.missing and proof.invocation_start_sha256 is None
        assert proof.verifier_preparation is not None
        evidence = proof.verifier_preparation
        assert evidence.native_execution_state == "FINISHED"
        assert evidence.native_failure_code is None
        assert evidence.native_started_sha256 and evidence.native_finished_sha256
        assert evidence.budget_source == "frozen_work_attempt"
        resolution = _resolve_preparation(fixture, proof)
        assert resolution.verifier_preparation == evidence
        assert resolution.retry_failure is None and resolution.retry_cause is None
        assert fixture.queue.consumed == [resolution]
