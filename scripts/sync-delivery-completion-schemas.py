"""Synchronize added contracts while retaining handwritten legacy Schema gates."""

import json
from pathlib import Path

from pydantic import BaseModel

from ai_software_engineer.agents.models import AgentRequest
from ai_software_engineer.domain.artifact import PlanContent
from ai_software_engineer.domain.delivery_disposition import (
    DeliveryDisposition,
    DeliveryFailureFacts,
)
from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
from ai_software_engineer.domain.execution_window import (
    CoderWorkSlice,
    PlanExecutionWindow,
    PlannedVerificationRequirement,
)
from ai_software_engineer.domain.native_verification import (
    NativeRoleVerificationAdmission,
    NativeRoleVerificationPlan,
)
from ai_software_engineer.domain.project_delivery import AcceptanceDesignMapping, ExecutionPlan
from ai_software_engineer.domain.task import Task
from ai_software_engineer.domain.workforce import WorkItem
from ai_software_engineer.manager.baseline_models import ExecutionBaselinePlan
from ai_software_engineer.manager.delivery_preflight import (
    DeliveryPreflightCheckpoint,
    DeliveryPreflightReceipt,
)
from ai_software_engineer.manager.production_agents import (
    AcceptanceMappingDraft,
    ExecutionPlanDraft,
)
from ai_software_engineer.manager.verifier_preparation import (
    VerifierPreparationCheckpoint,
    VerifierPreparationIntent,
    VerifierPreparationObservation,
)
from ai_software_engineer.multi_directory.models import JointApproval, JointCheckpoint
from ai_software_engineer.work_queue.baseline import BaselineQueueConsumption

ROOT = Path(__file__).resolve().parents[1] / "schemas"
FIELDS: dict[type[BaseModel], tuple[str, ...]] = {
    Task: ("engineering_policy",),
    WorkItem: ("wait_disposition",),
    AgentRequest: ("work_slice", "execution_baseline_sha256", "execution_base_ref"),
    PlanContent: ("verification_requirements", "execution_window"),
    ExecutionPlan: ("execution_window",),
    ExecutionPlanDraft: ("execution_window",),
    AcceptanceDesignMapping: (
        "verification_argv",
        "planned_test_files",
        "controlled_capability_kind",
        "verification_inspection",
    ),
    AcceptanceMappingDraft: (
        "verification_argv",
        "planned_test_files",
        "controlled_capability_kind",
        "verification_inspection",
    ),
    JointApproval: ("operator_principal",),
    JointCheckpoint: ("execution_window",),
}

# These definitions were introduced by this task and have no handwritten legacy
# gates. Refresh them fully when their models evolve; setdefault alone silently
# retained an obsolete nested reservation in already-generated schemas.
ADDED_DEFINITIONS = frozenset(
    {
        "CoderWorkSlice",
        "PlanExecutionWindow",
        "PlannedVerificationRequirement",
        "VerificationInspection",
        "DeliveryDisposition",
        "DeliveryFailureFacts",
        "ExecutionBaselineBinding",
        "ExecutionBaselinePlan",
        "BaselineExecutionFacts",
        "BaselineExecutionReservation",
        "RetainedExecutionPatch",
        "BaselineInputMode",
        "VerifierPreparationCheckpoint",
        "VerifierPreparationIntent",
        "VerifierPreparationObservation",
    }
)


def main() -> None:
    generated = {model.__name__: model.model_json_schema() for model in FIELDS}
    for path in sorted(ROOT.glob("*.schema.json")):
        schema = json.loads(path.read_text())
        before = json.dumps(schema)
        schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
        schema.setdefault("$id", f"https://ai-software-engineer.local/schemas/{path.name}")
        definitions = schema.setdefault("$defs", {})
        for model, names in FIELDS.items():
            source = generated[model.__name__]
            targets = [definitions[model.__name__]] if model.__name__ in definitions else []
            if schema.get("title") == model.__name__ and "properties" in schema:
                targets.append(schema)
            for target in targets:
                for name in names:
                    if name not in source["properties"]:
                        raise ValueError(f"unknown contract {model.__name__}.{name}")
                    target["properties"][name] = source["properties"][name]
                # Existing nodes contain handwritten cross-field constraints;
                # add only absent definitions and update additive contracts in
                # the same pass rather than replacing those nodes wholesale.
                for name, node in source.get("$defs", {}).items():
                    if name in ADDED_DEFINITIONS:
                        definitions[name] = node
                    else:
                        definitions.setdefault(name, node)
        if json.dumps(schema) != before:
            path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")
    standalone: dict[str, type[BaseModel]] = {
        "coder-work-slice": CoderWorkSlice,
        "plan-execution-window": PlanExecutionWindow,
        "planned-verification-requirement": PlannedVerificationRequirement,
        "delivery-disposition": DeliveryDisposition,
        "delivery-failure-facts": DeliveryFailureFacts,
        "delivery-preflight": DeliveryPreflightReceipt,
        "delivery-preflight-checkpoint": DeliveryPreflightCheckpoint,
        "execution-baseline": ExecutionBaselineBinding,
        "execution-baseline-plan": ExecutionBaselinePlan,
        "native-role-verification-plan": NativeRoleVerificationPlan,
        "native-role-verification-admission": NativeRoleVerificationAdmission,
        "verifier-preparation-checkpoint": VerifierPreparationCheckpoint,
        "verifier-preparation-intent": VerifierPreparationIntent,
        "verifier-preparation-observation": VerifierPreparationObservation,
        "execution-baseline-queue-consumption": BaselineQueueConsumption,
    }
    for name, model in standalone.items():
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://ai-software-engineer.local/schemas/{name}.schema.json"
        (ROOT / f"{name}.schema.json").write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
        )


if __name__ == "__main__":
    main()
