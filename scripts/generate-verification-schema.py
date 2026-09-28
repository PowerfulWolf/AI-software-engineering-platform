"""Regenerate the candidate-verification wire union from its typed contracts."""

import json
from pathlib import Path
from typing import Annotated

from pydantic import Field, TypeAdapter

from ai_software_engineer.domain.prerequisite_repair import PrerequisiteRepairPlan
from ai_software_engineer.manager.verification_coordination import ManagerVerificationAdvice
from ai_software_engineer.manager.verification_environment import VerificationEnvironmentIncident
from ai_software_engineer.recovery.models import RecoveryAuthorization
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
        | CandidateExecutorPrerequisite,
        Field(discriminator="kind"),
    ]
).json_schema()
schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
schema["$id"] = "https://ai-software-engineer.local/schemas/candidate-verification.schema.json"
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
