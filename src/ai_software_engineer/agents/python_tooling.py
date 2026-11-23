"""Project Python for platform-run role commands (Responses and Claude CLI routes).

Role commands otherwise resolve ``python3`` from the service PATH, which on macOS
is the system interpreter without the project's dependencies, so a Coder could
neither import the code it changes nor run its tests. The Codex route already
binds the registered checkout's ``.venv`` through fixed isolated launchers; this
module reuses exactly those launchers and puts them first on the command PATH.
"""

from __future__ import annotations

import os
import shlex
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ai_software_engineer.agents.codex_cli import (
    _NativePythonTooling,
    _prepare_coder_python_launchers,
    _registered_project_root,
    _registered_python_dependencies,
    _registered_python_executable,
)


@contextmanager
def project_python_path(workspace_root: Path) -> Iterator[str | None]:
    """Yield a PATH prefix with project python/python3/pytest/mypy/ruff, or None."""
    project_root = _registered_project_root(workspace_root)
    if project_root is None:
        yield None
        return
    python = _registered_python_executable(project_root, "python") or _venv_interpreter(
        project_root
    )
    dependencies = _registered_python_dependencies(project_root)
    if python is None or not dependencies:
        yield None
        return
    pytest = _registered_python_executable(project_root, "pytest")
    source = workspace_root / "src"
    source_paths = (
        (source, workspace_root)
        if source.is_dir() and not source.is_symlink()
        else (workspace_root,)
    )
    with tempfile.TemporaryDirectory(prefix="ase-role-python-") as directory:
        root = Path(directory).resolve(strict=True)
        caches = root / "caches"
        (caches / "mypy").mkdir(parents=True, mode=0o700)
        (caches / "pytest").mkdir(parents=True, mode=0o700)
        launchers = _prepare_coder_python_launchers(
            _NativePythonTooling(
                pytest=pytest,
                python=python,
                source_paths=source_paths,
                dependency_paths=dependencies,
            ),
            root,
            mypy_cache_root=caches / "mypy",
            pytest_cache_root=caches / "pytest",
        )
        if launchers is None or launchers.python is None:
            yield None
            return
        binaries = root / "bin"
        binaries.mkdir(mode=0o700)
        python_launcher = shlex.quote(str(launchers.python))
        scripts = {
            "python": f'exec {python_launcher} "$@"',
            "python3": f'exec {python_launcher} "$@"',
            "mypy": f'exec {python_launcher} -m mypy "$@"',
        }
        if launchers.pytest is not None:
            scripts["pytest"] = f'exec {shlex.quote(str(launchers.pytest))} "$@"'
        ruff = _registered_python_executable(project_root, "ruff")
        if ruff is not None:
            scripts["ruff"] = f'exec {shlex.quote(str(ruff))} "$@"'
        for name, body in scripts.items():
            path = binaries / name
            path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
            path.chmod(0o700)
        yield str(binaries)


def _venv_interpreter(project_root: Path) -> Path | None:
    """The base interpreter a venv's ``bin/python`` link points to.

    The launcher starts it isolated (-I -S) and adds only the venv's single
    site-packages root, so following the link does not widen what is imported.
    """
    environment = project_root / ".venv"
    link = environment / "bin" / "python"
    if environment.is_symlink() or not environment.is_dir():
        return None
    try:
        target = link.resolve(strict=True)
    except OSError:
        return None
    if not target.is_file() or not os.access(target, os.X_OK):
        return None
    return target


__all__ = ["project_python_path"]
