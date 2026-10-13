"""Regenerate physical deletion's bounded, body-free wire contracts."""

import json
from pathlib import Path

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
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://ai-software-engineer.local/schemas/" + filename
    (root / filename).write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")
