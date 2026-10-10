"""Offline provider inputs for the real native recovery composition."""

import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from ai_software_engineer.agents import AgentRequest, StructuredModelClient, StructuredModelResult
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentProducer,
    AgentRole,
    ArtifactIntegrity,
    ArtifactKind,
    ChangedFile,
    ChangeType,
    ImplementationAcceptanceMapping,
    ImplementationReportArtifact,
    ImplementationReportContent,
    TeamRole,
)
from ai_software_engineer.git import WorkspacePolicy
from tests.manager.test_production_backend import _ScriptedClientFactory, _ScriptedStructuredClient


def offline_failed_codex(tmp_path: Path) -> str:
    """Fail a real owned process without a provider or structured artifact."""
    executable = tmp_path / "offline-failed-codex"
    partial = "partially implemented\n"
    failure = "error: authentication failure in offline fixture\n"
    executable.write_text(
        f"#!{sys.executable}\n"
        "from pathlib import Path\n"
        "import sys\n"
        f"Path('hello.txt').write_text({partial!r})\n"
        f"sys.stderr.write({failure!r})\n"
        "raise SystemExit(1)\n"
    )
    executable.chmod(0o700)
    return str(executable)


def offline_coder_draft(
    definition: AgentDefinition, request: AgentRequest, root: Path
) -> ImplementationReportArtifact:
    """Leave only policy-bound source edits for the real platform candidate finalizer."""
    assert request.role is definition.role is AgentRole.CODER
    WorkspacePolicy(root, request.permissions).authorize_write("hello.txt")
    (root / "hello.txt").write_text("hello from the team\n")
    return ImplementationReportArtifact(
        artifact_id=f"art_impl_{request.run_id.removeprefix('run_')}",
        task_id=request.task_id,
        schema_version="v0.1",
        producer=AgentProducer(
            role=request.role,
            agent_id=definition.id,
            agent_version=definition.version,
            run_id=request.run_id,
        ),
        source_revision=request.source_revision,
        context_manifest_id=request.context_manifest_id,
        created_at=datetime.now(UTC),
        parent_artifact_ids=request.input_artifact_ids,
        evidence=(),
        supersedes=(request.expected_supersedes_by_kind or {}).get(
            ArtifactKind.IMPLEMENTATION_REPORT
        ),
        content=ImplementationReportContent(
            commit_sha=request.source_revision,
            changed_files=(
                ChangedFile(
                    path="hello.txt", change=ChangeType.MODIFIED, lines_added=1, lines_deleted=1
                ),
            ),
            acceptance_mapping=(
                ImplementationAcceptanceMapping(
                    criterion_id="ac_001_001", implementation="Updated the greeting file.", tests=()
                ),
            ),
            tests_run=(),
            known_risks=(),
        ),
        integrity=ArtifactIntegrity(sha256="0" * 64, validated=False),
    )


class _SourceInspectionClient(_ScriptedStructuredClient):
    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        result = super().complete(
            instructions=instructions,
            input_payload=input_payload,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            input_images=input_images,
        )
        if output_schema.get("title") != "TechnicalDesignDraft":
            return result
        # A text-only repository has no inferred test entrypoint. Freeze the
        # actual read-only candidate check in the approved Designer artifact.
        payload = dict(result.payload)
        mappings = payload["acceptance_mappings"]
        assert isinstance(mappings, list)
        payload["acceptance_mappings"] = [
            {
                **mapping,
                "test_levels": ["inspection"],
                "verification_inspection": {
                    "kind": "source",
                    "paths": ["hello.txt"],
                    "checklist": [
                        "Read the committed hello.txt and compare with the approved greeting."
                    ],
                },
            }
            for mapping in mappings
        ]
        return StructuredModelResult(payload=payload, duration_ms=result.duration_ms)


class OfflineRecoveryClients(_ScriptedClientFactory):
    def for_project(
        self, repository_root: Path, role: TeamRole = TeamRole.PRODUCT
    ) -> StructuredModelClient:
        del role
        assert repository_root.is_dir()
        return _SourceInspectionClient()
