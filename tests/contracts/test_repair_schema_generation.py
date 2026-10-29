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
def standalone_regenerated(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("standalone-schema-regeneration")
    scripts = root / "scripts"
    scripts.mkdir()
    shutil.copyfile(
        ROOT / "scripts/sync-legacy-rescue-schemas.py", scripts / "sync-legacy-rescue-schemas.py"
    )
    schemas = root / "schemas"
    shutil.copytree(ROOT / "schemas", schemas)
    # Standalone outputs are freshly generated, never their own policy source.
    for name in (
        "baseline-continue-authorization",
        "execution-native-rule-epoch",
        "execution-native-rule-change-inspection",
        "execution-baseline-queue-release",
        "team-snapshot",
        "requirement-checkpoint",
        "knowledge-stage-workflow",
        "completed-coder-output-unavailable",
        "stopped-provider-failure",
        "baseline-invocation-proof",
        "baseline-quiescence-proof",
        "consumed-pre-context-claim-observation",
        "reclaimed-uninvoked-claim-observation",
    ):
        (schemas / f"{name}.schema.json").unlink()
    command = (sys.executable, str(scripts / "sync-legacy-rescue-schemas.py"))
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, timeout=60)
    first = {path.name: path.read_bytes() for path in schemas.glob("*.schema.json")}
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, timeout=60)
    assert {path.name: path.read_bytes() for path in schemas.glob("*.schema.json")} == first
    return {name: json.loads(body) for name, body in first.items()}


@pytest.mark.parametrize(
    "name, title",
    [
        ("baseline-invocation-proof", "BaselineInvocationProof"),
        ("baseline-quiescence-proof", "BaselineQuiescenceProof"),
        ("consumed-pre-context-claim-observation", "ConsumedPreContextClaimObservation"),
        ("reclaimed-uninvoked-claim-observation", "ReclaimedUninvokedClaimObservation"),
    ],
)
def test_reclaimed_claim_proof_schemas_regenerate_standalone(
    standalone_regenerated: dict[str, Any],
    name: str,
    title: str,
) -> None:
    fresh = standalone_regenerated[name + ".schema.json"]
    published = json.loads((ROOT / "schemas" / (name + ".schema.json")).read_text())
    assert fresh == published
    assert fresh["title"] == title
    Draft202012Validator.check_schema(fresh)


@pytest.mark.parametrize("generated", [False, True])
def test_knowledge_isolation_guard_does_not_select_omitted_default_purpose(
    standalone_regenerated: dict[str, Any], generated: bool
) -> None:
    for name in (
        "console-deletion-cleanup",
        "console-operation",
        "execution-baseline-plan",
        "execution-baseline-queue-consumption",
        "execution-baseline-queue-release",
        "execution-baseline",
    ):
        document = (
            standalone_regenerated[name + ".schema.json"]
            if generated
            else json.loads((ROOT / "schemas" / (name + ".schema.json")).read_text())
        )
        nodes = {**document.get("$defs", {}), document.get("title"): document}
        for title in ("ExecutionBaselinePlan", "ExecutionBaselineBinding"):
            node = nodes.get(title)
            if node is None:
                continue
            guards = [
                guard
                for guard in node.get("allOf", [])
                if guard.get("if", {}).get("properties", {}).get("purpose", {}).get("const")
                == "knowledge_preparation_isolation"
            ]
            assert len(guards) == 1, (name, title)
            guard = guards[0]
            assert guard["if"].get("required") == ["purpose"], (name, title)
            check = Draft202012Validator(guard)
            ordinary = {"facts": {}} if title == "ExecutionBaselinePlan" else {}
            assert check.is_valid(ordinary), (name, title)
            assert not check.is_valid({**ordinary, "purpose": "knowledge_preparation_isolation"}), (
                name,
                title,
            )


@pytest.fixture(scope="module")
def generated_bundle(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    root = tmp_path_factory.mktemp("repair-schema-regeneration")
    scripts = root / "scripts"
    scripts.mkdir()
    schemas = root / "schemas"
    schemas.mkdir()
    for name in (
        "generate-repair-schemas.py",
        "sync-contained-unknown-contracts.py",
        "sync-legacy-rescue-schemas.py",
    ):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    shutil.copyfile(
        ROOT / "schemas" / "engineering-wait-resolution.schema.json",
        schemas / "engineering-wait-resolution.schema.json",
    )
    command = (sys.executable, str(scripts / "generate-repair-schemas.py"))
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, timeout=60)
    first = {path.name: path.read_bytes() for path in schemas.glob("*.schema.json")}
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, timeout=60)
    assert {path.name: path.read_bytes() for path in schemas.glob("*.schema.json")} == first
    return {name: cast(dict[str, Any], json.loads(body)) for name, body in first.items()}


