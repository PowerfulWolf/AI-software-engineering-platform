"""Native Coder reuses read-only tooling while importing its isolated source."""

import fcntl
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import venv
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from ai_software_engineer.agents import AgentRequest, CodexCliAgentAdapter, CodexInvocationResult
from ai_software_engineer.agents.codex_cli import CodexCliError
from ai_software_engineer.git import WorkspacePolicyError
from tests.agents.test_codex_cli import _CoderRunner, _git, _repository
from tests.agents.test_openai_compatible import StaticPromptBuilder, _coder_request
from tests.orchestration.test_native_continuation import Fixture, Guard


def _project(tmp_path: Path, *, python: bool = True) -> tuple[Path, Path, str]:
    registered, _ = _repository(tmp_path)
    (registered / ".git" / "info" / "exclude").write_text(".venv/\n", encoding="utf-8")
    if python:
        (registered / "pyproject.toml").write_text(
            '[project]\nname = "binding-fixture"\nversion = "0.1"\n', encoding="utf-8"
        )
        _git(registered, "add", "pyproject.toml")
        _git(registered, "commit", "-qm", "Python project")
    worktree = tmp_path / "coder"
    _git(registered, "worktree", "add", "--detach", str(worktree), "HEAD")
    return registered, worktree, _git(worktree, "rev-parse", "HEAD")


def _fake_tools(registered: Path) -> tuple[Path, Path]:
    binaries = registered / ".venv" / "bin"
    binaries.mkdir(parents=True)
    pytest_runner, python_runner = binaries / "pytest", binaries / "python"
    for executable in (pytest_runner, python_runner):
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    (
        registered
        / ".venv"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    ).mkdir(parents=True)
    return pytest_runner, python_runner


class _ToolProbeRunner(_CoderRunner):
    def __init__(
        self,
        request: AgentRequest,
        probe: Callable[[Path, Mapping[str, str], str], None] | None,
        argv_probe: Callable[[tuple[str, ...], Path, Mapping[str, str]], None] | None,
    ) -> None:
        super().__init__(request)
        self._probe = probe
        self._argv_probe = argv_probe

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        stdin: str,
        timeout_seconds: float,
    ) -> CodexInvocationResult:
        if self._probe is not None:
            self._probe(cwd, environment, stdin)
        if self._argv_probe is not None:
            self._argv_probe(argv, cwd, environment)
        return super().run(
            argv, cwd=cwd, environment=environment, stdin=stdin, timeout_seconds=timeout_seconds
        )


def _invoke(
    worktree: Path,
    base: str,
    *,
    probe: Callable[[Path, Mapping[str, str], str], None] | None = None,
    argv_probe: Callable[[tuple[str, ...], Path, Mapping[str, str]], None] | None = None,
) -> tuple[AgentRequest, _CoderRunner]:
    request = _coder_request().model_copy(update={"source_revision": base})
    runner = _ToolProbeRunner(request, probe, argv_probe)
    CodexCliAgentAdapter(
        workspace_root=worktree,
        model="gpt-test",
        agent_id="agent_coder_001",
        agent_version="v0.1",
        environment={
            "PATH": os.environ["PATH"],
            "PYTHONPATH": "/untrusted/old-source",
            "VIRTUAL_ENV": "/untrusted/host-env",
            "UV_PROJECT_ENVIRONMENT": "/untrusted/shared-env",
            "ASE_PROJECT_PYTEST": "/untrusted/pytest",
            "ASE_PROJECT_PYTHON": "/untrusted/python",
            "TMPDIR": "/untrusted/host-temp",
            "UV_CACHE_DIR": "/untrusted/host-cache",
        },
        prompt_builder=StaticPromptBuilder(),
        runner=runner,
    ).run(request)
    return request, runner


def _copy_pytest_dependencies(dependency_root: Path) -> None:
    for package_name in (
        "pytest",
        "_pytest",
        "pluggy",
        "packaging",
        "iniconfig",
        "pygments",
        "py.py",
    ):
        installed = Path(sysconfig.get_path("purelib")) / package_name
        if installed.is_dir():
            shutil.copytree(installed, dependency_root / package_name)
        else:
            shutil.copy2(installed, dependency_root / package_name)


