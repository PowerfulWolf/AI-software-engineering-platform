"""Resolve successor native bodies from the exact already-approved Git profile."""

import hashlib
import os
import re
import subprocess
from pathlib import Path

from ai_software_engineer.context.models import ContextSource
from ai_software_engineer.redaction import redact_text
from ai_software_engineer.repository_profile import RepositoryProfile


def rebind_native_rule_sources(
    repository_root: Path,
    profile: RepositoryProfile,
    sources: tuple[ContextSource, ...],
) -> tuple[ContextSource, ...]:
    """Keep source scopes/identity, but use the successor's sealed native revision.

    Recovery can approve a newer preparation than the original Requirement. Its
    baseline cannot be paired with the parent's older native bodies. No current
    checkout reads, historical record writes, or changed-hash exceptions are allowed.
    Absent bodies stay absent so historical omissions remain explicit.
    """
    profile.validate_integrity()
    references = {item.uri: item for item in profile.native_rules}
    result = []
    for source in sources:
        if not source.source_id.startswith("native.rule."):
            result.append(source)
            continue
        reference = references.get(source.uri)
        if reference is None:
            raise ValueError("native rule is not in the sealed profile")
        revision = profile.vcs.revision
        if revision is None or re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", revision) is None:
            raise ValueError("native rule requires a sealed Git revision")
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
