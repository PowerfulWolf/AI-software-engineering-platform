"""Read-only discovery and revalidation of a local Python/MySQL executor capability."""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

from ai_software_engineer.manager.python_verification import (
    PytestSelection,
    PythonMysqlSandboxCapability,
)
from ai_software_engineer.manager.python_verification_runner import __file__ as runner_file

_ENVIRONMENT = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_ALLOW_PROTOCOL": "",
    "GIT_TERMINAL_PROMPT": "0",
}


def _file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dependency_fingerprint(root: Path, *, max_files: int = 200_000) -> str:
    """Bind every importable byte, including .pyc (-B prevents writes, not reads)."""
    if root.resolve(strict=True) != root or not root.is_dir():
        raise ValueError("dependency tree must be a canonical real directory")
    result = hashlib.sha256()
    count = total = 0

    def scan_failed(error: OSError) -> None:
        raise ValueError("dependency tree cannot be completely fingerprinted") from error

    for directory, subdirectories, filenames in os.walk(
        root, followlinks=False, onerror=scan_failed
    ):
        for name in sorted((*subdirectories, *filenames)):
            path = Path(directory) / name
            metadata = path.lstat()
            count += 1
            if count > max_files:
                raise ValueError("dependency fingerprint exceeds its file/byte budget")
            if stat.S_ISLNK(metadata.st_mode):
                link = os.readlink(path)
                direct = Path(os.path.abspath(path.parent / link))
                target = direct.resolve(strict=True)
                if not direct.is_relative_to(root) or direct != target or not target.is_file():
                    raise ValueError("dependency symbolic link escapes its registered file tree")
                result.update(str(path.relative_to(root)).encode() + b"\0link\0")
                result.update(
                    link.encode() + b"\0" + str(target.relative_to(root)).encode() + b"\0"
                )
                # The canonical target is also visited and content-hashed below.
                continue
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("dependency tree contains a nonregular file")
            total += metadata.st_size
            if total > 2_000_000_000:
                raise ValueError("dependency fingerprint exceeds its file/byte budget")
            result.update(str(path.relative_to(root)).encode() + b"\0")
            result.update(str(stat.S_IMODE(metadata.st_mode)).encode() + b"\0")
            result.update(_file_sha256(path).encode() + b"\0")
        subdirectories.sort()
    return result.hexdigest()


def _read_command(argv: tuple[str, ...], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        argv, cwd=cwd, env=_ENVIRONMENT, capture_output=True, text=True, timeout=20, check=False
    )
    if result.returncode or len(result.stdout) > 16000:
        # Do not echo CLI diagnostics: config and environment may contain secrets.
        raise ValueError("verification host discovery failed")
    return result.stdout.strip()


def _binary(name: str) -> Path:
    found = shutil.which(name)
    if found is None:
        raise ValueError("required verification executable is unavailable")
    return Path(found).resolve(strict=True)


def require_selected_candidate_files(
    repository: Path, revision: str, selections: tuple[PytestSelection, ...]
) -> None:
    if re.fullmatch(r"[a-f0-9]{40}", revision) is None:
        raise ValueError("verification requires a full candidate commit")
    for selection in selections:
        path = selection.node_id.split("::", 1)[0]
        result = _read_command(
            ("/usr/bin/git", "-c", "core.fsmonitor=false", "ls-tree", revision, "--", path),
            cwd=repository,
        )
        if re.fullmatch(r"100(?:644|755) blob [a-f0-9]{40}\t" + re.escape(path), result) is None:
            raise ValueError("approved pytest selection is not a tracked regular candidate file")


def discover_python_mysql_capability(
    repository: Path,
    revision: str,
    selections: tuple[PytestSelection, ...],
    *,
    codex_executable: str,
    docker_executable: str = "docker",
    docker_socket: str | None = None,
    mysql_image: str = "mysql:8.0",
) -> PythonMysqlSandboxCapability:
    """No candidate evaluation, container creation, network connection, or image pull."""
    if platform.system() != "Darwin":
        raise ValueError("Python/MySQL capability requires the validated macOS sandbox")
    require_selected_candidate_files(repository, revision, selections)
    sandbox, docker = _binary(codex_executable), _binary(docker_executable)
    if docker_socket is None:
        endpoint = _read_command(
            (str(docker), "context", "inspect", "--format", "{{.Endpoints.docker.Host}}")
        )
        if not endpoint.startswith("unix://"):
            raise ValueError("verification requires a local Unix Docker daemon")
        docker_socket = endpoint.removeprefix("unix://")
    socket = Path(docker_socket).resolve(strict=True)
    if not stat.S_ISSOCK(socket.stat().st_mode):
        raise ValueError("verification Docker endpoint is not a local socket")
    with tempfile.TemporaryDirectory(prefix="ase-docker-discovery-") as directory:
        prefix = (str(docker), "--config", directory, "--host", f"unix://{socket}")
        daemon = _read_command((*prefix, "info", "--format", "{{.ID}}"))
        image = _read_command((*prefix, "image", "inspect", "--format", "{{.Id}}", mysql_image))
    python = Path(sys.executable).resolve(strict=True)
    runtime = Path(sys.base_prefix).resolve(strict=True)
    dependencies = Path(sysconfig.get_path("purelib")).resolve(strict=True)
    runner = Path(runner_file).resolve(strict=True)
    return PythonMysqlSandboxCapability(
        sandbox_executable=str(sandbox),
        sandbox_executable_sha256=_file_sha256(sandbox),
        python_executable=str(python),
        python_executable_sha256=_file_sha256(python),
        python_runtime_root=str(runtime),
        python_runtime_sha256=dependency_fingerprint(runtime),
        dependency_root=str(dependencies),
        dependency_sha256=dependency_fingerprint(dependencies),
        runner_path=str(runner),
        runner_sha256=_file_sha256(runner),
        docker_executable=str(docker),
        docker_executable_sha256=_file_sha256(docker),
        docker_socket=str(socket),
        docker_daemon_id=daemon,
        mysql_image_id=image,
        selections=selections,
    )
