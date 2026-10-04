"""Add quarantine policy without removing existing handwritten recovery contracts."""

import json
from pathlib import Path

from ai_software_engineer.recovery.models import RecoveryPlan

expected = RecoveryPlan.model_json_schema()["properties"]["quarantined_paths"]
expected["anyOf"][0]["uniqueItems"] = True
condition = {
    "if": {
        "required": ["quarantined_paths"],
        "properties": {"quarantined_paths": {"type": "array"}},
    },
    "then": {
        "required": ["input_mode"],
        "properties": {"input_mode": {"const": "coder_reapply"}},
    },
}
for path in sorted((Path(__file__).resolve().parents[1] / "schemas").glob("*.schema.json")):
    schema = json.loads(path.read_text())
    before = json.dumps(schema)
    node = schema.get("$defs", {}).get("RecoveryPlan")
    if node is not None:
        node["properties"]["quarantined_paths"] = expected
        rules = node.setdefault("allOf", [])
        if condition not in rules:
            rules.append(condition)
    if json.dumps(schema) != before:
        path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")
