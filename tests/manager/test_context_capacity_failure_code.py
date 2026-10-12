"""Capacity rejection stays distinct through Requirement checkpoint persistence."""

import json
from pathlib import Path

from ai_software_engineer.manager.delivery import _blocked_failure_code
from ai_software_engineer.manager.delivery_checkpoint import DeliveryFailureCode
from ai_software_engineer.orchestration import BlockedResult, RetryClassification
from tests.domain.factories import make_task


def test_context_capacity_does_not_become_retry_budget_exhaustion() -> None:
    result = BlockedResult(
        task=make_task(),
        classification=RetryClassification.CONTEXT_CAPACITY,
        reason="当前角色输入容量不足，模型未启动。",  # noqa: RUF001
        attempt=1,
        artifact_ids=(),
        event_ids=(),
    )
    assert _blocked_failure_code(result) is DeliveryFailureCode.CONTEXT_CAPACITY
    exhausted = result.model_copy(update={"classification": RetryClassification.BUDGET_EXHAUSTED})
    assert _blocked_failure_code(exhausted) is DeliveryFailureCode.RETRY_BUDGET_EXHAUSTED


def test_every_embedded_failure_code_schema_keeps_capacity_separate() -> None:
    expected = [value.value for value in DeliveryFailureCode]
    for path in Path("schemas").glob("*.schema.json"):
        schema = json.loads(path.read_text())
        embedded = schema.get("$defs", {}).get("DeliveryFailureCode")
        if embedded is not None:
            assert embedded["enum"] == expected, path
