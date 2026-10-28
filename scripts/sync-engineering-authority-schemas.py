"""Regenerate the organization engineering policy/admission wire contracts."""

import json
import sys
from pathlib import Path
from runpy import run_path
from typing import Annotated

from pydantic import Field, TypeAdapter

from ai_software_engineer.domain.delivery_disposition import DeliveryFailureFacts
from ai_software_engineer.domain.delivery_resolution import (
    RESULT_REPLAY_REJECTED_CLASSIFICATIONS,
    DeliveryResolution,
    DeliveryWaitHandling,
    DeliveryWaitInvestigation,
    EngineeringDispositionRecord,
)
from ai_software_engineer.domain.engineering_authority import (
    EngineeringAdmission,
    EngineeringCapability,
    EngineeringPolicy,
)
from ai_software_engineer.manager.rejected_output_checkpoint import RejectedCoderOutputCheckpoint

if sys.argv[1:] not in ([], ["--wait-only"]):
    raise SystemExit("usage: sync-engineering-authority-schemas.py [--wait-only]")
wait_only = sys.argv[1:] == ["--wait-only"]

schema = TypeAdapter(
    Annotated[EngineeringPolicy | EngineeringAdmission, Field(discriminator="kind")]
).json_schema()
schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
schema["$id"] = "https://ai-software-engineer.local/schemas/engineering-authority.schema.json"
if not wait_only:
    (Path(__file__).resolve().parents[1] / "schemas/engineering-authority.schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

resolution_schema = TypeAdapter(
    Annotated[
        DeliveryWaitInvestigation
        | DeliveryResolution
        | DeliveryWaitHandling
        | EngineeringDispositionRecord,
        Field(discriminator="kind"),
    ]
).json_schema()
resolution_schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
resolution_schema["$id"] = (
    "https://ai-software-engineer.local/schemas/engineering-wait-resolution.schema.json"
)
resolution_schema["$defs"]["DeliveryResolution"]["allOf"] = [
    {
        "if": {
            "required": ["retry_cause"],
            "properties": {"retry_cause": {"const": "service_pause"}},
        },
        "then": {
            "required": ["verifier_pause"],
            "properties": {
                "verifier_pause": {
                    "type": "object",
                    "properties": {
                        "request": {"properties": {"role": {"enum": ["qa", "reviewer"]}}}
                    },
                }
            },
        },
        "else": {"properties": {"verifier_pause": {"type": "null"}}},
    },
    {
        "if": {
            "properties": {"authorization_source": {"const": "organization_engineering_policy"}},
            "required": ["authorization_source"],
        },
        "then": {
            "required": ["engineering_admission"],
            "properties": {
                "engineering_admission": {"type": "object"},
                "operator_principal": {"type": "null"},
            },
        },
        "else": {
            "required": ["operator_principal"],
            "properties": {
                "operator_principal": {"type": "object"},
                "engineering_admission": {"type": "null"},
            },
        },
    },
    {
        "if": {"properties": {"resolution_kind": {"const": "RETRY_FROM_CHECKPOINT"}}},
        "then": {
            "required": ["retry_cause"],
            "properties": {"retry_cause": {"type": "string"}},
        },
        "else": {"properties": {"retry_cause": {"type": "null"}}},
    },
    {
        "if": {
            "required": ["retry_cause"],
            "properties": {
                "retry_cause": {"const": "provider_transient"},
            },
        },
        "then": {
            "required": ["retry_failure"],
            "properties": {
                "retry_failure": {"type": "object"},
            },
        },
        "else": {"properties": {"retry_failure": {"type": "null"}}},
    },
    {
        "if": {"properties": {"resolution_kind": {"const": "REPLAY_RECORDED_RESULT"}}},
        "then": {
            "required": ["original_authority"],
            "properties": {
                "original_authority": {"type": "object"},
            },
        },
        "else": {"properties": {"original_authority": {"type": "null"}}},
    },
    {
        "if": {"properties": {"resolution_kind": {"const": "REVERIFY_CANDIDATE"}}},
        "then": {
            "required": ["verification_retry"],
            "properties": {"verification_retry": {"type": "object"}},
        },
        "else": {"properties": {"verification_retry": {"type": "null"}}},
    },
    {
        "if": {"properties": {"resolution_kind": {"const": "RETRY_VERIFIER_PREPARATION"}}},
        "then": {
            "required": ["verifier_preparation"],
            "properties": {
                "verifier_preparation": {
                    "type": "object",
                    "properties": {"native_execution_state": {"const": "FINISHED"}},
                }
            },
        },
        "else": {
            "if": {"properties": {"resolution_kind": {"const": "RESUME_UNINVOKED"}}},
            "then": {
                "properties": {
                    "verifier_preparation": {
                        "allOf": [
                            {
                                "if": {
                                    "required": ["context_capacity_receipt_sha256"],
                                    "properties": {
                                        "context_capacity_receipt_sha256": {"type": "string"}
                                    },
                                },
                                "then": {
                                    "properties": {
                                        "native_execution_state": {
                                            "enum": ["NOT_STARTED", "FINISHED"]
                                        }
                                    }
                                },
                                "else": {
                                    "properties": {
                                        "native_execution_state": {"const": "NOT_STARTED"}
                                    }
                                },
                            }
                        ]
                    }
                }
            },
            "else": {
                "if": {"properties": {"resolution_kind": {"const": "STATIC_QA_MISSING_ENTRY"}}},
                "then": {
                    "required": ["verifier_preparation", "static_qa_missing_entry"],
                    "properties": {
                        "verifier_preparation": {
                            "type": "object",
                            "properties": {"native_execution_state": {"const": "NOT_STARTED"}},
                        },
                        "static_qa_missing_entry": {"type": "object"},
                    },
                },
                "else": {"properties": {"verifier_preparation": {"type": "null"}}},
            },
        },
    },
    {
        "if": {
            "required": ["resolution_kind"],
            "properties": {"resolution_kind": {"const": "RETRY_KNOWLEDGE_PREPARATION"}},
        },
        "then": {
            "required": ["knowledge_preparation"],
            "properties": {"knowledge_preparation": {"type": "object"}},
        },
        "else": {"properties": {"knowledge_preparation": {"type": "null"}}},
    },
    {
        "if": {
            "required": ["resolution_kind"],
            "properties": {"resolution_kind": {"const": "RETRY_REJECTED_CODER_OUTPUT"}},
        },
        "then": {
            "required": ["rejected_output"],
            "properties": {"rejected_output": {"type": "object"}},
        },
        "else": {"properties": {"rejected_output": {"type": "null"}}},
    },
]
resolution_schema["$defs"]["DeliveryResolution"]["allOf"].append(
    {
        "if": {
            "required": ["resolution_kind"],
            "properties": {"resolution_kind": {"const": "RETRY_REJECTED_KNOWLEDGE_PREPARATION"}},
        },
        "then": {
            "required": ["rejected_knowledge"],
            "properties": {"rejected_knowledge": {"type": "object"}},
        },
        "else": {"properties": {"rejected_knowledge": {"type": "null"}}},
    }
)
resolution_schema["$defs"]["DeliveryResolution"]["allOf"].append(
    {
        "if": {
            "required": ["resolution_kind"],
            "properties": {"resolution_kind": {"const": "RETRY_REJECTED_WORKSPACE_ADMISSION"}},
        },
        "then": {
            "required": ["rejected_workspace_admission"],
            "properties": {"rejected_workspace_admission": {"type": "object"}},
        },
        "else": {"properties": {"rejected_workspace_admission": {"type": "null"}}},
    }
)
resolution_schema["$defs"]["DeliveryWaitHandling"]["allOf"] = [
    {
        "if": {
            "required": ["budget_settlement_sha256"],
            "properties": {"budget_settlement_sha256": {"type": "string"}},
        },
        "then": {
            "properties": {
                "status": {"const": "BUDGET_EXHAUSTED"},
                "resolution": {"type": "null"},
                "collection_failed": {"const": False},
                "collection_failure": {"type": "null"},
                "investigation": {"properties": {"permitted_resolutions": {"maxItems": 0}}},
            },
        },
    },
    {
        "if": {"properties": {"status": {"const": "RESOLVED"}}},
        "then": {"required": ["resolution"], "properties": {"resolution": {"type": "object"}}},
        "else": {"properties": {"resolution": {"type": "null"}}},
    },
    {
        "if": {
            "required": ["collection_failure"],
            "properties": {"collection_failure": {"type": "string"}},
        },
        "then": {
            "required": ["collection_failed"],
            "properties": {
                "collection_failed": {"const": True},
                "status": {"const": "PLATFORM_ATTENTION"},
                "resolution": {"type": "null"},
                "investigation": {
                    "required": ["process_stop_sha256", "missing"],
                    "properties": {
                        "process_stop_sha256": {"type": "string"},
                        "missing": {
                            "contains": {"const": "CHECKPOINT_UNAVAILABLE"},
                            "not": {"contains": {"const": "STOP_UNRECORDED"}},
                        },
                        "permitted_resolutions": {"maxItems": 0},
                    },
                },
            },
        },
    },
]
resolution_schema["$defs"]["DeliveryWaitInvestigation"]["allOf"] = [
    {
        "if": {"required": ["missing"], "properties": {"missing": {"minItems": 1}}},
        "then": {"properties": {"permitted_resolutions": {"maxItems": 0}}},
    },
    {
        "if": {
            "properties": {
                "disposition": {
                    "properties": {
                        "facts": {
                            "properties": {
                                "classification": {
                                    "enum": sorted(RESULT_REPLAY_REJECTED_CLASSIFICATIONS)
                                }
                            }
                        }
                    }
                }
            }
        },
        "then": {
            "properties": {
                "permitted_resolutions": {"not": {"contains": {"const": "REPLAY_RECORDED_RESULT"}}}
            }
        },
    },
    {
        "if": {
            "required": ["permitted_resolutions"],
            "properties": {
                "permitted_resolutions": {"contains": {"const": "RETRY_KNOWLEDGE_PREPARATION"}}
            },
        },
        "then": {
            "required": ["knowledge_preparation"],
            "properties": {"knowledge_preparation": {"type": "object"}},
        },
    },
    {
        "if": {
            "required": ["knowledge_preparation"],
            "properties": {"knowledge_preparation": {"type": "object"}},
        },
        "then": {
            "required": ["original_run_id"],
            "properties": {
                "original_run_id": {"type": "string"},
                "invocation_start_sha256": {"type": "null"},
                "invocation_outcome_sha256": {"type": "null"},
                "original_authority": {"type": "null"},
                "verification_retry": {"type": "null"},
                "verifier_preparation": {"type": "null"},
                "permitted_resolutions": {
                    "maxItems": 1,
                    "items": {"const": "RETRY_KNOWLEDGE_PREPARATION"},
                },
                "disposition": {
                    "properties": {
                        "facts": {
                            "properties": {
                                "classification": {"const": "KNOWLEDGE_PREPARATION_LIMIT"},
                                "evidence_ids": {
                                    "minItems": 1,
                                    "maxItems": 1,
                                    "items": {"pattern": "^knowledge-preparation://[a-f0-9]{64}$"},
                                },
                            }
                        }
                    }
                },
            },
        },
    },
]
resolution_schema["$defs"]["DeliveryWaitInvestigation"]["allOf"] += [
    {
        "if": {
            "required": ["permitted_resolutions"],
            "properties": {
                "permitted_resolutions": {"contains": {"const": "STATIC_QA_MISSING_ENTRY"}}
            },
        },
        "then": {
            "required": ["static_qa_missing_entry", "verifier_preparation"],
            "properties": {
                "static_qa_missing_entry": {"type": "object"},
                "verifier_preparation": {
                    "type": "object",
                    "properties": {"native_execution_state": {"const": "NOT_STARTED"}},
                },
            },
        },
    },
    {
        "if": {
            "required": ["static_qa_missing_entry"],
            "properties": {"static_qa_missing_entry": {"type": "object"}},
        },
        "then": {
            "required": ["verifier_preparation", "original_run_id"],
            "properties": {
                "verifier_preparation": {
                    "type": "object",
                    "properties": {"native_execution_state": {"const": "NOT_STARTED"}},
                },
                "invocation_start_sha256": {"type": "null"},
                "invocation_outcome_sha256": {"type": "null"},
                "original_authority": {"type": "null"},
                "verification_retry": {"type": "null"},
                "knowledge_preparation": {"type": "null"},
                "rejected_output": {"type": "null"},
                "retry_cause": {"type": "null"},
                "process_stop_sha256": {"type": "null"},
                "permitted_resolutions": {
                    "minItems": 1,
                    "maxItems": 1,
                    "items": {"const": "STATIC_QA_MISSING_ENTRY"},
                },
                "disposition": {
                    "properties": {
                        "facts": {
                            "properties": {
                                "role": {"const": "qa"},
                                "classification": {
                                    "enum": ["ENVIRONMENT_UNAVAILABLE", "ENGINEERING_AUTHORIZATION"]
                                },
                                "evidence_ids": {
                                    "minItems": 1,
                                    "maxItems": 1,
                                    "items": {"pattern": "^verifier-preparation://[a-f0-9]{64}$"},
                                },
                            }
                        }
                    }
                },
            },
        },
        "else": {"properties": {"static_qa_missing_entry": {"type": "null"}}},
    },
]
resolution_schema["$defs"]["KnowledgePreparationRetryEvidence"]["allOf"] = [
    {
        "properties": {
            "role": {"enum": ["coder", "qa", "reviewer"]},
            "execution_record_sha256s": {"uniqueItems": True},
        }
    }
]
resolution_schema["$defs"]["DeliveryWaitInvestigation"]["allOf"] += [
    {
        "if": {
            "required": ["permitted_resolutions"],
            "properties": {
                "permitted_resolutions": {"contains": {"const": "RETRY_REJECTED_CODER_OUTPUT"}}
            },
        },
        "then": {
            "required": ["rejected_output"],
            "properties": {"rejected_output": {"type": "object"}},
        },
    },
    {
        "if": {
            "required": ["rejected_output"],
            "properties": {"rejected_output": {"type": "object"}},
        },
        "then": {
            "required": [
                "original_run_id",
                "invocation_start_sha256",
                "invocation_outcome_sha256",
                "process_stop_sha256",
                "workspace_inventory_sha256",
            ],
            "properties": {
                **{
                    name: {"type": "string"}
                    for name in (
                        "original_run_id",
                        "invocation_start_sha256",
                        "invocation_outcome_sha256",
                        "process_stop_sha256",
                        "workspace_inventory_sha256",
                    )
                },
                **{
                    name: {"type": "null"}
                    for name in (
                        "retry_cause",
                        "interruption_receipt_sha256",
                        "original_authority",
                        "knowledge_preparation",
                        "verification_retry",
                        "verifier_preparation",
                    )
                },
                "permitted_resolutions": {
                    "maxItems": 1,
                    "items": {"const": "RETRY_REJECTED_CODER_OUTPUT"},
                },
                "disposition": {
                    "properties": {
                        "facts": {
                            "properties": {
                                "role": {"const": "coder"},
                                "classification": {"enum": ["PLATFORM_BUG", "INVALID_OUTPUT"]},
                            }
                        }
                    }
                },
            },
        },
    },
]
resolution_schema["$defs"]["DeliveryWaitInvestigation"]["allOf"] += [
    {
        "if": {
            "required": ["permitted_resolutions"],
            "properties": {
                "permitted_resolutions": {
                    "contains": {"const": "RETRY_REJECTED_KNOWLEDGE_PREPARATION"}
                }
            },
        },
        "then": {
            "required": ["rejected_knowledge"],
            "properties": {"rejected_knowledge": {"type": "object"}},
        },
    },
    {
        "if": {
            "required": ["rejected_knowledge"],
            "properties": {"rejected_knowledge": {"type": "object"}},
        },
        "then": {
            "required": ["original_run_id", "workspace_inventory_sha256"],
            "properties": {
                "original_run_id": {"type": "string"},
                "workspace_inventory_sha256": {"type": "string"},
                **{
                    name: {"type": "null"}
                    for name in (
                        "invocation_start_sha256",
                        "invocation_outcome_sha256",
                        "retry_cause",
                        "interruption_receipt_sha256",
                        "process_stop_sha256",
                        "original_authority",
                        "knowledge_preparation",
                        "verification_retry",
                        "verifier_preparation",
                        "rejected_output",
                    )
                },
                "permitted_resolutions": {
                    "maxItems": 1,
                    "items": {"const": "RETRY_REJECTED_KNOWLEDGE_PREPARATION"},
                },
                "disposition": {
                    "properties": {
                        "facts": {
                            "properties": {
                                "role": {"const": "coder"},
                                "classification": {"const": "INVALID_OUTPUT"},
                                "evidence_ids": {
                                    "minItems": 1,
                                    "maxItems": 1,
                                    "items": {
                                        "pattern": "^knowledge-assessment-rejection://[a-f0-9]{64}$"
                                    },
                                },
                            }
                        }
                    }
                },
            },
        },
    },
]
# A sealed semantic rejection may reprove an old generic wait without changing it.
# Keep the exact two accepted shapes; foreign evidence never becomes retry authority.
resolution_schema["$defs"]["DeliveryWaitInvestigation"]["allOf"][-1]["then"]["properties"][
    "disposition"
]["properties"]["facts"] = {
    "required": ["role", "classification", "evidence_ids"],
    "properties": {"role": {"const": "coder"}},
    "anyOf": [
        {
            "properties": {
                "classification": {"const": "INVALID_OUTPUT"},
                "evidence_ids": {
                    "minItems": 1,
                    "maxItems": 1,
                    "items": {"pattern": "^knowledge-assessment-rejection://[a-f0-9]{64}$"},
                },
            }
        },
        {
            "properties": {
                "classification": {"const": "PLATFORM_BUG"},
                "evidence_ids": {"maxItems": 0},
            }
        },
    ],
}
# Today's complete draft needs its own operator decision, never an old policy grant.
resolution_schema["$defs"]["DeliveryResolution"]["allOf"].append(
    {
        "if": {"properties": {"resolution_kind": {"const": "STATIC_QA_MISSING_ENTRY"}}},
        "then": {
            "required": ["static_qa_missing_entry", "verifier_preparation", "operator_principal"],
            "properties": {
                "static_qa_missing_entry": {"type": "object"},
                "authorization_source": {"const": "engineering_operator_decision"},
                "operator_principal": {"type": "object"},
                "engineering_admission": {"type": "null"},
                "retry_failure": {"type": "null"},
                "retry_cause": {"type": "null"},
            },
        },
        "else": {"properties": {"static_qa_missing_entry": {"type": "null"}}},
    }
)
resolution_schema["$defs"]["DeliveryResolution"]["allOf"].append(
    {
        "if": {
            "required": ["rejected_knowledge"],
            "properties": {
                "rejected_knowledge": {
                    "type": "object",
                    "required": ["current_draft_sha256"],
                    "properties": {"current_draft_sha256": {"type": "string"}},
                }
            },
        },
        "then": {
            "required": ["authorization_source", "operator_principal"],
            "properties": {
                "authorization_source": {"const": "engineering_operator_decision"},
                "operator_principal": {"type": "object"},
                "engineering_admission": {"type": "null"},
            },
        },
    }
)
resolution_schema["$defs"]["RejectedKnowledgePreparationEvidence"]["properties"]["role"] = {
    "const": "coder"
}
resolution_schema["$defs"]["RejectedKnowledgePreparationEvidence"]["properties"][
    "carry_history_sha256s"
]["uniqueItems"] = True
resolution_schema["$defs"]["VerifierPreparationEvidence"]["allOf"] = [
    {
        "if": {"properties": {"native_execution_state": {"const": "FINISHED"}}},
        "then": {
            "required": [
                "native_binding_plan_sha256",
                "native_started_sha256",
                "native_finished_sha256",
            ],
            "properties": {
                **{
                    key: {"type": "string"}
                    for key in (
                        "native_binding_plan_sha256",
                        "native_started_sha256",
                        "native_finished_sha256",
                    )
                },
            },
            "allOf": [
                {
                    "if": {
                        "required": ["context_capacity_receipt_sha256"],
                        "properties": {"context_capacity_receipt_sha256": {"type": "string"}},
                    },
                    "then": {"properties": {"budget_source": {"type": "null"}}},
                    "else": {
                        "required": ["budget_source"],
                        "properties": {"budget_source": {"const": "frozen_work_attempt"}},
                    },
                }
            ],
        },
        "else": {
            "properties": {
                key: {"type": "null"}
                for key in (
                    "native_started_sha256",
                    "native_finished_sha256",
                    "native_failure_code",
                    "budget_source",
                )
            }
        },
    },
    {
        "if": {
            "required": ["context_capacity_receipt_sha256"],
            "properties": {"context_capacity_receipt_sha256": {"type": "string"}},
        },
        "then": {
            "required": ["context_capacity_claim_sha256"],
            "properties": {
                "context_capacity_claim_sha256": {"type": "string"},
                "native_execution_state": {"enum": ["NOT_STARTED", "FINISHED"]},
                "native_failure_code": {"type": "null"},
                "budget_source": {"type": "null"},
            },
        },
        "else": {"properties": {"context_capacity_claim_sha256": {"type": "null"}}},
    },
]
capacity_proof = {
    "required": ["verifier_preparation"],
    "properties": {
        "verifier_preparation": {
            "type": "object",
            "required": ["context_capacity_receipt_sha256"],
            "properties": {"context_capacity_receipt_sha256": {"type": "string"}},
        }
    },
}
resolution_schema["$defs"]["DeliveryResolution"]["allOf"].append(
    {
        "if": capacity_proof,
        "then": {"properties": {"resolution_kind": {"const": "RESUME_UNINVOKED"}}},
    }
)
resolution_schema["$defs"]["DeliveryWaitInvestigation"]["allOf"].append(
    {
        "if": capacity_proof,
        "then": {
            "properties": {
                **{
                    field: {"type": "null"}
                    for field in (
                        "invocation_start_sha256",
                        "invocation_outcome_sha256",
                        "process_stop_sha256",
                        "retry_cause",
                        "original_authority",
                        "verification_retry",
                        "knowledge_preparation",
                        "rejected_output",
                    )
                },
                "permitted_resolutions": {"maxItems": 1, "items": {"const": "RESUME_UNINVOKED"}},
                "disposition": {
                    "properties": {
                        "facts": {
                            "properties": {
                                "role": {"enum": ["qa", "reviewer"]},
                                "classification": {"const": "CONTEXT_CAPACITY"},
                                "evidence_ids": {
                                    "minItems": 1,
                                    "maxItems": 1,
                                    "items": {"pattern": "^context-capacity://[a-f0-9]{64}$"},
                                },
                            }
                        }
                    }
                },
            }
        },
    }
)
# The canonical wait graph also retains the pre-existing stopped-provider hint.
resolution_schema["$defs"]["DeliveryWaitInvestigation"]["allOf"].append(
    {
        "if": {
            "required": ["provider_failure_code"],
            "properties": {"provider_failure_code": {"type": "string"}},
        },
        "then": {
            "required": ["invocation_start_sha256", "invocation_outcome_sha256", "original_run_id"],
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
)
resolution_schema["$defs"]["DeliveryWaitInvestigation"]["allOf"] += [
    {
        "if": {
            "required": ["permitted_resolutions"],
            "properties": {
                "permitted_resolutions": {
                    "contains": {"const": "RETRY_REJECTED_WORKSPACE_ADMISSION"}
                }
            },
        },
        "then": {
            "required": ["rejected_workspace_admission"],
            "properties": {"rejected_workspace_admission": {"type": "object"}},
        },
    },
    {
        "if": {
            "required": ["rejected_workspace_admission"],
            "properties": {"rejected_workspace_admission": {"type": "object"}},
        },
        "then": {
            "required": [
                "original_run_id",
                "invocation_start_sha256",
                "invocation_outcome_sha256",
                "workspace_inventory_sha256",
            ],
            "properties": {
                **{
                    name: {"type": "string"}
                    for name in (
                        "original_run_id",
                        "invocation_start_sha256",
                        "invocation_outcome_sha256",
                        "workspace_inventory_sha256",
                    )
                },
                **{
                    name: {"type": "null"}
                    for name in (
                        "retry_cause",
                        "interruption_receipt_sha256",
                        "process_stop_sha256",
                        "original_authority",
                        "knowledge_preparation",
                        "verification_retry",
                        "verifier_preparation",
                        "rejected_output",
                        "rejected_knowledge",
                    )
                },
                "permitted_resolutions": {
                    "maxItems": 1,
                    "items": {"const": "RETRY_REJECTED_WORKSPACE_ADMISSION"},
                },
                "disposition": {
                    "properties": {
                        "facts": {
                            "properties": {
                                "role": {"const": "coder"},
                                "classification": {
                                    "enum": ["NONTRANSIENT_INFRA", "PLATFORM_BUG", "INVALID_OUTPUT"]
                                },
                            }
                        }
                    }
                },
            },
        },
    },
]
# A refusal is a positive pre-admission observation, never an empty execution list.
resolution_schema["$defs"]["DeliveryWaitInvestigation"]["allOf"].append(
    {
        "if": {
            "required": ["permitted_resolutions", "disposition"],
            "properties": {
                "permitted_resolutions": {"contains": {"const": "RESUME_UNINVOKED"}},
                "disposition": {
                    "properties": {
                        "facts": {
                            "properties": {
                                "evidence_ids": {"contains": {"pattern": "^knowledge-pause://"}},
                            }
                        }
                    }
                },
            },
        },
        "then": {
            "required": ["knowledge_pause"],
            "properties": {"knowledge_pause": {"type": "object"}},
        },
    }
)
resolution_schema["$defs"]["KnowledgePreparationPauseEvidence"]["allOf"] = [
    {
        "properties": {"execution_record_sha256s": {"uniqueItems": True}},
        "if": {"properties": {"proof_mode": {"const": "pre_admission_refusal"}}},
        "then": {
            "required": ["pre_admission_pause_sha256"],
            "properties": {
                "pre_admission_pause_sha256": {"type": "string"},
                "execution_record_sha256s": {"maxItems": 0},
            },
        },
        "else": {
            "properties": {
                "pre_admission_pause_sha256": {"type": "null"},
                "execution_record_sha256s": {"minItems": 2, "maxItems": 2},
            }
        },
    }
]
for proof_name in ("DeliveryResolution", "DeliveryWaitInvestigation"):
    excluded_pause_fields = (
        "retry_cause",
        "original_authority",
        "verifier_pause",
        "verification_retry",
        "verifier_preparation",
        "knowledge_preparation",
        "rejected_output",
        "rejected_knowledge",
        "rejected_workspace_admission",
        *(
            ("retry_failure",)
            if proof_name == "DeliveryResolution"
            else (
                "invocation_start_sha256",
                "invocation_outcome_sha256",
                "interruption_receipt_sha256",
                "process_stop_sha256",
            )
        ),
    )
    properties: dict[str, object] = {name: {"type": "null"} for name in excluded_pause_fields}
    if proof_name == "DeliveryResolution":
        properties["resolution_kind"] = {"const": "RESUME_UNINVOKED"}
    else:
        properties.update(
            {
                "permitted_resolutions": {
                    "maxItems": 1,
                    "items": {"const": "RESUME_UNINVOKED"},
                },
                "disposition": {
                    "properties": {
                        "facts": {
                            "properties": {
                                "classification": {"const": "SERVICE_PAUSED"},
                                "evidence_ids": {
                                    "minItems": 1,
                                    "maxItems": 1,
                                    "items": {"pattern": "^knowledge-pause://[a-f0-9]{64}$"},
                                },
                            }
                        }
                    }
                },
            }
        )
    resolution_schema["$defs"][proof_name]["allOf"].append(
        {
            "if": {
                "required": ["knowledge_pause"],
                "properties": {"knowledge_pause": {"type": "object"}},
            },
            "then": {"properties": properties},
        }
    )

local_stop_guard = run_path(str(Path(__file__).with_name("sync-contained-unknown-contracts.py")))[
    "LOCAL_STOP_GUARD"
]
if (
    "local_stop_confirmation_available"
    not in resolution_schema["$defs"]["DeliveryWaitInvestigation"]["properties"]
):
    raise RuntimeError("local stop capability is missing from the investigation model")
resolution_schema["$defs"]["DeliveryWaitInvestigation"]["allOf"].append(local_stop_guard)

if not wait_only:
    (
        Path(__file__).resolve().parents[1] / "schemas/engineering-wait-resolution.schema.json"
    ).write_text(
        json.dumps(resolution_schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

if wait_only:
    # Nested Console/settlement schemas have additional hand-written guards.
    # Copy only the new static-QA definitions and guards from the canonical
    # schema; full model regeneration would silently erase those guards.
    canonical = resolution_schema["$defs"]
    assert isinstance(canonical, dict)
    static_guard = next(
        guard
        for guard in canonical["DeliveryResolution"]["allOf"]
        if guard.get("if", {}).get("properties", {}).get("resolution_kind", {}).get("const")
        == "STATIC_QA_MISSING_ENTRY"
    )
    verifier_guard = next(
        guard
        for guard in canonical["DeliveryResolution"]["allOf"]
        if guard.get("if", {}).get("properties", {}).get("resolution_kind", {}).get("const")
        == "RETRY_VERIFIER_PREPARATION"
    )
    investigation_guards = tuple(
        guard
        for guard in canonical["DeliveryWaitInvestigation"]["allOf"]
        if "STATIC_QA_MISSING_ENTRY" in json.dumps(guard, sort_keys=True)
    )
    if len(investigation_guards) != 2:
        raise RuntimeError("static QA investigation guards are incomplete")
    local_stop_property = canonical["DeliveryWaitInvestigation"]["properties"][
        "local_stop_confirmation_available"
    ]
    for filename in (
        "engineering-wait-resolution.schema.json",
        "console-deletion-cleanup.schema.json",
        "console-operation.schema.json",
        "stopped-failure-budget-settlement.schema.json",
        "stopped-unknown-budget-settlement.schema.json",
    ):
        path = Path(__file__).resolve().parents[1] / "schemas" / filename
        nested = json.loads(path.read_text(encoding="utf-8"))
        definitions = nested["$defs"]
        kind = definitions["DeliveryResolutionKind"]
        expected_previous = [
            value
            for value in canonical["DeliveryResolutionKind"]["enum"]
            if value != "STATIC_QA_MISSING_ENTRY"
        ]
        if kind["enum"] not in (expected_previous, canonical["DeliveryResolutionKind"]["enum"]):
            raise RuntimeError(f"{filename} has an unexpected resolution enum")
        kind["enum"] = canonical["DeliveryResolutionKind"]["enum"]
        definitions["StaticQaMissingEntryEvidence"] = canonical["StaticQaMissingEntryEvidence"]
        for model_name in ("DeliveryResolution", "DeliveryWaitInvestigation"):
            if model_name not in definitions:
                continue
            model = definitions[model_name]
            model["properties"]["static_qa_missing_entry"] = canonical[model_name]["properties"][
                "static_qa_missing_entry"
            ]
            guards = model.setdefault("allOf", [])
            if model_name == "DeliveryResolution":
                for index, guard in enumerate(guards):
                    if (
                        guard.get("if", {})
                        .get("properties", {})
                        .get("resolution_kind", {})
                        .get("const")
                        == "RETRY_VERIFIER_PREPARATION"
                    ):
                        guards[index] = verifier_guard
                        break
                else:
                    raise RuntimeError(f"{filename} lost the verifier preparation guard")
                if static_guard not in guards:
                    guards.append(static_guard)
            else:
                for guard in investigation_guards:
                    if guard not in guards:
                        guards.append(guard)
                if filename not in (
                    "stopped-failure-budget-settlement.schema.json",
                    "stopped-unknown-budget-settlement.schema.json",
                ):
                    model["properties"]["local_stop_confirmation_available"] = local_stop_property
                    if local_stop_guard not in guards:
                        guards.append(local_stop_guard)
        path.write_text(json.dumps(nested, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

checkpoint_schema = RejectedCoderOutputCheckpoint.model_json_schema()
checkpoint_schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
checkpoint_schema["$id"] = (
    "https://ai-software-engineer.local/schemas/rejected-coder-output-checkpoint.schema.json"
)
checkpoint_schema["allOf"] = [
    {
        "properties": {
            "capture_stop": {
                "properties": {
                    "output_present": {"const": True},
                    "cause": {"type": "null"},
                    "original_error_code": {"type": "null"},
                    "process_stop": {
                        "properties": {"kind": {"const": "completed"}, "returncode": {"const": 0}}
                    },
                }
            },
            "outcome": {
                "properties": {
                    "start": {
                        "properties": {"request": {"properties": {"role": {"const": "coder"}}}}
                    },
                    "result": {
                        "properties": {
                            "status": {"const": "SUCCEEDED"},
                            "artifact": {"properties": {"kind": {"const": "coder-progress"}}},
                        }
                    },
                }
            },
            "capture": {
                "properties": {
                    "index_diff_sha256": {
                        "const": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
                    }
                }
            },
        }
    }
]
if not wait_only:
    (
        Path(__file__).resolve().parents[1] / "schemas/rejected-coder-output-checkpoint.schema.json"
    ).write_text(
        json.dumps(checkpoint_schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

# EngineeringPolicy is embedded in Task/dispatch/recovery wire contracts. Keep
# every copy's capability enum synchronized without erasing their hand-written
# validation matrices or unrelated definitions.
capability_schema = TypeAdapter(EngineeringCapability).json_schema()
failure_schema = DeliveryFailureFacts.model_json_schema()
failure_schema.pop("$defs")
embedded_paths = (
    () if wait_only else (Path(__file__).resolve().parents[1] / "schemas").glob("*.schema.json")
)
for path in embedded_paths:
    embedded = json.loads(path.read_text(encoding="utf-8"))
    definitions = embedded.get("$defs", {})
    changed = False
    if (
        "EngineeringCapability" in definitions
        and definitions["EngineeringCapability"] != capability_schema
    ):
        definitions["EngineeringCapability"] = capability_schema
        changed = True
    # The Team snapshot has its own complete model generator and read-side owner.
    # Other embedded copies must keep the same strict failure classification.
    if (
        path.name != "team-snapshot.schema.json"
        and "DeliveryFailureFacts" in definitions
        and definitions["DeliveryFailureFacts"] != failure_schema
    ):
        definitions["DeliveryFailureFacts"] = failure_schema
        changed = True
    if changed:
        path.write_text(json.dumps(embedded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
