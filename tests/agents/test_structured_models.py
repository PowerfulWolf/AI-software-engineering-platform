"""Structured upstream stages support bounded image input and safe fallback."""

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    CodexCliStructuredModelClient,
    FallbackStructuredModelClient,
    StructuredModelClient,
    StructuredModelError,
    StructuredModelResult,
    StructuredModelRoute,
)


class _StaticClient(StructuredModelClient):
    def __init__(self) -> None:
        self.images: tuple[Path, ...] = ()

    def complete(
        self,
        *,
        instructions: str,
        input_payload: Mapping[str, object],
        output_schema: Mapping[str, object],
        timeout_seconds: int,
        input_images: tuple[Path, ...] = (),
    ) -> StructuredModelResult:
        del instructions, input_payload, output_schema, timeout_seconds
        self.images = input_images
        return StructuredModelResult(payload={"result": "ok"}, duration_ms=1)


def test_codex_structured_command_binds_verified_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    commands: list[tuple[str, ...]] = []

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        commands.append(command)
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(json.dumps({"result": "ok"}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("ai_software_engineer.agents.structured.subprocess.run", run)
    client = CodexCliStructuredModelClient(
        repository_root=repository,
        model="gpt-test",
        executable="codex",
        environment={"PATH": "/usr/bin"},
    )

    result = client.complete(
        instructions="Return a result.",
        input_payload={"request": "inspect screenshot"},
        output_schema={
            "title": "Result",
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
        },
        timeout_seconds=30,
        input_images=(screenshot,),
    )

    assert result.payload == {"result": "ok"}
    assert commands[0][commands[0].index("--image") + 1] == str(screenshot)


def test_image_request_skips_routes_without_image_support(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.webp"
    screenshot.write_bytes(b"RIFFxxxxWEBPfixture")
    unsupported = _StaticClient()
    supported = _StaticClient()
    client = FallbackStructuredModelClient(
        (
            StructuredModelRoute("text-only", "first", unsupported, supports_images=False),
            StructuredModelRoute("vision", "second", supported, supports_images=True),
        )
    )

    result = client.complete(
        instructions="Return a result.",
        input_payload={},
        output_schema={"type": "object"},
        timeout_seconds=30,
        input_images=(screenshot,),
    )

    assert result.payload == {"result": "ok"}
    assert unsupported.images == ()
    assert supported.images == (screenshot,)


def test_same_structured_model_supports_distinct_reasoning_routes() -> None:
    first = _StaticClient()
    second = _StaticClient()

    client = FallbackStructuredModelClient(
        (
            StructuredModelRoute("codex", "gpt-5.6-sol", first, "medium"),
            StructuredModelRoute("codex", "gpt-5.6-sol", second, "high"),
        )
    )

    assert client is not None


def test_codex_structured_image_rejects_symlink_before_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    alias = tmp_path / "alias.png"
    alias.symlink_to(screenshot)
    monkeypatch.setattr(
        "ai_software_engineer.agents.structured.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("provider must not be called"),
    )
    client = CodexCliStructuredModelClient(
        repository_root=repository,
        model="gpt-test",
        executable="codex",
        environment={"PATH": "/usr/bin"},
    )

    with pytest.raises(StructuredModelError, match="image input is invalid"):
        client.complete(
            instructions="Return a result.",
            input_payload={},
            output_schema={"type": "object"},
            timeout_seconds=30,
            input_images=(alias,),
        )
