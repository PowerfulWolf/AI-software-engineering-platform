# AI Team evolution: bounded corrections

## Domain and responsibility

Project Knowledge describes evidenced project facts; Specs prescribe scoped engineering rules;
execution prerequisites describe a particular execution environment; capabilities are explicitly
registered, policy-bound actions. Installing a tool does not grant an Agent authority to use it.

Product owns requirement clarification, Designer technical decisions, Planner work decomposition,
Coder implementation, QA acceptance evidence, Reviewer independent scrutiny. Manager coordinates
conditions, dependencies and human decisions. Deterministic services enforce identity, permissions,
leases and gates. Historical learning never substitutes for current candidate verification.

## Slice 1: learning from ordinary delivery

Add optional bounded `project_observations` to implementation/QA/Review reports. Each observation
has an ID, title, descriptive fact, applicability, and nonempty evidence IDs validated against the
sealed report. Empty defaults serialize as absent so historical artifact hashes remain valid.
Observations are proposals, even when their parent report passes; they do not assert delivery DONE.

Extend the existing explicit collector, not a second memory system. Preserve exact repository,
Task, artifact digest, candidate, role and observation identity; redact text before proposal storage.
Publish only through existing exact human authorization. Background knowledge is the default;
facts/one-off environment conditions must not silently become mandatory Specs or executable Skills.
Existing `KNOWLEDGE_RESOLUTION` wire/UI drift is repaired in the same slice.

GET stays read-only. Collection remains an explicit resumable operation in this slice; production
automatic capture at accepted role checkpoints is a separate integration milestone and must not be
claimed complete. Upstream Product/Designer/Planner observation capture also remains a later seam.

The current Project learning page shows observation, applicability, evidence, role/candidate,
pending/authorized/published status. Publication uses a scope mutation lock so concurrent knowledge
selection updates are not lost. New requirements retrieve selected knowledge through the existing
snapshot/consultation flow; frozen requirements stay unchanged.

## Slice 2: Manager prerequisite incidents (not yet implemented)

Connect actual inconclusive verification recovery to persisted Manager incident/resolution records,
preserving candidate and report evidence. Repeated Continue before resolution must not call models.
An approved resolution must request a fresh bounded readiness check, not assert QA PASS. Changed
capability scope still requires exact plan approval. Do not wire an in-memory recovery facade and
describe that as a durable production fix.

## Safety and compatibility

No historical verdict, journal, approval, Task or frozen context rewrite; no ambient Agent writes to
knowledge; no self-approval; no tool install or permission expansion from model observations.
Old artifacts stay readable. Older binaries cannot consume newly added observation-bearing reports;
after adoption roll forward or keep compatible readers rather than deleting history.

## Validation

Contract fixtures cover old hashes, all report kinds, unknown evidence rejection, schema parity,
redaction, idempotent collection, pending/rejected isolation, exact authorization and A-to-B retrieval
for all six roles. Frontend tests cover each source variant without `undefined`, unsafe HTML or
cross-Project stale responses. Lifecycle audit distinguishes tested contracts from unconnected seams.
