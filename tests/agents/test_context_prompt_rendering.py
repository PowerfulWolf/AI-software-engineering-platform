"""Prompt projections preserve sealed Context facts and avoid redundant JSON escaping."""

import json
from pathlib import Path
from typing import cast

import pytest

from ai_software_engineer.agents.openai_compatible import ContextPromptBuilder
from ai_software_engineer.context import ContextBudget, ContextSource, InMemoryContextStore
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.domain.model import WirePayload
from ai_software_engineer.orchestration.context import FileRunContextBuilder
from tests.agents.test_openai_compatible import RecordingContextResolver, _request
from tests.domain.factories import make_implementation_artifact, make_task
from tests.orchestration.test_runner import _definitions


@pytest.mark.parametrize(
    "content",
    (
        '{"whole_patch":"diff --git a/app.py b/app.py\\n+print(\\"中文\\")\\n",'
        '"binding":{"revision":"abc","approved":true},"nothing":null}',
        '[{"id":1},{"id":2,"empty":[]} ]',
    ),
)
def test_json_context_sections_are_losslessly_projected_without_changing_sealed_bytes(
    tmp_path: Path, content: str
) -> None:
    contexts = InMemoryContextStore()
    task = make_task().model_copy(update={"repository": str(tmp_path)})
    context = FileRunContextBuilder(
        tmp_path,
        sources=(ContextSource(source_id="fixture", uri="fixture://approved", content=content),),
        context_store=contexts,
        budget=ContextBudget(max_input_tokens=256_000, reserved_output_tokens=4_000),
    ).build(task, _definitions()[AgentRole.CODER], attempt=1)
    before = context.to_wire()
    request = _request(
        AgentRole.CODER,
        source_revision=context.source_revision,
        context_manifest_id=context.context_id,
    ).model_copy(update={"task_id": task.id, "input_artifact_ids": ()})
    payload = ContextPromptBuilder(
        RecordingContextResolver(context, make_implementation_artifact())
    ).build(request)
    sections = json.loads(payload.messages[1].content)["sections"]
    actual = next(section for section in sections if section["uri"] == "fixture://approved")
    assert actual["content_format"] == "json"
    assert actual["content"] == json.loads(content)
    assert actual["sha256"] == next(s.sha256 for s in context.sections if s.uri == actual["uri"])
    assert [s["name"] for s in sections] == [s.name for s in context.sections if s.name != "policy"]
    assert context.to_wire() == before and contexts.get(context.context_id).to_wire() == before


@pytest.mark.parametrize(
    "content",
    (
        '{"duplicate":1,"duplicate":2}',
        '{"outer":{"duplicate":1,"duplicate":2}}',
        '{"nan":NaN}',
        '{"infinity":Infinity}',
        '{"overflow":1e9999}',
        '{"precision":1.00000000000000001}',
        '{"zero":0e9999999999999999999999}',
        '{"tiny":1e-9999999999999999999999}',
        '{"example":"\\ud800"}',
        '{"example":"\\udfff"}',
        '{"nested":' * 300 + '"complete original value"' + '}' * 300,
        "plain repository instructions",
        "17",
    ),
)
def test_ambiguous_or_non_json_context_keeps_its_original_text(
    tmp_path: Path, content: str
) -> None:
    task = make_task().model_copy(update={"repository": str(tmp_path)})
    context = FileRunContextBuilder(
        tmp_path,
        sources=(ContextSource(source_id="fixture", uri="fixture://original", content=content),),
    ).build(task, _definitions()[AgentRole.CODER], attempt=1)
    request = _request(
        AgentRole.CODER,
        source_revision=context.source_revision,
        context_manifest_id=context.context_id,
    ).model_copy(update={"task_id": task.id, "input_artifact_ids": ()})
    payload = ContextPromptBuilder(
        RecordingContextResolver(context, make_implementation_artifact())
    ).build(request)
    section = next(
        item
        for item in json.loads(payload.messages[1].content)["sections"]
        if item["uri"] == "fixture://original"
    )
    assert section["content"] == content
    assert section.get("content_format", "text") == "text"
    assert payload.messages[1].content.encode("utf-8")


