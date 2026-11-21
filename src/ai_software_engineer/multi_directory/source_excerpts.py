"""Exact repository file excerpts for upstream Designer and Planner calls.

The structured Designer has no file tools. Without the files a requirement names,
it can only report "source evidence is missing" and burn its retry budget. This
supplies a bounded, redacted, revision-pinned copy of those files as data.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from ai_software_engineer.domain.model import JsonValue
from ai_software_engineer.multi_directory.scope import DirectoryScope
from ai_software_engineer.redaction import redact_text

MAX_EXCERPT_FILES = 12
MAX_EXCERPT_FILE_BYTES = 48_000
MAX_EXCERPT_TOTAL_BYTES = 120_000

_PATH = re.compile(
    r"(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.(?:md|py|sh|json|toml|ya?ml|js|cjs|mjs|ts|tsx|txt|cfg|ini|swift|sql|css|html))(?![\w/-])"
)


def candidate_paths(texts: Iterable[str]) -> tuple[str, ...]:
    """Repository-relative file paths named in approved text, in first-seen order."""
    seen: dict[str, None] = {}
    for text in texts:
        for match in _PATH.finditer(text):
            path = match.group(1).removeprefix("./")
            parts = PurePosixPath(path).parts
            if (
                path.startswith("/")
                or not parts
                or any(part in {"", ".", "..", ".git"} for part in parts)
            ):
                continue
            seen.setdefault(path, None)
    return tuple(seen)


def _git_blob(root: Path, revision: str, path: str) -> bytes | None:
    # Excerpts are best-effort evidence: a missing checkout or a failed read
    # leaves the file out instead of failing the stage.
    if not root.is_dir():
        return None
    try:
        result = subprocess.run(
            (
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "show",
                f"{revision}:{path}",
            ),
            cwd=root,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "LC_ALL": "C"},
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def source_excerpts(scope: DirectoryScope, texts: Iterable[str]) -> list[JsonValue]:
    """Exact, redacted file contents at each unit's pinned base revision."""
    paths = candidate_paths(texts)
    excerpts: list[JsonValue] = []
    total = 0
    for path in paths:
        if len(excerpts) >= MAX_EXCERPT_FILES or total >= MAX_EXCERPT_TOTAL_BYTES:
            break
        for unit in scope.units:
            if unit.base_revision is None or not unit.permits(path):
                continue
            blob = _git_blob(Path(unit.root), unit.base_revision, path)
            if blob is None or b"\0" in blob[:8192]:
                continue
            budget = min(MAX_EXCERPT_FILE_BYTES, MAX_EXCERPT_TOTAL_BYTES - total)
            truncated = len(blob) > budget
            text = blob[:budget].decode("utf-8", errors="replace")
            safe = redact_text(text).text
            total += len(safe.encode())
            excerpts.append(
                {
                    "unit_id": unit.id,
                    "path": path,
                    "revision": unit.base_revision,
                    "blob_sha256": hashlib.sha256(blob).hexdigest(),
                    "bytes": len(blob),
                    "truncated": truncated,
                    "content": safe,
                }
            )
            break
    return excerpts


def excerpt_texts(*values: object) -> tuple[str, ...]:
    """Flatten approved wire values into text for path discovery."""
    return tuple(
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        for value in values
        if value is not None
    )
