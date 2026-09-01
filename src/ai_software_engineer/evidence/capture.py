"""Application services that capture redacted command, diff, test, and Agent evidence."""

import hashlib
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from ai_software_engineer.agents import AgentAdapter, AgentRequest, AgentResult, AgentRunStatus
from ai_software_engineer.evidence.models import (
    AgentUsageEvidencePayload,
    AgentUsageEvidenceRecord,
    CommandEvidencePayload,
    CommandEvidenceRecord,
    CommandOutcome,
    DiffEvidencePayload,
    DiffEvidenceRecord,
    EvidenceKind,
    EvidenceRecord,
    OperationId,
    RedactionFact,
    RunEvidenceIdentity,
    RunEvidenceManifest,
    RunOutcome,
    TestEvidencePayload,
    TestEvidenceRecord,
    TestOutcome,
    seal_evidence_record,
    seal_run_manifest,
)
from ai_software_engineer.evidence.store import FileEvidenceStore, RunEvidenceNotFound
from ai_software_engineer.execution import (
    CommandExecutionError,
    CommandExecutor,
    CommandResult,
    CommandTimedOut,
)
from ai_software_engineer.git import CommandPolicyViolation
from ai_software_engineer.redaction import RedactedText, redact_text

Clock = Callable[[], datetime]


class EvidenceCaptureError(RuntimeError):
    """Raised when an operation conflicts with already persisted evidence."""