def _reads(count: int = 14) -> list[WirePayload]:
    from ai_software_engineer.knowledge.models import KnowledgeEvidence, digest
    from ai_software_engineer.knowledge.retrieval import parse_document
    from tests.knowledge.test_retrieval_contract import binding, document, snapshot

    # Unique words create a sizeable derived lexical index without inventing
    # knowledge fields. All paragraph bytes and citations are still required.
    body = "# Rules\n" + " ".join(f"rule{i:04d}" for i in range(450))
    doc = document(body)
    frozen = snapshot(doc)
    run = binding(frozen)
    chunk = parse_document(doc)[0]
    values = []
    for index in range(count):
        item = KnowledgeEvidence(
            binding=run,
            operation_id=f"read_{index}",
            operation="read_knowledge",
            request_sha256=digest((index, chunk.citation.to_wire())),
            status="READ",
            chunk=chunk,
            evidence_id="0" * 64,
        )
        item = item.model_copy(
            update={"evidence_id": digest(item.model_dump(mode="json", exclude={"evidence_id"}))}
        )
        values.append(item.to_wire())
    return values


def test_knowledge_read_projection_keeps_complete_chunks_and_all_original_bindings(
    tmp_path: Path,
) -> None:
    reads = _reads()
    raw = json.dumps(reads, ensure_ascii=False, sort_keys=True)
    task = make_task().model_copy(update={"repository": str(tmp_path)})
    context = FileRunContextBuilder(
        tmp_path,
        sources=(
            ContextSource(source_id="placeholder", uri="knowledge://reads/frozen", content=raw),
        ),
        budget=ContextBudget(max_input_tokens=256_000, reserved_output_tokens=4_000),
    ).build(task, _definitions()[AgentRole.CODER], attempt=1)
    original = context.sections[-1]
    knowledge = original.model_copy(update={"name": "knowledge.reads"})
    context = context.model_copy(update={"sections": (*context.sections[:-1], knowledge)})
    before = context.to_wire()
    request = _request(
        AgentRole.CODER,
        source_revision=context.source_revision,
        context_manifest_id=context.context_id,
    ).model_copy(update={"task_id": task.id})
    payload = ContextPromptBuilder(
        RecordingContextResolver(context, make_implementation_artifact())
    ).build(request)
    section = next(
        item
        for item in json.loads(payload.messages[1].content)["sections"]
        if item["name"] == "knowledge.reads"
    )
    assert section["content_format"] == "knowledge-read-v1"
    assert section["omitted_derived_fields"] == ["chunk.terms"]
    assert section["source_content_sha256"] == original.sha256
    assert len(section["content"]) == len(reads)
    for projected, full in zip(section["content"], reads, strict=True):
        assert projected == {
            **full,
            "chunk": {k: v for k, v in cast(WirePayload, full["chunk"]).items() if k != "terms"},
        }
    assert context.to_wire() == before


@pytest.mark.parametrize(
    "fault", ["changed_terms", "bad_evidence", "changed_chunk", "unknown_field"]
)
def test_knowledge_projection_never_discards_invalid_or_non_derived_fields(fault: str) -> None:
    from ai_software_engineer.agents.context_rendering import render_context_section
    from ai_software_engineer.context.models import ContextSection
    from ai_software_engineer.knowledge.models import digest, text_digest

    read = _reads(1)[0]
    chunk = cast(WirePayload, read["chunk"])
    if fault == "changed_terms":
        chunk["terms"] = ["not-derived-rule"]
        read["evidence_id"] = digest({k: v for k, v in read.items() if k != "evidence_id"})
    elif fault == "bad_evidence":
        read["evidence_id"] = "f" * 64
    elif fault == "changed_chunk":
        chunk["content"] = cast(str, chunk["content"]) + "changed rule"
        read["evidence_id"] = digest({k: v for k, v in read.items() if k != "evidence_id"})
    else:
        chunk["business_rule"] = "Required policy"
    raw = json.dumps([read], ensure_ascii=False, sort_keys=True)
    section = ContextSection(
        name="knowledge.reads",
        uri="knowledge://reads/frozen",
        content=raw,
        sha256=text_digest(raw),
        tokens=(len(raw) + 3) // 4,
        priority=50,
    )
    assert render_context_section(section) is None


