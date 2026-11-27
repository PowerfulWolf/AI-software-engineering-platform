"""A Claude CLI schema repair round stays inside one recorded knowledge invocation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ai_software_engineer.agents.claude_cli import ClaudeCliStructuredModelClient
from ai_software_engineer.agents.model_diagnostics import model_call_phase
from ai_software_engineer.agents.structured import (
    FallbackStructuredModelClient,
    StructuredModelRoute,
)
from ai_software_engineer.agents.structured_observation import (
    StructuredExecutionAdmission,
    StructuredNativeStopReceipt,
)
from ai_software_engineer.domain.enums import TeamRole
from ai_software_engineer.knowledge.invocation import (
    KnowledgeInvocationJournal,
    KnowledgeInvocationOutcome,
    invocation_lane_sha256,
)
from ai_software_engineer.knowledge.store import KnowledgeRecordStore
from tests.knowledge.test_retrieval_contract import binding, snapshot

_SCHEMA = {
    "type": "object",
    "properties": {"queries": {"type": "array"}},
    "required": ["queries"],
    "additionalProperties": False,
}


def _fake_claude(tmp_path: Path) -> Path:
    counter = tmp_path / "calls"
    executable = tmp_path / "claude"
    executable.write_text(
        f"#!{sys.executable}\nimport json, sys\nfrom pathlib import Path\n"
        f"counter = Path({str(counter)!r})\n"
        "calls = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(calls + 1))\n"
        "sys.stdin.read()\n"
        "payload = {'queries': 'not-an-array'} if calls == 0 else {'queries': []}\n"
        "print(json.dumps({'type': 'result', 'is_error': False, 'structured_output': payload,"
        " 'usage': {'input_tokens': 1, 'output_tokens': 1}}))\n"
    )
    executable.chmod(0o700)
    return executable


def test_schema_repair_round_is_admitted_within_the_original_limit(tmp_path: Path) -> None:
    frozen = snapshot()
    bound = binding(frozen, TeamRole.PLANNER)
    root = tmp_path / "knowledge"
    workspace = tmp_path / "repository"
    workspace.mkdir()
    client = FallbackStructuredModelClient(
        (
            StructuredModelRoute(
                provider="claude",
                model="fixture-model",
                client=ClaudeCliStructuredModelClient(
                    repository_root=workspace,
                    model="fixture-model",
                    executable=str(_fake_claude(tmp_path)),
                    environment={"HOME": str(tmp_path)},
                ),
            ),
        ),
        role=TeamRole.PLANNER,
    )
    with model_call_phase("knowledge_intent"):
        result = KnowledgeInvocationJournal(KnowledgeRecordStore(root)).call(
            bound,
            "intent",
            client=client,
            instructions="prepare",
            input_payload={"task": "fixture"},
            output_schema=_SCHEMA,
            timeout_seconds=120,
        )
    assert dict(result.payload) == {"queries": []}
    assert json.loads((tmp_path / "calls").read_text()) == 2
    lane = KnowledgeRecordStore(
        root / "invocations" / invocation_lane_sha256(bound), read_only=True
    )
    outcome = lane.get(
        "knowledge-invocation-outcomes", bound.run_id + ":intent", KnowledgeInvocationOutcome
    )
    outcome.validate_integrity()
    assert outcome.state == "RETURNED"
    observations = [record.observation for record in outcome.executions]
    admissions = [item for item in observations if isinstance(item, StructuredExecutionAdmission)]
    stops = [item for item in observations if isinstance(item, StructuredNativeStopReceipt)]
    assert len(admissions) == len(stops) == 2
    assert admissions[0].timeout_seconds == 120
    assert 0 < admissions[1].timeout_seconds <= 120