@pytest.fixture(scope="module")
def regenerated(generated_bundle: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return generated_bundle["console-operation.schema.json"]


@pytest.mark.parametrize("name", ["console-operation", "stopped-failure-budget-settlement"])
def test_fresh_embedded_capacity_guards_keep_no_refund_and_legacy_finished_budget(
    generated_bundle: dict[str, dict[str, Any]], name: str
) -> None:
    from tests.domain.test_delivery_resolution_schema import _wire, capacity_resolution_wire

    schema = generated_bundle[name + ".schema.json"]
    canonical = json.loads((ROOT / "schemas/engineering-wait-resolution.schema.json").read_text())
    for model in ("VerifierPreparationEvidence", "DeliveryWaitInvestigation"):
        expected = canonical["$defs"][model]["allOf"]
        actual = schema["$defs"][model]["allOf"]
        # JSON Schema array order is not semantic. Keep the guard set exact;
        # the historical generator may append its compatibility guard later.
        assert len(actual) == len(expected)
        assert all(guard in actual for guard in expected)
    validator = Draft202012Validator(
        {
            "$defs": schema["$defs"],
            "$ref": "#/$defs/VerifierPreparationEvidence",
        }
    )
    capacity = capacity_resolution_wire()["verifier_preparation"]
    validator.validate(capacity)
    assert not validator.is_valid({**capacity, "budget_source": "frozen_work_attempt"})
    assert not validator.is_valid({**capacity, "native_finished_sha256": None})
    legacy = _wire("RETRY_VERIFIER_PREPARATION")["verifier_preparation"]
    validator.validate(legacy)
    assert not validator.is_valid({**legacy, "budget_source": None})


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
            "ProposeExecutionBaselineIntent",
            {"purpose": "knowledge_preparation_isolation", "input_mode": "preserve_draft"},
            {
                "purpose": "knowledge_preparation_isolation",
                "input_mode": "preserve_draft",
                "target_base_ref": "a",
            },
        ),
        (
            "ExecuteExecutionBaselineIntent",
            {
                "confirm_current_knowledge_execution_isolated": True,
                "continuation_mode": "pause",
            },
            {"confirm_current_knowledge_execution_isolated": True},
        ),
        (
            "ExecutionBaselineBinding",
            {
                "purpose": "knowledge_preparation_isolation",
                "input_mode": "preserve_draft",
                "authority_source": "engineering_operator_decision",
                "continuation_mode": "pause",
                "knowledge_isolation_sha256": "a",
            },
            {
                "purpose": "knowledge_preparation_isolation",
                "input_mode": "preserve_draft",
                "authority_source": "engineering_operator_decision",
                "continuation_mode": "pause",
                "knowledge_isolation_sha256": "a",
                "service_pause_outcome_sha256": "b",
            },
        ),
        (
            "BaselineExecutionReservation",
            {
                "retry_cause": "knowledge_isolation",
                "knowledge_isolation_sha256": "a",
                "reservation_already_applied": False,
            },
            {
                "retry_cause": "knowledge_isolation",
                "knowledge_isolation_sha256": "a",
                "original_run_id": "run_fabricated",
            },
        ),
        (
            "BaselineExecutionReservation",
            {
                "retry_cause": "knowledge_isolation",
                "knowledge_isolation_sha256": "a",
                "reservation_already_applied": False,
            },
            {
                "retry_cause": "knowledge_isolation",
                "knowledge_isolation_sha256": "a",
                "interruption_receipt_sha256": "b",
            },
        ),
        (
            "BaselineExecutionFacts",
            {
                "knowledge_isolation": {},
                "continuation": {"retry_cause": "knowledge_isolation"},
            },
            {
                "knowledge_isolation": None,
                "continuation": {"retry_cause": "knowledge_isolation"},
            },
        ),
        (
            "BaselineExecutionFacts",
            {
                "knowledge_isolation": {},
                "continuation": {"retry_cause": "knowledge_isolation"},
            },
            {"continuation": {"retry_cause": "knowledge_isolation"}},
        ),
        (
            "ExecutionBaselineBinding",
            {
                "purpose": "knowledge_preparation_isolation",
                "input_mode": "preserve_draft",
                "authority_source": "engineering_operator_decision",
                "continuation_mode": "pause",
                "knowledge_isolation_sha256": "a",
            },
            {
                "purpose": "knowledge_preparation_isolation",
                "input_mode": "preserve_draft",
                "authority_source": "organization_engineering_policy",
                "continuation_mode": "resume",
                "knowledge_isolation_sha256": "a",
            },
        ),
        (
            "ExecuteExecutionBaselineIntent",
            {
                "confirm_current_knowledge_execution_isolated": True,
                "continuation_mode": "pause",
            },
            {
                "confirm_current_knowledge_execution_isolated": True,
                "continuation_mode": "resume",
            },
        ),
        (
            "BaselineExecutionReservation",
            {
                "retry_cause": "completed_output_unavailable",
                "original_run_id": "run_original",
                "current_invocation_start_sha256": "a",
                "current_invocation_outcome_sha256": "b",
                "completed_output_sha256": "c",
                "reservation_already_applied": False,
            },
            {
                "retry_cause": "completed_output_unavailable",
                "original_run_id": "run_original",
                "current_invocation_start_sha256": "a",
                "current_invocation_outcome_sha256": "b",
                "completed_output_sha256": "c",
                "retry_failure": {},
            },
        ),
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


