"""Shared controlled Python/MySQL command execution, without Task state authority."""

from __future__ import annotations

import json
import os
import shlex
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import Field, StrictInt

from ai_software_engineer.agents.execution import ExecutionGuard
from ai_software_engineer.domain import AgentPermissions, AgentRole, NetworkAccess
from ai_software_engineer.domain.artifact import Sha256
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.execution import (
    CommandExecutionError,
    CommandResult,
    CommandTimedOut,
    SubprocessCommandExecutor,
)
from ai_software_engineer.manager.python_mysql_proxy import MysqlUnixProxy
from ai_software_engineer.manager.python_mysql_resources import (
    IsolatedMysqlResource,
    MysqlResourceUnavailable,
)
from ai_software_engineer.manager.python_verification import (
    PythonMysqlSandboxCapability,
    python_mysql_sandbox_command,
    python_mysql_sandbox_environment,
)
from ai_software_engineer.recovery.python_mysql_records import (
    MysqlResourceIntent,
    MysqlResourceRecord,
)
from ai_software_engineer.recovery.store import RecoveryRecordMissing
from ai_software_engineer.recovery.verification_records import VerificationExecutionRecord
from ai_software_engineer.redaction import redact_text


class PythonMysqlExecutionIdentity(DomainModel):
    plan_sha256: Sha256
    invocation_sha256: Sha256
    authorization_sha256: Sha256
    candidate_revision: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
    role: Literal[AgentRole.QA, AgentRole.REVIEWER]
    timeout_seconds: Annotated[StrictInt, Field(ge=1)]


class MysqlResourceJournal(Protocol):
    def list_mysql_resource_intents(self) -> tuple[MysqlResourceRecord, ...]: ...

    def get_mysql_resource(
        self, identity: str, phase: Literal["INTENT", "CREATED", "CLEANED", "CLEANUP_FAILED"], /
    ) -> MysqlResourceRecord: ...

    def put_mysql_resource(self, record: MysqlResourceRecord) -> MysqlResourceRecord: ...


class PythonMysqlExecutionJournal(MysqlResourceJournal, Protocol):
    def put_verification_execution(
        self, record: VerificationExecutionRecord
    ) -> VerificationExecutionRecord: ...


def safe_verification_output(value: str, *, truncated: bool, secrets: tuple[str, ...]) -> str:
    if truncated:
        return "[REDACTED:truncated_verification_output]"
    for secret in secrets:
        value = value.replace(secret, "[REDACTED:verification_credential]")
    return redact_text(value).text


def reconcile_python_mysql_resources(
    records: MysqlResourceJournal,
    *,
    clock: Callable[[], datetime],
    resource_factory: type[IsolatedMysqlResource] = IsolatedMysqlResource,
) -> None:
    """Only exact expired owned resources; never replay a role or tests."""
    for original in records.list_mysql_resource_intents():
        intent = original.intent
        try:
            records.get_mysql_resource(intent.resource_id, "CLEANED")
        except RecoveryRecordMissing:
            pass
        else:
            continue
        if intent.expires_at > clock():
            continue

        def publish(record: MysqlResourceRecord) -> MysqlResourceRecord:
            try:
                return records.get_mysql_resource(record.intent.resource_id, record.phase)
            except RecoveryRecordMissing:
                return records.put_mysql_resource(record)

        try:
            created = records.get_mysql_resource(intent.resource_id, "CREATED")
        except RecoveryRecordMissing:
            created = None
        resource_factory.for_cleanup(intent, publish, clock=clock, created=created).close()


