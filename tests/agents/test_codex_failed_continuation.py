"""A failed route compares its own mutations with the exact admitted draft."""

import os
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, cast

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    AgentRequest,
    AgentRunStatus,
    CodexCliAgentAdapter,
    CodexInvocationResult,
    FallbackAgentAdapter,
    FileModelRouteAttemptStore,
    ProviderAgentRoute,
    RouteAttemptOutcome,
)
from ai_software_engineer.agents import codex_cli as codex_cli_module
from ai_software_engineer.agents.continuation import (
    ContinuationExecutionUncertain,
    InterruptionObservation,
)
from ai_software_engineer.agents.workspace_admission import FirstCoderRunWorkspaceAdmission
from ai_software_engineer.git.mutation import (
    MutationInventoryRejected,
    WorkspaceMutationInventory,
    capture_mutation_inventory,
)
from tests.agents.test_codex_cli import _git, _ProgressRunner, _repository
from tests.agents.test_initial_admission_scope import progress
from tests.agents.test_openai_compatible import StaticPromptBuilder, _coder_request


class FailedRunner:
    def __init__(
        self,
        *,
        result: CodexInvocationResult | None = None,
        mutate: Callable[[Path], None] | None = None,
    ) -> None:
        self.result = result or CodexInvocationResult(returncode=1, stderr="usage limit reached")
        self.mutate = mutate
        self.calls = 0

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
        self.calls += 1
        if self.mutate is not None:
            self.mutate(cwd)
        return self.result


class InvocationControl:
    def __init__(self, observation: str = InterruptionObservation.UNCHANGED) -> None:
        self.observation = observation
        self.started_calls = 0

    def prepare(self, request: AgentRequest, root: Path) -> None:
        return None

    def started(self, request: AgentRequest, root: Path) -> WorkspaceMutationInventory:
        self.started_calls += 1
        return capture_mutation_inventory(root)

    def finished(
        self, request: AgentRequest, root: Path, *, before: WorkspaceMutationInventory
    ) -> None:
        raise AssertionError("a failed invocation cannot finish")

    def interrupted(
        self,
        request: AgentRequest,
        root: Path,
        *,
        before: WorkspaceMutationInventory,
        cause: str,
        original_error_code: AgentErrorCode,
        process_stop: object,
        output_present: bool,
    ) -> InterruptionObservation:
        if self.observation == "unknown_stop":
            raise ContinuationExecutionUncertain("fixture unknown actual stop")
        return InterruptionObservation(self.observation)


@pytest.mark.parametrize(
    ("invocation", "code", "transient", "status"),
    [
        (
            CodexInvocationResult(returncode=1, stderr="usage limit reached"),
            AgentErrorCode.QUOTA_EXHAUSTED,
            True,
            AgentRunStatus.FAILED,
        ),
        (
            CodexInvocationResult(returncode=1, stderr="error: 429 too many requests"),
            AgentErrorCode.RATE_LIMITED,
            True,
            AgentRunStatus.FAILED,
        ),
        (
            CodexInvocationResult(returncode=1, stderr="error: unauthorized"),
            AgentErrorCode.AUTHENTICATION_ERROR,
            False,
            AgentRunStatus.FAILED,
        ),
        (
            CodexInvocationResult(returncode=-15, stderr="usage limit reached"),
            AgentErrorCode.PROVIDER_ERROR,
            False,
            AgentRunStatus.FAILED,
        ),
        (
            CodexInvocationResult(returncode=-15, timed_out=True),
            AgentErrorCode.TIMEOUT,
            True,
            AgentRunStatus.TIMED_OUT,
        ),
    ],
)
def test_unchanged_accepted_progress_preserves_provider_failure(
    tmp_path: Path,
    invocation: CodexInvocationResult,
    code: AgentErrorCode,
    transient: bool,
    status: AgentRunStatus,
) -> None:
    root, request, admission = progress(tmp_path)
    before = capture_mutation_inventory(root)
    runner = FailedRunner(result=invocation)
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        prompt_builder=StaticPromptBuilder(),
        runner=runner,
        initial_workspace_admission=FirstCoderRunWorkspaceAdmission(admission),
    )
    result = adapter.run(request)
    assert result.error is not None
    assert result.error.code is code
    assert result.error.transient is transient
    assert result.status is status
    assert result.artifact is None
    assert capture_mutation_inventory(root) == before
    assert admission.attempts == [1]
    assert adapter.run(request) == result
    assert runner.calls == 1


