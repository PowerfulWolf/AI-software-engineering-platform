"""Structured upstream stages support bounded image input and safe fallback."""

import errno
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentErrorCode,
    CodexCliStructuredModelClient,
    FallbackStructuredModelClient,
    HttpResponse,
    ResponsesStructuredModelClient,
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
    assert not any(item.startswith("model_provider=") for item in commands[0])


def test_codex_structured_command_uses_explicit_local_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    commands: list[tuple[str, ...]] = []

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        commands.append(command)
        Path(command[command.index("--output-last-message") + 1]).write_text(
            json.dumps({"result": "ok"}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("ai_software_engineer.agents.structured.subprocess.run", run)
    client = CodexCliStructuredModelClient(
        repository_root=repository,
        model="gpt-test",
        proxy_base_url="http://127.0.0.1:8317/v1",
        environment={"PATH": "/usr/bin"},
    )

    client.complete(
        instructions="Return a result.",
        input_payload={},
        output_schema={"type": "object"},
        timeout_seconds=30,
    )

    command = commands[0]
    assert "--ignore-user-config" in command
    assert 'model_provider="ase_local_proxy"' in command
    assert 'model_providers.ase_local_proxy.base_url="http://127.0.0.1:8317/v1"' in command
    assert 'model_providers.ase_local_proxy.wire_api="responses"' in command
    assert "model_providers.ase_local_proxy.requires_openai_auth=true" in command


def test_codex_structured_command_mounts_additional_requirement_baselines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = tmp_path / "primary"
    additional = tmp_path / "additional"
    primary.mkdir()
    additional.mkdir()
    commands: list[tuple[str, ...]] = []

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        commands.append(command)
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(json.dumps({"result": "ok"}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("ai_software_engineer.agents.structured.subprocess.run", run)
    client = CodexCliStructuredModelClient(
        repository_root=primary,
        additional_repository_roots=(additional,),
        model="gpt-test",
        environment={"PATH": "/usr/bin"},
    )

    client.complete(
        instructions="Return a result.",
        input_payload={},
        output_schema={"type": "object"},
        timeout_seconds=30,
    )

    command = commands[0]
    assert command[command.index("-C") + 1] == str(primary)
    assert command[command.index("--add-dir") + 1] == str(additional)


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


@pytest.mark.parametrize(
    ("stderr", "code"),
    [
        ("Error: usage limit reached", AgentErrorCode.QUOTA_EXHAUSTED),
        ("Error: rate limit 429", AgentErrorCode.RATE_LIMITED),
        ("Error: authentication expired", AgentErrorCode.AUTHENTICATION_ERROR),
        ("Error: service connection closed", AgentErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_structured_cli_failure_preserves_safe_cause_not_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stderr: str, code: AgentErrorCode
) -> None:
    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "PROMPT usage limit PRIVATE", stderr)

    monkeypatch.setattr("ai_software_engineer.agents.structured.subprocess.run", run)
    client = CodexCliStructuredModelClient(repository_root=tmp_path, model="test")
    with pytest.raises(StructuredModelError) as raised:
        client.complete(instructions="Act", input_payload={}, output_schema={}, timeout_seconds=1)
    assert raised.value.code is code
    assert stderr in raised.value.safe_message
    assert "退出码 1" in raised.value.safe_message
    assert "PRIVATE" not in raised.value.safe_message


def test_provider_diagnostic_is_redacted_before_truncation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-" + "x" * 40
    diagnostic = (
        "PRIVATE TRANSCRIPT\n\x1b[31mError: auth token=opaque-token "
        f"{secret} mysql+pymysql://user:db-password@host/db "
        "https://host/secret-path?key=another-secret\x1b[0m " + "x" * 600
    )
    monkeypatch.setattr(
        "ai_software_engineer.agents.structured.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "PRIVATE", diagnostic),
    )
    client = CodexCliStructuredModelClient(repository_root=tmp_path, model="test")
    with pytest.raises(StructuredModelError) as raised:
        client.complete(instructions="Act", input_payload={}, output_schema={}, timeout_seconds=1)
    message = raised.value.safe_message
    assert len(message) <= 500
    assert "Error: auth" in message
    for forbidden in (secret, "opaque-token", "db-password", "another-secret", "PRIVATE", "\x1b"):
        assert forbidden not in message


@pytest.mark.parametrize("kind", ["start", "timeout", "json"])
def test_structured_process_boundary_failures_have_safe_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if kind == "start":
            raise FileNotFoundError(errno.ENOENT, "secret startup details", "/secret/path")
        if kind == "timeout":
            raise subprocess.TimeoutExpired(command, 1, output="secret", stderr="secret")
        Path(command[command.index("--output-last-message") + 1]).write_text("secret invalid JSON")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("ai_software_engineer.agents.structured.subprocess.run", run)
    client = CodexCliStructuredModelClient(repository_root=tmp_path, model="test")
    with pytest.raises(StructuredModelError) as raised:
        client.complete(instructions="Act", input_payload={}, output_schema={}, timeout_seconds=1)
    assert "secret" not in raised.value.safe_message
    expected = {
        "start": AgentErrorCode.PROVIDER_UNAVAILABLE,
        "timeout": AgentErrorCode.TIMEOUT,
        "json": AgentErrorCode.INVALID_OUTPUT,
    }
    assert raised.value.code is expected[kind]
    if kind == "start":
        assert "errno=2" in raised.value.safe_message


def test_responses_failure_keeps_http_cause_without_credentials() -> None:
    class Transport:
        def post(
            self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
        ) -> HttpResponse:
            return HttpResponse(
                status_code=403,
                body=(
                    b'{"error":{"message":"model denied for private-value; api_key=private-value"}}'
                ),
            )

    client = ResponsesStructuredModelClient(
        endpoint="https://example.invalid/v1/responses",
        api_key="private-value",
        model="test",
        transport=Transport(),
    )
    with pytest.raises(StructuredModelError) as raised:
        client.complete(instructions="Act", input_payload={}, output_schema={}, timeout_seconds=1)
    assert raised.value.code is AgentErrorCode.AUTHENTICATION_ERROR
    assert "HTTP 403" in raised.value.safe_message and "model denied" in raised.value.safe_message
    assert "private-value" not in raised.value.safe_message
