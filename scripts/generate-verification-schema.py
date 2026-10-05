"""Regenerate the candidate-verification wire union from its typed contracts."""

import json
from pathlib import Path
from typing import Annotated

from pydantic import Field, TypeAdapter

from ai_software_engineer.domain.engineering_authority import EngineeringAdmission
from ai_software_engineer.domain.prerequisite_repair import PrerequisiteRepairPlan
from ai_software_engineer.manager.verification_coordination import ManagerVerificationAdvice
from ai_software_engineer.manager.verification_environment import VerificationEnvironmentIncident
from ai_software_engineer.recovery.models import RecoveryAuthorization
from ai_software_engineer.recovery.python_mysql_records import MysqlResourceRecord
from ai_software_engineer.recovery.verification_records import (
    CandidateExecutorPrerequisite,
    CandidateVerificationCompletion,
    CandidateVerificationInvocation,
    CandidateVerificationPlan,
    VerificationExecutionRecord,
)

schema = TypeAdapter(
    Annotated[
        CandidateVerificationPlan
        | CandidateVerificationInvocation
        | CandidateVerificationCompletion
        | RecoveryAuthorization
        | VerificationEnvironmentIncident
        | ManagerVerificationAdvice
        | PrerequisiteRepairPlan
        | VerificationExecutionRecord
        | CandidateExecutorPrerequisite
        | MysqlResourceRecord
        | EngineeringAdmission,
        Field(discriminator="kind"),
    ]
).json_schema()
schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
schema["$id"] = "https://ai-software-engineer.local/schemas/candidate-verification.schema.json"
definitions = schema["$defs"]
definitions["CandidateVerificationPlan"]["allOf"] = [
    {
        "if": {"required": ["native_ui"], "properties": {"native_ui": {"not": {"type": "null"}}}},
        "then": {
            "required": ["executor_capability"],
            "properties": {
                "executor_capability": {
                    "type": "object",
                    "properties": {"kind": {"const": "codex_sandbox_swiftpm_v1"}},
                }
            },
        },
    }
]
definitions["VerificationExecutionRecord"]["allOf"] = [
    {
        "if": {
            "properties": {
                "capability": {"properties": {"kind": {"const": "codex_sandbox_pytest_mysql_v1"}}}
            }
        },
        "then": {
            "required": ["private_root", "mysql_resource_id"],
            "properties": {
                "private_root": {"type": "string"},
                "mysql_resource_id": {"type": "string"},
                "native_ui": {"type": "null"},
                "ui_results": {"type": "null"},
                "results": {"maxItems": 1},
            },
        },
        "else": {
            "properties": {"private_root": {"type": "null"}, "mysql_resource_id": {"type": "null"}}
        },
    }
]
definitions["MysqlResourceRecord"]["allOf"] = [
    {
        "if": {"properties": {"phase": {"const": "CREATED"}}},
        "then": {
            "required": ["container_id", "configuration_sha256"],
            "properties": {
                "container_id": {"type": "string"},
                "configuration_sha256": {"type": "string"},
            },
        },
    },
    {
        "if": {"properties": {"phase": {"const": "INTENT"}}},
        "then": {
            "properties": {
                "container_id": {"type": "null"},
                "configuration_sha256": {"type": "null"},
            }
        },
    },
]
definitions["PytestSelection"]["properties"]["criterion_ids"]["uniqueItems"] = True
definitions["MysqlResourceRecord"]["allOf"].append(
    {
        "if": {
            "required": ["configuration_sha256"],
            "properties": {"configuration_sha256": {"not": {"type": "null"}}},
        },
        "then": {"required": ["container_id"], "properties": {"container_id": {"type": "string"}}},
    }
)
schema["$defs"]["PrerequisiteRepairPlan"]["oneOf"] = [
    {
        "required": ["completion_sha256", "incident_sha256"],
        "properties": {
            "completion_sha256": {"type": "string"},
            "incident_sha256": {"type": "string"},
            "executor_prerequisite_sha256": {"type": "null"},
        },
    },
    {
        "required": ["executor_prerequisite_sha256"],
        "properties": {
            "executor_prerequisite_sha256": {"type": "string"},
            "completion_sha256": {"type": "null"},
            "incident_sha256": {"type": "null"},
        },
    },
]
(Path(__file__).resolve().parents[1] / "schemas/candidate-verification.schema.json").write_text(
    json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