def mutate_workspace(root: Path, mutation: str) -> None:
    draft = root / "src/partial.py"
    if mutation == "body":
        draft.write_text("new_write = True\n")
    elif mutation == "mode":
        draft.chmod(0o755)
    elif mutation == "delete":
        draft.unlink()
    elif mutation == "link":
        draft.unlink()
        draft.symlink_to("../README.md")
    elif mutation == "ignored":
        (root / ".pytest_cache").mkdir()
        (root / ".pytest_cache/route-write").write_text("new\n")
    elif mutation == "head":
        _git(root, "commit", "--allow-empty", "-qm", "unexpected head mutation")
    elif mutation == "stage":
        _git(root, "add", "src/partial.py")
    elif mutation == "intent_to_add":
        _git(root, "add", "-N", "src/partial.py")
    elif mutation == "assume_unchanged":
        _git(root, "update-index", "--assume-unchanged", "README.md")
    elif mutation == "skip_worktree":
        _git(root, "update-index", "--skip-worktree", "README.md")
    elif mutation == "index_blob":
        blob = _git(root, "hash-object", "-w", "src/partial.py")
        _git(root, "update-index", "--cacheinfo", f"100644,{blob},README.md")
    elif mutation == "index_mode":
        _git(root, "update-index", "--chmod=+x", "README.md")
    elif mutation == "index_conflict_stage":
        blob = _git(root, "rev-parse", "HEAD:README.md")
        subprocess.run(
            ("git", "update-index", "--index-info"),
            cwd=root,
            input=f"0 {'0' * 40}\tREADME.md\n100644 {blob} 2\tREADME.md\n",
            text=True,
            check=True,
            capture_output=True,
        )
    else:
        raise AssertionError(f"unknown fixture mutation: {mutation}")


@pytest.mark.parametrize("timed_out", [False, True])
@pytest.mark.parametrize(
    "mutation",
    [
        "body",
        "mode",
        "delete",
        "link",
        "ignored",
        "head",
        "stage",
        "intent_to_add",
        "assume_unchanged",
        "skip_worktree",
        "index_blob",
        "index_mode",
        "index_conflict_stage",
    ],
)
def test_new_route_mutations_remain_nontransient(
    tmp_path: Path, mutation: str, timed_out: bool
) -> None:
    root, request, admission = progress(tmp_path)
    (root / ".git/info/exclude").write_text(".pytest_cache/\n")
    before = capture_mutation_inventory(root)
    status_before = _git(root, "status", "--porcelain")
    runner = FailedRunner(
        result=CodexInvocationResult(
            returncode=1, stderr="usage limit reached", timed_out=timed_out
        ),
        mutate=lambda cwd: mutate_workspace(cwd, mutation),
    )
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        runner=runner,
        prompt_builder=StaticPromptBuilder(),
        initial_workspace_admission=FirstCoderRunWorkspaceAdmission(admission),
    )
    result = adapter.run(request)
    assert result.error is not None
    assert result.error.code is AgentErrorCode.POLICY_VIOLATION
    assert result.error.transient is False
    assert result.status is AgentRunStatus.FAILED and result.artifact is None
    assert "cause=" in result.error.message
    if mutation in {"body", "mode", "ignored", "head", "assume_unchanged", "skip_worktree"}:
        assert _git(root, "status", "--porcelain") == status_before
    if mutation in {
        "stage",
        "intent_to_add",
        "assume_unchanged",
        "skip_worktree",
        "index_blob",
        "index_mode",
        "index_conflict_stage",
        "head",
    }:
        assert capture_mutation_inventory(root) == before
    assert adapter.run(request) == result and runner.calls == 1


