"""Provider-safe JSON Schema normalization for strict structured output."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast


def strict_output_schema(schema: Mapping[str, object]) -> dict[str, object]:
    """Copy a schema and require every declared object property recursively.

    OpenAI strict structured output requires all keys in each ``properties`` object to also
    appear in ``required`` and requires ``additionalProperties=false``. Pydantic deliberately
    omits defaulted fields from ``required``, so its schema cannot be passed through unchanged.
    The domain model still supplies defaults when older/non-strict providers omit such fields.
    """
    normalized = _normalize(schema)
    if not isinstance(normalized, dict):  # pragma: no cover - Mapping always normalizes to dict
        raise TypeError("JSON Schema root must be an object")
    return cast(dict[str, object], normalized)


def _normalize(value: object) -> object:
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {
            str(key): _normalize(item) for key, item in value.items() if key != "default"
        }
        properties = normalized.get("properties")
        if isinstance(properties, dict):
            normalized["required"] = list(properties)
            normalized["additionalProperties"] = False
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize(item) for item in value]
    return value


__all__ = ["strict_output_schema"]
