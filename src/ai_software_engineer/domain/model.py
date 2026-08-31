"""Shared primitives for strict domain models and JSON wire payloads."""

from collections.abc import Hashable, Iterable
from typing import Annotated, cast

from pydantic import BaseModel, ConfigDict, StringConstraints

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
type WirePayload = dict[str, JsonValue]

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]


class DomainModel(BaseModel):
    """Immutable model that rejects fields outside the declared contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    def to_wire(self) -> WirePayload:
        """Return canonical JSON data and omit absent optional properties."""
        return cast(WirePayload, self.model_dump(mode="json", exclude_none=True))


def ensure_unique[HashableT: Hashable](values: Iterable[HashableT], label: str) -> None:
    """Reject duplicate identifiers while retaining stable input ordering."""
    seen: set[HashableT] = set()
    duplicates: set[HashableT] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        rendered = ", ".join(sorted(str(value) for value in duplicates))
        raise ValueError(f"{label} must be unique; duplicates: {rendered}")


def ensure_known_references(
    references: Iterable[str], available: Iterable[str], label: str = "references"
) -> None:
    """Reject references that cannot be resolved inside the current aggregate."""
    unknown = sorted(set(references) - set(available))
    if unknown:
        raise ValueError(f"{label} contain unknown Evidence IDs: {', '.join(unknown)}")