def test_regeneration_preserves_target_free_completed_output_command_gate(
    regenerated: dict[str, Any],
) -> None:
    from tests.manager.test_completed_output_rescue import public_input

    check = Draft202012Validator(
        {"$defs": regenerated["$defs"], "$ref": "#/$defs/ProposeExecutionBaselineIntent"}
    )
    wire = public_input()
    assert check.is_valid(wire)
    assert not check.is_valid({**wire, "target_base_ref": "e" * 40})
    assert not check.is_valid({**wire, "input_mode": "coder_reapply"})
    assert not check.is_valid({**wire, "purpose": "source_rebind"})
    assert check.is_valid({**wire, "purpose": "source_rebind", "target_base_ref": "e" * 40})


@pytest.mark.parametrize(
    ("model", "valid", "bad"),
    [
        (
            "ExecutionBaselinePlan",
            {
                "purpose": "completed_output_rescue",
                "input_mode": "preserve_draft",
                "conflicted": False,
                "facts": {"completed_output": {}},
            },
            {"facts": {"completed_output": None}},
        ),
        (
            "ExecutionBaselineBinding",
            {
                "purpose": "completed_output_rescue",
                "input_mode": "preserve_draft",
                "continuation_mode": "pause",
                "authority_source": "engineering_operator_decision",
                "completed_output_sha256": "a",
            },
            {"continuation_mode": "resume"},
        ),
    ],
)
def test_regeneration_keeps_distinct_completed_output_purpose_guards(
    regenerated: dict[str, Any],
    model: str,
    valid: dict[str, Any],
    bad: dict[str, Any],
) -> None:
    check = Draft202012Validator({"allOf": regenerated["$defs"][model]["allOf"]})
    assert check.is_valid(valid)
    assert not check.is_valid({**valid, **bad})


@pytest.mark.parametrize("generated", [False, True])
def test_every_published_and_fresh_embedded_binding_enforces_completed_pause_and_proof(
    standalone_regenerated: dict[str, Any], generated: bool
) -> None:
    documents = (
        standalone_regenerated
        if generated
        else {path.name: json.loads(path.read_text()) for path in (ROOT / "schemas").glob("*.json")}
    )
    matched: list[str] = []
    valid = {
        "purpose": "completed_output_rescue",
        "input_mode": "preserve_draft",
        "continuation_mode": "pause",
        "authority_source": "engineering_operator_decision",
        "completed_output_sha256": "a",
    }
    invalid = [
        {**valid, "continuation_mode": "resume"},
        {key: value for key, value in valid.items() if key != "completed_output_sha256"},
        {**valid, "input_mode": "coder_reapply"},
        {**valid, "authority_source": "organization_engineering_policy"},
        {**valid, "purpose": "stopped_provider_retry"},
    ]
    for filename, document in documents.items():
        binding = (
            document
            if document.get("title") == "ExecutionBaselineBinding"
            else document.get("$defs", {}).get("ExecutionBaselineBinding")
        )
        if binding is None:
            continue
        matched.append(filename)
        guard = Draft202012Validator({"allOf": binding.get("allOf", [])})
        assert guard.is_valid(valid), filename
        for wire in invalid:
            assert not guard.is_valid(wire), (filename, wire)
        # Applying the new purpose guard must retain the old containment gate.
        assert not guard.is_valid(
            {
                "purpose": "legacy_workspace_rescue",
                "input_mode": "coder_reapply",
                "authority_source": "organization_engineering_policy",
            }
        ), filename
    assert "execution-baseline.schema.json" in matched
    assert "execution-baseline-queue-consumption.schema.json" in matched
    assert "execution-baseline-queue-release.schema.json" in matched