def test_coder_receives_registered_tools_and_current_source_only(tmp_path: Path) -> None:
    registered, worktree, base = _project(tmp_path)
    (worktree / "src").mkdir()
    pytest_runner, python_runner = _fake_tools(registered)

    def probe(cwd: Path, environment: Mapping[str, str], prompt: str) -> None:
        del prompt
        assert cwd == worktree
        scratch = Path(environment["TMPDIR"])
        cache = Path(environment["UV_CACHE_DIR"])
        assert scratch.is_dir() and cache.is_dir() and scratch.parent == cache.parent
        for name, mode in (("ASE_PROJECT_PYTEST", "pytest"), ("ASE_PROJECT_PYTHON", "python")):
            launcher = Path(environment[name])
            assert not launcher.is_relative_to(scratch.parent)
            assert launcher.is_file() and os.access(launcher, os.X_OK)
            body = launcher.read_text(encoding="utf-8")
            assert str(python_runner) in body
            assert f"-I -S -B {launcher.parent}/python-bootstrap.py {mode}" in body
            assert '"$@"' in body
            assert str(pytest_runner) != str(launcher)

    def argv_probe(argv: tuple[str, ...], cwd: Path, environment: Mapping[str, str]) -> None:
        assert "--sandbox" not in argv
        assert 'default_permissions="ase_coder_tooling"' in argv
        profile = next(
            token for token in argv if token.startswith("permissions.ase_coder_tooling=")
        )
        assert f'{json.dumps(str(cwd))}="write"' in profile
        run_root = Path(environment["TMPDIR"]).parent
        tool_root = Path(environment["ASE_PROJECT_PYTHON"]).parent
        assert f'{json.dumps(str(run_root))}="write"' in profile
        assert f'{json.dumps(str(tool_root))}="read"' in profile
        assert f'{json.dumps(str(registered / ".venv"))}="read"' in profile
        assert f'{json.dumps(str(cwd / ".git"))}="read"' in profile
        assert "network={enabled=false}" in profile

    _, runner = _invoke(worktree, base, probe=probe, argv_probe=argv_probe)

    _, environment, prompt = runner.calls[0]
    assert not Path(environment["ASE_PROJECT_PYTEST"]).exists()
    assert not Path(environment["ASE_PROJECT_PYTHON"]).exists()
    assert not Path(environment["TMPDIR"]).parent.exists()
    assert not Path(environment["UV_CACHE_DIR"]).exists()
    assert environment["PYTHONPATH"] == os.pathsep.join((str(worktree / "src"), str(worktree)))
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["PATH"] == os.environ["PATH"]
    assert "VIRTUAL_ENV" not in environment
    assert "UV_PROJECT_ENVIRONMENT" not in environment
    assert "read-only Python test tooling" in prompt
    assert "Do not create, copy, install, or synchronize a virtual environment" in prompt
    assert "uv sync" in prompt
    assert "NOT_RUN" in prompt
    assert not (worktree / ".venv").exists()


