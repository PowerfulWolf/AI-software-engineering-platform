"""Self-contained DONE/BLOCKED handoff bundles and immutable file storage."""

import hashlib
import json
import os
import shlex
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Literal, Self

from pydantic import (
    AwareDatetime,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from ai_software_engineer.artifacts import ArtifactStore
from ai_software_engineer.domain.artifact import (
    Artifact,
    ArtifactId,
    ChangedFile,
    CommitSha,
    Evidence,
    ImplementationReportArtifact,
    PlanArtifact,
    QaReportArtifact,
    ReviewReportArtifact,
    Sha256,
)
from ai_software_engineer.domain.enums import (
    AgentRole,
    ArtifactKind,
    QaReportStatus,
    ReviewVerdict,
    TaskStatus,
)
from ai_software_engineer.domain.event import EventId, StateEvent
from ai_software_engineer.domain.model import (
    DomainModel,
    NonEmptyStr,
    WirePayload,
    ensure_known_references,
    ensure_unique,
)
from ai_software_engineer.domain.task import AcceptanceCriterionId, Task, TaskId
from ai_software_engineer.evaluation.delivery import DeliveryChain, resolve_delivery_chain
from ai_software_engineer.store import TaskRepository

HandoffId = Annotated[str, StringConstraints(pattern=r"^handoff_[a-f0-9]{64}$")]
_HANDOFF_ID_ADAPTER: Final[TypeAdapter[HandoffId]] = TypeAdapter(HandoffId)
_SCHEMA_VERSION: Final = "v0.1"
_PLACEHOLDER_ID: Final = f"handoff_{'0' * 64}"
Clock = Callable[[], datetime]


class HandoffOutcome(StrEnum):
    DONE = "DONE"
    BLOCKED = "BLOCKED"


class HandoffCriterionStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_TESTED = "NOT_TESTED"
    NOT_ASSESSED = "NOT_ASSESSED"


class HandoffCriterion(DomainModel):
    criterion_id: AcceptanceCriterionId
    description: NonEmptyStr
    required: StrictBool
    status: HandoffCriterionStatus
    evidence_ids: tuple[str, ...] = ()
    notes: str | None = None

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> Self:
        ensure_unique(self.evidence_ids, "handoff criterion evidence IDs")
        return self


class HandoffArtifact(DomainModel):
    artifact_id: ArtifactId
    kind: ArtifactKind
    sha256: Sha256
    producer_role: AgentRole
    run_id: NonEmptyStr
    source_revision: NonEmptyStr
    context_manifest_id: NonEmptyStr
    evidence_ids: tuple[str, ...]


class ReviewCommand(DomainModel):
    label: NonEmptyStr
    argv: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


class HandoffBundle(DomainModel):
    """Typed facts a human needs to review a terminal Task without internal logs."""

    handoff_id: HandoffId
    schema_version: Literal["v0.1"] = "v0.1"
    generated_at: AwareDatetime
    task_id: TaskId
    title: NonEmptyStr
    description: NonEmptyStr
    repository: NonEmptyStr
    outcome: HandoffOutcome
    attempts: StrictInt = Field(ge=0)
    base_revision: NonEmptyStr
    candidate_revision: CommitSha | None = None
    summary: NonEmptyStr
    qa_status: QaReportStatus | None = None
    review_verdict: ReviewVerdict | None = None
    criteria: tuple[HandoffCriterion, ...]
    changed_files: tuple[ChangedFile, ...]
    artifacts: tuple[HandoffArtifact, ...]
    evidence: tuple[Evidence, ...]
    event_ids: tuple[EventId, ...]
    known_risks: tuple[str, ...]
    blocked_classification: str | None = None
    blocked_reason: str | None = None
    next_actions: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    review_commands: tuple[ReviewCommand, ...]

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        ensure_unique((item.criterion_id for item in self.criteria), "handoff criteria")
        ensure_unique((item.artifact_id for item in self.artifacts), "handoff artifacts")
        ensure_unique((item.evidence_id for item in self.evidence), "handoff evidence")
        ensure_unique(self.event_ids, "handoff event IDs")
        ensure_unique((item.path for item in self.changed_files), "handoff changed files")
        evidence_references = (
            evidence_id for criterion in self.criteria for evidence_id in criterion.evidence_ids
        )
        ensure_known_references(
            evidence_references,
            (item.evidence_id for item in self.evidence),
            "handoff criterion evidence references",
        )
        ensure_known_references(
            (evidence_id for artifact in self.artifacts for evidence_id in artifact.evidence_ids),
            (item.evidence_id for item in self.evidence),
            "handoff Artifact evidence references",
        )
        if self.outcome is HandoffOutcome.DONE:
            if (
                self.candidate_revision is None
                or self.qa_status is not QaReportStatus.PASS
                or self.review_verdict is not ReviewVerdict.APPROVE
                or len(self.artifacts) != 4
                or self.blocked_reason is not None
            ):
                raise ValueError(
                    "DONE handoff requires candidate, PASS, APPROVE, and four artifacts"
                )
        elif self.blocked_reason is None:
            raise ValueError("BLOCKED handoff requires blocked_reason")
        return self


@dataclass(frozen=True, slots=True)
class HandoffRef:
    handoff_id: HandoffId
    sha256: Sha256
    json_path: Path
    markdown_path: Path


class HandoffError(RuntimeError):
    """Base class for stable Human Boundary failures."""


class HandoffNotReady(HandoffError):
    """Raised when a Task is not a handoff-ready terminal state."""


class HandoffContractError(HandoffError):
    """Raised when terminal delivery facts cannot form a trusted bundle."""


class HandoffNotFound(HandoffError):
    """Raised when a Handoff ID is absent or invalid."""


class HandoffConflict(HandoffError):
    """Raised when an immutable Handoff ID is reused with other facts."""


class HandoffCorruption(HandoffError):
    """Raised when persisted JSON or Markdown no longer matches the bundle."""


class HandoffIntegrityError(HandoffError):
    """Raised when a bundle's deterministic identity is forged."""


class HandoffBuilder:
    """Build a terminal Task handoff from repositories, never from Agent prose."""

    def __init__(
        self,
        *,
        repository: TaskRepository,
        artifact_store: ArtifactStore,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository
        self._artifact_store = artifact_store
        self._clock = clock or _utc_now

    def build(self, task_id: TaskId) -> HandoffBundle:
        task = self._repository.get(task_id)
        if task.status not in {TaskStatus.DONE, TaskStatus.BLOCKED}:
            raise HandoffNotReady(f"Task {task.id} is {task.status.value}")
        events = self._repository.list_events(task.id)
        if not events or events[-1].to_status is not task.status:
            raise HandoffContractError("terminal Task does not match its final StateEvent")
        artifacts = self._artifact_store.list_for_task(task.id)
        if task.status is TaskStatus.DONE:
            chain = resolve_delivery_chain(task, events, artifacts)
            if chain is None:
                raise HandoffContractError("DONE Task has no valid delivery chain")
            return self._done(task, events, chain)
        return self._blocked(task, events, artifacts)

    def _done(
        self, task: Task, events: tuple[StateEvent, ...], chain: DeliveryChain
    ) -> HandoffBundle:
        plan, implementation, qa, review = chain
        criteria = _criteria(task, qa)
        evidence = _evidence(chain)
        risks = _risks(plan, implementation)
        candidate = implementation.content.commit_sha
        provisional = HandoffBundle(
            handoff_id=_PLACEHOLDER_ID,
            generated_at=self._clock(),
            task_id=task.id,
            title=task.title,
            description=task.description,
            repository=task.repository,
            outcome=HandoffOutcome.DONE,
            attempts=task.attempts,
            base_revision=task.base_ref,
            candidate_revision=candidate,
            summary=(f"DONE: candidate {candidate} passed independent QA and Reviewer gates."),
            qa_status=qa.content.status,
            review_verdict=review.content.verdict,
            criteria=criteria,
            changed_files=implementation.content.changed_files,
            artifacts=tuple(_artifact_ref(artifact) for artifact in chain),
            evidence=evidence,
            event_ids=tuple(event.event_id for event in events),
            known_risks=risks,
            next_actions=(
                "Review the acceptance evidence and candidate diff.",
                "Merge the candidate through the repository's normal protected-branch process.",
                "Keep this handoff and its referenced Artifacts as the immutable delivery record.",
            ),
            review_commands=_review_commands(task.base_ref, candidate),
        )
        return _with_identity(provisional)

    def _blocked(
        self,
        task: Task,
        events: tuple[StateEvent, ...],
        artifacts: tuple[Artifact, ...],
    ) -> HandoffBundle:
        ordered = tuple(sorted(artifacts, key=_artifact_order))
        latest_plan = _latest(ordered, PlanArtifact)
        latest_implementation = _latest(ordered, ImplementationReportArtifact)
        latest_qa = _latest(ordered, QaReportArtifact)
        latest_review = _latest(ordered, ReviewReportArtifact)
        candidate = (
            latest_implementation.content.commit_sha if latest_implementation is not None else None
        )
        reason = events[-1].reason
        classification = reason.partition(":")[0] if ":" in reason else None
        provisional = HandoffBundle(
            handoff_id=_PLACEHOLDER_ID,
            generated_at=self._clock(),
            task_id=task.id,
            title=task.title,
            description=task.description,
            repository=task.repository,
            outcome=HandoffOutcome.BLOCKED,
            attempts=task.attempts,
            base_revision=task.base_ref,
            candidate_revision=candidate,
            summary=f"BLOCKED: {reason}",
            qa_status=latest_qa.content.status if latest_qa is not None else None,
            review_verdict=(latest_review.content.verdict if latest_review is not None else None),
            criteria=_criteria(task, latest_qa),
            changed_files=(
                latest_implementation.content.changed_files
                if latest_implementation is not None
                else ()
            ),
            artifacts=tuple(_artifact_ref(artifact) for artifact in ordered),
            evidence=_evidence(ordered),
            event_ids=tuple(event.event_id for event in events),
            known_risks=(
                _risks(latest_plan, latest_implementation)
                if latest_plan is not None and latest_implementation is not None
                else ()
            ),
            blocked_classification=classification,
            blocked_reason=reason,
            next_actions=(
                "Inspect the blocked reason, findings, and referenced evidence before deciding.",
                "Resolve the external decision or create a new explicitly authorized Task/attempt.",
                "Do not mutate this terminal record or rewrite another role's verdict.",
            ),
            review_commands=(
                _review_commands(task.base_ref, candidate) if candidate is not None else ()
            ),
        )
        return _with_identity(provisional)


class FileHandoffStore:
    """Persist canonical JSON and deterministic Markdown as one immutable handoff."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise HandoffError(f"cannot initialize HandoffStore at {self._root}") from error

    def put(self, bundle: HandoffBundle) -> HandoffRef:
        if handoff_identity(bundle) != bundle.handoff_id:
            raise HandoffIntegrityError(bundle.handoff_id)
        json_path, markdown_path = self._paths(bundle.handoff_id)
        if json_path.exists() or markdown_path.exists():
            if not json_path.is_file() or not markdown_path.is_file():
                raise HandoffCorruption(f"incomplete persisted Handoff {bundle.handoff_id}")
            existing = self.get(bundle.handoff_id)
            if _identity_payload(existing) != _identity_payload(bundle):
                raise HandoffConflict(bundle.handoff_id)
            return _reference(existing, json_path, markdown_path)
        _atomic_write(json_path, _canonical_json(bundle.to_wire()))
        _atomic_write(markdown_path, render_handoff_markdown(bundle))
        persisted = self.get(bundle.handoff_id)
        return _reference(persisted, json_path, markdown_path)

    def get(self, handoff_id: HandoffId) -> HandoffBundle:
        json_path, markdown_path = self._paths(handoff_id)
        if not json_path.is_file() or not markdown_path.is_file():
            raise HandoffNotFound(handoff_id)
        try:
            payload: object = json.loads(json_path.read_text(encoding="utf-8"))
            bundle = HandoffBundle.model_validate(payload)
            markdown = markdown_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
            raise HandoffCorruption(f"cannot decode Handoff {handoff_id}") from error
        if bundle.handoff_id != handoff_id or handoff_identity(bundle) != handoff_id:
            raise HandoffCorruption(f"Handoff identity mismatch for {handoff_id}")
        if markdown != render_handoff_markdown(bundle):
            raise HandoffCorruption(f"Handoff Markdown mismatch for {handoff_id}")
        return bundle

    def _paths(self, handoff_id: HandoffId) -> tuple[Path, Path]:
        try:
            validated_id = _HANDOFF_ID_ADAPTER.validate_python(handoff_id)
        except ValidationError as error:
            raise HandoffNotFound(handoff_id) from error
        return self._root / f"{validated_id}.json", self._root / f"{validated_id}.md"


def handoff_identity(bundle: HandoffBundle) -> HandoffId:
    digest = hashlib.sha256(_canonical_json(_identity_payload(bundle)).encode("utf-8")).hexdigest()
    return f"handoff_{digest}"


def render_handoff_markdown(bundle: HandoffBundle) -> str:
    """Render a deterministic review document solely from typed bundle fields."""
    lines = [
        f"# Handoff: {bundle.title}",
        "",
        f"- Outcome: `{bundle.outcome.value}`",
        f"- Task: `{bundle.task_id}`",
        f"- Repository: `{bundle.repository}`",
        f"- Base revision: `{bundle.base_revision}`",
        f"- Candidate revision: `{bundle.candidate_revision or 'not available'}`",
        f"- Attempts: {bundle.attempts}",
        "",
        bundle.summary,
        "",
        "## Acceptance Criteria",
        "",
    ]
    for criterion in bundle.criteria:
        marker = "x" if criterion.status is HandoffCriterionStatus.PASS else " "
        criterion_evidence = ", ".join(criterion.evidence_ids) or "no evidence"
        lines.append(
            f"- [{marker}] `{criterion.criterion_id}` {criterion.description} "
            f"— {criterion.status.value}; evidence: {criterion_evidence}"
        )
    lines.extend(["", "## Changed Files", ""])
    if bundle.changed_files:
        for changed in bundle.changed_files:
            lines.append(
                f"- `{changed.path}` — {changed.change.value}; "
                f"+{changed.lines_added}/-{changed.lines_deleted}"
            )
    else:
        lines.append("- No candidate file list is available.")
    lines.extend(["", "## Evidence", ""])
    if bundle.evidence:
        for evidence in bundle.evidence:
            lines.append(
                f"- `{evidence.evidence_id}` [{evidence.type.value}] {evidence.description} "
                f"— `{evidence.uri}`"
            )
    else:
        lines.append("- No persisted evidence is available.")
    lines.extend(["", "## Known Risks", ""])
    lines.extend(f"- {risk}" for risk in bundle.known_risks)
    if not bundle.known_risks:
        lines.append("- No known risks were reported.")
    if bundle.blocked_reason is not None:
        lines.extend(["", "## Blocked Reason", "", bundle.blocked_reason])
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- {action}" for action in bundle.next_actions)
    if bundle.review_commands:
        lines.extend(["", "## Review Commands", ""])
        lines.extend(
            f"- {command.label}: `{shlex.join(command.argv)}`" for command in bundle.review_commands
        )
    lines.append("")
    return "\n".join(lines)


def _criteria(task: Task, qa: QaReportArtifact | None) -> tuple[HandoffCriterion, ...]:
    results = (
        {result.criterion_id: result for result in qa.content.criteria_results}
        if qa is not None
        else {}
    )
    criteria: list[HandoffCriterion] = []
    for criterion in task.acceptance_criteria:
        result = results.get(criterion.id)
        status = (
            HandoffCriterionStatus.NOT_ASSESSED
            if result is None
            else HandoffCriterionStatus(result.status.value)
        )
        criteria.append(
            HandoffCriterion(
                criterion_id=criterion.id,
                description=criterion.description,
                required=criterion.required,
                status=status,
                evidence_ids=result.evidence_ids if result is not None else (),
                notes=result.notes if result is not None else None,
            )
        )
    return tuple(criteria)


def _evidence(artifacts: tuple[Artifact, ...]) -> tuple[Evidence, ...]:
    found: dict[str, Evidence] = {}
    for artifact in artifacts:
        for evidence in artifact.evidence:
            existing = found.get(evidence.evidence_id)
            if existing is not None and existing != evidence:
                raise HandoffContractError(
                    f"evidence ID {evidence.evidence_id} has conflicting content"
                )
            found[evidence.evidence_id] = evidence
    return tuple(found[evidence_id] for evidence_id in sorted(found))


def _risks(plan: PlanArtifact, implementation: ImplementationReportArtifact) -> tuple[str, ...]:
    plan_risks = tuple(f"{item.risk} Mitigation: {item.mitigation}" for item in plan.content.risks)
    return (*plan_risks, *implementation.content.known_risks)


def _artifact_ref(artifact: Artifact) -> HandoffArtifact:
    return HandoffArtifact(
        artifact_id=artifact.artifact_id,
        kind=artifact.kind,
        sha256=artifact.integrity.sha256,
        producer_role=artifact.producer.role,
        run_id=artifact.producer.run_id,
        source_revision=artifact.source_revision,
        context_manifest_id=artifact.context_manifest_id,
        evidence_ids=tuple(item.evidence_id for item in artifact.evidence),
    )


def _review_commands(base: str, candidate: CommitSha) -> tuple[ReviewCommand, ...]:
    revision_range = f"{base}..{candidate}"
    return (
        ReviewCommand(
            label="Inspect candidate summary",
            argv=("git", "diff", "--stat", "--end-of-options", revision_range, "--"),
        ),
        ReviewCommand(
            label="Inspect candidate diff",
            argv=("git", "diff", "--end-of-options", revision_range, "--"),
        ),
    )


def _latest[ArtifactT: Artifact](
    artifacts: tuple[Artifact, ...], artifact_type: type[ArtifactT]
) -> ArtifactT | None:
    candidates = tuple(item for item in artifacts if isinstance(item, artifact_type))
    return max(candidates, key=lambda item: (item.created_at, item.artifact_id), default=None)


def _artifact_order(artifact: Artifact) -> tuple[int, object, str]:
    rank = {
        ArtifactKind.PLAN: 0,
        ArtifactKind.IMPLEMENTATION_REPORT: 1,
        ArtifactKind.QA_REPORT: 2,
        ArtifactKind.REVIEW_REPORT: 3,
    }
    return rank[artifact.kind], artifact.created_at, artifact.artifact_id


def _with_identity(bundle: HandoffBundle) -> HandoffBundle:
    return bundle.model_copy(update={"handoff_id": handoff_identity(bundle)})


def _identity_payload(bundle: HandoffBundle) -> WirePayload:
    payload = bundle.to_wire()
    payload.pop("handoff_id", None)
    payload.pop("generated_at", None)
    return payload


def _reference(bundle: HandoffBundle, json_path: Path, markdown_path: Path) -> HandoffRef:
    digest = hashlib.sha256(_canonical_json(bundle.to_wire()).encode("utf-8")).hexdigest()
    return HandoffRef(
        handoff_id=bundle.handoff_id,
        sha256=digest,
        json_path=json_path,
        markdown_path=markdown_path,
    )


def _canonical_json(payload: WirePayload) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _atomic_write(target: Path, content: str) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
    except OSError as error:
        raise HandoffError(f"failed to atomically write {target.name}") from error
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "FileHandoffStore",
    "HandoffArtifact",
    "HandoffBuilder",
    "HandoffBundle",
    "HandoffConflict",
    "HandoffContractError",
    "HandoffCorruption",
    "HandoffCriterion",
    "HandoffCriterionStatus",
    "HandoffError",
    "HandoffId",
    "HandoffIntegrityError",
    "HandoffNotFound",
    "HandoffNotReady",
    "HandoffOutcome",
    "HandoffRef",
    "ReviewCommand",
    "handoff_identity",
    "render_handoff_markdown",
]
