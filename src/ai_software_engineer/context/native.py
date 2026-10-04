"""Resolve successor native bodies from the exact already-approved Git profile."""

import hashlib
import os
import re
import subprocess
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from ai_software_engineer.context.models import ContextSource
from ai_software_engineer.context.ports import ContextSourceError
from ai_software_engineer.redaction import redact_text
from ai_software_engineer.repository_profile import RepositoryProfile


def native_rule_prompt_sources(sources: tuple[ContextSource, ...]) -> tuple[ContextSource, ...]:
    """Project frozen rules for a prompt paired with active knowledge retrieval.

    The knowledge snapshot must still consume the original sources. Preserve all
    AGENTS instructions; other bodies remain available in the frozen search/read
    corpus. This projection is never persisted back into approved preparation.
    """
    projected = []
    for source in sources:
        if not source.source_id.startswith("native.rule."):
            projected.append(source)
            continue
        if source.content is None:
            raise ContextSourceError("native prompt projection requires frozen inline content")
        if PurePosixPath(urlparse(source.uri).path).name.lower() == "agents.md":
            projected.append(source)
            continue
        safe = redact_text(source.content).text
        content = (
            "Project-native rule reference; full body remains in the frozen knowledge snapshot. "
            f"URI={redact_text(source.uri).text}; "
            f"frozen_redacted_sha256={hashlib.sha256(safe.encode('utf-8')).hexdigest()}. "
            "Consult applicable rules before editing or verifying. Verified retrieved passages "
            "are supplied in knowledge.reads; references alone do not supply the rule text. "
            "Report missing required rules rather than inferring their contents."
        )
        projected.append(
            source.model_copy(
                update={
                    "source_id": source.source_id.replace("native.rule.", "native.reference.", 1),
                    "content": content,
                }
            )
        )
    return tuple(projected)


def rebind_native_rule_sources(
    repository_root: Path,
    profile: RepositoryProfile,
    sources: tuple[ContextSource, ...],
    *,
    source_revision: str | None = None,
) -> tuple[ContextSource, ...]:
    """Keep source scopes/identity, but use the successor's sealed native revision.

    Recovery can approve a newer preparation than the original Requirement. Its
    baseline cannot be paired with the parent's older native bodies. No current
    checkout reads, historical record writes, or changed-hash exceptions are allowed.
    Absent bodies stay absent so historical omissions remain explicit.
    """
    profile.validate_integrity()
    if not any(source.source_id.startswith("native.rule.") for source in sources):
        return sources
    revision = source_revision or profile.vcs.revision
    if revision is None or re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", revision) is None:
        raise ValueError("native rule requires a sealed Git revision")
    if profile.vcs.revision not in {None, "unknown", revision}:
        raise ValueError("native rule revision differs from the sealed profile")
    references = {item.uri: item for item in profile.native_rules}
    result = []
    for source in sources:
        if not source.source_id.startswith("native.rule."):
            result.append(source)
            continue
        reference = references.get(source.uri)
        if reference is None:
            raise ValueError("native rule is not in the sealed profile")
        if reference.byte_length > 256_000:
            raise ValueError("native rule exceeds context limit")
        object_name = f"{revision}:{reference.relative_path}"
        size = _git_object(repository_root, "-s", object_name)
        if size.strip() != str(reference.byte_length).encode("ascii"):
            raise ValueError("native rule differs from the sealed profile")
        data = _git_object(repository_root, "blob", object_name)
        if (
            len(data) != reference.byte_length
            or hashlib.sha256(data).hexdigest() != reference.sha256
        ):
            raise ValueError("native rule differs from the sealed profile")
        content = redact_text(data.decode("utf-8")).text
        result.append(source.model_copy(update={"content": content, "relative_path": None}))
    return tuple(result)


def _git_object(root: Path, mode: str, object_name: str) -> bytes:
    try:
        result = subprocess.run(
            (
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "cat-file",
                mode,
                object_name,
            ),
            cwd=root,
            env={
                "PATH": os.defpath,
                "LANG": "C",
                "LC_ALL": "C",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_NO_REPLACE_OBJECTS": "1",
            },
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("sealed native rule could not be read") from error
    if result.returncode:
        raise ValueError("sealed native rule could not be read")
    return result.stdout