@pytest.mark.parametrize("mutation", ["ignored", "assume_unchanged", "skip_worktree"])
def test_git_clean_status_cannot_hide_new_mutations(tmp_path: Path, mutation: str) -> None:
    root, base = _repository(tmp_path)
    (root / ".git/info/exclude").write_text(".pytest_cache/\n")
    request = _coder_request().model_copy(update={"source_revision": base})
    runner = FailedRunner(mutate=lambda cwd: mutate_workspace(cwd, mutation))
    result = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        runner=runner,
        prompt_builder=StaticPromptBuilder(),
    ).run(request)
    assert _git(root, "status", "--porcelain") == ""
    assert result.error is not None and result.error.code is AgentErrorCode.POLICY_VIOLATION
    assert not result.error.transient and runner.calls == 1


@pytest.mark.parametrize("refresh", ["stat_cache", "split_index"])
def test_index_storage_refresh_does_not_change_semantics(tmp_path: Path, refresh: str) -> None:
    root, request, admission = progress(tmp_path)

    def refresh_index(cwd: Path) -> None:
        if refresh == "stat_cache":
            readme = cwd / "README.md"
            os.utime(readme, (1_000_000_000, 1_000_000_000))
            _git(cwd, "status", "--porcelain")
        else:
            _git(cwd, "update-index", "--split-index")

    runner = FailedRunner(mutate=refresh_index)
    result = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        runner=runner,
        prompt_builder=StaticPromptBuilder(),
        initial_workspace_admission=FirstCoderRunWorkspaceAdmission(admission),
    ).run(request)
    assert result.error is not None and result.error.code is AgentErrorCode.QUOTA_EXHAUSTED
    assert result.error.transient and runner.calls == 1


def test_linked_worktree_accepted_progress_is_the_failure_baseline(tmp_path: Path) -> None:
    repository, base = _repository(tmp_path)
    root = tmp_path / "coder-linked"
    _git(repository, "worktree", "add", "--detach", str(root), base)
    first = _coder_request().model_copy(update={"source_revision": base})
    progress_result = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        runner=_ProgressRunner(first),
        prompt_builder=StaticPromptBuilder(),
    ).run(first)
    assert progress_result.artifact is not None
    request = AgentRequest.model_validate(
        {
            **first.to_wire(),
            "run_id": "run_linked_continuation",
            "attempt": 2,
            "input_artifact_ids": [progress_result.artifact.artifact_id],
            "continuation_checkpoint_id": progress_result.artifact.artifact_id,
            "continuation_changed_paths": ["src/partial.py"],
        }
    )
    before = capture_mutation_inventory(root)
    runner = FailedRunner()
    result = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        runner=runner,
        prompt_builder=StaticPromptBuilder(),
    ).run(request)
    assert result.error is not None and result.error.code is AgentErrorCode.QUOTA_EXHAUSTED
    assert result.error.transient and runner.calls == 1
    assert capture_mutation_inventory(root) == before


def test_exact_initial_dirty_seed_preserves_unchanged_failure(tmp_path: Path) -> None:
    root, base = _repository(tmp_path)
    (root / "src").mkdir()
    (root / "src/partial.py").write_text("approved_seed = True\n")
    before = capture_mutation_inventory(root)
    request = _coder_request().model_copy(update={"source_revision": base})
    admissions: list[AgentRequest] = []

    class Admission:
        def authorize(self, value: AgentRequest, workspace_root: Path) -> None:
            assert value == request and workspace_root == root
            assert capture_mutation_inventory(workspace_root) == before
            admissions.append(value)

    runner = FailedRunner()
    result = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        runner=runner,
        prompt_builder=StaticPromptBuilder(),
        initial_workspace_admission=Admission(),
    ).run(request)
    assert result.error is not None and result.error.code is AgentErrorCode.QUOTA_EXHAUSTED
    assert result.error.transient and runner.calls == 1 and admissions == [request]
    assert capture_mutation_inventory(root) == before


