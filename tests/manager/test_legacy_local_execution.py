"""Current local surveys are a prerequisite, never a historical stop receipt."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest

from ai_software_engineer.manager.legacy_containment import LocalBootObservation
from ai_software_engineer.manager.legacy_local_execution import (
    LegacyLocalExecutionSurvey,
    LegacyRescuePrerequisiteError,
    TrustedLegacyLocalExecutionObserver,
)
from ai_software_engineer.owned_processes import OwnedProcessesUncertain

OBSERVED = datetime(2026, 10, 8, 1, tzinfo=UTC)
BOOT = LocalBootObservation(
    machine_sha256="a" * 64,
    boot_session_sha256="b" * 64,
    booted_at=OBSERVED - timedelta(days=2),
)


def survey(**updates: object) -> LegacyLocalExecutionSurvey:
    return LegacyLocalExecutionSurvey.create(
        **{
            "worktree_path": "/worktrees/original-coder",
            "machine_sha256": BOOT.machine_sha256,
            "boot_session_sha256": BOOT.boot_session_sha256,
            "account_sha256": "c" * 64,
            "observed_at": OBSERVED,
            "scanner_version": "local-execution-v1",
            "blockers": (),
            **updates,
        }
    )


def test_sealed_survey_is_idle_and_does_not_claim_an_original_stop() -> None:
    value = survey()
    value.validate_integrity()
    value.require_idle()
    assert "process_stop" not in value.to_wire()
    assert "pid" not in value.to_wire()
    with pytest.raises(ValueError, match="完整性"):
        value.model_copy(update={"account_sha256": "d" * 64}).validate_integrity()


def test_stable_boundary_ignores_observation_time_and_unrelated_process_churn() -> None:
    first = survey()
    second = survey(observed_at=OBSERVED + timedelta(seconds=2))
    assert first.survey_sha256 != second.survey_sha256
    assert first.same_boundary(second)
    first.require_idle()
    second.require_idle()


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("worktree_path", "/worktrees/another-coder"),
        ("machine_sha256", "d" * 64),
        ("boot_session_sha256", "d" * 64),
        ("account_sha256", "d" * 64),
        ("scanner_version", "local-execution-v2"),
    ],
)
def test_boundary_drift_is_not_stable(field: str, changed: str) -> None:
    assert not survey().same_boundary(survey(**{field: changed}))


def test_blocker_returns_actionable_typed_wait_without_raw_identifiers() -> None:
    with pytest.raises(LegacyRescuePrerequisiteError) as failure:
        survey(blockers=("CODEX_EXECUTION_ACTIVE",)).require_idle()
    error = failure.value
    assert error.code == "LEGACY_LOCAL_EXECUTION_ACTIVE"
    assert "执行" in error.safe_message and error.next_action
    assert str(error) == error.safe_message
    assert (
        LegacyRescuePrerequisiteError(
            code="fixture", safe_message="安全原因", next_action="下一步"
        ).next_action
        == "下一步"
    )


class MacFixtureObserver(TrustedLegacyLocalExecutionObserver):
    def __init__(
        self,
        *,
        commands: tuple[str, str] = (
            "101 501 S Thu Oct  8 08:00:00 2026 /usr/bin/editor",
            "101 501 S Thu Oct  8 08:00:00 2026 /usr/bin/editor",
        ),
        open_files: bytes = b"p101\0\nfcwd\0tDIR\0n/elsewhere\0\n",
        failure: Literal["query", "truncated"] | None = None,
    ) -> None:
        self.commands = list(commands)
        self.open_files = open_files
        self.failure = failure
        self.calls: list[tuple[str, ...]] = []

    def _query(self, argv: tuple[str, ...]) -> bytes:
        self.calls.append(argv)
        if self.failure == "query":
            raise OSError("raw secret or native argv must not escape")
        if self.failure == "truncated":
            return b"x" * (self.MAX_QUERY_BYTES + 1)
        if argv[0] == "/bin/ps":
            return self.commands.pop(0).encode()
        return self.open_files

    def _birth(self, pid: int) -> str:
        # Native OS identity is separately tested; this fake must not inspect
        # the real process accidentally sharing its fixture PID.
        return "fixture-birth"


@pytest.fixture
def mac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ai_software_engineer.manager.legacy_local_execution.sys.platform", "darwin"
    )
    monkeypatch.setattr(
        "ai_software_engineer.manager.legacy_local_execution.os.getuid", lambda: 501
    )
    monkeypatch.setattr(
        "ai_software_engineer.manager.legacy_local_execution.os.geteuid", lambda: 501
    )


def test_mac_fixed_read_only_scan_accepts_unrelated_process_without_recording_argv(
    tmp_path: Path, mac: None
) -> None:
    observer = MacFixtureObserver()
    result = observer.observe(worktree_root=tmp_path, boot=BOOT)
    result.require_idle()
    assert result.worktree_path == str(tmp_path.resolve())
    assert result.machine_sha256 == BOOT.machine_sha256
    assert "editor" not in result.model_dump_json() and '"101"' not in result.model_dump_json()
    assert not ({"pid", "argv", "processes", "environment"} & result.to_wire().keys())
    assert observer.calls == [
        ("/bin/ps", "-ww", "-U", "501", "-o", "pid=,uid=,stat=,lstart=,command="),
        ("/usr/sbin/lsof", "-n", "-P", "-a", "-u", "501", "-F0pftn"),
        ("/bin/ps", "-ww", "-U", "501", "-o", "pid=,uid=,stat=,lstart=,command="),
    ]


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("/usr/local/bin/codex exec --model secret-model", "CODEX_EXECUTION_ACTIVE"),
        ("/bin/sh -c codex --resume secret-token", "CODEX_WRAPPER_ACTIVE"),
        ("/usr/bin/node /opt/codex.js exec secret-prompt", "CODEX_EXECUTION_ACTIVE"),
        ("/usr/bin/python -m ai_software_engineer.cli task run task_old", "CODEX_WRAPPER_ACTIVE"),
    ],
)
def test_current_native_or_wrapped_execution_blocks_without_leaking_arguments(
    tmp_path: Path, mac: None, command: str, expected: str
) -> None:
    row = f"101 501 S Thu Oct  8 08:00:00 2026 {command}"
    result = MacFixtureObserver(commands=(row, row)).observe(worktree_root=tmp_path, boot=BOOT)
    assert expected in result.blockers
    assert "secret" not in result.model_dump_json()
    with pytest.raises(LegacyRescuePrerequisiteError):
        result.require_idle()


@pytest.mark.parametrize("descriptor", ["cwd", "4"])
def test_worktree_cwd_and_open_file_are_detected_for_any_local_process(
    tmp_path: Path, mac: None, descriptor: str
) -> None:
    opened = tmp_path if descriptor == "cwd" else tmp_path / "draft.py"
    body = (
        b"p101\0\nfcwd\0tDIR\0n/elsewhere\0\n"
        + f"f{descriptor}\0t{'DIR' if descriptor == 'cwd' else 'REG'}\0n{opened}\0\n".encode()
    )
    result = MacFixtureObserver(open_files=body).observe(worktree_root=tmp_path, boot=BOOT)
    assert "WORKTREE_PROCESS_ACTIVE" in result.blockers


@pytest.mark.parametrize("problem", ["query", "truncated", "unknown_state", "missing_pid", "reuse"])
def test_incomplete_scan_is_not_stop_proof_even_without_direct_children(
    tmp_path: Path, mac: None, problem: str
) -> None:
    observer = MacFixtureObserver()
    if problem == "query":
        observer.failure = "query"
    elif problem == "truncated":
        observer.failure = "truncated"
    elif problem == "unknown_state":
        observer.commands[0] = "101 501 ? Thu Oct  8 08:00:00 2026 /usr/bin/editor"
    elif problem == "missing_pid":
        observer.open_files = b"p102\0\nfcwd\0tDIR\0n/elsewhere\0\n"
    else:
        births = iter(("birth-first", "birth-second"))
        observer._birth = lambda pid: next(births)  # type: ignore[method-assign]
    result = observer.observe(worktree_root=tmp_path, boot=BOOT)
    assert (
        "PROCESS_SCAN_INCOMPLETE" in result.blockers or "PROCESS_STATE_UNKNOWN" in result.blockers
    )
    assert "secret" not in result.model_dump_json()
    with pytest.raises(LegacyRescuePrerequisiteError):
        result.require_idle()


def test_similarly_named_neighbor_worktree_does_not_match(tmp_path: Path, mac: None) -> None:
    body = f"p101\0\nfcwd\0tDIR\0n{tmp_path}-other\0\n".encode()
    MacFixtureObserver(open_files=body).observe(worktree_root=tmp_path, boot=BOOT).require_idle()


def test_unrelated_process_churn_does_not_block_complete_scan(tmp_path: Path, mac: None) -> None:
    first = (
        "101 501 S Thu Oct  8 08:00:00 2026 /usr/bin/editor\n"
        "102 501 S Thu Oct  8 08:00:00 2026 /usr/bin/short"
    )
    second = (
        "101 501 S Thu Oct  8 08:00:00 2026 /usr/bin/editor\n"
        "103 501 S Thu Oct  8 08:00:00 2026 /usr/bin/short"
    )
    files = b"p101\0\nfcwd\0tDIR\0n/elsewhere\0\np103\0\nfcwd\0tDIR\0n/elsewhere\0\n"
    MacFixtureObserver(commands=(first, second), open_files=files).observe(
        worktree_root=tmp_path, boot=BOOT
    ).require_idle()


def test_new_live_process_without_path_coverage_is_not_an_idle_scan(
    tmp_path: Path, mac: None
) -> None:
    first = "101 501 S Thu Oct  8 08:00:00 2026 /usr/bin/editor"
    second = first + "\n103 501 S Thu Oct  8 08:00:00 2026 /usr/bin/unknown-tool"
    result = MacFixtureObserver(commands=(first, second)).observe(worktree_root=tmp_path, boot=BOOT)
    assert "PROCESS_SCAN_INCOMPLETE" in result.blockers


def test_desktop_protocol_server_is_not_an_active_native_exec(tmp_path: Path, mac: None) -> None:
    row = "101 501 S Thu Oct  8 08:00:00 2026 /Applications/Codex.app/vendor/codex app-server"
    MacFixtureObserver(commands=(row, row)).observe(
        worktree_root=tmp_path, boot=BOOT
    ).require_idle()


def test_later_boot_comparison_never_relaxes_other_boundaries() -> None:
    assert survey().same_boundary(survey(boot_session_sha256="d" * 64), allow_new_boot=True)
    assert not survey().same_boundary(
        survey(boot_session_sha256="d" * 64, account_sha256="e" * 64), allow_new_boot=True
    )


def test_owned_query_stop_uncertainty_is_a_wait_not_a_generic_failure(
    tmp_path: Path, mac: None
) -> None:
    class Observer(MacFixtureObserver):
        def _query(self, argv: tuple[str, ...]) -> bytes:
            raise OwnedProcessesUncertain("query still has an unverified stop")

    result = Observer().observe(worktree_root=tmp_path, boot=BOOT)
    assert result.blockers == ("PROCESS_SCAN_INCOMPLETE",)
    with pytest.raises(LegacyRescuePrerequisiteError, match="尚未完成"):
        result.require_idle()


def test_account_privilege_change_is_not_a_supported_scan(
    tmp_path: Path, mac: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ai_software_engineer.manager.legacy_local_execution.os.geteuid", lambda: 0)
    observer = MacFixtureObserver()
    result = observer.observe(worktree_root=tmp_path, boot=BOOT)
    assert result.blockers == ("PROCESS_SCAN_INCOMPLETE",) and not observer.calls


@pytest.mark.parametrize("reference", ["cwd", "open_file", "unrelated"])
def test_linux_checks_real_proc_cwd_and_descriptor_links(
    tmp_path: Path, mac: None, monkeypatch: pytest.MonkeyPatch, reference: str
) -> None:
    monkeypatch.setattr("ai_software_engineer.manager.legacy_local_execution.sys.platform", "linux")
    proc_root = tmp_path / "proc"
    proc = proc_root / "101"
    (proc / "fd").mkdir(parents=True)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (proc / "cwd").symlink_to(worktree if reference == "cwd" else tmp_path)
    (proc / "fd" / "1").symlink_to(
        worktree / "draft.py" if reference == "open_file" else tmp_path / "unrelated"
    )
    monkeypatch.setattr("ai_software_engineer.manager.legacy_local_execution._PROC_ROOT", proc_root)
    result = MacFixtureObserver().observe(worktree_root=worktree, boot=BOOT)
    assert ("WORKTREE_PROCESS_ACTIVE" in result.blockers) == (reference != "unrelated")
    assert "PROCESS_SCAN_INCOMPLETE" not in result.blockers


def test_linux_unreadable_process_and_pid_limit_fail_closed(
    tmp_path: Path, mac: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ai_software_engineer.manager.legacy_local_execution.sys.platform", "linux")
    monkeypatch.setattr("ai_software_engineer.manager.legacy_local_execution._PROC_ROOT", tmp_path)
    result = MacFixtureObserver().observe(worktree_root=tmp_path, boot=BOOT)
    assert result.blockers == ("PROCESS_SCAN_INCOMPLETE",)
    monkeypatch.setattr("ai_software_engineer.manager.legacy_local_execution._MAX_PROCESSES", 0)
    result = MacFixtureObserver().observe(worktree_root=tmp_path, boot=BOOT)
    assert result.blockers == ("PROCESS_SCAN_INCOMPLETE",)


def test_mac_alias_path_is_detected_and_desktop_process_still_cannot_hold_worktree(
    tmp_path: Path, mac: None
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(worktree)
    row = "101 501 S Thu Oct  8 08:00:00 2026 /Applications/Codex.app/vendor/codex app-server"
    body = f"p101\0\nfcwd\0tDIR\0n{alias}\0\n".encode()
    result = MacFixtureObserver(commands=(row, row), open_files=body).observe(
        worktree_root=worktree, boot=BOOT
    )
    assert result.blockers == ("WORKTREE_PROCESS_ACTIVE",)


def test_codex_resume_inside_desktop_resources_is_still_active(tmp_path: Path, mac: None) -> None:
    row = (
        "101 501 S Thu Oct  8 08:00:00 2026 "
        "/Applications/Codex.app/Contents/Resources/codex resume hidden-session"
    )
    result = MacFixtureObserver(commands=(row, row)).observe(worktree_root=tmp_path, boot=BOOT)
    assert result.blockers == ("CODEX_WRAPPER_ACTIVE",)


def test_real_uid_login_parent_is_excluded_but_effective_account_is_complete(
    tmp_path: Path, mac: None
) -> None:
    row = (
        "101 501 S Thu Oct  8 08:00:00 2026 /usr/bin/editor\n"
        "102 0 S Thu Oct  8 08:00:00 2026 /usr/bin/login"
    )
    MacFixtureObserver(commands=(row, row)).observe(
        worktree_root=tmp_path, boot=BOOT
    ).require_idle()


def test_linux_birth_uses_kernel_start_ticks_not_ps_seconds(
    tmp_path: Path, mac: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ai_software_engineer.manager.legacy_local_execution.sys.platform", "linux")
    proc_root = tmp_path / "proc"
    proc = proc_root / "101"
    (proc / "fd").mkdir(parents=True)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (proc / "cwd").symlink_to(tmp_path)
    (proc / "stat").write_text("101 (worker with ) bracket) " + " ".join(["S", *["0"] * 18, "77"]))
    monkeypatch.setattr("ai_software_engineer.manager.legacy_local_execution._PROC_ROOT", proc_root)

    class Observer(MacFixtureObserver):
        def _birth(self, pid: int) -> str:
            return TrustedLegacyLocalExecutionObserver._birth(self, pid)

    Observer().observe(worktree_root=worktree, boot=BOOT).require_idle()


def test_query_permission_denial_is_incomplete_without_raw_exception(
    tmp_path: Path, mac: None
) -> None:
    class Observer(MacFixtureObserver):
        def _query(self, argv: tuple[str, ...]) -> bytes:
            raise PermissionError("secret process args must not leak")

    result = Observer().observe(worktree_root=tmp_path, boot=BOOT)
    assert result.blockers == ("PROCESS_SCAN_INCOMPLETE",)
    assert "secret" not in result.model_dump_json()
