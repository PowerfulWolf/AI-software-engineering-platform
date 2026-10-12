"""Synchronize only capacity recovery additions, retaining all historical guards."""

import json
from copy import deepcopy
from pathlib import Path
from typing import cast

from ai_software_engineer.recovery.models import RecoveryPlan

type Schema = dict[str, object]


def _object(value: object) -> Schema:
    if not isinstance(value, dict):
        raise TypeError("Schema node must be an object")
    return cast(Schema, value)


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("Schema node must be an array")
    return cast(list[object], value)


def synchronize(schema: Schema, generated: Schema) -> Schema:
    result = deepcopy(schema)
    definitions = _object(result["$defs"])
    source = _object(definitions["RecoverySource"])
    generated_definitions = _object(generated["$defs"])
    expected = _object(generated_definitions["RecoverySource"])
    for field in ("failed_run_id", "context_capacity_receipt_sha256"):
        _object(source["properties"])[field] = _object(expected["properties"])[field]
    source["required"] = [field for field in _array(source["required"]) if field != "failed_run_id"]
    source_rule = {
        "if": {
            "required": ["context_capacity_receipt_sha256"],
            "properties": {"context_capacity_receipt_sha256": {"type": "string"}},
        },
        "then": {
            "required": ["execution_baseline_sha256", "execution_base_revision"],
            "properties": {
                "failed_run_id": {"type": "null"},
                "execution_baseline_sha256": {"type": "string"},
                "execution_base_revision": {"type": "string"},
            },
        },
        "else": {
            "required": ["failed_run_id"],
            "properties": {"failed_run_id": {"type": "string"}},
        },
    }
    rules = _array(source.setdefault("allOf", []))
    legacy_source_rule = deepcopy(source_rule)
    _object(legacy_source_rule["then"])["properties"] = {"failed_run_id": {"type": "null"}}
    if legacy_source_rule in rules:
        rules.remove(legacy_source_rule)
    if source_rule not in rules:
        rules.append(source_rule)
    plan = _object(definitions["RecoveryPlan"])
    _object(plan["properties"])["context_capacity_input"] = _object(generated["properties"])[
        "context_capacity_input"
    ]
    for name in ("ContextCapacityRecoveryInput", "RetainedExecutionPatch"):
        definitions[name] = generated_definitions[name]
    receipt_rule = {
        "if": {
            "properties": {
                "source": {
                    "required": ["context_capacity_receipt_sha256"],
                    "properties": {"context_capacity_receipt_sha256": {"type": "string"}},
                }
            }
        },
        "then": {
            "required": ["context_capacity_input"],
            "properties": {"context_capacity_input": {"type": "object"}},
        },
        "else": {"properties": {"context_capacity_input": {"type": "null"}}},
    }
    input_rule = {
        "if": {
            "required": ["context_capacity_input"],
            "properties": {"context_capacity_input": {"type": "object"}},
        },
        "then": {
            "required": ["input_mode"],
            "properties": {
                "input_mode": {"const": "coder_reapply"},
                "capture": {"properties": {"patch": {"const": ""}, "files": {"maxItems": 0}}},
                "workspace_snapshot": {"type": "null"},
                "scope_supplement": {"type": "null"},
                "quarantined_paths": {"type": "null"},
            },
        },
    }
    rules = _array(plan.setdefault("allOf", []))
    for rule in (receipt_rule, input_rule):
        if rule not in rules:
            rules.append(rule)
    return result


def main() -> None:
    path = Path(__file__).resolve().parents[1] / "schemas/delivery-recovery.schema.json"
    current = _object(json.loads(path.read_text()))
    updated = synchronize(current, RecoveryPlan.model_json_schema())
    if updated != current:
        path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
