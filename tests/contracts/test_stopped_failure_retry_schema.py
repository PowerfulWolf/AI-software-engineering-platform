"""Unknown native failures require their own exact ordinary-work authority."""

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
@pytest.mark.parametrize(
    ("title", "valid", "mutations"),
    [
        (
            "BaselineExecutionReservation",
            {
                "retry_cause": "stopped_failure_retry",
                "original_run_id": "run_old",
                "current_invocation_start_sha256": "a",
                "current_invocation_outcome_sha256": "b",
                "stopped_failure_sha256": "c",
            },
            [
                {"stopped_failure_sha256": None},
                {"current_invocation_outcome_sha256": None},
                {"retry_failure": {}},
                {"reservation_already_applied": True},
                {"stopped_provider_failure_sha256": "d"},
                {"stopped_execution_sha256": "d"},
                {"interruption_receipt_sha256": "d"},
                {"completed_output_sha256": "d"},
                {"retry_cause": "provider_transient"},
            ],
        ),
        (
            "BaselineExecutionFacts",
            {"continuation": {"retry_cause": "stopped_failure_retry"}, "stopped_failure": {}},
            [
                {"stopped_failure": None},
                {"stopped_provider_failure": {}},
                {"stopped_execution": {}},
                {"legacy_containment": {}},
                {"completed_output": {}},
                {"native_rule_change": {}},
                {"implementation_artifact_id": "art_impl"},
                {"continuation": {"retry_cause": "provider_prerequisite_repaired"}},
            ],
        ),
        (
            "ExecutionBaselinePlan",
            {
                "purpose": "stopped_failure_retry",
                "input_mode": "preserve_draft",
                "facts": {"stopped_failure": {}},
                "conflicted": False,
            },
            [
                {"input_mode": "coder_reapply"},
                {"conflicted": True},
                {"facts": {"stopped_failure": None}},
                {"purpose": "source_rebind"},
            ],
        ),
        (
            "ExecutionBaselineBinding",
            {
                "purpose": "stopped_failure_retry",
                "input_mode": "preserve_draft",
                "continuation_mode": "pause",
                "authority_source": "engineering_operator_decision",
                "stopped_failure_sha256": "a",
            },
            [
                {"stopped_failure_sha256": None},
                {"purpose": "source_rebind"},
                {"continuation_mode": "resume"},
                {"input_mode": "coder_reapply"},
                {"authority_source": "organization_engineering_policy"},
                {"completed_output_sha256": "b"},
                {"stopped_provider_failure_sha256": "b"},
                {"stopped_execution_sha256": "b"},
                {"context_capacity_receipt_sha256": "b"},
            ],
        ),
        (
            "ExecuteExecutionBaselineIntent",
            {"confirm_stopped_failure_retry": True, "continuation_mode": "pause"},
            [
                {"continuation_mode": "resume"},
                {"confirm_provider_prerequisites_repaired": True},
                {"confirm_local_execution_stopped": True},
                {"confirm_legacy_containment": True},
                {"approved_native_rule_change_sha256": "b"},
            ],
        ),
        (
            "ProposeExecutionBaselineIntent",
            {"purpose": "stopped_failure_retry", "input_mode": "preserve_draft"},
            [{"target_base_ref": "a"}, {"input_mode": "coder_reapply"}],
        ),
    ],
)
def test_published_and_regenerated_cross_field_guards(
    standalone_regenerated: dict[str, Any],
    fresh: bool,
    title: str,
    valid: dict[str, Any],
    mutations: list[dict[str, Any]],
) -> None:
    documents = (
        standalone_regenerated
        if fresh
        else {path.name: json.loads(path.read_text()) for path in (ROOT / "schemas").glob("*.json")}
    )
    matched = []
    for name, document in documents.items():
        node = document if document.get("title") == title else document.get("$defs", {}).get(title)
        if node is None:
            continue
        matched.append(name)
        check = Draft202012Validator({"allOf": node.get("allOf", [])})
        assert check.is_valid(valid), (name, title)
        for mutation in mutations:
            assert not check.is_valid({**valid, **mutation}), (name, title, mutation)
    assert matched, title


@pytest.mark.parametrize("fresh", [False, True])
def test_proof_guards_preserve_exact_failure_and_owned_stop(
    standalone_regenerated: dict[str, Any], fresh: bool
) -> None:
    document = (
        standalone_regenerated["stopped-failure.schema.json"]
        if fresh
        else json.loads((ROOT / "schemas/stopped-failure.schema.json").read_text())
    )
    check = Draft202012Validator({"allOf": document["allOf"]})
    valid = {
        "outcome": {
            "start": {"request": {"role": "coder"}},
            "result": {
                "status": "FAILED",
                "error": {"code": "PROVIDER_UNAVAILABLE", "transient": False},
            },
        },
        "capture_stop": {
            "output_present": False,
            "process_stop": {
                "kind": "failed",
                "returncode": 1,
                "session_proof": {"proof_scope": "owned_session_empty"},
            },
        },
    }
    assert check.is_valid(valid)
    mutations = [
        ("outcome.result.status", "SUCCEEDED"),
        ("outcome.result.error.code", "AUTHENTICATION_ERROR"),
        ("outcome.result.error.transient", True),
        ("outcome.result.artifact", {}),
        ("outcome.start.request.role", "qa"),
        ("capture_stop.output_present", True),
        ("capture_stop.cause", "provider_transient"),
        ("capture_stop.original_error_code", "AUTHENTICATION_ERROR"),
        ("capture_stop.execution_abort_reason", {}),
        ("capture_stop.process_stop.kind", "completed"),
        ("capture_stop.process_stop.returncode", 0),
        ("capture_stop.process_stop.session_proof", None),
        ("capture_stop.process_stop.session_proof.proof_scope", "boot_after_start"),
    ]
    for path, value in mutations:
        wire = json.loads(json.dumps(valid))
        parent = wire
        parts = path.split(".")
        for key in parts[:-1]:
            parent = parent[key]
        parent[parts[-1]] = value
        assert not check.is_valid(wire), path
