"""Wire-level tests for typed tool requests and results."""

from contextlib import suppress

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.tools import (
    TOOL_REQUEST_ADAPTER,
    ReadFileRequest,
    RunCommandRequest,
    WriteFileRequest,
)


def test_request_adapter_accepts_only_structured_argv_and_path_fields() -> None:
    request = TOOL_REQUEST_ADAPTER.validate_python(
        {
            "tool": "run_command",
            "run_id": "run_tool_models_001",
            "role": "coder",
            "operation_id": "tool.run",
            "argv": ["pytest", "tests/unit", "-q"],
        }
    )

    assert isinstance(request, RunCommandRequest)
    assert request.argv == ("pytest", "tests/unit", "-q")


def test_requests_are_immutable_and_do_not_have_free_text_shell_field() -> None:
    request = ReadFileRequest(
        run_id="run_tool_models_002",
        role=AgentRole.QA,
        operation_id="tool.read",
        path="src/app.py",
    )

    assert not hasattr(request, "shell")
    with suppress(Exception):
        request.path = "tests/app.py"
    assert request.path == "src/app.py"


def test_write_request_rejects_unknown_fields() -> None:
    try:
        WriteFileRequest(
            run_id="run_tool_models_003",
            role=AgentRole.CODER,
            operation_id="tool.write",
            path="src/app.py",
            content="x",
            verdict="APPROVE",  # type: ignore[call-arg]
        )
    except Exception as error:
        assert "verdict" in str(error)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("unknown verdict field must be rejected")
