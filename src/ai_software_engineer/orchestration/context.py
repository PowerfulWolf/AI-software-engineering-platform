"""Compose explicit upstream Artifacts into role-scoped Agent Run contexts."""

import json
from pathlib import Path
from typing import Protocol

from ai_software_engineer.context import ContextBundle, ContextSource, FileContextBuilder
from ai_software_engineer.context.ports import ContextSourceError
from ai_software_engineer.domain.agent import AgentDefinition
from ai_software_engineer.domain.artifact import Artifact
from ai_software_engineer.domain.task import Task


class RunContextBuilder(Protocol):
    """Build one ContextBundle from declared, persisted upstream Artifacts."""

    def build(
        self,
        task: Task,
        agent: AgentDefinition,
        *,
        attempt: int,
        candidate_revision: str | None = None,
        input_artifacts: tuple[Artifact, ...] = (),
    ) -> ContextBundle: ...


class FileRunContextBuilder:
    """Create a FileContextBuilder per run with explicit Artifact sources."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        sources: tuple[ContextSource, ...] = (),
    ) -> None:
        self._project_root = Path(project_root)
        self._sources = sources

    def build(
        self,
        task: Task,
        agent: AgentDefinition,
        *,
        attempt: int,
        candidate_revision: str | None = None,
        input_artifacts: tuple[Artifact, ...] = (),
    ) -> ContextBundle:
        """Compile machine policy, Task, role and persisted Artifact wire payloads."""
        artifact_sources = self._artifact_sources(task, agent, input_artifacts)
        builder = FileContextBuilder(
            self._project_root,
            agent.permissions,
            sources=self._sources + artifact_sources,
        )
        return builder.build(
            task,
            agent.role,
            attempt=attempt,
            candidate_revision=candidate_revision,
        )

    @staticmethod
    def _artifact_sources(
        task: Task,
        agent: AgentDefinition,
        artifacts: tuple[Artifact, ...],
    ) -> tuple[ContextSource, ...]:
        artifact_ids = tuple(artifact.artifact_id for artifact in artifacts)
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ContextSourceError("Agent Run input Artifact IDs must be unique")

        sources: list[ContextSource] = []
        allowed_kinds = set(agent.input_artifacts)
        for artifact in artifacts:
            if artifact.task_id != task.id:
                raise ContextSourceError(f"Artifact {artifact.artifact_id} belongs to another Task")
            if artifact.kind not in allowed_kinds:
                raise ContextSourceError(f"{agent.role.value} cannot consume {artifact.kind.value}")
            sources.append(
                ContextSource(
                    source_id=f"artifact.{artifact.artifact_id}",
                    uri=f"artifact://{artifact.artifact_id}",
                    content=_canonical_artifact(artifact),
                    roles=(agent.role,),
                    priority=60,
                    required=True,
                )
            )
        return tuple(sources)


def _canonical_artifact(artifact: Artifact) -> str:
    return json.dumps(
        artifact.to_wire(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


__all__ = ["FileRunContextBuilder", "RunContextBuilder"]