@pytest.mark.parametrize("new_mutation", [False, True])
def test_real_fallback_uses_preserved_progress_only_when_primary_left_it_unchanged(
    tmp_path: Path, new_mutation: bool
) -> None:
    root, request, admission = progress(tmp_path)
    before = capture_mutation_inventory(root)
    primary_runner = FailedRunner(
        mutate=(lambda cwd: mutate_workspace(cwd, "body")) if new_mutation else None
    )

    class BackupRunner(_ProgressRunner):
        calls = 0

        def run(
            self,
            argv: tuple[str, ...],
            *,
            cwd: Path,
            environment: Mapping[str, str],
            stdin: str,
            timeout_seconds: float,
        ) -> CodexInvocationResult:
            self.calls += 1
            return super().run(
                argv,
                cwd=cwd,
                environment=environment,
                stdin=stdin,
                timeout_seconds=timeout_seconds,
            )

    backup_runner = BackupRunner(request)
    routes = tuple(
        ProviderAgentRoute(
            "codex",
            model,
            CodexCliAgentAdapter(
                workspace_root=root,
                model=model,
                agent_id="agent_coder_001",
                agent_version="v0.1",
                runner=runner,
                prompt_builder=StaticPromptBuilder(),
                initial_workspace_admission=FirstCoderRunWorkspaceAdmission(admission),
            ),
        )
        for model, runner in (
            ("fixture-primary", primary_runner),
            ("fixture-backup", backup_runner),
        )
    )
    store = FileModelRouteAttemptStore(tmp_path / "model-routes")
    result = FallbackAgentAdapter(routes, attempt_store=store).run(request)
    records = store.list_for_run(request.run_id)
    assert primary_runner.calls == 1 and backup_runner.calls == (0 if new_mutation else 1)
    assert len(records) == (1 if new_mutation else 2)
    assert records[0].outcome is (
        RouteAttemptOutcome.FAILED if new_mutation else RouteAttemptOutcome.FALLBACK
    )
    if new_mutation:
        assert result.error is not None and result.error.code is AgentErrorCode.POLICY_VIOLATION
        assert (root / "src/partial.py").read_text() == "new_write = True\n"
    else:
        assert result.status is AgentRunStatus.SUCCEEDED and result.artifact is not None
        assert result.artifact.kind.value == "coder-progress"
        assert capture_mutation_inventory(root) == before
    assert FallbackAgentAdapter(routes, attempt_store=store).run(request) == result
    assert primary_runner.calls == 1 and backup_runner.calls == (0 if new_mutation else 1)


@pytest.mark.parametrize("fault", ["inventory", "index"])
@pytest.mark.parametrize("failure_at", [1, 2])
def test_unavailable_before_or_after_snapshot_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_at: int, fault: str
) -> None:
    root, request, admission = progress(tmp_path)
    calls = 0

    def observe(cwd: Path) -> WorkspaceMutationInventory:
        nonlocal calls
        calls += 1
        if calls == failure_at:
            raise MutationInventoryRejected("fixture unavailable observation")
        return capture_mutation_inventory(cwd)

    original_listing = codex_cli_module._index_listing

    def list_index(cwd: Path) -> str:
        nonlocal calls
        calls += 1
        if calls == (1 if failure_at == 1 else 3):
            raise MutationInventoryRejected("fixture unavailable index observation")
        return original_listing(cwd)

    if fault == "inventory":
        monkeypatch.setattr(codex_cli_module, "capture_mutation_inventory", observe)
    else:
        monkeypatch.setattr(codex_cli_module, "_index_listing", list_index)
    runner = FailedRunner()
    control = InvocationControl()
    result = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        runner=runner,
        prompt_builder=StaticPromptBuilder(),
        initial_workspace_admission=FirstCoderRunWorkspaceAdmission(admission),
        interruption_control=control,
    ).run(request)
    assert result.error is not None and not result.error.transient
    assert result.error.code is (
        AgentErrorCode.WORK_INTERRUPTED if failure_at == 1 else AgentErrorCode.POLICY_VIOLATION
    )
    assert runner.calls == failure_at - 1 and result.artifact is None
    assert control.started_calls == failure_at - 1


