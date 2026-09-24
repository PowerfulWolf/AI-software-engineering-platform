"""Shared read/write eligibility for an upstream engineering investigation handoff."""

from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.knowledge.context import snapshot_from_sources
from ai_software_engineer.knowledge.gaps import KnowledgeGap
from ai_software_engineer.knowledge.models import digest
from ai_software_engineer.multi_directory.budget import DesignRetryPolicy
from ai_software_engineer.multi_directory.models import JointCheckpoint, JointStage


def design_recheck_available(
    checkpoint: JointCheckpoint, gap: KnowledgeGap, policy: DesignRetryPolicy
) -> bool:
    """Caller must separately check that the gap has no committed human resolution."""
    gap.validate_integrity()
    if (
        checkpoint.stage is not JointStage.WAITING_HUMAN
        or checkpoint.knowledge_wait_stage not in {JointStage.DESIGNING, JointStage.PLANNING}
        or checkpoint.knowledge_gap_id != gap.gap_id
        or checkpoint.product_spec is None
        or checkpoint.approval is None
        or checkpoint.children
        or checkpoint.plan is not None
        or policy.budget(checkpoint.attempts).exhausted is not None
        or len(checkpoint.knowledge_rechecks or ()) >= 32
        or any(r.gap.gap_id == gap.gap_id for r in checkpoint.knowledge_rechecks or ())
    ):
        return False
    binding = gap.binding
    snapshot = snapshot_from_sources(
        team_id=checkpoint.team_id,
        project_id=checkpoint.project_id,
        requirement_id=checkpoint.delivery_id,
        repository_ids=tuple(sorted(p.result.repository_id for p in checkpoint.preparations)),
        sources=tuple(
            (p.result.repository_id, s) for p in checkpoint.preparations for s in p.context_sources
        ),
    )
    return (
        (binding.team_id, binding.project_id, binding.requirement_id)
        == (checkpoint.team_id, checkpoint.project_id, checkpoint.delivery_id)
        and binding.task_id is None
        and binding.role
        is (
            TeamRole.DESIGNER
            if checkpoint.knowledge_wait_stage is JointStage.DESIGNING
            else TeamRole.PLANNER
        )
        and binding.repository_ids == snapshot.repository_ids
        and binding.snapshot_sha256 == snapshot.snapshot_sha256
        and binding.source_revision
        == digest(tuple((u.id, u.base_revision) for u in checkpoint.scope.units))
    )
