# T002 — Task, Agent, and Artifact Domain Models

## Goal

Turn the accepted Task, Agent, and Artifact wire contracts into immutable, typed Python domain models that reject malformed or policy-inconsistent data before it reaches persistence or orchestration.

## Requirements

- Implement Pydantic v2 models under `src/ai_software_engineer/domain/`.
- Keep `TaskStatus`, `AgentRole`, and `ArtifactKind` in one canonical module.
- Cover Task, Agent Definition, the common Artifact envelope, and plan, implementation, QA, and review content.
- Preserve JSON Schema field names and JSON-compatible serialization.
- Reject unknown fields, unknown enum values, malformed IDs, and invalid timestamps.
- Enforce documented cross-field rules such as role/output ownership and valid review verdicts.
- Validate model-produced wire payloads against the repository's canonical Draft 2020-12 JSON Schemas.
- Add Pydantic as the runtime validation dependency and JSON Schema as a development contract-test dependency.

## Acceptance Criteria

- [x] Valid Task and Agent examples pass Pydantic and their canonical JSON Schemas.
- [x] Valid examples of all four Artifact kinds pass Pydantic and their canonical JSON Schemas.
- [x] Unknown fields and malformed IDs are rejected.
- [x] Agent role/output mismatches are rejected.
- [x] Artifact producer role/output-kind mismatches are rejected.
- [x] Reviewer `APPROVE` with `MAJOR`/`BLOCKER` findings is rejected.
- [x] Reviewer `REJECT` without a `MAJOR`/`BLOCKER` finding is rejected.
- [x] Artifact Evidence references must resolve to envelope Evidence IDs.
- [x] Ruff, strict mypy, pytest, and dependency lock checks pass.

## Out of Scope

- SQLite repositories, state reducers, ArtifactStore persistence, or SHA computation.
- Cross-artifact checks such as matching a QA report to a Task's required criteria or candidate revision.
- Git worktrees, Context Builder, Agent adapters, and orchestration.
- Dynamic roles, parallel execution, DAGs, vector databases, or model-provider SDKs.

## Rollback

Revert the T002 commit. T002 has no database migration, persistent runtime data, network call, or external resource.
