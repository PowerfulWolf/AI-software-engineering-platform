"""Bind command-free candidate reading to verified Task and artifact inputs."""

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from ai_software_engineer.agents.candidate_source import (
    CandidateReadScope,
    candidate_review_snapshot,
)
from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.agents.openai_compatible import ContextResolver
from ai_software_engineer.artifacts import artifact_digest
from ai_software_engineer.context.builder import estimate_input_tokens
from ai_software_engineer.domain import AgentRole, Task
from ai_software_engineer.domain.artifact import (
    Artifact,
    CoderProgressArtifact,
    ImplementationReportArtifact,
    PlanArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
)
from ai_software_engineer.domain.enums import QaReportStatus, ReviewVerdict
from ai_software_engineer.git import WorkspacePolicyError
from ai_software_engineer.redaction import redact_text


def candidate_read_scope(
    task: Task, plan: Artifact, implementation: Artifact, candidate_revision: str
) -> CandidateReadScope:
    """Only sealed same-Task lineage can select the base and planned dependencies."""
    if not isinstance(plan, PlanArtifact) or not isinstance(
        implementation, ImplementationReportArtifact
    ):
        raise WorkspacePolicyError("candidate source requires plan and implementation artifacts")
    for artifact in (plan, implementation):
        if (
            artifact.task_id != task.id
            or not artifact.integrity.validated
            or artifact_digest(artifact) != artifact.integrity.sha256
        ):
            raise WorkspacePolicyError("candidate source artifact identity or integrity differs")
    if (
        plan.source_revision != task.base_ref
        or not implementation.parent_artifact_ids
        or implementation.parent_artifact_ids[0] != plan.artifact_id
        or implementation.source_revision != candidate_revision
        or implementation.content.commit_sha != candidate_revision
    ):
        raise WorkspacePolicyError("candidate source artifact lineage or revision differs")
    try:
        return CandidateReadScope(
            task_id=task.id,
            base_revision=task.base_ref,
            candidate_revision=candidate_revision,
            related_paths=tuple(path for step in plan.content.steps for path in step.files),
            denied_paths=task.constraints.denied_paths if task.constraints else (),
        )
    except ValueError as error:
        raise WorkspacePolicyError(
            "candidate source requires exact revisions and dependencies"
        ) from error


def validate_candidate_artifact_lineage(
    task: Task,
    plan: Artifact,
    implementation: Artifact,
    artifacts: Mapping[str, Artifact],
) -> None:
    """Validate a first or remediation Coder candidate and sealed feedback.

    A remediation implementation legitimately has the original Plan plus the exact
    QA/Review finding as parents and supersedes the previous implementation. The old
    single-parent rule rejected that durable retry contract before QA could run.
    """
    if not isinstance(plan, PlanArtifact) or not isinstance(
        implementation, ImplementationReportArtifact
    ):
        raise WorkspacePolicyError("candidate source requires plan and implementation artifacts")
    if (
        plan.task_id != task.id
        or implementation.task_id != task.id
        or plan.source_revision != task.base_ref
        or plan.parent_artifact_ids
        or not implementation.parent_artifact_ids
        or implementation.parent_artifact_ids[0] != plan.artifact_id
        or implementation.source_revision != implementation.content.commit_sha
    ):
        raise WorkspacePolicyError("candidate source artifact lineage or revision differs")
    parents = tuple(
        artifacts.get(artifact_id) for artifact_id in implementation.parent_artifact_ids[1:]
    )
    if any(parent is None for parent in parents):
        raise WorkspacePolicyError("candidate source artifact lineage or revision differs")
    if implementation.supersedes is None:
        if any(not isinstance(parent, CoderProgressArtifact) for parent in parents):
            raise WorkspacePolicyError("candidate source artifact lineage or revision differs")
        for parent in parents:
            assert isinstance(parent, CoderProgressArtifact)
            if parent.task_id != task.id or parent.producer.role is not AgentRole.CODER:
                raise WorkspacePolicyError("candidate source artifact lineage or revision differs")
        return

    previous = artifacts.get(implementation.supersedes)
    if not isinstance(previous, ImplementationReportArtifact) or previous.task_id != task.id:
        raise WorkspacePolicyError("candidate source artifact lineage or revision differs")
    feedback: Artifact | None = None
    progress: list[CoderProgressArtifact] = []
    for parent in parents:
        assert parent is not None
        if isinstance(parent, CoderProgressArtifact):
            progress.append(parent)
        elif feedback is None and isinstance(parent, (QaReportArtifact, ReviewReportArtifact)):
            feedback = parent
        else:
            raise WorkspacePolicyError("candidate source artifact lineage or revision differs")
    if any(
        item.task_id != task.id or item.producer.role is not AgentRole.CODER for item in progress
    ):
        raise WorkspacePolicyError("candidate source artifact lineage or revision differs")
    if feedback is None or feedback.task_id != task.id:
        raise WorkspacePolicyError("candidate source artifact lineage or revision differs")
    if isinstance(feedback, QaReportArtifact):
        valid_feedback = (
            feedback.producer.role is AgentRole.QA
            and feedback.content.status is QaReportStatus.FAIL
            and feedback.source_revision == previous.content.commit_sha
            and feedback.parent_artifact_ids == (previous.artifact_id,)
        )
    else:
        accepted_qa = (
            artifacts.get(feedback.parent_artifact_ids[0]) if feedback.parent_artifact_ids else None
        )
        valid_feedback = (
            feedback.producer.role is AgentRole.REVIEWER
            and feedback.content.verdict is ReviewVerdict.REJECT
            and feedback.source_revision == previous.content.commit_sha
            and isinstance(accepted_qa, QaReportArtifact)
            and accepted_qa.task_id == task.id
            and accepted_qa.producer.role is AgentRole.QA
            and accepted_qa.content.status is QaReportStatus.PASS
            and accepted_qa.source_revision == previous.content.commit_sha
            and accepted_qa.parent_artifact_ids == (previous.artifact_id,)
        )
    if not valid_feedback:
        raise WorkspacePolicyError("candidate source artifact lineage or revision differs")


