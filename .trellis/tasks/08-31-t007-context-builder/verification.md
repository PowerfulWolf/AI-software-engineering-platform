# T007 Verification

## Acceptance evidence

- `tests/context/test_router.py` verifies role filtering, all-role sources, deterministic `(priority, uri, source_id)` ordering, duplicate source protection, and invalid-role rejection.
- `tests/context/test_builder.py` verifies stable identity/order/hash/token counts, exact candidate revision propagation, root-bound policy reads, traversal/deny/missing failures, redaction before counting/hashing (including JSON-shaped secrets and secret-bearing URIs), optional truncation, required overflow, and prompt-injection data boundaries.
- `tests/contracts/test_json_schema_contracts.py` validates a `ContextBundle` against `schemas/context.schema.json` and rejects a section missing `sha256`.

## Quality gates

| Check | Result |
|---|---|
| `uv run pytest` | 150 passed |
| `uv run ruff format --check .` | passed |
| `uv run ruff check .` | passed |
| `uv run mypy src tests` | passed; 48 files |
| `uv lock --check` | passed |
| `uv build` | source distribution and wheel built |
| `git diff --check` | passed |

## Security note

An adversarial repository source cannot claim priority `0`; that slot is reserved for the generated machine policy section. URI redaction uses safe `source://<source_id>` metadata so a secret embedded in a source URI is not exposed by the audit trail.
