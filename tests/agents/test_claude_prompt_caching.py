from __future__ import annotations

from pathlib import Path

from ai_software_engineer.agents.claude_cli import (
    ClaudeCliStructuredModelClient,
    render_responses_turn,
    render_responses_turn_parts,
    split_shared_input,
)


def _request(rounds: int) -> dict[str, object]:
    items: list[dict[str, object]] = [
        {"role": "system", "content": "machine policy"},
        {"role": "user", "content": '{"sections": ["big context"]}'},
    ]
    for index in range(rounds):
        items.append(
            {"type": "function_call", "call_id": f"c{index}", "name": "read", "arguments": "{}"}
        )
        items.append({"type": "function_call_output", "call_id": f"c{index}", "output": "x"})
    return {
        "input": items,
        "tools": [{"type": "function", "name": "read", "description": "d", "parameters": {}}],
        "text": {"format": {"schema": {"type": "object"}}},
    }


def test_cached_prefix_is_identical_across_tool_rounds() -> None:
    first, first_tail, _ = render_responses_turn_parts(_request(0))
    later, later_tail, _ = render_responses_turn_parts(_request(3))
    assert first == later
    assert "big context" in first and "machine policy" in first
    assert "big context" not in later_tail
    assert later_tail.count("TOOL RESULT") == 3
    assert "TOOL RESULT" not in first_tail
    joined, _ = render_responses_turn(_request(3))
    assert joined == later + "\n\n" + later_tail


def test_shared_knowledge_input_is_split_for_the_cache() -> None:
    shared, rest = split_shared_input(
        {"binding": {"run": 1}, "task": {"context": 1}, "knowledge_evidence": [1]}
    )
    assert shared == {"binding": {"run": 1}, "task": {"context": 1}}
    assert rest == {"knowledge_evidence": [1]}


def test_system_prompt_file_is_passed_to_the_cli(tmp_path: Path) -> None:
    client = ClaudeCliStructuredModelClient(
        repository_root=tmp_path, model="claude-opus-5-5", allow_repository_reads=False
    )
    target = tmp_path / "system.txt"
    argv = client.argv({"type": "object"}, system_prompt_file=target)
    index = argv.index("--append-system-prompt-file")
    assert argv[index + 1] == str(target)
    assert "--append-system-prompt-file" not in client.argv({"type": "object"})


def test_tool_less_calls_share_one_stable_private_working_directory() -> None:
    from ai_software_engineer.agents.claude_cli import _isolated_working_directory

    first = _isolated_working_directory()
    second = _isolated_working_directory()
    assert first == second
    assert first.is_dir() and not any(first.iterdir())


