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
    if static_rules[-1] == generated_rules[-1]:
        static_rules[-2] = generated_rules[-2]
    else:
        previous = cast(dict[str, object], static_rules[-1])
        previous_if = cast(dict[str, object], previous["if"])
        previous_properties = cast(dict[str, object], previous_if["properties"])
        snapshot = cast(dict[str, object], previous_properties["workspace_snapshot"])
        completion = cast(
            dict[str, object], cast(dict[str, object], snapshot["properties"])["completion_kind"]
        )
        if completion == {"const": "responses_workspace_policy_failure"}:
            static_rules[-2:] = generated_rules[-2:]
        elif completion == {"const": "responses_tool_refusal"}:
            static_rules[-1] = generated_rules[-2]
            static_rules.append(generated_rules[-1])
        else:
            raise ValueError("unexpected recovery workspace Plan guard; refuse schema replacement")
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
