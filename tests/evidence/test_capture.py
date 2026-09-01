"""Evidence capture redaction, replay, and run-manifest contracts."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentResult,
    AgentRunStatus,
    AgentUsage,
)
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.evidence import (
    CommandEvidenceRecord,
    CommandOutcome,
    EvidenceCaptureError,
    EvidenceCapturingAgentAdapter,
    EvidenceKind,
    FileEvidenceStore,
    RunEvidenceIdentity,
    RunEvidenceSession,
    RunOutcome,
)
from ai_software_engineer.evidence import TestOutcome as EvidenceTestOutcome
from ai_software_engineer.evidence.models import evidence_record_digest
from ai_software_engineer.execution import (
    CommandExecutionError,
    CommandResult,
    CommandTimedOut,
)
from ai_software_engineer.git import CommandPolicyViolation
from tests.domain.factories import make_implementation_artifact

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
CONTEXT_ID = "ctx_" + "c" * 64


def _identity(*, role: AgentRole = AgentRole.CODER) -> RunEvidenceIdentity:
    return RunEvidenceIdentity(
        project_id="project_evidence_001",
        task_id="task_evidence_001",
        run_id="run_evidence_001",
        agent_id="agent_evidence_001",
        role=role,
        attempt=1,
        source_revision="a" * 40,
        context_manifest_id=CONTEXT_ID,
    )


def _session(
    tmp_path: Path,
    *,
    role: AgentRole = AgentRole.CODER,
    clock: Callable[[], datetime] | None = None,
    max_patch_bytes: int = 1_000_000,
) -> RunEvidenceSession:
    return RunEvidenceSession(
        FileEvidenceStore(tmp_path / "evidence", tmp_path / "runs"),
        _identity(role=role),
        workspace_root=tmp_path / "worktree",
        clock=clock,
        max_patch_bytes=max_patch_bytes,
    )


class _Executor:
    def __init__(self, result: CommandResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        del timeout_seconds
        self.calls.append(arguments)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result.model_copy(update={"argv": arguments})


def _result(tmp_path: Path) -> CommandResult:
    return CommandResult(
        argv=("python", "-c", "print('ok')"),
        cwd=str(tmp_path / "worktree"),
        returncode=0,
        stdout="ready\nsecret=sk-abcdefghijklmnopqrstuvwxyz123456\n",
        stderr="",
        duration_ms=12,
    )


def test_command_capture_is_redacted_digest_sealed_and_replayable(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    executor = _Executor(_result(tmp_path))
    session = _session(tmp_path)

    first = session.capture_command(
        "command.test",
        executor,
        ("python", "-c", "print('token=do-not-persist')"),
    )
    replay = session.capture_command(
        "command.test",
        executor,
        ("python", "-c", "print('token=do-not-persist')"),
    )

    assert first == replay
    assert len(executor.calls) == 1
    assert first.payload.outcome is CommandOutcome.COMPLETED
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in first.payload.stdout
    assert "do-not-persist" not in first.payload.argv[-1]
    assert {item.kind for item in first.redactions} >= {"openai_key", "secret_assignment"}
    assert first.record_sha256 == evidence_record_digest(first)


@pytest.mark.parametrize(
    ("error", "expected"),
    (
        (CommandTimedOut(("python",), 42), CommandOutcome.TIMED_OUT),
        (CommandPolicyViolation("command rejected"), CommandOutcome.REJECTED),
        (CommandExecutionError("command could not start"), CommandOutcome.FAILED_TO_START),
    ),
)
def test_failed_commands_are_persisted_as_replayable_evidence(
    tmp_path: Path, error: Exception, expected: CommandOutcome
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    session = _session(tmp_path)
    executor = _Executor(error)

    with pytest.raises(type(error)):
        session.capture_command("command.failed", executor, ("python", "-c", "pass"))

    record = session._store.get(session._evidence_id(EvidenceKind.COMMAND, "command.failed"))
    assert isinstance(record, CommandEvidenceRecord)
    assert record.payload.outcome is expected
    assert record.payload.returncode is None
    assert record.payload.error_code is not None
    assert record.record_sha256 == evidence_record_digest(record)

    # A retry of the same operation replays the durable failure and never calls the executor.
    replay = session.capture_command("command.failed", executor, ("python", "-c", "pass"))
    assert replay == record
    assert len(executor.calls) == 1


def test_diff_and_test_evidence_are_bounded_and_linked_to_command(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    session = _session(tmp_path, max_patch_bytes=8)
    command = session.capture_command("command.test", _Executor(_result(tmp_path)), ("python",))
    diff = session.record_diff(
        "diff.candidate",
        base_revision="a" * 40,
        candidate_revision="b" * 40,
        changed_paths=("src/main.py",),
        patch="修改 token=private-value and more",
    )
    test = session.record_test(
        "test.pytest",
        framework="pytest",
        suite="tests/unit",
        outcome=EvidenceTestOutcome.PASS,
        command_evidence_id=command.evidence_id,
    )

    assert diff.payload.patch_truncated is True
    assert len(diff.payload.patch.encode()) <= 8
    assert test.payload.command_evidence_id == command.evidence_id
    assert {diff.evidence_id, test.evidence_id} <= {
        record.evidence_id for record in session._store.list_for_run(session.identity.run_id)
    }


def test_test_evidence_rejects_cross_run_command_reference(tmp_path: Path) -> None:
    first = _session(tmp_path / "first")
    (tmp_path / "first" / "worktree").mkdir(parents=True)
    command = first.capture_command(
        "command.test",
        _Executor(_result(tmp_path / "first")),
        ("python",),
    )
    second = _session(tmp_path / "second")
    (tmp_path / "second" / "worktree").mkdir(parents=True)

    # Both sessions use separate roots, so the second session cannot resolve the first run's ID.
    from ai_software_engineer.evidence import EvidenceNotFound

    with pytest.raises(EvidenceNotFound):
        second.record_test(
            "test.cross-run",
            framework="pytest",
            suite="tests",
            outcome=EvidenceTestOutcome.PASS,
            command_evidence_id=command.evidence_id,
        )


def test_agent_usage_and_manifest_are_sealed_with_exact_identity(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    session = _session(tmp_path)
    artifact = make_implementation_artifact().model_copy(
        update={
            "task_id": session.identity.task_id,
            "source_revision": "b" * 40,
            "context_manifest_id": session.identity.context_manifest_id,
            "producer": make_implementation_artifact().producer.model_copy(
                update={"run_id": session.identity.run_id}
            ),
        }
    )
    result = AgentResult(
        run_id=session.identity.run_id,
        task_id=session.identity.task_id,
        role=session.identity.role,
        attempt=session.identity.attempt,
        source_revision=session.identity.source_revision,
        context_manifest_id=session.identity.context_manifest_id,
        status=AgentRunStatus.SUCCEEDED,
        artifact=artifact,
        usage=AgentUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        duration_ms=33,
    )
    usage = session.record_agent_result("agent.result", result, provider="fake", model="test-model")
    manifest = session.seal(RunOutcome.SUCCEEDED)

    assert usage.payload.usage is not None
    assert usage.payload.usage.total_tokens == 15
    assert manifest.evidence_ids == (usage.evidence_id,)
    assert session._store.get_run(session.identity.run_id) == manifest


def test_agent_adapter_records_failed_run_before_returning_result(tmp_path: Path) -> None:
    from ai_software_engineer.agents import (
        AgentRequest,
        FakeAgentAdapter,
        FakeBehavior,
        FakeScenario,
    )
    from tests.agents.test_fake import _permissions

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    session = _session(tmp_path)
    request = AgentRequest(
        run_id=session.identity.run_id,
        task_id=session.identity.task_id,
        role=session.identity.role,
        attempt=1,
        source_revision=session.identity.source_revision,
        context_manifest_id=session.identity.context_manifest_id,
        input_artifact_ids=(),
        permissions=_permissions(),
        output_schema="schemas/implementation-report.schema.json",
        timeout_seconds=60,
    )
    adapter = EvidenceCapturingAgentAdapter(
        FakeAgentAdapter(default=FakeScenario(behavior=FakeBehavior.PROVIDER_ERROR)),
        session,
        provider="fake",
        model="offline",
    )
    result = adapter.run(request)

    assert result.status is AgentRunStatus.FAILED
    assert session._store.get_run(session.identity.run_id).outcome is RunOutcome.FAILED


def test_sealed_run_replay_rejects_changed_outcome(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    session = _session(tmp_path)
    session.capture_command("command.test", _Executor(_result(tmp_path)), ("python",))
    session.seal(RunOutcome.SUCCEEDED)

    with pytest.raises(EvidenceCaptureError):
        session.seal(RunOutcome.FAILED)
