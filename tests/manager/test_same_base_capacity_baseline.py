"""Public runtime-only capacity recovery preserves real stopped dirty Coder history."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.agents.codex_cli import (
    CodexCliAgentAdapter,
)
from ai_software_engineer.domain import (
    AgentRole,
    Artifact,
    Evidence,
    EvidenceType,
    QaReportArtifact,
    QaTestRun,
    QaTestStatus,
    ReviewReportArtifact,
)
from ai_software_engineer.execution import SubprocessCommandExecutor
from tests.manager.test_production_backend import _ScriptedDeliveryAdapter
from tests.manager.test_production_backend import mysql_dsn as mysql_dsn
from tests.orchestration.test_runner import _definitions

_DESIRED = "hello from the team\n"


def _independent_report(
    adapter: CodexCliAgentAdapter, request: AgentRequest, cwd: Path, evidence_root: Path
) -> Artifact:
    definition = _definitions()[request.role].model_copy(
        update={
            "id": adapter._agent_id,
            "version": adapter._agent_version,
            "permissions": request.permissions,
            "timeout_seconds": request.timeout_seconds,
        }
    )
    artifact = _ScriptedDeliveryAdapter(definition, cwd).run(request).artifact
    assert isinstance(artifact, (QaReportArtifact, ReviewReportArtifact))
    command = ("git", "show", f"{request.source_revision}:hello.txt")
    observed = SubprocessCommandExecutor(
        cwd, request.permissions, execution_guard=adapter._execution_guard
    ).run(command, timeout_seconds=5)
    assert observed.returncode == 0 and observed.stdout == _DESIRED
    path = evidence_root / f"verification-{request.run_id}.json"
    path.write_text(observed.model_dump_json())
    evidence = Evidence(
        evidence_id=f"ev_{request.run_id.removeprefix('run_')}",
        type=EvidenceType.TEST if request.role is AgentRole.QA else EvidenceType.COMMAND,
        uri=path.as_uri(),
        description="Independent role inspected the exact committed candidate greeting.",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    if isinstance(artifact, QaReportArtifact):
        qa_content = artifact.content.model_copy(
            update={
                "criteria_results": tuple(
                    value.model_copy(update={"evidence_ids": (evidence.evidence_id,)})
                    for value in artifact.content.criteria_results
                ),
                "tests_run": (
                    QaTestRun(
                        command=" ".join(command),
                        status=QaTestStatus.PASS,
                        evidence_id=evidence.evidence_id,
                        duration_ms=observed.duration_ms,
                    ),
                ),
            }
        )
    else:
        return artifact.model_copy(
            update={
                "evidence": (evidence,),
                "content": artifact.content.model_copy(
                    update={"evidence": (evidence.evidence_id,)}
                ),
            }
        )
    return artifact.model_copy(update={"evidence": (evidence,), "content": qa_content})


@dataclass
class _InputCapacity:
    blocked: bool = True
