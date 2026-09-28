"""Synchronize additive branch fields without erasing handwritten wire constraints."""

import json
from pathlib import Path

from ai_software_engineer.domain.project_delivery import ProductSpec
from ai_software_engineer.domain.task import Task
from ai_software_engineer.manager.production_agents import ProductDraft
from ai_software_engineer.recovery.models import CapturedChanges, RecoveryPlan

fields = {
    model.__name__: (model.model_json_schema(), field)
    for model, field in (
        (Task, "branch_name"),
        (ProductSpec, "branch_name"),
        (ProductDraft, "branch_name"),
        (CapturedChanges, "branch_name"),
        (RecoveryPlan, "target_branch_name"),
    )
}
root_models = {"task.schema.json": "Task", "product-spec.schema.json": "ProductSpec"}
for path in sorted((Path(__file__).resolve().parents[1] / "schemas").glob("*.schema.json")):
    schema = json.loads(path.read_text())
    before = json.dumps(schema)
    for name, (expected, field) in fields.items():
        for node in (
            schema.get("$defs", {}).get(name),
            schema if root_models.get(path.name) == name or schema.get("title") == name else None,
        ):
            if node is not None and "properties" in node:
                node["properties"][field] = expected["properties"][field]
    if json.dumps(schema) != before:
        path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")
