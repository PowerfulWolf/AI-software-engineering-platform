"""Current engineering testimony cannot replace original execution facts."""

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.agents.fallback import FileModelRouteAttemptStore, ModelRouteAttempt
from ai_software_engineer.agents.models import AgentErrorCode, AgentFailure, AgentRunStatus
from ai_software_engineer.domain.engineering_authority import (
    EngineeringScope,
    LocalOperatorPrincipal,
    OperatorDuty,
)
from ai_software_engineer.domain.workspace_admission_contract import (
    WorkspaceAdmissionAdapterContract,
    WorkspaceAdmissionAdapterContractRecord,
)
from ai_software_engineer.evaluation import (
    HumanAction,
    HumanActionEvent,
    InMemoryEvaluationEventStore,
)
from ai_software_engineer.knowledge.audit import KnowledgeHumanActionRecorder
from ai_software_engineer.knowledge.claim_identity import claim_identity_sha256
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.manager.legacy_audit import EngineeringHumanActionRecorder
from ai_software_engineer.manager.workspace_admission_contract import (
    SUPPORTED_ADAPTER_REVISION,
    SUPPORTED_ADAPTER_SOURCES,
    WorkspaceAdmissionAdapterContractStore,
    seal_workspace_admission_adapter_contract,
)
from ai_software_engineer.multi_directory.purge_state import (
    StateDeletionScope,
    task_state_directories,
)
from tests.manager.test_delivery_wait import WaitQueue, _outcome, native
from tests.orchestration.test_native_continuation import NOW, Fixture

__all__ = ["native"]


@dataclass(frozen=True)
class ContractFixture:
    native: Fixture
    queue: WaitQueue
    root: Path
    scope: EngineeringScope
    declaration: WorkspaceAdmissionAdapterContract

    def seal(
        self,
        declaration: WorkspaceAdmissionAdapterContract | None = None,
        principal: LocalOperatorPrincipal | None = None,
    ) -> WorkspaceAdmissionAdapterContractRecord:
        return seal_workspace_admission_adapter_contract(
            state=self.root,
            declaration=declaration or self.declaration,
            principal=principal or LocalOperatorPrincipal.trusted_local(),
            task=self.native.repository.get(self.native.task.id),
            item=self.queue.item,
            step=self.queue.bound,
            scope=self.scope,
            route_root=self.root / "routes",
            queue=self.queue,
            requirement_id=self.native.task.id,
            at=NOW + timedelta(seconds=2),
        )


@pytest.fixture
def contract(native: Fixture, tmp_path: Path) -> ContractFixture:
    state = tmp_path / "sidecar/state"
    state.mkdir(parents=True)
    queue = WaitQueue(native)
    result = native.result().model_copy(
        update={
            "status": AgentRunStatus.FAILED,
            "artifact": None,
            "usage": None,
            "error": AgentFailure(
                code=AgentErrorCode.WORK_INTERRUPTED,
                message="恢复工作区准入校验未通过。未调用模型。现场已保留。请查看平台恢复检查结果。",
                transient=False,
            ),
        }
    )
    outcome = _outcome(native, queue, state, result)
    route = ModelRouteAttempt.create(
        request=outcome.start.request,
        route_index=1,
        provider="codex",
        model="fixture-model",
        route_kind="codex_cli",
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        result=result,
        fallback=False,
    )
    FileModelRouteAttemptStore(state / "routes").append(route)
    scope = EngineeringScope(
        team_id=native.scope.team_id,
        project_id=native.scope.project_id,
        repository_id=native.scope.repository_id,
        repository_root=native.task.repository,
    )
    declaration = WorkspaceAdmissionAdapterContract(
        scope=scope,
        requirement_id=native.task.id,
        task_id=native.task.id,
        work_item_id=queue.item.id,
        lease_id=queue.original.lease.id,
        claim_sha256=claim_identity_sha256(queue.original),
        run_id=outcome.start.request.run_id,
        source_revision=outcome.start.request.source_revision,
        invocation_start_sha256=outcome.start.start_sha256,
        invocation_outcome_sha256=outcome.outcome_sha256,
        route_attempt_sha256=route.attempt_sha256,
        platform_revision=SUPPORTED_ADAPTER_REVISION,
        adapter_sources=SUPPORTED_ADAPTER_SOURCES,
        deployment_evidence_id="deployment-audit-fixture",
        deployment_evidence_sha256="a" * 64,
        service_instance_id="console_instance_fixture",
        service_process_birth="fixture-birth:12345",
        deployment_observed_at=NOW - timedelta(seconds=1),
    )
    return ContractFixture(native, queue, state, scope, declaration)


def test_public_seal_preserves_original_records_and_replays_exact_testimony(
    contract: ContractFixture,
) -> None:
    original = {path: path.read_bytes() for path in (contract.root / "invocations").glob("*.json")}
    record = contract.seal()
    record.validate_integrity()
    assert record == contract.seal()
    assert record.declaration == contract.declaration
    assert record.submitted_at == NOW + timedelta(seconds=2)
    assert record.attribution == "current_operator_supplied_historical_deployment_evidence"
    assert (
        WorkspaceAdmissionAdapterContractStore(contract.root, contract.native.task.id).for_run(
            contract.declaration.run_id
        )
        == record
    )
    assert all(path.read_bytes() == body for path, body in original.items())
    assert not (contract.root / "continuations" / contract.native.task.id / "captures").exists()


