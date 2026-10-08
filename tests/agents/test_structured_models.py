"""Structured upstream stages support bounded image input and safe fallback."""

import errno
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import cast

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
        self.calls = 0

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
        self.calls += 1
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
        assert "--json" in command
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(json.dumps({"result": "ok"}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("ai_software_engineer.agents.structured.run_structured_command", run)
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

    monkeypatch.setattr("ai_software_engineer.agents.structured.run_structured_command", run)
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


def test_codex_structured_proxy_uses_only_named_key_and_hides_stderr_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    commands: list[tuple[str, ...]] = []
    environments: list[dict[str, str]] = []

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        environments.append(kwargs["env"])  # type: ignore[arg-type]
        return subprocess.CompletedProcess(command, 1, "", "error: test-proxy-secret rejected")

    monkeypatch.setattr("ai_software_engineer.agents.structured.run_structured_command", run)
    client = CodexCliStructuredModelClient(
        repository_root=repository,
        model="gpt-test",
        proxy_base_url="http://127.0.0.1:8317/v1",
        proxy_api_key_env="ASE_CODEX_PROXY_API_KEY",
        environment={
            "PATH": "/usr/bin",
            "ASE_CODEX_PROXY_API_KEY": "test-proxy-secret",
            "OTHER_API_KEY": "never-forward",
        },
    )

    with pytest.raises(StructuredModelError) as error:
        client.complete(
            instructions="Return a result.",
            input_payload={},
            output_schema={"type": "object"},
            timeout_seconds=30,
        )

    command = commands[0]
    assert 'model_providers.ase_local_proxy.env_key="ASE_CODEX_PROXY_API_KEY"' in command
    assert "model_providers.ase_local_proxy.requires_openai_auth=false" in command
    assert 'shell_environment_policy.filters.ASE_CODEX_PROXY_API_KEY="exclude"' in command
    assert environments == [{"PATH": "/usr/bin", "ASE_CODEX_PROXY_API_KEY": "test-proxy-secret"}]
    assert "test-proxy-secret" not in repr(command)
    assert "test-proxy-secret" not in str(error.value)


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

    monkeypatch.setattr("ai_software_engineer.agents.structured.run_structured_command", run)
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
        "ai_software_engineer.agents.structured.run_structured_command",
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
        ("Error: 401 Missing API key", AgentErrorCode.AUTHENTICATION_ERROR),
        ("Error: HTTP 403 Forbidden", AgentErrorCode.AUTHENTICATION_ERROR),
        ("Error: service connection closed", AgentErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_structured_cli_failure_preserves_safe_cause_not_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stderr: str, code: AgentErrorCode
) -> None:
    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "PROMPT usage limit PRIVATE", stderr)

    monkeypatch.setattr("ai_software_engineer.agents.structured.run_structured_command", run)
    client = CodexCliStructuredModelClient(repository_root=tmp_path, model="test")
    with pytest.raises(StructuredModelError) as raised:
        client.complete(instructions="Act", input_payload={}, output_schema={}, timeout_seconds=1)
    assert raised.value.code is code
    assert raised.value.transient is (code is not AgentErrorCode.AUTHENTICATION_ERROR)
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
        "ai_software_engineer.agents.structured.run_structured_command",
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

    monkeypatch.setattr("ai_software_engineer.agents.structured.run_structured_command", run)
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


def test_local_cli_execution_limit_does_not_switch_provider_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, cast(int, kwargs["timeout"]))

    monkeypatch.setattr("ai_software_engineer.agents.structured.run_structured_command", run)
    backup = _StaticClient()
    first = CodexCliStructuredModelClient(repository_root=tmp_path, model="test")
    client = FallbackStructuredModelClient(
        (
            StructuredModelRoute("codex", "first", first),
            StructuredModelRoute("backup", "next", backup),
        )
    )
    with pytest.raises(StructuredModelError) as raised:
        client.complete(instructions="Act", input_payload={}, output_schema={}, timeout_seconds=600)
    assert raised.value.timeout_kind == "local_execution_limit"
    assert not raised.value.retryable
    assert backup.calls == 0


