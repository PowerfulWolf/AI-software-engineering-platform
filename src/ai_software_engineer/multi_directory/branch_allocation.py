"""Give each Requirement its own Coder branch even when Product names collide."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from ai_software_engineer.domain.branch import BranchName

_MAX_QUALIFIER = 30


def repository_branches(roots: Iterable[str]) -> frozenset[str]:
    """Local branch names in each repository; an unreadable root contributes none."""
    names: set[str] = set()
    for root in roots:
        path = Path(root)
        if not path.is_dir():
            continue
        try:
            completed = subprocess.run(
                (
                    "git",
                    "-c",
                    "core.fsmonitor=false",
                    "-C",
                    str(path),
                    "for-each-ref",
                    "--format=%(refname:short)",
                    "refs/heads",
                ),
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if completed.returncode == 0:
            names.update(line.strip() for line in completed.stdout.splitlines() if line.strip())
    return frozenset(names)


def unique_branch_name(name: str, taken: frozenset[str]) -> str:
    """Return ``name`` or the first free ``name-N`` that is still a valid BranchName.

    Product names a branch by business meaning, so two Requirements touching the
    same feature (or a retried Requirement after a closed one) propose the same
    name. A closed Requirement's branch is retained history, so the new one gets a
    numeric qualifier instead of colliding at Coder start.
    """
    if name not in taken:
        return name
    adapter = TypeAdapter(BranchName)
    for qualifier in range(2, _MAX_QUALIFIER + 1):
        candidate = f"{name}-{qualifier}"
        if candidate in taken:
            continue
        try:
            return adapter.validate_python(candidate)
        except ValidationError:
            break
    raise ValueError("no free branch name for this Requirement; close or purge older branches")
