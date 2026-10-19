"""Public wait handling recognizes only positive trusted workspace refusal evidence."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_software_engineer.agents.models import AgentErrorCode, AgentFailure, AgentRunStatus
from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolutionKind,
    HandleDeliveryWait,
    RejectedWorkspaceAdmissionEvidence,
    ResolveDeliveryWait,
)
from ai_software_engineer.domain.engineering_authority import EngineeringScope
from ai_software_engineer.domain.workspace_admission_contract import (
    WorkspaceAdmissionAdapterContract,
)
from ai_software_engineer.knowledge.claim_identity import claim_identity_sha256
from ai_software_engineer.manager.delivery_wait import DeliveryWaitRejected
from tests.manager.test_delivery_wait import (
    WaitQueue,
    _handling_policy,
    _outcome,
    _reject_wait,
    native,
    service,
)
from tests.orchestration.test_native_continuation import NOW, Fixture

__all__ = ["native"]


def _setup(
    native: Fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[WaitQueue, RejectedWorkspaceAdmissionEvidence, Mock]:
    queue = WaitQueue(native)
    _reject_wait(queue, "NONTRANSIENT_INFRA")
    result = native.result().model_copy(
        update={
            "status": AgentRunStatus.FAILED,
            "artifact": None,
            "error": AgentFailure(
                code=AgentErrorCode.WORK_INTERRUPTED,
                message="trusted fixture refusal",
                transient=False,
            ),
        }
    )
    outcome = _outcome(native, queue, tmp_path, result)
    proof = RejectedWorkspaceAdmissionEvidence(
        scope=EngineeringScope(
            team_id=native.scope.team_id,
            project_id=native.scope.project_id,
            repository_id=native.scope.repository_id,
            repository_root=native.task.repository,
        ),
        requirement_id=native.task.id,
        task_id=native.task.id,
        work_item_id=queue.item.id,
        role=AgentRole.CODER,
        checkpoint_sequence=queue.item.checkpoint_sequence,
        attempt=queue.item.attempt,
        dispatch_sequence=queue.item.dispatch_sequence,
        lease_id=queue.original.lease.id,
        claim_sha256=claim_identity_sha256(queue.original),
        run_id=outcome.start.request.run_id,
        context_manifest_id=outcome.start.request.context_manifest_id,
        source_revision=outcome.start.request.source_revision,
        invocation_start_sha256=outcome.start.start_sha256,
        invocation_outcome_sha256=outcome.outcome_sha256,
        route_attempt_sha256="a" * 64,
        context_sha256="b" * 64,
        baseline_binding_sha256="c" * 64,
        baseline_plan_sha256="d" * 64,
        progress_artifact_id="art_progress_fixture",
        progress_sha256="e" * 64,
        workspace_inventory_sha256="f" * 64,
        workspace_capture_sha256="a" * 64,
        adapter_contract_sha256="b" * 64,
        observation_sha256="0" * 64,
    )
    proof = proof.model_copy(update={"observation_sha256": proof.recompute_sha256()})
    monkeypatch.setattr(
        "ai_software_engineer.manager.delivery_wait.model_route_root",
        lambda sidecar: tmp_path / "routes",
    )
    observer = Mock(return_value=proof)
    monkeypatch.setattr(
        "ai_software_engineer.manager.delivery_wait.rejected_workspace_admission_evidence", observer
    )
    return queue, proof, observer


def test_handle_bypasses_native_stop_collection_only_with_positive_adapter_proof(
    native: Fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, expected, observer = _setup(native, tmp_path, monkeypatch)
    entry = service(native, queue, tmp_path)
    entry.artifacts = FileArtifactStore(tmp_path / "artifacts")
    collector = Mock(
        side_effect=AssertionError("trusted no-provider refusal cannot invent native stop")
    )
    entry.fact_collector = collector
    before = native.repository.get(native.task.id)
    handling = entry.handle(HandleDeliveryWait.model_validate(queue.command().to_wire()))
    assert handling.status == "NEEDS_AUTHORIZATION" and handling.manual_resolution_allowed
    assert handling.investigation.rejected_workspace_admission == expected
    assert handling.investigation.process_stop_sha256 is None
    assert handling.investigation.interruption_receipt_sha256 is None
    assert handling.investigation.permitted_resolutions == (
        DeliveryResolutionKind.RETRY_REJECTED_WORKSPACE_ADMISSION,
    )
    assert not collector.called and observer.call_count >= 2
    assert native.repository.get(native.task.id) == before
    decision = entry.resolve(
        ResolveDeliveryWait.model_validate(
            {
                **queue.command().to_wire(),
                "resolution_kind": "RETRY_REJECTED_WORKSPACE_ADMISSION",
                "proof_sha256": handling.investigation.proof_sha256,
                "submitted_at": NOW + timedelta(seconds=2),
            }
        )
    )
    assert decision.rejected_workspace_admission == expected and queue.consumed == [decision]


def test_missing_adapter_proof_keeps_generic_stop_collection_and_never_authorizes(
    native: Fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, _, observer = _setup(native, tmp_path, monkeypatch)
    observer.side_effect = ValueError("not trusted")
    entry = service(native, queue, tmp_path)
    entry.artifacts = FileArtifactStore(tmp_path / "artifacts")
    collector = Mock()
    entry.fact_collector = collector
    handling = entry.handle(HandleDeliveryWait.model_validate(queue.command().to_wire()))
    assert collector.call_count == 1
    assert handling.status == "PLATFORM_ATTENTION" and handling.resolution is None
    assert handling.investigation.rejected_workspace_admission is None
    assert not handling.investigation.permitted_resolutions and not queue.consumed


def test_unconsumed_resolution_rechecks_original_workspace_before_replay(
    native: Fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue, _, observer = _setup(native, tmp_path, monkeypatch)
    entry = service(native, queue, tmp_path)
    entry.artifacts = FileArtifactStore(tmp_path / "artifacts")
    proof = entry.inspect(queue.command())
    command = ResolveDeliveryWait.model_validate(
        {
            **queue.command().to_wire(),
            "resolution_kind": "RETRY_REJECTED_WORKSPACE_ADMISSION",
            "proof_sha256": proof.proof_sha256,
            "submitted_at": NOW + timedelta(seconds=2),
        }
    )
    consume = Mock(side_effect=RuntimeError("crash after decision sealed"))
    entry.consume = consume
    with pytest.raises(RuntimeError, match="crash"):
        entry.resolve(command)
    observer.side_effect = ValueError("workspace changed")
    with pytest.raises(DeliveryWaitRejected, match="变化"):
        entry.resolve(command)
    assert consume.call_count == 1 and not queue.consumed


def _declaration(
    native: Fixture, queue: WaitQueue, root: Path
) -> WorkspaceAdmissionAdapterContract:
    from ai_software_engineer.agents.fallback import (
        FileModelRouteAttemptStore,
        ModelRouteAttempt,
    )
    from ai_software_engineer.domain.workspace_admission_contract import (
        WorkspaceAdmissionAdapterContract,
    )
    from ai_software_engineer.knowledge.store import KnowledgeRecordStore
    from ai_software_engineer.manager.workspace_admission_contract import (
        SUPPORTED_ADAPTER_REVISION,
        SUPPORTED_ADAPTER_SOURCES,
    )
    from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome

    outcome = KnowledgeRecordStore(root / "invocations").get(
        "invocation-outcomes", queue.item.id, DeliveryInvocationOutcome
    )
    route = ModelRouteAttempt.create(
        request=outcome.start.request,
        route_index=1,
        provider="codex",
        model="fixture",
        route_kind="codex_cli",
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        result=outcome.result,
        fallback=False,
    )
    FileModelRouteAttemptStore(root / "routes").append(route)
    return WorkspaceAdmissionAdapterContract(
        scope=EngineeringScope(
            team_id=native.scope.team_id,
            project_id=native.scope.project_id,
            repository_id=native.scope.repository_id,
            repository_root=native.task.repository,
        ),
        requirement_id=native.task.id,
        task_id=native.task.id,
        work_item_id=queue.item.id,
        lease_id=outcome.start.lease_id,
        claim_sha256=claim_identity_sha256(queue.original),
        run_id=outcome.start.request.run_id,
        source_revision=outcome.start.request.source_revision,
        invocation_start_sha256=outcome.start.start_sha256,
        invocation_outcome_sha256=outcome.outcome_sha256,
        route_attempt_sha256=route.attempt_sha256,
        platform_revision=SUPPORTED_ADAPTER_REVISION,
        adapter_sources=SUPPORTED_ADAPTER_SOURCES,
        deployment_evidence_id="fixture_deployment_audit",
        deployment_evidence_sha256="a" * 64,
        service_instance_id="fixture_host",
        service_process_birth="fixture_birth",
        deployment_observed_at=NOW,
    )


def test_public_handle_declaration_is_sealed_then_excluded_from_resolution_input(
    native: Fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.manager.workspace_admission_contract import (
        WorkspaceAdmissionAdapterContractStore,
    )

    queue, expected, _ = _setup(native, tmp_path, monkeypatch)
    declaration = _declaration(native, queue, tmp_path)
    entry = service(native, queue, tmp_path)
    entry.artifacts = FileArtifactStore(tmp_path / "artifacts")
    handling = entry.handle(
        HandleDeliveryWait.model_validate(
            {
                **queue.command().to_wire(),
                "workspace_admission_adapter_contract": declaration.to_wire(),
            }
        )
    )
    assert handling.status == "NEEDS_AUTHORIZATION" and handling.manual_resolution_allowed
    assert handling.investigation.rejected_workspace_admission == expected
    record = WorkspaceAdmissionAdapterContractStore(tmp_path, native.task.id).for_run(
        declaration.run_id
    )
    assert record is not None and record.declaration == declaration
    assert not queue.consumed


@pytest.mark.parametrize("mutation", ["revision", "deployment", "scope", "task", "run"])
def test_public_handle_replay_refuses_changed_supplied_contract_before_old_success(
    native: Fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    from ai_software_engineer.manager.engineering_authority import EngineeringAuthority

    _handling_policy(native, tmp_path)
    queue, _, _ = _setup(native, tmp_path, monkeypatch)
    declaration = _declaration(native, queue, tmp_path)
    entry = service(native, queue, tmp_path)
    entry.artifacts = FileArtifactStore(tmp_path / "artifacts")
    authority = tmp_path / "authority"
    authority.mkdir()
    entry.engineering_authority = EngineeringAuthority(authority)
    command = HandleDeliveryWait.model_validate(
        {
            **queue.command().to_wire(),
            "workspace_admission_adapter_contract": declaration.to_wire(),
        }
    )
    handling = entry.handle(command)
    assert handling.status == "RESOLVED" and handling.resolution is not None
    assert entry.records.get("wait-handlings", handling.record_key, type(handling)) == handling
    changed = declaration.to_wire()
    if mutation == "revision":
        changed["platform_revision"] = "f" * 40
    elif mutation == "deployment":
        changed["deployment_evidence_sha256"] = "b" * 64
    elif mutation == "scope":
        changed["scope"] = {**declaration.scope.to_wire(), "project_id": "project_foreign"}
    elif mutation == "task":
        changed["task_id"] = "task_foreign"
    else:
        changed["run_id"] = "run_foreign"
    with pytest.raises(DeliveryWaitRejected):
        entry.handle(
            HandleDeliveryWait.model_validate(
                {
                    **queue.command().to_wire(),
                    "workspace_admission_adapter_contract": changed,
                }
            )
        )
    assert len(queue.consumed) == 1
    # An unchanged exact declaration and old clients omitting it both remain replayable.
    assert entry.handle(command).status == "RESOLVED"
    assert (
        entry.handle(HandleDeliveryWait.model_validate(queue.command().to_wire())).status
        == "RESOLVED"
    )


def test_manual_resolution_followed_by_handle_preserves_original_handling_and_aliases_result(
    native: Fixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_software_engineer.domain.delivery_resolution import DeliveryWaitHandling
    from ai_software_engineer.knowledge.models import digest

    queue, _, _ = _setup(native, tmp_path, monkeypatch)
    declaration = _declaration(native, queue, tmp_path)
    entry = service(native, queue, tmp_path)
    entry.artifacts = FileArtifactStore(tmp_path / "artifacts")
    command = HandleDeliveryWait.model_validate(
        {
            **queue.command().to_wire(),
            "workspace_admission_adapter_contract": declaration.to_wire(),
        }
    )
    initial = entry.handle(command)
    assert initial.status == "NEEDS_AUTHORIZATION"
    key = initial.record_key
    original_path = entry.records.root / entry.records._name("wait-handlings", key)
    original_bytes = original_path.read_bytes()
    decision = entry.resolve(
        ResolveDeliveryWait.model_validate(
            {
                **queue.command().to_wire(),
                "resolution_kind": "RETRY_REJECTED_WORKSPACE_ADMISSION",
                "proof_sha256": initial.investigation.proof_sha256,
                "submitted_at": NOW + timedelta(seconds=2),
            }
        )
    )
    resolved = entry.handle(command)
    assert resolved.status == "RESOLVED" and resolved.resolution == decision
    assert original_path.read_bytes() == original_bytes
    assert entry.records.get("wait-handlings", key, DeliveryWaitHandling) == initial
    alias = digest(queue.command().to_wire())
    assert entry.records.get("wait-handling-resolutions", alias, DeliveryWaitHandling) == resolved
    assert entry.handle(command) == resolved
    assert entry.handle(HandleDeliveryWait.model_validate(queue.command().to_wire())) == resolved
    assert len(queue.consumed) == 1
    workspace = decision.rejected_workspace_admission
    assert workspace is not None
    workspace = workspace.model_copy(update={"workspace_capture_sha256": "f" * 64})
    workspace = workspace.model_copy(update={"observation_sha256": workspace.recompute_sha256()})
    changed = decision.model_copy(update={"rejected_workspace_admission": workspace})
    changed = changed.model_copy(update={"resolution_sha256": changed.recompute_sha256()})
    with pytest.raises(ValueError, match="proof"):
        DeliveryWaitHandling.model_validate({**resolved.to_wire(), "resolution": changed.to_wire()})
