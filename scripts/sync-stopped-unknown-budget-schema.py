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
    # This v1 stopped-proof schema is a historical published contract. The
    # positive start-only capability belongs only to the separate contained
    # settlement, so a fresh regeneration must keep the old bytes unchanged.
    investigation = schema["$defs"]["DeliveryWaitInvestigation"]
    investigation["properties"].pop("local_stop_confirmation_available", None)
    static_qa_property = investigation["properties"].pop("static_qa_missing_entry")
    investigation["properties"]["static_qa_missing_entry"] = static_qa_property
    guards = [
        guard
        for guard in engineering["$defs"]["DeliveryWaitInvestigation"]["allOf"]
        if guard.get("if", {}).get("properties", {}).get("local_stop_confirmation_available")
        != {"const": True}
    ]
    static_guards = [guard for guard in guards if "STATIC_QA_MISSING_ENTRY" in json.dumps(guard)]
    if len(static_guards) != 2:
        raise RuntimeError("historical static QA guards are incomplete")
    investigation["allOf"] = [
        guard for guard in guards if guard not in static_guards
    ] + static_guards
    name = "stopped-unknown-budget-settlement.schema.json"
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://ai-software-engineer.local/schemas/" + name
    destination = root / "schemas" / name
    if destination.exists():
        if json.loads(destination.read_text()) != schema:
            raise RuntimeError("historical v1 schema differs from generated contract")
        return
    destination.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
