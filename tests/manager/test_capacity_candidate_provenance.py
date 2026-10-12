"""Pure typed-reader refusals; these synthetic receipts are never production facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentRequest, AgentResult, AgentRunStatus
from ai_software_engineer.artifacts import FileArtifactStore, seal_artifact
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.domain.artifact import ImplementationReportArtifact
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.manager.capacity_input_reader import (
    CapacityInputReader,
    UninvokedClaimBoundary,
)
from ai_software_engineer.work_queue import QueueArtifactReceipt
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact, QueuedRoleStep
from ai_software_engineer.work_queue.invocation import (
    DeliveryInvocationOutcome,
    DeliveryInvocationStart,
)
from ai_software_engineer.work_queue.models import QueueClaim
from tests.domain.factories import make_implementation_artifact
from tests.manager.test_baseline_knowledge_claim_proof import knowledge_failure


@dataclass
class _Queue:
    claim: QueueClaim
    step: QueuedRoleStep
    publications: tuple[AcceptedRoleArtifact, ...]

    def original_claim(self, lease_id: str) -> QueueClaim:
        if lease_id != self.claim.lease.id:
            raise ValueError("foreign synthetic original claim")
        return self.claim

    def step_for_invocation(self, work_item_id: str, baseline: str | None) -> QueuedRoleStep:
        assert work_item_id == self.claim.work_item.id and baseline is None
        return self.step

    def accepted(self, task_id: str) -> tuple[AcceptedRoleArtifact, ...]:
        assert task_id == self.claim.work_item.task_id
        return self.publications


@pytest.mark.parametrize(
    "fault",
    (
        "none",
        "missing_start",
        "duplicate_start",
        "missing_outcome",
        "foreign_outcome",
        "candidate_source",
        "candidate_context",
        "candidate_run",
        "candidate_evidence",
        "accepted_missing",
        "accepted_source",
        "accepted_claim",
        "step_source",
        "same_claim",
        "same_run",
    ),
)
def test_finalized_candidate_requires_exact_original_input_outcome_and_sql_publication(
    tmp_path: Path, fault: str
) -> None:
    facts = knowledge_failure(tmp_path, returned=True)
    context = FileContextStore(tmp_path / "contexts", read_only=True).get(
        facts.intent.binding.context_manifest_id
    )
    claim = facts.claim
    request = AgentRequest(
        task_id=facts.task.id,
        run_id="run_original_candidate",
        role=facts.item.role,
        attempt=facts.item.attempt,
        source_revision=context.source_revision,
        context_manifest_id=context.context_id,
        input_artifact_ids=(),
        permissions=facts.collector.permissions,
        output_schema="schemas/coder-output.schema.json",
        timeout_seconds=30,
    )
    raw = make_implementation_artifact()
    raw = raw.model_copy(
        update={
            "task_id": request.task_id,
            "context_manifest_id": request.context_manifest_id,
            "source_revision": "b" * 40,
            "content": raw.content.model_copy(update={"commit_sha": "b" * 40}),
            "producer": raw.producer.model_copy(
                update={"run_id": request.run_id, "agent_id": claim.assignment.agent_id}
            ),
        }
    )
    candidate = seal_artifact(raw, validated_at=claim.claimed_at + timedelta(seconds=3))
    assert isinstance(candidate, ImplementationReportArtifact)
    start = DeliveryInvocationStart(
        work_item_id=claim.work_item.id,
        checkpoint_sequence=claim.work_item.checkpoint_sequence,
        request=request,
        lease_id=claim.lease.id,
        started_at=claim.claimed_at + timedelta(seconds=1),
        start_sha256="0" * 64,
    )
    start = start.model_copy(
        update={"start_sha256": digest(start.model_dump(mode="json", exclude={"start_sha256"}))}
    )
    result = AgentResult(
        run_id=request.run_id,
        task_id=request.task_id,
        role=request.role,
        attempt=request.attempt,
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        status=AgentRunStatus.SUCCEEDED,
        artifact=raw,
    )
    outcome = DeliveryInvocationOutcome(start=start, result=result, outcome_sha256="0" * 64)
    outcome = outcome.model_copy(
        update={
            "outcome_sha256": digest(outcome.model_dump(mode="json", exclude={"outcome_sha256"}))
        }
    )
    publication = AcceptedRoleArtifact(
        task_id=candidate.task_id,
        work_item_id=claim.work_item.id,
        lease_id=claim.lease.id,
        dispatch_sequence=claim.work_item.dispatch_sequence,
        checkpoint_sequence=claim.work_item.checkpoint_sequence,
        run_id=candidate.producer.run_id,
        context_manifest_id=candidate.context_manifest_id,
        source_revision=candidate.source_revision,
        receipt=QueueArtifactReceipt(
            artifact_id=candidate.artifact_id, sha256=candidate.integrity.sha256
        ),
    )
    queue = _Queue(claim, facts.collector.queue.step(facts.item.id), (publication,))
    reader = CapacityInputReader(
        state=facts.collector.state,
        queue=queue,
        artifacts=FileArtifactStore(tmp_path / "artifacts"),
        route_root=tmp_path / "model-routes",
        baselines=None,
        permissions=request.permissions,
    )
    starts: tuple[DeliveryInvocationStart, ...] = (start,)
    outcomes: tuple[DeliveryInvocationOutcome, ...] = (outcome,)
    if fault == "missing_start":
        starts = ()
    elif fault == "duplicate_start":
        starts = (start, start)
    elif fault == "missing_outcome":
        outcomes = ()
    elif fault == "foreign_outcome":
        altered = outcome.model_copy(
            update={"result": result.model_copy(update={"artifact": None})}
        )
        outcomes = (
            altered.model_copy(
                update={
                    "outcome_sha256": digest(
                        altered.model_dump(mode="json", exclude={"outcome_sha256"})
                    )
                }
            ),
        )
    elif fault.startswith("candidate_"):
        field = fault.removeprefix("candidate_")
        updates: dict[str, dict[str, object]] = {
            "source": {"source_revision": "c" * 40},
            "context": {"context_manifest_id": "ctx_foreign_candidate"},
            "run": {"producer": candidate.producer.model_copy(update={"run_id": "run_foreign"})},
            "evidence": {"evidence": ()},
        }
        altered_candidate = seal_artifact(
            candidate.model_copy(update=updates[field]),
            validated_at=claim.claimed_at + timedelta(seconds=3),
        )
        assert isinstance(altered_candidate, ImplementationReportArtifact)
        candidate = altered_candidate
    elif fault == "accepted_missing":
        queue.publications = ()
    elif fault == "accepted_source":
        queue.publications = (publication.model_copy(update={"source_revision": "c" * 40}),)
    elif fault == "accepted_claim":
        queue.publications = (publication.model_copy(update={"lease_id": "lease_foreign"}),)
    elif fault == "step_source":
        queue.step = queue.step.model_copy(
            update={
                "boundary": queue.step.boundary.__class__(
                    facts.task.id,
                    AgentRole.CODER,
                    facts.item.attempt,
                    facts.item.checkpoint_sequence,
                    "c" * 40,
                )
            }
        )
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    if fault in {"same_claim", "same_run"}:
        marker = UninvokedClaimBoundary(
            task_id=facts.task.id,
            work_item_id=facts.item.id,
            lease_id=claim.lease.id,
            role=facts.item.role,
            attempt=facts.item.attempt,
            checkpoint_sequence=facts.item.checkpoint_sequence,
            dispatch_sequence=facts.item.dispatch_sequence,
            observed_at=claim.claimed_at + timedelta(seconds=5),
            run_id=request.run_id if fault == "same_run" else "run_capacity_unknown",
            context_manifest_id="ctx_capacity_other",
        )
        with pytest.raises(ValueError, match=r"原 Run|原 claim"):
            reader._require_other_model_fact(
                marker,
                run_id=candidate.producer.run_id,
                context_id=candidate.context_manifest_id,
                role=candidate.producer.role,
                source_revision=candidate.source_revision,
                starts=starts,
                outcomes=outcomes,
                candidate=candidate,
                allow_later_claims=False,
            )
    elif fault == "none":
        assert reader._candidate_input_revision(candidate, context, starts, outcomes) == "a" * 40
    else:
        with pytest.raises(ValueError):
            reader._candidate_input_revision(candidate, context, starts, outcomes)
    assert {path: path.read_bytes() for path in tmp_path.rglob("*.json")} == before
