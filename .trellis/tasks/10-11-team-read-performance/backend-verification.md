# Backend verification

## Ownership and allowlist

Worktree: `/Users/zhangjunshuai/workspace/code/ase-team-read-performance`, base `38d33cb`.
Backend worker owns only:

- `src/ai_software_engineer/team_view/engineering_history.py`
- `src/ai_software_engineer/team_view/reader.py`
- `tests/team_view/test_engineering_snapshot.py` (new)
- `tests/team_view/test_baseline_snapshot.py`
- `.trellis/spec/core/read-memory-lifecycle.md`
- this verification file

The UI worker's files were left intact. No main checkout, production source, DB, execution,
approval, service restart, full Team HTTP GET, profile, commit or push was performed by this worker.
Only a root-authorized stat inventory of wait/preflight/disposition metadata sizes was made.

## Red → green work evidence

The first regression invoked the real `_TaskReadSnapshot.read → _read_task_details` twice with
different complete presentation bases and a real independently stored investigation+handling.
Before implementation it failed with **6 proof reads, expected 4**; handling reads were 4 rather
than the required 2. Both independent Task projections and complete timeline equality are asserted.
After snapshot-local typed prefix reuse, the same regression passes with **4 proof reads / 2 handling
reads**, preserving the handling's independent original-proof lookup on both projections.

A separate real two-Task/same-sidecar fixture publishes six complete wait records. It keeps both
three-entry timelines and records **18 actual `KnowledgeRecordStore._read_name` calls** (12 complete
list/key checks + 6 independent reference reads); direct separate reads require 30. Returned nested
details can be mutated without affecting a subsequent timeline or stored bytes.

## Scope and limits

The helper is owned by a single `_TaskReadSnapshot` and shared only within that read. Root +
namespace + exact typed model distinguish prefixes; disposition records also retain original paths.
It validates full prefixes and immutable keys before caching, never successful per-Task decisions.
Per-Task intent/scope/policy/terminal snapshot and original proof/resolution/claimed-intent checks
remain in the projection path. All wait/preflight foreign records are validated before filtering.

Aggregate limits across this helper's entire read are 512 records / 16 MiB UTF-8 serialized model
bytes / 128 prefixes / 64 store identities. Exceeding any reuse limit keeps complete uncached reads;
it never drops history or fails an otherwise valid read. Serialized bytes do not claim a hard total
Python heap limit. The actual selected sidecar stat inventory is 57 files / 546,581 bytes, so this
budget covers its measured shared ledgers comfortably.

## Incremental verification

Interpreter/tool root: the existing main checkout `.venv`; `PYTHONPATH=src` points imports to this
isolated worktree. No dependencies were installed and no full test suite ran.

```text
PYTHONPATH=src <venv>/bin/python -m pytest \
  tests/team_view/test_engineering_snapshot.py \
  tests/team_view/test_engineering_history.py \
  tests/team_view/test_baseline_snapshot.py \
  tests/team_view/test_task_read_snapshot.py -q
```

The first combined run had 61 passes and 5 new-test fixture failures: the foreign native fixture
used the same Task ID and the capacity fixture reused the handling store's immutable deduplication
key. Corrected only those new fixtures (distinct Task ID and genuinely distinct step digest), then:

```text
PYTHONPATH=src <venv>/bin/python -m pytest tests/team_view/test_engineering_snapshot.py -q
14 passed in 0.70s
```

Together the runs establish **52 existing regressions + 14 current new regressions passing**.
The existing regressions include HTTP success/failure weak references for both snapshot helpers;
the source was unchanged between these runs. The red-test failure occurred before implementation,
and is distinct from the temporary fixture failures above.

```text
<venv>/bin/ruff format --check \
  src/ai_software_engineer/team_view/engineering_history.py \
  src/ai_software_engineer/team_view/reader.py \
  tests/team_view/test_engineering_snapshot.py tests/team_view/test_baseline_snapshot.py
4 files already formatted

<venv>/bin/ruff check <same four files>
All checks passed!

PYTHONPATH=src <venv>/bin/mypy <same four files>
Success: no issues found in 4 source files
```

Negative tests cover foreign corruption, resealed envelope/internal digest mismatch, wrong store
key, symlink, missing independent proof after warm capture, changed Task/Project, native-vs-parent
Requirement, terminal full Task snapshot, failed-capture retry, append/absent roots and four budget
limits. Overflow facts are revalidated even within the same limited snapshot. Existing authority,
policy, original claimed-intent, native execution and redaction cases continue to pass.

## 存量数据处置

无需改库或迁移。优化仅减少同一次 GET 中重复读取的完整 immutable ledger；不改需求、Task、
Operation、审批、queue、checkpoint、候选代码和保留的工作现场。下一次 GET 重新检查历史事实。
Root 在真实执行空闲后按受控服务维护流程加载代码，用户刷新原 Project 即可，不需新建 K1。

## Risks and rollback

Root completed sequential fresh read-only subprocess measurements; see `read-profile.json` and
`verification.md`. Old 7.112s / new 8.058s do not establish an overall latency improvement. The helper
does not establish or repair a permanent Team gate leak; oversized ledgers legitimately fall back
to the prior complete read cost. It changes no API/schema, execution permissions or role verdict.
Rollback these reader/helper/test/spec changes to restore repeated reads, leaving durable facts and
delivery progress untouched.
