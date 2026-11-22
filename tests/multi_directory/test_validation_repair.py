"""A schema-invalid upstream reply is repaired once with field errors only."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from ai_software_engineer.multi_directory.service import _validation_repair_instructions


class _Draft(BaseModel):
    action: int
    summary: str


def test_repair_names_fields_and_messages_but_never_submitted_values() -> None:
    try:
        _Draft.model_validate({"action": "PRIVATE-VALUE-123"})
    except ValidationError as error:
        text = _validation_repair_instructions(error)
    assert "action" in text and "summary" in text
    assert "PRIVATE-VALUE-123" not in text
    assert "complete corrected object" in text


def test_transient_backoff_grows_and_observes_service_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    from ai_software_engineer.multi_directory import service
    from ai_software_engineer.service_pause import ServicePauseRequested

    monkeypatch.setattr(service, "_TRANSIENT_BACKOFF_SECONDS", (10, 20, 40))
    now = [0.0]
    monkeypatch.setattr(service.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(service.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    service._transient_backoff(2)
    assert now[0] == 20
    service._transient_backoff(9)
    assert now[0] == 60
    monkeypatch.setattr("ai_software_engineer.service_pause.service_pause_requested", lambda: True)
    with pytest.raises(ServicePauseRequested):
        service._transient_backoff(1)
