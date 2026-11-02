"""The published route-transition fact has the same wire contract as its model."""

import json
from pathlib import Path

from ai_software_engineer.recovery.route_transition_claim import RouteTransitionSettlement


def test_route_transition_settlement_schema_matches_model() -> None:
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas/route-transition-settlement.schema.json").read_text()
    )
    expected = RouteTransitionSettlement.model_json_schema()
    expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    expected["$id"] = (
        "https://ai-software-engineer.local/schemas/route-transition-settlement.schema.json"
    )
    assert schema == expected
