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
