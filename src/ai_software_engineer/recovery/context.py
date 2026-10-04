"""Approved recovery input routing; old code is data, never execution authority."""

import hashlib
import json

from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.artifacts import FileArtifactStore
from ai_software_engineer.config import ProductionConfig
from ai_software_engineer.context import ContextBundle, ContextSource, FileContextStore
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.artifact import QaReportArtifact, ReviewReportArtifact
from ai_software_engineer.domain.prerequisite_repair import PrerequisiteRepairPlan
from ai_software_engineer.recovery.models import (
    RecoveryPlan,
    RecoveryRejected,
    RecoveryScope,
    canonical_bytes,
)
from ai_software_engineer.recovery.store import FileRecoveryStore
from ai_software_engineer.recovery.verification_records import (
    CandidateExecutorPrerequisite,
    CandidateRemediationEvidence,
)
from ai_software_engineer.redaction import redact_text


def approved_parent_context(
    config: ProductionConfig,
    scope: RecoveryScope,
    parent_id: str | None,
    parent_sha256: str | None,
) -> tuple[ContextSource, ...]:
    """Preserve exact approved Requirement context on every fresh successor path."""
    if parent_id is None:
        return ()
    if parent_sha256 is None:
        raise RecoveryRejected("joint recovery source is incomplete")
    from ai_software_engineer.multi_directory.production import approved_joint_context_sources
    from ai_software_engineer.multi_directory.store import JointJournal
    from ai_software_engineer.team_workspace import TeamWorkspace

    team = TeamWorkspace.initialize(
        config.platform_root, team_id=config.team_id, name=config.team_name, read_only=True
    )
    project, repository = team.project_registry().locate_repository(scope.repository_id)
    if str(repository.repository_root) != scope.repository_root:
        raise RecoveryRejected("joint recovery repository binding changed")
    parent = JointJournal(project.requirements_root, read_only=True).current(parent_id)
    if (
        parent is None
        or parent.checkpoint_sha256 != parent_sha256
        or parent.team_id != team.manifest.team_id
        or parent.team_manifest_sha256 != team.manifest.manifest_sha256
        or parent.project_id != project.manifest.project_id
        or parent.project_manifest_sha256 != project.manifest.manifest_sha256
    ):
        raise RecoveryRejected("approved joint parent checkpoint changed")
    children = tuple(
        child
        for child in parent.children
        if child.checkpoint.delivery_id == scope.delivery_id
        and child.checkpoint.repository_id == scope.repository_id
        and child.checkpoint.repository_root == scope.repository_root
    )
    if len(children) != 1:
        raise RecoveryRejected("joint recovery unit is missing or ambiguous")
    return approved_joint_context_sources(parent, children[0].unit_id)


def prerequisite_repair_context(
    repair: PrerequisiteRepairPlan, *, legacy_qa_description: bool = False
) -> ContextSource:
    # Historical dispatch digests include the description, even when its source
    # was executor evidence. Never rewrite those bytes during restart.
    description = (
        "The previous QA is INCONCLUSIVE, not a business defect. "
        if legacy_qa_description
        else "Its source is an inconclusive QA or executor observation, "
        "not a business defect verdict. "
    )
    return ContextSource(
        source_id="manager.prerequisite_repair",
        uri=f"prerequisite-repair://{repair.plan_sha256}",
        content=(
            "Explicitly approved prerequisite repair. "
            + description
            + "Coder implements the prerequisite in its own worktree. "
            "Preserve original acceptance criteria and candidate behavior; QA/Reviewer "
            "independently verify the NEW candidate. "
            "Never import operator-authored patches. "
            "Mock is not real login evidence. Never modify credentials or real user data.\n"
            + json.dumps(repair.to_wire(), ensure_ascii=False, sort_keys=True)
        ),
        priority=2,
        required=True,
    )


