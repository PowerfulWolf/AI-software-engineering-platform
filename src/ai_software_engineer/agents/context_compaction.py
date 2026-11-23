"""Prompt-only compaction of repetitive sealed Context sections.

Nothing here changes a ContextBundle, its manifest, or any evidence: the model
receives the same facts with repeated boilerplate removed. Every compaction is
exact and reversible — a projection is applied only when the sections match the
platform's own fixed templates, otherwise the original rendering is kept.

Measured on ASE's own delivery Contexts (~70k tokens per role turn):
* 120 ``source:native.reference.*`` sections repeat one ~95-token sentence;
* ``source:project.baseline`` re-lists the same (URI, sha256) pairs;
* every ``knowledge.reads`` item repeats one identical binding object.
"""

from __future__ import annotations

import json
import re
from typing import cast

from ai_software_engineer.domain.model import JsonValue

_REFERENCE_PREFIX = "source:native.reference."
_REFERENCE_TEMPLATE = re.compile(
    r"Project-native rule reference; full body remains in the frozen knowledge snapshot\. "
    r"URI=(?P<uri>[^;\s]+); frozen_redacted_sha256=(?P<sha>[0-9a-f]{64})\. "
    r"Consult applicable rules before editing or verifying\. Verified retrieved passages "
    r"are supplied in knowledge\.reads; references alone do not supply the rule text\. "
    r"Report missing required rules rather than inferring their contents\."
)
REFERENCE_NOTE = (
    "Project-native rule references; full bodies remain in the frozen knowledge snapshot. "
    "Consult applicable rules before editing or verifying. Verified retrieved passages are "
    "supplied in knowledge.reads; references alone do not supply the rule text. Report "
    "missing required rules rather than inferring their contents."
)

COMPACTION_GUIDANCE = (
    "\nPrompt compaction (reading form only; sealed Context is unchanged): "
    "content_format=native-reference-index-v1 lists every source:native.reference.N section "
    "(name, uri, section sha256, frozen_redacted_sha256) under one shared note; "
    "project-baseline-v2 lists only the opaque_project_sources entries that are not already "
    "(uri, frozen_redacted_sha256) pairs of that index; knowledge-read-v2 states one shared "
    "binding "
    "instead of repeating it on every READ item."
)


def compact_prompt_sections(sections: list[dict[str, JsonValue]]) -> list[dict[str, JsonValue]]:
    references: list[dict[str, JsonValue]] = []
    others: list[dict[str, JsonValue]] = []
    first_reference = -1
    for section in sections:
        name = str(section.get("name", ""))
        content = section.get("content")
        match = (
            _REFERENCE_TEMPLATE.fullmatch(content)
            if name.startswith(_REFERENCE_PREFIX) and isinstance(content, str)
            else None
        )
        if match is None or match["uri"] != section.get("uri"):
            others.append(section)
            continue
        if first_reference < 0:
            first_reference = len(others)
        references.append(
            {
                "name": name,
                "uri": match["uri"],
                "sha256": section.get("sha256"),
                "frozen_redacted_sha256": match["sha"],
            }
        )
    if len(references) < 2:
        return [_compact_reads(section) for section in sections]
    pairs = {(str(item["uri"]), str(item["frozen_redacted_sha256"])) for item in references}
    index: dict[str, JsonValue] = {
        "name": _REFERENCE_PREFIX + "*",
        "content_format": "native-reference-index-v1",
        "content": {"note": REFERENCE_NOTE, "references": cast(JsonValue, references)},
    }
    result = [_compact_baseline(_compact_reads(section), pairs) for section in others]
    result.insert(first_reference, index)
    return result


def compact_model_payload(payload: object) -> object:
    """Apply the same exact compaction to a raw ``{"context": ContextBundle}`` model input.

    Knowledge intent/assessment calls send the sealed ContextBundle wire itself; its
    sections carry unparsed JSON strings. Digests of the original payload are taken by
    callers before this reading projection, so recorded inputs keep their identity.
    """
    if not isinstance(payload, dict):
        return payload
    context = payload.get("context")
    if not isinstance(context, dict) or not isinstance(context.get("sections"), list):
        return payload
    sections: list[dict[str, JsonValue]] = []
    for section in context["sections"]:
        if not isinstance(section, dict):
            return payload
        content = section.get("content")
        if section.get("name") == "source:project.baseline" and isinstance(content, str):
            try:
                parsed = json.loads(content)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                section = {**section, "content": parsed}
        sections.append(cast(dict[str, JsonValue], section))
    compacted = compact_prompt_sections(sections)
    if compacted == sections:
        return payload
    return {
        **payload,
        "context": {**context, "sections": compacted},
        "reading_projection": COMPACTION_GUIDANCE.strip(),
    }


def _compact_baseline(
    section: dict[str, JsonValue], pairs: set[tuple[str, str]]
) -> dict[str, JsonValue]:
    content = section.get("content")
    if section.get("name") != "source:project.baseline" or not isinstance(content, dict):
        return section
    listed = content.get("opaque_project_sources")
    if not isinstance(listed, list) or not listed:
        return section
    if not all(
        isinstance(item, dict)
        and set(item) == {"uri", "sha256"}
        and isinstance(item["uri"], str)
        and isinstance(item["sha256"], str)
        for item in listed
    ):
        return section
    entries = cast(list[dict[str, str]], listed)
    covered = [item for item in entries if (item["uri"], item["sha256"]) in pairs]
    if len(covered) < 2 or len({(i["uri"], i["sha256"]) for i in entries}) != len(entries):
        return section
    return {
        **section,
        "content_format": "project-baseline-v2",
        "content": {
            **content,
            "opaque_project_sources": {
                "same_as_native_reference_index": len(covered),
                "additional": [item for item in entries if item not in covered],
            },
        },
    }


def _compact_reads(section: dict[str, JsonValue]) -> dict[str, JsonValue]:
    content = section.get("content")
    if (
        section.get("name") != "knowledge.reads"
        or section.get("content_format") != "knowledge-read-v1"
        or not isinstance(content, list)
        or len(content) < 2
        or not all(isinstance(item, dict) and "binding" in item for item in content)
    ):
        return section
    items = cast(list[dict[str, JsonValue]], content)
    binding = items[0]["binding"]
    if any(item["binding"] != binding for item in items):
        return section
    return {
        **section,
        "content_format": "knowledge-read-v2",
        "content": {
            "binding": binding,
            "reads": [{k: v for k, v in item.items() if k != "binding"} for item in items],
        },
    }


__all__ = [
    "COMPACTION_GUIDANCE",
    "REFERENCE_NOTE",
    "compact_model_payload",
    "compact_prompt_sections",
]
