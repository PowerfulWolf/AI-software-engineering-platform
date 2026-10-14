# Validation and operations

Base: `4863eb49c038b4b271607ede314ffdad78ffc73b`; origin/main independently fetched and equal before integration.
Implementation is in the isolated `codex/controlled-pause-restart` worktree.

## Validation

- Ruff `check src tests` plus schema scripts passed; all 69 changed Python files format-check passed.
- Strict mypy src + changed maintenance/transport/inspection/baseline SQL tests: 381 files, clean.
- Full test-tree mypy has preexisting unrelated failures; no runtime change depends on those tests.
- Console lifecycle/inspection/API/epoch regression: 137 passed (`/tmp/ase-epoch-full-final.log`).
- Last maintenance depth/phase/security regression: 76 passed (`/tmp/ase-epoch-final3.log`).
- Contracts, fresh schema generation, real-Git baseline/reservation/invocation and fallback: 91 passed
  (`/tmp/ase-pause-contract-finish.log`).
- Isolated MySQL baseline pause suite: 35 passed; its three new fresh-claim cases subsequently 3 passed
  (`/tmp/ase-samebase-mysql-final.log`, `/tmp/ase-samebase-mysql-claim3.log`). Test-only field errors repaired.
- Prior real-session/native/Responses/worker pause suites passed; logs documented in implementation context.
- Independent Standards and Spec reviews performed in separate read-only agents. All code findings repaired;
  final wording about the 128-node maintenance reader bound corrected.

## 存量数据处置

No SQL migration or historical Task/Run/Artifact/verdict/approval rewrite. Original K1 is preserved.
Online old Host ordinary stop refuses OWNED_PROCESSES/UNCONFIRMED despite no active Operations. Old
in-memory reader has the already-fixed claim parser defect; disk update cannot repair the live object.
Deploy through the trusted local exact-identity fault-retirement channel, keeping REFUSED/UNKNOWN
historical facts. Repeated maintenance now archives the exact predecessor controls and completion tree,
blocks startup during partial phases and requires new inspection completion and normal admission.
Production action receipts and online verification are recorded separately after execution.

## Startup-lock follow-up

The first ordinary startup exposed a detached-launcher defect: the environment retained the
replacement-lock FD number while `Popen` closed the descriptor. A real subprocess regression
reproduced EBADF before the fix. Only the Console now receives the borrowed FD via `pass_fds`;
after composition it validates and closes the FD without unlocking the parent's shared ownership.
Supervisor/caffeinate receive neither FD nor selector. Embedded factories retain caller ownership.

- Real launcher + maintenance completion + service pause regressions: 62 passed
  (`/tmp/ase-start-lock-final.log`); the red and green single regression logs are
  `/tmp/ase-start-lock-red.log` and `/tmp/ase-start-lock-green.log`.
- Ruff check, scoped format check and POSIX shell syntax passed.
- Strict mypy src + launcher regression: 377 files clean (`/tmp/ase-start-lock-mypy.log`).
- Independent Standards and Spec delta reviews found no code blockers. The lifecycle spec was
  corrected to explicitly document the Console-only borrowed descriptor.

The old refused Host was retired through exact approved maintenance plan
`7d24f57c24f2c822ab6146ac814b1bfa2505b559727ff11e9a871f785d522fd7`, receipt
`a75253ba1c7bbfc83b0093c7041d362e08f9b3a20da3c8400ecfd96f23a4765b`.
Historical execution remains UNKNOWN. Inspection Host successfully served the project summary and
then completed an ordinary controlled stop. Maintenance completion plan
`c4264f6210b69588679b687891b55df26f73e8ffd42068e09756cbd57074eaac` was executed;
ordinary admission is durably saved. The launcher fix requires retrying startup, without resetting
maintenance controls or repeating retirement.

## Online acceptance (2026-10-14)

Implementation `d6236e8` and startup-lock fix `2781f32` were fast-forwarded into main and pushed.
The registered K1 clone was clean and fast-forwarded to the same main code revision.
Ordinary startup succeeded with PID 5175. A real idle `scripts/ase-console-service.sh restart`
then sealed matching READY for instance `console_instance_7bbef1ff1b04a9eba4181bb75c29cf40`,
waited for its actual exit and started PID 14455 with distinct instance
`console_instance_68a6677e3a7a5dc87a859278f3874e53`. Kernel signal-zero inspection confirmed
the predecessor absent. Successor is RUNNING and `/api/v1/console` reports normal mode and
`delivery_ready=true`. Evidence: `/private/tmp/ase-{before,after}-ordinary-restart-20261014.json`.

Sequential ordinary-mode GET checks all returned HTTP 200: console 0.009s, selected Project
summary 1.580s, complete team facts 1.796s, operation summaries 0.070s. The browser loaded the
team members, then after actual restart and reload connected again and displayed the demand list.
These timings are one local acceptance sample, not a general latency guarantee.

Original K1 remains the same Requirement and Task; no SQL, verdict, approved product scope or old
execution history was rewritten. Public exact-checkpoint investigation
`operation_bf06b6a4e534067f9f0de3ba678f9c56` succeeded with missing OUTCOME_UNKNOWN,
STOP_UNRECORDED and CHECKPOINT_UNAVAILABLE, no permitted resolutions. Public same-base preserved-draft
legacy preparation `operation_d22d6db0e1c7fdbc5e0dbbfefb344034` was safely rejected: existing original
capture/start records make the no-original-ledger legacy route ineligible. No stop confirmation was
invented and no successor Coder was launched. K1's old execution needs its own original-record
recovery evidence; the new pause proof cannot backfill it. The current service is available while
that historical engineering wait and its draft remain preserved.

The exact disposable MySQL regression container
`50fa8fe43503acdbfe26f43a952b089adc952fc274a869fffe2cba2d4c05e279` was removed after all tests.
Production MySQL and original K1 worktrees were retained.

## Rollback / limits

No automatic timeout/provider retry/refund/verdict; outstanding synchronous HTTP waits for real return.
Unverified session/EOF/final save still refuses READY. Coder pause requires exact approved baseline,
including same-base outcome proof; old continuation permissions are not expanded.
Rollback must first use controlled stop and retain a reader for additive SERVICE_PAUSED/service_pause
records and the new maintenance epoch plan. A pending epoch is completed only by retrying its exact
plan; old marker/admission must never be manually restored.
