"""Credential boundary, exact admitted receipts and no replay of uncertain execution."""

from unittest.mock import Mock

import pytest

from ai_software_engineer.manager.verification_process import bounded_verification_command
from ai_software_engineer.recovery.models import RecoveryRejected
from ai_software_engineer.recovery.python_mysql_execution import safe_verification_output
from ai_software_engineer.recovery.store import RecoveryRecordMissing


def test_independent_role_receipts_are_admitted_durable_secret_free_and_not_replayed(
    tmp_path, monkeypatch
):

    from ai_software_engineer.execution import CommandResult, SubprocessCommandExecutor
    from ai_software_engineer.recovery.python_mysql_execution import (
        BoundPythonMysqlVerificationEvidence,
    )
    from ai_software_engineer.recovery.python_mysql_records import MysqlResourceRecord
    from ai_software_engineer.recovery.store import FileRecoveryStore
    from tests.manager.test_python_verification import capability
    from tests.recovery.test_verification_environment import _admitted

    cap = capability(tmp_path).model_copy(update={"denied_relative_paths": ("private.txt",)})
    plan, store, facts, requests, _ = _admitted(tmp_path, executor_capability=cap)
    prefix = "ai_software_engineer.recovery.python_mysql_execution."

    def discover(*args, **kwargs):
        assert kwargs["denied_patterns"] == ("private.txt",)
        return cap

    monkeypatch.setattr(prefix + "discover_python_mysql_capability", discover)
    monkeypatch.setattr(prefix + "_require_clean_candidate", lambda *a: None)
    resources = []

    class Resource:
        password = "0123456789abcdef" * 3
        secrets = (password, "9876543210fedcba" * 3)

        def __init__(self, intent, publish, clock):
            self.intent, self.publish, self.clock = intent, publish, clock
            resources.append(self)

        def start(self, guard):
            guard()
            self.publish(
                MysqlResourceRecord.create(
                    phase="INTENT", intent=self.intent, recorded_at=self.clock()
                )
            )
            self.publish(
                MysqlResourceRecord.create(
                    phase="CREATED",
                    intent=self.intent,
                    container_id="c" * 64,
                    configuration_sha256="d" * 64,
                    recorded_at=self.clock(),
                )
            )

        def verify_principal(self, endpoint):
            pass

        def close(self):
            self.publish(
                MysqlResourceRecord.create(
                    phase="CLEANED",
                    intent=self.intent,
                    container_id="c" * 64,
                    configuration_sha256="d" * 64,
                    recorded_at=self.clock(),
                )
            )

    monkeypatch.setattr(prefix + "IsolatedMysqlResource", Resource)
    monkeypatch.setattr(prefix + "MysqlUnixProxy", Mock())
    executed = []

    def run(executor, argv):
        executed.append(argv)
        return CommandResult(
            argv=argv,
            cwd=str(executor._workspace_root),
            returncode=0,
            stdout=Resource.password,
            stderr=Resource.secrets[1][:32],
            stderr_truncated=True,
            duration_ms=1,
        )

    monkeypatch.setattr(SubprocessCommandExecutor, "run", run)
    root = tmp_path / "worktrees"
    provider = BoundPythonMysqlVerificationEvidence(
        store=store, plan=plan, facts=facts, worktree_root=root
    )
    for request in requests:
        source = root / plan.execution_task_id / f"{request.role.value}-attempt-01"
        source.mkdir(parents=True)
        evidence = provider.evidence_for(request, source)
        assert "not a QA/Review verdict" in evidence.text
        assert (
            Resource.password not in evidence.text and Resource.secrets[1][:32] not in evidence.text
        )
        assert provider.evidence_for(request, source) == evidence
        reopened = BoundPythonMysqlVerificationEvidence(
            store=FileRecoveryStore(store._root, scope=plan.scope),
            plan=plan,
            facts=facts,
            worktree_root=root,
        )
        assert reopened.evidence_for(request, source) == evidence
    assert len(executed) == 2
    assert {resource.intent.role for resource in resources} == {"qa", "reviewer"}
    assert len({resource.intent.resource_id for resource in resources}) == 2
    for resource in resources:
        assert (
            store.get_mysql_resource(resource.intent.resource_id, "CLEANED").container_id
            == "c" * 64
        )
    facts.stale = True
    with pytest.raises(RecoveryRejected, match="facts changed"):
        provider.evidence_for(requests[0], root / plan.execution_task_id / "qa-attempt-01")
    assert len(executed) == 2


