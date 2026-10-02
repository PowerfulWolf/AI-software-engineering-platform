"""Exact pytest selections and fixed sandbox commands, without external services."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_software_engineer.manager.python_verification import (
    PytestSelection,
    PythonMysqlSandboxCapability,
    python_mysql_sandbox_command,
)


def capability(tmp_path: Path) -> PythonMysqlSandboxCapability:
    return PythonMysqlSandboxCapability(
        sandbox_executable=str(tmp_path / "codex"),
        sandbox_executable_sha256="a" * 64,
        python_executable=str(tmp_path / "runtime/bin/python"),
        python_executable_sha256="b" * 64,
        python_runtime_root=str(tmp_path / "runtime"),
        python_runtime_sha256="b" * 64,
        dependency_root=str(tmp_path / "deps"),
        dependency_sha256="c" * 64,
        runner_path=str(tmp_path / "runner.py"),
        runner_sha256="d" * 64,
        docker_executable=str(tmp_path / "docker"),
        docker_executable_sha256="e" * 64,
        docker_socket=str(tmp_path / "docker.sock"),
        docker_daemon_id="fixture-daemon",
        mysql_image_id="sha256:" + "f" * 64,
        selections=(
            PytestSelection(node_id="tests/test_example.py::test_sql", criterion_ids=("ac_sql",)),
        ),
    )


@pytest.mark.parametrize(
    "node",
    [
        "tests",
        "tests/test_example.py",
        "../tests/test_x.py::test_x",
        "tests/test_x.py::test_*",
        "tests/test_x.py::test_x --disable-warnings",
        "/tmp/tests/test_x.py::test_x",
        "tests/.hidden/test_x.py::test_x",
    ],
)
def test_directory_glob_flags_and_nonexact_pytest_selections_are_rejected(node: str) -> None:
    with pytest.raises(ValidationError):
        PytestSelection(node_id=node, criterion_ids=("ac_sql",))


def test_command_has_fixed_readonly_source_and_private_exact_socket(tmp_path: Path) -> None:
    cap = capability(tmp_path)
    source, scratch, private = (tmp_path / name for name in ("source", "scratch", "private"))
    argv = python_mysql_sandbox_command(cap, source, scratch, private)
    assert argv[-4:] == (str(source), str(scratch), str(private / "connection.json"), "256")
    assert "--include-managed-config" in argv
    assert argv[argv.index("--allow-unix-socket") + 1] == str(private / "mysql.sock")
    profile = argv[argv.index("-c") + 1]
    assert '":root"="none"' in profile and '":minimal"="read"' in profile
    assert '":slash_tmp"="none"' in profile and '":tmpdir"="none"' in profile
    assert "network={enabled=false}" in profile
    assert f'"{scratch}"="write"' in profile
    assert f'"{source}"="read"' in profile
    assert f'"{private}"="write"' not in profile
    assert cap.docker_socket not in profile
    assert argv[argv.index("--") + 2 : argv.index("--") + 5] == ("-I", "-S", "-B")
    assert "pytest" not in argv  # Only the hash-bound trusted runner constructs pytest argv.


@pytest.mark.parametrize("overlap", ["same", "nested", "source_private", "scratch_private"])
def test_source_scratch_and_proxy_must_not_overlap(tmp_path: Path, overlap: str) -> None:
    cap = capability(tmp_path)
    source, scratch, private = (tmp_path / name for name in ("source", "scratch", "private"))
    if overlap == "same":
        scratch = source
    elif overlap == "nested":
        scratch = source / "tmp"
    elif overlap == "source_private":
        private = source / "proxy"
    else:
        private = scratch / "proxy"
    with pytest.raises(ValueError, match="overlap"):
        python_mysql_sandbox_command(cap, source, scratch, private)


def test_selection_identity_and_bounds_are_part_of_capability(tmp_path: Path) -> None:
    cap = capability(tmp_path)
    with pytest.raises(ValidationError):
        PythonMysqlSandboxCapability.model_validate(
            {**cap.to_wire(), "selections": list(cap.selections) * 2}
        )
    with pytest.raises(ValidationError):
        PythonMysqlSandboxCapability.model_validate({**cap.to_wire(), "max_cases": 257})


def test_deny_config_budget_is_rejected_before_execution(tmp_path: Path) -> None:
    cap = capability(tmp_path)
    accepted = PythonMysqlSandboxCapability.model_validate(
        {
            **cap.to_wire(),
            "denied_relative_paths": [f"private/{index:04d}.txt" for index in range(500)],
        }
    )
    assert len(accepted.denied_relative_paths) == 500
    with pytest.raises(ValidationError, match="private config budget"):
        PythonMysqlSandboxCapability.model_validate(
            {
                **cap.to_wire(),
                "denied_relative_paths": [f"private/{index:04d}.txt" for index in range(2000)],
            }
        )