@pytest.mark.parametrize(
    "diagnostic", ["login authentication 401", "quota exceeded 429", "HTTP 504"]
)
@pytest.mark.parametrize("timed_out", [True, False])
def test_cli_transcript_is_not_provider_failure_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, diagnostic: str, timed_out: bool
) -> None:
    transcript = f"user\nWrite tests for {diagnostic}\nthinking\nInspecting tests.\n"

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if timed_out:
            raise subprocess.TimeoutExpired(
                command, cast(int, kwargs["timeout"]), stderr=transcript
            )
        return subprocess.CompletedProcess(command, 1, "", transcript)

    monkeypatch.setattr("ai_software_engineer.agents.structured.run_structured_command", run)
    client = CodexCliStructuredModelClient(repository_root=tmp_path, model="test")
    with pytest.raises(StructuredModelError) as raised:
        client.complete(instructions="Act", input_payload={}, output_schema={}, timeout_seconds=1)
    if timed_out:
        assert raised.value.code is AgentErrorCode.TIMEOUT
        assert raised.value.timeout_kind == "local_execution_limit"
        assert not raised.value.retryable
    else:
        assert raised.value.code is AgentErrorCode.PROVIDER_UNAVAILABLE
    assert diagnostic not in raised.value.safe_message


@pytest.mark.parametrize("timed_out", [True, False])
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, AgentErrorCode.AUTHENTICATION_ERROR),
        (403, AgentErrorCode.AUTHENTICATION_ERROR),
        (429, AgentErrorCode.RATE_LIMITED),
        (504, AgentErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_cli_json_provider_events_are_classified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    timed_out: bool,
    status: int,
    expected: AgentErrorCode,
) -> None:
    output = json.dumps(
        {"type": "turn.failed", "error": {"message": f"unexpected status {status}"}}
    )

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if timed_out:
            raise subprocess.TimeoutExpired(command, 1, output=output, stderr="")
        return subprocess.CompletedProcess(command, 1, output, "")

    monkeypatch.setattr("ai_software_engineer.agents.structured.run_structured_command", run)
    client = CodexCliStructuredModelClient(repository_root=tmp_path, model="test")
    with pytest.raises(StructuredModelError) as raised:
        client.complete(instructions="Act", input_payload={}, output_schema={}, timeout_seconds=1)
    assert raised.value.code is expected
    assert raised.value.retryable is (status not in {401, 403})


def test_cli_json_model_text_is_not_a_provider_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": "Error: authentication 401 quota exceeded 429 HTTP 504",
            },
        }
    )

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, 1, output=output, stderr="")

    monkeypatch.setattr("ai_software_engineer.agents.structured.run_structured_command", run)
    client = CodexCliStructuredModelClient(repository_root=tmp_path, model="test")
    with pytest.raises(StructuredModelError) as raised:
        client.complete(instructions="Act", input_payload={}, output_schema={}, timeout_seconds=1)
    assert raised.value.timeout_kind == "local_execution_limit"


def test_cli_timeout_with_explicit_provider_failure_uses_transient_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, cast(int, kwargs["timeout"]), stderr=b"HTTP 504")

    monkeypatch.setattr("ai_software_engineer.agents.structured.run_structured_command", run)
    backup = _StaticClient()
    client = FallbackStructuredModelClient(
        (
            StructuredModelRoute(
                "codex",
                "first",
                CodexCliStructuredModelClient(repository_root=tmp_path, model="test"),
            ),
            StructuredModelRoute("backup", "next", backup),
        )
    )
    result = client.complete(
        instructions="Act", input_payload={}, output_schema={}, timeout_seconds=600
    )
    assert result.provider == "backup"
    assert backup.calls == 1


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
