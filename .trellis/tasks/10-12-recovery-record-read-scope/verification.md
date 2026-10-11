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

## Parent integration verification

Integrated with idle-dispatch backoff, the versioned summary backend and summary-reading UI
in `task/delivery-input-recovery-integration`. The parent reran the shared public-read and
recovery-approval boundaries after integration:

```sh
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest -q --tb=short tests/web_console/test_operation_summaries.py tests/recovery/test_record_read_scope.py::test_public_approval_real_builder_fresh_fences_and_clear_before_execution
```

**22 passed, 20.70 seconds.** This includes the complete summary wire/history/authority
regressions and actual approval/builder/sealing gate with the integrated Knowledge/Context
ports. These overlap already reported subtask cases and are not additional distinct coverage.
The integrated UI's 18 new Node cases passed after its cherry-pick, and JavaScript syntax,
spec navigation links and `git diff --check` passed. Existing 224 related Node/13 isolated
Chrome checks remain the frontend's prior incremental evidence; no full suite was run.

Production at `1769977` continues the previously approved K1 operation. Integration validation
does not establish production activation or K1 delivery. The service and registered source
checkout remain unchanged until a safe maintenance boundary and any required exact source
baseline approval.

## Actual K1 source replay and remaining amplification

At `2026-10-11T21:13Z`–`21:17Z`, independent fresh processes replayed one real
`NativeRecoverySourceReader.inspect` for the already authorized K1 source. This was a
bounded read-only diagnosis: no TeamHost, initialization, authority, Task, queue, service
or workspace write. Its existing SQL ports used consistent READ ONLY snapshots and
finally rollback/close. Each process had a 45-second alarm; output retained only timings,
function names and fingerprints, never original source/context/DSN or credentials.

The old and integrated readers both succeeded. SHA-256 of exact source, Task, request,
ProductSpec, approval, TechnicalDesign and ExecutionPlan wire facts was identical:
`6b16fa4a665d3c4fb10b7d33059c54e6ead9cadff3d926ac7d62fcf09809795b`.
This checks those returned immutable source facts; it is not a claim/READY decision or
proof of the executing worker's instantaneous stack.

| Fresh-process replay | Baseline `1769977` | Integrated `874f6a6` |
| --- | ---: | ---: |
| Plain CPU seconds | 20.710 | 16.371 |
| Plain wall seconds | 21.074 | 16.513 |
| cProfile CPU seconds | 18.578 | 21.748 |
| cProfile wall seconds | 18.729 | 21.984 |

The plain comparison measured about 21% CPU reduction, rather than the smaller scalar
fixture's 6.3–8.6 times improvement. The instrumented result reversed the comparison;
the scoped path included over two million deep-copy calls. cProfile changes the cost of
many small calls, and machine/active-service variability remains. Treat the two plain
runs as one bounded observation, not a portable latency guarantee or whole-operation
benchmark. Do not remove private-copy isolation or freshness checks to improve a timer.

The baseline profile's single SourceReader inspection included four baseline epoch
reads, five complete `bindings_for_task` calls, 36 Plan reads, 20 Start reads and 20
native-rule epoch reads. Baseline epoch replay was about 9.94 cumulative CPU seconds;
15 joint-journal history reads were about 3.61 seconds. Nested cumulative times overlap.
These are actual isolated source-replay counts, not counts sampled from the running
production Operation. Do not multiply cold-reader timings into a predicted live duration:
reader-owned immutable journal reuse and input shape can differ.

The modern terminal path's static success graph from `TASK_SEALED` to fresh dispatch
contains six builders, 30 facts inspections and 180 SourceReader calls. Seed and first
Coder admission add two builders, ten inspections and 60 source reads. Each builder
retains its original authorization/facts/capture observations; MySQL pre/post callbacks
remain real fences. The dispatch prefix statically includes 192 capture verifications
(384 capture passes), 120 complete inventory calls (240 passes), and 480 read-only SQL
transactions before other allocator/backend work. These are code counts, not observed
production execution or measured full-path timings. The three-model decode scope does
not eliminate these live observations.

A bounded filename/stat inventory of the current sidecar's Product store found five
approvals / 4,375 bytes and five specs / 88,748 bytes. `find_approval` independently has
an O(approval × spec) lookup; it was not the main function in this profile. It requires
its own stable-prefix contract and regression rather than expanding the authority cache.

The initial four-phase fake-fixture readiness probe could not represent complete native
SQL/capture/inventory work. Their real timing remains unknown until the separately bounded
real offline fixture report is available. This task's validation and earlier isolated
numbers must not be described as end-to-end recovery performance.

The subsequent real offline fixture used a separate guarded database
`ai_software_engineer_test` (production is `ase_self_iteration`), temporary Git/sidecars,
the existing offline owned failed-Codex process, and serial execution. Baseline `1769977`
and scoped `aeca8a9` each reached the original hard deadline (120.06 and 120.04 wall
seconds). The first observer published only at session completion, so neither run
produced trustworthy phase timers or counts: those values remain **unknown**, rather
than zero, a pass, or a measured speedup. The `/tmp` observer was corrected to publish
bounded private intermediate statistics for future work, without rerunning or extending
this measurement budget. Both timeout paths reset the dedicated test database; all 13
mutable facts tables were checked empty, with no owned observer/offline-Codex process
remaining. This measurement is incomplete and is not a K1 recovery result.

## Later bounded baseline phase diagnostic

After fixing the observer's missing intermediate records, one new baseline-only probe
ran with a 45-second deadline. It is not a repeat performance comparison: observer behavior
and the random small fixture differ from the earlier 120-second probes. The observer now
publishes at startup/phase entry/every five seconds, records all-call counts before phase
selection, saves only function names for the main Python stack, and serializes private
0600 snapshots with monotonic sequence numbers. A 10,000-counter smoke cost about 0.0015
CPU seconds, which does not measure total observer overhead.

Collection completed at 1.582 seconds; test body began at 1.614; the authentic owned failed
fixture reached source/proposal at 4.994. That phase completed at 17.781, taking 12.787646
wall / 3.322146 CPU seconds, with 15 full SourceReader inspections, 40 read-only SQL
transactions, 15 capture verifications and 10 inventory function calls. Exact approval
began at 28.132; the last 40.062-second snapshot still showed that phase, with partial
11.930201 wall / 3.183599 CPU seconds, 15 source reads, 40 read-only SQL transactions,
15 capture verifications and nine inventory calls. Each inventory function internally
observes twice; these counters are function calls, not file passes. The final sampled
stack was the real Native facts/workspace/capture/Git subprocess chain.

The driver stopped after 45.139 seconds with SIGTERM. No completion data exist for sealing,
dispatch, seed or first provider admission, and the final five seconds are unknown.
The dedicated test database had 13 empty mutable tables before/after, no other connections
at admission, and no owned subprocess after cleanup; the exclusive lock was released.
No production Host/SQL/Requirement/workspace was accessed. Original 120-second positions
remain unknown; improved observability cannot restore their missing facts or prove why
they timed out. Detailed private reports live under `/tmp/ase-recovery-phase-baseline-short-*`.

The later admission-facts task reduces a supported builder from five complete inspections
to four. Its modern static dispatch prefix is therefore 24 inspections / 144 source reads,
with a further eight inspections / 48 reads for seed/first admission. This is the new code
graph, not observed production execution or a latency forecast. The earlier 30/180 and
10/60 counts above accurately describe their original version and are retained as history.
