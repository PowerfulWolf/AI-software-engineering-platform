# T002 Verification

## Standards Check

- Domain inputs are validated with Pydantic v2; unknown fields and unknown Enum values are rejected.
- `TaskStatus`, `AgentRole`, and `ArtifactKind` each have one canonical definition.
- `DomainModel.to_wire()` is the typed JSON-compatible boundary; no `Any`, provider response, SDK object, database, Git, subprocess, or shell behavior entered the domain layer.
- Runtime and development dependencies are constrained, locked, and each removes a documented contract failure mode.
- T002 remains inside the v0.1 serial Coder → QA → Reviewer boundary.

## Cross-Layer Check

- Data flow verified: untrusted input → Pydantic model → `to_wire()` → canonical Draft 2020-12 Schema.
- Correct Artifact subtype, content type, producer role, and output kind remain aligned for all four Artifact kinds.
- Evidence SHA-256 and Finding evidence requirements are synchronized across Schema, Python models, docs, and core spec.
- Python absolute imports are acyclic; the public package imports Task, Agent Definition, and all Artifact types successfully.
- Cross-object candidate revision, required-criterion, independent-run, and persistence checks are explicitly deferred to T003–T005 instead of being hidden in single-object validators.

## Unit and Contract Coverage

- Task: valid wire output, frozen fields, IDs, unknown properties, attempt budget, and constraint budget consistency.
- Agent Definition: all four role/output mappings, wrong output ownership, state-change permission, and merge prohibition.
- Artifact: discriminated union, all four producer-role mismatch branches, Evidence references, QA PASS consistency, Review APPROVE/REJECT consistency, and independent run IDs.
- JSON Schema: all seven schemas parse; Task, Agent, four typed Artifacts, and the common envelope have positive fixtures; malformed IDs, extra fields, missing content, missing Evidence digest, and invalid RFC 3339 timestamps have negative fixtures.

## Validation Evidence

```text
uv lock --check                         PASS (41 packages resolved)
ruff format --check .                   PASS (47 files)
ruff check .                            PASS
mypy src tests                          PASS (17 source files)
pytest                                  PASS (45 tests)
uv build                                PASS (sdist + wheel)
wheel contents                          PASS (domain package included)
git diff --check                        PASS
forbidden Any/shell/console scan        PASS
```

## Review Result

No blocking or major finding remains. T002 provides the typed foundation needed by T003 persistence without introducing persistence, orchestration, model adapters, parallelism, a DAG, or a vector database.
