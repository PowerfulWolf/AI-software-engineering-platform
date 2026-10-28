"""Generate start-only UNKNOWN settlement without weakening historical nested guards."""

import json
from collections.abc import Callable
from pathlib import Path
from runpy import run_path
from typing import cast

from ai_software_engineer.domain.contained_unknown_budget import ContainedUnknownBudgetSettlement


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = ContainedUnknownBudgetSettlement.model_json_schema()
    legacy_guards = cast(
        Callable[[dict[str, object]], None],
        run_path(str(root / "scripts/sync-legacy-rescue-schemas.py"))["guards"],
    )
    for node in (schema, *schema.get("$defs", {}).values()):
        legacy_guards(node)
    engineering = json.loads(
        (root / "schemas/engineering-wait-resolution.schema.json").read_text(encoding="utf-8")
    )
    schema["$defs"]["DeliveryWaitInvestigation"]["allOf"] = engineering["$defs"][
        "DeliveryWaitInvestigation"
    ]["allOf"]
    schema["allOf"].append(
        {
            "properties": {
                "investigation": {
                    "required": ["local_stop_confirmation_available"],
                    "properties": {"local_stop_confirmation_available": {"const": True}},
                }
            }
        }
    )
    name = "contained-unknown-budget-settlement.schema.json"
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://ai-software-engineer.local/schemas/" + name
    (root / "schemas" / name).write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
