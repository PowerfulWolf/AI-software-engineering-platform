"""Validated, explicit local transport for production Codex CLI invocations."""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

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


def codex_cli_proxy_overrides(base_url: str | None) -> tuple[str, ...]:
    """Build fixed TOML overrides while preserving --ignore-user-config."""
    if base_url is None:
        return ()
    safe_url = normalize_local_codex_proxy_base_url(base_url)
    return (
        "-c",
        'model_provider="ase_local_proxy"',
        "-c",
        'model_providers.ase_local_proxy.name="ASE local proxy"',
        "-c",
        f"model_providers.ase_local_proxy.base_url={json.dumps(safe_url)}",
        "-c",
        'model_providers.ase_local_proxy.wire_api="responses"',
        "-c",
        "model_providers.ase_local_proxy.requires_openai_auth=true",
    )
