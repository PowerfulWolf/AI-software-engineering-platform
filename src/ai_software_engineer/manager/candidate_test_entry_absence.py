"""Read-only candidate test-entry observation, never a QA verdict or admission.

This proves only a narrow Git-tree fact. A caller must separately validate the
current Requirement/Task/WorkItem checkpoint and original verifier no-start facts
before using it in any future recovery decision.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from ai_software_engineer.artifacts import ArtifactStore, artifact_digest
from ai_software_engineer.domain import (
    AgentRole,
    ImplementationReportArtifact,
    PlanArtifact,
    Task,
    TaskStatus,
)
from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.execution_window import PlannedVerificationRequirement
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.domain.native_verification import role_verification_digest
from ai_software_engineer.manager.verification_process import bounded_verification_command
from ai_software_engineer.work_queue.execution_store import AcceptedRoleArtifact

_ENVIRONMENT = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_ALLOW_PROTOCOL": "",
    "GIT_TERMINAL_PROMPT": "0",
}
_GIT = ("/usr/bin/git", "--literal-pathspecs", "-c", "core.fsmonitor=false")


def _git(root: Path, *arguments: str, limit: int = 4096) -> bytes:
    return bounded_verification_command(
        (*_GIT, *arguments), cwd=root, environment=_ENVIRONMENT, limit=limit
    )


def _exact_test_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or len(value) > 512
        or path.is_absolute()
        or str(path) != value
        or ".." in path.parts
        or any(character in value for character in "*?[]\\:")
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("planned test entry is not an exact safe relative path")
    return value


def _entry(root: Path, revision: str, path: str) -> bytes | None:
    raw = _git(root, "ls-tree", "-z", revision, "--", path)
    if not raw:
        return None
    if not raw.endswith(b"\0") or raw.count(b"\0") != 1:
        raise ValueError("candidate tree entry is ambiguous")
    metadata, separator, name = raw[:-1].partition(b"\t")
    if not separator or name != path.encode("utf-8"):
        raise ValueError("candidate tree entry does not match the planned path")
    return metadata


def _missing_regular_entry(root: Path, revision: str, path: str) -> bool:
    components = path.split("/")
    for index in range(1, len(components) + 1):
        prefix = "/".join(components[:index])
        entry = _entry(root, revision, prefix)
        if entry is None:
            return True
        mode = entry.split(b" ", 1)[0]
        if index < len(components):
            if mode != b"040000":
                raise ValueError("candidate test entry has a non-directory ancestor")
        elif mode in {b"100644", b"100755"}:
            return False
        else:
            raise ValueError("candidate test entry is not a regular file")
    raise AssertionError("unreachable")


class MissingPlannedTestEntry(DomainModel):
    requirement: PlannedVerificationRequirement
    requirement_sha256: Sha256
    path: NonEmptyStr

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if (
            self.requirement.role is not AgentRole.QA
            or self.requirement.argv is None
            or self.requirement_sha256 != role_verification_digest(self.requirement.to_wire())
            or self.path not in self.requirement.planned_new_files
            or not any(
                token == self.path or token.startswith(self.path + "::")
                for token in self.requirement.argv
            )
        ):
            raise ValueError("missing entry must bind an exact frozen QA command row")
        _exact_test_path(self.path)
        return self


class CandidateTestEntryAbsenceObservation(DomainModel):
    """One candidate-tree observation; deliberately has no executable authority."""

    kind: Literal["candidate_test_entry_absence_observation_v1"] = (
        "candidate_test_entry_absence_observation_v1"
    )
    task_id: NonEmptyStr
    task_intent_sha256: Sha256
    candidate_revision: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
    plan_artifact_id: NonEmptyStr
    plan_artifact_sha256: Sha256
    plan_requirements_sha256: Sha256
    implementation_artifact_id: NonEmptyStr
    implementation_artifact_sha256: Sha256
    missing: Annotated[tuple[MissingPlannedTestEntry, ...], Field(min_length=1, max_length=64)]
    observation_sha256: Sha256

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        ensure_unique(
            ((entry.requirement.id, entry.path) for entry in self.missing), "missing entries"
        )
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        observation = cls.model_validate({**values, "observation_sha256": "0" * 64})
        return observation.model_copy(update={"observation_sha256": observation.recompute_sha256()})

    def recompute_sha256(self) -> str:
        return role_verification_digest(
            self.model_dump(mode="json", exclude={"observation_sha256"})
        )

    def validate_integrity(self) -> None:
        type(self).model_validate(self.to_wire())
        if self.observation_sha256 != self.recompute_sha256():
            raise ValueError("candidate test entry absence observation changed")


def observe_candidate_test_entry_absence(
    *,
    repository_root: Path,
    task: Task,
    plan: PlanArtifact,
    implementation: ImplementationReportArtifact,
) -> CandidateTestEntryAbsenceObservation:
    """Inspect exact frozen QA rows at a full candidate SHA without running code."""
    root = repository_root.absolute()
    revision = implementation.source_revision
    rows = plan.content.verification_requirements
    if (
        root.resolve(strict=True) != root
        or str(root) != task.repository
        or task.status is not TaskStatus.QA
        or rows is None
        or plan.task_id != task.id
        or implementation.task_id != task.id
        or plan.artifact_id not in implementation.parent_artifact_ids
        or implementation.content.commit_sha != revision
        or re.fullmatch(r"[a-f0-9]{40}", revision) is None
    ):
        raise ValueError("candidate observation source facts do not match")
    ensure_unique((row.id for row in rows), "verification requirement IDs")
    if _git(root, "rev-parse", "--show-toplevel").decode("utf-8").strip() != str(root):
        raise ValueError("candidate observation repository root changed")
    if _git(root, "cat-file", "-t", revision).strip() != b"commit":
        raise ValueError("candidate observation source is not a commit")
    missing = []
    for row in rows:
        if row.role is not AgentRole.QA or row.argv is None:
            continue
        for path in row.planned_new_files:
            entry = MissingPlannedTestEntry(
                requirement=row,
                requirement_sha256=role_verification_digest(row.to_wire()),
                path=path,
            )
            if _missing_regular_entry(root, revision, path):
                missing.append(entry)
    if not missing:
        raise ValueError("candidate contains every planned test entry")
    observation = CandidateTestEntryAbsenceObservation.create(
        task_id=task.id,
        task_intent_sha256=task_intent_sha256(task),
        candidate_revision=revision,
        plan_artifact_id=plan.artifact_id,
        plan_artifact_sha256=artifact_digest(plan),
        plan_requirements_sha256=role_verification_digest([row.to_wire() for row in rows]),
        implementation_artifact_id=implementation.artifact_id,
        implementation_artifact_sha256=artifact_digest(implementation),
        missing=tuple(missing),
    )
    observation.validate_integrity()
    return observation


def observe_accepted_candidate_test_entry_absence(
    *,
    repository_root: Path,
    task: Task,
    source_revision: str,
    accepted: tuple[AcceptedRoleArtifact, ...],
    artifacts: ArtifactStore,
) -> CandidateTestEntryAbsenceObservation:
    """Bind the Git-tree absence to the accepted Plan and candidate lineage.

    The caller still has to prove the current wait and original QA no-start.
    This read-only seam grants no claim, execution permission or QA verdict.
    """
    candidates: list[ImplementationReportArtifact] = []
    for record in accepted:
        if record.task_id != task.id or record.source_revision != source_revision:
            continue
        artifact = artifacts.get(record.receipt.artifact_id)
        if (
            artifact.integrity.sha256 != record.receipt.sha256
            or artifact_digest(artifact) != record.receipt.sha256
            or artifact.task_id != task.id
        ):
            raise ValueError("accepted candidate receipt changed")
        if isinstance(artifact, ImplementationReportArtifact):
            candidates.append(artifact)
    if len(candidates) != 1:
        raise ValueError("static QA requires one exact accepted candidate")
    implementation = candidates[0]
    if len(implementation.parent_artifact_ids) != 1:
        raise ValueError("static QA candidate requires one frozen Plan parent")
    plan = artifacts.get(implementation.parent_artifact_ids[0])
    if not isinstance(plan, PlanArtifact) or not any(
        record.task_id == task.id
        and record.receipt.artifact_id == plan.artifact_id
        and record.receipt.sha256 == artifact_digest(plan)
        and record.source_revision == plan.source_revision
        for record in accepted
    ):
        raise ValueError("static QA requires the accepted Plan")
    return observe_candidate_test_entry_absence(
        repository_root=repository_root,
        task=task,
        plan=plan,
        implementation=implementation,
    )
