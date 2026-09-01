"""Role isolation and fail-closed behavior of the policy-bound tool registry."""

import hashlib
from pathlib import Path

import pytest

from ai_software_engineer.domain import (
    AgentDefinition,
    AgentPermissions,
    AgentRole,
    ArtifactKind,
    NetworkAccess,
)
from ai_software_engineer.execution import CommandResult
from ai_software_engineer.tools import (
    PolicyBoundToolRegistry,
    ReadFileRequest,
    ReadFileResult,
    RunCommandRequest,
    RunCommandResult,
    ToolRejectedResult,
    ToolRequestIdentityMismatch,
    WriteFileRequest,
    WriteFileResult,
)


class FakeCommandExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        del timeout_seconds
        self.calls.append(arguments)
        return CommandResult(
            argv=arguments,
            cwd="/fake/worktree",
            returncode=0,
            stdout="ok\n",
            stderr="",
            duration_ms=1,
        )


def _agent(role: AgentRole, *, broad_write: bool = False) -> AgentDefinition:
    inputs = {
        AgentRole.CODER: (
            ArtifactKind.PLAN,
            ArtifactKind.QA_REPORT,
            ArtifactKind.REVIEW_REPORT,
        ),
        AgentRole.QA: (ArtifactKind.PLAN, ArtifactKind.IMPLEMENTATION_REPORT),
        AgentRole.REVIEWER: (
            ArtifactKind.PLAN,
            ArtifactKind.IMPLEMENTATION_REPORT,
            ArtifactKind.QA_REPORT,
        ),
    }[role]
    output = {
        AgentRole.CODER: ArtifactKind.IMPLEMENTATION_REPORT,
        AgentRole.QA: ArtifactKind.QA_REPORT,
        AgentRole.REVIEWER: ArtifactKind.REVIEW_REPORT,
    }[role]
    return AgentDefinition(
        id=f"agent_{role.value}_tool",
        role=role,
        version="v0.1",
        model="fixture-model",
        permissions=AgentPermissions(
            read_paths=("**",),
            write_paths=("**",)
            if broad_write
            else (
                ("src/**", "tests/**")
                if role is AgentRole.CODER
                else ("tests/**",)
                if role is AgentRole.QA
                else ()
            ),
            commands=("pytest", "git diff", "git status"),
            network=NetworkAccess.NONE,
        ),
        input_artifacts=inputs,
        output_artifacts=(output,),
        max_retries=0,
        timeout_seconds=60,
        token_budget=1000,
    )


def _read(run_id: str = "run_tool_registry_001") -> ReadFileRequest:
    return ReadFileRequest(
        run_id=run_id,
        role=AgentRole.CODER,
        operation_id="tool.read",
        path="src/app.py",
    )


def test_coder_can_read_write_and_run_allowlisted_command(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    fake = FakeCommandExecutor()
    registry = PolicyBoundToolRegistry(
        tmp_path,
        _agent(AgentRole.CODER),
        run_id="run_tool_registry_001",
        command_executor=fake,
    )

    read = registry.execute(_read())
    assert isinstance(read, ReadFileResult)
    assert read.content == "VALUE = 1\n"
    assert read.content_sha256 == hashlib.sha256(b"VALUE = 1\n").hexdigest()

    write = registry.execute(
        WriteFileRequest(
            run_id="run_tool_registry_001",
            role=AgentRole.CODER,
            operation_id="tool.write",
            path="src/app.py",
            content="VALUE = 2\n",
        )
    )
    assert isinstance(write, WriteFileResult)
    assert (tmp_path / "src/app.py").read_text(encoding="utf-8") == "VALUE = 2\n"

    command = registry.execute(
        RunCommandRequest(
            run_id="run_tool_registry_001",
            role=AgentRole.CODER,
            operation_id="tool.test",
            argv=("pytest", "tests/unit", "-q"),
        )
    )
    assert isinstance(command, RunCommandResult)
    assert fake.calls == [("pytest", "tests/unit", "-q")]


def test_registry_returns_typed_rejection_for_shell_or_denied_paths(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    registry = PolicyBoundToolRegistry(
        tmp_path,
        _agent(AgentRole.CODER),
        run_id="run_tool_registry_001",
    )

    shell = registry.execute(
        RunCommandRequest(
            run_id="run_tool_registry_001",
            role=AgentRole.CODER,
            operation_id="tool.shell",
            argv=("pytest", "&&", "git", "push"),
        )
    )
    assert isinstance(shell, ToolRejectedResult)
    assert shell.error_code == "COMMAND_DENIED"

    interpreter = registry.execute(
        RunCommandRequest(
            run_id="run_tool_registry_001",
            role=AgentRole.CODER,
            operation_id="tool.interpreter",
            argv=("sh", "-c", "echo unsafe"),
        )
    )
    assert isinstance(interpreter, ToolRejectedResult)
    assert interpreter.error_code == "COMMAND_DENIED"

    denied = registry.execute(
        WriteFileRequest(
            run_id="run_tool_registry_001",
            role=AgentRole.CODER,
            operation_id="tool.policy",
            path=".trellis/spec/new.md",
            content="cannot change policy",
        )
    )
    assert isinstance(denied, ToolRejectedResult)
    assert denied.error_code == "PATH_DENIED"


def test_qa_cannot_write_production_even_when_permissions_are_misconfigured(tmp_path: Path) -> None:
    registry = PolicyBoundToolRegistry(
        tmp_path,
        _agent(AgentRole.QA, broad_write=True),
        run_id="run_tool_registry_qa01",
    )
    result = registry.execute(
        WriteFileRequest(
            run_id="run_tool_registry_qa01",
            role=AgentRole.QA,
            operation_id="tool.qa-prod",
            path="src/app.py",
            content="tamper",
        )
    )
    assert isinstance(result, ToolRejectedResult)
    assert result.error_code == "PATH_DENIED"


def test_reviewer_cannot_write_or_modify_verdict(tmp_path: Path) -> None:
    registry = PolicyBoundToolRegistry(
        tmp_path,
        _agent(AgentRole.REVIEWER, broad_write=True),
        run_id="run_tool_registry_rev01",
    )
    result = registry.execute(
        WriteFileRequest(
            run_id="run_tool_registry_rev01",
            role=AgentRole.REVIEWER,
            operation_id="tool.review-output",
            path="review-report.json",
            content='{"verdict":"APPROVE"}',
        )
    )
    assert isinstance(result, ToolRejectedResult)
    assert result.error_code == "PATH_DENIED"


def test_bound_registry_rejects_another_run_or_role(tmp_path: Path) -> None:
    registry = PolicyBoundToolRegistry(
        tmp_path,
        _agent(AgentRole.CODER),
        run_id="run_tool_registry_001",
    )
    with pytest.raises(ToolRequestIdentityMismatch):
        registry.execute(
            ReadFileRequest(
                run_id="run_tool_registry_002",
                role=AgentRole.CODER,
                operation_id="tool.read-other",
                path="src/app.py",
            )
        )
    with pytest.raises(ToolRequestIdentityMismatch):
        registry.execute(
            ReadFileRequest(
                run_id="run_tool_registry_001",
                role=AgentRole.QA,
                operation_id="tool.read-role",
                path="src/app.py",
            )
        )
