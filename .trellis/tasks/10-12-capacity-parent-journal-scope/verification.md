# Verification — 2026-10-12

## Outcome and exact scope

Only `recovery/context_capacity.py` changes production behavior: one source observation owns
one local map of existing JointJournal readers. Initial retirement and both parent helpers
retain all complete-byte/hash/path observations and current decisions. The existing decoder
cache is cleared together with the map on every exit, including retained failure tracebacks.
No public signature, Schema, SQL, approval, Task/Requirement status, Context scanning or
execution policy changed. Other authors' backend/frontend/summary files are outside this task.

## Red and green evidence

Real temporary stores contain a two-record retired Requirement plus its one-record replacement.
The source observer executes the actual retirement, parent and JointJournal readers; unrelated
SQL, baseline, approved-stage, Context and Git ports are explicit offline fixtures.

Before implementation, the focused test reached its intended assertion:
`JointCheckpoint.model_validate_json` was called **9 times instead of the required 3**.
After implementation, it is called **3 times**. Every file is still read by Journal three times
and independently by regular preflight three times: **six complete reads per file**, not three
total reads. Both reading ports are separately counted in the final regression. Reusing the
same reader for the next public discover starts cold: six cumulative Journal reads and six
cumulative preflight reads per file, with six cumulative decodes across three files.

The original SQL, claim, no-start and capture ports each run twice per observation. Full old
patch content remains identical. Tests reject same-size/mtime historical corruption, missing
history, symlinks, resealed ancestor/stale successor and newly corrupt retirement records;
a valid appended tail is visible on the final parent read. Normal and retained-exception exits
leave local journal decoder caches empty.

## Incremental checks

- Author's six-file compatibility command in `task.json`: **59 passed in 12.82s**.
- After adding the explicit regular-preflight counter, the focused count test: **1 passed
  in 0.67s**; it is already included among the 59 distinct author cases.
- Ruff check and format check: **passed**, two files.
- Strict mypy: **passed**, two files.
- `git diff --check`: **passed**.
- Independent reviewer `/root/summary_result_scope_compat`: static review **no blockers**;
  new scope/source/joint-history-snapshot incrementals **42 passed in 1.60s**. This overlaps
  the author's cases and is not an additional 42 distinct cases. Reviewer confirmed the final
  preflight-counter refinement and maintained the scoped PASS.

No full suite, production/model/service access or shared database connection was used for
this implementation. Fixture decoder reduction does not establish production end-to-end
latency, total heap/RSS improvement or the absence of other repeated recovery costs.

## 存量数据处置

无需改库或迁移文件，所有既有 Requirement、Task、Operation、审批、收据、历史补丁和工作区
保持原 bytes/hash。当前有交付执行时不部署；由 root 等待空闲后通过受控维护重启加载代码，
原需求按已有精确审批/继续入口执行。不得重建需求、补造 stop/claim 或更改旧失败。

Rollback restores the prior parent reader composition while execution is idle, retaining all
durable history and preserved work. It only restores repeated decoding cost.
