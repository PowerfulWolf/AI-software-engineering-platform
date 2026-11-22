"""Read-only repository tools let any Responses model verify code during Design."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import HttpResponse, ResponsesStructuredModelClient, structured
from ai_software_engineer.agents.model_diagnostics import model_call_phase
from ai_software_engineer.agents.repository_tools import (
    ReadableRepository,
    current_read_access,
    repository_read_access,
    run_tool,
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> ReadableRepository:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "window.py").write_text(
        "def bounded_coder_window(seconds, *, max_steps=3):\n    return seconds\n"
    )
    (root / ".env").write_text("TOKEN=private\n")
    subprocess.run(("git", "init", "-q", "-b", "main", str(root)), check=True)
    _git(root, "add", "src/window.py", ".env")
    _git(root, "commit", "-q", "-m", "base")
    base = _git(root, "rev-parse", "HEAD")
    (root / "src" / "window.py").write_text("changed after the pinned revision\n")
    return ReadableRepository(root=root, revision=base, label="repo1")


def _call(repo: ReadableRepository, name: str, **arguments: object) -> str:
    return run_tool((repo,), name, json.dumps({"repository": "repo1", **arguments}))


def test_tools_read_the_pinned_revision_not_the_working_tree(repo: ReadableRepository) -> None:
    assert "src/window.py" in _call(repo, "list_files", path="")
    text = _call(repo, "read_file", path="src/window.py", start_line=0, end_line=0)
    assert "1: def bounded_coder_window" in text and "changed after" not in text
    assert "src/window.py:1:" in _call(repo, "search_code", pattern="max_steps", path="")


@pytest.mark.parametrize("path", ["../outside.txt", ".git/config", ".env", "/etc/passwd"])
def test_tools_refuse_escapes_and_secrets(repo: ReadableRepository, path: str) -> None:
    assert _call(repo, "read_file", path=path, start_line=0, end_line=0).startswith("ERROR")
    assert ".env" not in _call(repo, "list_files", path="")
    assert "TOKEN" not in _call(repo, "search_code", pattern="TOKEN", path="")


def test_access_is_only_for_stage_replies(repo: ReadableRepository) -> None:
    with repository_read_access((repo,)):
        assert current_read_access() == (repo,)
        with model_call_phase("knowledge_intent"):
            assert current_read_access() is None
    assert current_read_access() is None


def test_responses_client_runs_a_tool_turn_then_returns_the_object(
    repo: ReadableRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(structured._RESPONSES_STREAMING, "enabled", False)
    sent: list[dict[str, object]] = []

    class Gateway:
        def post(
            self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
        ) -> HttpResponse:
            request = json.loads(body)
            sent.append(request)
            if len(sent) == 1:
                output = [
                    {"type": "reasoning", "id": "r1", "summary": []},
                    {
                        "type": "function_call",
                        "call_id": "c1",
                        "name": "read_file",
                        "arguments": json.dumps(
                            {
                                "repository": "repo1",
                                "path": "src/window.py",
                                "start_line": 0,
                                "end_line": 0,
                            }
                        ),
                    },
                ]
            else:
                output = [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": '{"answer": "ok"}'}],
                    }
                ]
            return HttpResponse(status_code=200, body=json.dumps({"output": output}).encode())

    client = ResponsesStructuredModelClient(
        endpoint="https://example.invalid/v1/responses",
        credential="k",
        model="m",
        transport=Gateway(),
    )
    with repository_read_access((repo,)):
        result = client.complete(
            instructions="Act as Designer.", input_payload={}, output_schema={}, timeout_seconds=5
        )
    assert result.payload == {"answer": "ok"}
    assert len(sent) == 2
    assert [tool["name"] for tool in sent[0]["tools"]] == ["list_files", "search_code", "read_file"]
    assert "read-only repository tools" in sent[0]["input"][0]["content"]
    replayed = sent[1]["input"]
    assert any(item.get("type") == "reasoning" for item in replayed)
    output_item = next(item for item in replayed if item.get("type") == "function_call_output")
    assert "bounded_coder_window" in output_item["output"]


def test_without_access_no_tools_are_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(structured._RESPONSES_STREAMING, "enabled", False)

    class Gateway:
        def post(
            self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
        ) -> HttpResponse:
            assert "tools" not in json.loads(body)
            return HttpResponse(
                status_code=200, body=b'{"output_text": "{\\"answer\\": \\"ok\\"}"}'
            )

    client = ResponsesStructuredModelClient(
        endpoint="https://example.invalid/v1/responses",
        credential="k",
        model="m",
        transport=Gateway(),
    )
    assert client.complete(
        instructions="x", input_payload={}, output_schema={}, timeout_seconds=5
    ).payload == {"answer": "ok"}
