"""Synchronize only the optional owned-session stop graph; keep all enclosing guards."""

import json
from pathlib import Path

from ai_software_engineer.agents.execution import NativeProcessStop

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
EXPECTED_EMBEDDINGS = frozenset(
    {
        "completed-coder-output-unavailable.schema.json",
        "console-deletion-cleanup.schema.json",
        "console-operation.schema.json",
        "engineering-wait-resolution.schema.json",
        "execution-baseline-plan.schema.json",
        "execution-baseline-queue-consumption.schema.json",
        "execution-capture.schema.json",
        "execution-continuation.schema.json",
        "knowledge-execution-record.schema.json",
        "knowledge-invocation-outcome.schema.json",
        "rejected-coder-output-checkpoint.schema.json",
        "service-pause-stop.schema.json",
        "stopped-failure-budget-settlement.schema.json",
        "stopped-provider-failure.schema.json",
        "structured-execution-observation.schema.json",
    }
)


def main() -> None:
    generated = NativeProcessStop.model_json_schema()
    definitions = generated.pop("$defs")
    files: list[tuple[Path, dict[str, object]]] = []
    for path in sorted(SCHEMAS.glob("*.schema.json")):
        schema = json.loads(path.read_text())
        if "NativeProcessStop" in schema.get("$defs", {}):
            files.append((path, schema))
    if {path.name for path, _ in files} != EXPECTED_EMBEDDINGS:
        raise ValueError(
            "owned-session contract requires review of the exact stop embedding inventory"
        )
    for path, schema in files:
        defs = schema["$defs"]
        assert isinstance(defs, dict)
        defs["NativeProcessStop"] = generated
        defs.update(definitions)
        path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
