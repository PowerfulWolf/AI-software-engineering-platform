"""Pre-model preparation gates preserve real native receipts and exact typed claims."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Never, cast

import pytest

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.domain import AgentRole, Task, TaskStatus
from ai_software_engineer.domain.native_verification import (
    NativeVerificationWaiting,
    NativeVerificationWaitReason,
)
from ai_software_engineer.execution import CommandTimedOut, SubprocessCommandExecutor
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.delivery_preflight import (
    DeliveryPreflightObservation,
    DeliveryPreflightReceipt,
)
from ai_software_engineer.manager.preflight_gate import PreflightInvocationControl
from ai_software_engineer.manager.verifier_preparation import (
    VerifierPreparationCheckpoint,
    VerifierPreparationIntent,
    observe_verifier_preparation,
)
from ai_software_engineer.work_queue.invocation import DurableInvocationControl
from ai_software_engineer.work_queue.worker import (
    WorkerDeliveryFailureControl,
    WorkerExecutionGuard,
)
from tests.manager.test_native_verification import (
    _PREFIX,
    _fake_ports,
    _Fixture,
    _fixture,
    _Guard,
    _interrupt_native_execution,
)


class _Wait(Exception):
    pass


class _Delegate:
    def __init__(self, *, started: bool = False) -> None:
        self.started = started
        self.calls = 0

    def has_started(self, request: AgentRequest) -> bool:
        return self.started

    def prepare(self, request: AgentRequest) -> AgentRequest:
        self.calls += 1
        return request


@dataclass(frozen=True)
class _WaitEvent:
    task: Task
    classification: str
    reason: str
    source_revision: str
    artifact_ids: tuple[str, ...]


class _Failure:
    def __init__(self) -> None:
        self.events: list[_WaitEvent] = []

    def wait(
        self,
        task: Task,
        *,
        classification: str,
        reason: str,
        source_revision: str,
        artifact_ids: tuple[str, ...],
    ) -> Never:
        self.events.append(_WaitEvent(task, classification, reason, source_revision, artifact_ids))
        raise _Wait()


def _gate(
    fixture: _Fixture,
    tmp_path: Path,
    *,
    delegate: _Delegate | None = None,
    prepare: Callable[[AgentRequest], None] | None = None,
    inspect: Callable[[Task, str], DeliveryPreflightReceipt | None] | None = None,
) -> tuple[PreflightInvocationControl, _Delegate, _Failure, KnowledgeRecordStore]:
    fixture.guard.lease = SimpleNamespace(claim=fixture.claim)
    delegate = delegate or _Delegate()
    failure = _Failure()
    records = KnowledgeRecordStore(tmp_path / "sidecar/state/delivery-preflight")

    def prepare_request(request: AgentRequest) -> None:
        fixture.registry.prepare_verifier(
            request=request,
            workspace_root=fixture.root,
            guard=fixture.guard,
        )

    gate = PreflightInvocationControl(
        delegate=cast(DurableInvocationControl, delegate),
        guard=cast(WorkerExecutionGuard, fixture.guard),
        task_reader=lambda: fixture.task,
        inspect=inspect or (lambda *_: None),
        records=records,
        failure_control=cast(WorkerDeliveryFailureControl, failure),
        prepare_verifier=prepare or prepare_request,
        observe_verifier=fixture.registry.observe_verifier_preparation,
    )
    return gate, delegate, failure, records


def _marker(records: KnowledgeRecordStore) -> VerifierPreparationCheckpoint:
    (marker,) = records.list("verifier-preparations", VerifierPreparationCheckpoint)
    marker.validate_integrity()
    return marker


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (NativeVerificationWaitReason.UNSUPPORTED_SWIFT_FILTER, "不能执行指定的 Swift 测试过滤"),
        (NativeVerificationWaitReason.UNSUPPORTED_ENTRYPOINT, "验证入口没有对应的注册执行能力"),
        (NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE, "当前工具或环境不可用"),
        (NativeVerificationWaitReason.NATIVE_UI_PREREQUISITE, "原生界面验证前提尚未满足"),
    ],
)
def test_coder_preflight_retains_specific_chinese_reason_before_any_model_start(
    tmp_path: Path,
    reason: NativeVerificationWaitReason,
    expected: str,
) -> None:
    fixture = _fixture(tmp_path)
    task = fixture.task.model_copy(update={"status": TaskStatus.IMPLEMENTING})
    request = fixture.request.model_copy(
        update={
            "role": AgentRole.CODER,
            "output_schema": "schemas/coder-output.schema.json",
            "input_artifact_ids": (fixture.plan.artifact_id,),
        }
    )
    claim = fixture.claim.model_copy(
        update={
            "work_item": fixture.claim.work_item.model_copy(update={"role": AgentRole.CODER}),
            "assignment": fixture.claim.assignment.model_copy(update={"role": AgentRole.CODER}),
        }
    )
    fixture = replace(fixture, task=task, request=request, claim=claim, guard=_Guard(claim))
    receipt = DeliveryPreflightReceipt(
        scope=fixture.registry.scope,
        task_id=task.id,
        source_revision=task.base_ref,
        plan_sha256="b" * 64,
        frozen_policy_sha256="c" * 64,
        requirements_sha256="d" * 64,
        observations=(
            DeliveryPreflightObservation(
                requirement_id="verify_native",
                status="WAIT_ENGINEERING",
                reason_code="CONTROLLED_VERIFICATION_CAPABILITY_REQUIRED",
                native_wait_reason=reason,
            ),
        ),
        status="WAIT_ENGINEERING",
        checked_at=claim.claimed_at,
        receipt_sha256="0" * 64,
    )
    receipt = receipt.model_copy(
        update={
            "receipt_sha256": digest(
                receipt.model_dump(mode="json", exclude={"receipt_sha256"}),
            )
        }
    )
    gate, delegate, failure, records = _gate(fixture, tmp_path, inspect=lambda *_: receipt)
    with pytest.raises(_Wait):
        gate.prepare(request)
    assert delegate.calls == 0
    event = failure.events[0]
    assert event.classification == "ENVIRONMENT_UNAVAILABLE"
    assert expected in event.reason
    assert reason.value not in event.reason
    assert "CONTROLLED_VERIFICATION_CAPABILITY_REQUIRED" not in event.reason
    assert "delivery-preflight://" + receipt.receipt_sha256 in event.artifact_ids
    (persisted,) = records.list("preflight-receipts", DeliveryPreflightReceipt)
    persisted.validate_integrity()
    assert persisted.observations[0].native_wait_reason is reason
    assert records.list("verifier-preparation-intents", VerifierPreparationIntent) == ()


def test_preparation_finishes_before_model_start_and_marker_binds_original_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    resources, executions, _ = _fake_ports(monkeypatch, fixture)
    gate, delegate, failure, records = _gate(fixture, tmp_path)
    assert gate.prepare(fixture.request) == fixture.request
    assert delegate.calls == 1 and not failure.events
    assert len(resources) == len(executions) == 1
    marker = _marker(records)
    assert marker.result == "READY" and marker.failure_reason is None
    assert marker.observation.native_execution_state == "FINISHED"
    assert marker.observation.native_failure_code is None
    assert marker.work_item_id == fixture.claim.work_item.id
    assert marker.lease_id == fixture.claim.lease.id
    assert marker.task_snapshot_sha256 == digest(fixture.task.to_wire())
    assert marker.request_sha256 == digest(fixture.request.to_wire())
    assert marker.context_manifest_id == fixture.request.context_manifest_id
    assert marker.run_id == fixture.request.run_id
    assert marker.request == fixture.request


def test_missing_prerequisite_is_proven_unstarted_and_never_creates_model_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    resources, executions, _ = _fake_ports(monkeypatch, fixture)

    def unavailable(request: AgentRequest) -> Never:
        raise NativeVerificationWaiting(NativeVerificationWaitReason.CAPABILITY_UNAVAILABLE)

    gate, delegate, failure, records = _gate(fixture, tmp_path, prepare=unavailable)
    before = fixture.task.to_wire()
    with pytest.raises(_Wait):
        gate.prepare(fixture.request)
    assert delegate.calls == 0 and not resources and not executions
    marker = _marker(records)
    assert marker.result == "WAIT"
    assert marker.observation.native_execution_state == "NOT_STARTED"
    assert marker.observation.native_started_sha256 is None
    assert failure.events[0].classification == "ENVIRONMENT_UNAVAILABLE"
    assert failure.events[0].artifact_ids == ("verifier-preparation://" + marker.checkpoint_sha256,)
    assert fixture.task.to_wire() == before


def test_native_timeout_is_finished_receipt_not_an_uninvoked_verification_or_provider_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    resources, _, _ = _fake_ports(monkeypatch, fixture)

    def timeout(executor: SubprocessCommandExecutor, argv: tuple[str, ...]) -> Never:
        raise CommandTimedOut(argv, duration_ms=1000)

    monkeypatch.setattr(SubprocessCommandExecutor, "run", timeout)
    gate, delegate, failure, records = _gate(fixture, tmp_path)
    before = fixture.task.to_wire()
    with pytest.raises(_Wait):
        gate.prepare(fixture.request)
    marker = _marker(records)
    assert delegate.calls == 0 and len(resources) == 1
    assert marker.observation.native_execution_state == "FINISHED"
    assert marker.observation.native_started_sha256
    assert marker.observation.native_finished_sha256
    assert marker.observation.native_failure_code == "COMMAND_TIMEOUT"
    assert marker.failure_reason is NativeVerificationWaitReason.COMMAND_TIMEOUT
    assert failure.events[0].classification == "ENVIRONMENT_UNAVAILABLE"
    assert fixture.task.to_wire() == before and not fixture.task.retry_failures


def test_native_started_without_final_remains_uncertain_even_without_model_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    resources, executions, _ = _fake_ports(monkeypatch, fixture)

    monkeypatch.setattr(
        _PREFIX + "execute_python_mysql_verification", _interrupt_native_execution(tmp_path)
    )
    with pytest.raises(KeyboardInterrupt):
        fixture.registry.prepare_verifier(
            request=fixture.request,
            workspace_root=fixture.root,
            guard=fixture.guard,
        )
    gate, delegate, failure, records = _gate(fixture, tmp_path)
    with pytest.raises(_Wait):
        gate.prepare(fixture.request)
    marker = _marker(records)
    assert delegate.calls == 0 and not resources and not executions
    assert marker.observation.native_execution_state == "UNCERTAIN"
    assert marker.observation.native_started_sha256
    assert marker.observation.native_finished_sha256 is None
    assert marker.failure_reason is NativeVerificationWaitReason.EXECUTION_UNCERTAIN
    assert failure.events[0].classification == "EXECUTION_UNCERTAIN"


def test_prior_model_invocation_bypasses_preparation_on_replay_or_unknown_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    resources, executions, _ = _fake_ports(monkeypatch, fixture)

    def forbidden(request: AgentRequest) -> Never:
        raise AssertionError("an existing model invocation cannot re-run preparation")

    gate, delegate, failure, records = _gate(
        fixture,
        tmp_path,
        delegate=_Delegate(started=True),
        prepare=forbidden,
    )
    assert gate.prepare(fixture.request) == fixture.request
    assert delegate.calls == 1 and not failure.events and not resources and not executions
    assert records.list("verifier-preparations", VerifierPreparationCheckpoint) == ()


@pytest.mark.parametrize("change", ["lease", "corrupt", "symlink"])
def test_observation_never_mislabels_wrong_or_damaged_native_authority_as_unstarted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    fixture = _fixture(tmp_path)
    _fake_ports(monkeypatch, fixture)
    provider = fixture.bind()
    assert provider is not None
    lease_id = fixture.claim.lease.id
    binding_path = provider._store.root / "binding.json"
    if change == "lease":
        lease_id = "lease_not_this_original_claim"
    elif change == "corrupt":
        binding_path.write_text('{"wrong": "typed record"}')
    else:
        binding_path.unlink()
        binding_path.symlink_to(tmp_path / "missing-private-record")
    observed = observe_verifier_preparation(
        repository_workspace_root=tmp_path / "sidecar",
        request=fixture.request,
        lease_id=lease_id,
    )
    assert observed.native_execution_state == "UNCERTAIN"


@pytest.mark.parametrize("state", ["NOT_STARTED", "FINISHED", "UNCERTAIN"])
def test_crash_before_model_start_keeps_original_intent_across_new_claim_and_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    fixture = _fixture(tmp_path)
    resources, executions, _ = _fake_ports(monkeypatch, fixture)
    if state == "UNCERTAIN":
        monkeypatch.setattr(
            _PREFIX + "execute_python_mysql_verification",
            _interrupt_native_execution(tmp_path),
        )

    def crash(request: AgentRequest) -> Never:
        records = KnowledgeRecordStore(tmp_path / "sidecar/state/delivery-preflight")
        (intent,) = records.list("verifier-preparation-intents", VerifierPreparationIntent)
        intent.validate_integrity()
        assert intent.request == request and intent.lease_id == fixture.claim.lease.id
        if state == "NOT_STARTED":
            assert fixture.bind() is not None
        else:
            fixture.registry.prepare_verifier(
                request=request,
                workspace_root=fixture.root,
                guard=fixture.guard,
            )
        raise KeyboardInterrupt()

    gate, delegate, _, records = _gate(fixture, tmp_path, prepare=crash)
    with pytest.raises(KeyboardInterrupt):
        gate.prepare(fixture.request)
    assert delegate.calls == 0
    assert records.list("verifier-preparations", VerifierPreparationCheckpoint) == ()
    original_receipts = {
        path: path.read_bytes()
        for path in (tmp_path / "sidecar/native-role-verification").rglob("*.json")
    }
    # A real queue reclaims an expired lease with dispatch_sequence + 1. That
    # scheduling change alone must never erase a preparation intent or old Run.
    next_claim = fixture.claim.model_validate(
        {
            **fixture.claim.to_wire(),
            "work_item": {**fixture.claim.work_item.to_wire(), "dispatch_sequence": 1},
            "assignment": {
                **fixture.claim.assignment.to_wire(),
                "id": "assignment_new_claim",
                "lease_id": "lease_new_claim",
            },
            "lease": {
                **fixture.claim.lease.to_wire(),
                "id": "lease_new_claim",
                "assignment_id": "assignment_new_claim",
            },
        }
    )
    request = fixture.request.model_copy(
        update={
            "run_id": "run_new_unused_verifier",
            "context_manifest_id": "ctx_" + "f" * 64,
        }
    )
    continued = replace(fixture, request=request, claim=next_claim, guard=_Guard(next_claim))

    def forbidden(request: AgentRequest) -> Never:
        raise AssertionError("a replacement claim cannot execute another native preparation")

    reopened, next_delegate, failure, reopened_records = _gate(
        continued,
        tmp_path,
        prepare=forbidden,
    )
    with pytest.raises(_Wait):
        reopened.prepare(request)
    marker = _marker(reopened_records)
    assert marker.result == "WAIT"
    assert marker.request == fixture.request and marker.lease_id == fixture.claim.lease.id
    assert marker.dispatch_sequence == 0
    assert marker.wait_lease_id == next_claim.lease.id and marker.wait_dispatch_sequence == 1
    assert marker.observation.native_execution_state == state
    assert next_delegate.calls == 0
    assert len(resources) == len(executions) == (1 if state == "FINISHED" else 0)
    assert all(path.read_bytes() == original for path, original in original_receipts.items())
    assert (
        len(reopened_records.list("verifier-preparation-intents", VerifierPreparationIntent)) == 1
    )
    assert failure.events[0].classification == (
        "EXECUTION_UNCERTAIN" if state == "UNCERTAIN" else "ENGINEERING_AUTHORIZATION"
    )
    if state == "FINISHED":
        assert marker.observation.native_failure_code is None
        assert "原验证准备已结束" in failure.events[0].reason
