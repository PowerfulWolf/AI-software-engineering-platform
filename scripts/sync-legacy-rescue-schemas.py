"""Refresh additive rescue contracts, retaining handwritten legacy wire gates."""

import json
from pathlib import Path

from pydantic import TypeAdapter

from ai_software_engineer.domain.delivery_resolution import DeliveryWaitInvestigation
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
from ai_software_engineer.manager.baseline_production import (
    BaselineInvocationProof,
    BaselineQuiescenceProof,
    ConsumedPreContextClaimObservation,
    ReclaimedUninvokedClaimObservation,
)
from ai_software_engineer.manager.completed_output_checkpoint import (
    CompletedCoderOutputUnavailableProof,
)
from ai_software_engineer.manager.knowledge_invocation_proof import ReplayGuardedClaimObservation
from ai_software_engineer.manager.knowledge_isolation import KnowledgePreparationIsolationProof
from ai_software_engineer.manager.rejected_candidate_output import RejectedCandidateOutputProof
from ai_software_engineer.manager.rejected_candidate_owner import (
    RejectedCandidateExpiredOwnerSettlement,
)
from ai_software_engineer.manager.stopped_execution_checkpoint import StoppedCoderExecutionProof
from ai_software_engineer.manager.stopped_failure_checkpoint import StoppedFailureProof
from ai_software_engineer.manager.stopped_provider_checkpoint import StoppedProviderFailureProof
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
    StoppedProviderFailureProof,
    StoppedFailureProof,
    StoppedCoderExecutionProof,
    ReplayGuardedClaimObservation,
    DeliveryWaitInvestigation,
    KnowledgePreparationIsolationProof,
    RejectedCandidateOutputProof,
    RejectedCandidateExpiredOwnerSettlement,
    BaselineQuiescenceProof,
    BaselineInvocationProof,
    ConsumedPreContextClaimObservation,
    ReclaimedUninvokedClaimObservation,
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
    "StoppedProviderFailureProof",
    "StoppedFailureProof",
    "StoppedCoderExecutionProof",
    "ExecutionCaptureStop",
    "ExecutionAbortReason",
    "BaselineInvocationProof",
    "ConsumedPreContextClaimObservation",
    "ReplayGuardedClaimObservation",
    "DeliveryWaitInvestigation",
    "KnowledgePreparationIsolationProof",
    "RejectedCandidateOutputProof",
    "RejectedCandidateExpiredOwnerSettlement",
    "BaselineQuiescenceProof",
    "ReclaimedUninvokedClaimObservation",
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
        ("stopped-provider-failure", StoppedProviderFailureProof),
        ("stopped-failure", StoppedFailureProof),
        ("stopped-coder-execution", StoppedCoderExecutionProof),
        ("replay-guarded-claim-observation", ReplayGuardedClaimObservation),
        ("knowledge-preparation-isolation", KnowledgePreparationIsolationProof),
        ("rejected-candidate-output", RejectedCandidateOutputProof),
        ("rejected-candidate-owner-settlement", RejectedCandidateExpiredOwnerSettlement),
        ("baseline-quiescence-proof", BaselineQuiescenceProof),
        ("baseline-invocation-proof", BaselineInvocationProof),
        ("consumed-pre-context-claim-observation", ConsumedPreContextClaimObservation),
        ("reclaimed-uninvoked-claim-observation", ReclaimedUninvokedClaimObservation),
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
                (ExecuteExecutionBaselineIntent, "confirm_provider_prerequisites_repaired"),
                (ExecuteExecutionBaselineIntent, "confirm_stopped_failure_retry"),
                (ExecuteExecutionBaselineIntent, "confirm_current_knowledge_execution_isolated"),
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


def completed_failure_code(code: str) -> dict[str, object]:
    """Match an actual embedded sealed code, not absent nested properties."""
    return {
        "type": "object",
        "required": ["outcome"],
        "properties": {
            "outcome": {
                "required": ["result"],
                "properties": {
                    "result": {
                        "required": ["error"],
                        "properties": {
                            "error": {
                                "required": ["code"],
                                "properties": {"code": {"const": code}},
                            }
                        },
                    }
                },
            }
        },
    }


