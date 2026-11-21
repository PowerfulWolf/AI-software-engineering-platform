"""The verification contract told to Designer/Planner matches the enforced validator."""

from __future__ import annotations

import pytest

from ai_software_engineer.domain.execution_window import (
    PlannedVerificationInspection,
    validate_inspection_levels,
)
from ai_software_engineer.multi_directory.service import _VERIFICATION_RULES

STATED = {
    "document": ("documentation", "document"),
    "source": ("inspection", "source-inspection", "review"),
    "native_ui": ("ui", "native-ui", "ui-inspection"),
}


def _inspection(kind: str) -> PlannedVerificationInspection:
    if kind == "native_ui":
        return PlannedVerificationInspection(kind=kind, checklist=("x",), scenario_sha256="a" * 64)
    return PlannedVerificationInspection(kind=kind, paths=("a.md",), checklist=("x",))


@pytest.mark.parametrize("kind", sorted(STATED))
def test_stated_levels_are_exactly_the_admitted_levels(kind: str) -> None:
    for level in STATED[kind]:
        assert f"'{level}'" in _VERIFICATION_RULES
        validate_inspection_levels(_inspection(kind), (level,))
    for other in {level for levels in STATED.values() for level in levels} - set(STATED[kind]):
        with pytest.raises(ValueError):
            validate_inspection_levels(_inspection(kind), (other,))
    with pytest.raises(ValueError):
        validate_inspection_levels(_inspection(kind), ("unit",))
