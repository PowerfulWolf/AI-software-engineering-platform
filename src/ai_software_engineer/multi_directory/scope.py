"""Read-only directory normalization; selected modules remain write boundaries."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Annotated

from pydantic import Field, StringConstraints

from ai_software_engineer.domain.model import DomainModel, NonEmptyStr

Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
UnitId = Annotated[str, StringConstraints(pattern=r"^unit_[a-f0-9]{16}$")]
Revision = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{40,64}$")]


class DirectoryUnit(DomainModel):
    id: UnitId
    root: NonEmptyStr
    selected_paths: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    base_revision: Revision | None

    def permits(self, path: str) -> bool:
        """A glob's literal directory prefix must remain within a selected module."""
        if (
            PurePosixPath(path).is_absolute()
            or "\\" in path
            or any(ord(c) < 32 for c in path)
            or any(p in {"", ".", "..", ".git"} for p in path.split("/"))
        ):
            return False
        return any(
            scope == "." or path == scope or path.startswith(scope + "/")
            for scope in self.selected_paths
        )


class DirectoryScope(DomainModel):
    units: Annotated[tuple[DirectoryUnit, ...], Field(min_length=1, max_length=32)]


def git_read(root: Path, *args: str) -> str | None:
    """No hooks, shell, inherited Git overrides, or interactive credentials."""
    result = subprocess.run(
        ("git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", *args),
        cwd=root,
        env={
            "PATH": os.defpath,
            "LANG": "C",
            "LC_ALL": "C",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def discover_scope(paths: tuple[str, ...]) -> DirectoryScope:
    if not paths or len(paths) > 32:
        raise ValueError("supply between one and 32 absolute directories")
    grouped: dict[str, set[str]] = {}
    common_roots: dict[str, str] = {}
    for raw in paths:
        if not Path(raw).is_absolute() or any(ord(c) < 32 for c in raw):
            raise ValueError("project directories must be absolute safe paths")
        root = Path(raw).resolve()
        if not root.is_dir():
            raise ValueError("project directory does not exist")
        git_root = git_read(root, "rev-parse", "--show-toplevel")
        repository = Path(git_root).resolve() if git_root else root
        common = git_read(repository, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if common:
            common = str(Path(common).resolve())
            previous = common_roots.setdefault(common, str(repository))
            if previous != str(repository):
                raise ValueError("different checkouts of the same repository are ambiguous")
        grouped.setdefault(str(repository), set()).add(root.relative_to(repository).as_posix())
    units: list[DirectoryUnit] = []
    for name, selected in sorted(grouped.items()):
        minimal = tuple(
            sorted(
                path
                for path in selected
                if not any(
                    other != path and (other == "." or path.startswith(other + "/"))
                    for other in selected
                )
            )
        )
        units.append(
            DirectoryUnit(
                id="unit_" + hashlib.sha256(name.encode()).hexdigest()[:16],
                root=name,
                selected_paths=minimal,
                base_revision=git_read(Path(name), "rev-parse", "--verify", "HEAD^{commit}"),
            )
        )
    return DirectoryScope(units=tuple(units))