def stopped_guards(node: dict[str, object]) -> None:
    """Canonical additive guards for fresh and embedded recovery schemas."""
    title = node.get("title")
    extra: list[dict[str, object]] = []
    properties: dict[str, object]
    reverse_if: dict[str, object]
    nulls = {
        name: {"type": "null"}
        for name in (
            "legacy_containment",
            "completed_output",
            "stopped_provider_failure",
            "native_rule_change",
            "context_capacity_receipt_sha256",
            "implementation_artifact_id",
        )
    }
    if title == "StoppedCoderExecutionProof":
        session = {
            "required": ["session_proof"],
            "properties": {
                "session_proof": {
                    "type": "object",
                    "properties": {"proof_scope": {"const": "owned_session_empty"}},
                },
            },
        }
        # Keep the historical v1 wire contract strict while admitting the
        # additive v2 variant for a completed native process with no durable
        # invocation outcome.  The variant is selected by the sealed proof,
        # never inferred from a browser payload.
        # Pydantic defaults an omitted schema_version to v1.  Keep that
        # historical wire shape guarded as v1 in JSON Schema as well; an
        # unqualified `properties` condition would otherwise match neither
        # branch and silently admit an unguarded stop.
        v1_selector = {
            "anyOf": [
                {"not": {"required": ["schema_version"]}},
                {
                    "required": ["schema_version"],
                    "properties": {"schema_version": {"const": "v1"}},
                },
            ]
        }
        extra = [
            {
                "if": v1_selector,
                "then": {
                    "properties": {
                        "capture_stop": {
                            "properties": {
                                "output_present": {"const": False},
                                "cause": {"type": "null"},
                                "process_stop": {
                                    **session,
                                    "properties": {
                                        **session["properties"],
                                        "kind": {"const": "failed"},
                                        "returncode": {"not": {"const": 0}},
                                    },
                                },
                            }
                        }
                    }
                },
            },
            {
                "if": {
                    "required": ["schema_version"],
                    "properties": {"schema_version": {"const": "v2"}},
                },
                "then": {
                    "properties": {
                        "capture_stop": {
                            "properties": {
                                "output_present": {"const": True},
                                "cause": {"type": "null"},
                                "original_error_code": {"type": "null"},
                                "execution_abort_reason": {"type": "null"},
                                "process_stop": {
                                    **session,
                                    "properties": {
                                        **session["properties"],
                                        "kind": {"const": "completed"},
                                        "returncode": {"const": 0},
                                    },
                                },
                            }
                        }
                    }
                },
            },
        ]
    elif title == "BaselineExecutionReservation":
        properties = {
            "original_run_id": {"type": "string"},
            "current_invocation_start_sha256": {"type": "string"},
            "stopped_execution_sha256": {"type": "string"},
            "reservation_already_applied": {"const": False},
            **{
                name: {"type": "null"}
                for name in (
                    "current_invocation_outcome_sha256",
                    "interruption_receipt_sha256",
                    "containment_sha256",
                    "completed_output_sha256",
                    "stopped_provider_failure_sha256",
                    "retry_failure",
                )
            },
        }
        extra = [
            {
                "if": {
                    "required": ["retry_cause"],
                    "properties": {"retry_cause": {"const": "stopped_execution_unknown"}},
                },
                "then": {
                    "required": [
                        "original_run_id",
                        "current_invocation_start_sha256",
                        "stopped_execution_sha256",
                    ],
                    "properties": properties,
                },
            },
            {
                "if": {
                    "required": ["stopped_execution_sha256"],
                    "properties": {"stopped_execution_sha256": {"type": "string"}},
                },
                "then": {"properties": {"retry_cause": {"const": "stopped_execution_unknown"}}},
            },
        ]
    elif title == "BaselineExecutionFacts":
        extra = [
            {
                "if": {
                    "required": ["stopped_execution"],
                    "properties": {"stopped_execution": {"type": "object"}},
                },
                "then": {
                    "required": ["continuation"],
                    "properties": {
                        **nulls,
                        "continuation": {
                            "type": "object",
                            "properties": {"retry_cause": {"const": "stopped_execution_unknown"}},
                        },
                    },
                },
            }
        ]
    elif title in {"ExecutionBaselinePlan", "ExecutionBaselineBinding"}:
        properties = {"input_mode": {"const": "preserve_draft"}}
        required = []
        if title == "ExecutionBaselinePlan":
            properties.update(
                {
                    "conflicted": {"const": False},
                    "facts": {
                        "required": ["stopped_execution"],
                        "properties": {"stopped_execution": {"type": "object"}, **nulls},
                    },
                }
            )
            reverse_if = {
                "properties": {
                    "facts": {
                        "required": ["stopped_execution"],
                        "properties": {"stopped_execution": {"type": "object"}},
                    }
                }
            }
        else:
            required = ["stopped_execution_sha256", "continuation_mode"]
            properties.update(
                {
                    "stopped_execution_sha256": {"type": "string"},
                    "continuation_mode": {"const": "pause"},
                    "authority_source": {"const": "engineering_operator_decision"},
                    **{
                        name: {"type": "null"}
                        for name in (
                            "legacy_containment_sha256",
                            "completed_output_sha256",
                            "stopped_provider_failure_sha256",
                            "context_capacity_receipt_sha256",
                            "service_pause_outcome_sha256",
                            "superseded_implementation_artifact_id",
                        )
                    },
                }
            )
            reverse_if = {
                "required": ["stopped_execution_sha256"],
                "properties": {"stopped_execution_sha256": {"type": "string"}},
            }
        extra = [
            {
                "if": {
                    "required": ["purpose"],
                    "properties": {"purpose": {"const": "stopped_execution_rescue"}},
                },
                "then": {"required": required, "properties": properties},
            },
            {
                "if": reverse_if,
                "then": {
                    "required": ["purpose"],
                    "properties": {"purpose": {"const": "stopped_execution_rescue"}},
                },
            },
        ]
    if extra:
        existing = node.get("allOf", [])
        assert isinstance(existing, list)
        node["allOf"] = [*existing, *(gate for gate in extra if gate not in existing)]


