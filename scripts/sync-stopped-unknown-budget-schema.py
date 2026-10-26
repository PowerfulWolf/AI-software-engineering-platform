"""Generate the separate UNKNOWN settlement, retaining nested historical guards."""

import json
from collections.abc import Callable
from pathlib import Path
from runpy import run_path
from typing import cast

from ai_software_engineer.domain.stopped_unknown_budget import StoppedUnknownBudgetSettlement


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = StoppedUnknownBudgetSettlement.model_json_schema()
    legacy_guards = cast(
        Callable[[dict[str, object]], None],
        run_path(str(root / "scripts/sync-legacy-rescue-schemas.py"))["guards"],
    )
    for node in (schema, *schema.get("$defs", {}).values()):
        legacy_guards(node)
    # The investigation's published policy includes guards that cannot be
    # inferred from a generic Pydantic after-validator. Reuse their canonical
    # graph exactly as the repair generator does.
    engineering = json.loads((root / "schemas/engineering-wait-resolution.schema.json").read_text())
    schema["$defs"]["DeliveryWaitInvestigation"]["allOf"] = engineering["$defs"][
        "DeliveryWaitInvestigation"
    ]["allOf"]
    name = "stopped-unknown-budget-settlement.schema.json"
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://ai-software-engineer.local/schemas/" + name
    (root / "schemas" / name).write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