@pytest.mark.parametrize("generated", [False, True])
def test_unaccepted_completed_output_reason_and_source_pause_guards_match_all_six_graphs(
    standalone_regenerated: dict[str, Any], generated: bool
) -> None:
    names = (
        "completed-coder-output-unavailable",
        "execution-baseline-plan",
        "execution-baseline",
        "execution-baseline-queue-consumption",
        "execution-baseline-queue-release",
        "console-operation",
    )
    for name in names:
        document = (
            standalone_regenerated[name + ".schema.json"]
            if generated
            else json.loads((ROOT / "schemas" / (name + ".schema.json")).read_text())
        )
        nodes = {**document.get("$defs", {}), document.get("title"): document}
        if "CompletedCoderOutputUnavailableProof" in nodes:
            guards = Draft202012Validator(
                {"allOf": nodes["CompletedCoderOutputUnavailableProof"].get("allOf", [])}
            )
            proof = {
                "outcome": {
                    "start": {"request": {"role": "coder"}},
                    "result": {
                        "status": "FAILED",
                        "error": {"code": "INVALID_OUTPUT", "transient": False},
                    },
                }
            }
            assert guards.is_valid(proof), name
            for code in ("POLICY_VIOLATION", "AUTHENTICATION_ERROR", "TIMEOUT"):
                bad = json.loads(json.dumps(proof))
                bad["outcome"]["result"]["error"]["code"] = code
                assert not guards.is_valid(bad), (name, code)
            bad = json.loads(json.dumps(proof))
            bad["outcome"]["start"]["request"]["role"] = "qa"
            assert not guards.is_valid(bad), name
        if "BaselineExecutionFacts" in nodes:
            guards = Draft202012Validator(
                {"allOf": nodes["BaselineExecutionFacts"].get("allOf", [])}
            )
            for code, cause in (
                ("WORK_INTERRUPTED", "completed_output_unavailable"),
                ("INVALID_OUTPUT", "completed_output_rejected"),
            ):
                facts: dict[str, Any] = {
                    "completed_output": {"outcome": {"result": {"error": {"code": code}}}},
                    "continuation": {"retry_cause": cause},
                }
                assert guards.is_valid(facts), name
                facts["continuation"]["retry_cause"] = (
                    "completed_output_unavailable"
                    if cause == "completed_output_rejected"
                    else "completed_output_rejected"
                )
                assert not guards.is_valid(facts), name
        if "ExecutionBaselineBinding" in nodes:
            guards = Draft202012Validator(
                {"allOf": nodes["ExecutionBaselineBinding"].get("allOf", [])}
            )
            source = {
                "purpose": "source_rebind",
                "completed_output_sha256": "a",
                "continuation_mode": "pause",
                "authority_source": "engineering_operator_decision",
            }
            assert guards.is_valid(source), name
            assert not guards.is_valid({**source, "continuation_mode": "resume"}), name
            assert not guards.is_valid(
                {**source, "authority_source": "organization_engineering_policy"}
            ), name
            assert guards.is_valid(
                {"purpose": "source_rebind", "authority_source": "organization_engineering_policy"}
            ), name
        if "BaselineQueueConsumption" in nodes:
            guards = Draft202012Validator(
                {"allOf": nodes["BaselineQueueConsumption"].get("allOf", [])}
            )
            consume: dict[str, Any] = {
                "plan": {
                    "facts": {
                        "completed_output": {
                            "outcome": {"result": {"error": {"code": "INVALID_OUTPUT"}}}
                        }
                    }
                },
                "binding": {
                    "completed_output_sha256": "a",
                    "continuation_mode": "pause",
                    "authority_source": "engineering_operator_decision",
                },
            }
            assert guards.is_valid(consume), name
            consume["binding"].pop("completed_output_sha256")
            assert not guards.is_valid(consume), name
