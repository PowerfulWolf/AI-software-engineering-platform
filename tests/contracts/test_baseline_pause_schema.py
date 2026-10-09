"""Published pause and rule-review models have the same additive strict wire shape."""

import json
from pathlib import Path

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
    assert schema == model.model_json_schema()
