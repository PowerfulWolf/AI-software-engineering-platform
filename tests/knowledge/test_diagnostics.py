"""Manager error summaries expose only fixed knowledge codes, never input text."""

import pytest

from ai_software_engineer.knowledge.models import KnowledgeError
from ai_software_engineer.manager.delivery import DeliveryBackendFailure
from ai_software_engineer.manager.production_backend import ProductionProjectDeliveryBackend


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("LEGACY_KNOWLEDGE_SCOPE_CHANGED", "LEGACY_KNOWLEDGE_SCOPE_CHANGED"),
        ("RECORD_CONFLICT", "RECORD_CONFLICT"),
        ("RESUME_REQUIRES_NEW_RUN_CONTEXT", "RESUME_REQUIRES_NEW_RUN_CONTEXT"),
        ("private credential value must not appear", "KNOWLEDGE_UNCLASSIFIED"),
    ],
)
def test_manager_preserves_fixed_knowledge_code_only(message: str, expected: str) -> None:
    def fail() -> None:
        raise KnowledgeError(message)

    with pytest.raises(DeliveryBackendFailure) as raised:
        ProductionProjectDeliveryBackend._guard("Delivery", fail)
    assert expected in raised.value.safe_summary
    assert "private credential" not in raised.value.safe_summary
