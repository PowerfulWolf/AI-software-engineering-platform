# Implementation and verification plan

## Ownership

- Root maintains this task's documents, `.trellis/spec/core/active-knowledge.md`, architecture
  documentation, integration and the separately authorized deployment/recovery.
- `native_owned_wait_fix` owns Worker lifecycle, resolution/domain/queue integration, exact
  legacy reentry, schemas and public native/MySQL recovery tests. Its delegated semantic
  worker owns only the agreed knowledge validator, observation and corresponding unit tests.
- `run6_owned_uncertainty` is the independent read-only reviewer. It may run isolated tests
  after explicit handoff of the exclusive test database. It never changes the implementation
  or K1 checkout. `recovery_deploy_audit` independently observes production facts read-only.

## Sequence

1. Preserve the exact offline red replay and its original report. Add minimal contract RED
   tests at the actual consultation/Worker/public recovery seams before source changes.
2. Implement safely sealed semantic rejection observations and the shared pure validator;
   maintain pre-publication secret guard and all exact READ membership checks.
3. Route known semantic rejection to nonterminal `INVALID_OUTPUT` engineering wait. Route
   other `KnowledgeError` to `PLATFORM_BUG` wait only; preserve `KnowledgeGapRaised` and
   fail closed when claim ownership has been lost.
4. Add a sibling proof scope for the precise legacy expired no-main BLOCKED case. Hold the
   actual Task flock through fresh proof and Requirement checkpoint append. The ordinary
   Dispatcher reclaims; fresh Worker refuses before any model call and commits its own wait.
5. Add `RETRY_REJECTED_KNOWLEDGE_PREPARATION` through existing inspect/resolve/continue,
   revalidate under final Task/MySQL fences and consume one ordinary work attempt exactly once.
6. Run pure/unit/contract tests, then the isolated native/MySQL public chain and refusal
   matrix. Independently review, run strict checks, regenerate schemas and check old wire SHA
   stability before committing. Serialize database reset and mutating test runs.
7. On a verified idle boundary, stop the exact current service through controlled shutdown,
   integrate reviewed platform code into `main`, restart and independently confirm health,
   code revision, current Requirement identity and all retained history/draft hashes.
8. Recover the original K1 using fresh exact public operations and current checkpoint digests.
   Record delegated engineering approvals, new ordinary work and independent QA/Review facts.
   Any further blocker is diagnosed from exact durable facts; no direct SQL repair or reset.

## Required assertions

Positive recovery reaches the same Task's Coder, independent QA and Reviewer on one candidate.
Before the exact engineering resolution, new model invocation count remains zero. Historical
RETURNED outcomes, UNKNOWN execution, Requirement BLOCKED checkpoints and accepted progress remain
byte-for-byte unchanged. New work has fresh work/claim/run/context identity; ordinary work rises
by one, provider failure counts and timeout window do not change. Exact repeat/crash replay
returns the same successor without a second debit.

Negative tests cover wrong scope/claim/source/checkpoint/context/snapshot, absent or incomplete
outcome/native stop, valid assessment, SEARCH-only and other-run READ, existing target main
start/outcome/output/artifact/acceptance, valid or successor claims, Task lock contention,
complete draft drift, no authority, exhausted frozen work budget and unknown store errors.
Each refusal preserves queue/Task/journal/draft and cannot authorize a new model invocation.
