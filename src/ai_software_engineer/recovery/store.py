"""Scoped append-only recovery records using no-follow directory descriptors."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Literal, TypeVar, cast

from pydantic import TypeAdapter

from ai_software_engineer.artifacts import artifact_digest
from ai_software_engineer.domain.artifact import QaReportArtifact, ReviewReportArtifact
from ai_software_engineer.domain.enums import (
    AgentRole,
    QaCriterionStatus,
    QaReportStatus,
    QaTestStatus,
)
from ai_software_engineer.domain.prerequisite_repair import PrerequisiteRepairPlan
from ai_software_engineer.domain.project_delivery import StageSha256
from ai_software_engineer.manager.verification_coordination import (
    ManagerVerificationAdvice,
    VerificationFailureReference,
)
from ai_software_engineer.manager.verification_environment import (
    VerificationEnvironmentIncident,
    swift_sandbox_command,
)
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
from ai_software_engineer.recovery.restart_records import PreExecutionRestartPlan
from ai_software_engineer.recovery.verification_records import (
    CandidateExecutorPrerequisite,
    CandidateRemediationEvidence,
    CandidateVerificationCompletion,
    CandidateVerificationDisposition,
    CandidateVerificationInvocation,
    CandidateVerificationPlan,
    VerificationExecutionRecord,
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
    VerificationEnvironmentIncident,
    VerificationExecutionRecord,
    PrerequisiteRepairPlan,
    ManagerVerificationAdvice,
    CandidateExecutorPrerequisite,
    PreExecutionRestartPlan,
)


class RecoveryRecordMissing(RecoveryRejected):
    """An exact plan or authorization has never been published."""


@dataclass
class _ReadGraph:
    owner: FileRecoveryStore
    values: dict[tuple[object, ...], object] = field(default_factory=dict)
    active: set[tuple[object, ...]] = field(default_factory=set)


_READ_GRAPH: ContextVar[_ReadGraph | None] = ContextVar("verification_read_graph", default=None)


def _validated_read[**P, R](method: Callable[P, R]) -> Callable[P, R]:
    """Memoize fully validated nodes only within one synchronous public read.

    Never retain trust across calls/threads or cache failed/in-progress validation. This
    bounds repeated diamond traversal while every new read detects changed durable bytes.
    """

    @wraps(method)
    def read(*args: P.args, **kwargs: P.kwargs) -> R:
        owner = cast(FileRecoveryStore, args[0])
        graph = _READ_GRAPH.get()
        token = None
        if graph is None or graph.owner is not owner:
            graph = _ReadGraph(owner)
            token = _READ_GRAPH.set(graph)
        key = (method.__name__, *args[1:], *sorted(kwargs.items()))
        try:
            if key in graph.active:
                raise RecoveryRejected("cyclic verification record references")
            if key in graph.values:
                return cast(R, graph.values[key])
            if len(graph.active) >= 128 or len(graph.values) >= 4096:
                raise RecoveryRejected("verification read graph exceeds the bound")
            graph.active.add(key)
            try:
                result = method(*args, **kwargs)
                graph.values[key] = result
                return result
            finally:
                graph.active.remove(key)
        finally:
            if token is not None:
                _READ_GRAPH.reset(token)

    return read


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

    def put_restart_plan(self, plan: PreExecutionRestartPlan) -> PreExecutionRestartPlan:
        plan.validate_integrity()
        if plan.scope != self._scope:
            raise RecoveryRejected("restart plan scope mismatch")
        return self._put("restart-plan", plan.plan_sha256, plan, PreExecutionRestartPlan)

    def get_restart_plan(self, plan_sha256: str) -> PreExecutionRestartPlan:
        plan = self._get("restart-plan", plan_sha256, PreExecutionRestartPlan)
        plan.validate_integrity()
        if plan.scope != self._scope or plan.plan_sha256 != plan_sha256:
            raise RecoveryRejected("restart plan identity mismatch")
        return plan

    def put_restart_authorization(self, record: RecoveryAuthorization) -> RecoveryAuthorization:
        plan = self.get_restart_plan(record.command.plan_sha256)
        record.validate_integrity()
        if record.command.submitted_at < plan.created_at:
            raise RecoveryRejected("restart approval predates plan")
        return self._put("restart-authorization", plan.plan_sha256, record, RecoveryAuthorization)

    def get_restart_authorization(self, plan_sha256: str) -> RecoveryAuthorization:
        plan = self.get_restart_plan(plan_sha256)
        record = self._get("restart-authorization", plan_sha256, RecoveryAuthorization)
        record.validate_integrity()
        if (
            record.command.plan_sha256 != plan_sha256
            or record.command.submitted_at < plan.created_at
        ):
            raise RecoveryRejected("restart authorization identity mismatch")
        return record

    def put_repair_plan(self, plan: PrerequisiteRepairPlan) -> PrerequisiteRepairPlan:
        self._validate_repair_plan(plan)
        return self._put("prerequisite-repair", plan.plan_sha256, plan, PrerequisiteRepairPlan)

    def get_repair_plan(self, plan_sha256: str) -> PrerequisiteRepairPlan:
        plan = self._get("prerequisite-repair", plan_sha256, PrerequisiteRepairPlan)
        self._validate_repair_plan(plan)
        if plan.plan_sha256 != plan_sha256:
            raise RecoveryRejected("repair plan filename identity mismatch")
        return plan

    def _validate_repair_plan(self, plan: PrerequisiteRepairPlan) -> None:
        plan.validate_integrity()
        advice = None
        if plan.manager_advice_input_sha256 is not None:
            advice = self.get_verification_advice(plan.manager_advice_input_sha256)
            if (
                advice.draft.prerequisite_repair != plan.request
                or advice.candidate_revision != plan.candidate_revision
            ):
                raise RecoveryRejected("repair differs from the exact Manager proposal")
        source = self.get_verification_plan(plan.source_plan_sha256)
        if plan.executor_prerequisite_sha256 is not None:
            observation = self.get_executor_prerequisite(plan.executor_prerequisite_sha256)
            if (
                observation.plan_sha256 != source.plan_sha256
                or plan.repository_root != self._scope.repository_root
                or plan.delivery_id != self._scope.delivery_id
                or plan.source_task_id != observation.source_task_id
                or plan.candidate_revision != observation.candidate_revision
                or (
                    advice is not None and advice.execution_failure != observation.execution_failure
                )
            ):
                raise RecoveryRejected("repair plan does not bind this executor prerequisite")
            return
        assert plan.incident_sha256 is not None
        incident = self.get_verification_incident(plan.incident_sha256)
        if (
            plan.repository_root != self._scope.repository_root
            or plan.delivery_id != self._scope.delivery_id
            or plan.source_task_id != source.inputs.task_id
            or plan.source_plan_sha256 != incident.source_plan_sha256
            or plan.completion_sha256 != incident.completion_sha256
            or plan.candidate_revision != incident.candidate_revision
        ):
            raise RecoveryRejected("repair plan does not bind this prerequisite incident")

    def record_executor_prerequisite(
        self, record: VerificationExecutionRecord
    ) -> CandidateExecutorPrerequisite:
        if (
            record.phase != "BLOCKED"
            or self.get_verification_execution(record.plan_sha256, record.role, completed=True)
            != record
        ):
            raise RecoveryRejected("executor prerequisite requires a sealed failure")
        try:
            self.get_verification_completion(record.plan_sha256)
        except RecoveryRecordMissing:
            pass
        else:
            raise RecoveryRejected("a completed verification is not a pre-model executor block")
        plan = self.get_verification_plan(record.plan_sha256)
        value = CandidateExecutorPrerequisite.create(
            plan_sha256=plan.plan_sha256,
            source_task_id=plan.inputs.task_id,
            candidate_revision=plan.inputs.candidate_revision,
            execution_failure=VerificationFailureReference(
                plan_sha256=record.plan_sha256,
                record_sha256=record.record_sha256,
                role=record.role,
            ),
            observed_at=record.recorded_at,
        )
        return self._put(
            "executor-prerequisite", value.observation_sha256, value, CandidateExecutorPrerequisite
        )

    def get_executor_prerequisite(self, sha256: str) -> CandidateExecutorPrerequisite:
        value = self._get("executor-prerequisite", sha256, CandidateExecutorPrerequisite)
        value.validate_integrity()
        ref = value.execution_failure
        record = self.get_verification_execution(ref.plan_sha256, ref.role, completed=True)
        plan = self.get_verification_plan(value.plan_sha256)
        if (
            value.observation_sha256 != sha256
            or record.phase != "BLOCKED"
            or ref.record_sha256 != record.record_sha256
            or value.source_task_id != plan.inputs.task_id
            or value.candidate_revision != record.candidate_revision
            or value.observed_at != record.recorded_at
        ):
            raise RecoveryRejected("executor prerequisite differs from admitted receipt")
        try:
            self.get_verification_completion(value.plan_sha256)
        except RecoveryRecordMissing:
            pass
        else:
            raise RecoveryRejected("a completed verification is not a pre-model executor block")
        return value

    def get_remediation_evidence(
        self, plan_sha256: str, executor_prerequisite_sha256: str | None = None
    ) -> CandidateRemediationEvidence:
        if executor_prerequisite_sha256 is None:
            return self.get_verification_completion(plan_sha256)
        value = self.get_executor_prerequisite(executor_prerequisite_sha256)
        if value.plan_sha256 != plan_sha256:
            raise RecoveryRejected("executor prerequisite belongs to another plan")
        return value

    def put_repair_authorization(self, record: RecoveryAuthorization) -> RecoveryAuthorization:
        record.validate_integrity()
        plan = self.get_repair_plan(record.command.plan_sha256)
        if record.command.submitted_at < plan.created_at:
            raise RecoveryRejected("repair authorization predates proposal")
        return self._put("repair-authorization", plan.plan_sha256, record, RecoveryAuthorization)

    def get_repair_authorization(self, plan_sha256: str) -> RecoveryAuthorization:
        plan = self.get_repair_plan(plan_sha256)
        record = self._get("repair-authorization", plan_sha256, RecoveryAuthorization)
        record.validate_integrity()
        if (
            record.command.plan_sha256 != plan_sha256
            or record.command.submitted_at < plan.created_at
        ):
            raise RecoveryRejected("repair authorization identity mismatch")
        return record

    def put_verification_plan(self, plan: CandidateVerificationPlan) -> CandidateVerificationPlan:
        plan.validate_integrity()
        if plan.scope != self._scope:
            raise RecoveryRejected("verification plan scope mismatch")
        self._validate_prerequisite_reference(plan)
        return self._put("verification-plan", plan.plan_sha256, plan, CandidateVerificationPlan)

    @_validated_read
    def get_verification_plan(self, plan_sha256: str) -> CandidateVerificationPlan:
        plan = self._get("verification-plan", plan_sha256, CandidateVerificationPlan)
        if plan.scope != self._scope or plan.plan_sha256 != plan_sha256:
            raise RecoveryRejected("verification plan identity mismatch")
        self._validate_prerequisite_reference(plan)
        return plan

    def _validate_prerequisite_reference(self, plan: CandidateVerificationPlan) -> None:
        self.validate_retained_qa(plan)
        if (
            plan.manager_advice is not None
            and self.get_verification_advice(plan.manager_advice.input_sha256)
            != plan.manager_advice
        ):
            raise RecoveryRejected("verification plan Manager advice is not durable")
        if plan.manager_advice is not None and plan.manager_advice.execution_failure is not None:
            source = self._get(
                "verification-plan",
                plan.manager_advice.execution_failure.plan_sha256,
                CandidateVerificationPlan,
            )
            if source.inputs.task_id != plan.inputs.task_id:
                raise RecoveryRejected("Manager executor advice belongs to another Task")
        if plan.prerequisite_incident_sha256 is None:
            return
        incident = self.get_verification_incident(plan.prerequisite_incident_sha256)
        if (
            incident.candidate_revision != plan.inputs.candidate_revision
            or incident.incident.delivery_id != plan.scope.delivery_id
            or incident.incident.repository_root != plan.scope.repository_root
            or incident.source_plan_sha256 == plan.plan_sha256
        ):
            raise RecoveryRejected("verification prerequisite belongs to another candidate")
        source = self.get_verification_plan(incident.source_plan_sha256)
        if source.inputs.task_id != plan.inputs.task_id:
            raise RecoveryRejected("verification prerequisite belongs to another Task")
        self.get_prior_visual_evidence(plan)

    @_validated_read
    def latest_verification_attempt(
        self, task_id: str, *, excluding: str | None = None
    ) -> CandidateVerificationPlan | None:
        """Use platform admission time, never model-authored artifact timestamps."""
        attempts = []
        for role in (AgentRole.QA, AgentRole.REVIEWER):
            prefix = f"verification-{role.value}-"
            for path in self._root.glob(f"{prefix}*.json"):
                sha = path.name.removeprefix(prefix).removesuffix(".json")
                if sha == excluding:
                    continue
                invocation = self.get_verification_invocation(sha, role)
                if invocation.request.task_id == task_id:
                    attempts.append(invocation)
        if not attempts:
            return None
        latest = max(attempts, key=lambda item: (item.admitted_at, item.invocation_sha256))
        return self.get_verification_plan(latest.plan_sha256)

    def validate_retained_qa(self, plan: CandidateVerificationPlan) -> None:
        ref = plan.retained_qa
        if ref is None:
            return
        source = self.get_verification_plan(ref.plan_sha256)
        qa_call = self.get_verification_invocation(ref.plan_sha256, AgentRole.QA)
        try:
            review_call = self.get_verification_invocation(ref.plan_sha256, AgentRole.REVIEWER)
        except RecoveryRecordMissing:
            review_call = None
        definition = next(d for d in source.definitions if d.role is AgentRole.QA)
        qa = ref.qa
        if (
            source.retained_qa is not None
            or source.scope != plan.scope
            or source.inputs.model_copy(update={"prior_run_ids": plan.inputs.prior_run_ids})
            != plan.inputs
            or source.dispatch_sha256 != plan.dispatch_sha256
            or source.approved_stage_chain_sha256 != plan.approved_stage_chain_sha256
            or source.parent_delivery_id != plan.parent_delivery_id
            or qa_call.invocation_sha256 != ref.qa_invocation_sha256
            or (review_call.invocation_sha256 if review_call else None)
            != ref.reviewer_invocation_sha256
            or (
                review_call is not None
                and review_call.request.input_artifact_ids[-1] != qa.artifact_id
            )
            or (source.native_ui.scenario if source.native_ui else None)
            != (plan.native_ui.scenario if plan.native_ui else None)
            or qa.task_id != plan.inputs.task_id
            or qa.source_revision != plan.inputs.candidate_revision
            or qa.parent_artifact_ids != (plan.inputs.implementation_id,)
            or qa.supersedes is not None
            or qa.producer.role is not AgentRole.QA
            or qa.producer.agent_id != definition.id
            or qa.producer.run_id != qa_call.request.run_id
            or qa.context_manifest_id != qa_call.request.context_manifest_id
            or qa.content.status is not QaReportStatus.PASS
            or not qa.integrity.validated
            or artifact_digest(qa) != qa.integrity.sha256
            or plan.created_at < (review_call or qa_call).admitted_at
        ):
            raise RecoveryRejected("retained QA differs from admitted standalone verification")
        try:
            self.get_verification_completion(source.plan_sha256)
        except RecoveryRecordMissing:
            pass
        else:
            raise RecoveryRejected("completed verification cannot supply interrupted QA reuse")
        if source.executor_capability is not None:
            receipt = self.get_verification_execution(
                source.plan_sha256, AgentRole.QA, completed=True
            )
            if receipt.phase != "COMPLETED" or receipt.effective_failure_code is not None:
                raise RecoveryRejected("retained QA lacks successful controlled execution")

    def get_prior_visual_evidence(
        self, plan: CandidateVerificationPlan
    ) -> VerificationExecutionRecord | None:
        """Revalidate the single explicitly approved predecessor, without following its images."""
        reference = plan.prior_visual_evidence
        if reference is None:
            return None
        if plan.prerequisite_incident_sha256 is None:
            raise RecoveryRejected("prior visual evidence has no prerequisite")
        incident = self.get_verification_incident(plan.prerequisite_incident_sha256)
        if reference.plan_sha256 != incident.source_plan_sha256:
            raise RecoveryRejected("prior visual evidence differs from the prerequisite plan")
        source = self.get_verification_plan(reference.plan_sha256)
        completion = self.get_verification_completion(reference.plan_sha256)
        receipt = self.get_verification_execution(
            reference.plan_sha256, AgentRole.QA, completed=True
        )
        if (
            source.scope != plan.scope
            or source.inputs.model_copy(
                update={
                    "prior_run_ids": plan.inputs.prior_run_ids,
                }
            )
            != plan.inputs
            or completion.completion_sha256 != incident.completion_sha256
            or completion.qa_invocation_sha256 != receipt.invocation_sha256
            or receipt.record_sha256 != reference.record_sha256
            or receipt.phase != "COMPLETED"
            or receipt.effective_failure_code is not None
            or not any(result.output.capture is not None for result in receipt.ui_results or ())
        ):
            raise RecoveryRejected("prior visual evidence differs from sealed candidate facts")
        return receipt

    def record_verification_incident(
        self, completion: CandidateVerificationCompletion
    ) -> VerificationEnvironmentIncident:
        """Run the Manager decision against authoritative, already sealed QA facts."""
        if self.get_verification_completion(completion.plan_sha256) != completion:
            raise RecoveryRejected("Manager incident requires a sealed completion")
        if completion.disposition is not CandidateVerificationDisposition.RETRY_VERIFICATION:
            raise RecoveryRejected("a business failure is not an environment prerequisite")
        plan = self.get_verification_plan(completion.plan_sha256)
        record = VerificationEnvironmentIncident.create(
            source_plan_sha256=plan.plan_sha256,
            completion_sha256=completion.completion_sha256,
            candidate_revision=plan.inputs.candidate_revision,
            qa_artifact_id=completion.qa.artifact_id,
            delivery_id=self._scope.delivery_id,
            repository_root=self._scope.repository_root,
            not_tested=sum(
                c.status is QaCriterionStatus.NOT_TESTED
                for c in completion.qa.content.criteria_results
            ),
            errors=sum(t.status is QaTestStatus.ERROR for t in completion.qa.content.tests_run),
        )
        return self._put(
            "verification-incident", record.incident_sha256, record, VerificationEnvironmentIncident
        )

    @_validated_read
    def get_verification_incident(self, incident_sha256: str) -> VerificationEnvironmentIncident:
        record = self._get(
            "verification-incident", incident_sha256, VerificationEnvironmentIncident
        )
        record.validate_integrity()
        if record.incident_sha256 != incident_sha256:
            raise RecoveryRejected("verification incident filename identity mismatch")
        # Read the source plan directly to avoid recursively following an untrusted graph.
        plan = self._get("verification-plan", record.source_plan_sha256, CandidateVerificationPlan)
        plan.validate_integrity()
        completion = self.get_verification_completion(record.source_plan_sha256)
        expected = VerificationEnvironmentIncident.create(
            source_plan_sha256=plan.plan_sha256,
            completion_sha256=completion.completion_sha256,
            candidate_revision=plan.inputs.candidate_revision,
            qa_artifact_id=completion.qa.artifact_id,
            delivery_id=self._scope.delivery_id,
            repository_root=self._scope.repository_root,
            not_tested=sum(
                c.status is QaCriterionStatus.NOT_TESTED
                for c in completion.qa.content.criteria_results
            ),
            errors=sum(t.status is QaTestStatus.ERROR for t in completion.qa.content.tests_run),
        )
        if (
            record != expected
            or completion.disposition is not CandidateVerificationDisposition.RETRY_VERIFICATION
        ):
            raise RecoveryRejected("verification incident differs from authoritative QA facts")
        return record

    @_validated_read
    def latest_verification_completion(self) -> CandidateVerificationCompletion | None:
        """Read validated immutable completions; orphan plans never count as outcomes."""
        records = tuple(
            self.get_verification_completion(
                path.name.removeprefix("verification-completion-").removesuffix(".json")
            )
            for path in self._root.glob("verification-completion-*.json")
        )
        return max(
            records,
            key=lambda record: (record.completed_at, record.completion_sha256),
            default=None,
        )

    def put_verification_advice(
        self, advice: ManagerVerificationAdvice
    ) -> ManagerVerificationAdvice:
        advice.validate_integrity()
        if advice.scope_sha256 != digest(self._scope.to_wire()):
            raise RecoveryRejected("Manager advice belongs to another delivery scope")
        self._validate_advice_execution(advice)
        return self._put(
            "verification-advice", advice.input_sha256, advice, ManagerVerificationAdvice
        )

    @_validated_read
    def get_verification_advice(self, input_sha256: str) -> ManagerVerificationAdvice:
        advice = self._get("verification-advice", input_sha256, ManagerVerificationAdvice)
        advice.validate_integrity()
        if advice.input_sha256 != input_sha256 or advice.scope_sha256 != digest(
            self._scope.to_wire()
        ):
            raise RecoveryRejected("Manager advice identity mismatch")
        self._validate_advice_execution(advice)
        return advice

    def _validate_advice_execution(self, advice: ManagerVerificationAdvice) -> None:
        ref = advice.execution_failure
        if ref is None:
            return
        record = self.get_verification_execution(ref.plan_sha256, ref.role, completed=True)
        if (
            record.record_sha256 != ref.record_sha256
            or record.effective_failure_code is None
            or record.candidate_revision != advice.candidate_revision
        ):
            raise RecoveryRejected("Manager advice executor source mismatch")
        prerequisite = advice.environment_prerequisite
        if prerequisite is not None:
            last_ui = record.ui_results[-1] if record.ui_results else None
            observed = (
                "SESSION_LOCKED"
                if record.effective_failure_code == "NATIVE_UI_SESSION_LOCKED"
                else last_ui.output.error
                if last_ui
                else None
            )
            if prerequisite.observed_status != observed:
                raise RecoveryRejected("Manager advice session prerequisite source mismatch")

    def latest_verification_execution(
        self, plan: CandidateVerificationPlan
    ) -> VerificationExecutionRecord | None:
        """Read final admitted receipts for this Task/candidate, never infer a verdict."""
        if plan.scope != self._scope:
            raise RecoveryRejected("execution lookup belongs to another delivery scope")
        records: list[VerificationExecutionRecord] = []
        for role in (AgentRole.QA, AgentRole.REVIEWER):
            prefix = f"verification-execution-{role.value}-completed-"
            for path in self._root.glob(f"{prefix}*.json"):
                key = path.name.removeprefix(prefix).removesuffix(".json")
                record = self.get_verification_execution(key, role, completed=True)
                source = self.get_verification_plan(key)
                if (
                    record.candidate_revision == plan.inputs.candidate_revision
                    and source.inputs.task_id == plan.inputs.task_id
                ):
                    records.append(record)
        return max(records, key=lambda r: (r.recorded_at, r.record_sha256), default=None)

    def put_verification_execution(
        self, record: VerificationExecutionRecord
    ) -> VerificationExecutionRecord:
        self._validate_verification_execution(record)
        return self._put(
            f"verification-execution-{record.role.value}-"
            + ("started" if record.phase == "STARTED" else "completed"),
            record.plan_sha256,
            record,
            VerificationExecutionRecord,
        )

    @_validated_read
    def get_verification_execution(
        self, plan_sha256: str, role: AgentRole, *, completed: bool
    ) -> VerificationExecutionRecord:
        phase = "completed" if completed else "started"
        record = self._get(
            f"verification-execution-{role.value}-{phase}", plan_sha256, VerificationExecutionRecord
        )
        if (
            record.plan_sha256 != plan_sha256
            or record.role is not role
            or (record.phase != "STARTED") != completed
        ):
            raise RecoveryRejected("verification execution filename identity mismatch")
        self._validate_verification_execution(record)
        return record

    def _validate_verification_execution(self, record: VerificationExecutionRecord) -> None:
        record.validate_integrity()
        plan = self.get_verification_plan(record.plan_sha256)
        invocation = self.get_verification_invocation(record.plan_sha256, record.role)
        if (
            plan.executor_capability is None
            or record.capability != plan.executor_capability
            or record.native_ui != plan.native_ui
            or record.candidate_revision != plan.inputs.candidate_revision
            or record.invocation_sha256 != invocation.invocation_sha256
            or record.authorization_sha256 != invocation.authorization_sha256
            or record.recorded_at < invocation.admitted_at
        ):
            raise RecoveryRejected("verification execution is outside admitted capability")
        if record.phase != "STARTED":
            if record.ui_results is not None:
                if (
                    plan.native_ui is None
                    or tuple(r.step for r in record.ui_results)
                    != plan.native_ui.scenario.steps[: len(record.ui_results)]
                ):
                    raise RecoveryRejected("native UI receipt differs from approved sequence")
                if len(record.ui_results) > len(plan.native_ui.scenario.steps):
                    raise RecoveryRejected("native UI receipt exceeds approved sequence")
            for index, result in enumerate(record.results):
                action: Literal["build", "test"] = "build" if index == 0 else "test"
                expected_argv = swift_sandbox_command(
                    record.capability, Path(record.source_root), Path(record.scratch_root), action
                )
                if result.argv != expected_argv or result.cwd != record.source_root:
                    raise RecoveryRejected("verification receipt contains unapproved commands")
            started = self.get_verification_execution(
                record.plan_sha256, record.role, completed=False
            )
            if (
                record.model_copy(
                    update={
                        "phase": "STARTED",
                        "results": (),
                        "ui_results": None,
                        "failure_code": None,
                        "recorded_at": started.recorded_at,
                        "record_sha256": started.record_sha256,
                    }
                )
                != started
            ):
                raise RecoveryRejected("completed execution differs from its durable start")

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

    @_validated_read
    def get_verification_authorization(self, plan_sha256: str) -> RecoveryAuthorization:
        plan = self.get_verification_plan(plan_sha256)
        record = self._get("verification-authorization", plan_sha256, RecoveryAuthorization)
        if (
            record.command.plan_sha256 != plan_sha256
            or record.command.submitted_at < plan.created_at
        ):
            raise RecoveryRejected("verification authorization identity mismatch")
        return record

    @_validated_read
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
                plan.reused_qa is not None
                or record.request.input_artifact_ids != prefix
                or record.request.expected_parent_artifact_ids != prefix[1:]
            ):
                raise RecoveryRejected("persisted QA invocation has invalid input lineage")
        else:
            if (
                len(record.request.input_artifact_ids) != 3
                or record.request.input_artifact_ids[:2] != prefix
                or record.request.expected_parent_artifact_ids
                != record.request.input_artifact_ids[2:]
            ):
                raise RecoveryRejected("persisted Reviewer invocation has invalid input lineage")
            if plan.reused_qa is not None:
                if record.request.input_artifact_ids[2] != plan.reused_qa.artifact_id:
                    raise RecoveryRejected("persisted Reviewer does not bind the pinned QA report")
            else:
                qa = self.get_verification_invocation(plan.plan_sha256, AgentRole.QA)
                if (
                    record.request.run_id == qa.request.run_id
                    or record.admitted_at < qa.admitted_at
                ):
                    raise RecoveryRejected("persisted Reviewer invocation has invalid role order")

    def put_verification_completion(
        self, record: CandidateVerificationCompletion
    ) -> CandidateVerificationCompletion:
        self._validate_verification_completion(record)
        return self._put(
            "verification-completion", record.plan_sha256, record, CandidateVerificationCompletion
        )

    @_validated_read
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
        reports: list[tuple[AgentRole, QaReportArtifact | ReviewReportArtifact, str | None]] = []
        if plan.reused_qa is not None:
            if (
                record.qa_invocation_sha256 is not None
                or record.qa.artifact_id != plan.reused_qa.artifact_id
                or artifact_digest(record.qa) != plan.reused_qa.artifact_sha256
                or record.qa.task_id != plan.inputs.task_id
                or record.qa.source_revision != plan.inputs.candidate_revision
                or record.qa.parent_artifact_ids != (plan.inputs.implementation_id,)
                or record.qa.supersedes is not None
                or record.qa.producer.role is not AgentRole.QA
                or record.qa.content.status is not QaReportStatus.PASS
            ):
                raise RecoveryRejected("completion reused QA differs from the approved plan")
        else:
            if record.qa_invocation_sha256 is None:
                raise RecoveryRejected("fresh QA completion is missing its invocation")
            reports.append((AgentRole.QA, record.qa, record.qa_invocation_sha256))
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
            "restart-plan",
            "restart-authorization",
            "authorization",
            "task",
            "seed",
            "invocation",
            "verification-plan",
            "verification-authorization",
            "verification-qa",
            "verification-reviewer",
            "verification-completion",
            "verification-incident",
            "verification-advice",
            "prerequisite-repair",
            "repair-authorization",
            "executor-prerequisite",
            "verification-execution-qa-started",
            "verification-execution-qa-completed",
            "verification-execution-reviewer-started",
            "verification-execution-reviewer-completed",
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
