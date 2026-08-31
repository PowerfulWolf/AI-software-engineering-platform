"""StateEvent value-object behavior."""

import pytest

from ai_software_engineer.domain import AgentRole, StateEvent, TaskStatus
from tests.domain.factories import make_state_event


def test_state_event_is_immutable_and_orchestrator_owned() -> None:
    event = make_state_event()

    assert event.actor is AgentRole.ORCHESTRATOR
    assert event.to_status is TaskStatus.PLANNING

    with pytest.raises(ValueError):
        event.reason = "changed"


def test_state_event_rejects_duplicate_artifact_ids() -> None:
    payload = make_state_event().to_wire()
    payload["artifact_ids"] = ["art_plan_001", "art_plan_001"]

    with pytest.raises(ValueError, match="artifact_ids must be unique"):
        StateEvent.model_validate(payload)


def test_state_event_rejects_non_orchestrator_actor() -> None:
    payload = make_state_event().to_wire()
    payload["actor"] = "coder"

    with pytest.raises(ValueError):
        StateEvent.model_validate(payload)