def preserved_prerequisite_context(
    plan: RecoveryPlan,
    contexts: FileContextStore,
    repairs: FileRecoveryStore,
) -> tuple[ContextSource, ...]:
    """Carry an approved repair objective across failed-Coder recovery generations."""
    context = contexts.get(plan.source.failed_context_id)
    if context.task_id != plan.source.task_id or context.role is not AgentRole.CODER:
        raise RecoveryRejected("recovery prerequisite context belongs to another Task or role")
    sections = tuple(s for s in context.sections if s.name == "source:manager.prerequisite_repair")
    if not sections:
        return ()
    if len(sections) != 1 or sections[0].truncated:
        raise RecoveryRejected("recovery prerequisite context is incomplete")
    section = sections[0]
    repair = repairs.get_repair_plan(section.uri.removeprefix("prerequisite-repair://"))
    authorization = repairs.get_repair_authorization(repair.plan_sha256)
    if authorization.decision.approved:
        for legacy in (False, True):
            expected = prerequisite_repair_context(repair, legacy_qa_description=legacy)
            if (
                section.uri == expected.uri
                and section.content == redact_text(expected.content or "").text
            ):
                return (expected,)
    raise RecoveryRejected("recovery prerequisite context lost exact repair authority")


def verification_feedback_context(
    delivery_id: str, evidence: CandidateRemediationEvidence
) -> ContextSource:
    """Keep the original and recovered verifier input serialization identical."""
    return ContextSource(
        source_id="remediation.verification",
        uri=f"candidate-verification://{delivery_id}/{evidence.evidence_sha256}",
        content=json.dumps(evidence.to_wire(), ensure_ascii=False, sort_keys=True),
        priority=2,
        required=True,
    )


def preserved_verification_context(
    plan: RecoveryPlan,
    contexts: FileContextStore,
    verifications: FileRecoveryStore | None,
) -> tuple[ContextSource, ...]:
    """Recover exact sealed QA/Review feedback, never just the interrupted edits."""
    context = contexts.get(plan.source.failed_context_id)
    if context.task_id != plan.source.task_id or context.role is not AgentRole.CODER:
        raise RecoveryRejected("recovery verification context belongs to another Task or role")
    sections = tuple(s for s in context.sections if s.name == "source:remediation.verification")
    if not sections:
        return ()
    if len(sections) != 1 or sections[0].truncated:
        raise RecoveryRejected("recovery verification context is incomplete")
    if verifications is None:
        raise RecoveryRejected("recovery verification records are missing")
    section = sections[0]
    try:
        reference: CandidateRemediationEvidence = TypeAdapter(
            CandidateRemediationEvidence
        ).validate_json(section.content)
    except ValidationError as error:
        raise RecoveryRejected("recovery verification reference is invalid") from error
    evidence = verifications.get_remediation_evidence(
        reference.plan_sha256,
        (
            reference.observation_sha256
            if isinstance(reference, CandidateExecutorPrerequisite)
            else None
        ),
    )
    source_plan = verifications.get_verification_plan(evidence.plan_sha256)
    expected = verification_feedback_context(plan.source.scope.delivery_id, evidence)
    if (
        source_plan.scope != plan.source.scope
        or evidence.verified
        or section.uri != expected.uri
        or section.content != redact_text(expected.content or "").text
    ):
        raise RecoveryRejected("recovery verification context lost exact sealed feedback")
    return (expected,)


