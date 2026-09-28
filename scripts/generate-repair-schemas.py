"""Regenerate wire contracts changed by the explicit prerequisite repair gate."""

import json
from itertools import combinations
from pathlib import Path

from pydantic import TypeAdapter

from ai_software_engineer.manager.dispatch import ContinuationDispatchRecord, RecoveryDispatchRecord
from ai_software_engineer.recovery.records import RecoveryInvocationRecord, RecoverySeedRecord
from ai_software_engineer.web_console.models import ConsoleOperation

root = Path(__file__).resolve().parents[1] / "schemas"
schemas = {
    "console-operation": ConsoleOperation.model_json_schema(),
    "recovery-execution": TypeAdapter(
        RecoveryDispatchRecord
        | ContinuationDispatchRecord
        | RecoverySeedRecord
        | RecoveryInvocationRecord
    ).json_schema(),
}
# Pydantic validators are not emitted by model_json_schema. Preserve the wire
# constraints instead of silently erasing them whenever a new field is added.
console = schemas["console-operation"]
definitions = console["$defs"]
for name in ("CreateRequirementIntent", "UpdateRequirementIntent"):
    roots = definitions[name]["properties"]["repository_roots"]
    roots["uniqueItems"] = True
    roots["items"]["pattern"] = r"^/(?!.*(?:^|/)\.\.(?:/|$))[^\u0000-\u001f]*$"
reply = definitions["ProductReplyIntent"]
reply["properties"]["screenshot_ids"]["uniqueItems"] = True
reply["anyOf"] = [
    {"required": ["message"], "properties": {"message": {"pattern": r"\S"}}},
    {"required": ["screenshot_ids"], "properties": {"screenshot_ids": {"minItems": 1}}},
]
approval_fields = (
    "approved_plan_sha256",
    "approved_scope_sha256",
    "approved_repair_sha256",
    "prerequisite_repair",
    "native_ui_scenario",
)
definitions["ContinueDeliveryIntent"]["allOf"] = [
    {
        "not": {
            "required": [left, right],
            "properties": {
                left: {"not": {"type": "null"}},
                right: {"not": {"type": "null"}},
            },
        }
    }
    for left, right in combinations(approval_fields, 2)
]
definitions["ConsoleCommandResult"]["oneOf"] = [
    {
        "required": ["delivery_id", "checkpoint_sha256"],
        "properties": {
            "delivery_id": {"type": "string"},
            "checkpoint_sha256": {"type": "string"},
        },
    },
    {
        "properties": {
            "delivery_id": {"type": "null"},
            "checkpoint_sha256": {"type": "null"},
            "approval": {"type": "null"},
        }
    },
]
console["allOf"] = [
    {
        "if": {"properties": {"sequence": {"const": 1}}},
        "then": {
            "properties": {
                "status": {"const": "QUEUED"},
                "previous_operation_sha256": {"type": "null"},
            }
        },
        "else": {
            "required": ["previous_operation_sha256"],
            "properties": {"previous_operation_sha256": {"type": "string"}},
        },
    },
    {
        "if": {"properties": {"status": {"enum": ["QUEUED", "RUNNING"]}}},
        "then": {
            "properties": {
                key: {"type": "null"} for key in ("result", "error_code", "error_summary")
            }
        },
    },
    {
        "if": {"properties": {"status": {"const": "SUCCEEDED"}}},
        "then": {
            "required": ["result"],
            "properties": {
                "result": {"type": "object"},
                "error_code": {"type": "null"},
                "error_summary": {"type": "null"},
            },
        },
    },
    {
        "if": {"properties": {"status": {"enum": ["FAILED", "INTERRUPTED"]}}},
        "then": {
            "required": ["error_code", "error_summary"],
            "properties": {
                "result": {"type": "null"},
                "error_code": {"type": "string"},
                "error_summary": {"type": "string"},
            },
        },
    },
]
for name, schema in schemas.items():
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://ai-software-engineer.local/schemas/{name}.schema.json"
    (root / f"{name}.schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
