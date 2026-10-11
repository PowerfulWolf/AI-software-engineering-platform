"""Coder mypy defaults use private scratch without weakening source inventory."""

import os
import shutil
import subprocess
import sys
import sysconfig
import venv
from collections.abc import Callable, Mapping
from importlib.metadata import distribution
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentRequest,
    AgentResult,
    AgentRunStatus,
    CodexCliAgentAdapter,
    CodexInvocationResult,
)
from ai_software_engineer.agents.codex_cli import CodexCliError
from ai_software_engineer.domain import AgentRole
from ai_software_engineer.git.mutation import (
    MAX_INVENTORY_FILE_BYTES,
    MutationInventoryRejected,
    capture_mutation_inventory,
    is_execution_cache_path,
)
from tests.agents.test_codex_cli import _git
from tests.agents.test_native_python_tooling import _fake_tools, _project, _ToolProbeRunner
from tests.agents.test_openai_compatible import StaticPromptBuilder, _coder_request, _request


def _run_coder(
    worktree: Path,
    base: str,
    probe: Callable[[Path, Mapping[str, str], str], None],
) -> AgentResult:
    request = _coder_request().model_copy(update={"source_revision": base})
    return CodexCliAgentAdapter(
        workspace_root=worktree,
        model="gpt-test",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        environment={
            "PATH": os.environ["PATH"],
            "MYPY_CACHE_DIR": "/untrusted/host-cache",
        },
        prompt_builder=StaticPromptBuilder(),
        runner=_ToolProbeRunner(request, probe, None),
    ).run(request)


@pytest.mark.parametrize("failure", [False, True])
def test_each_coder_call_owns_fresh_cache_and_cleans_it_on_exit(
    tmp_path: Path, failure: bool
) -> None:
    roots: list[Path] = []
    for index in range(2):
        fixture = tmp_path / str(index)
        fixture.mkdir()
        registered, worktree, base = _project(fixture)
        _fake_tools(registered)

        def probe(
            cwd: Path,
            environment: Mapping[str, str],
            prompt: str,
            *,
            registered_root: Path = registered,
        ) -> None:
            del prompt
            cache = Path(environment["MYPY_CACHE_DIR"])
            assert cache.is_dir()
            assert cache.stat().st_mode & 0o777 == 0o700
            assert cache.parent == Path(environment["TMPDIR"]).parent
            assert not cache.is_relative_to(cwd)
            assert not cache.is_relative_to(registered_root)
            assert not cache.is_relative_to(Path(environment["ASE_PROJECT_PYTHON"]).parent)
            roots.append(cache)
            (cache / "cache.db").write_bytes(b"private cache")
            if failure:
                raise CodexCliError("fixture runner could not start")

        result = _run_coder(worktree, base, probe)
        assert result.status is (AgentRunStatus.FAILED if failure else AgentRunStatus.SUCCEEDED)
        assert not roots[-1].exists()
        assert not (worktree / ".mypy_cache").exists()
    assert roots[0] != roots[1]


