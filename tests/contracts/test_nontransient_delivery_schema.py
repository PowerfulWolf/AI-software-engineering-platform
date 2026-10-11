"""Every published copy preserves the same failure taxonomy and old wire shape."""

import json
from pathlib import Path

from ai_software_engineer.domain.delivery_disposition import DeliveryFailureFacts


def test_all_embedded_failure_fact_classifications_match_current_contract() -> None:
    expected = DeliveryFailureFacts.model_json_schema()["properties"]["classification"]
    found = 0
    for path in Path("schemas").glob("*.schema.json"):
        schema = json.loads(path.read_text())
        facts = schema.get("$defs", {}).get("DeliveryFailureFacts")
        if schema.get("title") == "DeliveryFailureFacts":
            facts = schema
        if facts is not None:
            found += 1
            assert facts["properties"]["classification"] == expected, path.name
    assert found >= 15