class RunEvidenceSession:
    """Capture exactly-once evidence facts for one isolated Agent Run."""

    def __init__(
        self,
        store: FileEvidenceStore,
        identity: RunEvidenceIdentity,
        *,
        workspace_root: str | Path,
        clock: Clock | None = None,
        max_patch_bytes: int = 1_000_000,
    ) -> None:
        if type(max_patch_bytes) is not int or max_patch_bytes < 1:
            raise ValueError("max_patch_bytes must be a positive integer")
        self._store = store
        self._identity = identity
        self._workspace_root = str(Path(workspace_root).expanduser().resolve(strict=False))
        self._clock = clock or _utc_now
        self._started_at = self._clock()
        _require_aware(self._started_at, "run evidence start")
        self._max_patch_bytes = max_patch_bytes

    @property
    def identity(self) -> RunEvidenceIdentity:
        return self._identity

    def capture_command(
        self,
        operation_id: OperationId,
        executor: CommandExecutor,
        arguments: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
        description: str = "policy-bound command execution",
    ) -> CommandEvidenceRecord:
        evidence_id = self._evidence_id(EvidenceKind.COMMAND, operation_id)
        safe_arguments, argument_redactions = _redact_many(arguments)
        existing = self._existing(evidence_id, EvidenceKind.COMMAND, operation_id)
        if existing is not None:
            if not isinstance(existing, CommandEvidenceRecord):
                raise EvidenceCaptureError("existing command evidence has the wrong type")
            if existing.payload.argv != safe_arguments:
                raise EvidenceCaptureError("command replay changed argv")
            return existing
        captured_at = self._captured_at()
        try:
            result = executor.run(arguments, timeout_seconds=timeout_seconds)
        except CommandTimedOut as error:
            payload, redactions = self._failed_command_payload(
                CommandOutcome.TIMED_OUT,
                safe_arguments,
                error.duration_ms,
                "TIMEOUT",
                str(error),
                argument_redactions,
            )
            record = self._command_record(
                evidence_id, operation_id, description, captured_at, payload, redactions
            )
            self._store.put(record)
            raise
        except CommandPolicyViolation as error:
            payload, redactions = self._failed_command_payload(
                CommandOutcome.REJECTED,
                safe_arguments,
                0,
                "POLICY_REJECTED",
                str(error),
                argument_redactions,
            )
            record = self._command_record(
                evidence_id, operation_id, description, captured_at, payload, redactions
            )
            self._store.put(record)
            raise
        except CommandExecutionError as error:
            payload, redactions = self._failed_command_payload(
                CommandOutcome.FAILED_TO_START,
                safe_arguments,
                0,
                "EXECUTION_ERROR",
                str(error),
                argument_redactions,
            )
            record = self._command_record(
                evidence_id, operation_id, description, captured_at, payload, redactions
            )
            self._store.put(record)
            raise
        if result.argv != arguments:
            raise EvidenceCaptureError("command executor returned argv different from request")
        try:
            result_cwd = str(Path(result.cwd).expanduser().resolve(strict=False))
        except (OSError, RuntimeError) as error:
            raise EvidenceCaptureError("command executor returned an invalid cwd") from error
        if result_cwd != self._workspace_root:
            raise EvidenceCaptureError("command executor returned cwd outside evidence workspace")
        payload, redactions = self._completed_command_payload(
            result, safe_arguments, argument_redactions
        )
        record = self._command_record(
            evidence_id, operation_id, description, captured_at, payload, redactions
        )
        return cast(CommandEvidenceRecord, self._store.put(record))

    def record_diff(
        self,
        operation_id: OperationId,
        *,
        base_revision: str,
        candidate_revision: str,
        changed_paths: tuple[str, ...],
        patch: str,
        description: str = "candidate revision diff",
    ) -> DiffEvidenceRecord:
        evidence_id = self._evidence_id(EvidenceKind.DIFF, operation_id)
        existing = self._existing(evidence_id, EvidenceKind.DIFF, operation_id)
        safe_patch = redact_text(patch)
        bounded_patch, truncated = _truncate_utf8(safe_patch.text, self._max_patch_bytes)
        payload = DiffEvidencePayload(
            base_revision=base_revision,
            candidate_revision=candidate_revision,
            changed_paths=changed_paths,
            patch=bounded_patch,
            patch_truncated=truncated,
        )
        if existing is not None:
            if not isinstance(existing, DiffEvidenceRecord) or existing.payload != payload:
                raise EvidenceCaptureError("diff replay changed persisted content")
            return existing
        record = DiffEvidenceRecord(
            evidence_id=evidence_id,
            operation_id=operation_id,
            identity=self._identity,
            description=description,
            captured_at=self._captured_at(),
            redactions=_redaction_facts(safe_patch),
            payload=payload,
            record_sha256="0" * 64,
        )
        sealed = seal_evidence_record(record)
        return cast(DiffEvidenceRecord, self._store.put(sealed))

    def record_test(
        self,
        operation_id: OperationId,
        *,
        framework: str,
        suite: str,
        outcome: TestOutcome,
        command_evidence_id: str,
        required: bool = True,
        description: str = "test execution result",
    ) -> TestEvidenceRecord:
        command = self._store.get(command_evidence_id)
        if not isinstance(command, CommandEvidenceRecord) or command.identity != self._identity:
            raise EvidenceCaptureError("test evidence must reference this run's command evidence")
        evidence_id = self._evidence_id(EvidenceKind.TEST, operation_id)
        payload = TestEvidencePayload(
            framework=framework,
            suite=suite,
            outcome=outcome,
            command_evidence_id=command.evidence_id,
            required=required,
        )
        existing = self._existing(evidence_id, EvidenceKind.TEST, operation_id)
        if existing is not None:
            if not isinstance(existing, TestEvidenceRecord) or existing.payload != payload:
                raise EvidenceCaptureError("test replay changed persisted content")
            return existing
        record = TestEvidenceRecord(
            evidence_id=evidence_id,
            operation_id=operation_id,
            identity=self._identity,
            description=description,
            captured_at=self._captured_at(),
            payload=payload,
            record_sha256="0" * 64,
        )
        sealed = seal_evidence_record(record)
        return cast(TestEvidenceRecord, self._store.put(sealed))

    def record_agent_result(
        self,
        operation_id: OperationId,
        result: AgentResult,
        *,
        provider: str,
        model: str,
        description: str = "Agent provider usage and terminal outcome",
    ) -> AgentUsageEvidenceRecord:
        if (
            result.run_id != self._identity.run_id
            or result.task_id != self._identity.task_id
            or result.role is not self._identity.role
            or result.attempt != self._identity.attempt
            or result.context_manifest_id != self._identity.context_manifest_id
        ):
            raise EvidenceCaptureError("AgentResult does not match evidence run identity")
        safe_error = redact_text(result.error.message if result.error is not None else "")
        payload = AgentUsageEvidencePayload(
            provider=provider,
            model=model,
            status=result.status,
            duration_ms=result.duration_ms,
            usage=result.usage,
            error_code=result.error.code if result.error is not None else None,
            error_message=safe_error.text if result.error is not None else None,
            transient=result.error.transient if result.error is not None else None,
        )
        evidence_id = self._evidence_id(EvidenceKind.AGENT_USAGE, operation_id)
        existing = self._existing(evidence_id, EvidenceKind.AGENT_USAGE, operation_id)
        if existing is not None:
            if not isinstance(existing, AgentUsageEvidenceRecord) or existing.payload != payload:
                raise EvidenceCaptureError("Agent result replay changed persisted evidence")
            return existing
        record = AgentUsageEvidenceRecord(
            evidence_id=evidence_id,
            operation_id=operation_id,
            identity=self._identity,
            description=description,
            captured_at=self._captured_at(),
            redactions=_redaction_facts(safe_error),
            payload=payload,
            record_sha256="0" * 64,
        )
        sealed = seal_evidence_record(record)
        return cast(AgentUsageEvidenceRecord, self._store.put(sealed))

    def seal(self, outcome: RunOutcome) -> RunEvidenceManifest:
        try:
            existing = self._store.get_run(self._identity.run_id)
        except RunEvidenceNotFound:
            existing = None
        if existing is not None:
            if existing.identity != self._identity or existing.outcome is not outcome:
                raise EvidenceCaptureError("sealed run replay changed identity or outcome")
            return existing
        records = self._store.list_for_run(self._identity.run_id)
        if not records:
            raise EvidenceCaptureError("cannot seal a run without evidence")
        manifest = RunEvidenceManifest(
            identity=self._identity,
            outcome=outcome,
            evidence_ids=tuple(record.evidence_id for record in records),
            started_at=min(self._started_at, records[0].captured_at),
            completed_at=self._captured_at(),
            manifest_sha256="0" * 64,
        )
        return self._store.seal_run(seal_run_manifest(manifest))

    def _existing(
        self, evidence_id: str, kind: EvidenceKind, operation_id: OperationId
    ) -> EvidenceRecord | None:
        existing = self._store.find(evidence_id)
        if existing is not None and (
            existing.identity != self._identity
            or existing.kind is not kind
            or existing.operation_id != operation_id
        ):
            raise EvidenceCaptureError("evidence ID is bound to another operation")
        return existing

    def _command_record(
        self,
        evidence_id: str,
        operation_id: OperationId,
        description: str,
        captured_at: datetime,
        payload: CommandEvidencePayload,
        redactions: tuple[RedactionFact, ...],
    ) -> CommandEvidenceRecord:
        record = CommandEvidenceRecord(
            evidence_id=evidence_id,
            operation_id=operation_id,
            identity=self._identity,
            description=description,
            captured_at=captured_at,
            redactions=redactions,
            payload=payload,
            record_sha256="0" * 64,
        )
        return seal_evidence_record(record)

    def _completed_command_payload(
        self,
        result: CommandResult,
        arguments: tuple[str, ...],
        inherited: tuple[RedactionFact, ...],
    ) -> tuple[CommandEvidencePayload, tuple[RedactionFact, ...]]:
        safe_stdout = redact_text(result.stdout)
        safe_stderr = redact_text(result.stderr)
        safe_cwd = redact_text(result.cwd)
        redactions = _merge_redactions(
            inherited,
            _redaction_facts(safe_stdout),
            _redaction_facts(safe_stderr),
            _redaction_facts(safe_cwd),
        )
        return (
            CommandEvidencePayload(
                outcome=CommandOutcome.COMPLETED,
                # The requested argv is the replay identity.  A provider or
                # executor must not be able to rewrite the command evidence.
                argv=arguments,
                cwd=safe_cwd.text,
                returncode=result.returncode,
                stdout=safe_stdout.text,
                stderr=safe_stderr.text,
                duration_ms=result.duration_ms,
                stdout_truncated=result.stdout_truncated,
                stderr_truncated=result.stderr_truncated,
            ),
            redactions,
        )

    def _failed_command_payload(
        self,
        outcome: CommandOutcome,
        arguments: tuple[str, ...],
        duration_ms: int,
        error_code: str,
        error_message: str,
        inherited: tuple[RedactionFact, ...],
    ) -> tuple[CommandEvidencePayload, tuple[RedactionFact, ...]]:
        safe_error = redact_text(error_message)
        safe_cwd = redact_text(self._workspace_root)
        return (
            CommandEvidencePayload(
                outcome=outcome,
                argv=arguments,
                cwd=safe_cwd.text,
                duration_ms=duration_ms,
                error_code=error_code,
                error_message=safe_error.text,
            ),
            _merge_redactions(inherited, _redaction_facts(safe_error), _redaction_facts(safe_cwd)),
        )

    def _evidence_id(self, kind: EvidenceKind, operation_id: OperationId) -> str:
        seed = f"{self._identity.run_id}\0{kind.value}\0{operation_id}"
        return f"ev_{hashlib.sha256(seed.encode()).hexdigest()[:32]}"

    def _captured_at(self) -> datetime:
        value = self._clock()
        _require_aware(value, "evidence capture time")
        return value


