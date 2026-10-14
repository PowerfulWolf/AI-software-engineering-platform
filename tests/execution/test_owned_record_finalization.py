"""Actual durable writes own registry finalization; local command success does not."""

import hashlib
import sys
from pathlib import Path

import pytest

from ai_software_engineer.agents import (
    AgentRequest,
    AgentResult,
    FakeAgentAdapter,
    FakeBehavior,
    FakeScenario,
)
from ai_software_engineer.domain import AgentPermissions, NetworkAccess
from ai_software_engineer.evidence import (
    EvidenceCapturingAgentAdapter,
    EvidenceRecord,
    RunEvidenceManifest,
    RunOutcome,
)
from ai_software_engineer.execution import (
    CommandExecutionUncertain,
    CommandTimedOut,
    SubprocessCommandExecutor,
)
from ai_software_engineer.owned_processes import (
    HostOwnedProcessRegistry,
    OwnedProcessesUncertain,
    owned_record_finalization,
)
from tests.evidence.test_capture import _session


def _executor(root: Path) -> SubprocessCommandExecutor:
    root.mkdir(exist_ok=True)
    return SubprocessCommandExecutor(
        root,
        AgentPermissions(
            read_paths=("**",),
            write_paths=("**",),
            commands=(sys.executable,),
            network=NetworkAccess.NONE,
        ),
    )


def test_command_record_save_failure_keeps_registry_uncertain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session(tmp_path)
    executor = _executor(tmp_path / "worktree")
    registry = HostOwnedProcessRegistry()

    def failed(_: EvidenceRecord) -> EvidenceRecord:
        assert registry.snapshot()[0].state == "finalizing"
        assert not registry.await_stopped(0)
        raise OSError("fixture command evidence save failed")

    monkeypatch.setattr(session._store, "put", failed)
    with registry.operation_scope("operation_command_save"), pytest.raises(OSError):
        session.capture_command("command.one", executor, (sys.executable, "-c", "print('ok')"))
    assert registry.shutdown_failed
    with pytest.raises(OwnedProcessesUncertain):
        registry.require_stopped()


@pytest.mark.parametrize("timeout", [False, True])
def test_real_command_record_save_precedes_registry_removal(tmp_path: Path, timeout: bool) -> None:
    session = _session(tmp_path)
    executor = _executor(tmp_path / "worktree")
    registry = HostOwnedProcessRegistry()
    argv = (sys.executable, "-c", "import time;time.sleep(10)" if timeout else "print('ok')")
    with registry.operation_scope("operation_saved_command"):
        if timeout:
            with pytest.raises(CommandTimedOut):
                session.capture_command("command.one", executor, argv, timeout_seconds=0.05)
        else:
            session.capture_command("command.one", executor, argv)
    assert len(session._store.list_for_run(session.identity.run_id)) == 1
    registry.require_stopped()


@pytest.mark.parametrize("fail_seal", [False, True])
def test_multiple_saved_commands_wait_for_actual_run_manifest_seal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_seal: bool,
) -> None:
    session = _session(tmp_path)
    executor = _executor(tmp_path / "worktree")
    registry = HostOwnedProcessRegistry()
    request = AgentRequest(
        run_id=session.identity.run_id,
        task_id=session.identity.task_id,
        role=session.identity.role,
        attempt=1,
        source_revision=session.identity.source_revision,
        context_manifest_id=session.identity.context_manifest_id,
        input_artifact_ids=(),
        permissions=AgentPermissions(
            read_paths=("**",),
            write_paths=("**",),
            commands=(sys.executable,),
            network=NetworkAccess.NONE,
        ),
        output_schema="schemas/coder-output.schema.json",
        timeout_seconds=60,
    )

    class Delegate:
        def run(self, value: AgentRequest) -> AgentResult:
            for index in range(2):
                session.capture_command(
                    f"command.{index}",
                    executor,
                    (sys.executable, "-c", "print('ok')"),
                )
            assert len(registry.snapshot()) == 2
            assert all(p.state == "finalizing" for p in registry.snapshot())
            return FakeAgentAdapter(default=FakeScenario(behavior=FakeBehavior.PROVIDER_ERROR)).run(
                value
            )

    if fail_seal:

        def failed(_: RunEvidenceManifest) -> RunEvidenceManifest:
            assert len(registry.snapshot()) == 2
            raise OSError("fixture run manifest seal failed")

        monkeypatch.setattr(session._store, "seal_run", failed)
    adapter = EvidenceCapturingAgentAdapter(Delegate(), session, provider="fake", model="offline")
    with registry.operation_scope("operation_run_seal"):
        if fail_seal:
            with pytest.raises(OSError):
                adapter.run(request)
        else:
            adapter.run(request)
    if fail_seal:
        assert len(registry.snapshot()) == 2 and registry.shutdown_failed
    else:
        assert session._store.get_run(session.identity.run_id).outcome == RunOutcome.FAILED
        registry.require_stopped()


def test_finalization_is_bounded_and_no_local_success_can_confirm_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ai_software_engineer.owned_processes._MAX_FINALIZATION_PROCESSES", 1)
    registry = HostOwnedProcessRegistry()
    executor = _executor(tmp_path)
    with (
        registry.operation_scope("operation_bound"),
        pytest.raises(CommandExecutionUncertain),
        owned_record_finalization(),
    ):
        executor.run((sys.executable, "-c", "print('one')"))
        executor.run((sys.executable, "-c", "print('two')"))
    assert registry.shutdown_failed and not registry.await_stopped(0)