def execute_python_mysql_verification(
    *,
    identity: PythonMysqlExecutionIdentity,
    cap: PythonMysqlSandboxCapability,
    records: PythonMysqlExecutionJournal,
    source: Path,
    guard: ExecutionGuard | None,
    clock: Callable[[], datetime],
    validate_facts: Callable[[], None],
    require_clean_candidate: Callable[[Path, str], None],
    resource_factory: type[IsolatedMysqlResource] = IsolatedMysqlResource,
    proxy_factory: type[MysqlUnixProxy] = MysqlUnixProxy,
    executor_factory: type[SubprocessCommandExecutor] = SubprocessCommandExecutor,
) -> VerificationExecutionRecord:
    """Each caller provides a genuine admitted identity and immutable journal.

    No Task transitions, recovery budget, model verdict or generic shell authority
    are available to this executor. STARTED is durable before resource creation.
    """
    validate_facts()
    require_clean_candidate(source, identity.candidate_revision)
    with (
        tempfile.TemporaryDirectory(prefix="ase-pytest-scratch-") as temp,
        tempfile.TemporaryDirectory(prefix="ase-mysql-private-") as protected,
    ):
        scratch, private = Path(temp).resolve(), Path(protected).resolve()
        intent = MysqlResourceIntent.create(
            plan_sha256=identity.plan_sha256,
            invocation_sha256=identity.invocation_sha256,
            role=identity.role.value,
            capability=cap,
            recorded_at=clock(),
        )
        started = records.put_verification_execution(
            VerificationExecutionRecord.create(
                phase="STARTED",
                plan_sha256=identity.plan_sha256,
                invocation_sha256=identity.invocation_sha256,
                authorization_sha256=identity.authorization_sha256,
                candidate_revision=identity.candidate_revision,
                role=identity.role,
                capability=cap,
                source_root=str(source),
                scratch_root=str(scratch),
                private_root=str(private),
                mysql_resource_id=intent.resource_id,
                recorded_at=clock(),
            )
        )
        resource = resource_factory(intent, records.put_mysql_resource, clock=clock)
        proxy = None
        results: tuple[CommandResult, ...] = ()
        failure = None

        def check_owner() -> None:
            if guard is not None:
                guard.check()

        try:
            resource.start(check_owner)
            proxy = proxy_factory(resource, private / "mysql.sock")
            resource.verify_principal(private / "mysql.sock")
            config = private / "connection.json"
            descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                json.dump(
                    {
                        "socket": str(private / "mysql.sock"),
                        "user": "ase_verify",
                        "password": resource.password,
                        "database": "ase_verify_test",
                        "node_ids": [s.node_id for s in cap.selections],
                        "denied_paths": list(cap.denied_relative_paths),
                    },
                    stream,
                )
            private.chmod(0o500)
            argv = python_mysql_sandbox_command(cap, source, scratch, private)
            environment = python_mysql_sandbox_environment()
            executor = executor_factory(
                source,
                AgentPermissions(
                    read_paths=(),
                    write_paths=(),
                    network=NetworkAccess.NONE,
                    commands=(shlex.join(argv),),
                ),
                environment=environment,
                environment_allowlist=tuple(environment),
                default_timeout_seconds=min(900, max(1, identity.timeout_seconds // 2)),
                max_output_bytes=4096,
                execution_guard=guard,
            )
            result = executor.run(argv)

            results = (
                result.model_copy(
                    update={
                        "stdout": safe_verification_output(
                            result.stdout,
                            truncated=result.stdout_truncated,
                            secrets=resource.secrets,
                        ),
                        "stderr": safe_verification_output(
                            result.stderr,
                            truncated=result.stderr_truncated,
                            secrets=resource.secrets,
                        ),
                    }
                ),
            )
        except CommandTimedOut:
            failure = "COMMAND_TIMEOUT"
        except (CommandExecutionError, MysqlResourceUnavailable, OSError, ValueError):
            failure = "COMMAND_START_FAILED"
        finally:
            private.chmod(0o700)
            try:
                if proxy is not None:
                    try:
                        proxy.close()
                    except RuntimeError:
                        failure = "COMMAND_START_FAILED"
            finally:
                try:
                    resource.close()
                except MysqlResourceUnavailable:
                    failure = "COMMAND_START_FAILED"
        require_clean_candidate(source, identity.candidate_revision)
        validate_facts()
        return records.put_verification_execution(
            VerificationExecutionRecord.create(
                **{
                    k: v
                    for k, v in started.to_wire().items()
                    if k not in {"phase", "recorded_at", "record_sha256", "results", "failure_code"}
                },
                phase="BLOCKED" if failure else "COMPLETED",
                failure_code=failure,
                results=results,
                recorded_at=clock(),
            )
        )
