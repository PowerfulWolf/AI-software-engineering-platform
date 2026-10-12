"""Actual finished native preparation is distinct from starting the verifier model."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Never

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult
from ai_software_engineer.agents.model_input import FinalModelInputCapacityExceeded
from ai_software_engineer.agents.models import AgentErrorCode, AgentFailure, AgentRunStatus
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.context import (
    ContextBudget,
    ContextBundle,
    ContextSection,
    FileContextStore,
)
from ai_software_engineer.domain import AgentRole, WorkItemStatus
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryFailureFacts,
    decide_delivery_disposition,
)
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.capacity_input_reader import (
    CapacityInputReader,
    claimed_verifier_capacity,
)
from ai_software_engineer.manager.context_capacity import ContextCapacityReceipt
from ai_software_engineer.manager.delivery_preflight import DeliveryPreflightReceipt
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.work_queue.execution_store import QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem
from tests.manager.test_native_verification import _fake_ports, _Fixture, _fixture
from tests.manager.test_verifier_preparation import _Delegate, _gate, _marker, _Wait


class _NoStartDelegate(_Delegate):
    def result(self, request: AgentRequest) -> AgentResult | None:
        return None


@dataclass(frozen=True)
class _Queue:
    claim: QueueClaim
    step: QueuedRoleStep

    def original_claim(self, lease_id: str) -> QueueClaim:
        if lease_id != self.claim.lease.id:
            raise ValueError("没有真实原 claim")
        return self.claim

    def step_for_invocation(self, work_item_id: str, baseline_sha256: str | None) -> QueuedRoleStep:
        assert work_item_id == self.step.work_item.id and baseline_sha256 is None
        return self.step


@dataclass(frozen=True)
class _CapacityFixture:
    native: _Fixture
    records: KnowledgeRecordStore
    receipt: ContextCapacityReceipt
    prerequisites: DeliveryPreflightReceipt
    waiting: QueuedWorkItem
    queue: _Queue
    state: Path

    def read(self) -> object:
        return claimed_verifier_capacity(
            item=self.waiting,
            task=self.native.task,
            step=self.queue.step,
            prerequisites=self.prerequisites,
            state=self.state,
            queue=self.queue,
            artifacts=FileArtifactStore(self.state.parent / "artifacts"),
        )

    def reader(self) -> CapacityInputReader:
        return CapacityInputReader(
            state=self.state,
            queue=self.queue,
            artifacts=FileArtifactStore(self.state.parent / "artifacts"),
            route_root=self.state.parent / "model-routes",
            baselines=None,
        )


def _capacity_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: AgentRole = AgentRole.QA
) -> _CapacityFixture:
    native = _fixture(tmp_path, role)
    sections = []
    sealed_claim = {
        "task_id": native.task.id,
        "work_item_id": native.claim.work_item.id,
        "lease_id": native.claim.lease.id,
        "assignment_id": native.claim.assignment.id,
        "dispatch_sequence": native.claim.work_item.dispatch_sequence,
        "role": role.value,
        "attempt": native.claim.work_item.attempt,
        "checkpoint_sequence": native.claim.work_item.checkpoint_sequence,
    }
    for name, uri, data in (
        ("task", "task://" + native.task.id, native.task.to_wire()),
        ("source:execution.claim", "claim://" + native.claim.lease.id, sealed_claim),
    ):
        content = json.dumps(data, sort_keys=True)
        sections.append(
            ContextSection(
                name=name,
                uri=uri,
                sha256=hashlib.sha256(content.encode()).hexdigest(),
                tokens=1,
                content=content,
                priority=100,
            )
        )
    context = ContextBundle(
        context_id="ctx_" + "0" * 64,
        task_id=native.task.id,
        role=role,
        attempt=1,
        source_revision=native.request.source_revision,
        sections=tuple(sections),
        budget=ContextBudget(max_input_tokens=4000, reserved_output_tokens=0, used_input_tokens=2),
        built_at=native.claim.claimed_at,
    )
    context = context.model_copy(
        update={
            "context_id": "ctx_"
            + digest(context.model_dump(mode="json", exclude={"context_id", "built_at"}))
        }
    )
    contexts = FileContextStore(tmp_path / "sidecar/contexts")
    contexts.put(context)
    request = native.request.model_copy(update={"context_manifest_id": context.context_id})
    native.facts.request, native.facts.context = request, context.context_id
    native = replace(native, request=request)
    resources, executions, _ = _fake_ports(monkeypatch, native)
    gate, delegate, failure, records = _gate(native, tmp_path, delegate=_NoStartDelegate())
    gate.context_reader = contexts.get

    def overflow(request: AgentRequest) -> Never:
        assert _marker(records).observation.native_execution_state == "FINISHED"
        raise FinalModelInputCapacityExceeded(estimated_input_tokens=4001, max_input_tokens=4000)

    gate.prepare_input = overflow
    with pytest.raises(_Wait):
        gate.prepare(request)
    assert delegate.calls == 0 and len(resources) == len(executions) == 1
    assert len(failure.events) == 1 and failure.events[0].classification == "CONTEXT_CAPACITY"
    (receipt,) = records.list("context-capacity-receipts", ContextCapacityReceipt)
    receipt.validate_integrity()
    prerequisites = DeliveryPreflightReceipt(
        scope=native.registry.scope,
        task_id=native.task.id,
        source_revision=request.source_revision,
        plan_sha256="a" * 64,
        frozen_policy_sha256="b" * 64,
        requirements_sha256="c" * 64,
        observations=(),
        status="READY",
        checked_at=receipt.observed_at,
        receipt_sha256="0" * 64,
    )
    prerequisites = prerequisites.model_copy(
        update={
            "receipt_sha256": digest(
                prerequisites.model_dump(mode="json", exclude={"receipt_sha256"})
            )
        }
    )
    waiting = native.claim.work_item.model_copy(
        update={
            "status": WorkItemStatus.WAITING_DEPENDENCY,
            "wait_disposition": decide_delivery_disposition(
                DeliveryFailureFacts(
                    task_id=native.task.id,
                    work_item_id=native.claim.work_item.id,
                    role=role,
                    classification="CONTEXT_CAPACITY",
                    source_revision=request.source_revision,
                    task_intent_sha256=task_intent_sha256(native.task),
                    checkpoint_sequence=0,
                    budget_available=True,
                    evidence_ids=("context-capacity://" + receipt.receipt_sha256,),
                )
            ),
        }
    )
    assert role in {AgentRole.QA, AgentRole.REVIEWER}
    boundary = RoleRunBoundary(
        native.task.id,
        AgentRole.QA if role is AgentRole.QA else AgentRole.REVIEWER,
        1,
        0,
        request.source_revision,
    )
    step = QueuedRoleStep(
        work_item=native.claim.work_item, boundary=boundary, allocation_sha256="d" * 64
    )
    return _CapacityFixture(
        native,
        records,
        receipt,
        prerequisites,
        waiting,
        _Queue(native.claim, step),
        tmp_path / "sidecar/state",
    )


@pytest.mark.parametrize("role", [AgentRole.QA, AgentRole.REVIEWER])
def test_capacity_resumes_real_finished_native_preparation_without_refund_or_fake_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: AgentRole
) -> None:
    fixture = _capacity_fixture(tmp_path, monkeypatch, role)
    before = {path: path.read_bytes() for path in (tmp_path / "sidecar").rglob("*.json")}
    evidence = claimed_verifier_capacity(
        item=fixture.waiting,
        task=fixture.native.task,
        step=fixture.queue.step,
        prerequisites=fixture.prerequisites,
        state=fixture.state,
        queue=fixture.queue,
        artifacts=FileArtifactStore(fixture.state.parent / "artifacts"),
    )
    assert evidence.native_execution_state == "FINISHED"
    assert evidence.native_started_sha256 and evidence.native_finished_sha256
    assert evidence.native_failure_code is evidence.budget_source is None
    assert evidence.context_capacity_claim_sha256 == digest(fixture.native.claim.to_wire())
    assert evidence.context_capacity_receipt_sha256 == fixture.receipt.receipt_sha256
    assert _marker(fixture.records).result == "READY"
    assert all(path.read_bytes() == data for path, data in before.items())


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_ready",
        "missing_finished",
        "start_alias",
        "outcome_alias",
        "wrong_key",
        "duplicate_key",
    ],
)
def test_capacity_read_rejects_incomplete_preparation_and_alternate_run_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    fixture = _capacity_fixture(tmp_path, monkeypatch)
    if mutation == "missing_ready":
        for path in fixture.records.root.glob("verifier-preparations-*.json"):
            path.unlink()
    elif mutation == "missing_finished":
        for path in (tmp_path / "sidecar/native-role-verification").rglob("finished.json"):
            path.unlink()
    else:
        request = fixture.native.request.model_copy(update={"run_id": "run_alias_started"})
        start = DeliveryInvocationStart(
            work_item_id=fixture.receipt.work_item_id,
            checkpoint_sequence=0,
            request=request,
            lease_id=fixture.receipt.lease_id,
            started_at=fixture.receipt.observed_at,
            start_sha256="0" * 64,
        )
        start = start.model_copy(
            update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
        )
        records = KnowledgeRecordStore(fixture.state / "invocations")
        if mutation not in {"wrong_key", "outcome_alias"}:
            records.put("invocation-starts", start.work_item_id, start)
        if mutation in {"wrong_key", "duplicate_key"}:
            records.put("invocation-starts", "noncanonical_key", start)
        if mutation == "outcome_alias":
            result = AgentResult(
                run_id=request.run_id,
                task_id=request.task_id,
                role=request.role,
                attempt=request.attempt,
                source_revision=request.source_revision,
                context_manifest_id=request.context_manifest_id,
                status=AgentRunStatus.FAILED,
                error=AgentFailure(
                    code=AgentErrorCode.PROVIDER_UNAVAILABLE,
                    message="保存的提供方失败事实",
                    transient=True,
                ),
            )
            outcome = DeliveryInvocationOutcome(start=start, result=result, outcome_sha256="0" * 64)
            outcome = outcome.model_copy(
                update={
                    "outcome_sha256": digest(
                        outcome.model_dump(mode="json", exclude={"outcome_sha256"})
                    )
                }
            )
            records.put("invocation-outcomes", start.work_item_id, outcome)
    before = {path: path.read_bytes() for path in (tmp_path / "sidecar").rglob("*.json")}
    with pytest.raises(ValueError, match=r"唯一原验证准备|原验证准备记录|尚未核实|模型开始|记录键"):
        fixture.read()
    assert all(path.read_bytes() == data for path, data in before.items())


def test_historical_capacity_allows_only_later_real_claim_and_current_capacity_never_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _capacity_fixture(tmp_path, monkeypatch)
    old = fixture.native.claim
    after = fixture.receipt.observed_at + timedelta(seconds=1)
    claim = QueueClaim.model_validate(
        {
            **old.to_wire(),
            "work_item": {**old.work_item.to_wire(), "dispatch_sequence": 1},
            "assignment": {
                **old.assignment.to_wire(),
                "id": "assignment_later",
                "lease_id": "lease_later",
            },
            "lease": {
                **old.lease.to_wire(),
                "id": "lease_later",
                "assignment_id": "assignment_later",
            },
            "claimed_at": after.isoformat(),
        }
    )
    reader = fixture.reader()
    reader.queue = _Queue(claim, fixture.queue.step)
    start = DeliveryInvocationStart(
        work_item_id=fixture.receipt.work_item_id,
        checkpoint_sequence=0,
        request=fixture.native.request.model_copy(update={"run_id": "run_later_real_claim"}),
        lease_id=claim.lease.id,
        started_at=after,
        start_sha256="0" * 64,
    )
    start = start.model_copy(
        update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
    )
    KnowledgeRecordStore(fixture.state / "invocations").put(
        "invocation-starts", start.work_item_id, start
    )
    reader.require_not_started(fixture.receipt, allow_later_claims=True)
    with pytest.raises(ValueError, match="模型开始"):
        reader.require_not_started(fixture.receipt)
    reader.queue = fixture.queue
    with pytest.raises(ValueError, match="真实原 claim"):
        reader.require_not_started(fixture.receipt, allow_later_claims=True)


@pytest.mark.parametrize("alternate_context", [False, True])
def test_unaccepted_artifact_with_alternate_run_cannot_hide_original_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alternate_context: bool
) -> None:
    from ai_software_engineer.artifacts import seal_artifact
    from tests.domain.factories import make_qa_artifact

    fixture = _capacity_fixture(tmp_path, monkeypatch)
    contexts = FileContextStore(tmp_path / "sidecar/contexts")
    context = contexts.get(fixture.native.request.context_manifest_id)
    if alternate_context:
        sections = tuple(
            section.model_copy(
                update={
                    "content": section.content + "\n",
                    "sha256": hashlib.sha256((section.content + "\n").encode()).hexdigest(),
                }
            )
            for section in context.sections
        )
        context = context.model_copy(update={"sections": sections})
        context = context.model_copy(
            update={
                "context_id": "ctx_"
                + digest(context.model_dump(mode="json", exclude={"context_id", "built_at"}))
            }
        )
        contexts.put(context)
    original = make_qa_artifact()
    artifact = seal_artifact(
        original.model_copy(
            update={
                "task_id": fixture.native.task.id,
                "source_revision": fixture.native.request.source_revision,
                "context_manifest_id": context.context_id,
                "parent_artifact_ids": (),
                "producer": original.producer.model_copy(update={"run_id": "run_output_alias"}),
            }
        ),
        validated_at=fixture.receipt.observed_at,
    )
    FileArtifactStore(tmp_path / "sidecar/artifacts").put(artifact)
    with pytest.raises(ValueError, match=r"角色产出|产出或路由"):
        fixture.read()


@pytest.mark.parametrize("unsafe_path", ["dangling", "symlink", "directory", "fifo", "oversized"])
def test_raw_artifact_absence_requires_safe_regular_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe_path: str
) -> None:
    import os

    fixture = _capacity_fixture(tmp_path, monkeypatch)
    reader = fixture.reader()
    path = tmp_path / "sidecar/artifacts/art_unknown.json"
    if unsafe_path == "dangling":
        path.symlink_to(tmp_path / "missing-artifact")
    elif unsafe_path == "symlink":
        target = tmp_path / "foreign-artifact.json"
        target.write_text("{}")
        path.symlink_to(target)
    elif unsafe_path == "directory":
        path.mkdir()
    elif unsafe_path == "fifo":
        os.mkfifo(path)
    else:
        with path.open("wb") as stream:
            stream.seek(8_000_000)
            stream.write(b"x")
    with pytest.raises(ValueError, match=r"symlink|regular|byte budget"):
        reader.require_not_started(fixture.receipt)


@pytest.mark.parametrize("kind", ["receipt", "admission"])
def test_native_alternate_run_receipt_or_admission_cannot_hide_original_claim(
    tmp_path: Path, kind: str
) -> None:
    from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
    from tests.orchestration.test_continuation_records import make_admission, make_receipt

    original = make_receipt(tmp_path)
    admission = make_admission(original)
    request = original.request if kind == "receipt" else admission.new_request
    work_id = original.original_work_item_id if kind == "receipt" else admission.next_work_item_id
    lease_id = original.claim_lease_id if kind == "receipt" else admission.next_lease_id
    capacity_request = request.model_copy(update={"run_id": "run_uninvoked_capacity"})
    marker = ContextCapacityReceipt(
        origin="final_input",
        task_id=request.task_id,
        task_sha256="a" * 64,
        task_intent_sha256="b" * 64,
        task_revision=2,
        work_item_id=work_id,
        lease_id=lease_id,
        assignment_id="assignment_capacity",
        claim_sha256="c" * 64,
        dispatch_sequence=0,
        checkpoint_sequence=2,
        role=request.role,
        attempt=request.attempt,
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        context_sha256="d" * 64,
        max_input_tokens=4000,
        context_input_tokens=2,
        final_input_tokens=4001,
        request=capacity_request,
        observed_at=admission.created_at,
        receipt_sha256="0" * 64,
    )
    marker = marker.model_copy(
        update={
            "receipt_sha256": digest(marker.model_dump(mode="json", exclude={"receipt_sha256"}))
        }
    )
    state = tmp_path / "sidecar/state"
    (state / "continuations").mkdir(parents=True)
    store = FileContinuationStore.initialize(
        state / "continuations" / request.task_id, task_id=request.task_id
    )
    store.put_receipt(original)
    if kind == "admission":
        store.put_admission(admission)

    # The default current-marker path must reject before asking for a different
    # historical queue claim. Real fully validated orphan receipts are sufficient.
    class NoClaims:
        def original_claim(self, lease_id: str) -> QueueClaim:
            raise AssertionError("current same-claim contradiction needs no replacement claim")

        def step_for_invocation(
            self, work_item_id: str, baseline_sha256: str | None
        ) -> QueuedRoleStep:
            raise AssertionError("current contradiction cannot be a historical later step")

    reader = CapacityInputReader(
        state=state,
        queue=NoClaims(),
        artifacts=FileArtifactStore(tmp_path / "sidecar/artifacts"),
        route_root=tmp_path / "sidecar/model-routes",
        baselines=None,
    )
    with pytest.raises(ValueError, match="原生恢复记录"):
        reader.require_not_started(marker)


@pytest.mark.parametrize("alternate_context", [False, True])
def test_orphan_provider_route_with_alternate_run_never_proves_no_model_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alternate_context: bool
) -> None:
    from ai_software_engineer.agents.fallback import (
        FileModelRouteAttemptStore,
        ModelRouteAttempt,
        model_route_root,
    )

    fixture = _capacity_fixture(tmp_path, monkeypatch)
    context_id = fixture.native.request.context_manifest_id
    if alternate_context:
        contexts = FileContextStore(tmp_path / "sidecar/contexts")
        context = contexts.get(context_id)
        sections = tuple(
            section.model_copy(
                update={
                    "content": section.content + "\n",
                    "sha256": hashlib.sha256((section.content + "\n").encode()).hexdigest(),
                }
            )
            for section in context.sections
        )
        context = context.model_copy(update={"sections": sections})
        context = context.model_copy(
            update={
                "context_id": "ctx_"
                + digest(context.model_dump(mode="json", exclude={"context_id", "built_at"}))
            }
        )
        contexts.put(context)
        context_id = context.context_id
    request = fixture.native.request.model_copy(
        update={
            "run_id": "run_orphan_provider_alias",
            "context_manifest_id": context_id,
        }
    )
    result = AgentResult(
        run_id=request.run_id,
        task_id=request.task_id,
        role=request.role,
        attempt=request.attempt,
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        status=AgentRunStatus.FAILED,
        error=AgentFailure(
            code=AgentErrorCode.PROVIDER_UNAVAILABLE,
            message="原路由调用失败",
            transient=True,
        ),
    )
    route = ModelRouteAttempt.create(
        request=request,
        route_index=1,
        provider="fixture",
        model="fixture",
        started_at=fixture.receipt.observed_at,
        completed_at=fixture.receipt.observed_at,
        result=result,
        fallback=False,
    )
    FileModelRouteAttemptStore(model_route_root(tmp_path / "sidecar")).append(route)
    with pytest.raises(ValueError, match=r"角色产出|提供方路由|产出或路由"):
        fixture.read()