@pytest.mark.parametrize("failure", ["oversized", "timeout", "spawn", "nonzero", "encoding"])
def test_index_inspection_is_bounded_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    limit = 4096
    monkeypatch.setattr(codex_cli_module, "_MAX_INDEX_OBSERVATION_BYTES", limit)
    original_temporary_file = tempfile.TemporaryFile
    reads: list[int] = []

    @contextmanager
    def temporary_file(*, mode: str) -> Iterator[BinaryIO]:
        with original_temporary_file(mode=mode) as raw:
            actual = cast(BinaryIO, raw)

            class FileReadProbe:
                def fileno(self) -> int:
                    return actual.fileno()

                def seek(self, offset: int) -> int:
                    return actual.seek(offset)

                def read(self, size: int) -> bytes:
                    reads.append(size)
                    return actual.read(size)

                def write(self, body: bytes) -> int:
                    return actual.write(body)

                def truncate(self, size: int) -> int:
                    return actual.truncate(size)

            yield cast(BinaryIO, FileReadProbe())

    def inspect(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
        stdin: int,
        stdout: BinaryIO,
        stderr: int,
        shell: bool,
        timeout: int,
        check: bool,
    ) -> subprocess.CompletedProcess[bytes]:
        assert cwd == tmp_path and timeout == 30 and not shell and not check
        assert stdin == stderr == subprocess.DEVNULL
        assert "core.hooksPath=/dev/null" in argv and "core.fsmonitor=false" in argv
        assert set(env) == {"PATH", "LANG", "LC_ALL", "GIT_TERMINAL_PROMPT", "GIT_OPTIONAL_LOCKS"}
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, timeout)
        if failure == "spawn":
            raise OSError("private fixture startup detail")
        if failure == "oversized":
            stdout.truncate(limit + 1)
        elif failure == "encoding":
            stdout.write(b"\xff")
        return subprocess.CompletedProcess(argv, 1 if failure == "nonzero" else 0)

    monkeypatch.setattr(tempfile, "TemporaryFile", temporary_file)
    monkeypatch.setattr(subprocess, "run", inspect)
    with pytest.raises(MutationInventoryRejected) as rejected:
        codex_cli_module._index_listing(tmp_path)
    assert "private fixture" not in str(rejected.value)
    assert reads == ([limit + 1] if failure == "encoding" else [])


@pytest.mark.parametrize("observation", [*InterruptionObservation, "unknown_stop"])
def test_owned_interruption_decision_precedes_failure_fallback(
    tmp_path: Path, observation: str
) -> None:
    root, request, admission = progress(tmp_path)

    runner = FailedRunner()
    control = InvocationControl(observation)
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="fixture",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        runner=runner,
        prompt_builder=StaticPromptBuilder(),
        initial_workspace_admission=FirstCoderRunWorkspaceAdmission(admission),
        interruption_control=control,
    )
    if observation == "unknown_stop":
        with pytest.raises(ContinuationExecutionUncertain):
            adapter.run(request)
    else:
        result = adapter.run(request)
        assert result.error is not None and result.artifact is None
        unchanged = observation == InterruptionObservation.UNCHANGED
        assert result.error.code is (
            AgentErrorCode.QUOTA_EXHAUSTED if unchanged else AgentErrorCode.WORK_INTERRUPTED
        )
        assert result.error.transient is unchanged
    assert runner.calls == control.started_calls == 1
