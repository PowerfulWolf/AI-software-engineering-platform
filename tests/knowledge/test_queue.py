"""Contract for a knowledge wait using an actual dispatched, owner-fenced claim."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ai_software_engineer.domain.enums import TeamRole, WorkItemStatus
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGapRouting,
    KnowledgeGapService,
)
from ai_software_engineer.knowledge.models import (
    KnowledgeError,
    KnowledgeRunBinding,
    KnowledgeSearchRequest,
    KnowledgeSnapshot,
    digest,
)
from ai_software_engineer.knowledge.queue import QueueKnowledgeWaitPort
from ai_software_engineer.knowledge.retrieval import MarkdownKnowledgeRetrieval
from ai_software_engineer.knowledge.skills import KnowledgeSkillRegistry
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.work_queue import QueueClaim, QueueConflict, QueuedWorkItem
from tests.work_queue.test_dispatcher import NOW, MemoryQueue, agent, dispatcher, item

OWNER = "queue-owner-token-0001"


class FencedQueue(MemoryQueue):
    """Owner/lifecycle fake; claims still come through the production Dispatcher."""

    def __init__(self) -> None:
        super().__init__((item(),))
        self.wait_calls = 0
        self.released = False

    def wait(
        self,
        work_item_id: str,
        *,
        lease_id: str,
        owner_token: str,
        status: WorkItemStatus,
        reason: str,
        now: datetime,
    ) -> QueuedWorkItem:
        self.wait_calls += 1
        claim = self.claims[-1]
        if (
            self.released
            or owner_token != OWNER
            or lease_id != claim.lease.id
            or work_item_id != claim.work_item.id
            or now >= claim.lease.expires_at
        ):
            raise QueueConflict("claim owner or lifecycle mismatch")
        current = self.get(work_item_id)
        updated = current.model_copy(
            update={"status": status, "wait_reason": reason, "updated_at": now}
        )
        self.items = (updated,)
        self.released = True
        return updated


def bound(claim: QueueClaim) -> KnowledgeRunBinding:
    frozen = KnowledgeSnapshot.create(
        team_id="team_knowledge",
        project_id="project_knowledge",
        requirement_id="requirement_knowledge",
        repository_ids=(claim.work_item.repository_id,),
        documents=(),
    )
    return KnowledgeRunBinding(
        run_id="run_knowledge_claim_001",
        task_id=claim.work_item.task_id,
        role=TeamRole(claim.work_item.role.value),
        team_id=frozen.team_id,
        project_id=frozen.project_id,
        requirement_id=frozen.requirement_id,
        repository_ids=frozen.repository_ids,
        source_revision="a" * 40,
        context_manifest_id="ctx_" + "b" * 64,
        snapshot_sha256=frozen.snapshot_sha256,
    )


def route(
    records: KnowledgeRecordStore, binding: KnowledgeRunBinding, *, dependency: bool = False
) -> KnowledgeGapRouting:
    frozen = KnowledgeSnapshot.create(
        team_id=binding.team_id,
        project_id=binding.project_id,
        requirement_id=binding.requirement_id,
        repository_ids=binding.repository_ids,
        documents=(),
    )
    skills = KnowledgeSkillRegistry(binding, frozen, MarkdownKnowledgeRetrieval(), records)
    skills.search_knowledge(
        KnowledgeSearchRequest(operation_id="search_missing", binding=binding, query="SLA")
    )
    gaps = KnowledgeGapService(records)
    gap = gaps.report(
        manifest=skills.manifest(),
        question="SLA?",
        required_decision="Provide SLA",
        reason="MISSING",
        severity="BLOCKING",
        impact="Cannot verify acceptance",
        risk="high",
    )
    return gaps.route(gap.gap_id, "RESEARCH" if dependency else "USER", "Missing SLA")


def setup_port(
    tmp_path: Path, *, token: str = OWNER, dependency: bool = False
) -> tuple[FencedQueue, QueueKnowledgeWaitPort, KnowledgeRunBinding, KnowledgeGapRouting]:
    queue = FencedQueue()
    dispatched = dispatcher(queue, agent("coder")).tick(now=NOW)
    assert dispatched.claim is not None
    binding = bound(dispatched.claim)
    records = KnowledgeRecordStore(tmp_path)
    routing = route(records, binding, dependency=dependency)
    return (
        queue,
        QueueKnowledgeWaitPort(
            queue,
            claim=dispatched.claim,
            owner_token=token,
            binding=binding,
            records=records,
            clock=lambda: NOW + timedelta(seconds=1),
        ),
        binding,
        routing,
    )


@pytest.mark.parametrize("dependency", [False, True])
def test_wait_releases_capacity_and_retains_exact_gap_route(
    tmp_path: Path, dependency: bool
) -> None:
    queue, port, binding, routing = setup_port(tmp_path, dependency=dependency)
    port.wait(binding, routing)
    assert queue.released and queue.wait_calls == 1
    assert queue.items[0].status.value == routing.waiting_status
    assert queue.items[0].wait_reason == f"KNOWLEDGE_GAP:{routing.gap_id}:{routing.routing_sha256}"
    assert OWNER not in str(queue.items[0].to_wire())
    with pytest.raises(QueueConflict):
        port.wait(binding, routing)
    assert queue.wait_calls == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", "task_other_001"),
        ("role", TeamRole.QA),
        ("team_id", "team_other"),
        ("project_id", "project_other"),
        ("repository_ids", ("repository_other",)),
        ("run_id", "run_other_001"),
        ("source_revision", "c" * 40),
        ("context_manifest_id", "ctx_" + "c" * 64),
        ("snapshot_sha256", "c" * 64),
    ],
)
def test_changed_binding_cannot_release_claim(tmp_path: Path, field: str, value: object) -> None:
    queue, port, binding, routing = setup_port(tmp_path)
    with pytest.raises(KnowledgeError, match="QUEUE_BINDING"):
        port.wait(binding.model_copy(update={field: value}), routing)
    assert not queue.released and queue.wait_calls == 0


def test_wrong_owner_is_rejected_by_queue_fence(tmp_path: Path) -> None:
    queue, port, binding, routing = setup_port(tmp_path, token="wrong-owner-token-0001")
    with pytest.raises(QueueConflict):
        port.wait(binding, routing)
    assert not queue.released and queue.wait_calls == 1


def test_changed_checkpoint_cannot_reuse_old_claim(tmp_path: Path) -> None:
    queue, port, binding, routing = setup_port(tmp_path)
    queue.items = (queue.items[0].model_copy(update={"dispatch_sequence": 1}),)
    with pytest.raises(QueueConflict):
        port.wait(binding, routing)
    assert not queue.released and queue.wait_calls == 0


def test_resealed_routing_change_cannot_replace_persisted_route(tmp_path: Path) -> None:
    queue, port, binding, routing = setup_port(tmp_path)
    forged = routing.model_copy(update={"waiting_status": "WAITING_DEPENDENCY"})
    forged = forged.model_copy(
        update={
            "routing_sha256": digest(forged.model_dump(mode="json", exclude={"routing_sha256"}))
        }
    )
    with pytest.raises(KnowledgeError, match="QUEUE_ROUTE"):
        port.wait(binding, forged)
    assert not queue.released and queue.wait_calls == 0


def test_expired_owner_is_checked_by_queue_not_stale_claim_snapshot(tmp_path: Path) -> None:
    queue, _, binding, routing = setup_port(tmp_path)
    claim = queue.claims[0]
    port = QueueKnowledgeWaitPort(
        queue,
        claim=claim,
        owner_token=OWNER,
        binding=binding,
        records=KnowledgeRecordStore(tmp_path),
        clock=lambda: claim.lease.expires_at,
    )
    with pytest.raises(QueueConflict):
        port.wait(binding, routing)
    assert not queue.released and queue.wait_calls == 1


def test_restarted_port_cannot_claim_released_wait_as_its_own(tmp_path: Path) -> None:
    queue, port, binding, routing = setup_port(tmp_path)
    port.wait(binding, routing)
    reopened = QueueKnowledgeWaitPort(
        queue,
        claim=queue.claims[0],
        owner_token="other-owner-token-0001",
        binding=binding,
        records=KnowledgeRecordStore(tmp_path),
        clock=lambda: NOW + timedelta(seconds=2),
    )
    with pytest.raises(QueueConflict):
        reopened.wait(binding, routing)
    assert queue.wait_calls == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", None),
        ("role", TeamRole.PRODUCT),
        ("repository_ids", ("repository_other",)),
        ("repository_ids", ("repository_platform_001", "repository_other")),
    ],
)
def test_constructor_cannot_bind_claim_to_another_task_or_expanded_scope(
    tmp_path: Path, field: str, value: object
) -> None:
    queue, _, binding, _ = setup_port(tmp_path)
    with pytest.raises(KnowledgeError, match="QUEUE_BINDING"):
        QueueKnowledgeWaitPort(
            queue,
            claim=queue.claims[0],
            owner_token=OWNER,
            binding=binding.model_copy(update={field: value}),
            records=KnowledgeRecordStore(tmp_path),
            clock=lambda: NOW,
        )
    assert not queue.released


def test_route_from_another_run_cannot_release_claim(tmp_path: Path) -> None:
    queue, port, binding, _ = setup_port(tmp_path)
    other = binding.model_copy(update={"run_id": "run_other_001"})
    routing = route(KnowledgeRecordStore(tmp_path), other)
    with pytest.raises(KnowledgeError, match="QUEUE_ROUTE"):
        port.wait(binding, routing)
    assert queue.wait_calls == 0


def test_gap_route_calls_the_queue_port_with_persisted_facts(tmp_path: Path) -> None:
    queue, port, binding, routing = setup_port(tmp_path)
    result = KnowledgeGapService(KnowledgeRecordStore(tmp_path)).route(
        routing.gap_id, "USER", "Missing SLA", wait_port=port
    )
    assert result == routing
    assert queue.released and queue.wait_calls == 1
    assert binding.run_id == "run_knowledge_claim_001"
