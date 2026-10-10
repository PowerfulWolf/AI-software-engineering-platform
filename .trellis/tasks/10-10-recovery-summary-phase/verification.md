# Recovery summary phase verification — 2026-10-10

## Root cause and scope

The shipped summary computed its execution line from current `requestNodeExecution`, but computed
its phase line independently from durable `deliveryPhase`. With only a retained terminal Task and
a BLOCKED parent, this paired a historical blocked phase with a current exact approval or active
recovery. The same independent phase lookup existed in `currentOperationProgress.title`.

`deliveryPhase(item, node = null)` now accepts an already-computed read-only node. Current exact
approval means `恢复待确认`; platform processing means `恢复准备`. Without those flags, including
the default null parameter, its existing path and role phase mapping are unchanged. Both summary
and current Operation progress pass their own same evaluated node. It does not compute another
node, modify any state or introduce recursive calls. `recordedOperationOutcome` remains unchanged.

## RED → GREEN

- Direct real summary entry, before fix: **5 failed / 24 passed**. The exact prepared decision and
  four normal/read-contention processing cases reproduced `交付阶段 · 已阻塞` beside current recovery.
- Real `requestOperationHistory` entry, before shared phase fix: **4 failed / 39 passed**. Normal
  and busy/unavailable/timeout processing reproduced `当前阶段 · 已阻塞 · 平台正在处理恢复`.
- Tests use the actual Team issue string states `busy`, `unavailable`, `timeout`. They cover
  stale/foreign/consumed/unreadable approval rejection, updated durable failure, actual Coder/QA/
  Reviewer claims, explicit business gates, read-only byte equality and sealed historical outcomes.

```text
node --test tests/team_view/product-execution.test.cjs \
  tests/team_view/engineering-wait.test.cjs \
  tests/team_view/delivery-status.test.cjs \
  tests/team_view/operation-progress.test.cjs
134 passed, 0 failed, 597 ms

node --check src/ai_software_engineer/team_view/app.js
passed

git diff --check
passed
```

Existing control availability, capabilities, exact approval callbacks and node priority were not
changed. Both new and existing tests confirm no automatic Coder-running claim and no authority
restoration from retained Team data. No full suite or production operation was run by this task.

## Independent review and browser ownership

Read-only reviewer `/root/coder_python_tooling_fix/joint_schema_review` reviewed the final shared
seam and independently reran the four files: **134/134 passed (364 ms)**; syntax/diff checks passed.
It reported no remaining or new findings, confirmed no extra node evaluation/recursion, retained
default phase behavior, real-string Team gates and unchanged historical sealed BLOCKED outcome.

Root owns `tests/team_view/browser/recovery-read-contention.test.cjs`, real Chrome acceptance,
an additional independent review, integration and deployment. This subagent did not edit that
browser test. Source, both Node tests and spec were released before browser GREEN acceptance;
only this task's evidence/allowlist files were subsequently updated.

Root reported final real Chrome fixture acceptance:

```text
NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules node --test \
  tests/team_view/browser/recovery-read-contention.test.cjs
1 passed

NODE_PATH=/tmp/ase-ui-browser-check-20261010/node_modules node --test \
  --test-name-pattern='one unchanged running operation follows|sealed succeeded command outcomes' \
  tests/team_view/browser/execution-history.test.cjs
2 passed
```

Screenshots for both display defects were regenerated at widths 1440/1024/390. Root inspected
390/1440 and confirmed current phase consistency and no horizontal overflow. These are isolated
fixture/real Chrome checks, not a claim that production has been deployed or delivery resumed.

Root's separate read-only reviewer `baseline_resume_contract` also released the final change
without blocking findings. Its independent key subset was **17 passed, 0 failed**, including
read-failure scopes, old/current approvals, new failures, three role claims, business gates,
Project boundaries and sealed history. It reviewed the new browser fixture's isolated routes,
retained reading and zero non-GET assertions without repeating Chrome or the complete Node group.

## 存量数据处置与回滚

No SQL/journal/Task/Operation/approval migration is required; this is a pure compatible display
change. Existing requirements, old failures, complete progress and all immutable bytes/hash remain.
Reload compatible frontend assets and refresh the original requirement to recompute its summary.
No approvals or delivery were executed by this task.

Roll back this frontend, tests and spec change and refresh the page. This does not rewrite old
facts, remove retained progress or stop any current role execution.
