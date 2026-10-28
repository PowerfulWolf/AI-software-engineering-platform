"""Regenerate the immutable engineering recovery-input schedule contract."""

import json
from pathlib import Path

from ai_software_engineer.manager.recovery_input_schedule import RecoveryInputScheduleDecision

schema = RecoveryInputScheduleDecision.model_json_schema()
schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
schema["$id"] = "https://ai-software-engineer.local/schemas/recovery-input-schedule.schema.json"
target = Path(__file__).resolve().parents[1] / "schemas/recovery-input-schedule.schema.json"
target.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