def test_complete_native_input_and_schema_fit_without_dropping_required_patch_or_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_software_engineer.agents.codex_cli import CodexCliAgentAdapter
    from ai_software_engineer.agents.model_input import BoundModelInputBudget
    from ai_software_engineer.context import ContextBudgetExceeded
    from ai_software_engineer.context.builder import estimate_input_tokens
    from ai_software_engineer.knowledge.runtime import append_knowledge_context
    from tests.agents.test_codex_cli import _repository
    from tests.agents.test_model_input_preflight import _Runner

    root, revision = _repository(tmp_path)
    task = make_task().model_copy(update={"repository": str(root), "base_ref": revision})
    patch = ('+ preserved historical change "' + "x" * 380 + '"\n') * 1450
    patch_json = json.dumps(
        {"complete_patch": patch, "input_mode": "coder_reapply"}, ensure_ascii=False
    )
    approved_json = json.dumps({"approved_scope": "x" * 255_000}, ensure_ascii=False)
    contexts = InMemoryContextStore()
    base = FileRunContextBuilder(
        root,
        sources=(
            ContextSource(
                source_id="complete.patch",
                uri="fixture://full-patch",
                content=patch_json,
                required=True,
            ),
            ContextSource(
                source_id="complete.approved",
                uri="fixture://full-approved",
                content=approved_json,
                required=True,
            ),
        ),
        context_store=contexts,
        budget=ContextBudget(max_input_tokens=256_000, reserved_output_tokens=4_000),
    ).build(task, _definitions()[AgentRole.CODER], attempt=1)
    reads = _reads()
    context = append_knowledge_context(
        base,
        contexts,
        name="knowledge.reads",
        uri="knowledge://reads/frozen",
        content=json.dumps(reads, ensure_ascii=False, sort_keys=True),
    )
    before = context.to_wire()
    resolver = RecordingContextResolver(context, make_implementation_artifact())
    request = _request(
        AgentRole.CODER, source_revision=revision, context_manifest_id=context.context_id
    ).model_copy(update={"task_id": task.id})
    runner = _Runner()
    adapter = CodexCliAgentAdapter(
        workspace_root=root,
        model="test",
        agent_id="agent_test",
        agent_version="v1",
        runner=runner,
        prompt_builder=ContextPromptBuilder(resolver),
        input_budget=BoundModelInputBudget(resolver),
    )
    with monkeypatch.context() as old:
        old.setattr(
            "ai_software_engineer.agents.openai_compatible.render_context_section", lambda _: None
        )
        with pytest.raises(ContextBudgetExceeded):
            adapter.prepare_input(request)
    assert runner.calls == 0 and not adapter._prepared_inputs
    adapter.prepare_input(request)
    prepared = adapter._prepared_inputs[request.run_id]
    assert estimate_input_tokens(prepared.budget_content) <= 256_000
    messages = json.loads(prepared.compiled_prompt.split("PROMPT_MESSAGES=", 1)[1])
    user = next(message["content"] for message in messages if message["role"] == "user")
    patch_section = next(item for item in user["sections"] if item["uri"] == "fixture://full-patch")
    assert patch_section["content"]["complete_patch"] == patch
    knowledge = next(item for item in user["sections"] if item["name"] == "knowledge.reads")
    assert [item["chunk"]["content"] for item in knowledge["content"]] == [
        cast(WirePayload, item["chunk"])["content"] for item in reads
    ]
    assert prepared.schema_content and prepared.schema_path.read_text() == prepared.schema_content
    assert context.to_wire() == before and contexts.get(context.context_id).to_wire() == before
    adapter.discard_prepared_input(request)
    assert not adapter._prepared_inputs and runner.calls == 0
