from __future__ import annotations

import json

from ai_software_engineer.agents.context_compaction import (
    REFERENCE_NOTE,
    compact_model_payload,
    compact_prompt_sections,
)

_SHA = "a" * 64


def _reference(index: int, uri: str) -> dict[str, object]:
    return {
        "name": f"source:native.reference.{index}",
        "uri": uri,
        "sha256": f"{index:064x}",
        "content": (
            "Project-native rule reference; full body remains in the frozen knowledge snapshot. "
            f"URI={uri}; frozen_redacted_sha256={_SHA}. Consult applicable rules before editing "
            "or verifying. Verified retrieved passages are supplied in knowledge.reads; "
            "references alone do not supply the rule text. Report missing required rules rather "
            "than inferring their contents."
        ),
    }


def _sections() -> list[dict[str, object]]:
    return [
        {"name": "task", "uri": "task://1", "sha256": "t", "content": {"goal": "x"}},
        _reference(0, "project://r/a.md"),
        _reference(1, "project://r/b.md"),
        {
            "name": "source:project.baseline",
            "uri": "baseline://1",
            "sha256": "b",
            "content": {
                "revision": "abc",
                "opaque_project_sources": [
                    {"uri": "project://r/a.md", "sha256": _SHA},
                    {"uri": "project://r/b.md", "sha256": _SHA},
                    {"uri": "project://r/extra.md", "sha256": "c" * 64},
                ],
            },
        },
        {
            "name": "knowledge.reads",
            "uri": "reads://1",
            "sha256": "k",
            "content_format": "knowledge-read-v1",
            "content": [
                {"binding": {"run": "r1"}, "uri": "project://r/a.md", "text": "A"},
                {"binding": {"run": "r1"}, "uri": "project://r/b.md", "text": "B"},
            ],
        },
    ]


def test_references_collapse_into_one_lossless_index() -> None:
    compacted = compact_prompt_sections(_sections())  # type: ignore[arg-type]
    names = [section["name"] for section in compacted]
    assert names == [
        "task",
        "source:native.reference.*",
        "source:project.baseline",
        "knowledge.reads",
    ]
    index = compacted[1]["content"]
    assert index["note"] == REFERENCE_NOTE  # type: ignore[index]
    assert index["references"] == [  # type: ignore[index]
        {
            "name": "source:native.reference.0",
            "uri": "project://r/a.md",
            "sha256": f"{0:064x}",
            "frozen_redacted_sha256": _SHA,
        },
        {
            "name": "source:native.reference.1",
            "uri": "project://r/b.md",
            "sha256": f"{1:064x}",
            "frozen_redacted_sha256": _SHA,
        },
    ]
    baseline = compacted[2]
    assert baseline["content_format"] == "project-baseline-v2"
    assert baseline["content"]["revision"] == "abc"  # type: ignore[index]
    assert baseline["content"]["opaque_project_sources"] == {  # type: ignore[index]
        "same_as_native_reference_index": 2,
        "additional": [{"uri": "project://r/extra.md", "sha256": "c" * 64}],
    }
    reads = compacted[3]
    assert reads["content_format"] == "knowledge-read-v2"
    assert reads["content"] == {  # type: ignore[comparison-overlap]
        "binding": {"run": "r1"},
        "reads": [
            {"uri": "project://r/a.md", "text": "A"},
            {"uri": "project://r/b.md", "text": "B"},
        ],
    }


def test_unrecognised_reference_text_is_kept_verbatim() -> None:
    sections = _sections()
    sections[1] = {**sections[1], "content": "Custom rule text that must not be dropped."}
    compacted = compact_prompt_sections(sections)  # type: ignore[arg-type]
    assert sections[1] in compacted
    # only one recognised reference remains, so no index is produced
    assert all(section["name"] != "source:native.reference.*" for section in compacted)


def test_differing_bindings_are_not_hoisted() -> None:
    sections = _sections()
    reads = sections[4]["content"]
    reads[1] = {**reads[1], "binding": {"run": "r2"}}  # type: ignore[index]
    compacted = compact_prompt_sections(sections)  # type: ignore[arg-type]
    assert compacted[-1]["content_format"] == "knowledge-read-v1"


def test_raw_context_payload_is_compacted_with_guidance() -> None:
    sections = _sections()
    sections[3] = {**sections[3], "content": json.dumps(sections[3]["content"])}
    payload = {"task": {"id": "t"}, "context": {"context_id": "c", "sections": sections}}
    compacted = compact_model_payload(payload)
    assert isinstance(compacted, dict)
    assert compacted["task"] == {"id": "t"}
    assert "reading_projection" in compacted
    assert len(compacted["context"]["sections"]) == 4
    assert compact_model_payload({"task": 1}) == {"task": 1}


def test_knowledge_consultation_payload_nested_under_task_is_compacted() -> None:
    sections = _sections()
    sections[3] = {**sections[3], "content": json.dumps(sections[3]["content"])}
    consultation = {"task": {"id": "t"}, "context": {"context_id": "c", "sections": sections}}
    payload = {"binding": {"run_id": "r"}, "task": consultation, "available_documents": []}
    compacted = compact_model_payload(payload)
    assert isinstance(compacted, dict)
    assert compacted["binding"] == {"run_id": "r"}
    assert compacted["available_documents"] == []
    assert len(compacted["task"]["context"]["sections"]) == 4
    assert "reading_projection" in compacted["task"]
    unchanged = {"binding": {}, "task": {"id": "t"}}
    assert compact_model_payload(unchanged) is unchanged
