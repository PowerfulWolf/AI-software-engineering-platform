"""The public native entry continues a stopped Coder through real production seams."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ai_software_engineer.agents import (
    AgentRequest,
)
from ai_software_engineer.agents.codex_cli import (
    CodexCliAgentAdapter,
)
from ai_software_engineer.domain import (
    AgentProducer,
    Artifact,
    ArtifactIntegrity,
    ChangedFile,
    ChangeType,
    ImplementationAcceptanceMapping,
    ImplementationReportArtifact,
    ImplementationReportContent,
)
from ai_software_engineer.work_queue.models import QueueClaim
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn


@dataclass(frozen=True)
class Invocation:
    request: AgentRequest
    claim: QueueClaim
    workspace: Path
    branch: str
    input_head: str
    model: str


def _coder_draft(adapter: CodexCliAgentAdapter, request: AgentRequest) -> Artifact:
    return ImplementationReportArtifact(
        artifact_id=f"art_impl_{request.run_id.removeprefix('run_')}",
        task_id=request.task_id,
        schema_version="v0.1",
        producer=AgentProducer(
            role=request.role,
            agent_id=adapter._agent_id,
            agent_version=adapter._agent_version,
            run_id=request.run_id,
        ),
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        created_at=datetime.now(UTC),
        parent_artifact_ids=request.input_artifact_ids,
        evidence=(),
        integrity=ArtifactIntegrity(sha256="0" * 64, validated=False),
        content=ImplementationReportContent(
            # The native executor reports a draft. Only CandidateCommitSkill
            # may replace this source with a platform-owned candidate commit.
            commit_sha=request.source_revision,
            changed_files=(
                ChangedFile(
                    path="hello.txt", change=ChangeType.MODIFIED, lines_added=1, lines_deleted=1
                ),
            ),
            acceptance_mapping=(
                ImplementationAcceptanceMapping(
                    criterion_id="ac_001_001", implementation="Updated the greeting.", tests=()
                ),
            ),
            tests_run=(),
            known_risks=(),
        ),
    )
