"""Add frozen recovery authority without erasing handwritten wire constraints."""

import json
from copy import deepcopy
from pathlib import Path
from typing import cast

from ai_software_engineer.recovery.models import RecoveryPlan

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "delivery-recovery.schema.json"
FIELD = "target_authorization"
AUTHORIZATION = "RecoveryTargetAuthorization"


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("Schema nodes must be objects")
    return cast(dict[str, object], value)


def _references(value: object) -> set[str]:
    if isinstance(value, dict):
        result = set[str]()
        for key, child in value.items():
            if key == "$ref" and isinstance(child, str):
                if not child.startswith("#/$defs/"):
                    raise ValueError("Recovery authority only supports local Schema references")
                result.add(child.removeprefix("#/$defs/"))
            else:
                result.update(_references(child))
        return result
    if isinstance(value, list):
        return {name for child in value for name in _references(child)}
    return set()


def _retry_binding_rule() -> dict[str, object]:
    return {
        "if": {
            "required": ["source_retry_policy"],
            "properties": {"source_retry_policy": {"type": "object"}},
        },
        "then": {
            "required": ["interruption_continuation_policy"],
            "properties": {
                "interruption_continuation_policy": {
                    "type": "object",
                    "required": ["schema_version"],
                    "properties": {"schema_version": {"const": "v2"}},
                }
            },
        },
        "else": {"properties": {"interruption_continuation_policy": {"type": "null"}}},
    }


def synchronize(schema: dict[str, object], generated: dict[str, object]) -> dict[str, object]:
    """Update the one new field and its dependency graph, retaining existing contracts."""
    result = deepcopy(schema)
    definitions = _object(result["$defs"])
    generated_definitions = _object(generated["$defs"])
    field = _object(generated["properties"])[FIELD]
    _object(_object(definitions["RecoveryPlan"])["properties"])[FIELD] = deepcopy(field)

    pending = _references(field)
    visited = set[str]()
    while pending:
        name = min(pending)
        pending.remove(name)
        if name in visited:
            continue
        visited.add(name)
        node = generated_definitions[name]
        pending.update(_references(node) - visited)
        # Shared definitions can carry handwritten restrictions. This narrow
        # migration owns only the new authorization node and never regenerates
        # RecoveryPlan or any pre-existing shared definition.
        if name == AUTHORIZATION:
            previous = _object(definitions.get(name, {}))
            authority = deepcopy(_object(node))
            rules = cast(list[object], deepcopy(previous.get("allOf", [])))
            rule = _retry_binding_rule()
            if rule not in rules:
                rules.append(rule)
            authority["allOf"] = rules
            definitions[name] = authority
        elif name not in definitions:
            definitions[name] = deepcopy(node)
    return result


def main() -> None:
    schema = _object(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    result = synchronize(schema, RecoveryPlan.model_json_schema())
    if result != schema:
        SCHEMA_PATH.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
