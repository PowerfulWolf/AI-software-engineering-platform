"""Add the separate UNKNOWN recovery source to all embeddings, retaining guards."""

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


def synchronize(schema: Schema) -> Schema:
    result = deepcopy(schema)
    generated = {
        "RecoverySource": RecoverySource.model_json_schema(),
        "RecoveryPlan": RecoveryPlan.model_json_schema(),
    }
    definitions = _object(result.get("$defs", {}))
    for name, expected in generated.items():
        nodes = []
        if result.get("title") == name:
            nodes.append(result)
        if name in definitions:
            nodes.append(_object(definitions[name]))
        for node in nodes:
            if name == "RecoverySource":
                _object(node["properties"])["stopped_unknown_settlement_sha256"] = deepcopy(
                    _object(expected["properties"])["stopped_unknown_settlement_sha256"]
                )
            rules = _array(node.setdefault("allOf", []))
            for rule in _array(expected["allOf"]):
                if rule not in rules:
                    rules.append(deepcopy(rule))
    return result


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in sorted((root / "schemas").glob("*.json")):
        body = path.read_bytes()
        if b'"RecoverySource"' not in body and b'"RecoveryPlan"' not in body:
            continue
        current = _object(json.loads(body))
        updated = synchronize(current)
        if updated != current:
            path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
