"""Trusted retained ignored source survives progress and both provider candidate paths."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentAdapter,
    AgentRequest,
    AgentRunStatus,
    CodexCliAgentAdapter,
    CodexInvocationResult,
    HttpResponse,
    ResponsesAgentAdapter,
)
from ai_software_engineer.domain import Artifact, ChangedFile, ChangeType
from ai_software_engineer.git import GitCandidateCommitSkill
from tests.agents.test_openai_compatible import StaticPromptBuilder
from tests.agents.test_responses import _request
from tests.domain.factories import make_coder_progress_artifact, make_implementation_artifact
from tests.git.test_candidate_commit import RETAINED_PATH, _git, _ignored_repository


def _artifact(request: AgentRequest, *, progress: bool, report: bool = True) -> Artifact:
    template = make_coder_progress_artifact() if progress else make_implementation_artifact()
    content_changes: dict[str, object] = {
        "changed_files": (
            ChangedFile(
                path=RETAINED_PATH if report else "src/app.py",
                change=ChangeType.ADDED,
                lines_added=1,
                lines_deleted=0,
            ),
        ),
    }
    content_changes.update(
        {"checkpoint_sequence": request.attempt}
        if progress
        else {"commit_sha": request.source_revision}
    )
    return template.model_copy(
        update={
            "task_id": request.task_id,
            "source_revision": request.source_revision,
            "context_manifest_id": request.context_manifest_id,
            "parent_artifact_ids": request.input_artifact_ids,
            "producer": template.producer.model_copy(update={"run_id": request.run_id}),
            "content": template.content.model_copy(update=content_changes),
        }
    )


class _ExactAdmission:
    def __init__(self, root: Path, source: str) -> None:
        self.root, self.source = root, source

    def authorize(self, request: AgentRequest, workspace_root: Path) -> None:
        assert request.source_revision == self.source
        assert workspace_root == self.root
        assert GitCandidateCommitSkill(
            workspace_root, retained_source_paths=(RETAINED_PATH,)
        ).changed_paths() == (RETAINED_PATH,)


class _NativeOutput:
    def __init__(self, artifact: Artifact) -> None:
        self.artifact = artifact

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
    ) -> CodexInvocationResult:
        del cwd, environment, stdin, timeout_seconds
        Path(argv[argv.index("--output-last-message") + 1]).write_text(
            json.dumps({"artifact": self.artifact.to_wire()}), encoding="utf-8"
        )
        return CodexInvocationResult(returncode=0)


class _ResponsesOutput:
    def __init__(self, artifact: Artifact) -> None:
        self.artifact = artifact

    def post(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> HttpResponse:
        del url, headers, body, timeout_seconds
        return HttpResponse(
            status_code=200,
            body=json.dumps(
                {"output_text": json.dumps({"artifact": self.artifact.to_wire()})}
            ).encode(),
        )


def _adapter(
    root: Path, request: AgentRequest, provider: str, artifact: Artifact, *, seed: bool
) -> AgentAdapter:
    _, definition = _request(request.source_revision)
    skill = GitCandidateCommitSkill(root, retained_source_paths=(RETAINED_PATH,))
    admission = _ExactAdmission(root, request.source_revision) if seed else None
    if provider == "native":
        return CodexCliAgentAdapter(
            workspace_root=root,
            model="fixture",
            prompt_builder=StaticPromptBuilder(),
            candidate_commit_skill=skill,
            initial_workspace_admission=admission,
            agent_id=definition.id,
            agent_version=definition.version,
            runner=_NativeOutput(artifact),
        )
    return ResponsesAgentAdapter(
        workspace_root=root,
        model="fixture",
        prompt_builder=StaticPromptBuilder(),
        candidate_commit_skill=skill,
        initial_workspace_admission=admission,
        endpoint="https://example.invalid/responses",
        api_key="fixture-key",
        agent=definition,
        transport=_ResponsesOutput(artifact),
    )


@pytest.mark.parametrize("provider", ["native", "responses"])
def test_retained_source_progress_then_candidate_survives_fresh_provider_adapter(
    tmp_path: Path, provider: str
) -> None:
    root, source = _ignored_repository(tmp_path)
    request, _ = _request(source)
    first = _adapter(root, request, provider, _artifact(request, progress=True), seed=True).run(
        request
    )
    assert first.status is AgentRunStatus.SUCCEEDED, first.error
    assert first.artifact is not None
    assert first.artifact.kind.value == "coder-progress"
    assert _git(root, "rev-parse", "HEAD") == source
    assert _git(root, "ls-files", "--", RETAINED_PATH) == ""

    continuation = AgentRequest.model_validate(
        {
            **request.to_wire(),
            "run_id": "run_retained_continuation",
            "attempt": 2,
            "input_artifact_ids": [first.artifact.artifact_id],
            "continuation_checkpoint_id": first.artifact.artifact_id,
            "continuation_changed_paths": [RETAINED_PATH],
        }
    )
    result = _adapter(
        root, continuation, provider, _artifact(continuation, progress=False), seed=False
    ).run(continuation)

    assert result.status is AgentRunStatus.SUCCEEDED, result.error
    assert result.artifact is not None
    assert result.artifact.kind.value == "implementation-report"
    assert result.artifact.source_revision != source
    qa = tmp_path / "qa-checkout"
    _git(root, "worktree", "add", "--detach", str(qa), result.artifact.source_revision)
    assert (qa / RETAINED_PATH).read_text(encoding="utf-8") == "ACCEPTED = True\n"
    assert _git(qa, "status", "--porcelain") == ""


@pytest.mark.parametrize("provider", ["native", "responses"])
@pytest.mark.parametrize("progress", [False, True])
def test_retained_source_omitted_from_report_is_rejected(
    tmp_path: Path, provider: str, progress: bool
) -> None:
    root, source = _ignored_repository(tmp_path)
    request, _ = _request(source)

    result = _adapter(
        root, request, provider, _artifact(request, progress=progress, report=False), seed=True
    ).run(request)

    assert result.status is AgentRunStatus.FAILED
    assert _git(root, "rev-parse", "HEAD") == source
    assert _git(root, "diff", "--cached") == ""
    assert (root / RETAINED_PATH).read_text(encoding="utf-8") == "ACCEPTED = True\n"
