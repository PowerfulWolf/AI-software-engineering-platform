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
