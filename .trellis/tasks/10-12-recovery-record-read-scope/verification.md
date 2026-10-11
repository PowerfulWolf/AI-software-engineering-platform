# Verification and delivery notes

## Incremental checks

Only incremental suites were run; the full repository test suite is reserved for the user.
Use the main checkout's existing interpreter, with this worktree as cwd:

```sh
ASE_TEST_PYTHON=/Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python
PYTHONPATH=src "$ASE_TEST_PYTHON" -m pytest tests/recovery/test_record_read_scope.py -q
PYTHONPATH=src "$ASE_TEST_PYTHON" -m pytest tests/knowledge/test_store_read_limit.py tests/context/test_store.py tests/manager/test_execution_baseline.py tests/recovery/test_terminal_baseline_sql.py tests/recovery/test_terminal_baseline_context.py tests/recovery/test_terminal_source_inspection_scope.py tests/recovery/test_current.py -q
```

- The second command passed **41 tests in 183.77 seconds**. It includes unchanged SQL terminal
  fencing, old Context/baseline reading, public baseline service, before/after source inspection
  and current live facts regressions.
- All **10** new focused tests were independently verified by the native recovery reviewer:
  first run had 9 passing and one fixed-date test-fixture rejection; after replacing that
  fixture with the real `ExplicitRecoveryHuman`, the failing public-approval case passed in
  9.84 seconds. The implementer's corrected public-approval run also passed in 11.21 seconds.
  The production timing rule was never loosened. Earlier scope/context suites are additional
  checks, not counted again toward these 51 distinct cases.
- The public approval test performs real authorization, Task derivation, exact receipt and
  sealing writes against isolated file stores. It preserves all **18** facts observations,
  keeps original Task bytes unchanged and independently rereads authority per observation.
  The live source and SQL fixtures are deterministic isolated ports; no production connection
  is used. Warm record reuse still rejects changed live facts before accepting a sealed Task.
- The controller's actual continue method sees no active cache at its execution callback.
  Success/failure, same-size/mtime changes, envelope/key corruption, missing authority,
  nested-map poisoning, aggregate multi-root limits, valid large Context, non-UTF-8 Context,
  copied thread and same-thread asynchronous-child ownership are covered.
- Ruff lint and format check passed for all 9 changed Python files; strict mypy passed for
  all 9 (`MYPYPATH=src PYTHONPATH=src ... -m mypy <files>`). `git diff --check` passed.

Root and native recovery reviewers performed independent focused review; no code blocker
remained. The precise check commands are also recorded in `task.json`.

## Finite isolated performance measurement

The private probe `/tmp/ase-recovery-record-benchmark-20261012.py` builds a real temporary Git
and baseline fixture. Its complete Plan and Start serialize to **2,750,454** and **2,750,759**
bytes. It performs 12 rounds of actual binding selection, current selector, current-binding
requirement and complete required-context reads. Both modes have the same existing pure source
inspection scope, so the measurement isolates the new typed-record decoding reuse.

The final measurement is `/tmp/ase-recovery-record-benchmark-result-20261012.json`:

| Measurement | Full repeated decoding | Scoped immutable decoding |
| --- | ---: | ---: |
| Complete original file reads | 156 | 156 |
| Complete original bytes read | 231,154,644 | 231,154,644 |
| Full Plan decodes | 48 | 1 |
| Full Start decodes | 36 | 1 |
| Full authority decodes | 36 | 36 |
| Full binding decodes | 36 | 36 |
| CPU seconds | 3.106 | 0.363 |
| Wall seconds | 3.129 | 0.364 |
| Cache peak entries | 0 | 2 |
| Cache serialization accounting bytes | 0 | 11,002,861 |
| Cache entries after return | 0 | 0 |

The fixture reduced CPU/wall cost by approximately 8.6 times, with every original byte and
authority/binding decode preserved. A prior run measured 2.484 → 0.397 CPU seconds (about
6.3 times), showing normal timing variability. Independent 100 Plan deep copies took
0.0094 CPU seconds; that timer ends before any subsequent store read. The process peak RSS
was about 199 MB for the final complete probe. All cached model weakrefs were released
after scope exit, without forced GC or outputting raw Plans, contexts, source, credentials
or original journal records. The temporary Git worktree is removed after the probe.

These finite measurements do not assert total Python heap is bounded by the serialization
budget, establish absence of a long-running leak, or predict the full production approval
duration. Uncached SQL facts, recovery records, histories and other safety checks still execute.
The task made no production read probe while the authorized operation was active.

## 存量数据处置

No Schema/SQL/journal/approval migration is required; this task changes only repeated reading.
Existing K1 Requirement, Task, Operation, exact plan/approval, native execution history and
worktree progress remain valid and unchanged. No production Host, service or registered source
checkout was touched. Wait for the current authorized operation and role execution to end;
then load the repaired version with the normal controlled idle maintenance process. Inspect
the existing Requirement's latest durable state and use its existing exact approval/continue
entrypoint when applicable. Do not recreate the requirement, reset attempts or infer a stopped
execution from this optimization.

## Risks and rollback

The fixed record helper is internal trusted composition only. Extending it to other models
or async entrypoints requires another explicit contract and freshness/lifetime tests; authority
and current facts must remain outside reuse. Deep-copy return isolation has a measured cost;
large overflow records fully decode, preserving behavior rather than promising unlimited speed.

Rollback reverts this task's commit, restoring repeated read/decode cost. Keep every durable
record, approval, queue/Task state and retained worktree; no data downgrade or database action
is needed. Production activation remains the parent task's responsibility at an idle boundary.