def _real_mypy_tools(registered: Path) -> None:
    venv.EnvBuilder(with_pip=False, symlinks=False).create(registered / ".venv")
    dependency_root = (
        registered
        / ".venv"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    for name in ("mypy", "mypy_extensions.py", "pathspec", "librt", "typing_extensions.py"):
        installed = Path(sysconfig.get_path("purelib")) / name
        if installed.is_dir():
            shutil.copytree(installed, dependency_root / name)
        else:
            shutil.copy2(installed, dependency_root / name)
    # Compiled mypy wheels keep their shared mypyc support module alongside
    # the package. Copy only that wheel-owned direct dependency, not host paths.
    for entry in distribution("mypy").files or ():
        if len(entry.parts) == 1 and "__mypyc" in entry.name:
            shutil.copy2(Path(sysconfig.get_path("purelib")) / entry, dependency_root / entry)


@pytest.mark.parametrize("untrusted_value", [None, "/untrusted/command-cache"])
def test_real_mypy_launcher_rebinds_reduced_environment_and_keeps_inventory_clean(
    tmp_path: Path, untrusted_value: str | None
) -> None:
    registered, worktree, _ = _project(tmp_path)
    _real_mypy_tools(registered)
    source = worktree / "src"
    source.mkdir()
    (source / "sample.py").write_text("VALUE: int = 1\n", encoding="utf-8")
    _git(worktree, "add", "src/sample.py")
    _git(worktree, "commit", "-qm", "source for actual mypy")
    base = _git(worktree, "rev-parse", "HEAD")

    def probe(cwd: Path, environment: Mapping[str, str], prompt: str) -> None:
        del prompt
        cache = Path(environment["MYPY_CACHE_DIR"])
        before = capture_mutation_inventory(cwd)
        reduced = {"PATH": environment["PATH"]}
        if untrusted_value is not None:
            reduced["MYPY_CACHE_DIR"] = untrusted_value
        checked = subprocess.run(
            (
                environment["ASE_PROJECT_PYTHON"],
                "-m",
                "mypy",
                "--config-file",
                os.devnull,
                "src/sample.py",
            ),
            cwd=cwd,
            env=reduced,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert checked.returncode == 0, checked.stderr
        assert "Success" in checked.stdout
        assert any(path.is_file() for path in cache.rglob("*"))
        assert not (cwd / ".mypy_cache").exists()
        assert capture_mutation_inventory(cwd) == before
        # A realistic large mypy database remains execution scratch. Do not
        # increase the production inventory limit to accommodate this file.
        with (cache / "large-cache.db").open("wb") as stream:
            stream.truncate(MAX_INVENTORY_FILE_BYTES + 1)
        assert capture_mutation_inventory(cwd) == before

    assert _run_coder(worktree, base, probe).status is AgentRunStatus.SUCCEEDED
    assert not (worktree / ".mypy_cache").exists()


@pytest.mark.parametrize("relative", ["src/large.py", ".mypy_cache/3.12/cache.db"])
def test_large_workspace_files_still_fail_original_inventory_gate(
    tmp_path: Path, relative: str
) -> None:
    registered, worktree, base = _project(tmp_path)
    _fake_tools(registered)

    def probe(cwd: Path, environment: Mapping[str, str], prompt: str) -> None:
        del environment, prompt
        target = cwd / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as stream:
            stream.truncate(MAX_INVENTORY_FILE_BYTES + 1)
        with pytest.raises(MutationInventoryRejected, match="workspace file exceeds"):
            capture_mutation_inventory(cwd)
        assert not is_execution_cache_path(".mypy_cache/3.12/cache.db")
        raise CodexCliError("fixture preserves rejected workspace")

    assert _run_coder(worktree, base, probe).status is AgentRunStatus.FAILED
    assert (worktree / relative).stat().st_size == MAX_INVENTORY_FILE_BYTES + 1


class _ReadOnlyProbeRunner:
    def __init__(self) -> None:
        self.environment: Mapping[str, str] | None = None

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
    ) -> CodexInvocationResult:
        del argv, cwd, stdin, timeout_seconds
        self.environment = environment
        return CodexInvocationResult(returncode=1)


@pytest.mark.parametrize("role", [AgentRole.QA, AgentRole.REVIEWER])
def test_verifiers_do_not_receive_coder_cache_capability(tmp_path: Path, role: AgentRole) -> None:
    registered, worktree, base = _project(tmp_path)
    _fake_tools(registered)
    runner = _ReadOnlyProbeRunner()
    request: AgentRequest = _request(role, source_revision=base)
    CodexCliAgentAdapter(
        workspace_root=worktree,
        model="gpt-test",
        agent_id="agent_verifier_001",
        agent_version="v0.1",
        environment={"PATH": os.environ["PATH"], "MYPY_CACHE_DIR": "/untrusted/host-cache"},
        prompt_builder=StaticPromptBuilder(),
        runner=runner,
    ).run(request)
    assert runner.environment is not None
    assert "MYPY_CACHE_DIR" not in runner.environment
    assert "ASE_PROJECT_PYTHON" not in runner.environment
