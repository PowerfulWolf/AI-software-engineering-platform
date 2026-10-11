# Verification and stock data disposition

## Root cause and red loop

The original summary added a stricter equality assumption than the complete
Operation contract/real producers: result delivery had to equal submitted delivery.
Projection occurs for the entire Team inventory before scope filtering. Consequently
one lawful project-only DELETE result, or a historical same-Project native result,
made every Requirement summary fail with fixed 503 OPERATION_STATE_INVALID.

The actual ManagerConsoleAdapter DELETE producer was exercised through
FileConsoleOperationStore submit/claim/succeed, complete hash-chain replay and
GET /api/v1/operation-summaries: baseline red returned 503 instead of 200.
The two independent-result cases also failed with the scope-equality exception.
The shipped JS hydration red returned the independent result's coder_recovery
approval for the original Requirement via the intent-checkpoint fallback.

## Final incremental validation

Run from this isolated worktree with the existing interpreter, PYTHONPATH=src.

```sh
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest tests/web_console/test_operation_summaries.py -q -m 'not mysql'
node --test tests/team_view/operation-summary-reading.test.cjs tests/team_view/recovery-progress-summary.test.cjs tests/team_view/operation-capabilities.test.cjs tests/team_view/operation-progress.test.cjs tests/team_view/stale-operation-notice.test.cjs
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/mypy src/ai_software_engineer/web_console/summary_models.py tests/web_console/test_operation_summaries.py
```

Original commit Python: 25 passed; real store/HTTP/schema tests without MySQL or
models. Original commit Node: 83
passed, actual app.js/fake HTTP and safe DOM, including zero-POST stale approval
callback and independently labelled expanded audit. Ruff check/format, strict
Mypy (two changed files), node --check and git diff --check passed.

The large-plan summary test's existing artificial CREATE result was corrected to
carry its actual newly created delivery/checkpoint. Three existing Node fixture
cases likewise now carry Project/delivery/checkpoint identity instead of a
delivery-bound resource-free result. No production predicate was relaxed to make
these fixtures pass. CREATE_PROJECT without a submitted ID retains actual result
identity; old-summary compatibility still gates every complete result independently.

Complete numbered history bytes and complete HTTP GET wire remain unchanged.
Existing foreign Team/Project, corruption, same-mtime mutation, predecessor/hash,
active-completeness, cursor/ETag, cache bounds and fresh-write tests remain green.
No full suite, production HTTP mutation, model, Host, SQL or service operation.
No actual browser visual inspection or production deployment was performed.

## Existing data

No SQL/file migration and no Operation rewrite. The existing valid history is
projected with exact intent ownership and separate result locators. At a verified
idle boundary, load this version through controlled maintenance restart and
refresh the original Project/Requirement. Do not delete an independent result,
invent a parent/child association, recreate the Requirement, or change old approval
or failure bytes. Current delivery approval/QA/Review gates remain required.

## Rollback and limits

Revert this read-side code/assets/generated summary schema commit. Keep every
complete Operation and approval; the old reader may again fail for these histories.
This repair restores lawful history reading and prevents unrelated result authority;
it does not establish K1 candidate/QA/Review/Handoff completion, prove memory-leak
absence, or provide a general resource association service. Independent review
and safe deployment belong to the parent maintenance workflow.

## Independent review correction: edited draft navigation

Independent review found that UPDATE_REQUIREMENT is a legitimate replacement
producer: it writes a new draft, retires the exact old ID, and returns the new ID.
The legacy `ui.test.cjs` refresh-preservation case was red after the initial result
scope fix because the common result authority gate correctly excluded the new ID,
but the old edit navigation incorrectly consumed that gate.

The correction separates navigation from delivery authority. It requires a
successful complete UPDATE, exact original Team/Project/ID/checkpoint and exact
replacement ID/Project/checkpoint in the current Team snapshot, with the old draft
absent. Modern summary refresh explicitly reads the exact UPDATE after Team has
removed the old selection. It preserves page, Project and selection fences across
awaited reads. `operationResult` remains null; replacement stage, approvals and
baseline cannot attach to the old draft.

The new Python composition regression uses real Update producer → Operation
hash-chain → HTTP Team/summary/full GET with the shipped `refreshSnapshot` in a
Node VM. It verifies Team publishes the replacement first, exact full GET once,
no full-list polling, zero POST, and no old-draft approval. It separately delays
the full response while a user changes selection, Project or page and asserts
zero unintended navigation. The focused legacy UI red is now green.

Final correction incremental results: Python summary file 26 passed / 15.27 s;
five related Node files 85 passed / 0.48 s; focused legacy UI 1 passed / 0.70 s.
Strict Mypy passed on the three Python files. The existing preparation fixture
was brought up to the unchanged JointBackend protocol with the exact typed
`verify_unstarted_design_rejection` method that raises AssertionError; draft
mutation must not call that unrelated recovery path. Focused edit/delete/modern
refresh fixture checks were rerun together: 3 passed / 0.98 s. Ruff check/format,
both JS syntax checks and diff checks passed. Independent review separately
reran the modern composition, legacy edit and 85 related Node regressions and
approved the corrected navigation without widening result authority.
No production mutation,
service operation, SQL, real model or full suite was performed.

No stock-data repair is needed: this correction reads existing exact UPDATE
results and current replacement snapshots without rewriting old Operations,
checkpoints, retirements or approvals. Deploy through the parent's controlled idle
maintenance path. Refresh continues to show exact current Requirement identity;
the correction does not authorize a requirement recreation or delivery approval.
Rollback reverts this frontend navigation and documentation/test follow-up while
retaining all durable records. Browser visual QA and production deployment remain
the parent workflow's responsibility.
