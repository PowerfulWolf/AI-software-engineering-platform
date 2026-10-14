"""Pause the actual owned call without manufacturing completion or timeouts."""

import os
import sys
from pathlib import Path
from threading import Event, Thread

import pytest

from ai_software_engineer.agents.codex_cli import SubprocessCodexCommandRunner
from ai_software_engineer.service_pause import (
    PausedProcessReceipt,
    ServicePauseControl,
    ServicePauseRequested,
    check_service_pause,
)


def test_pause_scope_closes_future_admission_and_does_not_leak() -> None:
    control = ServicePauseControl(grace_seconds=0)
    with control.operation_scope("operation_fixture"):
        check_service_pause()
        control.request(request_id="shutdown_fixture", instance_id="instance_fixture")
        with pytest.raises(ServicePauseRequested):
            check_service_pause()
        control.request(request_id="shutdown_retry", instance_id="instance_fixture")
        assert control.request_id == "shutdown_fixture"
        control.cancel()
        check_service_pause()
    control.request()
    check_service_pause()


def test_pause_stops_real_owned_session_and_seals_the_exact_reason(tmp_path: Path) -> None:
    saved: list[PausedProcessReceipt] = []
    control = ServicePauseControl(grace_seconds=0.05, persist_stop=saved.append)
    finished = Event()
    outcomes = []

    def execute() -> None:
        with control.operation_scope("operation_fixture"):
            outcomes.append(
                SubprocessCodexCommandRunner().run(
                    (
                        sys.executable,
                        "-c",
                        "from pathlib import Path; import time; "
                        "Path('started').write_text('yes'); time.sleep(60)",
                    ),
                    cwd=tmp_path,
                    environment={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
                    stdin="",
                    timeout_seconds=60,
                )
            )
        finished.set()

    thread = Thread(target=execute)
    thread.start()
    try:
        for _ in range(300):
            if (tmp_path / "started").exists():
                break
            finished.wait(0.01)
        assert (tmp_path / "started").exists()
        control.request(request_id="shutdown_fixture", instance_id="instance_fixture")
        assert finished.wait(5)
    finally:
        control.request()
        thread.join(5)
    assert len(outcomes) == len(saved) == 1
    outcome = outcomes[0]
    assert not outcome.timed_out
    assert outcome.process_stop is not None
    assert outcome.process_stop.kind == "service_pause"
    assert outcome.process_stop.session_proof is not None
    saved[0].validate_integrity()
    assert saved[0].process_stop == outcome.process_stop
    assert saved[0].operation_id == "operation_fixture"
    assert saved[0].request_id == "shutdown_fixture"


@pytest.mark.parametrize("grace", [-1, float("inf"), float("nan"), 301])
def test_pause_window_must_be_finite_and_bounded(grace: float) -> None:
    with pytest.raises(ValueError):
        ServicePauseControl(grace_seconds=grace)


def test_resuming_during_actual_stop_preserves_original_pause_epoch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_software_engineer.owned_sessions import OwnedSessionController, OwnedSessionStopProof

    saved: list[PausedProcessReceipt] = []
    control = ServicePauseControl(grace_seconds=0, persist_stop=saved.append)
    actual_stop = OwnedSessionController.stop

    def resume_then_stop(
        controller: OwnedSessionController, *, timeout_seconds: float = 1.0
    ) -> OwnedSessionStopProof:
        control.cancel()
        return actual_stop(controller, timeout_seconds=timeout_seconds)

    monkeypatch.setattr(OwnedSessionController, "stop", resume_then_stop)

    def request_pause() -> None:
        from time import sleep

        for _ in range(200):
            if (tmp_path / "started").exists():
                control.request(request_id="original_request")
                return
            sleep(0.01)
        raise AssertionError("fixture process failed to start")

    thread = Thread(target=request_pause)
    thread.start()
    with control.operation_scope("operation_resume_race"):
        result = SubprocessCodexCommandRunner().run(
            (
                sys.executable,
                "-c",
                "from pathlib import Path; import time; "
                "Path('started').write_text('yes'); time.sleep(60)",
            ),
            cwd=tmp_path,
            environment={"PATH": os.defpath},
            stdin="",
            timeout_seconds=5,
        )
    thread.join(2)
    assert result.process_stop is not None and result.process_stop.kind == "service_pause"
    assert not control.requested() and len(saved) == 1
    assert saved[0].request_id == "original_request"
    saved[0].validate_integrity()
