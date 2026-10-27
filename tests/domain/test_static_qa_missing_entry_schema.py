"""Published wait schemas retain the exact static QA decision guards."""

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from shutil import copy2, copytree
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from ai_software_engineer.domain.delivery_resolution import DeliveryResolution
from tests.domain.test_delivery_resolution_schema import _wire

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


def _static_decision() -> dict[str, Any]:
    wire = _wire("RESUME_UNINVOKED")
    wire["resolution_kind"] = "STATIC_QA_MISSING_ENTRY"
    wire["verifier_preparation"] = {
        "candidate_revision": "c" * 40,
        "preparation_checkpoint_sha256": "a" * 64,
        "previous_run_id": "run_schema",
        "previous_context_manifest_id": "ctx_" + "b" * 64,
        "request_sha256": "d" * 64,
        "native_execution_state": "NOT_STARTED",
        "prerequisite_facts_sha256": "e" * 64,
    }
    wire["static_qa_missing_entry"] = {
        "candidate_revision": "c" * 40,
        "observation_sha256": "f" * 64,
        "plan_artifact_id": "art_plan_schema",
        "plan_artifact_sha256": "a" * 64,
        "implementation_artifact_id": "art_impl_schema",
        "implementation_artifact_sha256": "b" * 64,
        "preparation_checkpoint_sha256": "a" * 64,
        "original_lease_id": "lease_original_schema",
        "wait_lease_id": "lease_wait_schema",
        "original_dispatch_sequence": 0,
        "wait_dispatch_sequence": 1,
        "original_claim_sha256": "c" * 64,
        "wait_claim_sha256": "d" * 64,
        "previous_run_id": "run_schema",
        "previous_context_manifest_id": "ctx_" + "b" * 64,
        "prerequisite_facts_sha256": "e" * 64,
    }
    return dict(DeliveryResolution.model_validate(wire).to_wire())


@pytest.mark.parametrize(
    "filename",
    (
        "engineering-wait-resolution.schema.json",
        "console-operation.schema.json",
        "console-deletion-cleanup.schema.json",
    ),
)
@pytest.mark.parametrize(
    "mutation",
    ("none", "missing_static", "wrong_kind", "missing_preparation", "finished", "policy"),
)
def test_static_decision_schema_roundtrip_and_tamper(filename: str, mutation: str) -> None:
    schema = json.loads((SCHEMAS / filename).read_text(encoding="utf-8"))
    validator = Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": schema["$defs"],
            "$ref": "#/$defs/DeliveryResolution",
        }
    )
    wire = _static_decision()
    validator.validate(wire)
    DeliveryResolution.model_validate(wire)
    if mutation == "none":
        return
    changed = deepcopy(wire)
    if mutation == "missing_static":
        changed.pop("static_qa_missing_entry")
    elif mutation == "wrong_kind":
        changed["resolution_kind"] = "RESUME_UNINVOKED"
    elif mutation == "missing_preparation":
        changed.pop("verifier_preparation")
    elif mutation == "finished":
        changed["verifier_preparation"]["native_execution_state"] = "FINISHED"
    else:
        changed["authorization_source"] = "organization_engineering_policy"
    with pytest.raises(ValidationError):
        DeliveryResolution.model_validate(changed)
    with pytest.raises(SchemaValidationError):
        validator.validate(changed)


def test_deletion_schema_regeneration_preserves_static_qa_guards(tmp_path: Path) -> None:
    root = tmp_path / "regeneration"
    copytree(SCHEMAS, root / "schemas")
    (root / "scripts").mkdir()
    copy2(
        SCHEMAS.parent / "scripts/sync-requirement-purge-schemas.py",
        root / "scripts/sync-requirement-purge-schemas.py",
    )
    copy2(
        SCHEMAS.parent / "scripts/sync-legacy-rescue-schemas.py",
        root / "scripts/sync-legacy-rescue-schemas.py",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(SCHEMAS.parent / "src")
    subprocess.run(
        (sys.executable, str(root / "scripts/sync-requirement-purge-schemas.py")),
        check=True,
        env=environment,
    )
    regenerated_bytes = (root / "schemas/console-deletion-cleanup.schema.json").read_bytes()
    published_bytes = (SCHEMAS / "console-deletion-cleanup.schema.json").read_bytes()
    generated = json.loads(regenerated_bytes)
    published = json.loads(published_bytes)
    assert (
        generated["$defs"]["StaticQaMissingEntryEvidence"]
        == published["$defs"]["StaticQaMissingEntryEvidence"]
    )
    for name in ("DeliveryResolution", "DeliveryWaitInvestigation"):
        assert generated["$defs"][name]["allOf"] == published["$defs"][name]["allOf"]
    rejected = generated["$defs"]["RejectedKnowledgePreparationEvidence"]["properties"]
    assert rejected["role"] == {"const": "coder"}
    assert rejected["carry_history_sha256s"]["uniqueItems"] is True
    assert generated == published
    assert regenerated_bytes == published_bytes
