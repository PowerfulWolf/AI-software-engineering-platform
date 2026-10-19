"""Trusted pre-provider workspace refusal has its own ordinary-work recovery action."""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryResolutionKind,
    RejectedWorkspaceAdmissionEvidence,
)
from tests.domain.test_delivery_resolution_schema import _wire


def evidence_wire() -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "scope": {
            "team_id": "team_schema",
            "project_id": "project_schema",
            "repository_id": "repository_schema",
            "repository_root": "/tmp/schema",
        },
        "requirement_id": "delivery_schema",
        "task_id": "task_schema",
        "work_item_id": "work_schema",
        "role": "coder",
        "checkpoint_sequence": 4,
        "attempt": 2,
        "dispatch_sequence": 1,
        "lease_id": "lease_schema",
        "claim_sha256": "a" * 64,
        "run_id": "run_schema",
        "context_manifest_id": "ctx_" + "b" * 64,
        "source_revision": "c" * 40,
        "progress_artifact_id": "art_progress_schema",
        "reason": "PRESERVED_PROGRESS_CAPTURE_MISMATCH",
        "budget_source": "frozen_work_attempt",
        "observation_sha256": "0" * 64,
    }
    for key in (
        "invocation_start_sha256",
        "invocation_outcome_sha256",
        "route_attempt_sha256",
        "context_sha256",
        "baseline_binding_sha256",
        "baseline_plan_sha256",
        "progress_sha256",
        "workspace_inventory_sha256",
        "workspace_capture_sha256",
        "adapter_contract_sha256",
    ):
        evidence[key] = "d" * 64
    value = RejectedWorkspaceAdmissionEvidence.model_validate(evidence)
    return dict(value.model_copy(update={"observation_sha256": value.recompute_sha256()}).to_wire())


def resolution_wire() -> dict[str, Any]:
    wire = _wire("RESUME_UNINVOKED")
    wire["resolution_kind"] = "RETRY_REJECTED_WORKSPACE_ADMISSION"
    wire["rejected_workspace_admission"] = evidence_wire()
    return wire


def test_workspace_admission_action_is_distinct_and_preserves_old_wire() -> None:
    kind = DeliveryResolutionKind("RETRY_REJECTED_WORKSPACE_ADMISSION")
    assert kind is not DeliveryResolutionKind.RESUME_UNINVOKED
    old = DeliveryResolution.model_validate(_wire("RESUME_UNINVOKED"))
    assert "rejected_workspace_admission" not in old.to_wire()
    DeliveryResolution.model_validate(resolution_wire())


@pytest.mark.parametrize(
    "mutation", ["missing", "wrong_action", "wrong_budget", "qa", "reviewer", "source"]
)
def test_workspace_admission_resolution_schema_and_domain_reject_mismatches(mutation: str) -> None:
    wire = resolution_wire()
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/engineering-wait-resolution.schema.json").read_text()
    )
    validator = Draft202012Validator(schema)
    validator.validate(wire)
    if mutation == "missing":
        del wire["rejected_workspace_admission"]
    elif mutation == "wrong_action":
        wire["resolution_kind"] = "RESUME_UNINVOKED"
    elif mutation == "wrong_budget":
        wire["rejected_workspace_admission"]["budget_source"] = "provider_refund"
    elif mutation in {"qa", "reviewer"}:
        wire["rejected_workspace_admission"]["role"] = mutation
    else:
        wire["rejected_workspace_admission"]["source_revision"] = "f" * 40
    with pytest.raises(ValidationError):
        DeliveryResolution.model_validate(wire)
    if mutation != "source":
        with pytest.raises(SchemaValidationError):
            validator.validate(wire)


def test_observation_digest_is_independently_checked() -> None:
    wire = evidence_wire()
    evidence = RejectedWorkspaceAdmissionEvidence.model_validate(wire)
    evidence.validate_integrity()
    wire["workspace_inventory_sha256"] = "e" * 64
    with pytest.raises(ValueError):
        RejectedWorkspaceAdmissionEvidence.model_validate(wire).validate_integrity()


def test_workspace_adapter_declaration_standalone_and_all_console_embeddings_are_current() -> None:
    from ai_software_engineer.domain.workspace_admission_contract import (
        WorkspaceAdmissionAdapterContractRecord,
    )
    from ai_software_engineer.web_console.models import HandleDeliveryWaitIntent

    schemas = Path(__file__).parents[2] / "schemas"
    standalone = json.loads(
        (schemas / "workspace-admission-adapter-contract.schema.json").read_text()
    )
    assert standalone.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert standalone.pop("$id").endswith("/workspace-admission-adapter-contract.schema.json")
    assert standalone == WorkspaceAdmissionAdapterContractRecord.model_json_schema()
    handle = HandleDeliveryWaitIntent.model_json_schema()
    expected_defs = handle.pop("$defs")
    for path in schemas.glob("*.schema.json"):
        schema = json.loads(path.read_text())
        definitions = schema.get("$defs", {})
        if "HandleDeliveryWaitIntent" not in definitions:
            continue
        assert definitions["HandleDeliveryWaitIntent"] == handle, path.name
        for name in ("WorkspaceAdmissionAdapterContract", "WorkspaceAdmissionAdapterSource"):
            assert definitions[name] == expected_defs[name], (path.name, name)
