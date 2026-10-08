"""Regenerate only the private local service lifecycle contracts."""

from __future__ import annotations

import json
from pathlib import Path

from ai_software_engineer.web_console.service_lifecycle import (
    ServiceInstance,
    ServiceShutdownRequest,
    ServiceShutdownResult,
)

ROOT = Path(__file__).resolve().parents[1] / "schemas"

for filename, model in (
    ("console-service-instance.schema.json", ServiceInstance),
    ("console-service-shutdown-request.schema.json", ServiceShutdownRequest),
    ("console-service-shutdown-result.schema.json", ServiceShutdownResult),
):
    schema = model.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://ai-software-engineer.local/schemas/{filename}"
    (ROOT / filename).write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
