"""Regenerate only the independent Team current-summary and exact-detail contracts."""

import json
from pathlib import Path

from pydantic import TypeAdapter

from ai_software_engineer.team_view.read_models import TeamDetail, TeamDetailQuery, TeamSummary


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "schemas"
    for name, schema in (
        ("team-summary", TeamSummary.model_json_schema()),
        ("team-detail", TypeAdapter(TeamDetail).json_schema()),
        ("team-detail-query", TeamDetailQuery.model_json_schema()),
    ):
        schema["$id"] = f"https://ai-software-engineer.local/schemas/{name}.schema.json"
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        (root / f"{name}.schema.json").write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
