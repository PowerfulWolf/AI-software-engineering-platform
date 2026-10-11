# Verification

## Root cause and red test

Production evidence supplied by the parent: failed Coder attempt 11 and an old rejected progress from attempt 4 both bind input checkpoint 8. The old exact artifact has a committed typed WAIT_RESOLVED / RETRY_REJECTED_CODER_OUTPUT decision; it is not an input to the current invocation. The old settlement guard rejected all `publication.checkpoint_sequence >= proof.checkpoint_sequence`.

Before implementation, the actual isolated MySQL regression
`test_consumed_rejected_progress_at_same_input_checkpoint_does_not_block_settlement`
failed in public `DeliveryWaitService.handle -> settle_stopped_budget` with the exact
`QueueConflict: 原失败调用之后已有接纳产物, 暂不能额度收尾` (1 failed, 3 deselected, 3.88 s).
The fixture publishes under a real owner-fenced claim, consumes a real rejected-output
resolution, claims the successor at the same input checkpoint, and records a real
exited failure process with complete unchanged draft inventory. No model is called.

## Implementation and independent review

The existing typed consumed-decision reader accepts an optional current transaction
cursor. Its complete digest/closed work/deterministic successor validation is preserved.
The new pure predicate compares task/work/lease/dispatch/checkpoint/run/context/source/
artifact ID/SHA and refuses current work/Run and actual later checkpoint. Settlement,
rejected-output SQL consumption and collector use this same predicate. Old fake readers
without the optional capability retain the former strict behavior. No schema, wire,
approval, adoption, retry-budget, branch or artifact mutation contract changes.

Parent and independent audit Agent reviewed the three guard sites and same-cursor fence;
neither found a blocker. A separate test owner independently reproduced the collector
second-round red, then ran their complete native capture/inspection/replay regression
plus 15 negative identity/consumption cases against this production source: **16 passed**
(53.02 s). Those tests are in separate commit `99e94aa`, to integrate alongside this one.

## Incremental commands and results

Commands use `PYTHONPATH=src` and the existing main checkout `.venv/bin` executables;
the MySQL fixture enforces a dedicated isolated test database. The test window was
exclusive; no production SQL, services or models were operated by this subtask.

- `pytest -q --tb=short tests/work_queue/test_stopped_budget_settlement_mysql.py`: **10 passed**, 25.47 s. Public same-checkpoint retirement, atomic/replay/crash behavior and six genuine SQL read-path negatives: absent consumption, SHA drift, lease drift, current work, later checkpoint, corrupt resolution digest. All rejections preserve Task/events/item/publications/claims and publish no public success.
- `pytest -q --tb=short tests/work_queue/test_rejected_output_mysql.py tests/work_queue/test_wait_resolution_mysql.py`: **26 passed**, 7.72 s. Includes two real rejected rounds with immutable historical publications and claims, exact replay and unchanged retry/event history.
- Ruff lint and format-check on the four changed Python files: **passed**.
- Strict mypy on the four changed Python files: **passed**.
- `git diff --check`: **passed**.

The new two-round SQL fixture uses explicit times based on successor `created_at` and
an injected queue clock; it does not rely on wall-clock delay to claim a future fixture item.
No full suite was run, per user preference.

## 存量数据处置

This subtask makes no production data changes. After deployment the parent must use the
original K1 Requirement's exact public HANDLE action. Before/after compare the original
Task event prefix, all claims/publications, retry accounting and immutable invocation/
stop/capture records; only one terminal budget event and queue closure may be appended.
No new business Requirement, direct SQL, synthetic stop, refund, implicit approval or
manual modification of the retained worktree is authorized by this fix. The original
Requirement's existing recovery-plan and exact approval path remains required.

## Risks and rollback

Other independent publications still block safely; missing/corrupt consumed history is
not repaired or ignored. The additive helper/reader do not make historical invalid output
usable. Before consuming the public action, revert the code commit if necessary. After
terminal consumption retain compatible typed settlement readers and all original audit
records/drafts; use a forward fix rather than deleting history or reviving the Task.

## Production stock verification — 2026-10-12

The integrated code was pushed and deployed at `176997764f8b0d3a43c0b4daee5ee6424e9aae71`
using a successful controlled service stop/start. The registered target repository was
fast-forwarded to the same clean revision while the service was stopped. The original
K1 Requirement remains `delivery_multi_8a5103309c232515bcf733947d32830365dd02c6`;
no duplicate Requirement was created.

The exact public HANDLE operation
`operation_9b64d4fabd2d9279625629bc748973b0` completed `SUCCEEDED`. Its typed result
reports `ENGINEERING_WAIT_HANDLED / BUDGET_EXHAUSTED`, and directs a fresh recovery
proposal and exact approval under that original Requirement. The original stopped
Task `task_recovery_8ca06fa0aec236ab940597ad1482bfc8` became `BLOCKED`, and only its
current work item was closed. It was not revived or given additional attempts.

