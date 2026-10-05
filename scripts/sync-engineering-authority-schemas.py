"""Regenerate the organization engineering policy/admission wire contracts."""

import json
from pathlib import Path
from typing import Annotated

from pydantic import Field, TypeAdapter

from ai_software_engineer.domain.delivery_resolution import (
    RESULT_REPLAY_REJECTED_CLASSIFICATIONS,
    DeliveryResolution,
    DeliveryWaitInvestigation,
    EngineeringDispositionRecord,
)
from ai_software_engineer.domain.engineering_authority import (
    EngineeringAdmission,
    EngineeringPolicy,
)

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
        DeliveryWaitInvestigation | DeliveryResolution | EngineeringDispositionRecord,
        Field(discriminator="kind"),
    ]
).json_schema()
resolution_schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
resolution_schema["$id"] = (
    "https://ai-software-engineer.local/schemas/engineering-wait-resolution.schema.json"
)
resolution_schema["$defs"]["DeliveryResolution"]["allOf"] = [
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
                        "properties": {
                            "native_execution_state": {"const": "NOT_STARTED"},
                        }
                    }
                }
            },
            "else": {"properties": {"verifier_preparation": {"type": "null"}}},
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
]
resolution_schema["$defs"]["VerifierPreparationEvidence"]["allOf"] = [
    {
        "if": {"properties": {"native_execution_state": {"const": "FINISHED"}}},
        "then": {
            "required": [
                "native_binding_plan_sha256",
                "native_started_sha256",
                "native_finished_sha256",
                "budget_source",
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
                "budget_source": {"const": "frozen_work_attempt"},
            },
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
]
(
    Path(__file__).resolve().parents[1] / "schemas/engineering-wait-resolution.schema.json"
).write_text(json.dumps(resolution_schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
