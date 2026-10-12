#!/usr/bin/env python3
"""Generate the fixed private inspection fault-retirement record schemas."""

import json
from pathlib import Path

from ai_software_engineer.web_console.fault_log_retention import (
    ArchivedLogPurgeIntent,
    ArchivedLogPurgeReceipt,
)
from ai_software_engineer.web_console.fault_retirement import (
    FaultRetirementPlan,
    FaultRetirementReceipt,
    InspectionMarker,
    SignalSent,
    TerminationIntent,
)
from ai_software_engineer.web_console.maintenance_completion import (
    MaintenanceCompletionPlan,
    MaintenanceCompletionReceipt,
    MaintenanceNormalAdmission,
)

root = Path(__file__).resolve().parents[1] / "schemas"
for name, model in (
    ("console-fault-retirement-plan", FaultRetirementPlan),
    ("console-fault-retirement-receipt", FaultRetirementReceipt),
    ("console-fault-retirement-intent", TerminationIntent),
    ("console-fault-retirement-signal", SignalSent),
    ("console-inspection", InspectionMarker),
    ("console-archived-log-purge-intent", ArchivedLogPurgeIntent),
    ("console-archived-log-purge-receipt", ArchivedLogPurgeReceipt),
    ("console-maintenance-completion-plan", MaintenanceCompletionPlan),
    ("console-maintenance-completion-receipt", MaintenanceCompletionReceipt),
    ("console-maintenance-admission", MaintenanceNormalAdmission),
):
    schema = model.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    (root / (name + ".schema.json")).write_text(
        json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
    )