@pytest.mark.parametrize("layout", ["src", "flat"])
@pytest.mark.parametrize("startup", ["path", "executed", "virtualenv"])
def test_real_python_and_pytest_import_worktree_instead_of_editable_checkout(
    tmp_path: Path, layout: str, startup: str
) -> None:
    registered, worktree, _ = _project(tmp_path)
    relative_source = Path("src") if layout == "src" else Path()
    for root, label in ((registered, "registered-old"), (worktree, "candidate-current")):
        package = root / relative_source / "binding_sample"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(f'LABEL = "{label}"\n', encoding="utf-8")
    # The registered editable .pth deliberately points at an older checkout.
    binaries = registered / ".venv" / "bin"
    venv.EnvBuilder(with_pip=False, system_site_packages=False, symlinks=False).create(
        registered / ".venv"
    )
    python_runner = binaries / "python"
    assert not python_runner.is_symlink()
    dependency_root = (
        registered
        / ".venv"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    (dependency_root / "editable-old-source.pth").write_text(
        str(registered / relative_source) + "\n", encoding="utf-8"
    )
    _copy_pytest_dependencies(dependency_root)
    if startup == "executed":
        (dependency_root / "executable-editable.pth").write_text(
            f"import sys; sys.path.insert(0, {str(registered / relative_source)!r})\n",
            encoding="utf-8",
        )
    elif startup == "virtualenv":
        (dependency_root / "_virtualenv.pth").write_text("import _virtualenv\n", encoding="utf-8")
        (dependency_root / "_virtualenv.py").write_text(
            f"import sys; sys.path.insert(0, {str(registered / relative_source)!r})\n",
            encoding="utf-8",
        )
    (dependency_root / "sitecustomize.py").write_text(
        f"import sys; sys.path.insert(0, {str(registered / relative_source)!r})\n",
        encoding="utf-8",
    )
    pytest_runner = binaries / "pytest"
    pytest_runner.write_text(
        f"#!{python_runner}\nfrom pytest import console_main\nraise SystemExit(console_main())\n",
        encoding="utf-8",
    )
    pytest_runner.chmod(0o755)
    tests = worktree / "tests"
    tests.mkdir()
    expected_source = worktree / relative_source / "binding_sample" / "__init__.py"
    (tests / "test_binding.py").write_text(
        "from pathlib import Path\nimport binding_sample\n"
        "def test_candidate_source():\n"
        "    assert binding_sample.LABEL == 'candidate-current'\n"
        f"    assert Path(binding_sample.__file__) == Path({str(expected_source)!r})\n",
        encoding="utf-8",
    )
    _git(worktree, "add", str(relative_source / "binding_sample"), "tests/test_binding.py")
    _git(worktree, "commit", "-qm", "candidate source")
    base = _git(worktree, "rev-parse", "HEAD")
    baseline = subprocess.run(
        (str(python_runner), "-c", "import binding_sample; print(binding_sample.LABEL)"),
        cwd=worktree,
        env={"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    if layout == "src":
        assert baseline.stdout.strip() == "registered-old"

    def probe(cwd: Path, environment: Mapping[str, str], prompt: str) -> None:
        del prompt
        imported = subprocess.run(
            (
                environment["ASE_PROJECT_PYTHON"],
                "-c",
                "import json, binding_sample, sys; "
                "assert 'sitecustomize' not in sys.modules and '_virtualenv' not in sys.modules; "
                "print(json.dumps([binding_sample.LABEL, binding_sample.__file__]))",
            ),
            cwd=cwd,
            env=dict(environment),
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        assert json.loads(imported.stdout) == ["candidate-current", str(expected_source)]
        for entrypoint in (
            (environment["ASE_PROJECT_PYTEST"],),
            (environment["ASE_PROJECT_PYTHON"], "-m", "pytest"),
        ):
            tested = subprocess.run(
                (*entrypoint, "tests/test_binding.py", "-q", "-p", "no:cacheprovider"),
                cwd=cwd,
                env=dict(environment),
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            assert tested.returncode == 0, tested.stdout + tested.stderr
            assert "1 passed" in tested.stdout

    _invoke(worktree, base, probe=probe)
    assert not (worktree / ".venv").exists()


def test_executable_pth_overrides_direct_python_but_not_coder_launcher(tmp_path: Path) -> None:
    registered, worktree, _ = _project(tmp_path)
    for root, label in ((registered, "registered-old"), (worktree, "candidate-current")):
        package = root / "src" / "binding_sample"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(f'LABEL = "{label}"\n', encoding="utf-8")
    _git(worktree, "add", "src/binding_sample")
    _git(worktree, "commit", "-qm", "candidate source")
    base = _git(worktree, "rev-parse", "HEAD")
    venv.EnvBuilder(with_pip=False, symlinks=False).create(registered / ".venv")
    python_runner = registered / ".venv" / "bin" / "python"
    pytest_runner = python_runner.with_name("pytest")
    pytest_runner.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    pytest_runner.chmod(0o755)
    dependency_root = (
        registered
        / ".venv"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    pth = dependency_root / "editable-executed-source.pth"
    pth_body = f"import sys; sys.path.insert(0, {str(registered / 'src')!r})\n"
    pth.write_text(pth_body, encoding="utf-8")

    def probe(cwd: Path, environment: Mapping[str, str], prompt: str) -> None:
        del prompt
        imported = subprocess.run(
            (
                environment["ASE_PROJECT_PYTHON"],
                "-c",
                "import binding_sample; print(binding_sample.__file__)",
            ),
            cwd=cwd,
            env=dict(environment),
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        assert imported.stdout.strip() == str(worktree / "src/binding_sample/__init__.py")

    _, runner = _invoke(worktree, base, probe=probe)
    _, environment, prompt = runner.calls[0]
    # A real Python startup proves that simply setting PYTHONPATH cannot fence this source.
    imported = subprocess.run(
        (str(python_runner), "-c", "import binding_sample; print(binding_sample.__file__)"),
        cwd=worktree,
        env=dict(environment),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert imported.stdout.strip() == str(registered / "src/binding_sample/__init__.py")
    assert not Path(environment["ASE_PROJECT_PYTEST"]).exists()
    assert not Path(environment["ASE_PROJECT_PYTHON"]).exists()
    assert "fixed isolated Python startup" in prompt
    assert "never process .pth or sitecustomize" in prompt
    assert pth.read_text(encoding="utf-8") == pth_body
    assert not (worktree / ".venv").exists()


@pytest.mark.parametrize("layout", ["src", "flat"])
@pytest.mark.parametrize("shadow", ["package", "module", "nested", "namespace"])
def test_native_python_and_pytest_refuse_registered_namespace_shadow(
    tmp_path: Path, layout: str, shadow: str
) -> None:
    registered, worktree, _ = _project(tmp_path)
    source = worktree / "src" if layout == "src" else worktree
    relative = Path("namespace_sample/child") if shadow == "nested" else Path("namespace_sample")
    candidate = source / relative
    candidate.mkdir(parents=True)
    (candidate / "app.py").write_text('LABEL = "candidate-current"\n', encoding="utf-8")
    venv.EnvBuilder(with_pip=False, symlinks=False).create(registered / ".venv")
    dependency_root = next((registered / ".venv/lib").glob("python*/site-packages"))
    _copy_pytest_dependencies(dependency_root)
    old = dependency_root / relative
    old.mkdir(parents=True)
    sentinel = registered / "old-package-executed"
    initialization = f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\n"
    if shadow in {"package", "nested"}:
        (old / "__init__.py").write_text(initialization, encoding="utf-8")
    elif shadow == "module":
        (dependency_root / "namespace_sample.py").write_text(initialization, encoding="utf-8")
    (old / "app.py").write_text('LABEL = "registered-old"\n', encoding="utf-8")
    pytest_runner = registered / ".venv/bin/pytest"
    pytest_runner.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    pytest_runner.chmod(0o755)
    module = "namespace_sample.child.app" if shadow == "nested" else "namespace_sample.app"
    program = f"import {module} as app; print(app.__file__)"
    tests = worktree / "tests"
    tests.mkdir()
    (tests / "test_namespace.py").write_text(
        f"import {module} as app\ndef test_source():\n"
        f"    assert app.__file__ == {str(candidate / 'app.py')!r}\n",
        encoding="utf-8",
    )
    _git(worktree, "add", ".")
    _git(worktree, "commit", "-qm", "candidate namespace source")
    base = _git(worktree, "rev-parse", "HEAD")
    baseline = subprocess.run(
        (
            str(registered / ".venv/bin/python"),
            "-I",
            "-S",
            "-B",
            "-c",
            f"import sys; sys.path[:0] = {[str(source), str(dependency_root)]!r}; " + program,
        ),
        cwd=worktree,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if shadow != "namespace":
        assert sentinel.exists(), baseline.stderr
        sentinel.unlink()
    else:
        assert baseline.returncode == 0 and baseline.stdout.strip() == str(candidate / "app.py")

    def probe(cwd: Path, environment: Mapping[str, str], prompt: str) -> None:
        for arguments in (
            (environment["ASE_PROJECT_PYTHON"], "-c", program),
            (
                environment["ASE_PROJECT_PYTEST"],
                "tests/test_namespace.py",
                "-q",
                "-p",
                "no:cacheprovider",
            ),
        ):
            executed = subprocess.run(
                arguments,
                cwd=cwd,
                env=dict(environment),
                capture_output=True,
                text=True,
                timeout=20,
            )
            if shadow == "namespace":
                assert executed.returncode == 0, executed.stdout + executed.stderr
            else:
                assert executed.returncode != 0
                assert "current-source namespace" in executed.stdout + executed.stderr
            assert not sentinel.exists()
        assert "namespace" in prompt

    _invoke(worktree, base, probe=probe)


@pytest.mark.parametrize(
    "regular,dependency_namespace", [(False, False), (True, False), (True, True)]
)
def test_pytest_tool_loading_refuses_current_source_shadow_before_dependency_code(
    tmp_path: Path,
    regular: bool,
    dependency_namespace: bool,
) -> None:
    registered, worktree, _ = _project(tmp_path)
    candidate = worktree / "src/pluggy"
    candidate.mkdir(parents=True)
    (candidate / "candidate.py").write_text('LABEL = "candidate-current"\n', encoding="utf-8")
    if regular:
        (candidate / "__init__.py").write_text('LABEL = "candidate-current"\n', encoding="utf-8")
    venv.EnvBuilder(with_pip=False, symlinks=False).create(registered / ".venv")
    dependency_root = next((registered / ".venv/lib").glob("python*/site-packages"))
    _copy_pytest_dependencies(dependency_root)
    sentinel = registered / "tooling-dependency-executed"
    old = dependency_root / "pluggy/__init__.py"
    old.write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\n"
        + old.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    if dependency_namespace:
        old.unlink()
    pytest_runner = registered / ".venv/bin/pytest"
    pytest_runner.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    pytest_runner.chmod(0o755)
    _git(worktree, "add", "src")
    _git(worktree, "commit", "-qm", "candidate namespace conflicts with tooling")
    base = _git(worktree, "rev-parse", "HEAD")

    def probe(cwd: Path, environment: Mapping[str, str], prompt: str) -> None:
        del prompt
        for entrypoint in (
            (environment["ASE_PROJECT_PYTEST"],),
            (environment["ASE_PROJECT_PYTHON"], "-m", "pytest"),
        ):
            executed = subprocess.run(
                (*entrypoint, "--version"),
                cwd=cwd,
                env=dict(environment),
                capture_output=True,
                text=True,
                timeout=20,
            )
            assert executed.returncode != 0
            assert "current-source namespace" in executed.stdout + executed.stderr
            assert "pluggy" in executed.stdout + executed.stderr
            assert not sentinel.exists()

    _invoke(worktree, base, probe=probe)


def test_preloaded_module_cannot_bypass_namespace_source_check(tmp_path: Path) -> None:
    registered, worktree, _ = _project(tmp_path)
    candidate = worktree / "src/pathlib"
    candidate.mkdir(parents=True)
    (candidate / "app.py").write_text('LABEL = "candidate-current"\n', encoding="utf-8")
    venv.EnvBuilder(with_pip=False, symlinks=False).create(registered / ".venv")
    _git(worktree, "add", "src")
    _git(worktree, "commit", "-qm", "candidate namespace conflicts with preloaded support module")
    base = _git(worktree, "rev-parse", "HEAD")

    def probe(cwd: Path, environment: Mapping[str, str], prompt: str) -> None:
        del prompt
        executed = subprocess.run(
            (environment["ASE_PROJECT_PYTHON"], "-c", "print('user-code-started'); import pathlib"),
            cwd=cwd,
            env=dict(environment),
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert executed.returncode != 0
        assert "current-source namespace" in executed.stderr and "pathlib" in executed.stderr
        assert "user-code-started" not in executed.stdout

    _invoke(worktree, base, probe=probe)


@pytest.mark.parametrize("unsafe", ["venv_link", "bin_link", "pytest_link", "not_executable"])
def test_unsafe_registered_pytest_is_not_bound_or_installed(tmp_path: Path, unsafe: str) -> None:
    registered, worktree, base = _project(tmp_path)
    pytest_runner, _ = _fake_tools(registered)
    if unsafe == "not_executable":
        pytest_runner.chmod(0o644)
    elif unsafe == "pytest_link":
        original = pytest_runner.with_name("pytest-original")
        pytest_runner.rename(original)
        pytest_runner.symlink_to(original)
    else:
        original = registered / ".venv" / "bin" if unsafe == "bin_link" else registered / ".venv"
        external = tmp_path / "outside-tooling"
        original.rename(external)
        original.symlink_to(external, target_is_directory=True)

    _, runner = _invoke(worktree, base)

    _, environment, prompt = runner.calls[0]
    assert "ASE_PROJECT_PYTEST" not in environment
    assert "registered Python test tooling is unavailable" in prompt
    assert "NOT_RUN" in prompt
    assert "coder-progress" in prompt
    assert not (worktree / ".venv").exists()


def test_symlink_python_refuses_both_launchers_without_unsafe_fallback(tmp_path: Path) -> None:
    registered, worktree, base = _project(tmp_path)
    _, python_runner = _fake_tools(registered)
    original = python_runner.with_name("python-original")
    python_runner.rename(original)
    python_runner.symlink_to(original)

    _, runner = _invoke(worktree, base)

    _, environment, prompt = runner.calls[0]
    assert "ASE_PROJECT_PYTEST" not in environment
    assert "ASE_PROJECT_PYTHON" not in environment
    assert "No safe dedicated Python executable was found" in prompt
    assert "PYTHONPATH" in environment


@pytest.mark.parametrize("python", [True, False])
def test_missing_tools_do_not_install_or_impose_python_gate_on_other_projects(
    tmp_path: Path, python: bool
) -> None:
    _, worktree, base = _project(tmp_path, python=python)

    _, runner = _invoke(worktree, base)

    _, environment, prompt = runner.calls[0]
    assert "ASE_PROJECT_PYTEST" not in environment
    assert "ASE_PROJECT_PYTHON" not in environment
    assert "VIRTUAL_ENV" not in environment
    assert "UV_PROJECT_ENVIRONMENT" not in environment
    assert ("registered Python test tooling is unavailable" in prompt) is python
    assert ("PYTHONPATH" in environment) is python
    assert not (worktree / ".venv").exists()


@pytest.mark.parametrize("linked_parent", ["lib", "version", "site-packages", "multiple_versions"])
def test_unsafe_or_ambiguous_dependency_root_refuses_both_launchers(
    tmp_path: Path, linked_parent: str
) -> None:
    registered, worktree, base = _project(tmp_path)
    _fake_tools(registered)
    library = registered / ".venv" / "lib"
    version = library / f"python{sys.version_info.major}.{sys.version_info.minor}"
    if linked_parent == "multiple_versions":
        (library / "python3.99" / "site-packages").mkdir(parents=True)
    else:
        original = {
            "lib": library,
            "version": version,
            "site-packages": version / "site-packages",
        }[linked_parent]
        outside = tmp_path / "outside-dependencies"
        original.rename(outside)
        original.symlink_to(outside, target_is_directory=True)

    _, runner = _invoke(worktree, base)

    _, environment, prompt = runner.calls[0]
    assert "ASE_PROJECT_PYTEST" not in environment
    assert "ASE_PROJECT_PYTHON" not in environment
    assert "registered Python test tooling is unavailable" in prompt


def test_launchers_quote_paths_and_preserve_arguments_without_shell_evaluation(
    tmp_path: Path,
) -> None:
    project_directory = tmp_path / "project with ' quotes"
    project_directory.mkdir()
    registered, worktree, base = _project(project_directory)
    venv.EnvBuilder(with_pip=False, symlinks=False).create(registered / ".venv")
    pytest_runner = registered / ".venv" / "bin" / "pytest"
    pytest_runner.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    pytest_runner.chmod(0o755)
    sentinel = tmp_path / "shell-expansion-must-not-run"
    argument = f"literal space '$HOME' ; $(touch {sentinel})"
    script = worktree / "src" / "check.py"
    script.parent.mkdir()
    script.write_text("import json,sys;print(json.dumps(sys.argv[1:]))\n", encoding="utf-8")
    _git(worktree, "add", "src/check.py")
    _git(worktree, "commit", "-qm", "current script")
    base = _git(worktree, "rev-parse", "HEAD")
    outside_script = tmp_path / "outside.py"
    outside_script.write_text("print('outside script must not execute')\n", encoding="utf-8")

    def probe(cwd: Path, environment: Mapping[str, str], prompt: str) -> None:
        del prompt
        python = environment["ASE_PROJECT_PYTHON"]
        executed = subprocess.run(
            (python, "-c", "import json,sys;print(json.dumps(sys.argv[1:]))", argument),
            cwd=cwd,
            env=dict(environment),
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        assert json.loads(executed.stdout) == [argument]
        assert not sentinel.exists()
        scripted = subprocess.run(
            (python, "src/check.py", argument),
            cwd=cwd,
            env=dict(environment),
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        assert json.loads(scripted.stdout) == [argument]
        outside = subprocess.run(
            (python, str(outside_script)),
            cwd=cwd,
            env=dict(environment),
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert outside.returncode != 0
        assert "outside script must not execute" not in outside.stdout
        denied = subprocess.run(
            (python, "-I"), cwd=cwd, env=dict(environment), capture_output=True, timeout=10
        )
        assert denied.returncode != 0
        wrong_cwd = subprocess.run(
            (python, "-c", "raise SystemExit(0)"),
            cwd=registered,
            env=dict(environment),
            capture_output=True,
            timeout=10,
        )
        assert wrong_cwd.returncode != 0

    _invoke(worktree, base, probe=probe)


def test_private_launchers_are_removed_after_runner_failure(tmp_path: Path) -> None:
    registered, worktree, base = _project(tmp_path)
    _fake_tools(registered)
    paths: list[Path] = []

    def probe(cwd: Path, environment: Mapping[str, str], prompt: str) -> None:
        del cwd, prompt
        paths.extend(
            Path(environment[name]) for name in ("ASE_PROJECT_PYTEST", "ASE_PROJECT_PYTHON")
        )
        paths.append(Path(environment["TMPDIR"]).parent)
        assert paths[-1].is_dir()
        assert all(path.is_file() for path in paths[:2])
        raise CodexCliError("fixture runner could not start")

    _invoke(worktree, base, probe=probe)

    assert len(paths) == 3 and all(not path.exists() for path in paths)


@pytest.mark.skipif(
    os.environ.get("ASE_RUN_SANDBOX_TESTS") != "1"
    or not os.environ.get("ASE_TEST_CODEX_EXECUTABLE"),
    reason="explicit real local sandbox probe without a model",
)
def test_real_native_sandbox_protects_tooling_and_keeps_source_and_scratch_writable(
    tmp_path: Path,
) -> None:
    registered, worktree, _ = _project(tmp_path)
    package = worktree / "src" / "binding_sample"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('LABEL = "candidate-current"\n', encoding="utf-8")
    _git(worktree, "add", "src/binding_sample")
    _git(worktree, "commit", "-qm", "candidate source")
    base = _git(worktree, "rev-parse", "HEAD")
    venv.EnvBuilder(with_pip=False, symlinks=False).create(registered / ".venv")
    pytest_runner = registered / ".venv" / "bin" / "pytest"
    pytest_runner.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    pytest_runner.chmod(0o755)

    def probe(argv: tuple[str, ...], cwd: Path, environment: Mapping[str, str]) -> None:
        executable = os.environ["ASE_TEST_CODEX_EXECUTABLE"]
        tool_root = Path(environment["ASE_PROJECT_PYTHON"]).parent
        bootstrap = tool_root / "python-bootstrap.py"
        sentinel = tool_root / "legacy-default-sandbox-sentinel"
        sentinel.write_text("original\n", encoding="utf-8")
        legacy_environment = dict(environment)
        legacy_environment.pop("TMPDIR", None)
        if os.environ.get("TMPDIR"):
            legacy_environment["TMPDIR"] = os.environ["TMPDIR"]
        legacy = subprocess.run(
            (
                executable,
                "sandbox",
                "--include-managed-config",
                "-P",
                ":workspace",
                "-C",
                str(cwd),
                "--",
                str(registered / ".venv/bin/python"),
                "-I",
                "-S",
                "-B",
                "-c",
                "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('tampered')",
                str(sentinel),
            ),
            cwd=cwd,
            env=legacy_environment,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert legacy.returncode == 0, legacy.stderr[-1000:]
        assert sentinel.read_text(encoding="utf-8") == "tampered"
        profiles = [token for token in argv if token.startswith("permissions.ase_coder_tooling=")]
        assert len(profiles) == 1
        assert "--sandbox" not in argv
        originals = {
            path: path.read_bytes()
            for path in (bootstrap, tool_root / "python", tool_root / "pytest")
        }
        program = (
            "import binding_sample,json,os,sys; from pathlib import Path\n"
            "root=Path(sys.argv[1]); results=[]\n"
            "for path in (root/'python-bootstrap.py',root/'python',root/'pytest'):\n"
            "    for operation in ('write','unlink','replace'):\n"
            "        try:\n"
            "            if operation=='write': path.write_text('tampered')\n"
            "            elif operation=='unlink': path.unlink()\n"
            "            else:\n"
            "                replacement=Path(os.environ['TMPDIR'])/'replacement'\n"
            "                replacement.write_text('tampered'); replacement.replace(path)\n"
            "            results.append(False)\n"
            "        except PermissionError: results.append(True)\n"
            "    link=Path('src/tool-link'); link.symlink_to(path)\n"
            "    try: link.write_text('tampered'); results.append(False)\n"
            "    except PermissionError: results.append(True)\n"
            "    finally: link.unlink()\n"
            "try: root.rename(Path(os.environ['TMPDIR'])/'moved-tools'); results.append(False)\n"
            "except PermissionError: results.append(True)\n"
            "scratch=Path(os.environ['TMPDIR'])/'permitted'; scratch.write_text('allowed')\n"
            "source=Path('src/permitted_probe.py'); source.write_text('allowed'); source.unlink()\n"
            "try: (Path.cwd()/'.git').write_text('tampered'); results.append(False)\n"
            "except PermissionError: results.append(True)\n"
            "print(json.dumps({'source':binding_sample.__file__,'denials':results,'scratch':scratch.read_text()}))\n"
        )
        actual = subprocess.run(
            (
                executable,
                "sandbox",
                "--include-managed-config",
                "-P",
                "ase_coder_tooling",
                "-c",
                profiles[0],
                "-C",
                str(cwd),
                "--",
                environment["ASE_PROJECT_PYTHON"],
                "-c",
                program,
                str(tool_root),
            ),
            cwd=cwd,
            env=dict(environment),
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert actual.returncode == 0, actual.stdout + actual.stderr[-1500:]
        result = json.loads(actual.stdout)
        assert result == {
            "source": str(package / "__init__.py"),
            "denials": [True] * 14,
            "scratch": "allowed",
        }
        assert all(path.read_bytes() == body for path, body in originals.items())

    _invoke(worktree, base, argv_probe=probe)


def test_ignored_venv_mutation_still_refuses_native_completion(tmp_path: Path) -> None:
    fd = os.open(tmp_path / "task.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    fixture = Fixture(tmp_path, Guard(fd))
    try:
        root = fixture.worktree.path
        exclude = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        (exclude / "info" / "exclude").write_text(".venv/\n", encoding="utf-8")
        service = fixture.service()
        before = service.started(fixture.request, root)
        destination = root / ".venv" / ".gitignore"
        destination.parent.mkdir()
        destination.write_text("*\n", encoding="utf-8")
        assert _git(root, "status", "--porcelain") == ""
        with pytest.raises(WorkspacePolicyError):
            service.finished(fixture.request, root, before=before)
        assert destination.read_text(encoding="utf-8") == "*\n"
        assert fixture.store.receipt_for_task(fixture.task.id) is None
    finally:
        fixture.repository.close()
        os.close(fd)
