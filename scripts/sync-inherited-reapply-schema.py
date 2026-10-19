"""Synchronize complete inherited inputs without erasing historical wire guards."""

import json
from copy import deepcopy
from pathlib import Path
from typing import cast

from ai_software_engineer.recovery.models import RecoveryPlan


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("Schema node must be an object")
    return cast(dict[str, object], value)


def synchronize(schema: dict[str, object], generated: dict[str, object]) -> dict[str, object]:
    """Own only this additive property and new definition, retaining every other node."""
    result = deepcopy(schema)
    definitions = _object(result["$defs"])
    properties = _object(_object(definitions["RecoveryPlan"])["properties"])
    properties["inherited_reapply_inputs"] = deepcopy(
        _object(generated["properties"])["inherited_reapply_inputs"]
    )
    definitions["InheritedReapplyInput"] = deepcopy(
        _object(generated["$defs"])["InheritedReapplyInput"]
    )
    return result


def main() -> None:
    path = Path(__file__).resolve().parents[1] / "schemas/delivery-recovery.schema.json"
    current = _object(json.loads(path.read_text(encoding="utf-8")))
    updated = synchronize(current, RecoveryPlan.model_json_schema())
    if updated != current:
        path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
