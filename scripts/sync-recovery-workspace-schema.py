"""Synchronize terminal snapshot and its inherited-input mode guard."""

import json
from pathlib import Path
from typing import cast

from ai_software_engineer.recovery.models import RecoveryPlan


def main() -> None:
    path = Path(__file__).resolve().parents[1] / "schemas/delivery-recovery.schema.json"
    schema = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
    definitions = cast(dict[str, object], schema["$defs"])
    generated_root = cast(dict[str, object], RecoveryPlan.model_json_schema())
    generated = cast(dict[str, object], generated_root["$defs"])
    definitions["RecoveryWorkspaceSnapshot"] = generated["RecoveryWorkspaceSnapshot"]
    static_plan = cast(dict[str, object], definitions["RecoveryPlan"])
    static_rules = cast(list[object], static_plan["allOf"])
    generated_rules = cast(list[object], generated_root["allOf"])
    rule = generated_rules[-1]
    if rule not in static_rules:
        static_rules.append(rule)
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
