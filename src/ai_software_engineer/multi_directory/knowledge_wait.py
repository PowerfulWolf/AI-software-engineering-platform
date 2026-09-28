"""Carry a reconciled native checkpoint alongside a durable verifier wait."""

from ai_software_engineer.knowledge.gaps import KnowledgeGap, KnowledgeGapRaised
from ai_software_engineer.multi_directory.models import ChildDelivery


class ChildKnowledgeGapRaised(KnowledgeGapRaised):
    def __init__(self, gap: KnowledgeGap, child: ChildDelivery) -> None:
        if gap.binding.task_id != child.checkpoint.task_id or gap.binding.repository_ids != (
            child.checkpoint.repository_id,
        ):
            raise ValueError("knowledge wait does not belong to this native child")
        child.checkpoint.validate_integrity()
        super().__init__(gap)
        self.child = child
