"""Shared deterministic secret redaction for Context and durable evidence."""

import re
from dataclasses import dataclass
from typing import Final

_SECRET_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{19,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("bearer_token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")),
    (
        "secret_assignment",
        re.compile(
            r"""(?i)(["']?\b(?:password|passwd|secret|token|api[_-]?key)\b["']?\s*[:=]\s*["']?)([^\s,;"'}]+)(["']?)"""
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class RedactionOccurrence:
    """One redaction kind and replacement count."""

    kind: str
    count: int


@dataclass(frozen=True, slots=True)
class RedactedText:
    """Safe text plus non-secret replacement counts."""

    text: str
    occurrences: tuple[RedactionOccurrence, ...]


def redact_text(content: str) -> RedactedText:
    """Replace supported secret shapes without retaining original values."""
    redacted = content
    occurrences: list[RedactionOccurrence] = []
    for kind, pattern in _SECRET_PATTERNS:
        replacement = (
            rf"\1[REDACTED:{kind}]\3" if kind == "secret_assignment" else f"[REDACTED:{kind}]"
        )
        redacted, count = pattern.subn(replacement, redacted)
        if count:
            occurrences.append(RedactionOccurrence(kind=kind, count=count))
    return RedactedText(text=redacted, occurrences=tuple(occurrences))


__all__ = ["RedactedText", "RedactionOccurrence", "redact_text"]
