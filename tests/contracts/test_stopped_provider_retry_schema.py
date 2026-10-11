"""Published and fresh graphs retain stopped-provider gates independently of old rescues."""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.contracts.test_repair_schema_generation import (
    standalone_regenerated as regenerated_fixture,
)

standalone_regenerated = regenerated_fixture
ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize("fresh", [False, True])
def test_every_embedded_binding_requires_human_pause_and_exact_provider_proof(
    standalone_regenerated: dict[str, Any], fresh: bool
) -> None:
    documents = (
        standalone_regenerated
        if fresh
        else {p.name: json.loads(p.read_text()) for p in (ROOT / "schemas").glob("*.json")}
    )
    valid = {
        "purpose": "stopped_provider_retry",
        "input_mode": "preserve_draft",
        "continuation_mode": "pause",
        "authority_source": "engineering_operator_decision",
        "stopped_provider_failure_sha256": "a",
    }
    bad = [
        {**valid, "continuation_mode": "resume"},
        {k: v for k, v in valid.items() if k != "stopped_provider_failure_sha256"},
        {**valid, "input_mode": "coder_reapply"},
        {**valid, "authority_source": "organization_engineering_policy"},
        {**valid, "purpose": "legacy_workspace_rescue"},
        {**valid, "completed_output_sha256": "b"},
    ]
    matched = []
    for filename, document in documents.items():
        node = (
            document
            if document.get("title") == "ExecutionBaselineBinding"
            else document.get("$defs", {}).get("ExecutionBaselineBinding")
        )
        if node is None:
            continue
        matched.append(filename)
        check = Draft202012Validator({"allOf": node.get("allOf", [])})
        assert check.is_valid(valid), filename
        assert check.is_valid(
            {**valid, "purpose": "source_rebind", "input_mode": "coder_reapply"}
        ), filename
        for wire in bad:
            assert not check.is_valid(wire), (filename, wire)
    assert {
        "execution-baseline.schema.json",
        "execution-baseline-queue-consumption.schema.json",
        "execution-baseline-queue-release.schema.json",
    } <= set(matched)


@pytest.mark.parametrize("fresh", [False, True])
@pytest.mark.parametrize(
    ("name", "valid", "changes"),
    [
        (
            "BaselineExecutionReservation",
            {
                "retry_cause": "provider_prerequisite_repaired",
                "original_run_id": "run_original",
                "current_invocation_start_sha256": "a",
                "current_invocation_outcome_sha256": "b",
                "stopped_provider_failure_sha256": "c",
            },
            [
                {"retry_failure": {}},
                {"reservation_already_applied": True},
                {"interruption_receipt_sha256": "d"},
                {"completed_output_sha256": "e"},
                {"stopped_provider_failure_sha256": None},
            ],
        ),
        (
            "BaselineExecutionFacts",
            {
                "continuation": {"retry_cause": "provider_prerequisite_repaired"},
                "stopped_provider_failure": {},
            },
            [
                {"stopped_provider_failure": None},
                {"completed_output": {}},
                {"legacy_containment": {}},
                {"implementation_artifact_id": "art_impl"},
            ],
        ),
        (
            "ExecutionBaselinePlan",
            {
                "purpose": "stopped_provider_retry",
                "input_mode": "preserve_draft",
                "conflicted": False,
                "facts": {"stopped_provider_failure": {}},
            },
            [
                {"input_mode": "coder_reapply"},
                {"conflicted": True},
                {"facts": {"stopped_provider_failure": {}, "native_rule_change": {}}},
            ],
        ),
        (
            "ExecuteExecutionBaselineIntent",
            {"confirm_provider_prerequisites_repaired": True, "continuation_mode": "pause"},
            [
                {"continuation_mode": "resume"},
                {"confirm_legacy_containment": True},
                {"confirm_local_execution_stopped": True},
            ],
        ),
    ],
)
def test_fresh_and_published_cross_field_guards(
    standalone_regenerated: dict[str, Any],
    fresh: bool,
    name: str,
    valid: dict[str, Any],
    changes: list[dict[str, Any]],
) -> None:
    document = (
        standalone_regenerated["console-operation.schema.json"]
        if fresh
        else json.loads((ROOT / "schemas/console-operation.schema.json").read_text())
    )
    check = Draft202012Validator({"allOf": document["$defs"][name]["allOf"]})
    assert check.is_valid(valid)
    for mutation in changes:
        assert not check.is_valid({**valid, **mutation}), mutation
