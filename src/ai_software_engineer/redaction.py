"""Shared deterministic secret redaction for Context and durable evidence."""

import ast
import io
import re
import shlex
import textwrap
import tokenize
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Final, Literal

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

# A source snapshot is code, rather than a log or a URI.  These are the only
# assignment RHS forms that may be treated as references while checking a
# complete source file.  In particular, arbitrary identifiers and dotted
# values remain sensitive: ``token=my.jwt.secret`` may be a real credential.
_SOURCE_REFERENCE_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(
    r"(?i)(?P<field>\b(?:password|passwd|secret|token|api[_-]?key)\b)\s*=\s*"
    r"(?P<expression>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+|"
    r"[A-Za-z_]\w*\s*/\s*[\"'][^\"'\r\n]+[\"'])"
    r"(?=\s*(?:[,;\)\]\}]|\r?$|#))",
    re.MULTILINE,
)


def _source_reference(match: re.Match[str]) -> str:
    """Only recognize semantic field references or an explicit file path.

    An arbitrary dotted value is not enough. The terminal attribute must be
    the same field as the assigned argument, and its object must be a single
    name. Path construction requires a filename extension or a path separator.
    No call, indexing, arithmetic other than path division, or interpolation
    is accepted. The full original input is separately checked for key shapes.
    """
    try:
        expression = ast.parse(match["expression"], mode="eval").body
    except (SyntaxError, ValueError, RecursionError, MemoryError, OverflowError):
        return match[0]
    if (
        isinstance(expression, ast.Attribute)
        and isinstance(expression.value, ast.Name)
        and expression.attr.casefold().replace("_", "-")
        == match["field"].casefold().replace("_", "-")
    ) or (
        isinstance(expression, ast.BinOp)
        and isinstance(expression.op, ast.Div)
        and isinstance(expression.left, ast.Name)
        and isinstance(expression.right, ast.Constant)
        and isinstance(expression.right.value, str)
        and re.search(r"(?:[./\\\\])", expression.right.value)
        and not redact_text(expression.right.value).occurrences
    ):
        return "source_reference"
    return match[0]


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


_MAX_INSPECTION_ENTRIES = 512
_MAX_INSPECTION_BYTES = 16 * 1024 * 1024


@dataclass(slots=True)
class _SourceInspectionCache:
    # Full text equality is required; path controls the conservative language
    # exception. Only immutable detection facts, never a domain approval, are reused.
    facts: dict[
        tuple[Literal["source", "patch"], str | None, str], tuple[RedactionOccurrence, ...]
    ] = field(default_factory=dict)
    bytes: int = 0

    def remember(
        self,
        key: tuple[Literal["source", "patch"], str | None, str],
        facts: tuple[RedactionOccurrence, ...],
    ) -> None:
        if len(self.facts) >= _MAX_INSPECTION_ENTRIES:
            return
        # Avoid a large temporary encoding for keys already over the byte bound.
        if len(key[2]) + len(key[1] or "") > _MAX_INSPECTION_BYTES - self.bytes:
            return
        try:
            size = len(key[2].encode("utf-8")) + len((key[1] or "").encode("utf-8"))
        except UnicodeEncodeError:
            # Memoization cannot add a new rejection to the original detector.
            return
        if self.bytes + size <= _MAX_INSPECTION_BYTES:
            self.facts[key] = facts
            self.bytes += size


_SOURCE_INSPECTION_CACHE: ContextVar[_SourceInspectionCache | None] = ContextVar(
    "source_inspection_cache", default=None
)


@contextmanager
def source_inspection_scope() -> Iterator[None]:
    """Bound repeated pure source/patch scans to one synchronous read lifetime."""
    if _SOURCE_INSPECTION_CACHE.get() is not None:
        yield
        return
    token = _SOURCE_INSPECTION_CACHE.set(_SourceInspectionCache())
    try:
        yield
    finally:
        _SOURCE_INSPECTION_CACHE.reset(token)


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


def source_secret_occurrences(
    content: str, *, source_path: str | None = None
) -> tuple[RedactionOccurrence, ...]:
    """Inspect complete source, reusing only pure facts within an explicit read scope."""
    cache = _SOURCE_INSPECTION_CACHE.get()
    key: tuple[Literal["source", "patch"], str | None, str] = ("source", source_path, content)
    if cache is not None and (found := cache.facts.get(key)) is not None:
        return found
    result = _inspect_source(content, source_path=source_path)
    if cache is not None:
        cache.remember(key, result)
    return result


