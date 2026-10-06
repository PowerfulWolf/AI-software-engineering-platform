"""Fingerprint the actual trusted files; candidate selection discovery never imports tests."""

import os
import socket
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_software_engineer.domain.native_verification import NativeVerificationCapabilityDetail
from ai_software_engineer.manager.python_verification import (
    PytestSelection,
    PythonMysqlHostPrerequisites,
)
from ai_software_engineer.manager.python_verification_discovery import (
    PythonMysqlDiscoveryError,
    candidate_denied_paths,
    dependency_fingerprint,
    discover_python_mysql_capability,
    discover_python_mysql_host_prerequisites,
    require_selected_candidate_files,
)


def test_host_discovery_classifies_unsupported_platform_without_host_details() -> None:
    with (
        patch(
            "ai_software_engineer.manager.python_verification_discovery.platform.system",
            return_value="Linux",
        ),
        pytest.raises(PythonMysqlDiscoveryError) as caught,
    ):
        from ai_software_engineer.manager.python_verification_discovery import (
            discover_python_mysql_host_prerequisites,
        )

        discover_python_mysql_host_prerequisites(codex_executable="codex")
    assert caught.value.code is NativeVerificationCapabilityDetail.PLATFORM_UNSUPPORTED
    assert str(caught.value) == NativeVerificationCapabilityDetail.PLATFORM_UNSUPPORTED.value


def test_candidate_discovery_classifies_unsupported_platform_without_candidate_access(
    tmp_path: Path,
) -> None:
    with (
        patch(
            "ai_software_engineer.manager.python_verification_discovery.platform.system",
            return_value="Linux",
        ),
        pytest.raises(PythonMysqlDiscoveryError) as caught,
    ):
        discover_python_mysql_capability(
            tmp_path,
            "0" * 40,
            (),
            codex_executable="codex",
        )
    assert caught.value.code is NativeVerificationCapabilityDetail.PLATFORM_UNSUPPORTED


def _host_discovery_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    codex = tmp_path / "codex"
    docker = tmp_path / "docker"
    codex.write_bytes(b"codex")
    docker.write_bytes(b"docker")
    monkeypatch.setattr(
        "ai_software_engineer.manager.python_verification_discovery.platform.system",
        lambda: "Darwin",
    )
    monkeypatch.setattr(
        "ai_software_engineer.manager.python_verification_discovery._binary",
        lambda name: codex if name == "codex" else docker,
    )
    monkeypatch.setattr(
        "ai_software_engineer.manager.python_verification_discovery._file_sha256",
        lambda path: "a" * 64,
    )
    return docker


