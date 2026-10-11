"""Synchronize only the optional owned-session stop graph; keep all enclosing guards."""

import json
from pathlib import Path

from ai_software_engineer.agents.execution import NativeProcessStop

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def main() -> None:
    generated = NativeProcessStop.model_json_schema()
    definitions = generated.pop("$defs")
    files: list[tuple[Path, dict[str, object]]] = []
    for path in sorted(SCHEMAS.glob("*.schema.json")):
        schema = json.loads(path.read_text())
        if "NativeProcessStop" in schema.get("$defs", {}):
            files.append((path, schema))
    if len(files) != 10:
        raise ValueError("owned-session contract requires review of all ten stop embeddings")
    for path, schema in files:
        defs = schema["$defs"]
        assert isinstance(defs, dict)
        defs["NativeProcessStop"] = generated
        defs.update(definitions)
        path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
