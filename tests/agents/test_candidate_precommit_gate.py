"""A scheduled recovery source gate runs before either provider can commit a candidate."""

from pathlib import Path

import pytest

from ai_software_engineer.agents import CodexCliAgentAdapter
from ai_software_engineer.agents import codex_cli as codex_cli_module
from ai_software_engineer.agents.responses import _finalize_coder_candidate
from ai_software_engineer.git import (
    CandidateCommitRequest,
    CandidateCommitResult,
    WorkspacePolicyError,
)
from tests.agents.test_openai_compatible import _coder_request
from tests.domain.factories import make_implementation_artifact


class _CandidateSkill:
    def __init__(self, path: str) -> None:
        self.path = path
        self.finalized = False

    def changed_paths(self) -> tuple[str, ...]:
        return (self.path,)

    def finalize(self, _request: CandidateCommitRequest) -> CandidateCommitResult:
        self.finalized = True
        raise AssertionError("candidate commit must not run before source coverage")


def test_both_native_routes_gate_before_candidate_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _coder_request()
    template = make_implementation_artifact()
    artifact = template.model_copy(
        update={
            "task_id": request.task_id,
            "source_revision": request.source_revision,
            "context_manifest_id": request.context_manifest_id,
            "producer": template.producer.model_copy(update={"run_id": request.run_id}),
        }
    )
    path = artifact.content.changed_files[0].path
    calls: list[str] = []

    def reject(current: object) -> None:
        assert current == request
        calls.append("checked")
        raise WorkspacePolicyError("scheduled recovery has an uncovered source")

    skill = _CandidateSkill(path)
    with pytest.raises(WorkspacePolicyError, match="uncovered source"):
        _finalize_coder_candidate(request, request.source_revision, artifact, skill, reject)
    assert not skill.finalized

    monkeypatch.setattr(codex_cli_module, "_git", lambda *_args: request.source_revision)
    skill = _CandidateSkill(path)
    adapter = CodexCliAgentAdapter(
        workspace_root=tmp_path,
        model="test-model",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        candidate_commit_skill=skill,
        candidate_precommit_validator=reject,
    )
    with pytest.raises(WorkspacePolicyError, match="uncovered source"):
        adapter._finalize_coder_candidate(request, request.source_revision, artifact)
    assert calls == ["checked", "checked"]
    assert not skill.finalized
