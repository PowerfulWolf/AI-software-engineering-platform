"""Typed ArtifactStore boundary independent of the filesystem implementation."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ai_software_engineer.domain.artifact import Artifact, ArtifactId, Sha256
from ai_software_engineer.domain.enums import ArtifactKind
from ai_software_engineer.domain.task import TaskId


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Stable metadata returned after an Artifact is durably stored."""

    artifact_id: ArtifactId
    task_id: TaskId
    kind: ArtifactKind
    sha256: Sha256
    path: Path


class ArtifactStore(Protocol):
    """Minimal immutable Artifact persistence seam used by the Orchestrator."""

    def put(self, artifact: Artifact) -> ArtifactRef: ...

    def get(self, artifact_id: ArtifactId) -> Artifact: ...

    def list_for_task(self, task_id: TaskId) -> tuple[Artifact, ...]: ...