def test_uncertain_start_and_unapproved_resource_never_execute(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from ai_software_engineer.domain import AgentRole
    from ai_software_engineer.recovery.models import RecoveryRejected
    from ai_software_engineer.recovery.python_mysql_execution import (
        BoundPythonMysqlVerificationEvidence,
    )
    from ai_software_engineer.recovery.python_mysql_records import (
        MysqlResourceIntent,
        MysqlResourceRecord,
    )
    from ai_software_engineer.recovery.verification_records import VerificationExecutionRecord
    from tests.manager.test_python_verification import capability
    from tests.recovery.test_verification_environment import _admitted

    cap = capability(tmp_path)
    plan, store, facts, requests, _ = _admitted(tmp_path, executor_capability=cap)
    request = next(r for r in requests if r.role is AgentRole.QA)
    invocation = store.get_verification_invocation(plan.plan_sha256, AgentRole.QA)
    root = tmp_path / "worktrees"
    source = root / plan.execution_task_id / "qa-attempt-01"
    source.mkdir(parents=True)
    now = datetime.now(UTC)
    intent = MysqlResourceIntent.create(
        plan_sha256=plan.plan_sha256,
        invocation_sha256=invocation.invocation_sha256,
        role="qa",
        capability=cap,
        recorded_at=now,
    )
    # Before STARTED there can be no durable resource authority.
    with pytest.raises(RecoveryRecordMissing):
        store.put_mysql_resource(
            MysqlResourceRecord.create(phase="INTENT", intent=intent, recorded_at=now)
        )
    store.put_verification_execution(
        VerificationExecutionRecord.create(
            phase="STARTED",
            plan_sha256=plan.plan_sha256,
            invocation_sha256=invocation.invocation_sha256,
            authorization_sha256=invocation.authorization_sha256,
            candidate_revision=plan.inputs.candidate_revision,
            role=AgentRole.QA,
            capability=cap,
            source_root=str(source),
            scratch_root=str(tmp_path / "scratch"),
            private_root=str(tmp_path / "private"),
            mysql_resource_id=intent.resource_id,
            recorded_at=now,
        )
    )
    start = Mock()
    monkeypatch.setattr(
        "ai_software_engineer.recovery.python_mysql_execution.IsolatedMysqlResource", start
    )
    with pytest.raises(RecoveryRejected, match="uncertain"):
        BoundPythonMysqlVerificationEvidence(
            store=store, plan=plan, facts=facts, worktree_root=root
        ).evidence_for(request, source)
    start.assert_not_called()


@pytest.mark.parametrize("cut", [4095, 4096, 65535, 65536])
def test_truncated_output_never_preserves_a_partial_credential(cut):
    secret = "0123456789abcdef" * 3
    observed = ("x" * (cut - 12) + secret)[:cut]
    assert secret[:12] in observed
    assert safe_verification_output(observed, truncated=True, secrets=(secret,)) == (
        "[REDACTED:truncated_verification_output]"
    )
    assert secret not in safe_verification_output(secret, truncated=False, secrets=(secret,))


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_trusted_docker_discovery_output_is_hard_bounded(stream):
    import sys

    with pytest.raises(ValueError, match="exceeds bound"):
        bounded_verification_command(
            (sys.executable, "-c", f"import sys; sys.{stream}.write('x'*10000)"),
            environment={"PATH": "/usr/bin:/bin"},
            limit=100,
        )


def test_fixed_command_timeout_kills_and_reaps_a_stalled_process():
    import sys

    with pytest.raises(ValueError, match="timed out"):
        bounded_verification_command(
            (sys.executable, "-c", "import time; time.sleep(10)"),
            environment={"PATH": "/usr/bin:/bin"},
            timeout=1,
        )


def test_timeout_reaps_descendants_after_group_leader_has_exited(tmp_path):
    import os
    import signal
    import sys
    import time
    from contextlib import suppress

    pid_file = tmp_path / "leader.pid"
    sentinel = tmp_path / "descendant-survived"
    script = (
        f"import os,time; open({str(pid_file)!r},'w').write(str(os.getpid())); "
        "child=os.fork(); os._exit(0) if child else None; time.sleep(2); "
        f"open({str(sentinel)!r},'w').write('survived')"
    )
    try:
        with pytest.raises(ValueError, match="timed out"):
            bounded_verification_command(
                (sys.executable, "-c", script), environment={"PATH": "/usr/bin:/bin"}, timeout=1
            )
        # Darwin can report EPERM for an already killed orphan group; observe its
        # promised late side effect rather than treating killpg(0) as liveness.
        time.sleep(1.3)
        assert not sentinel.exists()
    finally:
        if pid_file.exists():
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(int(pid_file.read_text()), signal.SIGKILL)


def test_expired_resource_reconciliation_is_exact_durable_and_never_replays_tests(
    tmp_path, monkeypatch
):
    from datetime import UTC, datetime, timedelta

    from ai_software_engineer.domain import AgentRole
    from ai_software_engineer.recovery.python_mysql_execution import (
        reconcile_expired_mysql_resources,
    )
    from ai_software_engineer.recovery.python_mysql_records import (
        MysqlResourceIntent,
        MysqlResourceRecord,
    )
    from ai_software_engineer.recovery.verification_records import VerificationExecutionRecord
    from tests.manager.test_python_verification import capability
    from tests.recovery.test_verification_environment import _admitted

    cap = capability(tmp_path)
    plan, store, _, _, _ = _admitted(tmp_path, executor_capability=cap)
    invocation = store.get_verification_invocation(plan.plan_sha256, AgentRole.QA)
    now = datetime.now(UTC)
    intent = MysqlResourceIntent.create(
        plan_sha256=plan.plan_sha256,
        invocation_sha256=invocation.invocation_sha256,
        role="qa",
        capability=cap,
        recorded_at=now,
    )
    store.put_verification_execution(
        VerificationExecutionRecord.create(
            phase="STARTED",
            plan_sha256=plan.plan_sha256,
            invocation_sha256=invocation.invocation_sha256,
            authorization_sha256=invocation.authorization_sha256,
            candidate_revision=plan.inputs.candidate_revision,
            role=AgentRole.QA,
            capability=cap,
            source_root=str(tmp_path / "source"),
            scratch_root=str(tmp_path / "scratch"),
            private_root=str(tmp_path / "private"),
            mysql_resource_id=intent.resource_id,
            recorded_at=now,
        )
    )
    store.put_mysql_resource(
        MysqlResourceRecord.create(phase="INTENT", intent=intent, recorded_at=now)
    )
    failed = store.put_mysql_resource(
        MysqlResourceRecord.create(
            phase="CLEANUP_FAILED", intent=intent, container_id="c" * 64, recorded_at=now
        )
    )
    created = store.put_mysql_resource(
        MysqlResourceRecord.create(
            phase="CREATED",
            intent=intent,
            container_id="c" * 64,
            configuration_sha256="d" * 64,
            recorded_at=now + timedelta(seconds=1),
        )
    )
    assert store.get_mysql_resource(intent.resource_id, "CLEANUP_FAILED") == failed
    recovered = []

    def cleanup(original, publish, *, clock, created):
        assert original == intent and created.container_id == "c" * 64
        recovered.append(original.resource_id)
        return Mock(
            close=lambda: publish(
                MysqlResourceRecord.create(
                    phase="CLEANED",
                    intent=original,
                    container_id="c" * 64,
                    configuration_sha256="d" * 64,
                    recorded_at=clock(),
                )
            )
        )

    prefix = "ai_software_engineer.recovery.python_mysql_execution."
    monkeypatch.setattr(prefix + "_now", lambda: now)
    monkeypatch.setattr(prefix + "IsolatedMysqlResource.for_cleanup", cleanup)
    reconcile_expired_mysql_resources(store)
    assert recovered == []
    monkeypatch.setattr(prefix + "_now", lambda: now + timedelta(seconds=1201))
    reconcile_expired_mysql_resources(store)
    reconcile_expired_mysql_resources(store)
    assert recovered == [intent.resource_id]
    assert store.get_mysql_resource(intent.resource_id, "CLEANUP_FAILED") == failed
    assert store.get_mysql_resource(intent.resource_id, "CLEANED").intent == intent
    from ai_software_engineer.recovery.store import FileRecoveryStore

    reopened = FileRecoveryStore(store._root, scope=plan.scope)
    assert reopened.get_mysql_resource(intent.resource_id, "CLEANUP_FAILED") == failed
    assert reopened.get_mysql_resource(intent.resource_id, "CREATED") == created
    for identity, configuration in (("e" * 64, "d" * 64), ("c" * 64, "e" * 64)):
        with pytest.raises(RecoveryRejected, match="cleanup differs"):
            reopened.put_mysql_resource(
                MysqlResourceRecord.create(
                    phase="CLEANUP_FAILED",
                    intent=intent,
                    container_id=identity,
                    configuration_sha256=configuration,
                    recorded_at=now + timedelta(seconds=1202),
                )
            )
    with pytest.raises(RecoveryRecordMissing):
        store.get_verification_execution(plan.plan_sha256, AgentRole.QA, completed=True)


@pytest.mark.parametrize("criteria", [("ac_01",), ("ac_01", "ac_02", "ac_extra")])
def test_missing_or_extra_criteria_are_rejected_before_capability_discovery(criteria, monkeypatch):
    from types import SimpleNamespace

    from ai_software_engineer.manager.python_verification import PytestSelection
    from ai_software_engineer.recovery.verification_entry import _python_capability

    discovery = Mock()
    monkeypatch.setattr(
        "ai_software_engineer.recovery.verification_entry.discover_python_mysql_capability",
        discovery,
    )
    source = SimpleNamespace(
        runtime=SimpleNamespace(
            task=SimpleNamespace(
                acceptance_criteria=(SimpleNamespace(id="ac_01"), SimpleNamespace(id="ac_02"))
            )
        )
    )
    with pytest.raises(RecoveryRejected, match="all and only Task criteria"):
        _python_capability(
            source,
            (PytestSelection(node_id="tests/test_sql.py::test_sql", criterion_ids=criteria),),
            Mock(),
        )
    discovery.assert_not_called()
