"""Generate the standalone no-start observation wire contract and its guards."""

import json
from pathlib import Path

from ai_software_engineer.manager.context_capacity import ContextCapacityReceipt

schema = ContextCapacityReceipt.model_json_schema()
schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
schema["$id"] = "https://ai-software-engineer.local/schemas/context-capacity-receipt.schema.json"
schema["properties"]["role"]["enum"] = ["coder", "qa", "reviewer"]
schema["allOf"] = [
    {
        "if": {"properties": {"origin": {"const": "final_input"}}, "required": ["origin"]},
        "then": {
            "required": ["request", "final_input_tokens"],
            "properties": {
                "request": {"$ref": "#/$defs/AgentRequest"},
                "final_input_tokens": {"type": "integer", "minimum": 1},
                "legacy_terminal_event_sha256": {"type": "null"},
                "legacy_terminal_source_revision": {"type": "null"},
            },
        },
        "else": {
            "properties": {
                "request": {"type": "null"},
                "final_input_tokens": {"type": "null"},
            },
        },
    },
    {
        "if": {
            "required": ["legacy_terminal_event_sha256"],
            "properties": {"legacy_terminal_event_sha256": {"type": "string"}},
        },
        "then": {
            "required": ["legacy_terminal_source_revision"],
            "properties": {"legacy_terminal_source_revision": {"type": "string"}},
        },
        "else": {"properties": {"legacy_terminal_source_revision": {"type": "null"}}},
    },
]
root = Path(__file__).resolve().parents[1]
(root / "schemas/context-capacity-receipt.schema.json").write_text(
    json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
