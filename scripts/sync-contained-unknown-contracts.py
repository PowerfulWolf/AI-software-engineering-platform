"""Add the start-only local-stop fields without reordering historical Schema graphs."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ai_software_engineer.domain.delivery_resolution import DeliveryWaitInvestigation
from ai_software_engineer.web_console.models import HandleDeliveryWaitIntent

LOCAL_STOP_GUARD: dict[str, Any] = {
    "if": {
        "required": ["local_stop_confirmation_available"],
        "properties": {"local_stop_confirmation_available": {"const": True}},
    },
    "then": {
        "required": ["original_run_id", "invocation_start_sha256"],
        "properties": {
            "original_run_id": {"type": "string"},
            "invocation_start_sha256": {"type": "string"},
            "invocation_outcome_sha256": {"type": "null"},
            "interruption_receipt_sha256": {"type": "null"},
            "process_stop_sha256": {"type": "null"},
            "permitted_resolutions": {"maxItems": 0},
            "missing": {
                "minItems": 4,
                "maxItems": 4,
                "allOf": [
                    {"contains": {"const": name}}
                    for name in (
                        "OUTCOME_UNKNOWN",
                        "STOP_UNRECORDED",
                        "CHECKPOINT_UNAVAILABLE",
                        "BUDGET_EXHAUSTED",
                    )
                ],
            },
            "disposition": {
                "properties": {
                    "facts": {
                        "properties": {
                            "role": {"const": "coder"},
                            "classification": {"const": "EXECUTION_UNCERTAIN"},
                        }
                    }
                }
            },
        },
    },
}

HANDLE_CONFIRMATION_GUARD: dict[str, Any] = {
    "if": {
        "required": ["confirm_local_execution_stopped"],
        "properties": {"confirm_local_execution_stopped": {"const": True}},
    },
    "then": {
        "required": ["local_stop_reference"],
        "properties": {
            "local_stop_reference": {"type": "string"},
            "workspace_admission_adapter_contract": {"type": "null"},
        },
    },
    "else": {"properties": {"local_stop_reference": {"type": "null"}}},
}


def synchronize(schema: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(schema)
    defs = result["$defs"]
    investigation = defs["DeliveryWaitInvestigation"]
    expected_investigation = DeliveryWaitInvestigation.model_json_schema()
    investigation["properties"]["local_stop_confirmation_available"] = deepcopy(
        expected_investigation["properties"]["local_stop_confirmation_available"]
    )
    investigation.setdefault("allOf", [])
    if LOCAL_STOP_GUARD not in investigation["allOf"]:
        investigation["allOf"].append(deepcopy(LOCAL_STOP_GUARD))
    if "HandleDeliveryWaitIntent" in defs:
        handle = defs["HandleDeliveryWaitIntent"]
        expected_handle = HandleDeliveryWaitIntent.model_json_schema()
        for field in ("confirm_local_execution_stopped", "local_stop_reference"):
            handle["properties"][field] = deepcopy(expected_handle["properties"][field])
        handle.setdefault("allOf", [])
        if HANDLE_CONFIRMATION_GUARD not in handle["allOf"]:
            handle["allOf"].append(deepcopy(HANDLE_CONFIRMATION_GUARD))
    return result


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "schemas"
    for name in (
        "engineering-wait-resolution.schema.json",
        "console-operation.schema.json",
        "console-deletion-cleanup.schema.json",
    ):
        path = root / name
        current = json.loads(path.read_text(encoding="utf-8"))
        updated = synchronize(current)
        if updated != current:
            path.write_text(
                json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )


if __name__ == "__main__":
    main()
