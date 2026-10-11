"""Refresh additive rescue contracts, retaining handwritten legacy wire gates."""

import json
from pathlib import Path

from pydantic import TypeAdapter

from ai_software_engineer.domain.execution_baseline import ExecutionBaselineBinding
from ai_software_engineer.domain.execution_native_rules import (
    NativeRuleChangeInspection,
    NativeRuleEpoch,
)
from ai_software_engineer.knowledge.stages import StageWorkflowProof
from ai_software_engineer.manager.baseline_models import (
    BaselineContinueAuthorization,
    ExecutionBaselinePlan,
)
from ai_software_engineer.manager.completed_output_checkpoint import (
    CompletedCoderOutputUnavailableProof,
)
from ai_software_engineer.multi_directory.models import JointCheckpoint
from ai_software_engineer.team_view.models import TeamSnapshot
from ai_software_engineer.web_console.models import (
    ConsoleOperation,
    ExecuteExecutionBaselineIntent,
    ProposeExecutionBaselineIntent,
    ResumeExecutionBaselineIntent,
)
from ai_software_engineer.work_queue.baseline import BaselineQueueConsumption, BaselineQueueRelease
from ai_software_engineer.work_queue.execution_store import (
    AcceptedRoleArtifact,
    QueuedRoleStep,
    RoleQueueAdmission,
)

ROOT = Path(__file__).resolve().parents[1] / "schemas"
MODELS = (
    ExecutionBaselineBinding,
    ExecutionBaselinePlan,
    BaselineQueueConsumption,
    ConsoleOperation,
    BaselineContinueAuthorization,
    NativeRuleEpoch,
    NativeRuleChangeInspection,
    BaselineQueueRelease,
    TeamSnapshot,
    CompletedCoderOutputUnavailableProof,
)
UPDATED = {
    "ExecutionBaselineBinding",
    "ExecutionBaselinePlan",
    "BaselineExecutionFacts",
    "BaselineExecutionReservation",
    "BaselineOperatorAuthorization",
    "BaselinePurpose",
    "LegacyExecutionContainment",
    "LocalBootObservation",
    "LegacyLocalExecutionSurvey",
    "LegacyRescuePreparation",
    "BaselineContinuationMode",
    "BaselineContinueAuthorization",
    "DeliveryFailureFacts",
    "DeliveryDisposition",
    "DeliveryNextAction",
    "NativeRuleChangePlan",
    "NativeRuleDelta",
    "NativeRuleEpochReference",
    "ResumeExecutionBaselineIntent",
    "RoleQueueView",
    "CompletedCoderOutputUnavailableProof",
    "ProposeExecutionBaselineIntent",
}