def _inspect_source(
    content: str, *, source_path: str | None = None
) -> tuple[RedactionOccurrence, ...]:
    """Check bounded source while preserving safe reference expressions.

    Complete retained source must remain byte-for-byte identical.  We therefore
    replace only the narrowly recognized reference spans in a temporary value,
    run the ordinary conservative detector, and return occurrence facts only.
    No raw sensitive text is returned as a supposedly redacted value. The generic detector remains
    unchanged for every other text boundary.
    """
    detected = redact_text(content).occurrences
    if not any(occurrence.kind == "secret_assignment" for occurrence in detected):
        return detected
    if (
        source_path is None
        or not source_path.endswith(".py")
        or redact_text(source_path).occurrences
    ):
        return detected
    try:
        # Syntax is inspected, never evaluated. Unknown/incomplete source gets
        # no exception; quotes/comments cannot manufacture a field reference.
        ast.parse(content)
        tokens = tuple(tokenize.generate_tokens(io.StringIO(content).readline))
    except (
        SyntaxError,
        ValueError,
        tokenize.TokenError,
        IndentationError,
        RecursionError,
        MemoryError,
        OverflowError,
    ):
        return redact_text(content).occurrences
    lines = content.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    excluded: list[tuple[int, int]] = []
    interpolated: list[int] = []
    for token in tokens:
        start = offsets[token.start[0] - 1] + token.start[1]
        end = offsets[token.end[0] - 1] + token.end[1]
        kind = tokenize.tok_name[token.type]
        if kind in {"FSTRING_START", "TSTRING_START"}:
            interpolated.append(start)
        elif kind in {"FSTRING_END", "TSTRING_END"} and interpolated:
            beginning = interpolated.pop()
            excluded.append((beginning, end))
        elif token.type in {tokenize.STRING, tokenize.COMMENT}:
            excluded.append((start, end))
    excluded.sort()
    excluded_index = 0

    def protect(match: re.Match[str]) -> str:
        nonlocal excluded_index
        while excluded_index < len(excluded) and excluded[excluded_index][1] <= match.start():
            excluded_index += 1
        if excluded_index < len(excluded) and excluded[excluded_index][0] <= match.start():
            return match[0]
        return _source_reference(match)

    # Never mask a credential inside an otherwise valid reference/path span.
    strong = tuple(
        RedactionOccurrence(kind=kind, count=len(pattern.findall(content)))
        for kind, pattern in _SECRET_PATTERNS
        if kind != "secret_assignment" and pattern.search(content)
    )
    protected = _SOURCE_REFERENCE_ASSIGNMENT.sub(protect, content)
    assignments = tuple(
        occurrence
        for occurrence in redact_text(protected).occurrences
        if occurrence.kind == "secret_assignment"
    )
    return (*strong, *assignments)


def patch_secret_occurrences(content: str) -> tuple[RedactionOccurrence, ...]:
    """Inspect complete hunks with a separate, read-scoped patch cache namespace."""
    cache = _SOURCE_INSPECTION_CACHE.get()
    key: tuple[Literal["source", "patch"], str | None, str] = ("patch", None, content)
    if cache is not None and (found := cache.facts.get(key)) is not None:
        return found
    result = _inspect_patch(content)
    if cache is not None:
        cache.remember(key, result)
    return result


def _inspect_patch(content: str) -> tuple[RedactionOccurrence, ...]:
    """Inspect code hunk sides separately; headers and unknown patches stay generic.

    Never infer a language from arbitrary leading +/- characters. Only explicit
    Git diff headers and real hunk headers select the supported Python mode.
    Partial hunks that cannot be parsed remain conservatively sensitive.
    """
    metadata: list[str] = []
    old_lines: list[str] = []
    new_lines: list[str] = []
    paths: tuple[str, str] | None = None
    in_hunk = False
    remaining: tuple[int, int] | None = None
    invalid = False
    occurrences: list[RedactionOccurrence] = []

    def flush() -> None:
        nonlocal invalid, remaining
        if remaining is not None and remaining != (0, 0):
            invalid = True
        remaining = None
        for body, path in (
            (old_lines, paths[0] if paths else None),
            (new_lines, paths[1] if paths else None),
        ):
            if body:
                occurrences.extend(
                    source_secret_occurrences(textwrap.dedent("".join(body)), source_path=path)
                )
        old_lines.clear()
        new_lines.clear()

    for line in content.splitlines(keepends=True):
        if line.startswith("diff --git "):
            flush()
            in_hunk = False
            try:
                names = shlex.split(line.rstrip("\r\n"))
                paths = (
                    (names[2][2:], names[3][2:])
                    if len(names) == 4 and names[2].startswith("a/") and names[3].startswith("b/")
                    else None
                )
            except ValueError:
                paths = None
            metadata.append(line)
        elif match := re.match(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@(?:\r?\n)?$", line):
            flush()
            in_hunk = paths is not None
            if any(value is not None and len(value) > 7 for value in (match[1], match[2])):
                return redact_text(content).occurrences
            remaining = (
                int(match[1]) if match[1] is not None else 1,
                int(match[2]) if match[2] is not None else 1,
            )
            metadata.append(line)
        elif in_hunk and line[:1] in {"+", "-", " "}:
            if remaining is None:
                invalid = True
            else:
                remaining = (
                    remaining[0] - (line[0] != "+"),
                    remaining[1] - (line[0] != "-"),
                )
                if min(remaining) < 0:
                    invalid = True
            if line[0] != "+":
                old_lines.append(line[1:])
            if line[0] != "-":
                new_lines.append(line[1:])
        elif in_hunk and line.startswith("\\ No newline at end of file"):
            pass
        else:
            flush()
            in_hunk = False
            metadata.append(line)
    flush()
    if invalid:
        return redact_text(content).occurrences
    occurrences.extend(redact_text("".join(metadata)).occurrences)
    return tuple(occurrences)


__all__ = [
    "RedactedText",
    "RedactionOccurrence",
    "patch_secret_occurrences",
    "redact_text",
    "source_secret_occurrences",
]
