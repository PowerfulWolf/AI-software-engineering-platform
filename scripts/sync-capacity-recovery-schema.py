"""Synchronize only capacity recovery additions, retaining all historical guards."""

import json
from copy import deepcopy
from pathlib import Path
from typing import cast

from ai_software_engineer.recovery.models import RecoveryPlan, RecoverySource

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
    for field in (
        "failed_run_id",
        "failed_context_id",
        "historical_progress_run_id",
        "historical_progress_context_id",
        "context_capacity_receipt_sha256",
        "route_transition_settlement_sha256",
    ):
        _object(source["properties"])[field] = _object(expected["properties"])[field]
    source["required"] = [
        field
        for field in _array(source["required"])
        if field not in {"failed_run_id", "failed_context_id"}
    ]
    source_rule = {
        "if": {
            "required": ["context_capacity_receipt_sha256"],
            "properties": {"context_capacity_receipt_sha256": {"type": "string"}},
        },
        "then": {
            "required": [
                "failed_context_id",
                "execution_baseline_sha256",
                "execution_base_revision",
            ],
            "properties": {
                "failed_run_id": {"type": "null"},
                "failed_context_id": {"type": "string"},
                "historical_progress_context_id": {"type": "null"},
                "historical_progress_run_id": {"type": "null"},
                "execution_baseline_sha256": {"type": "string"},
                "execution_base_revision": {"type": "string"},
            },
        },
        "else": {
            "if": {
                "required": ["route_transition_settlement_sha256"],
                "properties": {"route_transition_settlement_sha256": {"type": "string"}},
            },
            "then": {
                "required": [
                    "historical_progress_run_id",
                    "historical_progress_context_id",
                    "execution_baseline_sha256",
                    "execution_base_revision",
                ],
                "properties": {
                    "failed_run_id": {"type": "null"},
                    "failed_context_id": {"type": "null"},
                    "historical_progress_context_id": {"type": "string"},
                    "historical_progress_run_id": {"type": "string"},
                    "context_capacity_receipt_sha256": {"type": "null"},
                    "stopped_unknown_settlement_sha256": {"type": "null"},
                    "contained_unknown_settlement_sha256": {"type": "null"},
                },
            },
            "else": {
                "required": ["failed_run_id", "failed_context_id"],
                "properties": {
                    "failed_run_id": {"type": "string"},
                    "failed_context_id": {"type": "string"},
                    "historical_progress_context_id": {"type": "null"},
                    "historical_progress_run_id": {"type": "null"},
                },
            },
        },
    }
    rules = _array(source.setdefault("allOf", []))
    # This generator owns the exclusive source-kind guard; replacing its older
    # variants keeps regeneration idempotent without weakening unrelated rules.
    owned = [
        index
        for index, rule in enumerate(rules)
        if isinstance(rule, dict)
        and isinstance(rule.get("if"), dict)
        and "context_capacity_receipt_sha256" in rule["if"].get("required", [])
        and isinstance(rule.get("else"), dict)
    ]
    if owned:
        rules[owned[0]] = source_rule
        for index in reversed(owned[1:]):
            del rules[index]
    else:
        rules.append(source_rule)
    for rule in _array(RecoverySource.model_json_schema().get("allOf", [])):
        if rule not in rules:
            rules.append(deepcopy(rule))
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
    for rule in _array(generated.get("allOf", [])):
        if rule not in rules:
            rules.append(deepcopy(rule))
    return result


def main() -> None:
    path = Path(__file__).resolve().parents[1] / "schemas/delivery-recovery.schema.json"
    current = _object(json.loads(path.read_text()))
    updated = synchronize(current, RecoveryPlan.model_json_schema())
    if updated != current:
        path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
