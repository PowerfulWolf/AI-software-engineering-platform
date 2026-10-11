"""Current role phases are derived only from exact immutable invocation facts."""

import json
import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.agents.models import (
    AgentErrorCode,
    AgentFailure,
    AgentRequest,
    AgentResult,
    AgentRunStatus,
)
from ai_software_engineer.agents.structured_observation import (
    StructuredCallIdentity,
    StructuredExecutionAdmission,
    StructuredHttpRoundTripReceipt,
)
from ai_software_engineer.domain.agent import AgentPermissions
from ai_software_engineer.domain.enums import (
    AgentRole,
    BrainTier,
    ModelRouteReason,
    NetworkAccess,
    RiskTier,
    TeamRole,
    WorkItemStatus,
)
from ai_software_engineer.domain.workforce import ModelSelection, RoleAssignment, TaskLease
from ai_software_engineer.knowledge.invocation import (
    KnowledgeExecutionRecord,
    KnowledgeInvocationIntent,
    KnowledgeInvocationOutcome,
    KnowledgeInvocationResult,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.models import KnowledgeError, KnowledgeRunBinding, digest
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.team_view.knowledge_preparation import (
    RoleExecutionScope,
    read_execution_phase,
)
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim, QueuedWorkItem

NOW = datetime(2026, 10, 11, tzinfo=UTC)


@dataclass(frozen=True)
class Fixture:
    scope: RoleExecutionScope
    claim: QueueClaim

    @property
    def item(self) -> QueuedWorkItem:
        return self.claim.work_item.model_copy(update={"status": WorkItemStatus.RUNNING})

    def phase(self) -> str | None:
        return read_execution_phase(
            scope=self.scope,
            item=self.item,
            assignment=self.claim.assignment,
            lease=self.claim.lease,
        )

    def intent(self, **changes: object) -> KnowledgeInvocationIntent:
        bound = KnowledgeRunBinding.model_validate(
            {
                "team_id": self.scope.team_id,
                "project_id": self.scope.project_id,
                "requirement_id": self.scope.requirement_id,
                "repository_ids": (self.item.repository_id,),
                "task_id": self.item.task_id,
                "role": TeamRole(self.item.role.value),
                "source_revision": self.scope.source_revision,
                "run_id": "run_knowledge_phase",
                "context_manifest_id": "ctx_" + "b" * 64,
                "snapshot_sha256": "c" * 64,
                **changes,
            }
        )
        intent = KnowledgeInvocationIntent.create(
            binding=bound,
            phase="intent",
            request_sha256="d" * 64,
            timeout_seconds=2,
            claim=self.claim,
            created_at=NOW + timedelta(seconds=1),
        )
        self.records(intent).put("knowledge-invocation-intents", bound.run_id + ":intent", intent)
        return intent

    def records(self, intent: KnowledgeInvocationIntent) -> KnowledgeRecordStore:
        return KnowledgeRecordStore(
            self.scope.sidecar
            / "knowledge"
            / "runs"
            / "invocations"
            / invocation_lane_sha256(intent.binding)
        )

    def main(self, *, complete: bool = False, **changes: object) -> None:
        request = AgentRequest(
            run_id="run_role_phase",
            task_id=self.item.task_id,
            role=self.item.role,
            attempt=self.item.attempt,
            source_revision=self.scope.source_revision,
            context_manifest_id="ctx_" + "b" * 64,
            input_artifact_ids=(),
            permissions=AgentPermissions(
                read_paths=("**",), write_paths=("src/**",), commands=(), network=NetworkAccess.NONE
            ),
            output_schema="schemas/coder-output.schema.json",
            timeout_seconds=2,
        )
        start = DeliveryInvocationStart.model_validate(
            {
                "work_item_id": self.item.id,
                "checkpoint_sequence": self.item.checkpoint_sequence,
                "request": request,
                "lease_id": self.claim.lease.id,
                "started_at": NOW + timedelta(seconds=2),
                "start_sha256": "0" * 64,
                **changes,
            }
        )
        start = start.model_copy(
            update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
        )
        records = KnowledgeRecordStore(self.scope.sidecar / "state" / "invocations")
        records.put("invocation-starts", self.item.id, start)
        if complete:
            result = AgentResult(
                run_id=request.run_id,
                task_id=request.task_id,
                role=request.role,
                attempt=request.attempt,
                source_revision=request.source_revision,
                context_manifest_id=request.context_manifest_id,
                status=AgentRunStatus.FAILED,
                error=AgentFailure(
                    code=AgentErrorCode.PROVIDER_UNAVAILABLE, message="fixture", transient=True
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
            records.put("invocation-outcomes", self.item.id, outcome)


def fixture(tmp_path: Path) -> Fixture:
    item = QueuedWorkItem(
        id="work_knowledge_phase",
        task_id="task_knowledge_phase",
        repository_id="repository_phase",
        role=AgentRole.CODER,
        attempt=2,
        checkpoint_sequence=5,
        dispatch_sequence=3,
        repository_scopes=("/workspace/repository",),
        status=WorkItemStatus.LEASED,
        priority=500,
        risk=RiskTier.NORMAL,
        required_capabilities=("python",),
        created_at=NOW,
        updated_at=NOW,
    )
    assignment = RoleAssignment(
        id="assignment_phase",
        repository_id=item.repository_id,
        task_id=item.task_id,
        agent_id="agent_phase_coder",
        role=item.role,
        attempt=item.attempt,
        lease_id="lease_phase",
        assigned_at=NOW,
    )
    lease = TaskLease(
        id=assignment.lease_id,
        assignment_id=assignment.id,
        task_id=item.task_id,
        agent_id=assignment.agent_id,
        acquired_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    claim = QueueClaim(
        work_item=item,
        assignment=assignment,
        lease=lease,
        worker_id="worker_phase",
        model_selection=ModelSelection(
            policy_id="model_policy_phase",
            policy_version="v1",
            provider="fixture",
            model="fixture",
            tier=BrainTier.STANDARD,
            reasons=(ModelRouteReason.DEFAULT,),
            selected_at=NOW,
        ),
        claimed_at=NOW,
    )
    return Fixture(
        RoleExecutionScope(
            tmp_path / "sidecar", "team_phase", "project_phase", "delivery_multi_phase", "a" * 40
        ),
        claim,
    )


def test_missing_legacy_records_are_neutral_and_do_not_create_directories(tmp_path: Path) -> None:
    view = fixture(tmp_path)
    assert view.phase() is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("complete", [False, True])
def test_current_knowledge_receipt_never_claims_main_role_started(
    tmp_path: Path, complete: bool
) -> None:
    view = fixture(tmp_path)
    intent = view.intent()
    if complete:
        outcome = KnowledgeInvocationOutcome.create(
            intent=intent,
            state="RETURNED",
            result=KnowledgeInvocationResult(payload={"queries": []}, duration_ms=2),
            completed_at=NOW + timedelta(seconds=2),
        )
        view.records(intent).put(
            "knowledge-invocation-outcomes", intent.binding.run_id + ":intent", outcome
        )
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    assert view.phase() == "KNOWLEDGE_PREPARATION"
    assert {path: path.read_bytes() for path in tmp_path.rglob("*.json")} == before


def test_renewed_current_lease_preserves_original_claim_phase(tmp_path: Path) -> None:
    view = fixture(tmp_path)
    view.intent()
    current = view.claim.model_copy(
        update={
            "lease": view.claim.lease.model_copy(update={"expires_at": NOW + timedelta(hours=1)})
        }
    )
    assert replace(view, claim=current).phase() == "KNOWLEDGE_PREPARATION"


@pytest.mark.parametrize(
    "field", ["attempt", "checkpoint_sequence", "dispatch_sequence", "repository_scopes"]
)
def test_changed_work_identity_does_not_reuse_historical_phase(tmp_path: Path, field: str) -> None:
    view = fixture(tmp_path)
    view.intent()
    old = getattr(view.item, field)
    changed = ("/workspace/other",) if field == "repository_scopes" else old + 1
    current = view.claim.model_copy(
        update={"work_item": view.claim.work_item.model_copy(update={field: changed})}
    )
    assert replace(view, claim=current).phase() is None


@pytest.mark.parametrize("field", ["team_id", "project_id", "requirement_id", "source_revision"])
def test_other_scope_or_source_does_not_supply_current_phase(tmp_path: Path, field: str) -> None:
    view = fixture(tmp_path)
    view.intent(
        **{
            field: "team_other"
            if field == "team_id"
            else "project_other"
            if field == "project_id"
            else "other_scope"
        }
    )
    assert view.phase() is None


def test_old_lease_does_not_supply_current_phase(tmp_path: Path) -> None:
    view = fixture(tmp_path)
    view.intent()
    current = view.claim.model_copy(
        update={
            "assignment": view.claim.assignment.model_copy(update={"lease_id": "lease_new_phase"}),
            "lease": view.claim.lease.model_copy(update={"id": "lease_new_phase"}),
        }
    )
    assert replace(view, claim=current).phase() is None


def test_known_task_id_legacy_scope_is_explicitly_supported(tmp_path: Path) -> None:
    view = fixture(tmp_path)
    view.intent(requirement_id=view.item.task_id)
    assert view.phase() == "KNOWLEDGE_PREPARATION"


@pytest.mark.parametrize(("complete", "phase"), [(False, "ROLE_EXECUTION"), (True, "FINALIZING")])
def test_current_main_invocation_takes_precedence_over_knowledge(
    tmp_path: Path, complete: bool, phase: str
) -> None:
    view = fixture(tmp_path)
    view.intent()
    view.main(complete=complete)
    assert view.phase() == phase


def test_old_main_lease_cannot_claim_main_execution(tmp_path: Path) -> None:
    view = fixture(tmp_path)
    view.main(lease_id="lease_old_phase")
    assert view.phase() is None


@pytest.mark.parametrize("unsafe", ["digest", "symlink", "fifo", "oversize"])
def test_unsafe_current_receipts_fail_closed(
    tmp_path: Path, unsafe: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = fixture(tmp_path)
    intent = view.intent()
    path = next(view.records(intent).root.glob("knowledge-invocation-intents-*.json"))
    if unsafe == "digest":
        payload = json.loads(path.read_text())
        payload["record"]["timeout_seconds"] = 7
        path.write_text(json.dumps(payload))
    elif unsafe == "symlink":
        target = tmp_path / "other.json"
        path.rename(target)
        path.symlink_to(target)
    elif unsafe == "fifo":
        path.unlink()
        os.mkfifo(path)
    else:
        monkeypatch.setattr("ai_software_engineer.knowledge.store._MAX_BYTES", 128)
    with pytest.raises(KnowledgeError):
        view.phase()


def test_dangling_legacy_store_link_is_unsafe_not_missing(tmp_path: Path) -> None:
    view = fixture(tmp_path)
    root = view.scope.sidecar / "state" / "invocations"
    root.parent.mkdir(parents=True)
    root.symlink_to(tmp_path / "missing")
    with pytest.raises(KnowledgeError, match="STORE_PATH"):
        view.phase()


def test_knowledge_outcome_requires_its_independent_exact_execution_receipts(
    tmp_path: Path,
) -> None:
    view = fixture(tmp_path)
    intent = view.intent()
    admission = StructuredExecutionAdmission.create(
        observation_id="f" * 32,
        call=StructuredCallIdentity(
            invocation_id="e" * 32,
            route_index=1,
            provider="fixture",
            model="fixture",
            reasoning_effort="medium",
            role=intent.binding.role,
            phase="knowledge_intent",
            request_sha256=intent.request_sha256,
        ),
        execution_kind="http",
        transport_request_sha256="a" * 64,
        timeout_seconds=2,
        admitted_at=NOW + timedelta(seconds=2),
    )
    receipt = StructuredHttpRoundTripReceipt.create(
        admission=admission,
        outcome="returned",
        http_status=200,
        response_body_sha256="a" * 64,
        completed_at=NOW + timedelta(seconds=3),
    )
    executions = tuple(
        KnowledgeExecutionRecord.create(intent_sha256=intent.intent_sha256, observation=record)
        for record in (admission, receipt)
    )
    outcome = KnowledgeInvocationOutcome.create(
        intent=intent,
        state="RETURNED",
        result=KnowledgeInvocationResult(payload={"queries": []}, duration_ms=2),
        executions=executions,
        completed_at=NOW + timedelta(seconds=4),
    )
    records = view.records(intent)
    records.put("knowledge-invocation-outcomes", intent.binding.run_id + ":intent", outcome)
    records.put("knowledge-execution-records", executions[0].record_sha256, executions[0])
    with pytest.raises(KnowledgeError, match="RECORD_NOT_FOUND"):
        view.phase()
    records.put("knowledge-execution-records", executions[1].record_sha256, executions[1])
    assert view.phase() == "KNOWLEDGE_PREPARATION"


def test_lane_intent_count_is_bounded_before_any_invalid_payload_parse(tmp_path: Path) -> None:
    view = fixture(tmp_path)
    intent = view.intent()
    root = view.records(intent).root
    for index in range(512):
        (root / f"knowledge-invocation-intents-extra-{index}.json").write_text("invalid")
    with pytest.raises(KnowledgeError, match="STORE_RECORD_LIMIT"):
        view.phase()


def test_main_outcome_without_its_start_is_corruption_not_execution(tmp_path: Path) -> None:
    view = fixture(tmp_path)
    view.main(complete=True)
    next((view.scope.sidecar / "state" / "invocations").glob("invocation-starts-*.json")).unlink()
    with pytest.raises(ValueError, match="exact invocation start"):
        view.phase()
