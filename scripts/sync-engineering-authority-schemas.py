"""Regenerate the organization engineering policy/admission wire contracts."""

import json
from pathlib import Path
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

schema = TypeAdapter(
    Annotated[EngineeringPolicy | EngineeringAdmission, Field(discriminator="kind")]
).json_schema()
schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
schema["$id"] = "https://ai-software-engineer.local/schemas/engineering-authority.schema.json"
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
            "else": {"properties": {"verifier_preparation": {"type": "null"}}},
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
(
    Path(__file__).resolve().parents[1] / "schemas/engineering-wait-resolution.schema.json"
).write_text(json.dumps(resolution_schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
(
    Path(__file__).resolve().parents[1] / "schemas/rejected-coder-output-checkpoint.schema.json"
).write_text(json.dumps(checkpoint_schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# EngineeringPolicy is embedded in Task/dispatch/recovery wire contracts. Keep
# every copy's capability enum synchronized without erasing their hand-written
# validation matrices or unrelated definitions.
capability_schema = TypeAdapter(EngineeringCapability).json_schema()
failure_schema = DeliveryFailureFacts.model_json_schema()
failure_schema.pop("$defs")
for path in (Path(__file__).resolve().parents[1] / "schemas").glob("*.schema.json"):
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
