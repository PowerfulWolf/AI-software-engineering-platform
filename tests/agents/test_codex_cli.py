"""Codex CLI adapter tests through an injected process boundary and real Git."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentRequest,
    AgentRunStatus,
    CodexCliAgentAdapter,
    CodexInvocationResult,
)
from ai_software_engineer.domain import ChangedFile, ChangeType
from tests.agents.test_openai_compatible import StaticPromptBuilder, _coder_request
from tests.domain.factories import make_implementation_artifact


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "target"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "agent@example.invalid")
    _git(root, "config", "user.name", "Agent Test")
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "initial")
    return root, _git(root, "rev-parse", "HEAD")


class _CoderRunner:
    def __init__(self, request: AgentRequest, changed_path: str = "src/change.py") -> None:
        self.request = request
        self.changed_path = changed_path
        self.calls: list[tuple[tuple[str, ...], Mapping[str, str], str]] = []

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
    ) -> CodexInvocationResult:
        del timeout_seconds
        self.calls.append((argv, environment, stdin))
        target = cwd / self.changed_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("VALUE = 1\n", encoding="utf-8")
        _git(cwd, "add", self.changed_path)
        _git(cwd, "commit", "-qm", "candidate")
        candidate = _git(cwd, "rev-parse", "HEAD")
        template = make_implementation_artifact()
        content = template.content.model_copy(
            update={
                "commit_sha": candidate,
                "changed_files": (
                    ChangedFile(
                        path=self.changed_path,
                        change=ChangeType.ADDED,
                        lines_added=1,
                        lines_deleted=0,
                    ),
                ),
            }
        )
        artifact = template.model_copy(
            update={
                "task_id": self.request.task_id,
                "source_revision": candidate,
                "context_manifest_id": self.request.context_manifest_id,
                "parent_artifact_ids": self.request.input_artifact_ids,
                "producer": template.producer.model_copy(update={"run_id": self.request.run_id}),
                "content": content,
            }
        )
        output_path = Path(argv[argv.index("--output-last-message") + 1])
        output_path.write_text(json.dumps(artifact.to_wire()), encoding="utf-8")
        return CodexInvocationResult(returncode=0)


class _FailureRunner:
    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
    ) -> CodexInvocationResult:
        del argv, cwd, environment, stdin, timeout_seconds
        return CodexInvocationResult(returncode=1, stderr="usage limit reached")


class _DirtyFailureRunner:
    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
    ) -> CodexInvocationResult:
        del argv, environment, stdin, timeout_seconds
        target = cwd / "src" / "partial.py"
        target.parent.mkdir()
        target.write_text("partial = True\n", encoding="utf-8")
        return CodexInvocationResult(returncode=1, stderr="usage limit reached")


def test_coder_creates_verified_candidate_in_isolated_worktree(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": base})
    runner = _CoderRunner(request)
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="gpt-5.5",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        environment={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "UV_CACHE_DIR": str(tmp_path / "uv-cache"),
            "QWEN_API_KEY": "must-not-reach-codex",
        },
        runner=runner,
    )

    result = adapter.run(request)

    assert result.status is AgentRunStatus.SUCCEEDED
    assert result.artifact is not None
    assert result.artifact.source_revision == _git(root, "rev-parse", "HEAD")
    assert _git(root, "status", "--porcelain") == ""
    argv, environment, prompt = runner.calls[0]
    assert "gpt-5.5" in argv
    assert "workspace-write" in argv
    assert "--approve-for-me" not in argv
    assert "QWEN_API_KEY" not in environment
    assert environment["UV_CACHE_DIR"] == str(tmp_path / "uv-cache")
    assert "Never merge, push, deploy" in prompt


def test_coder_change_outside_write_policy_is_rejected(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": base})
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="gpt-5.5",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=_CoderRunner(request, "docs/unauthorized.md"),
    )

    result = adapter.run(request)

    assert result.status is AgentRunStatus.FAILED
    assert result.error is not None
    assert result.error.code is AgentErrorCode.POLICY_VIOLATION


def test_cli_usage_limit_is_typed_for_provider_fallback(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": base})
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="gpt-5.5",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=_FailureRunner(),
    )

    result = adapter.run(request)

    assert result.status is AgentRunStatus.FAILED
    assert result.error is not None
    assert result.error.code is AgentErrorCode.QUOTA_EXHAUSTED
    assert result.error.transient is True


def test_cli_failure_with_partial_changes_cannot_fallback(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": base})
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="gpt-5.5",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=_DirtyFailureRunner(),
    )

    result = adapter.run(request)

    assert result.status is AgentRunStatus.FAILED
    assert result.error is not None
    assert result.error.code is AgentErrorCode.POLICY_VIOLATION
    assert result.error.transient is False