A before/after consistent read-only SQL snapshot audit passed. It verified:

- The Task changed only its status and update time; attempts remain **11**, and the
  complete retry account is unchanged.
- The original eight StateEvents remain an identical prefix; exactly one legitimate
  terminal event was appended. Its original sealed settlement time is preserved on
  replay rather than replaced with a new decision time.
- All eleven claims and all three accepted publication records are unchanged.
- The original invocation start, failed outcome and real failed process-stop record
  retain their original digests. The truncated unknown failure was not reclassified,
  refunded, corrected or treated as a usable result.
- The retained worktree HEAD, branch, index, all thirty dirty paths, complete file
  bytes/modes and complete inventory match the pre-settlement capture. The full patch
  remains 604,438 bytes with SHA-256
  `c085ce5563e49e446c861eb4771cc3634af2f8ad0ebb27181175d9cbf80211f5`.

The read-only audit reported `audit_passed=true`, `attempts_unchanged=true`,
`original_failure_stop_claims_accepted_and_history_preserved=true` and
`new_state_events=1`. It always rolls back and closes its connection; no diagnostic
Host, DDL or direct production SQL update was used. Private raw snapshots and source
bodies are excluded from the repository.

The same original Requirement's public Continue action was then submitted without
an approval digest to prepare a fresh recovery plan. That proposal is separate from
settlement success. K1 is **not delivered** at this boundary: it still requires the
new exact plan approval, a claimed Coder, candidate-bound independent QA and Review,
and a verifiable final handoff. Preserve the stock audit and all original records if
subsequent recovery fails; do not reopen the terminal Task or discard its draft.

## Exact successor preparation — 2026-10-12

The original Requirement's proposal Operation
`operation_8b1b11c81dabbb24469eb9cf8672cdb1` completed successfully. Its recovery
plan is `5536cf4e59ca28db0213bd719d50860d14e6d4dbba1489a4c583e176b89e077a`.
The plan retains the complete thirty-file draft, approved solution and original
write permissions, targets clean revision `176997764f8b0d3a43c0b4daee5ee6424e9aae71`,
and names successor Task `task_recovery_5536cf4e59ca28db0213bd719d50860d` under
the same original Requirement. It uses the ordinary complete Git seed path;
there was no invented patch conflict, partial reapplication, scope expansion or
new business Requirement.

Under the user's existing engineering delegation, the exact plan digest was
submitted once in Operation `operation_062c258f7ca2307dc9c75fde02a57c11` at
`2026-10-11T20:14:08.115216Z`. Public preparation progress sealed
`AUTHORIZATION_RECORDED` at `20:29:48.464301Z` and `TASK_SEALED` at
`20:45:09.758661Z`. At the read-only SQL observation `20:46:00.981228Z`, the
successor Task had not yet been committed to SQL, and there was no current
WorkItem, active lease or new Coder invocation. A sealed Task draft and an
execution claim are distinct facts; neither approval nor preparation is K1
delivery. The Operation was still running without a terminal error.

While that production Operation runs, maintenance remains in isolated worktrees.
Do not replace its service binary, update the registered source checkout,
resubmit the approval or rewrite its state to accelerate preparation. The
independently reviewed idle-dispatch, bounded summary/UI and operation-local
immutable-decode changes require a safe idle controlled deployment. Runtime
deployment alone does not authorize a new Task source baseline: any later source
update must use the original Requirement's explicit current baseline/approval
flow. Retain this exact approval and all settlement history through that step.

## Original Requirement crossed first claimed execution — 2026-10-12

The same single approval Operation continued; no second approval, Requirement or
manual production state update was submitted. Public preparation records now include
`DISPATCH_COMMITTED` at `2026-10-11T22:13:07.559855Z`, `SEED_VERIFIED` at
`22:28:35.604268Z`, and `EXECUTION_CLAIMED` at `22:28:46.705971Z`. The dispatch
digest is `4af8c641fe7135cda3510bc45797c44e3d25f2ada959009f91b046a3d41e510a`.
Dispatch persistence and Task materialization are different boundaries: the latter
follows seed and additional Context preparation.

Read-only SQL and native invocation records observed the exact successor Task as
`IMPLEMENTING`, attempt 1, at approved base
`176997764f8b0d3a43c0b4daee5ee6424e9aae71`, with current Coder WorkItem
`work_9f2c8d58fcb43f582178d25e647cd1de7ef6fecee6851186cf391057966943db`.
Run `run_cd17fc4c9d254fdf8ae13f19d0cc1fe9` has an invocation start at
`22:30:47.480310Z`. Its ACTIVE lease continued heartbeats through the last
`22:48:00Z` observation. The public completed-call records contain two successful
`codex/gpt-6.1-sol` Coder knowledge phases: intent and assessment. These are real
model calls, separately recorded from the main development process.