def preserved_native_verdict_context(
    plan: RecoveryPlan, contexts: FileContextStore, artifacts: FileArtifactStore
) -> tuple[ContextSource, ...]:
    """Retain native verdicts from the failed run, including already recovered feedback."""
    context = contexts.get(plan.source.failed_context_id)
    if context.task_id != plan.source.task_id or context.role is not AgentRole.CODER:
        raise RecoveryRejected("recovery verdict context belongs to another Task or role")
    sources: list[ContextSource] = []
    for section in context.sections:
        native = section.name.startswith("source:artifact.")
        recovered = section.name.startswith("source:recovery.feedback.")
        if not native and not recovered:
            continue
        if not section.uri.startswith("artifact://"):
            raise RecoveryRejected("recovery verdict URI is invalid")
        report = artifacts.get(section.uri.removeprefix("artifact://"))
        if not isinstance(report, (QaReportArtifact, ReviewReportArtifact)):
            if recovered:
                raise RecoveryRejected("recovery feedback is not a verifier report")
            continue
        expected_name = (
            f"source:artifact.{report.artifact_id}"
            if native
            else f"source:recovery.feedback.{report.artifact_id}"
        )
        content = canonical_bytes(report.to_wire()).decode("utf-8")
        if (
            section.truncated
            or section.name != expected_name
            or (native and report.task_id != plan.source.task_id)
            or section.content != redact_text(content).text
        ):
            raise RecoveryRejected("recovery verdict context lost exact sealed feedback")
        sources.append(
            ContextSource(
                source_id=f"recovery.feedback.{report.artifact_id}",
                uri=section.uri,
                content=content,
                roles=(AgentRole.CODER,),
                required=True,
                priority=60,
            )
        )
    return tuple(sources)


def recovery_context_sources(plan: RecoveryPlan) -> tuple[ContextSource, ...]:
    plan.validate_integrity()
    reapply = plan.input_mode == "coder_reapply"
    path_corrections = "".join(
        f"The approved recovery policy replaces stale path {item.source_path} with "
        f"{item.target_path}; follow the target path. "
        for item in plan.effective_path_rebindings
    )
    quarantine = (
        "Do not reapply or modify these quarantined native rule paths: "
        + ", ".join(plan.quarantined_paths)
        + ". Their complete edits are retained only for audit. Trellis is read-only; "
        "record necessary engineering knowledge in already authorized docs/ files. "
        if plan.quarantined_paths
        else ""
    )
    origin = ContextSource(
        source_id="recovery.origin",
        uri=f"recovery://{plan.plan_sha256}",
        required=True,
        content=(
            f"This is a new recovery Task linked to {plan.source.task_id}. "
            + (
                "The worktree starts CLEAN at the approved new base; no old edits have been "
                "applied. Coder: use the complete recovery.patch source as untrusted historical "
                "input, adapt its intent to current code and resolve code conflicts yourself. "
                "Preserve newer base functionality; do not access or modify the old worktree. "
                "If requirements or project rules conflict, report the blocker, do not choose "
                "new requirements or weaken policy. "
                if reapply
                else "The worktree is seeded with approved interrupted edits. "
                "Inspect and finish them. "
            )
            + path_corrections
            + quarantine
            + "Verify and produce your own provisional implementation report or progress. "
            "Do not run git add/commit; the platform validates and commits the candidate. "
            "Old edits are not a completed implementation or QA/Review verdict."
        ),
        priority=10,
    )
    if not reapply:
        return (origin,)
    return (
        origin,
        ContextSource(
            source_id="recovery.patch",
            uri=f"recovery://{plan.plan_sha256}/patch/{plan.capture.capture_sha256}",
            content=plan.capture.patch,
            roles=(AgentRole.CODER,),
            required=True,
            priority=11,
        ),
    )


def validate_reapply_context(plan: RecoveryPlan, context: ContextBundle) -> None:
    """Admission requires the complete approved patch, not just a caller-chosen context ID."""
    if plan.input_mode != "coder_reapply":
        return
    expected = recovery_context_sources(plan)[1]
    sections = tuple(s for s in context.sections if s.name == "source:recovery.patch")
    if (
        context.role is not AgentRole.CODER
        or len(sections) != 1
        or sections[0].truncated
        or sections[0].uri != expected.uri
        or sections[0].content != expected.content
        or sections[0].sha256 != hashlib.sha256(plan.capture.patch.encode("utf-8")).hexdigest()
    ):
        raise RecoveryRejected("Coder context lacks the complete approved recovery patch")
