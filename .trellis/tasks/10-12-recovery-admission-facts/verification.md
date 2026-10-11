# Incremental verification

Base: `874f6a6`; worktree `ase-recovery-admission-facts`, branch
`task/recovery-admission-facts`. Root independently reviewed the implementation and reported
no remaining blockers after the bound-delegate compatibility fix; isolated commit authorized.
All commands ran from this isolated worktree with `PYTHONPATH=src` where needed and the
existing platform `.venv`. No production Host/SQL/service/registered repository or real
model was accessed; no full suite and no MySQL integration case was run.

## Red / green observations

The initial actual builder test failed before implementation: observed ten underlying
native facts observations versus the target eight, with both capture verifications intact.
The supported path now removes only the middle derivation inspection.

Independent review found a compatibility defect in the initial exact-class-only selector:
an instance-specific stronger `validate` was bypassed. A new precise test reproduced zero
validation calls where the original path requires four. The selector now additionally
requires the actual bound standard delegate, its function identity and the same receiver.
The fixed test preserves four validates/five inspections on successful compatibility builds
and rejects at the third stronger validate when derivation enables rejection.

## Executed test commands

```sh
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest tests/recovery/test_authorized_facts.py tests/recovery/test_authorization.py tests/recovery/test_task_policy_builder.py tests/recovery/test_preparation_inspection_scope.py tests/recovery/test_task_record.py tests/recovery/test_record_read_scope.py -q --tb=short
```

Result before the instance-delegate guard review: **97 passed in 70.51 seconds**.
This includes actual public approve/authorization/builder/sealing, wire equality against
the unchanged compatibility path, complete facts drift, Plan/receipt/directory/body drift,
capture-after checks, rejection/missing records, scope release and OfflineAuthority fences.

```sh
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest tests/recovery/test_authorized_facts.py tests/recovery/test_git_integration.py tests/recovery/test_terminal_baseline_sql.py tests/recovery/test_terminal_source_inspection_scope.py -q --tb=short
```

Result before that final guard adjustment: **28 passed in 43.94 seconds**.
The actual Git capture fixture and terminal source/fake-SQL regressions were not repeated
after the localized guard fix because their supported composition did not change.

After the review fix, only the new file and directly affected compatibility/count/public
approval gates were rerun:

```sh
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest tests/recovery/test_authorized_facts.py tests/recovery/test_task_policy_builder.py::test_authorized_builder_copies_only_exact_plan_policies tests/recovery/test_preparation_inspection_scope.py::test_builder_reuses_complete_source_and_generic_but_repeats_all_fresh_facts tests/recovery/test_preparation_inspection_scope.py::test_allocator_shares_scans_across_both_fenced_fresh_checks tests/recovery/test_record_read_scope.py::test_public_approval_real_builder_fresh_fences_and_clear_before_execution -q --tb=short
```

Final result: **24 passed in 19.29 seconds**. Test command totals overlap and are not a
count of unique cases. The wider 97-case suite was not rerun unnecessarily.

## Exact native call graph

| Gate | Old underlying facts observations | New | Other asserted counters |
| --- | ---: | ---: | --- |
| One supported builder | 10 | 8 | Plan getters 6, authority getters 2, capture checks 2; scan counts unchanged |
| Public exact approval plus one seal | 18 | 16 | All retained authority reads fresh; native authority decodes at least 16 |
| First OfflineAuthority allocation | 40 | 32 | Four builders, captures 8, Plan getters 33, authority getters 14, both fences 1 |
| Allocation replay | 30 | 24 | Three builders, captures 6, Plan getters 24, authority getters 10, first fence retained |
| Seed / first authorize builder | 10 | 8 | Separate seed/verify/invocation guards retained; no provider inherits inspection scope |

No current-facts observations cross the independent builders, callback windows, transaction
fences, seed or execution admission. The removed middle inspection consisted of two
underlying observations; do not claim every former observation remains. These are actual
deterministic fixture counts, not an end-to-end production timing or RSS benchmark.

## Static checks and limits

Ruff check, Ruff format check and strict Mypy passed for the two production files and three
affected test files. `git diff --check` passed. No Schema, durable store, approval, Task wire,
metadata, queue, claim, role permission or state transition contract changed.

The new native complete-facts final comparison applies only to the same exact native
inspector with its standard bound delegate. Generic validate-only, independent inspector,
subclass and instance override compatibility paths retain their original checks and output;
they do not gain that new comparison. Native facts acquisition in these tests is an
existing deterministic fixture port, not complete live process/SQL/Git inspection.

## Existing data and rollback

存量数据处置：no migration or production fact rewrite. Preserve the original Requirement,
Task, failed history, exact approval, hashes and worktrees. Load or roll back only after
authorized active workers are idle; use the original Requirement's public exact continue
path afterward. This optimization does not itself approve or restart delivery.

Rollback restores the old redundant middle inspection without changing stored bytes.
Larger shared-observation windows are deferred and require separate admission/callback/
transaction design and review. Runtime deployment and any current Operation remain root-owned.