At `22:45:54Z`, a structured process inventory first observed the service-owned
Codex process and its code-mode-host child. They were still observed at `22:48:10Z`.
This proves process startup observation, not candidate completion or a verdict; the
invocation start and a valid claim alone did not prove the main process had started.
Its precise preceding preparation frame remains unknown. At the latest bounded
observation there was still no outcome, candidate, QA, Review or final Handoff, and
the original Operation remained RUNNING without a terminal error.

The preparation's multi-hour latency is a platform performance failure, even though
it eventually progresses. Isolated maintenance repairs now cover bounded summaries,
idle polling, complete-byte decode reuse, complete Product approval-prefix reading,
local authorized Task facts and the two-observation terminal window. Incremental
evidence and explicit scope limits are in their respective tasks. Frontend summary
repairs separately restore recovery progress, neutral command completion and coherent
scope observations. These changes are committed/pushed on the maintenance branch,
but production is still the original `1769977` instance while its owned work runs.

No current stopping boundary can cancel this active preparation safely: controlled
shutdown drains the admitted Operation, and `resume` merely removes drain. Do not
force-kill the service to deploy, equate service restart with original Run stop, or
reuse an unsealed dirty seed as a successful receipt. Continue monitoring the same
Run, use actual outcomes/waits and independent candidate-bound QA/Review, then deploy
maintenance at a genuine idle boundary. No full test suite was run by maintenance.

## Real Coder rejection and safe runtime deployment — 2026-10-12

The original Run `run_cd17fc4c9d254fdf8ae13f19d0cc1fe9` finished with a genuine
native completed stop at `2026-10-11T23:05:22.278533Z`, returncode 0 and output present.
Stop digest is `003759142ac5d3da6717ce457e28c335ea4b2463583a9e48a75ba7349541efb9`.
The original result is FAILED / INVALID_OUTPUT / nontransient / no Artifact,
duration 2082576 ms. Native diagnostic recorded GIT_CONTRACT, output digest
`43e3d373e4df98707542e06bb468aa05269a55ceff2dff2196d2b8b6a7753fec`
and 10529 bytes; the precise historical validation subcause was not preserved.
Ephemeral raw output no longer exists, so later slice tests cannot establish its
specific historic cause. Outcome digest:
`7576ef54a4ff31cc2f22f2df0589288e3d841c753a916a7705b9221bf476a090`.

The real lease was RELEASED at `23:05:30.177671Z`. Operation
`operation_062c258f7ca2307dc9c75fde02a57c11` finished SUCCEEDED at
`23:06:13.561468Z`; this records successful command settlement, not K1 delivery.
The original successor Task remains IMPLEMENTING, attempt 1, revision 2. Its
Coder WorkItem remains WAITING_DEPENDENCY, with budget available and retry not
authorized. Original base is still 1769977. The same original branch retains
approximately 30 legal dirty paths, unstaged, with no candidate. Old terminal
Task `task_recovery_8ca06fa0aec236ab940597ad1482bfc8` and all 11 attempts remain
unchanged.

Read-only consistent SQL found no ACTIVE claims or RUNNING work. Controlled
stop then produced exact READY, drained and saved all operations, and confirmed
old PID 82883 exited. Only afterwards the main runtime fast-forwarded to
770c02e, `uv sync --locked` retained dependencies, origin/main push succeeded,
and a new service PID 54268 started. Public console/admin report ready,
CONNECTED MySQL, available Codex and no restart required. Registered repository
source, Task source, Coder HEAD and all approvals were deliberately unchanged:
runtime deployment is not permission for a source rebind.

The public scoped operation summary returned 503 under the real 330-operation
history. Investigation identified five valid DELETE no-resource results and
54 historical CONTINUE operations returning a different native child delivery
ID under a parent intent. Typed original bytes and chains are intact. New summary
projection incorrectly rejected that legitimate old history. Compatibility is
being fixed in its own task without guessing parent-child authority or rewriting
records. This deployment therefore does not establish complete UI readiness.

Current K1 investigation has CHECKPOINT_UNAVAILABLE / OUTCOME_REJECTED and no
permitted resolution. The native stop is trustworthy; this is not timeout,
provider outage, expired lease or an unknown live process. Existing recovery
supported unavailable WORK_INTERRUPTED and one specialized rejected progress
case, leaving this ordinary stopped INVALID_OUTPUT without a complete user path.
The new uniform proof/cause, human PAUSE, fresh RESUME and ordinary work recovery
is being validated separately. No production SQL fact was manually changed,
no duplicate Requirement created, and no QA/Review/Handoff or DONE claimed.
