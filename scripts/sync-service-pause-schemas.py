"""Synchronize additive pause fields while preserving enclosing handwritten guards."""

import json
from pathlib import Path
from runpy import run_path

from ai_software_engineer.agents.execution import PausedInvocationProof, SynchronousToolLoopStop
from ai_software_engineer.agents.structured_observation import StructuredNativeNotStartedReceipt
from ai_software_engineer.domain.delivery_disposition import DeliveryFailureFacts
from ai_software_engineer.domain.delivery_resolution import (
    DeliveryResolution,
    DeliveryWaitInvestigation,
)
from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
from ai_software_engineer.domain.native_verification import NativeVerificationWaitReason
from ai_software_engineer.evidence.models import CommandOutcome
from ai_software_engineer.manager.baseline_models import BaselineExecutionReservation
from ai_software_engineer.recovery.verification_records import VerificationExecutionRecord
from ai_software_engineer.service_pause import PausedProcessReceipt
from ai_software_engineer.work_queue.invocation import DeliveryInvocationOutcome

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
MODELS = (
    SynchronousToolLoopStop,
    StructuredNativeNotStartedReceipt,
    DeliveryFailureFacts,
    BaselineExecutionReservation,
)
FIELDS = ("kind", "failure_kind", "classification", "retry_cause")


def main() -> None:
    legacy_guards = run_path(str(Path(__file__).with_name("sync-legacy-rescue-schemas.py")))[
        "guards"
    ]
    for path in sorted(SCHEMAS.glob("*.schema.json")):
        schema = json.loads(path.read_text())
        before = json.dumps(schema)
        for model, field in zip(MODELS, FIELDS, strict=True):
            node = schema.get("$defs", {}).get(model.__name__)
            if node is not None:
                node["properties"][field] = model.model_json_schema()["properties"][field]
        definitions = schema.setdefault("$defs", {})
        for model, field in (
            (ExecutionBaselineBinding, "service_pause_outcome_sha256"),
            (DeliveryInvocationOutcome, "service_pause"),
            (DeliveryWaitInvestigation, "verifier_pause"),
            (DeliveryWaitInvestigation, "retry_cause"),
            (DeliveryResolution, "retry_cause"),
            (DeliveryResolution, "verifier_pause"),
            (VerificationExecutionRecord, "failure_code"),
        ):
            node = (
                schema if schema.get("title") == model.__name__ else definitions.get(model.__name__)
            )
            if node is not None:
                generated = model.model_json_schema()
                node["properties"][field] = generated["properties"][field]
                for name, definition in generated.get("$defs", {}).items():
                    definitions.setdefault(name, definition)
        if "PausedInvocationProof" in definitions:
            proof = PausedInvocationProof.model_json_schema()
            nested = proof.pop("$defs")
            definitions["PausedInvocationProof"] = proof
            for name, definition in nested.items():
                definitions.setdefault(name, definition)
        if "NativeVerificationWaitReason" in definitions:
            definitions["NativeVerificationWaitReason"]["enum"] = [
                item.value for item in NativeVerificationWaitReason
            ]
        for definition in definitions.values():
            legacy_guards(definition)
        if "CommandOutcome" in definitions:
            definitions["CommandOutcome"]["enum"] = [item.value for item in CommandOutcome]
        if "DeliveryResolution" in definitions:
            guard = {
                "if": {
                    "required": ["retry_cause"],
                    "properties": {"retry_cause": {"const": "service_pause"}},
                },
                "then": {
                    "required": ["verifier_pause"],
                    "properties": {
                        "verifier_pause": {
                            "type": "object",
                            "properties": {
                                "request": {"properties": {"role": {"enum": ["qa", "reviewer"]}}}
                            },
                        }
                    },
                },
                "else": {"properties": {"verifier_pause": {"type": "null"}}},
            }
            if guard not in definitions["DeliveryResolution"].setdefault("allOf", []):
                definitions["DeliveryResolution"]["allOf"].append(guard)
        failure = schema.get("$defs", {}).get("AgentFailure")
        if failure is not None:
            guard = {
                "if": {"required": ["code"], "properties": {"code": {"const": "SERVICE_PAUSED"}}},
                "then": {"properties": {"transient": {"const": False}}},
            }
            if guard not in failure.setdefault("allOf", []):
                failure["allOf"].append(guard)
        if not definitions:
            schema.pop("$defs", None)
        if json.dumps(schema) != before:
            path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")
    schema = PausedProcessReceipt.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://ai-software-engineer.local/schemas/service-pause-stop.schema.json"
    schema["properties"]["process_stop"] = {
        "allOf": [
            schema["properties"]["process_stop"],
            {"properties": {"kind": {"const": "service_pause"}}},
        ]
    }
    (SCHEMAS / "service-pause-stop.schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
