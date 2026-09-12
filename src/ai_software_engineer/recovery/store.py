"""Scoped append-only recovery records using no-follow directory descriptors."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TypeVar

from pydantic import TypeAdapter

from ai_software_engineer.domain.artifact import QaReportArtifact, ReviewReportArtifact
from ai_software_engineer.domain.enums import AgentRole
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.recovery.models import (
    RecoveryAuthorization,
    RecoveryConflict,
    RecoveryPlan,
    RecoveryRejected,
    RecoveryScope,
    canonical_bytes,
    digest,
)
from ai_software_engineer.recovery.records import (
    RecoveryInvocationRecord,
    RecoverySeedRecord,
    RecoveryTaskRecord,
)
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationCompletion,
    CandidateVerificationInvocation,
    CandidateVerificationPlan,
)

MAX_RECORD_BYTES = 8_000_000
_Record = TypeVar(
    "_Record",
    RecoveryPlan,
    RecoveryAuthorization,
    RecoveryScope,
    RecoveryTaskRecord,
    RecoverySeedRecord,
    RecoveryInvocationRecord,
    CandidateVerificationPlan,
    CandidateVerificationInvocation,
    CandidateVerificationCompletion,
)


class RecoveryRecordMissing(RecoveryRejected):
    """An exact plan or authorization has never been published."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _open_directory(path: Path) -> int:
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError as error:
        os.close(descriptor)
        raise RecoveryRejected("recovery directory is missing or unsafe") from error


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


