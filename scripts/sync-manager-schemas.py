"""Regenerate only the wire contracts affected by bounded Manager coordination."""

import json
from pathlib import Path

from ai_software_engineer.domain.retry_policy import ExecutionRetryPolicy
from ai_software_engineer.manager.model_execution import ManagerContext, ManagerRunRecord
from ai_software_engineer.multi_directory.models import JointCheckpoint
from ai_software_engineer.team_view.models import TeamSnapshot

root = Path(__file__).resolve().parents[1] / "schemas"

for filename, model in (
    ("requirement-checkpoint.schema.json", JointCheckpoint),
    ("team-snapshot.schema.json", TeamSnapshot),
    ("manager-model-run.schema.json", ManagerRunRecord),
    ("manager-model-context.schema.json", ManagerContext),
):
    schema = model.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://ai-software-engineer.local/schemas/{filename}"
    (root / filename).write_text(
        json.dumps(
            schema, ensure_ascii=False, indent=2, sort_keys=filename == "team-snapshot.schema.json"
        )
        + "\n"
    )

path = root / "production-config.schema.json"
config = json.loads(path.read_text())
policy = ExecutionRetryPolicy.model_json_schema()
config["$defs"].update(policy.pop("$defs"))
config["$defs"]["ExecutionRetryPolicy"] = policy
path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
