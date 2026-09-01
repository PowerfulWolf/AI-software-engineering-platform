# T009 Technical Design

## Public seams

| Interface | Input | Output | Failure behavior |
|---|---|---|---|
| `SerialOrchestrator.run_task` | persisted NEW Task ID | immutable `DeliveryResult` | typed `OrchestrationError`; no speculative routing |
| `RunContextBuilder.build` | Task, AgentDefinition, explicit upstream Artifacts | deterministic ContextBundle | existing typed Context errors |
| `OrchestrationIdentityFactory` | Task/role/status/attempt | run/event IDs | invalid/colliding IDs fail at typed model boundary |

Tests observe behavior only through these public seams plus TaskRepository and ArtifactStore public
read APIs. They use real temporary SQLite/filesystem implementations and only fake the external Agent
execution boundary, time and identity generation.

## Data flow

```text
TaskRepository.get(NEW)
  → event(PLANNING)
  → Context(orchestrator, base, []) → plan → seal/store
  → event(IMPLEMENTING, plan)
  → Context(coder, base, [plan]) → implementation(candidate) → seal/store
  → event(QA, implementation)
  → Context(qa, candidate, [plan, implementation]) → QA PASS → seal/store
  → event(REVIEW, qa)
  → Context(reviewer, candidate, [plan, implementation, qa])
      → Review APPROVE → seal/store
  → event(DONE, [plan, implementation, qa, review])
  → DeliveryResult
```

Downstream Context sources are rebuilt from Artifacts read back through ArtifactStore, not from an
upstream Agent's implicit memory. Artifact sources use stable `artifact://<id>` URIs and canonical
wire JSON.

## Revision contract

`AgentRequest.source_revision` is the exact input revision represented by the ContextBundle. For
Orchestrator, QA and Reviewer, the output Artifact describes that same revision. Coder is the only
role that creates a new revision: its implementation-report Artifact may therefore differ from the
request revision, but its envelope `source_revision` must equal `content.commit_sha`. Every later
request and verdict uses that candidate revision exactly.

## State and Artifact guards

- `NEW → PLANNING` carries no Artifact; every later event carries the gate Artifact and the `DONE`
  event carries all four IDs.
- Plan, implementation and QA criterion IDs must exactly cover the Task criteria; QA must be PASS
  and Reviewer must be APPROVE.
- Direct parent lineage is fixed to `()`, `(plan)`, `(implementation)`, `(qa)`.
- Producer run IDs must be unique across the delivery chain; role, kind, task and Context identity
  are already enforced at AgentResult and are rechecked before state transitions.
- ArtifactStore owns sealing/digest/atomic persistence. Runner immediately reads each stored
  Artifact back before using it as downstream input.

## Error matrix

| Problem | Stable result | Durable checkpoint |
|---|---|---|
| Task not NEW | `TaskNotRunnable` | unchanged |
| missing/mismatched AgentDefinition | `OrchestratorConfigurationError` | unchanged |
| Agent FAILED/TIMED_OUT | `AgentRunFailed` | current stage |
| unexpected QA/Review verdict | `UnexpectedVerdict` | QA/REVIEW |
| criterion, revision, parent or run identity mismatch | `DeliveryContractViolation` | current stage; invalid Artifact not used as a gate |
| ArtifactStore/Repository/Context failure | original typed boundary error | last committed checkpoint |

T010 will classify and route these failures; T009 never guesses a retry.

## Good / Base / Bad

- **Good**: one fixture reaches DONE, four immutable Artifacts and five events reproduce the decision.
- **Base**: all orchestration tests run offline with FakeAgentAdapter and temporary local storage.
- **Bad**: treating Coder's base revision as its output commit, trusting free text, accepting missing
  criteria, or allowing QA/Reviewer to inspect different revisions.
