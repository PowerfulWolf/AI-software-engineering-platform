"""Published pause and rule-review models have the same additive strict wire shape."""

import json
from pathlib import Path
from typing import cast

import pytest
from pydantic import BaseModel

from ai_software_engineer.domain.execution_native_rules import (
    NativeRuleChangeInspection,
    NativeRuleEpoch,
)
from ai_software_engineer.manager.baseline_models import BaselineContinueAuthorization
from ai_software_engineer.team_view.models import TeamSnapshot
from ai_software_engineer.work_queue.baseline import BaselineQueueRelease


@pytest.mark.parametrize(
    ("filename", "model"),
    [
        ("baseline-continue-authorization", BaselineContinueAuthorization),
        ("execution-native-rule-epoch", NativeRuleEpoch),
        ("execution-native-rule-change-inspection", NativeRuleChangeInspection),
        ("execution-baseline-queue-release", BaselineQueueRelease),
        ("team-snapshot", TeamSnapshot),
    ],
)
def test_standalone_schema_matches_runtime_wire_shape(
    filename: str, model: type[BaseModel]
) -> None:
    path = Path(__file__).parents[2] / "schemas" / f"{filename}.schema.json"
    schema = json.loads(path.read_text())
    assert schema.pop("$schema") == "https://json-schema.org/draft/2020-12/schema"
    assert schema.pop("$id") == f"https://ai-software-engineer.local/schemas/{filename}.schema.json"
    generated = model.model_json_schema()
    # Cross-field gates are handwritten because Pydantic validators do not emit
    # them. Keep strict generated shape parity while testing those gates in the
    # independent published/fresh-regeneration semantic contract tests.
    generated_definitions = generated.get("$defs", {})
    published_definitions = schema.get("$defs", {})
    assert published_definitions.keys() == generated_definitions.keys()
    node_pairs = [(schema, generated)] + [
        (published_definitions[name], expected) for name, expected in generated_definitions.items()
    ]
    for published, expected in node_pairs:
        if "allOf" not in expected:
            cast(dict[str, object], published).pop("allOf", None)
    assert schema == generated
