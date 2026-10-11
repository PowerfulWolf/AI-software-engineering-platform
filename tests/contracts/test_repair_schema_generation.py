"""Repair regeneration retains independent legacy and knowledge wire guards."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator

from tests.domain.test_knowledge_preparation_retry_schema import _decision, _evidence, _proof

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("repair-schema-regeneration")
    scripts = root / "scripts"
    scripts.mkdir()
    schemas = root / "schemas"
    schemas.mkdir()
    for name in ("generate-repair-schemas.py", "sync-legacy-rescue-schemas.py"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    shutil.copyfile(
        ROOT / "schemas" / "engineering-wait-resolution.schema.json",
        schemas / "engineering-wait-resolution.schema.json",
    )
    command = (sys.executable, str(scripts / "generate-repair-schemas.py"))
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, timeout=60)
    first = (schemas / "console-operation.schema.json").read_bytes()
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, timeout=60)
    assert (schemas / "console-operation.schema.json").read_bytes() == first
    return cast(dict[str, Any], json.loads(first))


def test_regeneration_preserves_every_published_allof_without_requiring_a_previous_output(
    regenerated: dict[str, Any],
) -> None:
    published = json.loads((ROOT / "schemas/console-operation.schema.json").read_text())
    for name, node in published["$defs"].items():
        for guard in node.get("allOf", []):
            assert guard in regenerated["$defs"][name].get("allOf", []), name
    assert regenerated["allOf"] == published["allOf"]


@pytest.mark.parametrize(
    ("model", "valid", "invalid"),
    [
        (
            "BaselineExecutionReservation",
            {
                "retry_cause": "legacy_execution_abandoned",
                "original_run_id": "run_original",
                "current_invocation_start_sha256": "a",
                "containment_sha256": "b",
                "reservation_already_applied": False,
            },
            {"retry_cause": "legacy_execution_abandoned", "reservation_already_applied": True},
        ),
        (
            "ExecuteExecutionBaselineIntent",
            {"confirm_local_execution_stopped": True},
            {"confirm_legacy_containment": True, "confirm_local_execution_stopped": True},
        ),
        (
            "ExecutionBaselineBinding",
            {
                "purpose": "legacy_workspace_rescue",
                "input_mode": "preserve_draft",
                "authority_source": "engineering_operator_decision",
                "legacy_containment_sha256": "a",
            },
            {
                "purpose": "legacy_workspace_rescue",
                "input_mode": "coder_reapply",
                "authority_source": "organization_engineering_policy",
            },
        ),
        (
            "ExecutionBaselinePlan",
            {
                "purpose": "legacy_workspace_rescue",
                "input_mode": "preserve_draft",
                "conflicted": False,
                "facts": {"legacy_containment": {}},
            },
            {
                "purpose": "legacy_workspace_rescue",
                "input_mode": "preserve_draft",
                "conflicted": True,
                "facts": {},
            },
        ),
        (
            "LegacyExecutionContainment",
            {"method": "operator_confirmed_local_stop", "local_execution_survey": {"blockers": []}},
            {"method": "operator_confirmed_local_stop"},
        ),
        (
            "ConsoleCommandResult",
            {
                "delivery_id": "delivery_original",
                "checkpoint_sha256": "a",
                "legacy_rescue_preparation": {"status": "WAITING"},
            },
            {
                "delivery_id": "delivery_original",
                "checkpoint_sha256": "a",
                "legacy_rescue_preparation": {"status": "READY"},
            },
        ),
    ],
)
def test_regenerated_legacy_guards_reject_unsafe_cross_field_combinations(
    regenerated: dict[str, Any], model: str, valid: dict[str, Any], invalid: dict[str, Any]
) -> None:
    # Exercise the handwritten cross-field gate independently of generated shape.
    # Valid and invalid examples deliberately share the same trigger semantics.
    guards = regenerated["$defs"][model].get("allOf")
    assert guards, model
    validator = Draft202012Validator({"allOf": guards})
    assert validator.is_valid(valid), model
    assert not validator.is_valid(invalid), model


@pytest.mark.parametrize("model", ["DeliveryResolution", "DeliveryWaitInvestigation"])
def test_regeneration_keeps_new_knowledge_evidence_required(
    regenerated: dict[str, Any], model: str
) -> None:
    proof = _proof()
    wire = _decision(proof).to_wire() if model == "DeliveryResolution" else proof.to_wire()
    validator = Draft202012Validator({"$defs": regenerated["$defs"], "$ref": f"#/$defs/{model}"})
    assert validator.is_valid(wire)
    wire.pop("knowledge_preparation")
    assert not validator.is_valid(wire)


def test_regeneration_keeps_knowledge_role_and_independent_receipt_guards(
    regenerated: dict[str, Any],
) -> None:
    validator = Draft202012Validator(
        {"$defs": regenerated["$defs"], "$ref": "#/$defs/KnowledgePreparationRetryEvidence"}
    )
    wire = _evidence()
    assert validator.is_valid(wire)
    assert not validator.is_valid({**wire, "role": "planner"})
    assert not validator.is_valid({**wire, "execution_record_sha256s": ["a" * 64] * 2})


def test_regeneration_preserves_canonical_engineering_guards_and_optional_parent_binding(
    regenerated: dict[str, Any],
) -> None:
    canonical = json.loads((ROOT / "schemas/engineering-wait-resolution.schema.json").read_text())
    for name in (
        "DeliveryResolution",
        "DeliveryWaitInvestigation",
        "DeliveryWaitHandling",
        "VerifierPreparationEvidence",
        "KnowledgePreparationRetryEvidence",
    ):
        assert regenerated["$defs"][name]["allOf"] == canonical["$defs"][name]["allOf"]
    evidence = regenerated["$defs"]["KnowledgePreparationRetryEvidence"]
    assert (
        evidence["properties"]["delivery_requirement_id"]
        == canonical["$defs"]["KnowledgePreparationRetryEvidence"]["properties"][
            "delivery_requirement_id"
        ]
    )
    assert evidence["properties"]["delivery_requirement_id"]["default"] is None
    assert "delivery_requirement_id" not in evidence["required"]
