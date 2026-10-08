# Bug analysis: controlled restart

## 1. Root cause category

B, D, E: cross-layer lifecycle contract, integration coverage gap and implicit completion assumptions.
Join returning was treated as execution ending; process leader exit was confused with group/pipe stop;
Uvicorn shutdown was already committed before lifespan could refuse; config apply and CLI could race.

## 2. Why local repairs are insufficient

Increasing join time only delays abandonment. Waiting in lifespan cannot undo Uvicorn should_exit.
Killing a service PID neither seals the model's result nor proves its child has stopped. Watching only
delivery-native runners misses upstream structured runs, verification subprocesses and HTTP choosers.
Allowing RESUME on every REFUSED state silently bypasses persistence/stop failures. Recreating a
Requirement cannot reconstruct absent original execution facts.

## 3. Prevention mechanisms

| Priority | Mechanism | Implementation | Status |
|---|---|---|---|
| P0 | Lifecycle architecture | Admission gates + retained writes + conjunctive coordinator | DONE |
| P0 | Verifiable actual process proof | Trusted spawn-only registry; group/pipes/stop persistence | DONE |
| P0 | Replacement protocol | Exact instance/request/PID, private fsync record, shared flock | DONE |
| P0 | Fail closed | Timeout refusal; known failed-write/uncertain-stop latch | DONE |
| P0 | Real integration regressions | Uvicorn subprocess, HTTP cancellation, signals, shell lifecycle | DONE |
| P1 | Cross-file independent review | Core/script and host/runner reviewers do not judge their own files | DONE |
| P1 | Organization knowledge | Core executable contract + recovery checklist + operations guide | DONE |

## 4. Systematic expansion

Covered Console dispatcher, threadpool HTTP writes, knowledge worker, native and structured models,
command tools, candidate Git source reads, isolated verification, UI mock app/driver, MySQL relay and
native directory chooser. Reads remain available while draining; no read-side API starts delivery.
Port binding/identity publication happen before workers to avoid work in an unusable failed startup.

## 5. Knowledge capture

- Updated core lifecycle spec, its index and Console service contracts.
- Updated recovery-thinking to distinguish admission/completion/outcome/stop/publication.
- Added explicit old-binary upgrade and existing-data treatment; no missing historical stop is forged.
- No generated Trellis template tree exists here; static Schema parity is executable.
