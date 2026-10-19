"""Read-only receipt provenance from frozen typed standalone-verification inputs."""

from __future__ import annotations

from ai_software_engineer.agents import AgentRequest
from ai_software_engineer.agents.verification_output import (
    TrustedVerificationOutputContract,
    verification_output_contract,
)
from ai_software_engineer.artifacts import artifact_digest
from ai_software_engineer.domain import AgentRole, PlanArtifact, Task
from ai_software_engineer.domain.model import DomainModel
from ai_software_engineer.manager.python_verification import PythonMysqlSandboxCapability
from ai_software_engineer.recovery.models import RecoveryRejected, digest
from ai_software_engineer.recovery.verification_records import (
    CandidateVerificationPlan,
    VerificationExecutionRecord,
)
from ai_software_engineer.swift_verification import SWIFT_VERIFICATION_COMMANDS


class VerificationOutputInputs(DomainModel):
    """Exact native facts for coverage; neither prompt parsing nor execution authority."""

    task: Task
    plan_artifact: PlanArtifact

    def validate_plan(self, plan: CandidateVerificationPlan) -> None:
        if (
            self.task.id != plan.inputs.task_id
            or digest(self.task.to_wire()) != plan.inputs.task_sha256
            or self.plan_artifact.task_id != self.task.id
            or self.plan_artifact.artifact_id != plan.inputs.plan_id
            or artifact_digest(self.plan_artifact) != plan.inputs.plan_sha256
        ):
            raise RecoveryRejected("verification output inputs differ from the frozen plan")


def receipt_output_contract(
    plan: CandidateVerificationPlan,
    request: AgentRequest,
    receipt: VerificationExecutionRecord,
    inputs: VerificationOutputInputs | None,
) -> TrustedVerificationOutputContract:
    """Bind only actual approved coverage; legacy missing typed mappings stay unknown."""
    covered: set[str] = set()
    if inputs is not None:
        inputs.validate_plan(plan)
        if isinstance(plan.executor_capability, PythonMysqlSandboxCapability):
            covered = {
                criterion
                for selection in plan.executor_capability.selections
                for criterion in selection.criterion_ids
            }
        else:
            requirements = inputs.plan_artifact.content.verification_requirements or ()
            direct = tuple(item for item in requirements if item.role is request.role)
            effective = direct or tuple(item for item in requirements if item.role is AgentRole.QA)
            commands = {tuple(command.split()) for command in SWIFT_VERIFICATION_COMMANDS[1:]}
            scenario_sha256 = (
                digest(plan.native_ui.scenario.to_wire())
                if plan.native_ui is not None and receipt.ui_results is not None
                else None
            )
            for item in effective:
                if item.argv in commands or (
                    item.inspection is not None
                    and item.inspection.kind == "native_ui"
                    and item.inspection.scenario_sha256 == scenario_sha256
                ):
                    covered.update(item.criterion_ids)
        required = {
            criterion.id for criterion in inputs.task.acceptance_criteria if criterion.required
        }
        covered.intersection_update(required)
    return verification_output_contract(
        request,
        receipt_uri=f"verification-execution://{plan.plan_sha256}/{request.role.value}",
        receipt_sha256=receipt.record_sha256,
        authority_sha256=receipt.authorization_sha256,
        receipt_covered_required_criterion_ids=tuple(sorted(covered)),
        command_returncodes=tuple(result.returncode for result in receipt.results),
    )