def main() -> None:
    generated = [model.model_json_schema() for model in MODELS]
    nodes = {name: node for source in generated for name, node in source.get("$defs", {}).items()}
    nodes.update(
        {source["title"]: {k: v for k, v in source.items() if k != "$defs"} for source in generated}
    )
    standalone = (
        ("baseline-continue-authorization", BaselineContinueAuthorization),
        ("execution-native-rule-epoch", NativeRuleEpoch),
        ("execution-native-rule-change-inspection", NativeRuleChangeInspection),
        ("execution-baseline-queue-release", BaselineQueueRelease),
        ("team-snapshot", TeamSnapshot),
        # This exact generated graph owns the Manager's DeliveryNextAction.
        # Name-only rescue updates otherwise replace it with the disposition enum.
        ("requirement-checkpoint", JointCheckpoint),
        ("knowledge-stage-workflow", StageWorkflowProof),
        ("completed-coder-output-unavailable", CompletedCoderOutputUnavailableProof),
    )
    standalone_names = {f"{filename}.schema.json" for filename, _ in standalone}
    for filename, model in standalone:
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://ai-software-engineer.local/schemas/{filename}.schema.json"
        for node in (schema, *schema.get("$defs", {}).values()):
            guards(node)
        (ROOT / f"{filename}.schema.json").write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=model is TeamSnapshot) + "\n"
        )
    for path in ROOT.glob("*.schema.json"):
        if path.name in standalone_names:
            continue
        document = json.loads(path.read_text())
        before = json.dumps(document)
        definitions = document.get("$defs", {})
        for source in generated:
            if (
                document.get("title") == source.get("title")
                and source["title"] != "ConsoleOperation"
            ):
                document = {**source, "$id": document["$id"], "$schema": document["$schema"]}
                definitions = document.setdefault("$defs", {})
        for name in UPDATED & definitions.keys():
            if name in nodes:
                definitions[name] = nodes[name]
        if "ConsoleCommandResult" in definitions:
            definitions["ConsoleCommandResult"]["properties"]["legacy_rescue_preparation"] = nodes[
                "ConsoleCommandResult"
            ]["properties"]["legacy_rescue_preparation"]
        if "ProposeExecutionBaselineIntent" in definitions:
            for intent_model, field in (
                (ProposeExecutionBaselineIntent, "purpose"),
                (ExecuteExecutionBaselineIntent, "confirm_legacy_containment"),
                (ExecuteExecutionBaselineIntent, "confirm_local_execution_stopped"),
                (ExecuteExecutionBaselineIntent, "continuation_mode"),
                (ExecuteExecutionBaselineIntent, "approved_native_rule_change_sha256"),
            ):
                source = intent_model.model_json_schema()
                definitions[intent_model.__name__]["properties"][field] = source["properties"][
                    field
                ]
        if document.get("title") == "ConsoleOperation":
            source = ConsoleOperation.model_json_schema()
            document["properties"]["intent"] = source["properties"]["intent"]
            definitions["ResumeExecutionBaselineIntent"] = (
                ResumeExecutionBaselineIntent.model_json_schema()
            )
            definitions["ResumeExecutionBaselineIntent"].pop("$defs", None)
        while True:
            references = refs(document)
            missing = references - definitions.keys()
            if not missing:
                break
            for name in missing:
                definitions[name] = nodes[name]
            document["$defs"] = definitions
        for node in [document, *definitions.values()]:
            guards(node)
        if json.dumps(document) != before:
            path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    # Full historical traversal consumes this union too. Its exact schema
    # previously omitted the existing QueuedWorkItem.wait_disposition contract.
    queue_path = ROOT / "role-queue-execution.schema.json"
    previous = json.loads(queue_path.read_text())
    adapter: TypeAdapter[RoleQueueAdmission | QueuedRoleStep | AcceptedRoleArtifact] = TypeAdapter(
        RoleQueueAdmission | QueuedRoleStep | AcceptedRoleArtifact
    )
    queue_document = {
        **adapter.json_schema(),
        "$id": previous["$id"],
        "$schema": previous["$schema"],
    }
    if queue_document != previous:
        queue_path.write_text(
            json.dumps(queue_document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
    # Standalone envelopes embed the same guarded contracts as public operations.
    # Preserve their cross-field gates during this final generated rewrite too.
    for filename, model in standalone:
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://ai-software-engineer.local/schemas/{filename}.schema.json"
        for node in (schema, *schema.get("$defs", {}).values()):
            guards(node)
        (ROOT / f"{filename}.schema.json").write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=model is TeamSnapshot) + "\n"
        )