class FileRecoveryStore:
    """Open existing scoped storage without initialization or target-project writes."""

    def __init__(
        self, root: str | Path, *, scope: RecoveryScope, _initialize: bool = False
    ) -> None:
        self._root = self._validate_placement(root, scope)
        self._scope = RecoveryScope.model_validate(scope.to_wire())
        descriptor = _open_directory(self._root)
        try:
            metadata = os.fstat(descriptor)
            if metadata.st_mode & 0o077:
                raise RecoveryRejected("recovery directory must be private")
            self._root_identity = _identity(metadata)
        finally:
            os.close(descriptor)
        scope_digest = digest(self._scope.to_wire())
        if _initialize:
            self._put("scope", scope_digest, self._scope, RecoveryScope)
        stored_scope = self._get("scope", scope_digest, RecoveryScope)
        if stored_scope != self._scope:
            raise RecoveryRejected("recovery root is bound to another scope")

    @classmethod
    def initialize(cls, root: str | Path, *, scope: RecoveryScope) -> FileRecoveryStore:
        """Create only the named child of an existing sidecar parent (never parents)."""
        target = cls._validate_placement(root, scope)
        parent_fd = _open_directory(target.parent)
        try:
            with suppress(FileExistsError):
                os.mkdir(target.name, 0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
            current_parent = _open_directory(target.parent)
            try:
                if _identity(os.fstat(current_parent)) != _identity(os.fstat(parent_fd)):
                    raise RecoveryRejected("recovery parent directory changed")
            finally:
                os.close(current_parent)
        except OSError as error:
            raise RecoveryRejected("cannot initialize recovery directory") from error
        finally:
            os.close(parent_fd)
        return cls(target, scope=scope, _initialize=True)

    @staticmethod
    def _validate_placement(root: str | Path, scope: RecoveryScope) -> Path:
        scope = RecoveryScope.model_validate(scope.to_wire())
        target = Path(root)
        if not target.is_absolute() or ".." in target.parts or target == Path("/"):
            raise RecoveryRejected("recovery root must be a specific absolute directory")
        project = Path(scope.repository_root)
        # Resolve only for placement comparison; all actual opens reject symlinks.
        resolved, project_resolved = target.resolve(), project.resolve()
        if resolved.is_relative_to(project_resolved) or project_resolved.is_relative_to(resolved):
            raise RecoveryRejected("recovery storage must not overlap project code")
        return target

    def put_plan(self, plan: RecoveryPlan) -> RecoveryPlan:
        plan.validate_integrity()
        self._validate_scope(plan)
        return self._put("plan", plan.plan_sha256, plan, RecoveryPlan)

    def put_verification_plan(self, plan: CandidateVerificationPlan) -> CandidateVerificationPlan:
        plan.validate_integrity()
        if plan.scope != self._scope:
            raise RecoveryRejected("verification plan scope mismatch")
        return self._put("verification-plan", plan.plan_sha256, plan, CandidateVerificationPlan)

    def get_verification_plan(self, plan_sha256: str) -> CandidateVerificationPlan:
        plan = self._get("verification-plan", plan_sha256, CandidateVerificationPlan)
        if plan.scope != self._scope or plan.plan_sha256 != plan_sha256:
            raise RecoveryRejected("verification plan identity mismatch")
        return plan

    def put_verification_authorization(
        self, record: RecoveryAuthorization
    ) -> RecoveryAuthorization:
        record.validate_integrity()
        plan = self.get_verification_plan(record.command.plan_sha256)
        if record.command.submitted_at < plan.created_at:
            raise RecoveryRejected("verification approval predates plan")
        return self._put(
            "verification-authorization", plan.plan_sha256, record, RecoveryAuthorization
        )

    def get_verification_authorization(self, plan_sha256: str) -> RecoveryAuthorization:
        plan = self.get_verification_plan(plan_sha256)
        record = self._get("verification-authorization", plan_sha256, RecoveryAuthorization)
        if (
            record.command.plan_sha256 != plan_sha256
            or record.command.submitted_at < plan.created_at
        ):
            raise RecoveryRejected("verification authorization identity mismatch")
        return record

    def get_verification_invocation(
        self, plan_sha256: str, role: AgentRole
    ) -> CandidateVerificationInvocation:
        if role not in (AgentRole.QA, AgentRole.REVIEWER):
            raise RecoveryRejected("only verifier invocation records are supported")
        record = self._get(
            f"verification-{role.value}", plan_sha256, CandidateVerificationInvocation
        )
        self._validate_verification_invocation(record)
        if record.plan_sha256 != plan_sha256 or record.request.role is not role:
            raise RecoveryRejected("verification invocation filename identity mismatch")
        return record

    def put_verification_invocation(
        self, record: CandidateVerificationInvocation
    ) -> CandidateVerificationInvocation:
        self._validate_verification_invocation(record)
        return self._put(
            f"verification-{record.request.role.value}",
            record.plan_sha256,
            record,
            CandidateVerificationInvocation,
        )

    def _validate_verification_invocation(self, record: CandidateVerificationInvocation) -> None:
        record.validate_integrity()
        plan = self.get_verification_plan(record.plan_sha256)
        authorization = self.get_verification_authorization(record.plan_sha256)
        definition = next(d for d in plan.definitions if d.role is record.request.role)
        if (
            not authorization.decision.approved
            or record.authorization_sha256 != authorization.authorization_sha256
            or record.admitted_at < authorization.decision.decided_at
            or record.request.task_id != plan.inputs.task_id
            or record.request.source_revision != plan.inputs.candidate_revision
            or record.request.permissions != definition.permissions
            or record.request.timeout_seconds != definition.timeout_seconds
            or record.request.run_id in plan.inputs.prior_run_ids
            or record.request.continuation_checkpoint_id is not None
        ):
            raise RecoveryRejected("verification invocation is outside the approved plan")
        prefix = (plan.inputs.plan_id, plan.inputs.implementation_id)
        if record.request.role is AgentRole.QA:
            if (
                record.request.input_artifact_ids != prefix
                or record.request.expected_parent_artifact_ids != prefix[1:]
            ):
                raise RecoveryRejected("persisted QA invocation has invalid input lineage")
        else:
            qa = self.get_verification_invocation(plan.plan_sha256, AgentRole.QA)
            if (
                len(record.request.input_artifact_ids) != 3
                or record.request.input_artifact_ids[:2] != prefix
                or record.request.expected_parent_artifact_ids
                != record.request.input_artifact_ids[2:]
                or record.request.run_id == qa.request.run_id
                or record.admitted_at < qa.admitted_at
            ):
                raise RecoveryRejected("persisted Reviewer invocation has invalid input lineage")

    def put_verification_completion(
        self, record: CandidateVerificationCompletion
    ) -> CandidateVerificationCompletion:
        self._validate_verification_completion(record)
        return self._put(
            "verification-completion", record.plan_sha256, record, CandidateVerificationCompletion
        )

    def get_verification_completion(self, plan_sha256: str) -> CandidateVerificationCompletion:
        record = self._get("verification-completion", plan_sha256, CandidateVerificationCompletion)
        if record.plan_sha256 != plan_sha256:
            raise RecoveryRejected("verification completion identity mismatch")
        self._validate_verification_completion(record)
        return record

    def _validate_verification_completion(self, record: CandidateVerificationCompletion) -> None:
        record.validate_integrity()
        plan = self.get_verification_plan(record.plan_sha256)
        authorization = self.get_verification_authorization(record.plan_sha256)
        if record.authorization_sha256 != authorization.authorization_sha256:
            raise RecoveryRejected("completion authorization mismatch")
        reports: list[tuple[AgentRole, QaReportArtifact | ReviewReportArtifact, str | None]] = [
            (AgentRole.QA, record.qa, record.qa_invocation_sha256)
        ]
        if record.review is not None:
            reports.append((AgentRole.REVIEWER, record.review, record.reviewer_invocation_sha256))
        for role, report, invocation_sha in reports:
            invocation = self.get_verification_invocation(plan.plan_sha256, role)
            request = invocation.request
            definition = next(d for d in plan.definitions if d.role is role)
            if (
                invocation.invocation_sha256 != invocation_sha
                or record.completed_at < invocation.admitted_at
                or report.task_id != plan.inputs.task_id
                or report.source_revision != plan.inputs.candidate_revision
                or report.producer.run_id != request.run_id
                or report.producer.agent_id != definition.id
                or report.producer.role is not role
                or report.context_manifest_id != request.context_manifest_id
                or report.parent_artifact_ids != request.expected_parent_artifact_ids
                or report.supersedes is not None
            ):
                raise RecoveryRejected("completion report differs from admitted verification")
        if record.review is not None and record.review.parent_artifact_ids != (
            record.qa.artifact_id,
        ):
            raise RecoveryRejected("completion Review does not reference its QA")

    def get_plan(self, plan_sha256: str) -> RecoveryPlan:
        plan = self._get("plan", plan_sha256, RecoveryPlan)
        self._validate_scope(plan)
        if plan.plan_sha256 != plan_sha256:
            raise RecoveryRejected("recovery plan filename identity mismatch")
        return plan

    def put_authorization(self, record: RecoveryAuthorization) -> RecoveryAuthorization:
        record.validate_integrity()
        plan = self.get_plan(record.command.plan_sha256)
        if record.command.submitted_at < plan.created_at:
            raise RecoveryRejected("recovery decision predates plan")
        return self._put("authorization", plan.plan_sha256, record, RecoveryAuthorization)

    def get_authorization(self, plan_sha256: str) -> RecoveryAuthorization:
        plan = self.get_plan(plan_sha256)
        record = self._get("authorization", plan_sha256, RecoveryAuthorization)
        if (
            record.command.plan_sha256 != plan.plan_sha256
            or record.command.submitted_at < plan.created_at
        ):
            raise RecoveryRejected("recovery decision filename or time mismatch")
        return record

    def find_authorization(self, plan_sha256: str) -> RecoveryAuthorization | None:
        # A missing plan is not a missing decision; missing/corrupt lineage must fail.
        self.get_plan(plan_sha256)
        try:
            return self.get_authorization(plan_sha256)
        except RecoveryRecordMissing:
            return None

    def _validate_scope(self, plan: RecoveryPlan) -> None:
        if plan.source.scope != self._scope:
            raise RecoveryRejected("recovery belongs to another team, project or delivery")
        if self._get("scope", digest(self._scope.to_wire()), RecoveryScope) != self._scope:
            raise RecoveryRejected("recovery scope manifest changed")

    def put_task_record(self, record: RecoveryTaskRecord) -> RecoveryTaskRecord:
        plan = self.get_plan(record.recovery_plan_sha256)
        record.validate_binding(plan, self.get_authorization(plan.plan_sha256))
        return self._put("task", plan.plan_sha256, record, RecoveryTaskRecord)

    def get_task_record(self, plan_sha256: str) -> RecoveryTaskRecord:
        plan = self.get_plan(plan_sha256)
        record = self._get("task", plan_sha256, RecoveryTaskRecord)
        record.validate_binding(plan, self.get_authorization(plan_sha256))
        return record

    def put_seed(self, record: RecoverySeedRecord) -> RecoverySeedRecord:
        self._validate_seed(record)
        return self._put("seed", record.recovery_plan_sha256, record, RecoverySeedRecord)

    @contextmanager
    def execution_lock(self) -> Iterator[None]:
        """One executor for this recovery scope; never wait while another runs."""
        with self._directory() as directory:
            fd = os.open(
                "execution.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory
            )
            try:
                metadata = os.fstat(fd)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                    raise RecoveryRejected("unsafe recovery execution lock")
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise RecoveryRejected("recovery already has an executor") from error
                yield
            finally:
                os.close(fd)

    def get_seed(self, plan_sha256: str) -> RecoverySeedRecord:
        record = self._get("seed", plan_sha256, RecoverySeedRecord)
        if record.recovery_plan_sha256 != plan_sha256:
            raise RecoveryRejected("seed filename identity mismatch")
        self._validate_seed(record)
        return record

    def _validate_seed(self, record: RecoverySeedRecord) -> None:
        record.validate_integrity()
        plan = self.get_plan(record.recovery_plan_sha256)
        task = self.get_task_record(plan.plan_sha256).task
        target = record.capture.to_capture().worktree
        if target.task_id != task.id or target.head_revision != task.base_ref:
            raise RecoveryRejected("seed target differs from authorized Task")
        if target.role.value != "coder" or target.attempt != 1:
            raise RecoveryRejected("seed is not the first recovery Coder")
        if plan.input_mode == "coder_reapply" and (record.capture.patch or record.capture.files):
            raise RecoveryRejected("Coder reapplication initial capture must be clean")

    def get_invocation(self, plan_sha256: str) -> RecoveryInvocationRecord:
        record = self._get("invocation", plan_sha256, RecoveryInvocationRecord)
        if (
            record.recovery_plan_sha256 != plan_sha256
            or record.seed_record_sha256 != self.get_seed(plan_sha256).record_sha256
        ):
            raise RecoveryRejected("invocation seed lineage mismatch")
        return record

    def put_invocation(self, record: RecoveryInvocationRecord) -> RecoveryInvocationRecord:
        if record.seed_record_sha256 != self.get_seed(record.recovery_plan_sha256).record_sha256:
            raise RecoveryRejected("invocation seed mismatch")
        return self._put(
            "invocation", record.recovery_plan_sha256, record, RecoveryInvocationRecord
        )

    @contextmanager
    def _directory(self) -> Iterator[int]:
        descriptor = _open_directory(self._root)
        try:
            self._check_directory(descriptor)
            yield descriptor
            self._check_directory(descriptor)
        finally:
            os.close(descriptor)

    def _check_directory(self, descriptor: int) -> None:
        current = _open_directory(self._root)
        try:
            if os.fstat(descriptor).st_mode & 0o077 or os.fstat(current).st_mode & 0o077:
                raise RecoveryRejected("recovery directory is no longer private")
            if (
                _identity(os.fstat(descriptor)) != self._root_identity
                or _identity(os.fstat(current)) != self._root_identity
            ):
                raise RecoveryRejected("recovery root identity changed")
        finally:
            os.close(current)

    @staticmethod
    def _name(category: str, identity: str) -> str:
        try:
            TypeAdapter(StageSha256).validate_python(identity)
        except ValueError as error:
            raise RecoveryRejected("invalid recovery record identity") from error
        if category not in (
            "scope",
            "plan",
            "authorization",
            "task",
            "seed",
            "invocation",
            "verification-plan",
            "verification-authorization",
            "verification-qa",
            "verification-reviewer",
            "verification-completion",
        ):
            raise RecoveryRejected("invalid recovery record category")
        if category == "scope":
            return "scope.json"
        return f"{category}-{identity}.json"

    def _get(self, category: str, identity: str, model: type[_Record]) -> _Record:
        name = self._name(category, identity)
        with self._directory() as directory:
            try:
                descriptor = os.open(
                    name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
                )
            except FileNotFoundError as error:
                raise RecoveryRecordMissing("recovery record is missing") from error
            except OSError as error:
                raise RecoveryRejected("recovery record path is unsafe") from error
            try:
                before = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_mode & 0o077
                    or before.st_size > MAX_RECORD_BYTES
                ):
                    raise RecoveryRejected("recovery record must be a private bounded regular file")
                with os.fdopen(descriptor, "rb", closefd=False) as stream:
                    content = stream.read(MAX_RECORD_BYTES + 1)
                after = os.fstat(descriptor)
                named = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (
                    len(content) > MAX_RECORD_BYTES
                    or _identity(named) != _identity(before)
                    or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                ):
                    raise RecoveryRejected("recovery record changed during read")
                envelope: object = json.loads(content, object_pairs_hook=_unique_object)
                if (
                    not isinstance(envelope, dict)
                    or set(envelope) != {"record", "sha256"}
                    or envelope["sha256"] != digest(envelope["record"])
                ):
                    raise RecoveryRejected("recovery envelope integrity mismatch")
                record = model.model_validate(envelope["record"])
                if not isinstance(record, RecoveryScope):
                    record.validate_integrity()
                return record
            except (OSError, ValueError) as error:
                raise RecoveryRejected("cannot decode trusted recovery record") from error
            finally:
                os.close(descriptor)

    def _put(self, category: str, identity: str, record: _Record, model: type[_Record]) -> _Record:
        name = self._name(category, identity)
        wire = record.to_wire()
        try:
            existing = self._get(category, identity, model)
        except RecoveryRecordMissing:
            pass
        else:
            if existing.to_wire() != wire:
                raise RecoveryConflict("recovery record already has different content")
            return existing
        payload = canonical_bytes({"record": wire, "sha256": digest(wire)})
        if len(payload) > MAX_RECORD_BYTES:
            raise RecoveryRejected("recovery record exceeds byte limit")
        temporary = ".pending-" + uuid.uuid4().hex
        with self._directory() as directory:
            try:
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory,
                )
                try:
                    remaining = memoryview(payload)
                    while remaining:
                        written = os.write(descriptor, remaining)
                        if written <= 0:
                            raise OSError("short recovery record write")
                        remaining = remaining[written:]
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                self._check_directory(directory)
                with suppress(FileExistsError):
                    os.link(
                        temporary,
                        name,
                        src_dir_fd=directory,
                        dst_dir_fd=directory,
                        follow_symlinks=False,
                    )
                os.fsync(directory)
            except OSError as error:
                raise RecoveryRejected("cannot publish recovery record") from error
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=directory)
        existing = self._get(category, identity, model)
        if existing.to_wire() != wire:
            raise RecoveryConflict("recovery record already has different content")
        return existing
