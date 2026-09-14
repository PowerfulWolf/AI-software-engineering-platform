"""Evidence-backed Learning proposals and human-controlled publication."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, TypeAdapter, model_validator

from ai_software_engineer.artifacts import ArtifactStoreError, FileArtifactStore
from ai_software_engineer.domain.artifact import (
    ArtifactId,
    Finding,
    QaReportArtifact,
    ReviewReportArtifact,
)
from ai_software_engineer.domain.enums import (
    QaReportStatus,
    ReviewVerdict,
    TeamRole,
)
from ai_software_engineer.domain.identity import ProjectId, RepositoryId, TeamId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.task import TaskId
from ai_software_engineer.knowledge_documents import (
    KnowledgeDocumentError,
    ProjectKnowledgeDocumentStore,
)
from ai_software_engineer.knowledge_selection import (
    KnowledgeSelectionError,
    ProjectKnowledgeSelectionStore,
    effective_project_knowledge_paths,
)
from ai_software_engineer.project_workspace import ProjectWorkspace
from ai_software_engineer.spec_documents import (
    CreateSpecDocument,
    ProjectSpecDocumentStore,
    SpecDocumentError,
)

LearningProposalId = Annotated[str, StringConstraints(pattern=r"^learning_proposal_[a-f0-9]{32}$")]
LearningDecisionId = Annotated[str, StringConstraints(pattern=r"^learning_decision_[a-f0-9]{32}$")]
LearningAuthorizationId = Annotated[
    str, StringConstraints(pattern=r"^learning_authorization_[a-f0-9]{32}$")
]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
_MAX_RECORD_BYTES = 512_000
_SAFE_FRAGMENT = re.compile(r"[^a-z0-9.-]+")


class LearningError(RuntimeError):
    """Raised when Learning evidence, decisions or publication cannot be trusted."""


class LearningTrigger(StrEnum):
    QA_FAILURE = "QA_FAILURE"
    REVIEW_REJECTION = "REVIEW_REJECTION"


class LearningTarget(StrEnum):
    KNOWLEDGE = "KNOWLEDGE"
    SPEC = "SPEC"
    SKILL = "SKILL"


class LearningDecisionAction(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class LearningEvidence(DomainModel):
    repository_id: RepositoryId
    task_id: TaskId
    artifact_id: ArtifactId
    artifact_sha256: Digest
    finding_id: NonEmptyStr
    evidence_uris: tuple[NonEmptyStr, ...]

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        ensure_unique(self.evidence_uris, "Learning evidence URIs")
        return self


class LearningProposal(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    proposal_id: LearningProposalId
    team_id: TeamId
    project_id: ProjectId
    trigger: LearningTrigger
    recurrence_key: Digest
    occurrence_count: Annotated[int, Field(ge=1)]
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    observation: NonEmptyStr
    proposed_improvement: NonEmptyStr
    verification: NonEmptyStr
    suggested_target: LearningTarget = LearningTarget.SPEC
    evidence: Annotated[tuple[LearningEvidence, ...], Field(min_length=1)]
    created_at: AwareDatetime
    proposal_sha256: Digest

    @model_validator(mode="after")
    def validate_proposal(self) -> Self:
        ensure_unique(
            (
                (item.repository_id, item.task_id, item.artifact_id, item.finding_id)
                for item in self.evidence
            ),
            "Learning evidence identities",
        )
        return self

    def recompute_digest(self) -> str:
        return _sha256(self.model_dump(mode="json", exclude={"proposal_sha256"}))

    def validate_integrity(self) -> None:
        identity = _proposal_identity(self)
        if self.proposal_id != f"learning_proposal_{identity[:32]}":
            raise LearningError("Learning proposal identity mismatch")
        if self.proposal_sha256 != self.recompute_digest():
            raise LearningError("Learning proposal digest mismatch")

    def as_markdown(self) -> str:
        evidence = "\n".join(
            f"- `{item.repository_id}` / `{item.task_id}` / `{item.artifact_id}` / "
            f"`{item.finding_id}`"
            for item in self.evidence
        )
        return (
            f"# {self.title}\n\n"
            "## Observed failure\n\n"
            f"{self.observation}\n\n"
            "## Proposed improvement\n\n"
            f"{self.proposed_improvement}\n\n"
            "## Verification\n\n"
            f"{self.verification}\n\n"
            "## Evidence\n\n"
            f"{evidence}\n"
        )


class DecideLearningProposal(DomainModel):
    proposal_sha256: Digest
    action: LearningDecisionAction
    target: LearningTarget
    operator_id: NonEmptyStr
    rationale: NonEmptyStr


class LearningAuthorization(DomainModel):
    """Durable human authorization written before any approved publication."""

    schema_version: Literal["v0.1"] = "v0.1"
    authorization_id: LearningAuthorizationId
    proposal_id: LearningProposalId
    proposal_sha256: Digest
    action: LearningDecisionAction
    target: LearningTarget
    operator_id: NonEmptyStr
    rationale: NonEmptyStr
    authorized_at: AwareDatetime
    authorization_sha256: Digest

    def recompute_digest(self) -> str:
        return _sha256(self.model_dump(mode="json", exclude={"authorization_sha256"}))

    def validate_integrity(self) -> None:
        identity = _authorization_identity(self)
        if self.authorization_id != f"learning_authorization_{identity[:32]}":
            raise LearningError("Learning authorization identity mismatch")
        if self.authorization_sha256 != self.recompute_digest():
            raise LearningError("Learning authorization digest mismatch")


class LearningDecision(DomainModel):
    schema_version: Literal["v0.1"] = "v0.1"
    decision_id: LearningDecisionId
    proposal_id: LearningProposalId
    proposal_sha256: Digest
    action: LearningDecisionAction
    target: LearningTarget
    operator_id: NonEmptyStr
    rationale: NonEmptyStr
    published_uri: NonEmptyStr | None = None
    decided_at: AwareDatetime
    decision_sha256: Digest

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if (self.action is LearningDecisionAction.APPROVE) != (self.published_uri is not None):
            raise ValueError("only an approved Learning decision has a publication")
        return self

    def recompute_digest(self) -> str:
        return _sha256(self.model_dump(mode="json", exclude={"decision_sha256"}))

    def validate_integrity(self) -> None:
        identity = _decision_identity(self)
        if self.decision_id != f"learning_decision_{identity[:32]}":
            raise LearningError("Learning decision identity mismatch")
        if self.decision_sha256 != self.recompute_digest():
            raise LearningError("Learning decision digest mismatch")


class LearningProposalView(DomainModel):
    proposal: LearningProposal
    authorization: LearningAuthorization | None = None
    decision: LearningDecision | None = None


@dataclass(frozen=True, slots=True)
class _ObservedFinding:
    finding_id: str
    code: str | None
    message: str
    file: str | None
    evidence_ids: tuple[str, ...]
    recommendation: str | None

    @classmethod
    def from_finding(cls, finding: Finding) -> _ObservedFinding:
        return cls(
            finding_id=finding.finding_id,
            code=finding.code,
            message=finding.message,
            file=finding.file,
            evidence_ids=finding.evidence_ids,
            recommendation=finding.recommendation,
        )


@dataclass(frozen=True, slots=True)
class ProjectLearningStore:
    project: ProjectWorkspace

    @property
    def root(self) -> Path:
        return self.project.root / "specs" / "learning"

    def collect(self, *, collected_at: datetime | None = None) -> tuple[LearningProposalView, ...]:
        self.project.validate_current()
        timestamp = collected_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise LearningError("Learning collection timestamp must include a timezone")
        failures = _failure_evidence(self.project)
        occurrence_counts: dict[str, int] = {}
        for item in failures:
            key = _recurrence_key(item[2])
            occurrence_counts[key] = occurrence_counts.get(key, 0) + 1
        for repository_id, artifact, finding in failures:
            proposal = _proposal(
                self.project,
                repository_id=repository_id,
                artifact=artifact,
                finding=finding,
                occurrence_count=occurrence_counts[_recurrence_key(finding)],
                created_at=timestamp,
            )
            self._put_proposal(proposal)
        return self.list()

    def list(self) -> tuple[LearningProposalView, ...]:
        self.project.validate_current()
        if not self.root.exists():
            return ()
        _require_directory(self.root)
        views: list[LearningProposalView] = []
        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            proposal = self._read_proposal(directory)
            authorization_path = directory / "authorization.json"
            authorization = (
                self._read_authorization(authorization_path)
                if authorization_path.exists()
                else None
            )
            decision_path = directory / "decision.json"
            decision = self._read_decision(decision_path) if decision_path.exists() else None
            views.append(
                LearningProposalView(
                    proposal=proposal,
                    authorization=authorization,
                    decision=decision,
                )
            )
        return tuple(
            sorted(
                views,
                key=lambda item: (item.proposal.created_at, item.proposal.proposal_id),
            )
        )

    def decide(
        self,
        proposal_id: str,
        command: DecideLearningProposal,
        *,
        decided_at: datetime | None = None,
    ) -> LearningProposalView:
        self.project.validate_current()
        identity = TypeAdapter(LearningProposalId).validate_python(proposal_id)
        directory = self.root / identity
        proposal = self._read_proposal(directory)
        if proposal.proposal_sha256 != command.proposal_sha256:
            raise LearningError("Learning decision does not match the exact proposal")
        decision_path = directory / "decision.json"
        if decision_path.exists() or decision_path.is_symlink():
            existing = self._read_decision(decision_path)
            if (
                existing.proposal_sha256 == command.proposal_sha256
                and existing.action is command.action
                and existing.target is command.target
                and existing.operator_id == command.operator_id
                and existing.rationale == command.rationale
            ):
                authorization_path = directory / "authorization.json"
                authorization = (
                    self._read_authorization(authorization_path)
                    if authorization_path.exists()
                    else None
                )
                return LearningProposalView(
                    proposal=proposal,
                    authorization=authorization,
                    decision=existing,
                )
            raise LearningError("Learning proposal already has a different immutable decision")
        timestamp = decided_at or datetime.now(UTC)
        authorization = self._authorize(directory, proposal, command, timestamp)
        try:
            published_uri = (
                self._publish(proposal, command.target)
                if command.action is LearningDecisionAction.APPROVE
                else None
            )
        except (
            KnowledgeDocumentError,
            KnowledgeSelectionError,
            SpecDocumentError,
            OSError,
            ValueError,
        ) as error:
            raise LearningError("Approved Learning publication could not be completed") from error
        provisional = LearningDecision(
            decision_id="learning_decision_" + "0" * 32,
            proposal_id=proposal.proposal_id,
            proposal_sha256=proposal.proposal_sha256,
            action=command.action,
            target=command.target,
            operator_id=command.operator_id,
            rationale=command.rationale,
            published_uri=published_uri,
            decided_at=authorization.authorized_at,
            decision_sha256="0" * 64,
        )
        identity_digest = _decision_identity(provisional)
        identified = provisional.model_copy(
            update={"decision_id": f"learning_decision_{identity_digest[:32]}"}
        )
        decision = identified.model_copy(update={"decision_sha256": identified.recompute_digest()})
        _write_new(decision_path, decision.model_dump_json(indent=2).encode())
        return LearningProposalView(
            proposal=proposal,
            authorization=authorization,
            decision=self._read_decision(decision_path),
        )

    def _authorize(
        self,
        directory: Path,
        proposal: LearningProposal,
        command: DecideLearningProposal,
        authorized_at: datetime,
    ) -> LearningAuthorization:
        path = directory / "authorization.json"
        if path.exists() or path.is_symlink():
            existing = self._read_authorization(path)
            if (
                existing.proposal_id == proposal.proposal_id
                and existing.proposal_sha256 == command.proposal_sha256
                and existing.action is command.action
                and existing.target is command.target
                and existing.operator_id == command.operator_id
                and existing.rationale == command.rationale
            ):
                return existing
            raise LearningError("Learning proposal already has a different authorization")
        provisional = LearningAuthorization(
            authorization_id="learning_authorization_" + "0" * 32,
            proposal_id=proposal.proposal_id,
            proposal_sha256=command.proposal_sha256,
            action=command.action,
            target=command.target,
            operator_id=command.operator_id,
            rationale=command.rationale,
            authorized_at=authorized_at,
            authorization_sha256="0" * 64,
        )
        identity = _authorization_identity(provisional)
        identified = provisional.model_copy(
            update={"authorization_id": f"learning_authorization_{identity[:32]}"}
        )
        authorization = identified.model_copy(
            update={"authorization_sha256": identified.recompute_digest()}
        )
        _write_new(path, authorization.model_dump_json(indent=2).encode())
        return self._read_authorization(path)

    def _publish(self, proposal: LearningProposal, target: LearningTarget) -> str:
        body = proposal.as_markdown()
        if target is LearningTarget.KNOWLEDGE:
            knowledge_store = ProjectKnowledgeDocumentStore(self.project)
            document = knowledge_store.import_document(
                filename=f"{proposal.proposal_id}.md",
                content=body.encode(),
            )
            selection = set(effective_project_knowledge_paths(self.project))
            selection.add(document.normalized_relative_path)
            ProjectKnowledgeSelectionStore(self.project).save(tuple(sorted(selection)))
            return (
                f"project://{self.project.manifest.project_id}/knowledge/"
                f"{document.normalized_relative_path}#{document.normalized_sha256}"
            )
        if target is LearningTarget.SPEC:
            spec_store = ProjectSpecDocumentStore(self.project)
            key = f"learning.{proposal.recurrence_key[:24]}"
            spec = spec_store.create(
                CreateSpecDocument(
                    spec_key=key,
                    title=proposal.title,
                    body_markdown=body,
                    roles=(TeamRole.CODER, TeamRole.QA, TeamRole.REVIEWER),
                    stages=("implementing", "qa", "review"),
                    path_globs=("*",),
                    verification=proposal.verification,
                )
            )
            activation = spec_store.activation()
            active = {
                item.spec_key: item.spec_id
                for item in activation.active
                if item.spec_key != spec.spec_key
            }
            active[spec.spec_key] = spec.spec_id
            spec_store.activate(tuple(active[key] for key in sorted(active)))
            return f"project://{self.project.manifest.project_id}/specs/{spec.spec_id}"
        return self._publish_skill_design(proposal, body)

    def _publish_skill_design(self, proposal: LearningProposal, body: str) -> str:
        root = self.project.team.root / "skills" / "learning-proposals"
        root.mkdir(parents=True, exist_ok=True)
        _require_directory(root)
        target = root / f"{proposal.proposal_id}.md"
        if target.exists():
            if _read_regular(target, _MAX_RECORD_BYTES).decode() != body:
                raise LearningError("Skill-design proposal identity collision")
        else:
            _write_new(target, body.encode())
        return f"platform://team/{proposal.team_id}/skills/proposals/{proposal.proposal_id}"

    def _put_proposal(self, proposal: LearningProposal) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        _require_directory(self.root)
        target = self.root / proposal.proposal_id
        if target.exists() or target.is_symlink():
            if self._read_proposal(target) != proposal:
                # Collection time is not identity. Keep the first immutable observation.
                existing = self._read_proposal(target)
                if _proposal_identity(existing) != _proposal_identity(proposal):
                    raise LearningError("Learning proposal identity collision")
            return
        target.mkdir()
        _write_new(target / "proposal.json", proposal.model_dump_json(indent=2).encode())

    def _read_proposal(self, directory: Path) -> LearningProposal:
        _require_directory(directory)
        try:
            proposal = LearningProposal.model_validate_json(
                _read_regular(directory / "proposal.json", _MAX_RECORD_BYTES)
            )
        except ValueError as error:
            raise LearningError("Learning proposal is invalid") from error
        proposal.validate_integrity()
        if directory.name != proposal.proposal_id:
            raise LearningError("Learning proposal directory identity mismatch")
        if (
            proposal.team_id != self.project.manifest.team_id
            or proposal.project_id != self.project.manifest.project_id
        ):
            raise LearningError("Learning proposal owner mismatch")
        return proposal

    def _read_decision(self, path: Path) -> LearningDecision:
        try:
            decision = LearningDecision.model_validate_json(_read_regular(path, _MAX_RECORD_BYTES))
        except ValueError as error:
            raise LearningError("Learning decision is invalid") from error
        decision.validate_integrity()
        if path.parent.name != decision.proposal_id:
            raise LearningError("Learning decision owner mismatch")
        return decision

    def _read_authorization(self, path: Path) -> LearningAuthorization:
        try:
            authorization = LearningAuthorization.model_validate_json(
                _read_regular(path, _MAX_RECORD_BYTES)
            )
        except ValueError as error:
            raise LearningError("Learning authorization is invalid") from error
        authorization.validate_integrity()
        if path.parent.name != authorization.proposal_id:
            raise LearningError("Learning authorization owner mismatch")
        return authorization


def _failure_evidence(
    project: ProjectWorkspace,
) -> tuple[tuple[RepositoryId, QaReportArtifact | ReviewReportArtifact, _ObservedFinding], ...]:
    values: list[
        tuple[RepositoryId, QaReportArtifact | ReviewReportArtifact, _ObservedFinding]
    ] = []
    try:
        for repository in project.repository_registry().discover():
            root = repository.directory("artifacts")
            store = FileArtifactStore(root, read_only=True)
            for path in sorted(root.glob("art_*.json")):
                artifact = store.get(TypeAdapter(ArtifactId).validate_python(path.stem))
                failure: QaReportArtifact | ReviewReportArtifact
                match artifact:
                    case QaReportArtifact() if artifact.content.status is QaReportStatus.FAIL:
                        failure = artifact
                    case ReviewReportArtifact() if artifact.content.verdict is ReviewVerdict.REJECT:
                        failure = artifact
                    case _:
                        continue
                values.extend(
                    (repository.repository_id, failure, finding)
                    for finding in _findings_or_fallback(failure)
                )
    except (ArtifactStoreError, OSError, ValueError) as error:
        raise LearningError("Learning evidence cannot be trusted") from error
    return tuple(values)


def _findings_or_fallback(
    artifact: QaReportArtifact | ReviewReportArtifact,
) -> tuple[_ObservedFinding, ...]:
    if artifact.content.findings:
        return tuple(_ObservedFinding.from_finding(item) for item in artifact.content.findings)
    # A QA FAIL may be expressed only by criterion/test results.
    return (
        _ObservedFinding(
            finding_id=f"failure-{artifact.artifact_id}",
            code="QA_FAILURE_WITHOUT_FINDING",
            message="QA reported FAIL without a structured finding.",
            evidence_ids=tuple(item.evidence_id for item in artifact.evidence[:1]),
            file=None,
            recommendation="Add a regression test and a precise failure-prevention rule.",
        ),
    )


def _proposal(
    project: ProjectWorkspace,
    *,
    repository_id: RepositoryId,
    artifact: QaReportArtifact | ReviewReportArtifact,
    finding: _ObservedFinding,
    occurrence_count: int,
    created_at: datetime,
) -> LearningProposal:
    trigger = (
        LearningTrigger.QA_FAILURE
        if isinstance(artifact, QaReportArtifact)
        else LearningTrigger.REVIEW_REJECTION
    )
    recurrence_key = _recurrence_key(finding)
    evidence_by_id = {item.evidence_id: item for item in artifact.evidence}
    evidence_uris = tuple(
        sorted(
            evidence_by_id[identity].uri
            for identity in finding.evidence_ids
            if identity in evidence_by_id
        )
    )
    evidence = LearningEvidence(
        repository_id=repository_id,
        task_id=artifact.task_id,
        artifact_id=artifact.artifact_id,
        artifact_sha256=artifact.integrity.sha256,
        finding_id=finding.finding_id,
        evidence_uris=evidence_uris,
    )
    title_fragment = finding.code or finding.finding_id
    title = f"Prevent recurrence: {title_fragment}"[:200]
    proposal_seed = {
        "team_id": project.manifest.team_id,
        "project_id": project.manifest.project_id,
        "trigger": trigger.value,
        "recurrence_key": recurrence_key,
        "evidence": [evidence.to_wire()],
    }
    identity = _sha256(proposal_seed)
    provisional = LearningProposal(
        proposal_id=f"learning_proposal_{identity[:32]}",
        team_id=project.manifest.team_id,
        project_id=project.manifest.project_id,
        trigger=trigger,
        recurrence_key=recurrence_key,
        occurrence_count=occurrence_count,
        title=title,
        observation=finding.message,
        proposed_improvement=(
            finding.recommendation
            or "Define a mandatory prevention rule and preserve regression evidence."
        ),
        verification=(
            "Reproduce the original failure, add a regression check, and require independent "
            "QA/Review evidence before delivery."
        ),
        evidence=(evidence,),
        created_at=created_at,
        proposal_sha256="0" * 64,
    )
    return provisional.model_copy(update={"proposal_sha256": provisional.recompute_digest()})


def _recurrence_key(finding: _ObservedFinding) -> str:
    return _sha256(
        {
            "code": finding.code,
            "message": finding.message.strip().lower(),
            "file": finding.file,
        }
    )


def _proposal_identity(proposal: LearningProposal) -> str:
    evidence = [item.to_wire() for item in proposal.evidence]
    return _sha256(
        {
            "team_id": proposal.team_id,
            "project_id": proposal.project_id,
            "trigger": proposal.trigger.value,
            "recurrence_key": proposal.recurrence_key,
            "evidence": evidence,
        }
    )


def _decision_identity(decision: LearningDecision) -> str:
    return _sha256(
        decision.model_dump(
            mode="json",
            exclude={"decision_id", "decided_at", "decision_sha256"},
        )
    )


def _authorization_identity(authorization: LearningAuthorization) -> str:
    return _sha256(
        authorization.model_dump(
            mode="json",
            exclude={"authorization_id", "authorized_at", "authorization_sha256"},
        )
    )


def _sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _require_directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise LearningError("Learning store cannot traverse a symlink")


def _read_regular(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise LearningError("Learning record path is not a regular file")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise LearningError("Learning record is not a regular file")
            payload = stream.read(maximum + 1)
    except OSError as error:
        raise LearningError("Learning record could not be read") from error
    if len(payload) > maximum:
        raise LearningError("Learning record exceeds its size limit")
    return payload


def _write_new(path: Path, payload: bytes) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        raise LearningError("Learning record could not be published") from error


__all__ = [
    "DecideLearningProposal",
    "LearningAuthorization",
    "LearningDecision",
    "LearningDecisionAction",
    "LearningError",
    "LearningProposal",
    "LearningProposalView",
    "LearningTarget",
    "LearningTrigger",
    "ProjectLearningStore",
]
