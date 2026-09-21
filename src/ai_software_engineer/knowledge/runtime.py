"""Production composition of frozen knowledge for upstream and Delivery roles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from ai_software_engineer.agents.structured import StructuredModelClient
from ai_software_engineer.context import ContextBundle, ContextSection, ContextSource, ContextStore
from ai_software_engineer.context.ports import ContextBudgetExceeded
from ai_software_engineer.domain import AgentDefinition, AgentRole, Task
from ai_software_engineer.domain.artifact import Artifact
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.knowledge.agents import (
    KnowledgeAwareStructuredClient,
    KnowledgeConsultationService,
)
from ai_software_engineer.knowledge.context import snapshot_from_sources
from ai_software_engineer.knowledge.gaps import (
    KnowledgeGap,
    KnowledgeResolution,
    KnowledgeWaitPort,
)
from ai_software_engineer.knowledge.models import (
    KnowledgeRunBinding,
    digest,
    text_digest,
)
from ai_software_engineer.knowledge.retrieval import KnowledgeRetrieval
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from ai_software_engineer.multi_directory.models import JointCheckpoint
from ai_software_engineer.orchestration.context import RunContextBuilder


def joint_knowledge_client(
    client: StructuredModelClient,
    checkpoint: JointCheckpoint,
    role: TeamRole,
    records_root: Path,
    retrieval: KnowledgeRetrieval | None = None,
) -> StructuredModelClient:
    repositories = tuple(sorted({p.result.repository_id for p in checkpoint.preparations}))
    if not repositories:
        return client
    snapshot = snapshot_from_sources(
        team_id=checkpoint.team_id,
        project_id=checkpoint.project_id,
        requirement_id=checkpoint.delivery_id,
        repository_ids=repositories,
        sources=tuple(
            (p.result.repository_id, source)
            for p in checkpoint.preparations
            for source in p.context_sources
        ),
    )
    identity = digest((checkpoint.checkpoint_sha256, role.value))
    binding = KnowledgeRunBinding(
        run_id="run_knowledge_" + identity[:32],
        role=role,
        team_id=checkpoint.team_id,
        project_id=checkpoint.project_id,
        requirement_id=checkpoint.delivery_id,
        repository_ids=repositories,
        source_revision=digest(
            tuple((unit.id, unit.base_revision) for unit in checkpoint.scope.units)
        ),
        context_manifest_id="ctx_" + identity,
        snapshot_sha256=snapshot.snapshot_sha256,
    )
    records = KnowledgeRecordStore(records_root)
    records.put("snapshots", snapshot.snapshot_sha256, snapshot)
    records.put("stage-contexts", binding.context_manifest_id, checkpoint)
    return KnowledgeAwareStructuredClient(
        client,
        binding,
        snapshot,
        records,
        retrieval,
        allow_repository_inspection=True,
    )


class KnowledgeRoleClients(Protocol):
    def for_project(self, repository_root: Path, role: TeamRole) -> StructuredModelClient: ...


def append_knowledge_context(
    context: ContextBundle, store: ContextStore, *, name: str, uri: str, content: str
) -> ContextBundle:
    """Seal the exact delivered bytes under the ordinary Context identity and budget."""
    tokens = (len(content) + 3) // 4
    used = context.budget.used_input_tokens + tokens
    if used > context.budget.max_input_tokens:
        raise ContextBudgetExceeded("Required knowledge consultation exceeds Context budget")
    section = ContextSection(
        name=name,
        uri=uri,
        sha256=text_digest(content),
        tokens=tokens,
        content=content,
        priority=50,
    )
    updated = context.model_copy(
        update={
            "sections": (*context.sections, section),
            "budget": context.budget.model_copy(update={"used_input_tokens": used}),
        }
    )
    payload = updated.model_dump(mode="json", exclude={"context_id", "built_at"})
    return store.put(updated.model_copy(update={"context_id": "ctx_" + digest(payload)}))


class KnowledgeRunContextBuilder:
    """Consult frozen sources before constructing the final Delivery Agent request.

    Consultation is its own bounded, recorded role run. Its immutable receipt is a
    required section in the final Context, so downstream Artifacts inherit its lineage.
    """

    def __init__(
        self,
        delegate: RunContextBuilder,
        *,
        contexts: ContextStore,
        clients: KnowledgeRoleClients,
        repository_root: Path,
        records: KnowledgeRecordStore,
        team_id: str,
        project_id: str,
        repository_id: str,
        sources: tuple[ContextSource, ...],
        retrieval: KnowledgeRetrieval | None = None,
        wait_port: KnowledgeWaitPort | None = None,
    ) -> None:
        self.delegate, self.contexts, self.clients = delegate, contexts, clients
        self.repository_root, self.records = repository_root, records
        self.team_id, self.project_id, self.repository_id = team_id, project_id, repository_id
        self.sources, self.retrieval = sources, retrieval
        self.wait_port = wait_port

    def build(
        self,
        task: Task,
        agent: AgentDefinition,
        *,
        attempt: int,
        candidate_revision: str | None = None,
        input_artifacts: tuple[Artifact, ...] = (),
    ) -> ContextBundle:
        base = self.delegate.build(
            task,
            agent,
            attempt=attempt,
            candidate_revision=candidate_revision,
            input_artifacts=input_artifacts,
        )
        if agent.role is AgentRole.ORCHESTRATOR:
            return base
        requirement_id = task.id
        for source in self.sources:
            if source.uri.startswith("joint://"):
                requirement_id = source.uri.split("/")[2]
        snapshot = snapshot_from_sources(
            team_id=self.team_id,
            project_id=self.project_id,
            requirement_id=requirement_id,
            repository_ids=(self.repository_id,),
            sources=tuple((self.repository_id, source) for source in self.sources),
        )
        self.records.put("snapshots", snapshot.snapshot_sha256, snapshot)
        resolutions = []
        for gap in self.records.list("gaps", KnowledgeGap):
            if (
                gap.binding.team_id,
                gap.binding.project_id,
                gap.binding.requirement_id,
                gap.binding.task_id,
                gap.binding.role,
                gap.binding.snapshot_sha256,
            ) != (
                self.team_id,
                self.project_id,
                requirement_id,
                task.id,
                TeamRole(agent.role.value),
                snapshot.snapshot_sha256,
            ):
                continue
            gap.validate_integrity()
            resolution = self.records.find("gap-resolutions", gap.gap_id, KnowledgeResolution)
            if resolution is not None:
                resolution.validate_integrity()
                resolutions.append(resolution)
        if resolutions:
            content = json.dumps(
                [
                    item.to_wire()
                    for item in sorted(resolutions, key=lambda item: item.resolution_id)
                ],
                ensure_ascii=False,
                sort_keys=True,
            )
            base = append_knowledge_context(
                base,
                self.contexts,
                name="knowledge.resolutions",
                uri="knowledge-resolution://" + text_digest(content),
                content=content,
            )
        binding = KnowledgeRunBinding(
            run_id="run_knowledge_" + digest((base.context_id, snapshot.snapshot_sha256))[:32],
            task_id=task.id,
            role=TeamRole(agent.role.value),
            team_id=self.team_id,
            project_id=self.project_id,
            requirement_id=requirement_id,
            repository_ids=(self.repository_id,),
            source_revision=base.source_revision,
            context_manifest_id=base.context_id,
            snapshot_sha256=snapshot.snapshot_sha256,
        )
        client = self.clients.for_project(self.repository_root, binding.role)
        consultation = KnowledgeConsultationService(
            client,
            self.records,
            self.retrieval,
            wait_port=self.wait_port,
            allow_repository_inspection=True,
        ).consult(
            binding,
            snapshot,
            {"task": task.to_wire(), "context": base.to_wire()},
            timeout_seconds=min(agent.timeout_seconds, 120),
        )
        return append_knowledge_context(
            base,
            self.contexts,
            name="knowledge.consultation",
            uri="knowledge://consultations/" + consultation.consultation_sha256,
            content=json.dumps(consultation.to_wire(), ensure_ascii=False, sort_keys=True),
        )
