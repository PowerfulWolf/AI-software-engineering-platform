"""Synchronize pause receipt graphs without discarding existing engineering guards."""

import json
from pathlib import Path
from runpy import run_path
from typing import Any

from ai_software_engineer.agents.structured_pause import StructuredPreAdmissionPauseReceipt
from ai_software_engineer.knowledge.invocation import KnowledgeInvocationOutcome

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


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


def main() -> None:
    # Its canonical producer owns allOf gates and complete dependency closure.
    generator = run_path(
        str(ROOT / "scripts/sync-rejected-knowledge-schemas.py"), run_name="__main__"
    )
    generated = KnowledgeInvocationOutcome.model_json_schema()
    definitions = generated.pop("$defs", {})
    for path in SCHEMAS.glob("*.schema.json"):
        original = json.loads(path.read_text())
        document = json.loads(path.read_text())
        nodes = document.get("$defs", {})
        if document.get("title") == "KnowledgeInvocationOutcome":
            document = {
                **generated,
                "$defs": definitions,
                "$id": document["$id"],
                "$schema": document["$schema"],
            }
        elif "KnowledgeInvocationOutcome" in nodes:
            nodes["KnowledgeInvocationOutcome"] = generated
            while missing := references(document) - nodes.keys():
                for name in missing:
                    nodes[name] = definitions[name]
        if document != original:
            path.write_text(
                json.dumps(
                    generator["preserve_order"](document, original), ensure_ascii=False, indent=2
                )
                + "\n"
            )
    raw = StructuredPreAdmissionPauseReceipt.model_json_schema()
    raw["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    raw["$id"] = (
        "https://ai-software-engineer.local/schemas/structured-pre-admission-pause.schema.json"
    )
    (SCHEMAS / "structured-pre-admission-pause.schema.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