def _bound_unix_socket() -> tuple[socket.socket, Path]:
    socket_path = Path("/tmp/ase-preflight-docker.sock")
    socket_path.unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    return server, socket_path


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        ("codex", NativeVerificationCapabilityDetail.CODEX_EXECUTABLE_UNAVAILABLE),
        ("docker", NativeVerificationCapabilityDetail.DOCKER_EXECUTABLE_UNAVAILABLE),
        ("context", NativeVerificationCapabilityDetail.DOCKER_CONTEXT_UNAVAILABLE),
        ("endpoint", NativeVerificationCapabilityDetail.DOCKER_ENDPOINT_INVALID),
        ("socket", NativeVerificationCapabilityDetail.DOCKER_SOCKET_UNAVAILABLE),
        ("daemon", NativeVerificationCapabilityDetail.DOCKER_DAEMON_UNAVAILABLE),
        ("image", NativeVerificationCapabilityDetail.MYSQL_IMAGE_UNAVAILABLE),
        ("python", NativeVerificationCapabilityDetail.PYTHON_RUNTIME_UNAVAILABLE),
        ("runner", NativeVerificationCapabilityDetail.RUNNER_UNAVAILABLE),
        ("dependencies", NativeVerificationCapabilityDetail.DEPENDENCY_FINGERPRINT_FAILED),
    ],
)
def test_host_discovery_classifies_each_safe_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    expected: NativeVerificationCapabilityDetail,
) -> None:
    _host_discovery_fixture(tmp_path, monkeypatch)
    if stage == "codex":
        monkeypatch.setattr(
            "ai_software_engineer.manager.python_verification_discovery._binary",
            lambda name: (_ for _ in ()).throw(ValueError("secret-sentinel")),
        )
    elif stage == "docker":
        monkeypatch.setattr(
            "ai_software_engineer.manager.python_verification_discovery._binary",
            lambda name: (
                tmp_path / "codex"
                if name == "codex"
                else (_ for _ in ()).throw(ValueError("secret-sentinel"))
            ),
        )
    elif stage == "context":
        monkeypatch.setattr(
            "ai_software_engineer.manager.python_verification_discovery._read_command",
            lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("secret-sentinel")),
        )
    elif stage == "endpoint":
        monkeypatch.setattr(
            "ai_software_engineer.manager.python_verification_discovery._read_command",
            lambda *args, **kwargs: "tcp://remote",
        )
    elif stage == "socket":
        docker_socket = tmp_path / "missing.sock"
    else:
        server, docker_socket = _bound_unix_socket()
        calls = iter(
            ("daemon-id", "invalid-image")
            if stage == "image"
            else ("daemon-id", "sha256:" + "0" * 64)
        )
        monkeypatch.setattr(
            "ai_software_engineer.manager.python_verification_discovery._read_command",
            (
                lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("secret-sentinel"))
                if stage == "daemon"
                else next(calls)
            ),
        )
        if stage == "python":
            monkeypatch.setattr(
                "ai_software_engineer.manager.python_verification_discovery.sys.executable",
                str(tmp_path / "missing-python"),
            )
        elif stage == "runner":
            monkeypatch.setattr(
                "ai_software_engineer.manager.python_verification_discovery.runner_file",
                str(tmp_path / "missing-runner"),
            )
        elif stage == "dependencies":
            runner = tmp_path / "runner.py"
            runner.write_text("runner\n")
            monkeypatch.setattr(
                "ai_software_engineer.manager.python_verification_discovery.runner_file",
                str(runner),
            )
            monkeypatch.setattr(
                "ai_software_engineer.manager.python_verification_discovery.dependency_fingerprint",
                lambda root: (_ for _ in ()).throw(ValueError("secret-sentinel")),
            )
        try:
            with pytest.raises(PythonMysqlDiscoveryError) as caught:
                discover_python_mysql_host_prerequisites(
                    codex_executable="codex", docker_socket=str(docker_socket)
                )
        finally:
            server.close()
            docker_socket.unlink(missing_ok=True)
        assert caught.value.code is expected
        assert "secret-sentinel" not in str(caught.value)
        return
    with pytest.raises(PythonMysqlDiscoveryError) as caught:
        discover_python_mysql_host_prerequisites(
            codex_executable="codex",
            docker_socket=str(docker_socket) if stage == "socket" else None,
        )
    assert caught.value.code is expected
    assert "secret-sentinel" not in str(caught.value)


def test_host_discovery_rejects_malformed_daemon_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _host_discovery_fixture(tmp_path, monkeypatch)
    server, docker_socket = _bound_unix_socket()
    monkeypatch.setattr(
        "ai_software_engineer.manager.python_verification_discovery._read_command",
        lambda *args, **kwargs: "",
    )
    try:
        with pytest.raises(PythonMysqlDiscoveryError) as caught:
            discover_python_mysql_host_prerequisites(
                codex_executable="codex", docker_socket=str(docker_socket)
            )
    finally:
        server.close()
        docker_socket.unlink(missing_ok=True)
    assert caught.value.code is NativeVerificationCapabilityDetail.DOCKER_DAEMON_UNAVAILABLE


