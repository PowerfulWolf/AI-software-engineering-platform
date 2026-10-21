"""Refresh semantic recovery graphs while preserving unrelated handwritten contracts."""

import json
from pathlib import Path
from runpy import run_path
from typing import Any

from ai_software_engineer.domain.delivery_disposition import DeliveryFailureFacts
from ai_software_engineer.domain.workspace_admission_contract import (
    WorkspaceAdmissionAdapterContractRecord,
)
from ai_software_engineer.knowledge.assessment_rejection import RejectedKnowledgeAssessment
from ai_software_engineer.manager.rejected_knowledge_draft import RejectedKnowledgeCurrentDraft
from ai_software_engineer.manager.rejected_knowledge_preparation import (
    RejectedKnowledgeCarryRefusal,
)
from ai_software_engineer.web_console.models import HandleDeliveryWaitIntent

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
NAMES = (
    "DeliveryResolutionKind",
    "DeliveryResolution",
    "DeliveryWaitInvestigation",
    "DeliveryWaitHandling",
    "RejectedKnowledgePreparationEvidence",
    "KnowledgePreparationPauseEvidence",
    "RejectedWorkspaceAdmissionEvidence",
    "DeliveryFailureFacts",
    "HandleDeliveryWaitIntent",
)


def references(value: Any) -> set[str]:
    if isinstance(value, dict):
        reference = value.get("$ref")
        found = (
            {reference.removeprefix("#/$defs/")}
            if isinstance(reference, str) and reference.startswith("#/$defs/")
            else set()
        )
        return found.union(*(references(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(references(child) for child in value))
    return set()


def preserve_order(value: Any, previous: Any) -> Any:
    if isinstance(value, dict) and isinstance(previous, dict):
        keys = [key for key in previous if key in value] + [
            key for key in value if key not in previous
        ]
        return {key: preserve_order(value[key], previous.get(key)) for key in keys}
    if isinstance(value, list) and isinstance(previous, list):
        return [
            preserve_order(child, previous[index] if index < len(previous) else None)
            for index, child in enumerate(value)
        ]
    return value


def main() -> None:
    original_bytes = {path: path.read_text() for path in SCHEMAS.glob("*.schema.json")}
    # Owns the manually authored if/then gates; do not rebuild those from Pydantic.
    run_path(str(ROOT / "scripts/sync-engineering-authority-schemas.py"))
    canonical = json.loads((SCHEMAS / "engineering-wait-resolution.schema.json").read_text())
    handle = HandleDeliveryWaitIntent.model_json_schema()
    all_nodes = {**canonical["$defs"], **handle.pop("$defs", {})}
    all_nodes["HandleDeliveryWaitIntent"] = handle
    nodes = {name: all_nodes[name] for name in NAMES}
    facts = DeliveryFailureFacts.model_json_schema()
    nodes["DeliveryFailureFacts"] = {key: value for key, value in facts.items() if key != "$defs"}
    for path, content in original_bytes.items():
        original = json.loads(content)
        updated = json.loads(content)
        if path.name == "engineering-wait-resolution.schema.json":
            updated = canonical
        else:
            definitions = updated.get("$defs", {})
            applicable = set(NAMES) & definitions.keys()
            for name in applicable:
                definitions[name] = nodes[name]
            if updated.get("title") == "DeliveryFailureFacts":
                updated = {**facts, "$id": updated["$id"], "$schema": updated["$schema"]}
            while applicable:
                missing = references(updated) - definitions.keys()
                if not missing:
                    break
                for name in missing:
                    definitions[name] = all_nodes[name]
        if updated == original:
            path.write_text(content)
        else:
            path.write_text(
                json.dumps(preserve_order(updated, original), ensure_ascii=False, indent=2) + "\n"
            )
    for name, model in (
        ("rejected-knowledge-assessment", RejectedKnowledgeAssessment),
        ("rejected-knowledge-carry-refusal", RejectedKnowledgeCarryRefusal),
        ("rejected-knowledge-current-draft", RejectedKnowledgeCurrentDraft),
        ("workspace-admission-adapter-contract", WorkspaceAdmissionAdapterContractRecord),
    ):
        wire = model.model_json_schema()
        wire["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        wire["$id"] = f"https://ai-software-engineer.local/schemas/{name}.schema.json"
        (SCHEMAS / f"{name}.schema.json").write_text(
            json.dumps(wire, ensure_ascii=False, indent=2) + "\n"
        )


if __name__ == "__main__":
    main()
