"""A consumed trusted rescue admission can request a fresh existing-candidate report."""

import json
from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentErrorCode, AgentRequest, AgentRunStatus, HttpResponse
from ai_software_engineer.agents.codex_cli import CodexCliAgentAdapter
from ai_software_engineer.agents.responses import ResponsesAgentAdapter
from ai_software_engineer.domain.artifact import ChangedFile, ImplementationReportArtifact
from ai_software_engineer.domain.enums import ChangeType
from tests.agents.test_codex_cli import _ArtifactOutputRunner
from tests.agents.test_openai_compatible import RecordingTransport, StaticPromptBuilder
from tests.agents.test_responses import _git, _repository, _request
from tests.domain.factories import make_implementation_artifact


@pytest.mark.parametrize("transport", ["codex", "responses"])
@pytest.mark.parametrize("trusted", [False, True])
def test_report_existing_candidate_requires_trusted_rescue_comparison(
    tmp_path: Path, transport: str, trusted: bool
) -> None:
    root, base = _repository(tmp_path)
    (root / "src/change.py").write_text("VALUE = 1\n")
    _git(root, "add", "src/change.py")
    _git(root, "commit", "-qm", "retained original candidate")
    candidate = _git(root, "rev-parse", "HEAD")
    request, definition = _request(candidate)
    request = request.model_copy(
        update={
            "execution_base_ref": base,
            "execution_baseline_sha256": "1" * 64,
        }
    )
    template = make_implementation_artifact()
    report = template.model_copy(
        update={
            "source_revision": candidate,
            "context_manifest_id": request.context_manifest_id,
            "parent_artifact_ids": request.input_artifact_ids,
            "producer": template.producer.model_copy(update={"run_id": request.run_id}),
            "content": template.content.model_copy(
                update={
                    "commit_sha": candidate,
                    "changed_files": (
                        ChangedFile(
                            path="src/change.py",
                            change=ChangeType.ADDED,
                            lines_added=1,
                            lines_deleted=0,
                        ),
                    ),
                }
            ),
        }
    )

    class ExactAdmission:
        def authorize(self, value: AgentRequest, workspace_root: Path) -> None:
            assert value == request and workspace_root == root

        def retained_candidate_report_base(
            self,
            value: AgentRequest,
            workspace_root: Path,
            artifact: ImplementationReportArtifact,
        ) -> str:
            assert value == request and workspace_root == root
            assert artifact.source_revision == candidate
            return base

    admission = ExactAdmission() if trusted else None
    if transport == "codex":
        result = CodexCliAgentAdapter(
            workspace_root=root,
            model="fixture",
            agent_id="agent_coder_001",
            agent_version="v0.1",
            prompt_builder=StaticPromptBuilder(),
            runner=_ArtifactOutputRunner(report.to_wire()),
            initial_workspace_admission=admission,
        ).run(request)
    else:
        result = ResponsesAgentAdapter(
            workspace_root=root,
            model="fixture",
            endpoint="https://example.invalid/v1",
            api_key="test-key",
            agent=definition,
            prompt_builder=StaticPromptBuilder(),
            transport=RecordingTransport(
                response=HttpResponse(
                    status_code=200,
                    body=json.dumps(
                        {
                            "output_text": json.dumps({"artifact": report.to_wire()}),
                        }
                    ).encode(),
                )
            ),
            initial_workspace_admission=admission,
        ).run(request)
    if trusted:
        assert result.status is AgentRunStatus.SUCCEEDED
        assert result.artifact is not None and result.artifact.source_revision == candidate
    else:
        assert result.status is AgentRunStatus.FAILED and result.artifact is None
        assert result.error is not None and result.error.code is AgentErrorCode.INVALID_OUTPUT
    assert _git(root, "rev-parse", "HEAD") == candidate
    assert _git(root, "status", "--porcelain") == ""
