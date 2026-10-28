"""Regenerate physical deletion's bounded, body-free wire contracts."""

import json
from collections.abc import Callable
from pathlib import Path
from runpy import run_path
from typing import cast

from ai_software_engineer.multi_directory.purge import (
    RequirementPurgeCompletion,
    RequirementPurgePlan,
)
from ai_software_engineer.web_console.deletion_cleanup import ConsoleDeletionCleanup

root = Path(__file__).resolve().parents[1] / "schemas"
for filename, model in (
    ("console-deletion-cleanup.schema.json", ConsoleDeletionCleanup),
    ("requirement-purge-plan.schema.json", RequirementPurgePlan),
    ("requirement-purge-completion.schema.json", RequirementPurgeCompletion),
):
    schema = model.model_json_schema()
    if filename == "console-deletion-cleanup.schema.json":
        guards = cast(
            Callable[[dict[str, object]], None],
            run_path(str(root.parent / "scripts/sync-legacy-rescue-schemas.py"))["guards"],
        )
        for node in (schema, *schema.get("$defs", {}).values()):
            guards(node)
        engineering = json.loads(
            (root / "engineering-wait-resolution.schema.json").read_text(encoding="utf-8")
        )
        for name in ("DeliveryResolution", "DeliveryWaitInvestigation", "DeliveryWaitHandling"):
            schema["$defs"][name]["allOf"] = engineering["$defs"][name]["allOf"]
        console = json.loads((root / "console-operation.schema.json").read_text(encoding="utf-8"))
        handle = console["$defs"]["HandleDeliveryWaitIntent"]
        if "confirm_local_execution_stopped" not in handle["properties"] or not handle.get("allOf"):
            raise RuntimeError("canonical local-stop HANDLE guard is not published")
        schema["$defs"]["HandleDeliveryWaitIntent"]["allOf"] = handle["allOf"]
        schema["$defs"]["RejectedKnowledgePreparationEvidence"] = engineering["$defs"][
            "RejectedKnowledgePreparationEvidence"
        ]
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://ai-software-engineer.local/schemas/" + filename
    target = root / filename
    if target.exists() and json.loads(target.read_text(encoding="utf-8")) == schema:
        continue
    target.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")
