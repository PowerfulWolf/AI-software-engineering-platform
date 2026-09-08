"""Codex CLI adapter tests through an injected process boundary and real Git."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentRequest,
    AgentRunStatus,
    CodexCliAgentAdapter,
    CodexInvocationResult,
)
from ai_software_engineer.agents.codex_cli import (
    SubprocessCodexCommandRunner,
    _completion_reserve_seconds,
)
from ai_software_engineer.domain import (
    ChangedFile,
    ChangeType,
    ImplementationReportArtifact,
)
from tests.agents.test_openai_compatible import StaticPromptBuilder, _coder_request
from tests.domain.factories import make_coder_progress_artifact, make_implementation_artifact


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


class _DirtySuccessRunner:
    """Model-success fixture for linked worktrees whose Git metadata is sandbox-external."""

    def __init__(
        self,
        request: AgentRequest,
        changed_path: str = "src/change.py",
        reported_path: str | None = None,
        provisional_revision: str | None = None,
    ) -> None:
        self.request = request
        self.changed_path = changed_path
        self.reported_path = reported_path or changed_path
        self.provisional_revision = provisional_revision or request.source_revision

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
    ) -> CodexInvocationResult:
        del environment, stdin, timeout_seconds
        changed_path = self.changed_path
        target = cwd / changed_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("VALUE = 1\n", encoding="utf-8")
        template = make_implementation_artifact()
        content = template.content.model_copy(
            update={
                "commit_sha": self.provisional_revision,
                "changed_files": (
                    ChangedFile(
                        path=self.reported_path,
                        change=ChangeType.ADDED,
                        lines_added=1,
                        lines_deleted=0,
                    ),
                ),
            }
        )
        draft = template.model_copy(
            update={
                "task_id": self.request.task_id,
                "source_revision": self.provisional_revision,
                "context_manifest_id": self.request.context_manifest_id,
                "parent_artifact_ids": self.request.input_artifact_ids,
                "producer": template.producer.model_copy(update={"run_id": self.request.run_id}),
                "content": content,
            }
        )
        output_path = Path(argv[argv.index("--output-last-message") + 1])
        output_path.write_text(json.dumps({"artifact": draft.to_wire()}), encoding="utf-8")
        return CodexInvocationResult(returncode=0)


class _DirtyFailureRunner:
    def __init__(self, invocation: CodexInvocationResult | None = None) -> None:
        self.invocation = invocation or CodexInvocationResult(
            returncode=1, stderr="usage limit reached"
        )

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
        return self.invocation


class _ProgressRunner:
    def __init__(self, request: AgentRequest) -> None:
        self.request = request

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
    ) -> CodexInvocationResult:
        del environment, stdin, timeout_seconds
        target = cwd / "src" / "partial.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("PARTIAL = True\n", encoding="utf-8")
        template = make_coder_progress_artifact()
        progress = template.model_copy(
            update={
                "task_id": self.request.task_id,
                "source_revision": self.request.source_revision,
                "context_manifest_id": self.request.context_manifest_id,
                "parent_artifact_ids": self.request.input_artifact_ids,
                "producer": template.producer.model_copy(update={"run_id": self.request.run_id}),
                "content": template.content.model_copy(
                    update={
                        "changed_files": (
                            ChangedFile(
                                path="src/partial.py",
                                change=ChangeType.ADDED,
                                lines_added=1,
                                lines_deleted=0,
                            ),
                        )
                    }
                ),
            }
        )
        output_path = Path(argv[argv.index("--output-last-message") + 1])
        output_path.write_text(json.dumps({"artifact": progress.to_wire()}), encoding="utf-8")
        return CodexInvocationResult(returncode=0)


def test_coder_creates_verified_candidate_in_isolated_worktree(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    request = _coder_request().model_copy(
        update={"source_revision": base, "timeout_seconds": 1_800}
    )
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
    assert "hard execution limit is 1800 seconds" in prompt
    assert "Reserve the final 300 seconds" in prompt
    assert "focused required tests before broader optional suites" in prompt
    assert "Do not run git add or git commit" in prompt
    assert "platform will policy-check and bind the candidate" in prompt
    assert "JSON report and a complete intended diff" in prompt


def test_platform_finalizes_coder_draft_when_git_metadata_is_sandbox_external(
    tmp_path: Path,
) -> None:
    root, base = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": base})
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="gpt-5.5",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=_DirtySuccessRunner(request),
    )

    result = adapter.run(request)

    assert result.status is AgentRunStatus.SUCCEEDED
    assert result.artifact is not None
    assert isinstance(result.artifact, ImplementationReportArtifact)
    candidate = _git(root, "rev-parse", "HEAD")
    assert candidate != base
    assert result.artifact.source_revision == candidate
    assert result.artifact.content.commit_sha == candidate
    assert _git(root, "status", "--porcelain") == ""


def test_coder_progress_preserves_authorized_draft_for_the_next_run(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    first_request = _coder_request().model_copy(update={"source_revision": base})
    first = CodexCliAgentAdapter(
        workspace_root=root,
        model="gpt-5.5",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=_ProgressRunner(first_request),
    ).run(first_request)

    assert first.status is AgentRunStatus.SUCCEEDED
    assert first.artifact is not None
    assert first.artifact.kind.value == "coder-progress"
    assert _git(root, "rev-parse", "HEAD") == base
    assert _git(root, "status", "--porcelain") == "?? src/"

    second_request = AgentRequest.model_validate(
        {
            **first_request.to_wire(),
            "run_id": "run_real_002",
            "attempt": 2,
            "input_artifact_ids": [first.artifact.artifact_id],
            "continuation_checkpoint_id": first.artifact.artifact_id,
            "continuation_changed_paths": ["src/partial.py"],
        }
    )
    second = CodexCliAgentAdapter(
        workspace_root=root,
        model="gpt-5.5",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=_DirtySuccessRunner(second_request, changed_path="src/partial.py"),
    ).run(second_request)

    assert second.status is AgentRunStatus.SUCCEEDED
    assert second.artifact is not None
    assert second.artifact.kind.value == "implementation-report"
    assert _git(root, "rev-parse", "HEAD") == second.artifact.source_revision
    assert _git(root, "status", "--porcelain") == ""


def test_platform_finalizes_draft_in_real_linked_worktree(tmp_path: Path) -> None:
    repository, base = _repository(tmp_path)
    worktree = tmp_path / "roles" / "coder"
    worktree.parent.mkdir()
    _git(repository, "worktree", "add", "-q", "-b", "ai/candidate", str(worktree), base)
    request = _coder_request().model_copy(update={"source_revision": base})
    adapter = CodexCliAgentAdapter(
        workspace_root=worktree,
        model="gpt-5.5",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=_DirtySuccessRunner(request),
    )

    result = adapter.run(request)

    assert result.status is AgentRunStatus.SUCCEEDED
    assert result.artifact is not None
    candidate = _git(worktree, "rev-parse", "HEAD")
    assert candidate != base
    assert _git(repository, "rev-parse", "HEAD") == base
    assert _git(worktree, "status", "--porcelain") == ""
    assert result.artifact.source_revision == candidate


def test_platform_does_not_finalize_unauthorized_coder_draft(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": base})
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="gpt-5.5",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=_DirtySuccessRunner(request, changed_path="docs/unauthorized.md"),
    )

    result = adapter.run(request)

    assert result.status is AgentRunStatus.FAILED
    assert result.error is not None
    assert result.error.code is AgentErrorCode.POLICY_VIOLATION
    assert _git(root, "rev-parse", "HEAD") == base
    assert _git(root, "status", "--porcelain") == "?? docs/"


def test_platform_does_not_finalize_coder_draft_with_mismatched_inventory(
    tmp_path: Path,
) -> None:
    root, base = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": base})
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="gpt-5.5",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=_DirtySuccessRunner(request, reported_path="src/other.py"),
    )

    result = adapter.run(request)

    assert result.status is AgentRunStatus.FAILED
    assert result.error is not None
    assert result.error.code is AgentErrorCode.POLICY_VIOLATION
    assert _git(root, "rev-parse", "HEAD") == base
    assert _git(root, "status", "--porcelain") == "?? src/"


def test_platform_does_not_finalize_coder_draft_with_unbound_revision(
    tmp_path: Path,
) -> None:
    root, base = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": base})
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="gpt-5.5",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=_DirtySuccessRunner(request, provisional_revision="f" * 40),
    )

    result = adapter.run(request)

    assert result.status is AgentRunStatus.FAILED
    assert result.error is not None
    assert result.error.code is AgentErrorCode.INVALID_OUTPUT
    assert _git(root, "rev-parse", "HEAD") == base
    assert _git(root, "status", "--porcelain") == "?? src/"


@pytest.mark.parametrize(
    ("timeout_seconds", "expected_reserve"),
    [(1, 0), (2, 1), (60, 12), (1_200, 240), (1_800, 300), (3_600, 300)],
)
def test_completion_reserve_is_bounded(timeout_seconds: int, expected_reserve: int) -> None:
    assert _completion_reserve_seconds(timeout_seconds) == expected_reserve
    assert expected_reserve < timeout_seconds


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
    assert "cause=QUOTA_EXHAUSTED" in result.error.message
    assert "returncode=1" in result.error.message


@pytest.mark.parametrize(
    ("stderr", "timed_out", "cause"),
    [
        ("usage limit reached", False, "QUOTA_EXHAUSTED"),
        ("rate limit exceeded", False, "RATE_LIMITED"),
        ("authentication failed", False, "AUTHENTICATION_ERROR"),
        ("unrecognized provider exit", False, "UNKNOWN_EXIT"),
        ("partial output before termination", True, "TIMEOUT"),
    ],
)
def test_dirty_failure_preserves_safe_diagnostics_without_enabling_retry(
    tmp_path: Path, stderr: str, timed_out: bool, cause: str
) -> None:
    root, base = _repository(tmp_path)
    request = _coder_request().model_copy(update={"source_revision": base})
    private = "private-task-prose-and-secret-value"
    invocation = CodexInvocationResult(
        returncode=-1 if timed_out else 1,
        timed_out=timed_out,
        stdout=private,
        stderr=stderr + private,
    )
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=_DirtyFailureRunner(invocation),
    )
    result = adapter.run(request)
    assert result.error is not None
    assert result.status is AgentRunStatus.FAILED
    assert result.error.code is AgentErrorCode.POLICY_VIOLATION
    assert result.error.transient is False
    assert result.artifact is None
    assert f"cause={cause}" in result.error.message
    assert hashlib.sha256(private.encode()).hexdigest() in result.error.message
    assert private not in result.model_dump_json()
    assert len(result.error.message) < 400
    assert _git(root, "rev-parse", "HEAD") == base
    assert (root / "src" / "partial.py").read_text() == "partial = True\n"
    assert adapter.run(request) == result


def test_subprocess_capture_retains_trailing_failure_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="start" + "x" * 1_000_010 + "usage limit reached",
            stderr="private stderr",
        )

    monkeypatch.setattr(subprocess, "run", run)
    invocation = SubprocessCodexCommandRunner().run(
        ("unused",),
        cwd=tmp_path,
        environment={},
        stdin="",
        timeout_seconds=1,
    )
    assert len(invocation.stdout) == 1_000_000
    assert invocation.stdout.startswith("start")
    assert invocation.stdout.endswith("usage limit reached")


def test_subprocess_timeout_retains_bounded_partial_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            cmd="unused", timeout=1, output=b"partial stdout", stderr=b"partial stderr\xff"
        )

    monkeypatch.setattr(subprocess, "run", run)
    invocation = SubprocessCodexCommandRunner().run(
        ("unused",),
        cwd=tmp_path,
        environment={},
        stdin="",
        timeout_seconds=1,
    )
    assert invocation.timed_out
    assert invocation.returncode == -1
    assert invocation.stdout == "partial stdout"
    assert invocation.stderr == "partial stderr\ufffd"
