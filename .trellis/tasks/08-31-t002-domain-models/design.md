# T002 Technical Design

## Data Flow

```text
untrusted JSON / Python input
  → Pydantic model_validate
  → immutable domain model
  → to_wire (JSON-compatible, omit absent optional fields)
  → canonical JSON Schema validation
  → future repository / ArtifactStore boundary
```

Pydantic models enforce both wire shape and same-object invariants. Checks that require another aggregate, Git, persistence, or policy history remain in later services.

## Public Seams

| Seam | Input | Output | Failure behavior |
|---|---|---|---|
| Model construction | untrusted Python object | typed Task, Agent Definition, or Artifact | raises Pydantic `ValidationError` |
| `to_wire()` | a valid domain model | JSON-compatible object with absent optionals omitted | cannot produce unknown fields |
| Artifact union validation | untrusted object + expected `ArtifactKind` | one discriminated Artifact subtype | rejects unknown/mismatched `kind` |
| Canonical Schema contract test | `to_wire()` payload + schema kind | no validation errors | test failure blocks merge |

These seams are accepted from the existing `schemas/*.json`, `docs/contracts.md`, and T002 milestone; no persistence or orchestration interface is introduced.

## Model Boundaries

```text
domain/
├── enums.py       # TaskStatus, AgentRole, ArtifactKind and report enums
├── model.py       # strict immutable base model and JSON wire value types
├── task.py        # Task aggregate and acceptance/constraint value objects
├── agent.py       # Agent Definition and machine permissions
└── artifact.py    # envelope, shared evidence/finding, four typed artifacts
```

## Same-Object Invariants

- Task acceptance IDs and labels are unique; `attempts <= max_attempts`; timestamps are ordered.
- Agent Definition output kinds are fixed by role; only Orchestrator can change state; no v0.1 role can merge.
- Artifact IDs, Evidence IDs, and parent IDs are unique and self-reference is rejected.
- Artifact kind determines producer role and typed content.
- All content Evidence IDs resolve to the envelope's Evidence list.
- QA `PASS` cannot coexist with failed/not-tested criteria, failed/error tests, or major/blocker findings.
- Review `APPROVE` permits only informational findings; `REJECT` requires a major/blocker finding.

## Deferred Cross-Aggregate Rules

- Required acceptance criteria belong to Task and are checked against QA in the Orchestrator/validator layer.
- Candidate revision equality across implementation, QA, and review artifacts belongs to ArtifactStore/state transition guards.
- Integrity SHA computation and `validated=true` ownership belong to ArtifactStore.
- Independent `run_id` checks across Coder, QA, and Reviewer require artifact history.

## Dependency Decision

- `pydantic>=2,<3` eliminates malformed/unknown external payloads crossing into the domain layer and provides typed boundary validation.
- `jsonschema[format]>=4,<5` plus its type stubs are development-only and eliminate drift between Python models and the committed cross-language Draft 2020-12 contracts, including RFC 3339 timestamp formats, without weakening strict type checks.

## Good / Base / Bad Cases

- Good: a typed QA artifact with resolvable Evidence serializes to JSON and validates against `qa-report.schema.json`.
- Base: an optional field is absent and `to_wire()` omits it rather than emitting schema-invalid `null`.
- Bad: a Coder produces a QA artifact, an Evidence ID is dangling, or Reviewer approves while reporting a major defect.

## Test Points

- One independent positive fixture per top-level model and Artifact kind.
- Negative shape tests for IDs, enums, extra fields, ranges, and timestamps.
- Policy matrix tests for Agent Definition outputs and Artifact producers.
- Cross-field tests for Task attempts, Evidence links, QA status, and review verdicts.
- Every positive wire payload is checked by the corresponding canonical JSON Schema with format validation enabled.
