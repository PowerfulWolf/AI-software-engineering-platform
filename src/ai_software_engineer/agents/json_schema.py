"""Provider-safe JSON Schema normalization for strict structured output."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from ai_software_engineer.domain.artifact import SUPPORTED_ARTIFACT_SCHEMA_VERSION


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


def bind_coder_progress_sequence(schema: dict[str, object], *, attempt: int) -> None:
    """Bind a freshly generated Coder transport schema to its exact current attempt."""
    if type(attempt) is not int or attempt < 1:
        raise ValueError("Coder progress schema requires a positive exact attempt")
    definitions = cast(dict[str, object], schema["$defs"])
    content = cast(dict[str, object], definitions["CoderProgressContent"])
    properties = cast(dict[str, object], content["properties"])
    sequence = cast(dict[str, object], properties["checkpoint_sequence"])
    sequence["const"] = attempt


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


__all__ = ["bind_artifact_schema_version", "bind_coder_progress_sequence", "strict_output_schema"]


def bind_artifact_schema_version(schema: dict[str, object]) -> None:
    """Constrain generated live transport schemas, leaving historical models unchanged."""

    def bind(value: object) -> None:
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict) and "schema_version" in properties:
                properties["schema_version"] = {
                    "type": "string",
                    "const": SUPPORTED_ARTIFACT_SCHEMA_VERSION,
                }
            for child in value.values():
                bind(child)
        elif isinstance(value, list):
            for child in value:
                bind(child)

    bind(schema)
