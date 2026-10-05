"""Select only feedback belonging to the implementation being revised."""

from ai_software_engineer.domain.artifact import (
    Artifact,
    ImplementationReportArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
)
from ai_software_engineer.domain.enums import QaReportStatus, ReviewVerdict


def coder_feedback(
    previous: ImplementationReportArtifact | None,
    qa: QaReportArtifact | None,
    review: ReviewReportArtifact | None,
) -> tuple[Artifact, ...]:
    if previous is None:
        return ()
    current_qa = qa is not None and (
        qa.task_id == previous.task_id
        and qa.source_revision == previous.content.commit_sha
        and qa.parent_artifact_ids == (previous.artifact_id,)
    )
    if current_qa:
        assert qa is not None
        if qa.content.status is QaReportStatus.FAIL:
            return (qa,)
        if review is not None and (
            review.task_id == previous.task_id
            and review.source_revision == previous.content.commit_sha
            and review.parent_artifact_ids == (qa.artifact_id,)
            and review.content.verdict is ReviewVerdict.REJECT
        ):
            return (qa, review)
    return ()
