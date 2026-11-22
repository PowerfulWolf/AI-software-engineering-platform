"""A schema-invalid upstream reply is repaired once with field errors only."""

from __future__ import annotations

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
