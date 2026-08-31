# T005 Verification

## Standards Check

- `ArtifactStore` is a typed Protocol; `FileArtifactStore` is the only filesystem implementation and domain models remain I/O-free.
- Canonical digesting excludes only the top-level `integrity` field, avoiding circular hashes while protecting all Agent-produced content and lineage.
- Writes use a controlled Artifact ID filename, same-directory temporary file, flush, `fsync`, and atomic `os.replace`.

## Cross-Layer Check

- Write flow verified: typed Artifact → seal → typed/integrity/lineage guards → canonical JSON → atomic file → `ArtifactRef`.
- Read flow verified: artifact ID → controlled path → JSON decode → typed union validation → schema-version/digest check → typed Artifact.
- Exact replay is idempotent; conflicting ID content, missing/cross-Task parents, cross-kind supersedes, and corrupted files return stable errors without overwriting evidence.
- Existing JSON Schemas and domain Artifact models were not duplicated or weakened.

## Unit and Contract Coverage

- 13 ArtifactStore tests cover deterministic sealing, immutable input, strict JSON numbers, round-trip, unsealed/digest/schema rejection, exact replay, ID conflict, lineage, corruption/tampering, and temp-file cleanup.
- Existing domain, JSON Schema, state-machine, SQLite repository, and CLI tests continue to pass.

## Validation Evidence

```text
ruff format --check .                   PASS (75 files)
ruff check .                            PASS
mypy src tests                          PASS (33 source files)
pytest                                  PASS (111 tests)
uv lock --check                         PASS (41 packages resolved)
uv build                                PASS (sdist + wheel)
git diff --check                        PASS
```

No blocking or major finding remains. T005 completes the M1 Artifact persistence exit criterion without adding a remote service, queue, database index, or parallel execution path.
