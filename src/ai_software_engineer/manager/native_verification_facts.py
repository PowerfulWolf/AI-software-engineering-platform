"""Production readback of accepted role inputs and a real, currently owned claim."""

from collections.abc import Callable, Mapping
from pathlib import Path

from ai_software_engineer.agents.execution import ExecutionGuard
from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.artifacts import ArtifactStore
from ai_software_engineer.context import FileContextStore
from ai_software_engineer.context.execution_baseline import execution_baseline_from_context
from ai_software_engineer.domain import (
    AgentDefinition,
    AgentRole,
    ImplementationReportArtifact,
    PlanArtifact,
    QaReportArtifact,
    QaReportStatus,
    Task,
    TaskStatus,
)
from ai_software_engineer.domain.continuation import task_intent_sha256
from ai_software_engineer.domain.native_verification import (
    NativeRoleVerificationAdmission,
    NativeRoleVerificationPlan,
    role_verification_digest,
)
from ai_software_engineer.manager.native_verification import NativeRoleVerificationInputs
from ai_software_engineer.orchestration.execution_baseline import CoderExecutionInputResolver
from ai_software_engineer.work_queue.worker import WorkerExecutionGuard


class ProductionNativeVerificationFacts:
    def __init__(
        self,
        *,
        task_reader: Callable[[], Task],
        artifacts: ArtifactStore,
        contexts: FileContextStore,
        guard: WorkerExecutionGuard,
        definitions: Mapping[AgentRole, AgentDefinition],
        worktrees_root: Path,
        repository_id: str,
        inputs: CoderExecutionInputResolver | None = None,
    ) -> None:
        self.task_reader, self.artifacts, self.contexts = task_reader, artifacts, contexts
        self.guard, self.definitions, self.root = guard, definitions, worktrees_root
        self.repository_id, self.inputs = repository_id, inputs

    def read(
        self,
        *,
        request: AgentRequest,
        workspace_root: Path,
        guard: ExecutionGuard,
    ) -> NativeRoleVerificationInputs:
        self._require_request(request, workspace_root, guard)
        assert self.guard.lease is not None
        values = tuple(self.artifacts.get(identity) for identity in request.input_artifact_ids)
        plans = tuple(value for value in values if isinstance(value, PlanArtifact))
        implementations = tuple(
            value for value in values if isinstance(value, ImplementationReportArtifact)
        )
        if len(plans) != 1 or len(implementations) != 1:
            raise ValueError("native verifier requires one exact accepted Plan and implementation")
        plan, implementation = plans[0], implementations[0]
        if implementation.content.commit_sha != request.source_revision:
            raise ValueError("native verifier candidate differs from the accepted implementation")
        if request.role is AgentRole.REVIEWER:
            qa = tuple(value for value in values if isinstance(value, QaReportArtifact))
            if (
                len(qa) != 1
                or qa[0].source_revision != request.source_revision
                or qa[0].content.status is not QaReportStatus.PASS
            ):
                raise ValueError("Review requires this same candidate's accepted QA PASS")
            if qa[0].producer.agent_id == self.guard.lease.claim.assignment.agent_id:
                raise ValueError("Review and QA must be independent")
        return NativeRoleVerificationInputs(
            self.task_reader(),
            plan,
            implementation,
            self.guard.lease.claim,
            self,
        )

    def _require_request(
        self,
        request: AgentRequest,
        workspace_root: Path,
        guard: ExecutionGuard,
    ) -> None:
        if guard is not self.guard:
            raise ValueError("native verification uses another execution guard")
        self.guard.check()
        lease = self.guard.lease
        if lease is None:
            raise ValueError("native verification has no real role claim")
        task = self.task_reader()
        expected = TaskStatus.QA if request.role is AgentRole.QA else TaskStatus.REVIEW
        if request.role not in {AgentRole.QA, AgentRole.REVIEWER} or task.status is not expected:
            raise ValueError("native verification is not the currently authorized serial role")
        claim = lease.claim
        context = self.contexts.get(request.context_manifest_id)
        baseline = execution_baseline_from_context(context, request, task)
        current = (
            self.inputs.current(task, implementation=None, progress=None) if self.inputs else None
        )
        expected_binding = current.baseline if current else None
        if baseline != expected_binding:
            raise ValueError(
                "native verification execution baseline is not the current trusted binding"
            )
        root = (
            self.root
            / self.repository_id
            / task.id
            / f"{request.role.value}-attempt-{request.attempt:02d}"
        )
        if (
            task.id != request.task_id
            or task.attempts != request.attempt
            or request.permissions != self.definitions[request.role].permissions
            or (context.task_id, context.role, context.attempt, context.source_revision)
            != (request.task_id, request.role, request.attempt, request.source_revision)
            or (claim.work_item.task_id, claim.work_item.role, claim.work_item.attempt)
            != (task.id, request.role, request.attempt)
            or claim.work_item.repository_id != self.repository_id
            or workspace_root != root
            or root.resolve(strict=True) != root
            or any(path.is_symlink() for path in (root, *root.parents))
        ):
            raise ValueError("native verification Context, Task, workspace or claim facts drifted")

    def validate(
        self,
        *,
        plan: NativeRoleVerificationPlan,
        admission: NativeRoleVerificationAdmission,
        request: AgentRequest,
        workspace_root: Path,
        guard: ExecutionGuard,
    ) -> None:
        inputs = self.read(request=request, workspace_root=workspace_root, guard=guard)
        task, claim = inputs.task, inputs.claim
        plan.validate_integrity()
        admission.validate_integrity()
        if (
            task.engineering_policy is None
            or plan.scope != task.engineering_policy.scope
            or plan.task_intent_sha256 != task_intent_sha256(task)
            or admission.policy != task.engineering_policy
            or plan.policy_sha256 != admission.policy_sha256
            or plan.request_sha256 != role_verification_digest(request.to_wire())
            or plan.plan_artifact_id != inputs.plan_artifact.artifact_id
            or plan.plan_artifact_sha256 != inputs.plan_artifact.integrity.sha256
            or plan.implementation_artifact_id != inputs.implementation.artifact_id
            or plan.implementation_artifact_sha256 != inputs.implementation.integrity.sha256
            or (
                plan.claim.work_item_id,
                plan.claim.lease_id,
                plan.claim.assignment_id,
                plan.claim.agent_id,
                plan.claim.dispatch_sequence,
            )
            != (
                claim.work_item.id,
                claim.lease.id,
                claim.assignment.id,
                claim.assignment.agent_id,
                claim.work_item.dispatch_sequence,
            )
            or plan.work_attempt != task.work_attempt
            or admission.work_attempt != task.work_attempt
        ):
            raise ValueError(
                "native verification binding is no longer the current accepted role input"
            )
