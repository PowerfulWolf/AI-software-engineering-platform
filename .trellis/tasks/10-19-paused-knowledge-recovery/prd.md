# Recover a service-paused knowledge preparation without inventing execution facts

## Goal
Preserve accepted K1 progress and safely continue the same Requirement after a controlled
service restart pauses the next WorkItem during knowledge preparation. A knowledge phase with
no main-role InvocationStart must not be diagnosed as an unknown Coder invocation by default.

## Observed symptom
After Run4 progress was accepted and the old service reached official READY/exit, the next
WorkItem is WAITING_DEPENDENCY with a released claim. Its knowledge outcome reports
FAILED/SERVICE_PAUSED and executions=[]; the engineering investigation reports
INVOCATION_UNRECORDED and offers no resolution. These fields alone do not establish that no
provider ever started. The exact paused admission/owned execution facts must be authenticated.

## Requirements
- Reproduce the controlled pause at the actual knowledge-preparation/wait-consumer seam with
  temporary stores and fake ports before implementation. Keep genuinely unknown calls refused.
- Distinguish knowledge preparation, main-role execution and output/checkpoint acceptance.
- Retain exact Task/Requirement/WorkItem/claim/source/intent/outcome lineage and original frozen
  budgets, permissions, draft and accepted progress. Do not fabricate a stop or no-start proof.
- Use existing typed public investigation/resolution or exact engineering-plan paths for stored
  K1. If a stronger future receipt is necessary, define its backward-compatible contract first;
  never reinterpret an old empty list as that new fact.
- No production SQL repair, record/verdict rewrite, budget reset, Requirement recreation,
  maintenance edits to the K1 worktree or universal service-pause retry exception.

## Ownership / verification
Root owns this task, executable spec, integration, controlled deployment and public K1 recovery.
Worker run6 initially owns a focused new regression fixture only; no production code change
until the receipt contract and root cause are established. Independent reviewer native_owned
owns read-only facts/root-cause audit and later independent final review. Everyone shares the
maintenance checkout and must preserve others' edits.

Validation: deterministic red/green real seam, meaningful negative/lineage/unknown/budget tests,
focused existing knowledge/wait regressions, Ruff/strict Mypy and independent review. Deployment
uses official READY/actual exit. Rollback preserves all new/old facts and reader compatibility.

## Stored data disposition
Do not edit old SERVICE_PAUSED outcome or old platform-attention investigation. Re-evaluate the
exact original WorkItem through a public operation after deploying the repair. If old facts are
insufficient, prepare and separately approve the existing precise engineering recovery path,
preserving every original uncertainty instead of inventing evidence.