def test_dependency_fingerprint_binds_source_and_loadable_bytecode(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("VALUE = 1\n")
    first = dependency_fingerprint(tmp_path)
    assert dependency_fingerprint(tmp_path) == first
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__/module.pyc").write_bytes(b"mutable interpreter cache")
    second = dependency_fingerprint(tmp_path)
    assert second != first
    (tmp_path / "module.py").write_text("VALUE = 2\n")
    assert dependency_fingerprint(tmp_path) != second


def test_dependency_fingerprint_binds_relative_names_and_modes(tmp_path: Path) -> None:
    original = tmp_path / "module.py"
    original.write_text("VALUE = 1\n")
    first = dependency_fingerprint(tmp_path)
    original.chmod(0o755)
    assert dependency_fingerprint(tmp_path) != first
    second = dependency_fingerprint(tmp_path)
    original.rename(tmp_path / "other.py")
    assert dependency_fingerprint(tmp_path) != second


def test_dependency_symlink_and_file_budget_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "escape.py").symlink_to(Path(__file__).resolve())
    with pytest.raises(ValueError, match="symbolic"):
        dependency_fingerprint(tmp_path)
    (tmp_path / "escape.py").unlink()
    (tmp_path / "module.py").write_text("VALUE = 1\n")
    with pytest.raises(ValueError, match="budget"):
        dependency_fingerprint(tmp_path, max_files=0)


def test_internal_file_alias_binds_target_and_link(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("VALUE = 1\n")
    (tmp_path / "alias.py").symlink_to("module.py")
    first = dependency_fingerprint(tmp_path)
    (tmp_path / "module.py").write_text("VALUE = 2\n")
    assert dependency_fingerprint(tmp_path) != first


def test_external_link_hop_returning_inside_tree_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "dependencies"
    root.mkdir()
    (root / "module.py").write_text("VALUE = 1\n")
    (tmp_path / "external-link").symlink_to(root / "module.py")
    (root / "alias.py").symlink_to(tmp_path / "external-link")
    with pytest.raises(ValueError, match="symbolic link"):
        dependency_fingerprint(root)


def test_candidate_selection_uses_regular_sealed_git_files(tmp_path: Path) -> None:
    def git(*arguments: str) -> str:
        return subprocess.check_output(
            ("/usr/bin/git", "-c", "core.hooksPath=/dev/null", *arguments),
            cwd=tmp_path,
            env={"PATH": os.defpath, "GIT_CONFIG_GLOBAL": "/dev/null"},
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).strip()

    git("init", "-q")
    (tmp_path / "tests").mkdir()
    test_file = tmp_path / "tests/test_case.py"
    test_file.write_text("raise RuntimeError('must never import during discovery')\n")
    (tmp_path / "tests/test_alias.py").symlink_to("test_case.py")
    git("add", "tests")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.test",
        "commit",
        "-qm",
        "fixture",
    )
    revision = git("rev-parse", "HEAD")
    # A mutable checkout deletion must not replace the approved candidate's facts.
    test_file.unlink()
    selection = PytestSelection(node_id="tests/test_case.py::test_case", criterion_ids=("ac_01",))
    require_selected_candidate_files(tmp_path, revision, (selection,))
    for node in ("tests/test_alias.py::test_case", "tests/test_missing.py::test_case"):
        with pytest.raises(ValueError, match="tracked regular candidate"):
            require_selected_candidate_files(
                tmp_path, revision, (PytestSelection(node_id=node, criterion_ids=("ac_01",)),)
            )


def test_unreadable_directory_cannot_produce_a_partial_fingerprint(tmp_path: Path) -> None:
    with (
        patch("os.scandir", side_effect=PermissionError("fixture unreadable directory")),
        pytest.raises(ValueError, match="completely fingerprinted"),
    ):
        dependency_fingerprint(tmp_path)


def test_nul_deny_inventory_preserves_legal_leading_and_trailing_spaces(tmp_path: Path) -> None:
    with patch(
        "ai_software_engineer.manager.python_verification_discovery.bounded_verification_command",
        return_value=b" denied.txt\0normal.txt\0trailing.txt \0",
    ):
        assert candidate_denied_paths(tmp_path, "a" * 40, (" denied.txt", "trailing.txt ")) == (
            " denied.txt",
            "trailing.txt ",
        )


def test_secret_like_untouched_denied_filename_is_not_sealed_or_echoed(tmp_path: Path) -> None:
    with patch(
        "ai_software_engineer.manager.python_verification_discovery.bounded_verification_command",
        return_value=b"private/password=fixture-credential.txt\0normal.py\0",
    ):
        with pytest.raises(ValueError, match="secret-like") as failure:
            candidate_denied_paths(tmp_path, "a" * 40, ("private/*",))
        assert "fixture-credential" not in str(failure.value)


