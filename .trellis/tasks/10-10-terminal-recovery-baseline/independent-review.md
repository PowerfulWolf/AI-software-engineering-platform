# Independent review of root-owned recovery/UI integration

This file does not approve this worker's own baseline implementation. The review covers root's
workspace snapshot plan integration, Console summary/UI and two reusable patch detection callsites.

## Findings requiring resolution

1. Modern source audit initially applied failed-Run/capture-stop-only requirements to all terminal
   modern Tasks, including the existing accepted SUCCEEDED coder-progress and pre-provider prior
   progress contracts. Root delegated exact final-route classification to the workspace worker.
   Prior progress presence alone cannot skip the audit: the production failed Run also has earlier
   accepted progress. Missing stop facts must not silently become a passing `None` snapshot.
2. `_terminal_sql_facts` initially selected only `id,payload_json` for work_queue_items, while its
   decoder verifies only ID. A contradictory SQL scheduling status versus CLOSED payload would pass
   the all-closed gate. Query raw task_id/status and require exact row/payload equality before
   applying the closed-state predicate; keep the reader SELECT-only and add drift negatives.

Both findings were sent to root; they must be rechecked after the corresponding worker's changes.

## Reviewed without additional findings

- Plan snapshot is optional/omitted for historical wire compatibility, changes the exact plan hash
  when present, and binds original Task/revision/hash, Run/Context/worktree/source/effective base,
  dispatch and capture. Native current-fact checks compare a fresh deterministic snapshot.
- The original Task lock is opened without create or symlink following. SQL collection avoids queue
  initialization and a nested global authority lock, and rechecks source/facts/inventory.
- Console keeps outcome, preserved progress and the approval action visible, grouping only
  technical identities and hashes in an optional collapsed block. Existing exact checkpoint,
  project, approval-signature and active-operation guards remain intact. Text uses safe rendering.
- Both patch-content callsites now reuse the existing `patch_secret_occurrences` detector. The
  detector remains conservative for unknown files, arbitrary text, metadata, incomplete hunks,
  credential literals and unproven references. No parser, secret pattern or permission was changed.

## Independent incremental verification

```text
pytest -q tests/recovery/test_workspace_plan.py tests/recovery/test_workspace_snapshot.py
  tests/web_console/test_manager.py tests/web_console/test_scope_contract.py --tb=short
117 passed in 30.26s

node --test tests/team_view/product-execution.test.cjs
20 passed

pytest -q tests/git/test_recovery_source_content.py tests/git/test_capture.py
  tests/context/test_source_secret_detection.py --tb=short
149 passed in 19.91s
```

No production operation, approval, reset, cleanup, service restart, real model invocation or full
suite was performed by this reviewer. Tests passing do not resolve the two uncovered findings.
