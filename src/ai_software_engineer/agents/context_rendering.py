"""Prompt-only rendering of complete sealed Context sections.

This module never writes Context or evidence. A projection is allowed only when
its JSON values are unambiguous, and omitted retrieval terms are verified as an
exact deterministic derivative of the complete chunk text.
"""

import json
import math
from decimal import Decimal
from typing import Literal, cast

from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.context.models import ContextSection
from ai_software_engineer.domain.model import DomainModel, JsonValue, NonEmptyStr
from ai_software_engineer.knowledge.models import KnowledgeError, KnowledgeEvidence, text_digest
from ai_software_engineer.knowledge.retrieval import terms


class PromptSectionRendering(DomainModel):
    content: JsonValue
    content_format: Literal["json", "knowledge-read-v1"]
    # SHA belongs to the original sealed section, never to a rewritten record.
    source_content_sha256: NonEmptyStr
    omitted_derived_fields: tuple[Literal["chunk.terms"], ...] = ()


def _unique_object(items: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in items:
        if key in result:
            raise ValueError("ambiguous JSON object")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or Decimal(value) != Decimal(str(number)):
        raise ValueError("JSON numeric value cannot be projected losslessly")
    return number


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON value")


def render_context_section(section: ContextSection) -> PromptSectionRendering | None:
    """Return a bounded reading representation, or retain the original text."""
    try:
        value = cast(
            JsonValue,
            json.loads(
                section.content,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
                parse_float=_finite_float,
            ),
        )
    except (ValueError, RecursionError):
        return None
    if not isinstance(value, (dict, list)):
        return None
    if section.name == "knowledge.reads":
        if not isinstance(value, list):
            return None
        try:
            evidence = TypeAdapter(tuple[KnowledgeEvidence, ...]).validate_python(value)
            projected: list[JsonValue] = []
            for item in evidence:
                item.validate_integrity()
                chunk = item.chunk
                if (
                    item.operation != "read_knowledge"
                    or item.status != "READ"
                    or chunk is None
                    or chunk.citation.chunk_sha256 != text_digest(chunk.content)
                    or chunk.terms != terms(chunk.content)
                ):
                    return None
                # Keep every original field/value except the verified lexical
                # index. Preserve explicit null/empty fields as they appeared.
                original = cast(dict[str, JsonValue], value[len(projected)])
                original_chunk = cast(dict[str, JsonValue], original["chunk"])
                projected.append(
                    {
                        **original,
                        "chunk": {k: v for k, v in original_chunk.items() if k != "terms"},
                    }
                )
            return PromptSectionRendering(
                content=projected,
                content_format="knowledge-read-v1",
                source_content_sha256=section.sha256,
                omitted_derived_fields=("chunk.terms",),
            )
        except (ValueError, ValidationError, KnowledgeError, TypeError, KeyError):
            return None
    return PromptSectionRendering(
        content=value,
        content_format="json",
        source_content_sha256=section.sha256,
    )