class EvidenceCapturingAgentAdapter:
    """Persist Agent outcome/usage and seal the run before returning its result."""

    def __init__(
        self,
        delegate: AgentAdapter,
        session: RunEvidenceSession,
        *,
        provider: str,
        model: str,
    ) -> None:
        self._delegate = delegate
        self._session = session
        self._provider = provider
        self._model = model

    def run(self, request: AgentRequest) -> AgentResult:
        if request.run_id != self._session.identity.run_id:
            raise EvidenceCaptureError("AgentRequest does not match evidence session")
        result = self._delegate.run(request)
        self._session.record_agent_result(
            "agent.result", result, provider=self._provider, model=self._model
        )
        outcome = {
            AgentRunStatus.SUCCEEDED: RunOutcome.SUCCEEDED,
            AgentRunStatus.FAILED: RunOutcome.FAILED,
            AgentRunStatus.TIMED_OUT: RunOutcome.TIMED_OUT,
        }[result.status]
        self._session.seal(outcome)
        return result


def _redact_many(values: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[RedactionFact, ...]]:
    results = tuple(redact_text(value) for value in values)
    return tuple(result.text for result in results), _merge_redactions(
        *(_redaction_facts(result) for result in results)
    )


def _redaction_facts(result: RedactedText) -> tuple[RedactionFact, ...]:
    return tuple(RedactionFact(kind=item.kind, count=item.count) for item in result.occurrences)


def _merge_redactions(*groups: tuple[RedactionFact, ...]) -> tuple[RedactionFact, ...]:
    totals: Counter[str] = Counter()
    for group in groups:
        totals.update({item.kind: item.count for item in group})
    return tuple(RedactionFact(kind=kind, count=totals[kind]) for kind in sorted(totals))


def _truncate_utf8(content: str, max_bytes: int) -> tuple[str, bool]:
    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return content, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EvidenceCaptureError(f"{label} must be timezone-aware")


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "EvidenceCaptureError",
    "EvidenceCapturingAgentAdapter",
    "RunEvidenceSession",
]
