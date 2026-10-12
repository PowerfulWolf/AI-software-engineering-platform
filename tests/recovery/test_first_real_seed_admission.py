"""Actual seed service uses claimed main facts, not knowledge preparation attempts."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult, AgentRunStatus
from ai_software_engineer.agents.continuation import ContinuationExecutionUncertain
from ai_software_engineer.agents.execution import bind_execution_guard
from ai_software_engineer.agents.workspace_admission import (
    FirstCoderRunWorkspaceAdmission,
    workspace_admission_for_request,
)
from ai_software_engineer.artifacts import seal_artifact
from ai_software_engineer.config import ModelProviderKind, ProductionConfig, ProviderRouteConfig
from ai_software_engineer.context import FileContextBuilder
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.manager.dispatch import RecoveryDispatchRecord
from ai_software_engineer.recovery.entry import NativeRecoveryEntry
from ai_software_engineer.recovery.interruption import RecoveryInterruptionService
from ai_software_engineer.recovery.interruption_records import (
    RecoveryInterruptionInvocation,
    RecoveryInterruptionPlan,
)
from ai_software_engineer.recovery.models import (
    RecoveryApprovalCommand,
    RecoveryAuthorization,
    RecoveryPlan,
    RecoveryRejected,
    VerifiedRecoveryDecision,
    digest,
)
from ai_software_engineer.recovery.records import RecoveryInvocationRecord
from ai_software_engineer.recovery.seed import RecoverySeedService
from ai_software_engineer.recovery.store import FileRecoveryStore, RecoveryRecordMissing
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact
from ai_software_engineer.work_queue.invocation import DurableInvocationControl
from ai_software_engineer.work_queue.models import QueueArtifactReceipt, QueueClaim
from ai_software_engineer.work_queue.ports import QueueLeaseLost
from tests.domain.factories import NOW, make_coder_progress_artifact, make_implementation_artifact
from tests.recovery.seed_admission_support import SeedGuard
from tests.recovery.test_preparation_inspection_scope import (
    SOURCE,
    preparation_fixture,
    seed_fixture,
)


def next_request(seed: RecoverySeedService, prior: AgentRequest, attempt: int) -> AgentRequest:
    context = seed.contexts.put(
        FileContextBuilder(
            Path(seed.store.get_seed(seed.dispatch.recovery_plan_sha256).capture.worktree_path),
            seed.permissions,
        ).build(seed.dispatch.task, AgentRole.CODER, attempt=attempt)
    )
    return prior.model_copy(
        update={
            "attempt": attempt,
            "run_id": f"run_first_real_{attempt}",
            "context_manifest_id": context.context_id,
        }
    )


@pytest.mark.parametrize("authority_drift", [False, True])
def test_knowledge_only_first_identity_keeps_real_seed_gate_for_attempt_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, authority_drift: bool
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    seed, target, first = seed_fixture(f, main_started=False)
    seed.seed(target)
    request = next_request(seed, first, 2)
    guard = cast(SeedGuard, seed.guard)
    guard.bind(request)
    assert seed.prior_main_outcomes(request) == (), "current start is not historical consumption"
    assert workspace_admission_for_request(FirstCoderRunWorkspaceAdmission(seed), request) is seed
    if authority_drift:
        f.body.write_text(SOURCE + "# changed authority input\n")
        with pytest.raises(RecoveryRejected):
            seed.authorize(request, target.path)
        with pytest.raises(RecoveryRecordMissing):
            f.store.get_invocation(f.plan.plan_sha256)
    else:
        seed.authorize(request, target.path)
        receipt = f.store.get_invocation(f.plan.plan_sha256)
        assert (receipt.run_id, receipt.context_manifest_id) == (
            request.run_id,
            request.context_manifest_id,
        )
    assert guard.queue.read_keys and set(guard.queue.read_keys) == {"work_native_2"}


@pytest.mark.parametrize("drift", ["claim", "context", "source", "missing_worker"])
def test_first_main_rejects_exact_claim_context_or_source_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    seed, target, first = seed_fixture(f, main_started=False)
    seed.seed(target)
    request = next_request(seed, first, 2)
    guard = cast(SeedGuard, seed.guard)
    guard.bind(request)
    if drift == "claim":
        guard.lost = True
    elif drift == "context":
        request = request.model_copy(update={"context_manifest_id": first.context_manifest_id})
    elif drift == "source":
        request = request.model_copy(update={"source_revision": "f" * 40})
    else:
        seed.guard = None
    with pytest.raises(QueueLeaseLost if drift == "claim" else RecoveryRejected):
        seed.authorize(request, target.path)
    with pytest.raises(RecoveryRecordMissing):
        f.store.get_invocation(f.plan.plan_sha256)


@pytest.mark.parametrize("admitted", [False, True])
def test_prior_main_unknown_cannot_be_replayed_or_backfilled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, admitted: bool
) -> None:
    f = preparation_fixture(tmp_path, monkeypatch)
    seed, target, first = seed_fixture(f)
    seed.seed(target)
    if admitted:
        seed.authorize(first, target.path)
    request = next_request(seed, first, 2)
    cast(SeedGuard, seed.guard).bind(request)
    with pytest.raises(ContinuationExecutionUncertain, match="结果尚未封存"):
        workspace_admission_for_request(FirstCoderRunWorkspaceAdmission(seed), request)
    if not admitted:
        with pytest.raises(RecoveryRecordMissing):
            f.store.get_invocation(f.plan.plan_sha256)


def accepted_input_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, admitted: bool, kind: str
) -> tuple[RecoverySeedService, AgentRequest, AgentRequest, SeedGuard]:
    f = preparation_fixture(tmp_path, monkeypatch)
    seed, target, first = seed_fixture(f, dispatch_sequence=1)
    seed.seed(target)
    if admitted:
        seed.authorize(first, target.path)
    guard = cast(SeedGuard, seed.guard)
    assert guard.lease is not None
    claim = guard.lease.claim
    template = (
        make_coder_progress_artifact() if kind == "progress" else make_implementation_artifact()
    )
    candidate = "e" * 40 if kind == "candidate" else first.source_revision
    artifact = template.model_copy(
        update={
            "task_id": first.task_id,
            "source_revision": candidate,
            "context_manifest_id": first.context_manifest_id,
            "producer": template.producer.model_copy(update={"run_id": first.run_id}),
            "parent_artifact_ids": (),
            **(
                {"content": template.content.model_copy(update={"commit_sha": candidate})}
                if kind == "candidate"
                else {}
            ),
        }
    )
    result = AgentResult(
        run_id=first.run_id,
        task_id=first.task_id,
        role=first.role,
        attempt=first.attempt,
        source_revision=first.source_revision,
        context_manifest_id=first.context_manifest_id,
        status=AgentRunStatus.SUCCEEDED,
        artifact=artifact,
    )
    DurableInvocationControl(seed.invocations, guard).completed(first, result)
    reference = seed.artifacts.put(seal_artifact(artifact, validated_at=NOW))
    guard.queue.publications.append(
        AcceptedRoleArtifact(
            task_id=first.task_id,
            work_item_id=claim.work_item.id,
            lease_id=claim.lease.id,
            dispatch_sequence=claim.work_item.dispatch_sequence,
            checkpoint_sequence=claim.work_item.checkpoint_sequence,
            run_id=first.run_id,
            context_manifest_id=first.context_manifest_id,
            source_revision=candidate,
            receipt=QueueArtifactReceipt(
                artifact_id=reference.artifact_id, sha256=reference.sha256
            ),
        )
    )
    request = next_request(seed, first, 2).model_copy(
        update={
            "source_revision": candidate,
            "input_artifact_ids": (artifact.artifact_id,),
            "continuation_checkpoint_id": artifact.artifact_id if kind == "progress" else None,
        }
    )
    guard.bind(request)
    return seed, first, request, guard


@pytest.mark.parametrize("admitted", [False, True])
@pytest.mark.parametrize("kind", ["progress", "candidate"])
def test_accepted_later_input_uses_normal_gate_with_or_without_legacy_seed_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, admitted: bool, kind: str
) -> None:
    seed, _, request, guard = accepted_input_fixture(tmp_path, monkeypatch, admitted, kind)
    # Fresh service object still selects from immutable files and accepted receipts.
    fresh = RecoverySeedService(
        store=seed.store,
        sealing=seed.sealing,
        manager=seed.manager,
        dispatch=seed.dispatch,
        permissions=seed.permissions,
        contexts=seed.contexts,
        invocations=seed.invocations,
        artifacts=seed.artifacts,
    )
    with bind_execution_guard(guard):
        assert (
            workspace_admission_for_request(FirstCoderRunWorkspaceAdmission(fresh), request) is None
        )
    if not admitted:
        with pytest.raises(RecoveryRecordMissing):
            seed.store.get_invocation(seed.dispatch.recovery_plan_sha256)
        guard.queue.publications.clear()
        with bind_execution_guard(guard), pytest.raises(ContinuationExecutionUncertain):
            workspace_admission_for_request(FirstCoderRunWorkspaceAdmission(fresh), request)


def test_original_claim_returned_under_foreign_lease_key_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed, _, request, guard = accepted_input_fixture(tmp_path, monkeypatch, False, "progress")
    original = guard.queue.claims["lease_native_1"]
    foreign = QueueClaim.model_validate(
        {
            **original.to_wire(),
            "lease": {**original.lease.to_wire(), "id": "lease_foreign_key"},
            "assignment": {
                **original.assignment.to_wire(),
                "lease_id": "lease_foreign_key",
            },
        }
    )
    guard.queue.claims["lease_native_1"] = foreign
    with (
        bind_execution_guard(guard),
        pytest.raises(RecoveryRejected, match="durable queue step"),
    ):
        workspace_admission_for_request(FirstCoderRunWorkspaceAdmission(seed), request)
    with pytest.raises(RecoveryRecordMissing):
        seed.store.get_invocation(seed.dispatch.recovery_plan_sha256)


def interruption_selector(
    seed: RecoverySeedService,
    first: AgentRequest,
    guard: SeedGuard,
    monkeypatch: pytest.MonkeyPatch,
) -> RecoveryInterruptionService:
    """A legacy original admission plus a genuinely completed replacement main."""
    recovery = seed.store.get_plan(seed.dispatch.recovery_plan_sha256)
    seed_receipt = seed.store.get_seed(recovery.plan_sha256)
    original = RecoveryInvocationRecord(
        recovery_plan_sha256=recovery.plan_sha256,
        seed_record_sha256=seed_receipt.record_sha256,
        run_id="run_legacy_original",
        context_manifest_id=first.context_manifest_id,
        record_sha256="0" * 64,
    )
    original = original.model_copy(update={"record_sha256": original.recompute_sha256()})
    seed.store.put_invocation(original)
    first_claim = guard.queue.claims["lease_native_1"]
    now = max(datetime.now(UTC), first_claim.lease.expires_at + timedelta(seconds=1))
    plan = RecoveryInterruptionPlan(
        scope=recovery.source.scope,
        recovery_plan_sha256=recovery.plan_sha256,
        authorization_sha256=seed.store.get_authorization(
            recovery.plan_sha256
        ).authorization_sha256,
        seed_record_sha256=seed_receipt.record_sha256,
        invocation_record_sha256=original.record_sha256,
        task_id=first.task_id,
        task_sha256=digest(seed.dispatch.task.to_wire()),
        events_sha256="d" * 64,
        task_revision=2,
        dispatch_sha256=seed.dispatch.dispatch_sha256,
        work_item_id=first_claim.work_item.id,
        dispatch_sequence=0,
        expired_lease=first_claim.lease.model_copy(update={"id": "lease_legacy_expired"}),
        created_at=now,
        plan_sha256="0" * 64,
    )
    plan = plan.model_copy(update={"plan_sha256": plan.recompute_sha256()})
    seed.store.put_interruption_plan(plan)
    command = RecoveryApprovalCommand(
        operation_id="operation_fixture_replacement",
        plan_sha256=plan.plan_sha256,
        approval_reference="human-exact-replacement",
        submitted_at=now,
    )
    authorization = RecoveryAuthorization.create(
        command,
        VerifiedRecoveryDecision(
            plan_sha256=plan.plan_sha256,
            approval_reference=command.approval_reference,
            approved=True,
            operator_id="engineering_fixture",
            rationale="one exact replacement",
            decided_at=now,
        ),
    )
    seed.store.put_interruption_authorization(recovery.plan_sha256, authorization)
    replacement = RecoveryInterruptionInvocation(
        plan_sha256=plan.plan_sha256,
        authorization_sha256=authorization.authorization_sha256,
        previous_invocation_sha256=original.record_sha256,
        request=first,
        lease_id=first_claim.lease.id,
        dispatch_sequence=first_claim.work_item.dispatch_sequence,
        admitted_at=now,
        record_sha256="0" * 64,
    )
    replacement = replacement.model_copy(update={"record_sha256": replacement.recompute_sha256()})
    seed.store.put_interruption_invocation(recovery.plan_sha256, replacement)
    sidecar = seed.invocations.root.parent.parent
    monkeypatch.setattr(
        "ai_software_engineer.recovery.entry._repository_sidecar", lambda *_: sidecar
    )

    class Entry:
        config = ProductionConfig(
            platform_root=str(sidecar),
            model_routes=(
                ProviderRouteConfig(
                    provider="codex", model="offline", kind=ModelProviderKind.CODEX_CLI
                ),
            ),
        )

        def __init__(self) -> None:
            self.environment: dict[str, str] = {}

        def _dispatch_for(
            self, store: FileRecoveryStore, actual: RecoveryPlan
        ) -> RecoveryDispatchRecord:
            assert store is seed.store and actual == recovery
            return seed.dispatch

    return RecoveryInterruptionService(cast(NativeRecoveryEntry, Entry()), seed.store, recovery)


@pytest.mark.parametrize("kind", ["progress", "candidate"])
def test_replacement_admission_is_not_replayed_after_accepted_progress_or_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    seed, first, request, guard = accepted_input_fixture(tmp_path, monkeypatch, False, kind)
    interruption = interruption_selector(seed, first, guard, monkeypatch)
    with bind_execution_guard(guard):
        assert (
            workspace_admission_for_request(FirstCoderRunWorkspaceAdmission(interruption), request)
            is None
        )
    guard.queue.publications.clear()
    with bind_execution_guard(guard), pytest.raises(ContinuationExecutionUncertain):
        workspace_admission_for_request(FirstCoderRunWorkspaceAdmission(interruption), request)
