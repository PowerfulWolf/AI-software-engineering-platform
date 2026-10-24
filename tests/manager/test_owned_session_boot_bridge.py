"""A scoped stable-boot bridge supplements identity, never original process stop."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from ai_software_engineer.agents.execution import ExecutionStop, NativeProcessStop
from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.agents.structured_observation import (
    StructuredExecutionAdmission,
    StructuredNativeStopReceipt,
)
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain import AgentRole, Task, TaskStatus
from ai_software_engineer.domain.engineering_authority import LocalOperatorPrincipal
from ai_software_engineer.domain.execution_baseline import BaselineContinuationMode, BaselinePurpose
from ai_software_engineer.git import WorktreeChangeCapture, WorktreeRef
from ai_software_engineer.knowledge.invocation import (
    KnowledgeExecutionRecord,
    KnowledgeInvocationIntent,
    KnowledgeInvocationOutcome,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.models import KnowledgeError
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.baseline_models import (
    BaselineOperatorAuthorization,
    ExecutionBaselinePlan,
)
from ai_software_engineer.manager.baseline_store import FileExecutionBaselineStore
from ai_software_engineer.manager.legacy_containment import LocalBootObservation, LocalBootObserver
from ai_software_engineer.manager.owned_session_boot_bridge import (
    ScopedNativeStopVerifier,
    _BootContinuity,
    _ValidatedBootAnchor,
)
from ai_software_engineer.orchestration.continuation_models import ContinuationRejected
from ai_software_engineer.owned_sessions import (
    OwnedProcessIdentity,
    OwnedSessionStopProof,
    OwnedSessionUnknown,
    require_recorded_session_empty,
)
from ai_software_engineer.recovery import (
    FileRecoveryStore,
    RecoveryAuthorization,
    RecoveryPlan,
    RecoveryRejected,
    RecoveryScope,
)
from ai_software_engineer.recovery.models import CapturedChanges, digest
from ai_software_engineer.store import TaskRepository
from tests.contracts.test_owned_session_stop_schema import _proof as _schema_proof
from tests.manager.test_baseline_knowledge_claim_proof import knowledge_failure
from tests.manager.test_completed_output_checkpoint import CompletedFixture
from tests.manager.test_completed_output_checkpoint import completed as completed
from tests.manager.test_knowledge_isolation import isolation_fixture
from tests.recovery.test_authorization import Human, approval, make_plan
from tests.recovery.test_task_record import record_for

NOW = datetime.now(UTC)
BOOT = LocalBootObservation(
    machine_sha256="a" * 64,
    boot_session_sha256="b" * 64,
    booted_at=(NOW - timedelta(days=10)).replace(microsecond=0),
)


def _proof() -> OwnedSessionStopProof:
    original = _schema_proof()
    birth_seconds = int((NOW - timedelta(days=1) + timedelta(seconds=1)).timestamp())
    births = tuple(
        p.model_copy(
            update={
                "birth_identity": f"darwin-time:{birth_seconds}:{123456 + i}",
            }
        )
        for i, p in enumerate(original.observed_processes)
    )
    return OwnedSessionStopProof.create(
        **{
            **original.to_wire(),
            "boot_identity": f"darwin:{int(BOOT.booted_at.timestamp())}:123456",
            "leader": births[0],
            "observed_processes": births,
            "observed_at": NOW,
        }
    )


def _anchor() -> _ValidatedBootAnchor:
    return _ValidatedBootAnchor(
        boot=BOOT,
        account_sha256="c" * 64,
        observed_at=NOW - timedelta(days=2),
        plan_sha256="d" * 64,
        binding_sha256="e" * 64,
        authority_sha256="f" * 64,
        isolation_sha256="1" * 64,
        recovery_chain_sha256s=("2" * 64,),
    )


def test_bridge_reopens_anchor_and_original_witness_on_every_boundary() -> None:
    calls: list[str] = []
    proof = _proof()
    proof = proof.model_copy(update={"proof_sha256": proof.recompute_sha256()})

    def anchor() -> _ValidatedBootAnchor:
        calls.append("anchor")
        return _anchor()

    def witness() -> datetime:
        calls.append("witness")
        return NOW - timedelta(days=1)

    bridge = _BootContinuity(
        proof,
        anchor,
        witness,
        cast(LocalBootObserver, SimpleNamespace(observe=lambda: BOOT)),
        lambda machine: "c" * 64,
    )
    bridge.require_current(proof, "darwin-session:" + "b" * 64)
    bridge.require_current(proof, "darwin-session:" + "b" * 64)
    assert calls == ["witness", "anchor", "witness", "anchor"]


@pytest.mark.parametrize("changed", ["machine", "boot", "account", "late", "proof", "prefix"])
def test_bridge_refuses_wrong_boundary(changed: str) -> None:
    proof = _proof()
    proof = proof.model_copy(update={"proof_sha256": proof.recompute_sha256()})
    current = BOOT.model_copy(
        update={
            "machine_sha256": "9" * 64 if changed == "machine" else BOOT.machine_sha256,
            "boot_session_sha256": "9" * 64 if changed == "boot" else BOOT.boot_session_sha256,
        }
    )
    bridge = _BootContinuity(
        proof,
        _anchor,
        lambda: NOW - timedelta(days=3 if changed == "late" else 1),
        cast(LocalBootObserver, SimpleNamespace(observe=lambda: current)),
        lambda machine: "9" * 64 if changed == "account" else "c" * 64,
    )
    selected = (
        proof.model_copy(update={"observations_sha256": "8" * 64}) if changed == "proof" else proof
    )
    observed = "darwin:123:456" if changed == "prefix" else "darwin-session:" + "b" * 64
    with pytest.raises((OwnedSessionUnknown, ValueError)):
        bridge.require_current(selected, observed)


def _real_anchor(
    tmp_path: Path, *, approve: bool
) -> tuple[ScopedNativeStopVerifier, ExecutionBaselinePlan]:
    f, isolation = isolation_fixture(tmp_path)
    state = tmp_path / "sidecar/state"
    target = state / "execution-baselines" / f.collector.facts.task.id
    f.service.store = FileExecutionBaselineStore(target)
    plan = f.service.propose(None, purpose=BaselinePurpose.KNOWLEDGE_PREPARATION_ISOLATION)
    if approve:
        authority = BaselineOperatorAuthorization.for_plan(
            plan,
            principal=LocalOperatorPrincipal.trusted_local(),
            reference="exact isolated stable boot fixture anchor",
            submitted_at=datetime.now(UTC),
            continuation_mode=BaselineContinuationMode.PAUSE,
            confirm_current_knowledge_execution_isolated=True,
        )
        f.service.execute(plan.plan_sha256, authority=authority)
    repository = cast(TaskRepository, SimpleNamespace(get=lambda identity: plan.facts.task))
    verifier = ScopedNativeStopVerifier(
        state=state,
        task=plan.facts.task,
        scope=plan.facts.scope,
        requirement_id=isolation.requirement_id,
        knowledge_requirement_id=isolation.knowledge_requirement_id,
        repository=repository,
    )
    return verifier, plan


def test_original_file_store_anchor_requires_actual_approved_binding_and_is_read_only(
    tmp_path: Path,
) -> None:
    verifier, plan = _real_anchor(tmp_path, approve=True)
    before = {p: p.read_bytes() for p in verifier.state.rglob("*.json")}
    anchor = verifier._anchor()
    assert anchor.plan_sha256 == plan.plan_sha256
    assert plan.facts.knowledge_isolation is not None
    assert anchor.isolation_sha256 == plan.facts.knowledge_isolation.proof_sha256
    assert anchor.recovery_chain_sha256s == ()
    assert before == {p: p.read_bytes() for p in verifier.state.rglob("*.json")}


def test_proposal_without_binding_cannot_anchor_a_legacy_stop(tmp_path: Path) -> None:
    verifier, _ = _real_anchor(tmp_path, approve=False)
    before = {p: p.read_bytes() for p in verifier.state.rglob("*.json")}
    with pytest.raises(ValueError, match="no approved stable boot anchor"):
        verifier._anchor()
    assert before == {p: p.read_bytes() for p in verifier.state.rglob("*.json")}


@pytest.mark.parametrize("changed", ["team", "project", "repository", "native", "knowledge"])
def test_real_approved_anchor_cannot_move_to_foreign_scope(tmp_path: Path, changed: str) -> None:
    verifier, _ = _real_anchor(tmp_path, approve=True)
    if changed in {"native", "knowledge"}:
        setattr(
            verifier,
            "requirement_id" if changed == "native" else "knowledge_requirement_id",
            "delivery_foreign",
        )
    else:
        verifier.scope = verifier.scope.model_copy(update={changed + "_id": changed + "_foreign"})
    with pytest.raises(ValueError, match="another approved scope"):
        verifier._anchor()


def _recovered_anchor(
    tmp_path: Path,
) -> tuple[ScopedNativeStopVerifier, FileRecoveryStore, RecoveryPlan, dict[str, Task]]:
    verifier, _ = _real_anchor(tmp_path, approve=True)
    parent = verifier.task.model_copy(update={"status": TaskStatus.BLOCKED})
    seed = make_plan(Path(parent.repository))
    source = seed.source.model_copy(
        update={
            "scope": RecoveryScope(
                team_id=verifier.scope.team_id,
                repository_id=verifier.scope.repository_id,
                repository_root=parent.repository,
                delivery_id=verifier.requirement_id,
            ),
            "task_id": parent.id,
            "task_sha256": digest(parent.to_wire()),
            "task_revision": 3,
            "parent_delivery_id": verifier.knowledge_requirement_id,
            "parent_checkpoint_sha256": "3" * 64,
            "base_revision": parent.base_ref,
        }
    )
    capture = CapturedChanges.from_capture(
        WorktreeChangeCapture(
            worktree=WorktreeRef(
                task_id=parent.id,
                role=AgentRole.CODER,
                attempt=1,
                path=tmp_path / "roles" / parent.id / "coder-attempt-01",
                head_revision=parent.base_ref,
                branch=f"ai/{parent.id}/attempt-1",
                detached=False,
            ),
            patch=b"",
            index_diff_sha256="0" * 64,
            file_sha256s=(),
        )
    )
    plan = RecoveryPlan.create(
        **{
            **seed.to_wire(),
            "source": source,
            "capture": capture,
            "target_base_revision": parent.base_ref,
            "created_at": datetime.now(UTC),
        }
    )
    command = approval(plan).model_copy(update={"submitted_at": datetime.now(UTC)})
    decision = Human().verify(command).model_copy(update={"decided_at": command.submitted_at})
    authority = RecoveryAuthorization.create(command, decision)
    sealed = record_for(plan, authority)
    store = FileRecoveryStore.initialize(
        verifier.state / f"recovery-{verifier.requirement_id}", scope=source.scope
    )
    store.put_plan(plan)
    store.put_authorization(authority)
    store.put_task_record(sealed)
    current = sealed.task.model_copy(update={"status": TaskStatus.IMPLEMENTING, "attempts": 1})
    tasks = {current.id: current, parent.id: parent}
    verifier.task = current
    verifier.repository = cast(
        TaskRepository,
        SimpleNamespace(
            get=lambda identity: tasks[identity],
            current_revision=lambda identity: 3,
        ),
    )
    return verifier, store, plan, tasks


def test_real_approved_recovery_edge_reopens_exact_ancestor_anchor_without_writes(
    tmp_path: Path,
) -> None:
    verifier, _, plan, _ = _recovered_anchor(tmp_path)
    before = {p: p.read_bytes() for p in verifier.state.rglob("*.json")}
    anchor = verifier._anchor()
    assert anchor.recovery_chain_sha256s[0] == plan.plan_sha256
    assert len(anchor.recovery_chain_sha256s) == 3
    assert before == {p: p.read_bytes() for p in verifier.state.rglob("*.json")}


@pytest.mark.parametrize("changed", ["task", "revision", "authorization", "record", "scope"])
def test_recovery_chain_drift_or_missing_approval_cannot_bridge(
    tmp_path: Path, changed: str
) -> None:
    verifier, store, plan, tasks = _recovered_anchor(tmp_path)
    if changed == "task":
        tasks[plan.source.task_id] = tasks[plan.source.task_id].model_copy(
            update={"title": "changed"}
        )
    elif changed == "revision":
        verifier.repository = cast(
            TaskRepository,
            SimpleNamespace(
                get=lambda identity: tasks[identity],
                current_revision=lambda identity: 4,
            ),
        )
    elif changed == "scope":
        verifier.knowledge_requirement_id = "delivery_foreign"
    else:
        (
            store._root
            / f"{changed if changed == 'authorization' else 'task'}-{plan.plan_sha256}.json"
        ).unlink()
    with pytest.raises((ValueError, RecoveryRejected)):
        verifier._anchor()


@pytest.mark.parametrize(
    "changed",
    [
        "boot_before_anchor",
        "boot_after_start",
        "bad_usec",
        "birth_before_start",
        "birth_after_stop",
        "foreign_birth",
    ],
)
def test_legacy_timestamp_contradictions_are_rejected_without_seconds_as_identity(
    changed: str,
) -> None:
    proof = _proof()
    if changed.startswith("boot_") or changed == "bad_usec":
        value = (
            "darwin:123:456"
            if changed == "boot_before_anchor"
            else f"darwin:{int(NOW.timestamp())}:123456"
            if changed == "boot_after_start"
            else f"darwin:{int(BOOT.booted_at.timestamp())}:1000000"
        )
        proof = OwnedSessionStopProof.create(**{**proof.to_wire(), "boot_identity": value})
    else:
        birth = (
            f"darwin-time:{int((NOW - timedelta(days=3)).timestamp())}:0"
            if changed == "birth_before_start"
            else f"darwin-time:{int((NOW + timedelta(days=1)).timestamp())}:0"
            if changed == "birth_after_stop"
            else "linux-ticks:123"
        )
        processes = tuple(
            p.model_copy(update={"birth_identity": birth}) for p in proof.observed_processes
        )
        proof = OwnedSessionStopProof.create(
            **{**proof.to_wire(), "leader": processes[0], "observed_processes": processes}
        )
    bridge = _BootContinuity(
        proof,
        _anchor,
        lambda: NOW - timedelta(days=1),
        cast(LocalBootObserver, SimpleNamespace(observe=lambda: BOOT)),
        lambda machine: "c" * 64,
    )
    with pytest.raises(OwnedSessionUnknown):
        bridge.require_current(proof, "darwin-session:" + "b" * 64)


@pytest.mark.parametrize("occupied", ["none", "leader", "birth", "sid"])
def test_bridge_keeps_original_birth_and_complete_sid_rechecks(
    monkeypatch: pytest.MonkeyPatch, occupied: str
) -> None:
    proof = _proof()

    class Inspector:
        def boot_identity(self) -> str:
            return "darwin-session:" + "b" * 64

        def identity(self, pid: int) -> OwnedProcessIdentity | None:
            if occupied == "leader" and pid == proof.leader.process_id:
                return proof.leader.model_copy(update={"birth_identity": "recycled"})
            if occupied == "birth" and pid == proof.observed_processes[1].process_id:
                return proof.observed_processes[1].model_copy(update={"session_id": 999})
            return None

        def members(self, sid: int) -> tuple[OwnedProcessIdentity, ...]:
            return (proof.observed_processes[1],) if occupied == "sid" else ()

    monkeypatch.setattr("ai_software_engineer.owned_sessions._inspector", Inspector)
    bridge = _BootContinuity(
        proof,
        _anchor,
        lambda: NOW - timedelta(days=1),
        cast(LocalBootObserver, SimpleNamespace(observe=lambda: BOOT)),
        lambda machine: "c" * 64,
    )
    before = proof.to_wire()
    if occupied == "none":
        require_recorded_session_empty(proof, boot_continuity=bridge)
    else:
        with pytest.raises(OwnedSessionUnknown):
            require_recorded_session_empty(proof, boot_continuity=bridge)
    with pytest.raises(OwnedSessionUnknown, match="boot identity"):
        require_recorded_session_empty(proof)
    assert proof.to_wire() == before


@pytest.mark.parametrize("changed", ["boot", "account"])
def test_mid_sweep_stable_boundary_change_refuses_publication(
    monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    proof = _proof()
    calls = {"observe": 0, "account": 0}

    class Inspector:
        def boot_identity(self) -> str:
            return "darwin-session:" + "b" * 64

        def identity(self, pid: int) -> None:
            return None

        def members(self, sid: int) -> tuple[OwnedProcessIdentity, ...]:
            return ()

    def observe() -> LocalBootObservation:
        calls["observe"] += 1
        return (
            BOOT.model_copy(update={"boot_session_sha256": "9" * 64})
            if changed == "boot" and calls["observe"] > 1
            else BOOT
        )

    def account(machine: str) -> str:
        calls["account"] += 1
        return "9" * 64 if changed == "account" and calls["account"] > 1 else "c" * 64

    monkeypatch.setattr("ai_software_engineer.owned_sessions._inspector", Inspector)
    bridge = _BootContinuity(
        proof,
        _anchor,
        lambda: NOW - timedelta(days=1),
        cast(LocalBootObserver, SimpleNamespace(observe=observe)),
        account,
    )
    with pytest.raises(OwnedSessionUnknown):
        require_recorded_session_empty(proof, boot_continuity=bridge)


def _native_knowledge(
    tmp_path: Path,
) -> tuple[ScopedNativeStopVerifier, StructuredNativeStopReceipt, KnowledgeInvocationOutcome, str]:
    facts = knowledge_failure(tmp_path)
    original_admission = facts.outcome.executions[0].observation
    assert isinstance(original_admission, StructuredExecutionAdmission)
    intent = KnowledgeInvocationIntent.create(**{**facts.intent.to_wire(), "phase": "intent"})
    admission = StructuredExecutionAdmission.create(
        **{
            **original_admission.to_wire(),
            "call": original_admission.call.model_copy(
                update={"phase": "knowledge_intent", "route_kind": "codex_cli"}
            ),
            "execution_kind": "native",
            "admitted_at": NOW - timedelta(days=1),
        }
    )
    proof = _proof()
    stop = NativeProcessStop.create(
        process_id=proof.leader.process_id,
        group_id=proof.leader.group_id,
        returncode=1,
        kind="failed",
        stopped_at=NOW,
        session_proof=proof,
    )
    receipt = StructuredNativeStopReceipt.create(
        admission=admission, process_stop=stop, stdout_sha256="4" * 64, stderr_sha256="5" * 64
    )
    executions = tuple(
        KnowledgeExecutionRecord.create(intent_sha256=intent.intent_sha256, observation=value)
        for value in (admission, receipt)
    )
    outcome = KnowledgeInvocationOutcome.create(
        **{
            **facts.outcome.to_wire(),
            "intent": intent,
            "executions": executions,
            "completed_at": NOW,
        }
    )
    facts.records.put("knowledge-invocation-intents", intent.binding.run_id + ":intent", intent)
    facts.records.put("knowledge-invocation-outcomes", intent.binding.run_id + ":intent", outcome)
    for execution in executions:
        facts.records.put("knowledge-execution-records", execution.record_sha256, execution)
    context = FileContextStore(tmp_path / "contexts", read_only=True).get(
        intent.binding.context_manifest_id
    )
    verifier = ScopedNativeStopVerifier(
        state=tmp_path / "state",
        task=facts.task,
        scope=facts.collector.scope,
        requirement_id="delivery_native",
        knowledge_requirement_id=intent.binding.requirement_id,
        repository=cast(TaskRepository, SimpleNamespace(get=lambda identity: facts.task)),
    )
    return verifier, receipt, outcome, digest(context.to_wire())


@pytest.mark.parametrize("changed", ["none", "receipt", "outcome", "observation", "context"])
def test_knowledge_bridge_reopens_exact_receipt_outcome_independent_record_and_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    verifier, receipt, outcome, context_sha = _native_knowledge(tmp_path)

    def only_witness(
        stop: ExecutionStop, request: AgentRequest | None, witness: Callable[[], datetime]
    ) -> None:
        witness()

    monkeypatch.setattr(verifier, "_require", only_witness)
    if changed == "receipt":
        receipt = StructuredNativeStopReceipt.create(
            **{**receipt.to_wire(), "stdout_sha256": "9" * 64}
        )
    elif changed == "outcome":
        outcome = KnowledgeInvocationOutcome.create(
            **{**outcome.to_wire(), "completed_at": NOW + timedelta(seconds=1)}
        )
    elif changed == "observation":
        records = KnowledgeRecordStore(
            verifier.state.parent
            / "knowledge/runs/invocations"
            / invocation_lane_sha256(outcome.intent.binding),
            read_only=True,
        )
        (
            records.root
            / records._name("knowledge-execution-records", outcome.executions[-1].record_sha256)
        ).unlink()
    elif changed == "context":
        context_sha = "9" * 64
    if changed == "none":
        verifier.require_knowledge(receipt, outcome, context_sha)
    else:
        with pytest.raises((ValueError, KnowledgeError)):
            verifier.require_knowledge(receipt, outcome, context_sha)


@pytest.mark.parametrize("changed", ["none", "stop", "request", "envelope"])
def test_capture_bridge_reopens_exact_original_start_and_stop(
    completed: CompletedFixture, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    f = completed
    verifier = ScopedNativeStopVerifier(
        state=f.collector.state,
        task=f.task,
        scope=f.collector.scope,
        requirement_id=f.capture_start.scope.requirement_id,
        knowledge_requirement_id="delivery_parent",
        repository=f.native.repository,
    )

    def only_witness(
        stop: ExecutionStop, request: AgentRequest | None, witness: Callable[[], datetime]
    ) -> None:
        witness()

    monkeypatch.setattr(verifier, "_require", only_witness)
    stop = f.capture_stop.process_stop
    request = f.capture_start.request
    if changed == "stop":
        stop = NativeProcessStop.create(
            **{**stop.to_wire(), "stopped_at": stop.stopped_at + timedelta(seconds=1)}
        )
    elif changed == "request":
        request = request.model_copy(update={"source_revision": "9" * 40})
    elif changed == "envelope":
        (f.ledger._root / f"capture-stop-{request.run_id}.json").write_text("{}")
    if changed == "none":
        verifier.require_stopped(stop, request)
    else:
        with pytest.raises((ValueError, ContinuationRejected)):
            verifier.require_stopped(stop, request)
