"""Shared validation for the final four-Artifact delivery chain."""

from ai_software_engineer.domain.artifact import (
    Artifact,
    ImplementationReportArtifact,
    PlanArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
)
from ai_software_engineer.domain.enums import QaReportStatus, ReviewVerdict, TaskStatus
from ai_software_engineer.domain.event import StateEvent
from ai_software_engineer.domain.task import Task

type DeliveryChain = tuple[
    PlanArtifact,
    ImplementationReportArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
]


def resolve_delivery_chain(
    task: Task,
    state_events: tuple[StateEvent, ...],
    artifacts: tuple[Artifact, ...],
) -> DeliveryChain | None:
    """Return the trusted DONE chain, or None when any cross-object gate fails."""
    if not state_events or state_events[-1].to_status is not TaskStatus.DONE:
        return None
    artifact_ids = state_events[-1].artifact_ids
    if len(artifact_ids) != 4:
        return None
    by_id = {artifact.artifact_id: artifact for artifact in artifacts}
    try:
        plan, implementation, qa, review = (by_id[artifact_id] for artifact_id in artifact_ids)
    except KeyError:
        return None
    if not (
        isinstance(plan, PlanArtifact)
        and isinstance(implementation, ImplementationReportArtifact)
        and isinstance(qa, QaReportArtifact)
        and isinstance(review, ReviewReportArtifact)
    ):
        return None
    expected_criteria = {criterion.id for criterion in task.acceptance_criteria}
    if (
        plan.source_revision != task.base_ref
        or implementation.source_revision != implementation.content.commit_sha
        or qa.source_revision != implementation.content.commit_sha
        or review.source_revision != implementation.content.commit_sha
        or plan.artifact_id not in implementation.parent_artifact_ids
        or qa.parent_artifact_ids != (implementation.artifact_id,)
        or review.parent_artifact_ids != (qa.artifact_id,)
        or qa.content.status is not QaReportStatus.PASS
        or review.content.verdict is not ReviewVerdict.APPROVE
        or {mapping.criterion_id for mapping in plan.content.acceptance_mapping}
        != expected_criteria
        or {mapping.criterion_id for mapping in implementation.content.acceptance_mapping}
        != expected_criteria
        or {result.criterion_id for result in qa.content.criteria_results} != expected_criteria
        or len({item.producer.run_id for item in (plan, implementation, qa, review)}) != 4
        or not all(item.integrity.validated for item in (plan, implementation, qa, review))
    ):
        return None
    return plan, implementation, qa, review


__all__ = ["DeliveryChain", "resolve_delivery_chain"]