def _complete_with(
    tmp_path: Path, monkeypatch: object, answer: object, schema: dict[str, object]
) -> tuple[object, dict[str, object]]:
    import json
    import subprocess

    import pytest

    from ai_software_engineer.agents import claude_cli

    seen: dict[str, object] = {}

    def fake_run(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["argv"], seen["input"] = argv, kwargs["input"]
        return subprocess.CompletedProcess(argv, 0, json.dumps({"structured_output": answer}), "")

    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.setattr(claude_cli, "run_structured_command", fake_run)
    client = ClaudeCliStructuredModelClient(
        repository_root=tmp_path, model="claude-opus-5-5", allow_repository_reads=False
    )
    try:
        result: object = client.complete(
            instructions="x",
            input_payload={"task": {"t": 1}},
            output_schema=schema,
            timeout_seconds=30,
        )
    except Exception as error:
        result = error
    return result, seen


_INTENT = {
    "type": "object",
    "properties": {"queries": {"type": "array", "items": {"type": "string"}}},
    "required": ["queries"],
    "additionalProperties": False,
}


def test_tool_less_calls_share_one_cli_schema_and_state_the_real_one_after_the_cache(
    tmp_path: Path, monkeypatch: object
) -> None:
    import json

    result, seen = _complete_with(tmp_path, monkeypatch, {"queries": ["a"]}, _INTENT)
    argv = seen["argv"]
    assert isinstance(argv, tuple)
    assert json.loads(argv[argv.index("--json-schema") + 1]) == {"type": "object"}
    assert "OUTPUT_SCHEMA=" in str(seen["input"]) and '"queries"' in str(seen["input"])
    assert result.payload == {"queries": ["a"]}


def test_tool_less_answer_violating_the_real_schema_is_rejected(
    tmp_path: Path, monkeypatch: object
) -> None:
    from ai_software_engineer.agents.structured import StructuredModelError

    result, _ = _complete_with(tmp_path, monkeypatch, {"queries": "not-a-list"}, _INTENT)
    assert isinstance(result, StructuredModelError)
    assert result.transient is True
    assert "queries" in str(result)


def test_malformed_final_gets_one_repair_round_with_the_exact_problem(
    monkeypatch: object,
) -> None:
    import json
    import subprocess

    import pytest

    from ai_software_engineer import owned_processes
    from ai_software_engineer.agents.claude_cli import ClaudeCliResponsesTransport

    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    replies = [
        {"action": "final", "tool_calls": [], "final_json": '{"summary": 3}'},
        {"action": "final", "tool_calls": [], "final_json": '{"summary": "done"}'},
    ]
    prompts: list[str] = []
    argvs: list[tuple[str, ...]] = []

    def fake_run(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        argvs.append(argv)
        prompts.append(str(kwargs["input"]))
        body = json.dumps({"structured_output": replies[len(prompts) - 1]})
        return subprocess.CompletedProcess(argv, 0, body, "")

    monkeypatch.setattr(owned_processes, "run_owned_subprocess", fake_run)
    request = _request(1)
    request["text"] = {
        "format": {
            "schema": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
            }
        }
    }
    transport = ClaudeCliResponsesTransport(model="claude-opus-5-5")
    response = transport.post("u", {}, json.dumps(request).encode(), 600)
    assert response.status_code == 200
    assert len(prompts) == 2
    assert "YOUR PREVIOUS REPLY WAS REJECTED" in prompts[1] and "summary" in prompts[1]
    assert all("--system-prompt-file" in argv for argv in argvs)
    body = json.loads(response.body)
    assert body["output"][0]["content"][0]["text"] == '{"summary": "done"}'


def test_tool_less_structured_calls_replace_the_cli_system_prompt(
    tmp_path: Path, monkeypatch: object
) -> None:
    _, seen = _complete_with(tmp_path, monkeypatch, {"queries": []}, _INTENT)
    argv = seen["argv"]
    assert isinstance(argv, tuple)
    assert "--system-prompt-file" in argv and "--append-system-prompt-file" not in argv


def test_stringified_array_is_decoded_only_where_the_schema_demands_a_container(
    tmp_path: Path, monkeypatch: object
) -> None:
    schema = {
        "type": "object",
        "properties": {
            "queries": {"type": "array", "items": {"type": "string"}},
            "note": {"type": "string"},
        },
        "required": ["queries", "note"],
    }
    answer = {"queries": '["retry policy", "window"]', "note": '["kept as text"]'}
    result, seen = _complete_with(tmp_path, monkeypatch, answer, schema)
    assert result.payload == {
        "queries": ["retry policy", "window"],
        "note": '["kept as text"]',
    }
    assert "YOUR PREVIOUS REPLY WAS REJECTED" not in str(seen["input"])


def test_each_tool_round_is_its_own_stable_content_block() -> None:
    from ai_software_engineer.agents.claude_cli import render_responses_turn_blocks

    static_two, two, _ = render_responses_turn_blocks(_request(2))
    static_three, three, _ = render_responses_turn_blocks(_request(3))
    # Earlier rounds are byte-identical blocks, so the next call re-reads them from cache.
    assert static_two == static_three
    assert three[: len(two)] == two
    assert len(three) == 3
    assert all(block.count("TOOL RESULT") == 1 for block in three)
    # No fixed trailing cue after the last round: it would break the cached prefix.
    assert "Now reply" not in three[-1]
    assert "next JSON object" in static_three


def test_parallel_tool_calls_of_one_round_share_a_block() -> None:
    from ai_software_engineer.agents.claude_cli import render_responses_turn_blocks

    request = _request(0)
    items = request["input"]
    assert isinstance(items, list)
    items += [
        {"type": "function_call", "call_id": "a", "name": "read", "arguments": "{}"},
        {"type": "function_call", "call_id": "b", "name": "read", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "a", "output": "x"},
        {"type": "function_call_output", "call_id": "b", "output": "y"},
        {"role": "user", "content": "correction"},
    ]
    _, blocks, _ = render_responses_turn_blocks(request)
    assert len(blocks) == 2
    assert blocks[0].count("TOOL CALL") == 2 and blocks[0].count("TOOL RESULT") == 2
    assert blocks[1] == "USER:\ncorrection"


def test_transport_streams_round_blocks_and_reads_the_result_event(
    monkeypatch: object,
) -> None:
    import json
    import subprocess

    import pytest

    from ai_software_engineer import owned_processes
    from ai_software_engineer.agents.claude_cli import ClaudeCliResponsesTransport

    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    seen: dict[str, object] = {}
    reply = {"action": "final", "tool_calls": [], "final_json": "{}"}
    stdout = "\n".join(
        (
            json.dumps({"type": "system", "subtype": "init"}),
            json.dumps({"type": "assistant", "message": {}}),
            json.dumps({"type": "result", "is_error": False, "structured_output": reply}),
        )
    )

    def fake_run(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["argv"], seen["input"] = argv, kwargs["input"]
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(owned_processes, "run_owned_subprocess", fake_run)
    response = ClaudeCliResponsesTransport(model="claude-opus-5-5").post(
        "u", {}, json.dumps(_request(2)).encode(), 600
    )
    assert response.status_code == 200
    argv = seen["argv"]
    assert isinstance(argv, tuple)
    assert argv[argv.index("--input-format") + 1] == "stream-json"
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv
    message = json.loads(str(seen["input"]))
    assert message["type"] == "user"
    content = message["message"]["content"]
    assert [part["type"] for part in content] == ["text", "text"]
    assert "TOOL RESULT [c1]" in content[1]["text"]
