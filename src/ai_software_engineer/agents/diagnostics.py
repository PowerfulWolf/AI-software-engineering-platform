"""Bounded diagnostics, not a transport for provider transcripts or credentials."""

import json
import re

from ai_software_engineer.redaction import redact_text


def safe_diagnostic(text: str, *, limit: int = 500) -> str:
    """Clean complete values before truncating, including credential-bearing URLs."""
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", text)
    text = redact_text(text).text
    text = re.sub(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>\"']+", "[REDACTED:URL]", text)
    text = " ".join("".join(c if c.isprintable() else " " for c in text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def provider_error_detail(stderr: str) -> str:
    """Take only a diagnostic line, never stdout, prompts, or a whole CLI transcript."""
    # Redact before selecting a line so a multiline private key cannot be split open.
    cleaned = redact_text(stderr).text
    cleaned = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", cleaned)
    for line in reversed(cleaned.splitlines()):
        if re.match(r"^\s*(?:error|fatal)(?:\s|:|\[)", line, re.IGNORECASE):
            return safe_diagnostic(line, limit=240)
    return "未获得可安全展示的错误详情"


def http_error_detail(body: bytes, api_key: str) -> str:
    """Expose only a bounded, redacted structured error message, never a raw body."""
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        return "未获得结构化服务错误详情"
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        message = payload["error"].get("message")
        if isinstance(message, str):
            return safe_diagnostic(message.replace(api_key, "[REDACTED:api_key]"), limit=240)
    return "未获得结构化服务错误详情"