def refs(value: object) -> set[str]:
    if isinstance(value, dict):
        reference = value.get("$ref")
        found = (
            {reference[8:]}
            if isinstance(reference, str) and reference.startswith("#/$defs/")
            else set()
        )
        return found | set().union(*(refs(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(refs(child) for child in value))
    return set()


def guards(node: dict[str, object]) -> None:
    title = node.get("title")
    if title == "ProposeExecutionBaselineIntent":
        node["allOf"] = [
            {
                "if": {
                    "required": ["purpose"],
                    "properties": {"purpose": {"const": "completed_output_rescue"}},
                },
                "then": {
                    "properties": {
                        "target_base_ref": {"type": "null"},
                        "input_mode": {"const": "preserve_draft"},
                    }
                },
                "else": {
                    "required": ["target_base_ref"],
                    "properties": {"target_base_ref": {"type": "string"}},
                },
            }
        ]
    elif title == "LegacyExecutionContainment":
        node["allOf"] = [
            {
                "if": {
                    "required": ["method"],
                    "properties": {"method": {"const": "operator_confirmed_local_stop"}},
                },
                "then": {
                    "required": ["local_execution_survey"],
                    "properties": {
                        "local_execution_survey": {
                            "type": "object",
                            "properties": {"blockers": {"maxItems": 0}},
                        }
                    },
                },
                "else": {"properties": {"local_execution_survey": {"type": "null"}}},
            }
        ]
    elif title in {"BaselineOperatorAuthorization", "ExecuteExecutionBaselineIntent"}:
        existing = node.get("allOf", [])
        assert isinstance(existing, list)
        exclusive = {
            "not": {
                "required": ["confirm_legacy_containment", "confirm_local_execution_stopped"],
                "properties": {
                    "confirm_legacy_containment": {"const": True},
                    "confirm_local_execution_stopped": {"const": True},
                },
            }
        }
        if exclusive not in existing:
            node["allOf"] = [*existing, exclusive]
    elif title == "ConsoleCommandResult":
        existing = node.get("allOf", [])
        assert isinstance(existing, list)
        existing = [
            guard
            for guard in existing
            if not (
                isinstance(guard, dict)
                and isinstance(guard.get("if"), dict)
                and guard["if"].get("required") == ["legacy_rescue_preparation"]
            )
        ]
        gate = {
            "if": {
                "required": ["legacy_rescue_preparation"],
                "properties": {
                    "legacy_rescue_preparation": {"type": "object"},
                },
            },
            "then": {
                "required": ["delivery_id", "checkpoint_sha256"],
                "properties": {
                    "delivery_id": {"type": "string"},
                    "checkpoint_sha256": {"type": "string"},
                    "execution_baseline_binding": {"type": "null"},
                    "approval": {"type": "null"},
                },
                "allOf": [
                    {
                        "if": {
                            "properties": {
                                "legacy_rescue_preparation": {
                                    "properties": {"status": {"const": "READY"}},
                                }
                            }
                        },
                        "then": {
                            "required": ["execution_baseline_plan"],
                            "properties": {
                                "execution_baseline_plan": {
                                    "type": "object",
                                    "required": ["purpose"],
                                    "properties": {"purpose": {"const": "legacy_workspace_rescue"}},
                                }
                            },
                        },
                    },
                    {
                        "if": {
                            "properties": {
                                "legacy_rescue_preparation": {
                                    "properties": {"status": {"const": "WAITING"}},
                                }
                            }
                        },
                        "then": {
                            "properties": {
                                "execution_baseline_plan": {"type": "null"},
                                "execution_baseline_binding": {"type": "null"},
                                "approval": {"type": "null"},
                            }
                        },
                    },
                ],
            },
        }
        node["allOf"] = [*existing, gate]
    elif title == "BaselineExecutionReservation":
        node["allOf"] = [
            {
                "if": {
                    "required": ["retry_cause"],
                    "properties": {"retry_cause": {"const": "legacy_execution_abandoned"}},
                },
                "then": {
                    "required": [
                        "original_run_id",
                        "current_invocation_start_sha256",
                        "containment_sha256",
                    ],
                    "properties": {
                        "original_run_id": {"type": "string"},
                        "current_invocation_start_sha256": {"type": "string"},
                        "containment_sha256": {"type": "string"},
                        "current_invocation_outcome_sha256": {"type": "null"},
                        "interruption_receipt_sha256": {"type": "null"},
                        "retry_failure": {"type": "null"},
                        "reservation_already_applied": {"const": False},
                    },
                },
            },
            {
                "if": {
                    "required": ["retry_cause"],
                    "properties": {"retry_cause": {"const": "completed_output_unavailable"}},
                },
                "then": {
                    "required": [
                        "original_run_id",
                        "current_invocation_start_sha256",
                        "current_invocation_outcome_sha256",
                        "completed_output_sha256",
                    ],
                    "properties": {
                        "original_run_id": {"type": "string"},
                        "current_invocation_start_sha256": {"type": "string"},
                        "current_invocation_outcome_sha256": {"type": "string"},
                        "completed_output_sha256": {"type": "string"},
                        "containment_sha256": {"type": "null"},
                        "interruption_receipt_sha256": {"type": "null"},
                        "retry_failure": {"type": "null"},
                        "reservation_already_applied": {"const": False},
                    },
                },
                "else": {"properties": {"completed_output_sha256": {"type": "null"}}},
            },
        ]
    elif title == "CompletedCoderOutputUnavailableProof":
        node["allOf"] = [
            {
                "properties": {
                    "outcome": {
                        "properties": {
                            "result": {
                                "required": ["error"],
                                "properties": {
                                    "status": {"const": "FAILED"},
                                    "artifact": {"type": "null"},
                                    "error": {
                                        "type": "object",
                                        "properties": {
                                            "code": {"const": "WORK_INTERRUPTED"},
                                            "transient": {"const": False},
                                        },
                                    },
                                },
                            },
                        }
                    },
                    "capture_stop": {
                        "properties": {
                            "output_present": {"const": True},
                            "cause": {"type": "null"},
                            "original_error_code": {"type": "null"},
                            "process_stop": {
                                "properties": {
                                    "kind": {"const": "completed"},
                                    "returncode": {"const": 0},
                                }
                            },
                        }
                    },
                },
            }
        ]
    elif title == "BaselineExecutionFacts":
        node["allOf"] = [
            {
                "if": {
                    "required": ["continuation"],
                    "properties": {
                        "continuation": {
                            "type": "object",
                            "required": ["retry_cause"],
                            "properties": {
                                "retry_cause": {"const": "completed_output_unavailable"}
                            },
                        },
                    },
                },
                "then": {
                    "required": ["completed_output"],
                    "properties": {
                        "completed_output": {"type": "object"},
                        "legacy_containment": {"type": "null"},
                        "implementation_artifact_id": {"type": "null"},
                    },
                },
                "else": {"properties": {"completed_output": {"type": "null"}}},
            }
        ]
    elif title in {"ExecutionBaselinePlan", "ExecutionBaselineBinding"}:
        properties: dict[str, object] = {"input_mode": {"const": "preserve_draft"}}
        required = []
        if title == "ExecutionBaselinePlan":
            properties.update(
                {
                    "conflicted": {"const": False},
                    "facts": {
                        "required": ["legacy_containment"],
                        "properties": {"legacy_containment": {"type": "object"}},
                    },
                }
            )
        else:
            properties.update(
                {
                    "authority_source": {"const": "engineering_operator_decision"},
                    "legacy_containment_sha256": {"type": "string"},
                }
            )
            required = ["legacy_containment_sha256"]
        node["allOf"] = [
            {
                "if": {
                    "required": ["purpose"],
                    "properties": {"purpose": {"const": "legacy_workspace_rescue"}},
                },
                "then": {"required": required, "properties": properties},
            }
        ]

    if title in {"ExecutionBaselinePlan", "ExecutionBaselineBinding"}:
        existing = node.get("allOf", [])
        assert isinstance(existing, list)
        gate = {
            "if": {
                "required": ["purpose"],
                "properties": {"purpose": {"const": "completed_output_rescue"}},
            },
            "then": {
                "properties": (
                    {
                        "input_mode": {"const": "preserve_draft"},
                        "conflicted": {"const": False},
                        "facts": {
                            "required": ["completed_output"],
                            "properties": {
                                "completed_output": {"type": "object"},
                                "legacy_containment": {"type": "null"},
                                "native_rule_change": {"type": "null"},
                                "implementation_artifact_id": {"type": "null"},
                            },
                        },
                    }
                    if title == "ExecutionBaselinePlan"
                    else {
                        "input_mode": {"const": "preserve_draft"},
                        "continuation_mode": {"const": "pause"},
                        "authority_source": {"const": "engineering_operator_decision"},
                        "completed_output_sha256": {"type": "string"},
                        "legacy_containment_sha256": {"type": "null"},
                        "superseded_implementation_artifact_id": {"type": "null"},
                    }
                ),
                **(
                    {"required": ["completed_output_sha256", "continuation_mode"]}
                    if title == "ExecutionBaselineBinding"
                    else {}
                ),
            },
            **(
                {"else": {"properties": {"completed_output_sha256": {"type": "null"}}}}
                if title == "ExecutionBaselineBinding"
                else {}
            ),
        }
        if gate not in existing:
            node["allOf"] = [*existing, gate]


if __name__ == "__main__":
    main()