@pytest.mark.parametrize(
    "mutation", ["principal", "revision", "manifest", "scope", "claim", "outcome", "route", "time"]
)
def test_invalid_engineering_testimony_never_publishes(
    contract: ContractFixture, mutation: str
) -> None:
    declaration = contract.declaration
    principal = LocalOperatorPrincipal.trusted_local()
    if mutation == "principal":
        principal = LocalOperatorPrincipal(
            operator_id="product:fixture", duties=(OperatorDuty.PRODUCT,)
        )
    elif mutation == "revision":
        declaration = declaration.model_copy(update={"platform_revision": "f" * 40})
    elif mutation == "manifest":
        sources = (
            declaration.adapter_sources[0].model_copy(update={"sha256": "f" * 64}),
            *declaration.adapter_sources[1:],
        )
        declaration = declaration.model_copy(update={"adapter_sources": sources})
    elif mutation == "scope":
        declaration = declaration.model_copy(
            update={"scope": declaration.scope.model_copy(update={"project_id": "project_foreign"})}
        )
    elif mutation == "claim":
        declaration = declaration.model_copy(update={"claim_sha256": "f" * 64})
    elif mutation == "outcome":
        declaration = declaration.model_copy(update={"invocation_outcome_sha256": "f" * 64})
    elif mutation == "route":
        declaration = declaration.model_copy(update={"route_attempt_sha256": "f" * 64})
    else:
        declaration = declaration.model_copy(
            update={"deployment_observed_at": NOW + timedelta(seconds=1)}
        )
    with pytest.raises(ValueError):
        contract.seal(declaration, principal)
    assert (
        WorkspaceAdmissionAdapterContractStore(contract.root, contract.native.task.id).for_run(
            contract.declaration.run_id
        )
        is None
    )


def test_changed_existing_testimony_and_corrupt_seal_fail_closed(contract: ContractFixture) -> None:
    record = contract.seal()
    changed = contract.declaration.model_copy(update={"deployment_evidence_sha256": "f" * 64})
    with pytest.raises(ValueError, match="不可改写"):
        contract.seal(changed)
    with pytest.raises(ValueError, match="integrity"):
        record.model_copy(update={"contract_sha256": "f" * 64}).validate_integrity()


def test_unique_route_for_a_different_request_cannot_support_testimony(
    contract: ContractFixture,
) -> None:
    routes = FileModelRouteAttemptStore(contract.root / "routes")
    (original,) = routes.list_for_run(contract.declaration.run_id)
    foreign = original.model_copy(update={"request_sha256": "f" * 64})
    payload = foreign.to_wire()
    payload.pop("attempt_sha256")
    foreign = foreign.model_copy(update={"attempt_sha256": digest(payload)})
    for path in (contract.root / "routes").rglob("*.json"):
        path.unlink()
    routes.append(foreign)
    declaration = contract.declaration.model_copy(
        update={"route_attempt_sha256": foreign.attempt_sha256}
    )
    with pytest.raises(ValueError, match="原调用、路由"):
        contract.seal(declaration)
    assert (
        WorkspaceAdmissionAdapterContractStore(contract.root, contract.native.task.id).for_run(
            contract.declaration.run_id
        )
        is None
    )


def test_human_supplied_evidence_is_audited_even_without_old_baseline_store(
    contract: ContractFixture,
) -> None:
    record = contract.seal()
    recorder = EngineeringHumanActionRecorder(
        KnowledgeHumanActionRecorder(()), contract.root / "execution-baselines"
    )
    events = InMemoryEvaluationEventStore()
    recorder.record(contract.native.task, "case_workspace_admission", events)
    recorder.record(contract.native.task, "case_workspace_admission", events)
    history = events.list_for_case("case_workspace_admission")
    assert len(history) == 1
    event = history[0]
    assert isinstance(event, HumanActionEvent)
    assert event.action is HumanAction.SUPPLY_EVIDENCE
    assert event.occurred_at == record.submitted_at
    assert event.evidence_uri and "adapter-declarations-" in event.evidence_uri
    assert event.note and "原调用没有自动版本回执" in event.note


def test_task_physical_deletion_includes_only_fully_validated_declaration_tree(
    contract: ContractFixture,
) -> None:
    contract.seal()
    expected = StateDeletionScope(
        team_id=contract.scope.team_id,
        project_id=contract.scope.project_id,
        repository_id=contract.scope.repository_id,
        repository_root=contract.scope.repository_root,
        requirement_ids=frozenset({contract.declaration.requirement_id}),
        task_ids=frozenset({contract.native.task.id}),
    )
    store = WorkspaceAdmissionAdapterContractStore(contract.root, contract.native.task.id)
    assert task_state_directories(contract.root.parent, expected) == (store.root.parent,)
    for field in ("team_id", "project_id", "repository_id", "repository_root"):
        with pytest.raises(ValueError, match="differs"):
            task_state_directories(
                contract.root.parent, expected.model_copy(update={field: "foreign"})
            )
    with pytest.raises(ValueError, match="Requirement differs"):
        task_state_directories(
            contract.root.parent,
            expected.model_copy(update={"requirement_ids": frozenset({"delivery_foreign"})}),
        )
    (store.root / "unrecognized.json").write_text("{}\n")
    with pytest.raises(ValueError, match="unsupported workspace admission declaration"):
        task_state_directories(contract.root.parent, expected)
