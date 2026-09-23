"""Validated, explicit local transport for production Codex CLI invocations."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from urllib.parse import urlsplit

CODEX_PROXY_API_KEY_ENV = "ASE_CODEX_PROXY_API_KEY"

_LOCAL_PROXY_URL = re.compile(
    r"^http://(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]+)?"
    r"(?:/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*)?$"
)


def normalize_local_codex_proxy_base_url(value: str) -> str:
    """Accept only a secret-free loopback HTTP base URL."""
    if not value or len(value) > 2048 or _LOCAL_PROXY_URL.fullmatch(value) is None:
        raise ValueError("Codex CLI proxy must be a safe loopback HTTP URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError("Codex CLI proxy must be a safe loopback HTTP URL") from error
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.netloc.endswith(":")
        or (port is not None and port < 1)
    ):
        raise ValueError("Codex CLI proxy must be a safe loopback HTTP URL")
    return value


def codex_cli_proxy_overrides(
    base_url: str | None, api_key_env: str | None = None
) -> tuple[str, ...]:
    """Build fixed TOML overrides while preserving --ignore-user-config."""
    if base_url is None:
        if api_key_env is not None:
            raise ValueError("Codex CLI proxy key requires a proxy URL")
        return ()
    safe_url = normalize_local_codex_proxy_base_url(base_url)
    if api_key_env is not None and api_key_env != CODEX_PROXY_API_KEY_ENV:
        raise ValueError("Codex CLI proxy key environment name is invalid")
    overrides = (
        "-c",
        'model_provider="ase_local_proxy"',
        "-c",
        'model_providers.ase_local_proxy.name="ASE local proxy"',
        "-c",
        f"model_providers.ase_local_proxy.base_url={json.dumps(safe_url)}",
        "-c",
        'model_providers.ase_local_proxy.wire_api="responses"',
    )
    if api_key_env is None:
        return (
            *overrides,
            "-c",
            "model_providers.ase_local_proxy.requires_openai_auth=true",
        )
    return (
        *overrides,
        "-c",
        "model_providers.ase_local_proxy.requires_openai_auth=false",
        "-c",
        f"model_providers.ase_local_proxy.env_key={json.dumps(api_key_env)}",
        "-c",
        "shell_environment_policy.ignore_default_excludes=false",
        "-c",
        f'shell_environment_policy.filters.{api_key_env}="exclude"',
    )


def codex_cli_proxy_key_environment(
    source: Mapping[str, str], api_key_env: str | None
) -> dict[str, str]:
    """Pass only the explicitly configured key to the Codex process itself."""
    if api_key_env is None:
        return {}
    if api_key_env != CODEX_PROXY_API_KEY_ENV:
        raise ValueError("Codex CLI proxy key environment name is invalid")
    value = source.get(api_key_env)
    if not value:
        raise ValueError("Codex CLI proxy API key is not configured")
    return {api_key_env: value}