def _host_prerequisites(tmp_path: Path) -> PythonMysqlHostPrerequisites:
    runtime = (tmp_path / "runtime").resolve()
    return PythonMysqlHostPrerequisites(
        sandbox_executable=str(tmp_path / "codex"),
        sandbox_executable_sha256="a" * 64,
        python_executable=str(runtime / "python"),
        python_executable_sha256="b" * 64,
        python_runtime_root=str(runtime),
        python_runtime_sha256="c" * 64,
        dependency_root=str(tmp_path / "dependencies"),
        dependency_sha256="d" * 64,
        runner_path=str(tmp_path / "runner.py"),
        runner_sha256="e" * 64,
        docker_executable=str(tmp_path / "docker"),
        docker_executable_sha256="f" * 64,
        docker_socket=str(tmp_path / "docker.sock"),
        docker_daemon_id="fixture-daemon",
        mysql_image_id="sha256:" + "0" * 64,
    )


def test_host_prerequisites_cannot_be_used_as_candidate_capability(tmp_path: Path) -> None:
    from ai_software_engineer.manager.python_verification import PythonMysqlSandboxCapability

    host = _host_prerequisites(tmp_path)
    assert "selections" not in host.to_wire()
    assert "denied_relative_paths" not in host.to_wire()
    with pytest.raises(ValueError):
        PythonMysqlSandboxCapability.model_validate(host.to_wire())
    with pytest.raises(ValueError):
        PythonMysqlSandboxCapability.model_validate(
            {**host.to_wire(), "kind": "codex_sandbox_pytest_mysql_v1"}
        )


def test_candidate_discovery_keeps_exact_selected_files_gate_before_host_discovery(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.manager.python_verification_discovery import (
        discover_python_mysql_capability,
    )

    selection = PytestSelection(
        node_id="tests/test_missing.py::test_case", criterion_ids=("ac_01",)
    )
    with (
        patch(
            "ai_software_engineer.manager.python_verification_discovery.platform.system",
            return_value="Darwin",
        ),
        patch(
            "ai_software_engineer.manager.python_verification_discovery.require_selected_candidate_files",
            side_effect=ValueError("missing exact candidate test"),
        ),
        patch(
            "ai_software_engineer.manager.python_verification_discovery.discover_python_mysql_host_prerequisites"
        ) as discover,
        pytest.raises(ValueError, match="missing exact candidate"),
    ):
        discover_python_mysql_capability(tmp_path, "a" * 40, (selection,), codex_executable="codex")
    discover.assert_not_called()


def test_candidate_capability_binds_fresh_host_without_changing_legacy_wire_fields(
    tmp_path: Path,
) -> None:
    from ai_software_engineer.manager.python_verification_discovery import (
        discover_python_mysql_capability,
    )

    host = _host_prerequisites(tmp_path)
    selection = PytestSelection(node_id="tests/test_case.py::test_case", criterion_ids=("ac_01",))
    with (
        patch(
            "ai_software_engineer.manager.python_verification_discovery.platform.system",
            return_value="Darwin",
        ),
        patch(
            "ai_software_engineer.manager.python_verification_discovery.require_selected_candidate_files"
        ) as require,
        patch(
            "ai_software_engineer.manager.python_verification_discovery.candidate_denied_paths",
            return_value=("private/secret.txt",),
        ),
        patch(
            "ai_software_engineer.manager.python_verification_discovery.discover_python_mysql_host_prerequisites",
            return_value=host,
        ) as discover,
    ):
        result = discover_python_mysql_capability(
            tmp_path, "a" * 40, (selection,), codex_executable="codex"
        )
    require.assert_called_once_with(tmp_path, "a" * 40, (selection,))
    discover.assert_called_once_with(
        codex_executable="codex",
        docker_executable="docker",
        docker_socket=None,
        mysql_image="mysql:8.0",
    )
    expected = {
        **host.to_wire(),
        "kind": "codex_sandbox_pytest_mysql_v1",
        "selections": [selection.to_wire()],
        "denied_relative_paths": ["private/secret.txt"],
        "max_cases": 256,
        "resource_timeout_seconds": 1200,
        "transport": "pymysql_unix_proxy_docker_exec_loopback",
    }
    assert result.to_wire() == expected
