"""Regenerate the separately approved recovery-interruption wire contract."""

import json
from pathlib import Path
from typing import Annotated

from pydantic import Field, TypeAdapter

from ai_software_engineer.recovery.interruption_records import (
    RecoveryInterruptionInvocation,
    RecoveryInterruptionPlan,
)
from ai_software_engineer.recovery.models import RecoveryAuthorization

schema = TypeAdapter(
    Annotated[
        RecoveryInterruptionPlan | RecoveryInterruptionInvocation | RecoveryAuthorization,
        Field(discriminator="kind"),
    ]
).json_schema()
schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
schema["$id"] = "https://ai-software-engineer.local/schemas/recovery-interruption.schema.json"
(Path(__file__).resolve().parents[1] / "schemas/recovery-interruption.schema.json").write_text(
    json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
)
