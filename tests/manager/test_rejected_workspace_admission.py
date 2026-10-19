"""Real Git and sealed adapter refusal, independently rederived by the observer.

Queue ownership is a typed in-memory unit seam. The public MySQL test replaces
that seam; no provider, production database or target delivery workspace is used.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Never

import pytest

from ai_software_engineer.agents import CodexCliAgentAdapter
from ai_software_engineer.agents.fallback import (
    FallbackAgentAdapter,
    FileModelRouteAttemptStore,
    ModelRouteAttempt,
    ProviderAgentRoute,
)
from ai_software_engineer.agents.models import AgentRequest, AgentResult, AgentRunStatus
from ai_software_engineer.artifacts import (
    ArtifactStore,
    FileArtifactStore,
    artifact_digest,
    seal_artifact,
)
from ai_software_engineer.context import (
    ContextBudget,
    ContextBundle,
    ContextSection,
    FileContextStore,
)
from ai_software_engineer.context.execution_baseline import (
    ExecutionBaselineContext,
    PreservedWorktreeBaselineContext,
)
from ai_software_engineer.domain import (
    AgentPermissions,
    AgentRole,
    BrainTier,
    ModelRouteReason,
    ModelSelection,
    RiskTier,
    RoleAssignment,
    Task,
    TaskLease,
    WorkItemStatus,
)
from ai_software_engineer.domain.artifact import Artifact, CoderProgressArtifact
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.delivery_resolution import RejectedWorkspaceAdmissionEvidence
from ai_software_engineer.domain.engineering_authority import (
    EngineeringScope,
    LocalOperatorPrincipal,
)
from ai_software_engineer.domain.workspace_admission_contract import (
    WorkspaceAdmissionAdapterContract,
    WorkspaceAdmissionAdapterContractRecord,
)
from ai_software_engineer.evidence.models import (
    CommandEvidencePayload,
    CommandEvidenceRecord,
    CommandOutcome,
    EvidenceKind,
    RunEvidenceIdentity,
    seal_evidence_record,
)
from ai_software_engineer.evidence.store import FileEvidenceStore
from ai_software_engineer.git.mutation import capture_mutation_inventory
from ai_software_engineer.git.policy import WorkspacePolicyError
from ai_software_engineer.knowledge.claim_identity import claim_identity_sha256
from ai_software_engineer.knowledge.models import KnowledgeError, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.manager.rejected_workspace_admission import (
    rejected_workspace_admission_evidence,
)
from ai_software_engineer.manager.workspace_admission_contract import (
    SUPPORTED_ADAPTER_REVISION,
    SUPPORTED_ADAPTER_SOURCES,
    seal_workspace_admission_adapter_contract,
)
from ai_software_engineer.orchestration.continuation_models import (
    ContinuationRejected,
    ContinuationScope,
    ExecutionCaptureStart,
)
from ai_software_engineer.orchestration.continuation_store import FileContinuationStore
from ai_software_engineer.orchestration.steps import RoleRunBoundary
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueArtifactReceipt, QueueClaim, QueuedWorkItem
from tests.manager.test_baseline_preserved_progress_admission import (
    PreservedFixture,
    _preserved_fixture,
)


@dataclass
class _Queue:
    claims: dict[str, QueueClaim]
    steps: dict[str, QueuedRoleStep]
    publications: tuple[AcceptedRoleArtifact, ...]

    def original_claim(self, lease_id: str) -> QueueClaim:
        return self.claims[lease_id]

    def claims_for_work_item(self, work_item_id: str) -> tuple[QueueClaim, ...]:
        return tuple(value for value in self.claims.values() if value.work_item.id == work_item_id)

    def step_for_invocation(self, work_item_id: str, baseline_sha256: str | None) -> QueuedRoleStep:
        return self.steps[work_item_id]

    def accepted(self, task_id: str) -> tuple[AcceptedRoleArtifact, ...]:
        return tuple(value for value in self.publications if value.task_id == task_id)


def _claim(task: Task, scope: EngineeringScope, attempt: int, at: datetime) -> QueueClaim:
    item = QueuedWorkItem(
        id=f"work_admission_{attempt}",
        task_id=task.id,
        repository_id=scope.repository_id,
        role=AgentRole.CODER,
        attempt=attempt,
        checkpoint_sequence=attempt,
        repository_scopes=(task.repository,),
        status=WorkItemStatus.LEASED,
        priority=500,
        risk=RiskTier.NORMAL,
        created_at=at,
        updated_at=at,
    )
    assignment = RoleAssignment(
        id=f"assignment_admission_{attempt}",
        repository_id=scope.repository_id,
        task_id=task.id,
        agent_id=f"agent_admission_{attempt}",
        role=AgentRole.CODER,
        attempt=attempt,
        lease_id=f"lease_admission_{attempt}",
        assigned_at=at,
    )
    return QueueClaim(
        work_item=item,
        assignment=assignment,
        lease=TaskLease(
            id=assignment.lease_id,
            assignment_id=assignment.id,
            task_id=task.id,
            agent_id=assignment.agent_id,
            acquired_at=at,
            expires_at=at + timedelta(minutes=20),
        ),
        model_selection=ModelSelection(
            policy_id="model_policy_admission",
            policy_version="v1",
            provider="codex",
            model="fixture",
            tier=BrainTier.STANDARD,
            reasons=(ModelRouteReason.DEFAULT,),
            selected_at=at,
        ),
        worker_id="worker_admission",
        claimed_at=at,
    )


def _context(
    task: Task,
    claim: QueueClaim,
    source: str,
    permissions: AgentPermissions,
    *,
    baseline: PreservedWorktreeBaselineContext | None = None,
) -> ContextBundle:
    data: list[tuple[str, str, object]] = [
        ("task", "task://" + task.id, task.to_wire()),
        (
            "policy",
            "policy://frozen",
            {
                **permissions.to_wire(),
                "denied_paths": list(task.constraints.denied_paths if task.constraints else ()),
            },
        ),
        (
            "source:execution.claim",
            "claim://" + claim.lease.id,
            {
                "task_id": task.id,
                "work_item_id": claim.work_item.id,
                "lease_id": claim.lease.id,
                "assignment_id": claim.assignment.id,
                "dispatch_sequence": claim.work_item.dispatch_sequence,
                "role": AgentRole.CODER.value,
                "attempt": claim.work_item.attempt,
                "checkpoint_sequence": claim.work_item.checkpoint_sequence,
            },
        ),
    ]
    if baseline is not None:
        data.append(
            (
                "execution.baseline",
                "baseline://" + baseline.binding.binding_sha256,
                baseline.to_wire(),
            )
        )
    sections = []
    for name, uri, value in data:
        content = json.dumps(value, sort_keys=True)
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
        task_id=task.id,
        role=AgentRole.CODER,
        attempt=claim.work_item.attempt,
        source_revision=source,
        sections=tuple(sections),
        budget=ContextBudget(
            max_input_tokens=100000, reserved_output_tokens=0, used_input_tokens=len(sections)
        ),
        built_at=claim.claimed_at,
    )
    return context.model_copy(
        update={
            "context_id": "ctx_"
            + digest(context.model_dump(mode="json", exclude={"context_id", "built_at"}))
        }
    )


def _start(request: AgentRequest, claim: QueueClaim, at: datetime) -> DeliveryInvocationStart:
    start = DeliveryInvocationStart(
        work_item_id=claim.work_item.id,
        checkpoint_sequence=claim.work_item.checkpoint_sequence,
        request=request,
        lease_id=claim.lease.id,
        started_at=at,
        start_sha256="0" * 64,
    )
    return start.model_copy(
        update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
    )


@dataclass(frozen=True)
class _Fixture:
    preserved: PreservedFixture
    task: Task
    claim: QueueClaim
    item: QueuedWorkItem
    step: QueuedRoleStep
    queue: _Queue
    scope: EngineeringScope
    state: Path
    route_root: Path
    artifacts: FileArtifactStore
    request: AgentRequest
    start: DeliveryInvocationStart
    outcome: DeliveryInvocationOutcome
    declaration: WorkspaceAdmissionAdapterContract
    provider_calls: int

    def observe(
        self, *, artifacts: ArtifactStore | None = None
    ) -> RejectedWorkspaceAdmissionEvidence:
        return rejected_workspace_admission_evidence(
            task=self.task,
            item=self.item,
            step=self.step,
            scope=self.scope,
            requirement_id="delivery_admission_fixture",
            state=self.state,
            route_root=self.route_root,
            queue=self.queue,
            artifacts=artifacts if artifacts is not None else self.artifacts,
            git=self.preserved.source.manager,
        )

    def declare(self) -> WorkspaceAdmissionAdapterContractRecord:
        return seal_workspace_admission_adapter_contract(
            state=self.state,
            declaration=self.declaration,
            principal=LocalOperatorPrincipal.trusted_local(),
            task=self.task,
            item=self.item,
            step=self.step,
            scope=self.scope,
            route_root=self.route_root,
            queue=self.queue,
            requirement_id="delivery_admission_fixture",
            at=datetime.now(UTC),
        )


def _fixture(
    tmp_path: Path,
    *,
    seal_declaration: bool = True,
    claim_factory: Callable[[Task, EngineeringScope, int, datetime], QueueClaim] | None = None,
    progress_published: Callable[[QueueClaim, CoderProgressArtifact, FileArtifactStore], None]
    | None = None,
) -> _Fixture:
    state = tmp_path / "sidecar/state"
    f = _preserved_fixture(tmp_path, state=state)
    task = f.source.collector.facts.task.model_copy(update={"attempts": 2})
    scope = f.source.collector.facts.scope
    now = datetime.now(UTC)
    old_task = task.model_copy(update={"attempts": 1})
    make_claim = claim_factory or _claim
    old_claim = make_claim(old_task, scope, 1, now - timedelta(minutes=5))
    contexts = FileContextStore(state.parent / "contexts")
    old_context = contexts.put(
        _context(
            old_task,
            old_claim,
            f.request.source_revision,
            f.request.permissions,
        )
    )
    artifacts = FileArtifactStore(state.parent / "artifacts")
    for artifact in f.artifacts.list_for_task(task.id):
        if artifact.artifact_id != f.progress.artifact_id:
            artifacts.put(artifact)
    progress = seal_artifact(
        f.progress.model_copy(
            update={
                "context_manifest_id": old_context.context_id,
                "producer": f.progress.producer.model_copy(
                    update={
                        "run_id": "run_admission_progress",
                        "agent_id": old_claim.assignment.agent_id,
                    }
                ),
            }
        ),
        validated_at=now,
    )
    assert isinstance(progress, CoderProgressArtifact)
    artifacts.put(progress)
    old_request = f.request.model_copy(
        update={
            "run_id": progress.producer.run_id,
            "attempt": 1,
            "context_manifest_id": old_context.context_id,
            "continuation_checkpoint_id": None,
            "continuation_changed_paths": (),
            "execution_baseline_sha256": None,
            "execution_base_ref": None,
        }
    )
    records = KnowledgeRecordStore(state / "invocations")
    old_start = _start(old_request, old_claim, old_claim.claimed_at)
    records.put("invocation-starts", old_claim.work_item.id, old_start)
    old_result = AgentResult(
        run_id=old_request.run_id,
        task_id=task.id,
        role=AgentRole.CODER,
        attempt=1,
        source_revision=old_request.source_revision,
        context_manifest_id=old_request.context_manifest_id,
        status=AgentRunStatus.SUCCEEDED,
        artifact=progress,
    )
    old_outcome = DeliveryInvocationOutcome(
        start=old_start, result=old_result, outcome_sha256="0" * 64
    )
    old_outcome = old_outcome.model_copy(
        update={
            "outcome_sha256": digest(
                old_outcome.model_dump(mode="json", exclude={"outcome_sha256"})
            )
        }
    )
    records.put("invocation-outcomes", old_claim.work_item.id, old_outcome)
    if progress_published is not None:
        progress_published(old_claim, progress, artifacts)
    claim = make_claim(task, scope, 2, datetime.now(UTC))
    complete = ExecutionBaselineContext.from_required_context(
        f.binding, f.source.service.store.required_context(f.binding)
    )
    context = contexts.put(
        _context(
            task,
            claim,
            f.request.source_revision,
            f.request.permissions,
            baseline=PreservedWorktreeBaselineContext.from_complete(complete),
        )
    )
    request = f.request.model_copy(update={"context_manifest_id": context.context_id})
    start = _start(request, claim, datetime.now(UTC))
    records.put("invocation-starts", claim.work_item.id, start)

    class OriginalPathOnlyAdmission:
        def authorize(self, value: AgentRequest, workspace_root: Path) -> None:
            capture = f.source.manager.capture_mutations(
                f.source.worktree,
                value.permissions,
                denied_paths=task.constraints.denied_paths if task.constraints else (),
            )
            if capture.changed_paths != value.continuation_changed_paths:
                raise ValueError("original exact checkpoint path-only compatibility defect")
            raise AssertionError("fixture must exercise the original failing gate")

    class Provider:
        calls = 0

        def run(self, *args: object, **kwargs: object) -> Never:
            self.calls += 1
            raise AssertionError("admission must refuse before the provider boundary")

    provider = Provider()
    adapter = CodexCliAgentAdapter(
        workspace_root=f.source.worktree.path,
        model="fixture",
        agent_id="agent_admission_2",
        agent_version="v0.1",
        runner=provider,
        initial_workspace_admission=OriginalPathOnlyAdmission(),
    )
    route_root = state.parent / "runs/model-routes"
    result = FallbackAgentAdapter(
        (
            ProviderAgentRoute(
                provider="codex",
                model="fixture",
                adapter=adapter,
                route_kind="codex_cli",
            ),
        ),
        attempt_store=FileModelRouteAttemptStore(route_root),
    ).run(request)
    outcome = DeliveryInvocationOutcome(start=start, result=result, outcome_sha256="0" * 64)
    outcome = outcome.model_copy(
        update={
            "outcome_sha256": digest(outcome.model_dump(mode="json", exclude={"outcome_sha256"}))
        }
    )
    records.put("invocation-outcomes", claim.work_item.id, outcome)
    step = QueuedRoleStep(
        work_item=claim.work_item,
        boundary=RoleRunBoundary(
            task.id,
            AgentRole.CODER,
            2,
            claim.work_item.checkpoint_sequence,
            request.source_revision,
        ),
        allocation_sha256="1" * 64,
    )
    old_step = QueuedRoleStep(
        work_item=old_claim.work_item,
        boundary=RoleRunBoundary(
            task.id,
            AgentRole.CODER,
            1,
            old_claim.work_item.checkpoint_sequence,
            request.source_revision,
        ),
        allocation_sha256="1" * 64,
    )
    queue = _Queue(
        {claim.lease.id: claim, old_claim.lease.id: old_claim},
        {step.work_item.id: step, old_step.work_item.id: old_step},
        (
            AcceptedRoleArtifact(
                task_id=task.id,
                work_item_id=old_claim.work_item.id,
                lease_id=old_claim.lease.id,
                dispatch_sequence=0,
                checkpoint_sequence=old_claim.work_item.checkpoint_sequence,
                run_id=progress.producer.run_id,
                context_manifest_id=progress.context_manifest_id,
                source_revision=progress.source_revision,
                receipt=QueueArtifactReceipt(
                    artifact_id=progress.artifact_id, sha256=artifact_digest(progress)
                ),
            ),
        ),
    )
    (route,) = FileModelRouteAttemptStore(route_root, read_only=True).list_for_run(request.run_id)
    declaration = WorkspaceAdmissionAdapterContract(
        scope=scope,
        requirement_id="delivery_admission_fixture",
        task_id=task.id,
        work_item_id=claim.work_item.id,
        lease_id=claim.lease.id,
        claim_sha256=claim_identity_sha256(claim),
        run_id=request.run_id,
        source_revision=request.source_revision,
        invocation_start_sha256=start.start_sha256,
        invocation_outcome_sha256=outcome.outcome_sha256,
        route_attempt_sha256=route.attempt_sha256,
        platform_revision=SUPPORTED_ADAPTER_REVISION,
        adapter_sources=SUPPORTED_ADAPTER_SOURCES,
        deployment_evidence_id="fixture_current_operator_supplied_historical_evidence",
        deployment_evidence_sha256="d" * 64,
        service_instance_id="fixture_console_instance",
        service_process_birth="fixture-process-birth",
        deployment_observed_at=now,
    )
    fixture = _Fixture(
        f,
        task,
        claim,
        claim.work_item,
        step,
        queue,
        scope,
        state,
        route_root,
        artifacts,
        request,
        start,
        outcome,
        declaration,
        provider.calls,
    )
    if seal_declaration:
        fixture.declare()
    return fixture


def test_real_adapter_refusal_requires_exact_current_maintainer_declaration(tmp_path: Path) -> None:
    f = _fixture(tmp_path, seal_declaration=False)
    assert f.provider_calls == 0 and f.outcome.result.status is AgentRunStatus.FAILED
    with pytest.raises(ValueError, match="声明"):
        f.observe()
    f.declare()
    before = {path: path.read_bytes() for path in f.state.parent.rglob("*.json")}
    proof = f.observe()
    assert proof.reason == "PRESERVED_PROGRESS_CAPTURE_MISMATCH"
    assert proof.invocation_outcome_sha256 == f.outcome.outcome_sha256
    assert {path: path.read_bytes() for path in f.state.parent.rglob("*.json")} == before
    assert proof.workspace_inventory_sha256 == f.preserved.binding.after_inventory_sha256


def test_raw_unaccepted_output_cannot_hide_behind_filtered_runtime_store(tmp_path: Path) -> None:
    f = _fixture(tmp_path)
    accepted = f.artifacts.list_for_task(f.task.id)

    class AcceptedInputs(FileArtifactStore):
        def list_for_task(self, task_id: str) -> tuple[Artifact, ...]:
            assert task_id == f.task.id
            return accepted

    filtered = AcceptedInputs(f.state.parent / "artifacts", read_only=True)
    f.observe(artifacts=filtered)
    template = f.artifacts.get(f.preserved.progress.artifact_id)
    assert isinstance(template, CoderProgressArtifact)
    output = seal_artifact(
        template.model_copy(
            update={
                "artifact_id": "art_admission_unaccepted_output",
                "context_manifest_id": f.request.context_manifest_id,
                "producer": template.producer.model_copy(update={"run_id": f.request.run_id}),
            }
        ),
        validated_at=datetime.now(UTC),
    )
    f.artifacts.put(output)
    assert output not in filtered.list_for_task(f.task.id)
    with pytest.raises(ValueError, match="已有角色产出"):
        f.observe(artifacts=filtered)


@pytest.mark.parametrize(
    "change",
    [
        "body",
        "mode",
        "extra",
        "index",
        "claim",
        "accepted",
        "native_orphan",
        "native_start",
        "command",
        "route_alias",
        "extra_route",
        "generic_interruption",
        "missing_outcome",
        "ignored",
    ],
)
def test_observer_refuses_drift_or_contradictory_execution(tmp_path: Path, change: str) -> None:
    f = _fixture(tmp_path)
    f.observe()
    root = f.preserved.source.worktree.path
    if change == "body":
        (root / "src/retained.py").write_text("RETAINED = 99\n")
    elif change == "mode":
        (root / "src/retained.py").chmod(0o755)
    elif change == "extra":
        (root / "src/foreign.py").write_text("FOREIGN = 1\n")
    elif change == "index":
        from tests.git.test_worktree import _git

        _git(root, "add", "src/retained.py")
    elif change == "claim":
        f.queue.claims[f.claim.lease.id] = f.claim.model_copy(
            update={"lease": f.claim.lease.model_copy(update={"id": "lease_foreign"})}
        )
    elif change == "accepted":
        f.queue.publications = ()
    elif change == "native_orphan":
        path = f.state / "continuations" / f.task.id / f"capture-stop-{f.request.run_id}.json"
        path.write_text("{}")
    elif change == "native_start":
        native = FileContinuationStore(f.state / "continuations" / f.task.id, task_id=f.task.id)
        native.put_capture_start(
            ExecutionCaptureStart.create(
                scope=ContinuationScope(
                    team_id=f.scope.team_id,
                    project_id=f.scope.project_id,
                    repository_id=f.scope.repository_id,
                    requirement_id="delivery_admission_fixture",
                    dispatch_sha256="1" * 64,
                ),
                request=f.request,
                claim=f.claim,
                task_intent_sha256=task_intent_sha256(f.task),
                task_revision=f.item.checkpoint_sequence,
                policy_sha256="1" * 64,
                worktree_path=str(root),
                inventory_before=capture_mutation_inventory(root),
                started_at=datetime.now(UTC),
            )
        )
    elif change == "command":
        evidence = seal_evidence_record(
            CommandEvidenceRecord(
                evidence_id="ev_admission_command",
                kind=EvidenceKind.COMMAND,
                operation_id="admission.command",
                identity=RunEvidenceIdentity(
                    repository_id=f.scope.repository_id,
                    task_id=f.task.id,
                    run_id=f.request.run_id,
                    agent_id=f.claim.assignment.agent_id,
                    role=AgentRole.CODER,
                    attempt=2,
                    source_revision=f.request.source_revision,
                    context_manifest_id=f.request.context_manifest_id,
                ),
                description="A contradictory completed tool command",
                captured_at=datetime.now(UTC),
                record_sha256="0" * 64,
                payload=CommandEvidencePayload(
                    outcome=CommandOutcome.COMPLETED,
                    argv=("git", "status"),
                    cwd=str(root),
                    returncode=0,
                    duration_ms=1,
                ),
            )
        )
        FileEvidenceStore(f.state.parent / "evidence", f.state.parent / "runs").put(evidence)
    elif change in {"route_alias", "extra_route"}:
        request = (
            f.request.model_copy(update={"run_id": "run_admission_alias"})
            if change == "route_alias"
            else f.request
        )
        result = f.outcome.result.model_copy(update={"run_id": request.run_id})
        at = datetime.now(UTC)
        route = ModelRouteAttempt.create(
            request=request,
            route_index=1 if change == "route_alias" else 2,
            provider="codex",
            model="fixture",
            route_kind="codex_cli",
            started_at=at,
            completed_at=at,
            result=result,
            fallback=False,
        )
        FileModelRouteAttemptStore(f.route_root).append(route)
    elif change == "generic_interruption":
        assert f.outcome.result.error is not None
        result = f.outcome.result.model_copy(
            update={
                "error": f.outcome.result.error.model_copy(
                    update={"message": "ordinary interrupted provider call"}
                )
            }
        )
        outcome = f.outcome.model_copy(update={"result": result, "outcome_sha256": "0" * 64})
        outcome = outcome.model_copy(
            update={
                "outcome_sha256": digest(
                    outcome.model_dump(mode="json", exclude={"outcome_sha256"})
                )
            }
        )
        records = KnowledgeRecordStore(f.state / "invocations")
        path = records.root / records._name("invocation-outcomes", f.item.id)
        path.write_text(
            json.dumps({"record": outcome.to_wire(), "sha256": digest(outcome.to_wire())})
        )
    elif change == "missing_outcome":
        records = KnowledgeRecordStore(f.state / "invocations")
        (records.root / records._name("invocation-outcomes", f.item.id)).unlink()
    elif change == "ignored":
        (root / ".pytest_cache").mkdir()
        (root / ".pytest_cache/new").write_text("not an approved inventory item")
    with pytest.raises((ValueError, WorkspacePolicyError, ContinuationRejected, KnowledgeError)):
        f.observe()
