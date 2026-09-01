"""M6 wire-level checks for evidence and typed tool schemas."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from ai_software_engineer.domain import AgentRole
from ai_software_engineer.evidence import (
    CommandEvidencePayload,
    CommandEvidenceRecord,
    CommandOutcome,
    RunEvidenceIdentity,
    RunEvidenceManifest,
    RunOutcome,
    seal_evidence_record,
    seal_run_manifest,
)
from ai_software_engineer.execution import CommandResult
from ai_software_engineer.tools import (
    ReadFileResult,
    RunCommandResult,
    ToolRejectedResult,
    WriteFileResult,
)

SCHEMA_DIR = Path(__file__).parents[2] / "schemas"


JsonSchema = dict[str, object]


def _schemas() -> tuple[dict[str, JsonSchema], Registry]:
    decoded = [
        json.loads(path.read_text(encoding="utf-8")) for path in SCHEMA_DIR.glob("*.schema.json")
    ]
    schemas = [cast(JsonSchema, schema) for schema in decoded]
    registry = Registry().with_resources(
        (cast(str, schema["$id"]), Resource.from_contents(schema)) for schema in schemas
    )
    return (
        {cast(str, schema["$id"]).rsplit("/", 1)[-1]: schema for schema in schemas},
        registry,
    )


def _assert_valid(payload: Mapping[str, object], schema_name: str) -> None:
    schemas, registry = _schemas()
    errors = list(
        Draft202012Validator(
            cast(Mapping[str, object], schemas[schema_name]),
            registry=registry,
            format_checker=FormatChecker(),
        ).iter_errors(payload)
    )
    assert errors == [], [error.message for error in errors]


def _identity() -> RunEvidenceIdentity:
    return RunEvidenceIdentity(
        project_id="project_contract_m6",
        task_id="task_contract_m6",
        run_id="run_contract_m6",
        agent_id="agent_contract_m6",
        role=AgentRole.CODER,
        attempt=1,
        source_revision="a" * 40,
        context_manifest_id="ctx_" + "c" * 64,
    )


def test_evidence_record_and_manifest_wire_match_schemas() -> None:
    identity = _identity()
    timestamp = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    record = seal_evidence_record(
        CommandEvidenceRecord(
            evidence_id="ev_contract_m6_command",
            operation_id="contract.command",
            identity=identity,
            description="contract command",
            captured_at=timestamp,
            payload=CommandEvidencePayload(
                outcome=CommandOutcome.COMPLETED,
                argv=("pytest", "-q"),
                cwd="/tmp/worktree",
                returncode=0,
                duration_ms=4,
            ),
            record_sha256="0" * 64,
        )
    )
    manifest = seal_run_manifest(
        RunEvidenceManifest(
            identity=identity,
            outcome=RunOutcome.SUCCEEDED,
            evidence_ids=(record.evidence_id,),
            started_at=timestamp,
            completed_at=timestamp,
            manifest_sha256="0" * 64,
        )
    )

    _assert_valid(record.to_wire(), "evidence.schema.json")
    _assert_valid(manifest.to_wire(), "run-evidence-manifest.schema.json")


def test_typed_tool_results_wire_match_schema() -> None:
    command = CommandResult(
        argv=("pytest",),
        cwd="/tmp/worktree",
        returncode=0,
        stdout="ok",
        stderr="",
        duration_ms=1,
    )
    results = (
        ReadFileResult(
            run_id="run_contract_m6",
            role=AgentRole.CODER,
            operation_id="contract.read",
            path="src/app.py",
            content="VALUE = 1\n",
            content_sha256="a" * 64,
            bytes_read=10,
        ),
        WriteFileResult(
            run_id="run_contract_m6",
            role=AgentRole.CODER,
            operation_id="contract.write",
            path="src/app.py",
            content_sha256="b" * 64,
            bytes_written=10,
        ),
        RunCommandResult(
            run_id="run_contract_m6",
            role=AgentRole.CODER,
            operation_id="contract.command",
            command=command,
        ),
        ToolRejectedResult(
            run_id="run_contract_m6",
            role=AgentRole.CODER,
            operation_id="contract.rejected",
            tool="write_file",
            error_code="PATH_DENIED",
            error_message="write denied",
        ),
    )
    for result in results:
        _assert_valid(result.to_wire(), "tool-result.schema.json")
