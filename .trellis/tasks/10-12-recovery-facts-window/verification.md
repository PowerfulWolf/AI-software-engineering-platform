# Verification

## Authentic red and green

All real cases use temporary Git, a real TeamHost with offline structured model clients,
an actual owned Python failure process, complete native approved Product/Design/Plan,
Context, dispatch/claim/queue/Task/events, routes/invocation/capture-start/capture-stop and
the unchanged native SQL decoders. No high-level Source/Facts replacement, cast or
SimpleNamespace establishes the new window's acceptance.

```sh
PYTHONPATH=src python -m pytest -q -s --tb=short \
  tests/recovery/test_facts_window.py::test_complete_modern_native_inspection_reads_source_twice
```

first failed before production changes: **actual 6 reads versus expected 2**, 11.16 seconds.
Fixture was ready at 5.229 seconds. Finally recorded owned process zero and all 13 tables
empty before both locks were released. The first implementation green passed in 8.84 seconds,
with fixture ready at 4.934 seconds. These small-fixture timings are not production K1
latency measurements, end-to-end approval/dispatch timings or memory-leak evidence.

The full initial 14-case increment ran in 110.51 seconds: 13 passed and one negative test
failed because it simulated legacy `os.killpg`, while authentic modern stops use the
owned-session OS inspector. Only that test seam was corrected: it now supplies an occupied
leader through `_SessionInspector`, with the original real stop/proof and all native gates
unchanged. Its targeted rerun passed in 10.52 seconds. Two additional real source/target
drift cases passed in 17.33 seconds. Thus all current 16 real cases have passed individually;
the already passing cases were not rerun without a new code change.
The existing ownership case additionally gained a missing-second-observation rejection
and subsequent lock-release assertion; its targeted rerun passed in 8.62 seconds.

Assertions cover exact source/target/terminal/inventory ordering, both full source readers,
independent fresh stop objects, lock held before source and released on return/failure,
late changed capture, missing stop, raw SQL status inconsistency, ignored environment
inventory, currently occupied owned session, approved source corruption, dirty logical
target, busy/missing/symlink/replaced-inode Worker lock, fixed class/instance/subclass
delegate fallback with six complete reads, and closed/foreign-thread/foreign-async-task/
missing-second/third-observation rejection.

## Compatibility and typed checks

```sh
PYTHONPATH=src python -m pytest -q --tb=short -m 'not mysql' \
  tests/recovery/test_workspace_snapshot.py \
  tests/recovery/test_terminal_source_inspection_scope.py \
  tests/recovery/test_workspace_plan.py tests/recovery/test_scope.py \
  tests/recovery/test_current.py
```

passed: **97 passed, 1 deselected**, 104.46 seconds. This covers the independently safe
public wrapper, legacy/progress handling, scoped records/source scans and workspace/scope
contracts. Their historical mock compositions are compatibility checks, not proof of the
new complete Native window.

Ruff check, Ruff format and strict Mypy (`MYPYPATH=src`, `--follow-imports=silent`) passed
for the two production files and both new test files. `git diff --check` passed.

```sh
PYTHONPATH=src python -m pytest --collect-only -q -m 'not mysql' \
  tests/recovery/test_facts_window.py
```

This deselected all 16 cases and selected none (pytest's
expected exit 5). No fixture or database connection ran. Real cases retain the mysql marker
and the repository's unsafe-DSN setup rejection; this file's local empty autouse override
prevents an early reset before the helper's exclusive admission.

## Test database disposition

Only `ai_software_engineer_test` was used. Each fixture acquired the shared private
`/tmp/ase-ai-software-engineer-test-probe.lock` and
`GET_LOCK('ase:isolated-probe:ai_software_engineer_test', 0)`, then verified the actual
database name, absence of other sessions and all 13 mutable fact tables empty. Fixture
cleanup matched the actual resolved executable inside this temporary directory, verified
its PID/birth absence, checked no other test DB sessions, reset all 13 tables, rechecked
empty and released both locks. Every real case emitted `owned_processes_zero` and
`cleanup_13_tables_empty`. No production DSN/config/Host/service/model/Requirement operation
or registered code repository was read, initialized, reset, approved or dispatched.

## 存量数据处置 and rollback

No SQL/Schema/Task/journal/artifact/approval/snapshot wire format changes or data migration
are required. Existing exact approvals and the retained old worktree remain unchanged;
this optimization grants no retry, execution or recovery approval. Root owns deployment
and resumption of the same Requirement through its existing public exact action after
current workers are idle. Rollback restores nested inspection cost while preserving all
existing durable facts and files. No full test suite was run.

## Independent review and explicit limits

Root and an independent read-only reviewer inspected the production composition, scope
selector, old Worker lock, complete comparisons, fixture admission/cleanup and specs.
The independent reviewer ran 11 non-database regression cases successfully and reported
no blocking finding; Root confirmed the change can be committed.

The new authentic Native matrix covers modern FAILED recovery with a complete snapshot,
no quarantine and the supported standard inspector, plus trusted delegate fallback. It
does not add an authentic full Native matrix for legacy, accepted-progress or quarantine
selector routes. Those retain the original independent public wrapper and unchanged
ordering and are covered by the existing compatibility increments; that coverage must
not be described as new full-chain acceptance for those modes.

The implementation is not deployed by this worker. Root owns core-index registration,
integration and additional real authorization-service/builder crossing tests.
