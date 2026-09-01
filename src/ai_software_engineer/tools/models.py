"""Typed wire contracts for the role tool protocol.

The model adapter is deliberately not given a shell or a mutable Python object.  It
can only emit one of the small request types below.  The registry turns the request
into a policy-checked operation and returns an immutable result (or a typed
rejection).  Adding a new capability therefore requires a contract and a policy
decision instead of quietly expanding an Agent prompt.
"""

from typing import Annotated, Final, Literal

from pydantic import Field, StrictBool, StrictInt, StringConstraints, TypeAdapter

from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.identity import RunId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr
from ai_software_engineer.evidence.models import OperationId
from ai_software_engineer.execution import CommandResult

ToolPath = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
ToolErrorCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class ToolRequestBase(DomainModel):
    """Identity carried by every tool call and included in every result."""

    run_id: RunId
    role: AgentRole
    operation_id: OperationId


class ReadFileRequest(ToolRequestBase):
    """Read one UTF-8 repository-relative file through the read allowlist."""

    tool: Literal["read_file"] = "read_file"
    path: ToolPath
    max_bytes: StrictInt = Field(default=1_000_000, ge=1, le=10_000_000)


class WriteFileRequest(ToolRequestBase):
    """Write one UTF-8 repository-relative file through the write allowlist."""

    tool: Literal["write_file"] = "write_file"
    path: ToolPath
    content: str


class RunCommandRequest(ToolRequestBase):
    """Run an already-tokenized command; shell source is not representable here."""

    tool: Literal["run_command"] = "run_command"
    argv: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1, max_length=64)]
    timeout_seconds: StrictInt | None = Field(default=None, ge=1, le=3600)


type ToolRequest = Annotated[
    ReadFileRequest | WriteFileRequest | RunCommandRequest,
    Field(discriminator="tool"),
]
TOOL_REQUEST_ADAPTER: Final[TypeAdapter[ToolRequest]] = TypeAdapter(ToolRequest)


class ToolResultBase(DomainModel):
    """Common identity of successful and rejected tool results."""

    run_id: RunId
    role: AgentRole
    operation_id: OperationId


class ReadFileResult(ToolResultBase):
    result_kind: Literal["read_file"] = "read_file"
    status: Literal["SUCCEEDED"] = "SUCCEEDED"
    tool: Literal["read_file"] = "read_file"
    path: ToolPath
    content: str
    content_sha256: Sha256
    bytes_read: StrictInt = Field(ge=0)
    truncated: StrictBool = False


class WriteFileResult(ToolResultBase):
    result_kind: Literal["write_file"] = "write_file"
    status: Literal["SUCCEEDED"] = "SUCCEEDED"
    tool: Literal["write_file"] = "write_file"
    path: ToolPath
    content_sha256: Sha256
    bytes_written: StrictInt = Field(ge=0)


class RunCommandResult(ToolResultBase):
    result_kind: Literal["run_command"] = "run_command"
    status: Literal["SUCCEEDED"] = "SUCCEEDED"
    tool: Literal["run_command"] = "run_command"
    command: CommandResult


class ToolRejectedResult(ToolResultBase):
    """A fail-closed refusal; it is never interpreted as a successful operation."""

    result_kind: Literal["rejected"] = "rejected"
    status: Literal["REJECTED"] = "REJECTED"
    tool: Literal["read_file", "write_file", "run_command"]
    rejected: Literal[True] = True
    error_code: ToolErrorCode
    error_message: NonEmptyStr


type ToolResult = Annotated[
    ReadFileResult | WriteFileResult | RunCommandResult | ToolRejectedResult,
    Field(discriminator="result_kind"),
]
TOOL_RESULT_ADAPTER: Final[TypeAdapter[ToolResult]] = TypeAdapter(ToolResult)


__all__ = [
    "TOOL_REQUEST_ADAPTER",
    "TOOL_RESULT_ADAPTER",
    "ReadFileRequest",
    "ReadFileResult",
    "RunCommandRequest",
    "RunCommandResult",
    "ToolPath",
    "ToolRejectedResult",
    "ToolRequest",
    "ToolRequestBase",
    "ToolResult",
    "ToolResultBase",
    "WriteFileRequest",
    "WriteFileResult",
]
