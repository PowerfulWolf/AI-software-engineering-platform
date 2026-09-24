"""Typed investigation handoff; never a human answer or a knowledge resolution."""

from typing import Literal

from pydantic import AwareDatetime

from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.knowledge.gaps import KnowledgeGap
from ai_software_engineer.knowledge.models import Digest, KnowledgeError, KnowledgeRunBinding


class DesignKnowledgeRecheck(DomainModel):
    kind: Literal["design_knowledge_recheck"] = "design_knowledge_recheck"
    gap: KnowledgeGap
    source_checkpoint_sha256: Digest
    product_spec_sha256: Digest
    operator_id: NonEmptyStr
    request_reference: NonEmptyStr
    requested_at: AwareDatetime

    def validate_binding(self, binding: KnowledgeRunBinding) -> None:
        self.gap.validate_integrity()
        prior = self.gap.binding
        fields = {
            "team_id",
            "project_id",
            "requirement_id",
            "repository_ids",
            "source_revision",
            "snapshot_sha256",
        }
        if (
            prior.role not in {TeamRole.DESIGNER, TeamRole.PLANNER}
            or prior.task_id is not None
            or binding.task_id is not None
            or prior.model_dump(include=fields) != binding.model_dump(include=fields)
        ):
            raise KnowledgeError("RECHECK_BINDING")


def rechecked_gap_ids(
    rechecks: tuple[DesignKnowledgeRecheck, ...], binding: KnowledgeRunBinding
) -> frozenset[str]:
    for recheck in rechecks:
        recheck.validate_binding(binding)
    return frozenset(item.gap.gap_id for item in rechecks)