def test_normal_scope_exit_without_actual_save_never_clears_registry(tmp_path: Path) -> None:
    registry = HostOwnedProcessRegistry()
    with registry.operation_scope("operation_no_save"), owned_record_finalization():
        _executor(tmp_path).run((sys.executable, "-c", "print('local complete')"))
        assert registry.snapshot()[0].state == "finalizing"
    assert registry.shutdown_failed
    with pytest.raises(OwnedProcessesUncertain):
        registry.require_stopped()


@pytest.mark.parametrize("violation", ["duplicate_confirmation", "spawn_after_confirmation"])
def test_finalization_protocol_error_invalidates_all_pending_observations(
    tmp_path: Path,
    violation: str,
) -> None:
    registry = HostOwnedProcessRegistry()
    executor = _executor(tmp_path)
    with (
        registry.operation_scope("operation_protocol_error"),
        owned_record_finalization() as finalization,
    ):
        executor.run((sys.executable, "-c", "print('one')"))
        finalization.confirm_saved()
        if violation == "duplicate_confirmation":
            with pytest.raises(OwnedProcessesUncertain):
                finalization.confirm_saved()
        else:
            with pytest.raises(CommandExecutionUncertain):
                executor.run((sys.executable, "-c", "print('late')"))
    assert len(registry.snapshot()) == (1 if violation == "duplicate_confirmation" else 2)
    assert all(value.state == "uncertain" for value in registry.snapshot())


@pytest.mark.parametrize("fail_save", [False, True])
def test_controlled_verification_registry_waits_for_actual_receipt_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_save: bool,
) -> None:
    from ai_software_engineer.recovery.verification_execution import BoundSwiftVerificationEvidence
    from ai_software_engineer.recovery.verification_records import VerificationExecutionRecord
    from tests.recovery.test_verification_environment import _admitted, capability

    binary = tmp_path / "fixture-executor"
    binary.write_text("#!/bin/sh\n/bin/sleep 0.03\n/usr/bin/printf 'fixture command\\n'\n")
    binary.chmod(0o700)
    cap = capability().model_copy(
        update={
            "sandbox_executable": str(binary),
            "sandbox_executable_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        }
    )
    plan, store, facts, requests, _ = _admitted(tmp_path, executor_capability=cap)
    root = tmp_path / "worktrees"
    source = root / plan.execution_task_id / "qa-attempt-01"
    source.mkdir(parents=True)
    registry = HostOwnedProcessRegistry()

    original_put = store.put_verification_execution

    def put(record: VerificationExecutionRecord) -> VerificationExecutionRecord:
        if record.phase != "STARTED":
            assert len(registry.snapshot()) == 2
            assert all(p.state == "finalizing" for p in registry.snapshot())
            if fail_save:
                raise OSError("fixture verification receipt save failed")
        return original_put(record)

    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_execution.discover_swift_sandbox_capability",
        lambda _: cap,
    )
    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_execution._require_clean_candidate",
        lambda *_: None,
    )
    monkeypatch.setattr(store, "put_verification_execution", put)
    provider = BoundSwiftVerificationEvidence(
        store=store,
        plan=plan,
        facts=facts,
        worktree_root=root,
    )
    with registry.operation_scope("operation_verification_receipt"):
        if fail_save:
            with pytest.raises(OSError):
                provider.evidence_for(requests[0], source)
        else:
            provider.evidence_for(requests[0], source)
    if fail_save:
        assert registry.shutdown_failed and len(registry.snapshot()) == 2
    else:
        registry.require_stopped()


@pytest.mark.parametrize("started", [False, True])
def test_service_pause_command_evidence_finishes_before_owned_registry_release(
    tmp_path: Path, started: bool
) -> None:
    from threading import Thread
    from time import sleep

    from ai_software_engineer.evidence.models import CommandOutcome
    from ai_software_engineer.execution import CommandServicePaused
    from ai_software_engineer.service_pause import (
        PausedProcessReceipt,
        ServicePauseControl,
        ServicePauseRequested,
    )

    session = _session(tmp_path)
    root = tmp_path / "worktree"
    executor = _executor(root)
    registry = HostOwnedProcessRegistry()
    saved: list[PausedProcessReceipt] = []
    control = ServicePauseControl(grace_seconds=0, persist_stop=saved.append)
    thread: Thread | None = None
    if started:

        def request() -> None:
            for _ in range(500):
                if (root / "started").exists():
                    control.request()
                    return
                sleep(0.01)
            raise AssertionError("command never started")

        thread = Thread(target=request)
        thread.start()
    else:
        control.request()
    with (
        control.operation_scope("operation_command_pause"),
        registry.operation_scope("operation_command_pause"),
        pytest.raises((CommandServicePaused, ServicePauseRequested)),
    ):
        session.capture_command(
            "command.paused",
            executor,
            (
                sys.executable,
                "-c",
                "from pathlib import Path; import time; "
                "Path('started').write_text('yes'); time.sleep(60)",
            ),
        )
    if thread is not None:
        thread.join(5)
        assert not thread.is_alive()
    (evidence,) = session._store.list_for_run(session.identity.run_id)
    from ai_software_engineer.evidence.models import CommandEvidenceRecord

    assert isinstance(evidence, CommandEvidenceRecord)
    assert evidence.payload.outcome is CommandOutcome.SERVICE_PAUSED
    assert len(saved) == int(started)
    registry.require_stopped()