class BoundCandidateSource:
    """Compile source after all other prompt additions, enforcing the original input budget."""

    def __init__(self, resolver: ContextResolver) -> None:
        self._resolver = resolver

    def append(self, request: AgentRequest, root: Path, prompt: str) -> str:
        context = self._resolver.get_context(request.context_manifest_id)
        if (
            request.role not in (AgentRole.QA, AgentRole.REVIEWER)
            or context.context_id != request.context_manifest_id
            or context.task_id != request.task_id
            or context.role is not request.role
            or context.attempt != request.attempt
            or context.source_revision != request.source_revision
        ):
            raise WorkspacePolicyError("candidate source Context differs from AgentRequest")
        for section in context.sections:
            if hashlib.sha256(section.content.encode()).hexdigest() != section.sha256:
                raise WorkspacePolicyError("candidate source Context section integrity differs")
        task_sections = [s for s in context.sections if s.name == "task"]
        if (
            len(task_sections) != 1
            or task_sections[0].uri != f"task://{request.task_id}"
            or task_sections[0].truncated
        ):
            raise WorkspacePolicyError("candidate source requires the original Task section")
        try:
            task = Task.model_validate_json(task_sections[0].content)
        except ValueError as error:
            raise WorkspacePolicyError("candidate source Task section is invalid") from error
        if task.id != request.task_id:
            raise WorkspacePolicyError("candidate source Task identity differs")
        artifacts = tuple(self._resolver.get_artifact(i) for i in request.input_artifact_ids)
        artifacts_by_id = {artifact.artifact_id: artifact for artifact in artifacts}
        plans = [a for a in artifacts if isinstance(a, PlanArtifact)]
        implementations = [a for a in artifacts if isinstance(a, ImplementationReportArtifact)]
        if len(plans) != 1 or len(implementations) != 1:
            raise WorkspacePolicyError("candidate source requires one plan and implementation")
        # The sealed inputs must be the same inputs actually delivered to this role.
        for artifact in (plans[0], implementations[0]):
            sections = [
                s for s in context.sections if s.uri == f"artifact://{artifact.artifact_id}"
            ]
            expected = redact_text(
                json.dumps(
                    artifact.to_wire(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
            ).text
            if len(sections) != 1 or sections[0].truncated:
                raise WorkspacePolicyError("candidate source artifact is absent from Context")
            try:
                matches = json.loads(sections[0].content) == json.loads(expected)
            except ValueError as error:
                raise WorkspacePolicyError(
                    "candidate source artifact Context is invalid"
                ) from error
            if not matches:
                raise WorkspacePolicyError("candidate source artifact differs from Context")
        referenced_ids = set(implementations[0].parent_artifact_ids)
        if implementations[0].supersedes is not None:
            referenced_ids.add(implementations[0].supersedes)
        for artifact_id in referenced_ids:
            if artifact_id in artifacts_by_id:
                continue
            try:
                artifacts_by_id[artifact_id] = self._resolver.get_artifact(artifact_id)
            except Exception as error:
                raise WorkspacePolicyError(
                    "candidate source artifact lineage or revision differs"
                ) from error
        # A remediation feedback artifact may itself point at the previous QA PASS.
        for artifact in tuple(artifacts_by_id.values()):
            if isinstance(artifact, ReviewReportArtifact):
                for artifact_id in artifact.parent_artifact_ids:
                    if artifact_id not in artifacts_by_id:
                        try:
                            artifacts_by_id[artifact_id] = self._resolver.get_artifact(artifact_id)
                        except Exception as error:
                            raise WorkspacePolicyError(
                                "candidate source artifact lineage or revision differs"
                            ) from error
        validate_candidate_artifact_lineage(task, plans[0], implementations[0], artifacts_by_id)
        scope = candidate_read_scope(task, plans[0], implementations[0], request.source_revision)
        result = prompt + candidate_review_snapshot(root, scope, request.permissions)
        if estimate_input_tokens(result) > context.budget.max_input_tokens:
            raise WorkspacePolicyError(
                "candidate review prompt exceeds its configured Context budget"
            )
        return result