def guards(node: dict[str, object]) -> None:
    if node.get("title") in {"KnowledgePreparationPauseEvidence", "DeliveryResolution"}:
        canonical = json.loads((ROOT / "engineering-wait-resolution.schema.json").read_text())
        inherited = canonical["$defs"][node["title"]].get("allOf", [])
        existing = node.get("allOf", [])
        assert isinstance(existing, list)
        node["allOf"] = [*existing, *(guard for guard in inherited if guard not in existing)]
    title = node.get("title")

    if title == "ProposeExecutionBaselineIntent":
        node["allOf"] = [
            {
                "if": {
                    "required": ["purpose"],
                    "properties": {
                        "purpose": {
                            "enum": [
                                "completed_output_rescue",
                                "stopped_provider_retry",
                                "stopped_failure_retry",
                                "stopped_execution_rescue",
                                "context_capacity_resume",
                                "knowledge_preparation_isolation",
                                "rejected_candidate_rescue",
                            ]
                        }
                    },
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
                    "properties": {
                        "retry_cause": {
                            "enum": ["completed_output_unavailable", "completed_output_rejected"]
                        }
                    },
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
                            "start": {
                                "properties": {
                                    "request": {"properties": {"role": {"const": "coder"}}}
                                }
                            },
                            "result": {
                                "required": ["error"],
                                "properties": {
                                    "status": {"const": "FAILED"},
                                    "artifact": {"type": "null"},
                                    "error": {
                                        "type": "object",
                                        "properties": {
                                            "code": {
                                                "enum": ["WORK_INTERRUPTED", "INVALID_OUTPUT"]
                                            },
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
                                "retry_cause": {
                                    "enum": [
                                        "completed_output_unavailable",
                                        "completed_output_rejected",
                                    ]
                                }
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
        }
        if gate not in existing:
            node["allOf"] = [*existing, gate]

    if title == "BaselineExecutionFacts":
        existing = node.get("allOf", [])
        assert isinstance(existing, list)
        capacity_gate = {
            "if": {
                "required": ["context_capacity_receipt_sha256"],
                "properties": {"context_capacity_receipt_sha256": {"type": "string"}},
            },
            "then": {
                "required": ["continuation"],
                "properties": {
                    "continuation": {
                        "type": "object",
                        "required": ["retry_cause", "reservation_already_applied"],
                        "properties": {
                            "retry_cause": {"const": "uninvoked"},
                            "reservation_already_applied": {"const": True},
                        },
                    },
                    "legacy_containment": {"type": "null"},
                    "completed_output": {"type": "null"},
                    "stopped_provider_failure": {"type": "null"},
                },
            },
        }
        if capacity_gate not in existing:
            existing.append(capacity_gate)
        for cause, code in (
            ("completed_output_unavailable", "WORK_INTERRUPTED"),
            ("completed_output_rejected", "INVALID_OUTPUT"),
        ):
            gate = {
                "if": {
                    "required": ["completed_output"],
                    "properties": {"completed_output": completed_failure_code(code)},
                },
                "then": {
                    "required": ["continuation"],
                    "properties": {
                        "continuation": {
                            "type": "object",
                            "required": ["retry_cause"],
                            "properties": {"retry_cause": {"const": cause}},
                        }
                    },
                },
            }
            existing.append(gate)
        node["allOf"] = existing
    elif title == "ExecutionBaselineBinding":
        existing = node.get("allOf", [])
        assert isinstance(existing, list)
        gate = {
            "if": {
                "required": ["completed_output_sha256"],
                "properties": {"completed_output_sha256": {"type": "string"}},
            },
            "then": {
                "required": ["continuation_mode"],
                "properties": {
                    "purpose": {"enum": ["source_rebind", "completed_output_rescue"]},
                    "continuation_mode": {"const": "pause"},
                    "authority_source": {"const": "engineering_operator_decision"},
                    "legacy_containment_sha256": {"type": "null"},
                    "stopped_provider_failure_sha256": {"type": "null"},
                    "superseded_implementation_artifact_id": {"type": "null"},
                },
            },
        }
        node["allOf"] = [*existing, gate]
    elif title == "BaselineQueueConsumption":
        node["allOf"] = [
            {
                "if": {
                    "required": ["plan"],
                    "properties": {
                        "plan": {
                            "required": ["facts"],
                            "properties": {
                                "facts": {
                                    "required": ["completed_output"],
                                    "properties": {
                                        "completed_output": completed_failure_code("INVALID_OUTPUT")
                                    },
                                }
                            },
                        }
                    },
                },
                "then": {
                    "required": ["binding"],
                    "properties": {
                        "binding": {
                            "required": ["completed_output_sha256", "continuation_mode"],
                            "properties": {
                                "completed_output_sha256": {"type": "string"},
                                "continuation_mode": {"const": "pause"},
                                "authority_source": {"const": "engineering_operator_decision"},
                            },
                        }
                    },
                },
            }
        ]

    # These are independent of the older rescue gates: every regenerated root
    # and embedded definition must retain the permanent-provider boundary.
    extra: list[dict[str, object]] = []
    if title == "StoppedProviderFailureProof":
        extra = [
            {
                "properties": {
                    "outcome": {
                        "properties": {
                            "start": {
                                "properties": {
                                    "request": {"properties": {"role": {"const": "coder"}}}
                                }
                            },
                            "result": {
                                "required": ["error"],
                                "properties": {
                                    "status": {"const": "FAILED"},
                                    "artifact": {"type": "null"},
                                    "error": {
                                        "type": "object",
                                        "properties": {
                                            "code": {"const": "AUTHENTICATION_ERROR"},
                                            "transient": {"const": False},
                                        },
                                    },
                                },
                            },
                        }
                    },
                    "capture_stop": {
                        "properties": {
                            "output_present": {"const": False},
                            "cause": {"type": "null"},
                            "original_error_code": {"enum": [None, "AUTHENTICATION_ERROR"]},
                            "process_stop": {
                                "properties": {
                                    "kind": {"const": "failed"},
                                    "returncode": {"not": {"const": 0}},
                                }
                            },
                        }
                    },
                }
            }
        ]
    elif title == "BaselineExecutionReservation":
        extra = [
            {
                "if": {
                    "required": ["retry_cause"],
                    "properties": {"retry_cause": {"const": "provider_prerequisite_repaired"}},
                },
                "then": {
                    "required": [
                        "original_run_id",
                        "current_invocation_start_sha256",
                        "current_invocation_outcome_sha256",
                        "stopped_provider_failure_sha256",
                    ],
                    "properties": {
                        "original_run_id": {"type": "string"},
                        "current_invocation_start_sha256": {"type": "string"},
                        "current_invocation_outcome_sha256": {"type": "string"},
                        "stopped_provider_failure_sha256": {"type": "string"},
                        "completed_output_sha256": {"type": "null"},
                        "containment_sha256": {"type": "null"},
                        "interruption_receipt_sha256": {"type": "null"},
                        "retry_failure": {"type": "null"},
                        "reservation_already_applied": {"const": False},
                    },
                },
                "else": {"properties": {"stopped_provider_failure_sha256": {"type": "null"}}},
            }
        ]
    elif title == "BaselineExecutionFacts":
        extra = [
            {
                "if": {
                    "required": ["continuation"],
                    "properties": {
                        "continuation": {
                            "type": "object",
                            "required": ["retry_cause"],
                            "properties": {
                                "retry_cause": {"const": "provider_prerequisite_repaired"}
                            },
                        }
                    },
                },
                "then": {
                    "required": ["stopped_provider_failure"],
                    "properties": {
                        "stopped_provider_failure": {"type": "object"},
                        "legacy_containment": {"type": "null"},
                        "completed_output": {"type": "null"},
                        "implementation_artifact_id": {"type": "null"},
                    },
                },
                "else": {"properties": {"stopped_provider_failure": {"type": "null"}}},
            }
        ]
    elif title in {"BaselineOperatorAuthorization", "ExecuteExecutionBaselineIntent"}:
        extra = [
            {
                "if": {
                    "required": ["confirm_provider_prerequisites_repaired"],
                    "properties": {"confirm_provider_prerequisites_repaired": {"const": True}},
                },
                "then": {
                    "required": ["continuation_mode"],
                    "properties": {
                        "continuation_mode": {"const": "pause"},
                        "confirm_legacy_containment": {"type": "null"},
                        "confirm_local_execution_stopped": {"type": "null"},
                    },
                },
            }
        ]
    elif title == "ExecutionBaselinePlan":
        extra = [
            {
                "if": {
                    "required": ["purpose"],
                    "properties": {"purpose": {"const": "stopped_provider_retry"}},
                },
                "then": {
                    "properties": {
                        "input_mode": {"const": "preserve_draft"},
                        "conflicted": {"const": False},
                        "facts": {
                            "required": ["stopped_provider_failure"],
                            "properties": {
                                "stopped_provider_failure": {"type": "object"},
                                "legacy_containment": {"type": "null"},
                                "completed_output": {"type": "null"},
                                "native_rule_change": {"type": "null"},
                                "implementation_artifact_id": {"type": "null"},
                            },
                        },
                    }
                },
            }
        ]
    elif title == "ExecutionBaselineBinding":
        extra = [
            {
                "if": {
                    "required": ["purpose"],
                    "properties": {"purpose": {"const": "stopped_provider_retry"}},
                },
                "then": {
                    "required": ["stopped_provider_failure_sha256", "continuation_mode"],
                    "properties": {
                        "input_mode": {"const": "preserve_draft"},
                        "stopped_provider_failure_sha256": {"type": "string"},
                    },
                },
            },
            {
                "if": {
                    "required": ["stopped_provider_failure_sha256"],
                    "properties": {"stopped_provider_failure_sha256": {"type": "string"}},
                },
                "then": {
                    "required": ["continuation_mode"],
                    "properties": {
                        "purpose": {"enum": ["source_rebind", "stopped_provider_retry"]},
                        "continuation_mode": {"const": "pause"},
                        "authority_source": {"const": "engineering_operator_decision"},
                        "completed_output_sha256": {"type": "null"},
                        "legacy_containment_sha256": {"type": "null"},
                        "superseded_implementation_artifact_id": {"type": "null"},
                    },
                },
            },
        ]
    elif title == "DeliveryWaitInvestigation":
        canonical = json.loads((ROOT / "engineering-wait-resolution.schema.json").read_text())
        old = canonical["$defs"]["DeliveryWaitInvestigation"].get("allOf", [])
        existing = node.get("allOf", [])
        assert isinstance(existing, list)
        node["allOf"] = [*existing, *(guard for guard in old if guard not in existing)]
        extra = [
            {
                "if": {
                    "required": ["provider_failure_code"],
                    "properties": {"provider_failure_code": {"type": "string"}},
                },
                "then": {
                    "required": [
                        "invocation_start_sha256",
                        "invocation_outcome_sha256",
                        "original_run_id",
                    ],
                    "properties": {
                        "invocation_start_sha256": {"type": "string"},
                        "invocation_outcome_sha256": {"type": "string"},
                        "original_run_id": {"type": "string"},
                        "permitted_resolutions": {"maxItems": 0},
                        "disposition": {
                            "properties": {"facts": {"properties": {"role": {"const": "coder"}}}}
                        },
                    },
                },
            }
        ]
    if extra:
        existing = node.get("allOf", [])
        assert isinstance(existing, list)
        node["allOf"] = [*existing, *(guard for guard in extra if guard not in existing)]

    stopped_guards(node)
    stopped_failure_guards(node)
    knowledge_isolation_guards(node)
    rejected_candidate_guards(node)

    # Runtime-only capacity recovery is an independent purpose. These local
    # wire gates supplement the complete plan/binding/queue association in code.
    if title in {"ExecutionBaselinePlan", "ExecutionBaselineBinding"}:
        properties = {"input_mode": {"const": "preserve_draft"}}
        required = []
        if title == "ExecutionBaselinePlan":
            properties.update(
                {
                    "conflicted": {"const": False},
                    "facts": {
                        "required": ["context_capacity_receipt_sha256", "continuation"],
                        "properties": {
                            "context_capacity_receipt_sha256": {"type": "string"},
                            "legacy_containment": {"type": "null"},
                            "completed_output": {"type": "null"},
                            "stopped_provider_failure": {"type": "null"},
                            "native_rule_change": {"type": "null"},
                            "continuation": {
                                "type": "object",
                                "required": ["retry_cause", "reservation_already_applied"],
                                "properties": {
                                    "retry_cause": {"const": "uninvoked"},
                                    "reservation_already_applied": {"const": True},
                                },
                            },
                        },
                    },
                }
            )
        else:
            required = ["context_capacity_receipt_sha256", "continuation_mode"]
            properties.update(
                {
                    "context_capacity_receipt_sha256": {"type": "string"},
                    "continuation_mode": {"const": "pause"},
                    "authority_source": {"const": "engineering_operator_decision"},
                    "legacy_containment_sha256": {"type": "null"},
                    "completed_output_sha256": {"type": "null"},
                    "stopped_provider_failure_sha256": {"type": "null"},
                    "superseded_implementation_artifact_id": {"type": "null"},
                    "superseded_progress_artifact_id": {"type": "null"},
                }
            )
        gate = {
            "if": {
                "required": ["purpose"],
                "properties": {"purpose": {"const": "context_capacity_resume"}},
            },
            "then": {"required": required, "properties": properties},
        }
        existing = node.get("allOf", [])
        assert isinstance(existing, list)
        if gate not in existing:
            existing.append(gate)
        if title == "ExecutionBaselineBinding":
            digest_gate = {
                "if": {
                    "required": ["context_capacity_receipt_sha256"],
                    "properties": {"context_capacity_receipt_sha256": {"type": "string"}},
                },
                "then": {
                    "required": ["purpose"],
                    "properties": {"purpose": {"const": "context_capacity_resume"}},
                },
            }
            if digest_gate not in existing:
                existing.append(digest_gate)
        node["allOf"] = existing


def stopped_failure_guards(node: dict[str, object]) -> None:
    """Independent unknown failure gates, never widening the AUTH proof family."""
    title = node.get("title")
    extra: list[dict[str, object]] = []
    facts_nulls = {
        name: {"type": "null"}
        for name in (
            "legacy_containment",
            "completed_output",
            "stopped_provider_failure",
            "stopped_execution",
            "native_rule_change",
            "context_capacity_receipt_sha256",
            "implementation_artifact_id",
        )
    }
    if title == "StoppedFailureProof":
        extra = [
            {
                "properties": {
                    "outcome": {
                        "properties": {
                            "start": {
                                "properties": {
                                    "request": {"properties": {"role": {"const": "coder"}}}
                                }
                            },
                            "result": {
                                "required": ["error"],
                                "properties": {
                                    "status": {"const": "FAILED"},
                                    "artifact": {"type": "null"},
                                    "error": {
                                        "type": "object",
                                        "properties": {
                                            "code": {"const": "PROVIDER_UNAVAILABLE"},
                                            "transient": {"const": False},
                                        },
                                    },
                                },
                            },
                        }
                    },
                    "capture_stop": {
                        "properties": {
                            "output_present": {"const": False},
                            "cause": {"type": "null"},
                            "original_error_code": {"enum": [None, "PROVIDER_UNAVAILABLE"]},
                            "execution_abort_reason": {"type": "null"},
                            "process_stop": {
                                "required": ["session_proof"],
                                "properties": {
                                    "kind": {"const": "failed"},
                                    "returncode": {"type": "integer", "not": {"const": 0}},
                                    "session_proof": {
                                        "type": "object",
                                        "properties": {
                                            "proof_scope": {"const": "owned_session_empty"},
                                        },
                                    },
                                },
                            },
                        }
                    },
                }
            }
        ]
    elif title == "BaselineExecutionReservation":
        extra = [
            {
                "if": {
                    "required": ["retry_cause"],
                    "properties": {"retry_cause": {"const": "stopped_failure_retry"}},
                },
                "then": {
                    "required": [
                        "original_run_id",
                        "current_invocation_start_sha256",
                        "current_invocation_outcome_sha256",
                        "stopped_failure_sha256",
                    ],
                    "properties": {
                        **{
                            name: {"type": "string"}
                            for name in (
                                "original_run_id",
                                "current_invocation_start_sha256",
                                "current_invocation_outcome_sha256",
                                "stopped_failure_sha256",
                            )
                        },
                        **{
                            name: {"type": "null"}
                            for name in (
                                "containment_sha256",
                                "completed_output_sha256",
                                "stopped_provider_failure_sha256",
                                "stopped_execution_sha256",
                                "interruption_receipt_sha256",
                                "retry_failure",
                            )
                        },
                        "reservation_already_applied": {"const": False},
                    },
                },
                "else": {"properties": {"stopped_failure_sha256": {"type": "null"}}},
            }
        ]
    elif title == "BaselineExecutionFacts":
        extra = [
            {
                "if": {
                    "required": ["continuation"],
                    "properties": {
                        "continuation": {
                            "type": "object",
                            "required": ["retry_cause"],
                            "properties": {"retry_cause": {"const": "stopped_failure_retry"}},
                        }
                    },
                },
                "then": {
                    "required": ["stopped_failure"],
                    "properties": {"stopped_failure": {"type": "object"}, **facts_nulls},
                },
                "else": {"properties": {"stopped_failure": {"type": "null"}}},
            }
        ]
    elif title in {"BaselineOperatorAuthorization", "ExecuteExecutionBaselineIntent"}:
        extra = [
            {
                "if": {
                    "required": ["confirm_stopped_failure_retry"],
                    "properties": {"confirm_stopped_failure_retry": {"const": True}},
                },
                "then": {
                    "required": ["continuation_mode"],
                    "properties": {
                        "continuation_mode": {"const": "pause"},
                        **{
                            name: {"type": "null"}
                            for name in (
                                "confirm_provider_prerequisites_repaired",
                                "confirm_legacy_containment",
                                "confirm_local_execution_stopped",
                                "approved_native_rule_change_sha256",
                            )
                        },
                    },
                },
            }
        ]
    elif title == "ProposeExecutionBaselineIntent":
        extra = [
            {
                "if": {
                    "required": ["purpose"],
                    "properties": {"purpose": {"const": "stopped_failure_retry"}},
                },
                "then": {
                    "properties": {
                        "input_mode": {"const": "preserve_draft"},
                        "target_base_ref": {"type": "null"},
                    }
                },
            }
        ]
    elif title == "ExecutionBaselinePlan":
        extra = [
            {
                "if": {
                    "required": ["purpose"],
                    "properties": {"purpose": {"const": "stopped_failure_retry"}},
                },
                "then": {
                    "properties": {
                        "input_mode": {"const": "preserve_draft"},
                        "conflicted": {"const": False},
                        "facts": {
                            "required": ["stopped_failure"],
                            "properties": {"stopped_failure": {"type": "object"}, **facts_nulls},
                        },
                    }
                },
                "else": {
                    "properties": {"facts": {"properties": {"stopped_failure": {"type": "null"}}}}
                },
            }
        ]
    elif title == "ExecutionBaselineBinding":
        extra = [
            {
                "if": {
                    "required": ["purpose"],
                    "properties": {"purpose": {"const": "stopped_failure_retry"}},
                },
                "then": {
                    "required": ["stopped_failure_sha256", "continuation_mode"],
                    "properties": {
                        "stopped_failure_sha256": {"type": "string"},
                        "input_mode": {"const": "preserve_draft"},
                        "continuation_mode": {"const": "pause"},
                        "authority_source": {"const": "engineering_operator_decision"},
                        **{
                            name: {"type": "null"}
                            for name in (
                                "legacy_containment_sha256",
                                "completed_output_sha256",
                                "stopped_provider_failure_sha256",
                                "stopped_execution_sha256",
                                "context_capacity_receipt_sha256",
                                "service_pause_outcome_sha256",
                                "superseded_implementation_artifact_id",
                            )
                        },
                    },
                },
                "else": {"properties": {"stopped_failure_sha256": {"type": "null"}}},
            }
        ]
    existing = node.get("allOf", [])
    assert isinstance(existing, list)
    if extra:
        node["allOf"] = [*existing, *(guard for guard in extra if guard not in existing)]


def knowledge_isolation_guards(node: dict[str, object]) -> None:
    """A current engineering containment decision retains unknown historical transport."""
    title = node.get("title")
    guards_to_add = []
    if title == "BaselineExecutionReservation":
        guards_to_add.append(
            {
                "if": {"properties": {"retry_cause": {"const": "knowledge_isolation"}}},
                "then": {
                    "required": ["knowledge_isolation_sha256"],
                    "properties": {
                        "knowledge_isolation_sha256": {"type": "string"},
                        "reservation_already_applied": {"const": False},
                        **{
                            name: {"type": "null"}
                            for name in (
                                "original_run_id",
                                "current_invocation_start_sha256",
                                "current_invocation_outcome_sha256",
                                "retry_failure",
                                "interruption_receipt_sha256",
                                "containment_sha256",
                                "stopped_execution_sha256",
                                "completed_output_sha256",
                                "stopped_provider_failure_sha256",
                                "stopped_failure_sha256",
                            )
                        },
                    },
                },
                "else": {"properties": {"knowledge_isolation_sha256": {"type": "null"}}},
            }
        )
    elif title == "BaselineExecutionFacts":
        guards_to_add.append(
            {
                "if": {
                    "required": ["continuation"],
                    "properties": {
                        "continuation": {
                            "type": "object",
                            "required": ["retry_cause"],
                            "properties": {"retry_cause": {"const": "knowledge_isolation"}},
                        }
                    },
                },
                "then": {
                    "required": ["knowledge_isolation"],
                    "properties": {"knowledge_isolation": {"type": "object"}},
                },
            }
        )
        guards_to_add.append(
            {
                "if": {
                    "required": ["knowledge_isolation"],
                    "properties": {"knowledge_isolation": {"type": "object"}},
                },
                "then": {
                    "required": ["continuation"],
                    "properties": {
                        "continuation": {
                            "type": "object",
                            "properties": {
                                "retry_cause": {"const": "knowledge_isolation"},
                            },
                        },
                        **{
                            name: {"type": "null"}
                            for name in (
                                "legacy_containment",
                                "stopped_execution",
                                "completed_output",
                                "stopped_provider_failure",
                                "stopped_failure",
                                "context_capacity_receipt_sha256",
                                "native_rule_change",
                                "implementation_artifact_id",
                            )
                        },
                    },
                },
            }
        )
    elif title in {"BaselineOperatorAuthorization", "ExecuteExecutionBaselineIntent"}:
        guards_to_add.append(
            {
                "if": {
                    "required": ["confirm_current_knowledge_execution_isolated"],
                    "properties": {"confirm_current_knowledge_execution_isolated": {"const": True}},
                },
                "then": {
                    "required": ["continuation_mode"],
                    "properties": {
                        "continuation_mode": {"const": "pause"},
                        **{
                            name: {"type": "null"}
                            for name in (
                                "confirm_legacy_containment",
                                "confirm_local_execution_stopped",
                                "confirm_provider_prerequisites_repaired",
                                "confirm_stopped_failure_retry",
                                "approved_native_rule_change_sha256",
                            )
                        },
                    },
                },
            }
        )
    elif title in {"ExecutionBaselinePlan", "ExecutionBaselineBinding"}:
        shared: dict[str, object] = {"input_mode": {"const": "preserve_draft"}}
        otherwise: dict[str, object]
        if title == "ExecutionBaselinePlan":
            shared.update(
                {
                    "conflicted": {"const": False},
                    "facts": {
                        "required": ["knowledge_isolation"],
                        "properties": {
                            "knowledge_isolation": {"type": "object"},
                        },
                    },
                }
            )
            required = ["input_mode", "facts"]
            otherwise = {"facts": {"properties": {"knowledge_isolation": {"type": "null"}}}}
        else:
            shared.update(
                {
                    "authority_source": {"const": "engineering_operator_decision"},
                    "continuation_mode": {"const": "pause"},
                    "knowledge_isolation_sha256": {"type": "string"},
                    "superseded_progress_artifact_id": {"type": "null"},
                    "superseded_implementation_artifact_id": {"type": "null"},
                    **{
                        name: {"type": "null"}
                        for name in (
                            "legacy_containment_sha256",
                            "stopped_execution_sha256",
                            "completed_output_sha256",
                            "stopped_provider_failure_sha256",
                            "stopped_failure_sha256",
                            "context_capacity_receipt_sha256",
                            "service_pause_outcome_sha256",
                        )
                    },
                }
            )
            required = ["input_mode", "knowledge_isolation_sha256", "continuation_mode"]
            otherwise = {"knowledge_isolation_sha256": {"type": "null"}}
        guards_to_add.append(
            {
                "if": {
                    "required": ["purpose"],
                    "properties": {"purpose": {"const": "knowledge_preparation_isolation"}},
                },
                "then": {"required": required, "properties": shared},
                "else": {"properties": otherwise},
            }
        )
    existing = node.get("allOf", [])
    assert isinstance(existing, list)
    if guards_to_add:
        conditions = [guard["if"] for guard in guards_to_add]
        if title in {"ExecutionBaselinePlan", "ExecutionBaselineBinding"}:
            # Old published graphs treated an omitted default purpose as isolation.
            conditions.append(
                {"properties": {"purpose": {"const": "knowledge_preparation_isolation"}}}
            )
        # These generated gates replace prior variants of this new proof family;
        # unrelated policy gates keep their complete existing bytes and order.
        retained = [guard for guard in existing if guard.get("if") not in conditions]
        node["allOf"] = [*retained, *guards_to_add]


def rejected_candidate_guards(node: dict[str, object]) -> None:
    """Keep unsupported successful candidates separate from every old rescue family."""
    title = node.get("title")
    purpose = {
        "required": ["purpose"],
        "properties": {"purpose": {"const": "rejected_candidate_rescue"}},
    }
    facts_nulls = {
        name: {"type": "null"}
        for name in (
            "legacy_containment",
            "completed_output",
            "stopped_provider_failure",
            "stopped_failure",
            "stopped_execution",
            "knowledge_isolation",
            "native_rule_change",
            "context_capacity_receipt_sha256",
            "implementation_artifact_id",
        )
    }
    binding_nulls = {
        name: {"type": "null"}
        for name in (
            "legacy_containment_sha256",
            "completed_output_sha256",
            "stopped_provider_failure_sha256",
            "stopped_failure_sha256",
            "stopped_execution_sha256",
            "knowledge_isolation_sha256",
            "context_capacity_receipt_sha256",
            "service_pause_outcome_sha256",
            "superseded_implementation_artifact_id",
        )
    }
    cause = {
        "required": ["retry_cause"],
        "properties": {"retry_cause": {"const": "rejected_candidate_output"}},
    }
    gates: list[dict[str, object]] = []
    if title == "RejectedCandidateOutputProof":
        gates = [
            {
                "properties": {
                    "task": {"properties": {"status": {"const": "IMPLEMENTING"}}},
                    "outcome": {
                        "properties": {
                            "service_pause": {"type": "null"},
                            "start": {
                                "properties": {
                                    "request": {"properties": {"role": {"const": "coder"}}}
                                }
                            },
                            "result": {
                                "required": ["artifact"],
                                "properties": {
                                    "status": {"const": "SUCCEEDED"},
                                    "error": {"type": "null"},
                                    "artifact": {
                                        "type": "object",
                                        "required": ["kind", "schema_version"],
                                        "properties": {
                                            "kind": {"const": "implementation-report"},
                                            "schema_version": {"not": {"const": "v0.1"}},
                                            "content": {
                                                "properties": {"blocked_reason": {"type": "null"}}
                                            },
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
                            "execution_abort_reason": {"type": "null"},
                            "process_stop": {
                                "required": ["session_proof"],
                                "properties": {
                                    "kind": {"const": "completed"},
                                    "returncode": {"const": 0},
                                    "session_proof": {
                                        "type": "object",
                                        "properties": {
                                            "proof_scope": {"const": "owned_session_empty"}
                                        },
                                    },
                                },
                            },
                        }
                    },
                }
            }
        ]
    elif title == "BaselineExecutionReservation":
        required = [
            "rejected_candidate_output_sha256",
            "original_run_id",
            "current_invocation_start_sha256",
            "current_invocation_outcome_sha256",
        ]
        gates = [
            {
                "if": cause,
                "then": {
                    "required": required,
                    "properties": {
                        **{name: {"type": "string"} for name in required},
                        **{
                            name: {"type": "null"}
                            for name in (
                                "containment_sha256",
                                "completed_output_sha256",
                                "stopped_provider_failure_sha256",
                                "stopped_failure_sha256",
                                "stopped_execution_sha256",
                                "knowledge_isolation_sha256",
                                "interruption_receipt_sha256",
                                "retry_failure",
                            )
                        },
                        "reservation_already_applied": {"const": False},
                    },
                },
                "else": {"properties": {"rejected_candidate_output_sha256": {"type": "null"}}},
            }
        ]
    elif title == "BaselineExecutionFacts":
        gates = [
            {
                "if": {
                    "required": ["continuation"],
                    "properties": {"continuation": {"type": "object", **cause}},
                },
                "then": {
                    "required": ["rejected_candidate_output"],
                    "properties": {
                        "rejected_candidate_output": {"type": "object"},
                        **facts_nulls,
                    },
                },
                "else": {"properties": {"rejected_candidate_output": {"type": "null"}}},
            },
            {
                "if": {
                    "required": ["rejected_candidate_output"],
                    "properties": {"rejected_candidate_output": {"type": "object"}},
                },
                "then": {
                    "required": ["continuation"],
                    "properties": {"continuation": {"type": "object", **cause}, **facts_nulls},
                },
            },
        ]
    elif title == "ExecutionBaselinePlan":
        gates = [
            {
                "if": purpose,
                "then": {
                    "properties": {
                        "input_mode": {"const": "preserve_draft"},
                        "conflicted": {"const": False},
                        "facts": {
                            "required": ["rejected_candidate_output"],
                            "properties": {
                                "rejected_candidate_output": {"type": "object"},
                                **facts_nulls,
                            },
                        },
                    }
                },
                "else": {
                    "properties": {
                        "facts": {"properties": {"rejected_candidate_output": {"type": "null"}}}
                    }
                },
            }
        ]
    elif title == "ExecutionBaselineBinding":
        gates = [
            {
                "if": purpose,
                "then": {
                    "required": ["rejected_candidate_output_sha256", "continuation_mode"],
                    "properties": {
                        "rejected_candidate_output_sha256": {"type": "string"},
                        "continuation_mode": {"const": "pause"},
                        "authority_source": {"const": "engineering_operator_decision"},
                        "input_mode": {"const": "preserve_draft"},
                        **binding_nulls,
                    },
                },
                "else": {"properties": {"rejected_candidate_output_sha256": {"type": "null"}}},
            }
        ]
    elif title == "BaselineQueueConsumption":
        gates = [
            {
                "if": {"required": ["plan"], "properties": {"plan": purpose}},
                "then": {
                    "properties": {
                        "binding": {
                            "required": [
                                "purpose",
                                "rejected_candidate_output_sha256",
                                "continuation_mode",
                            ],
                            "properties": {
                                "purpose": {"const": "rejected_candidate_rescue"},
                                "rejected_candidate_output_sha256": {"type": "string"},
                                "continuation_mode": {"const": "pause"},
                                "authority_source": {"const": "engineering_operator_decision"},
                                **binding_nulls,
                            },
                        }
                    }
                },
            }
        ]
    existing = node.get("allOf", [])
    assert isinstance(existing, list)
    if gates:
        node["allOf"] = [*existing, *(gate for gate in gates if gate not in existing)]


if __name__ == "__main__":
    main()
