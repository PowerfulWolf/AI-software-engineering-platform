# Verification

## Red evidence

The first real 3-request × 3-version history decoded 81 ProductSpecs for 9 approvals; its
linear-read assertion expected 9 and failed. Existing decode/store behavior was preserved by
fixed decoder extraction. Independent review reproduced partial-overflow/held-error retention
with weak references before the follow-up lifecycle fixes.

## Incremental verification

Use the main checkout's existing virtual environment without changing that checkout:

```sh
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest -q --tb=short tests/product/test_approval_read_prefix.py tests/product/test_store.py tests/product/test_service.py tests/design/test_service.py
MYPYPATH=src PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m mypy src/ai_software_engineer/product/store.py tests/product/test_approval_read_prefix.py
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m ruff check src/ai_software_engineer/product/store.py tests/product/test_approval_read_prefix.py
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m ruff format --check src/ai_software_engineer/product/store.py tests/product/test_approval_read_prefix.py
git diff --check
```

Final combined incremental run: **79 passed in 2.95 seconds**, including 33 new cases.
Strict mypy: **Success, 2 files**. Ruff: **All checks passed**. Format check: **2 files
already formatted**. `git diff --check`: **passed**. No broadening beyond the related stores
and services occurred after those checks.
Independent reviewer separately passed the six newly repaired lifecycle/Designer cases in
0.50 seconds; earlier other 27 new cases were also independently green.
The integration agent reviewed the final spec, verification, existing-data disposition and
measurement limits and accepted the complete diff before the isolated task commit.

No full suite, MySQL, production Host/service/source mutation or real model execution occurred.
Actual DesignerService coverage uses its normal services, real file stores, real complete
artifacts and an offline fake adapter callback; it rejects request/approval drift after the
callback and publishes no Design receipt/checkpoint/stage advance.

## Finite isolated complete-store measurement

One process, 6 requests × 6 versions: 36 full specs, each with about 26 KiB of fixture summary,
36 exact approvals. Compare the actual original `_find_approval_unindexed` with the public
optimized `find_approval` on the same real fixture. Exact found approval equality held.

| Fact | Original complete path | Call-local prefix |
| --- | ---: | ---: |
| ProductSpec decode/integrity validations | 1296 | 36 |
| ProductSpecApproval validations | 36 | 36 |
| Complete trusted raw reads | 1332 | 144 |
| Complete raw bytes read | 35,181,900 | 2,002,500 |
| Process CPU seconds | 0.549352 | 0.033492 |
| Wall seconds | 0.553193 | 0.033638 |
| Peak retained association/fingerprint entries | N/A | 123 |
| Peak serialized retained accounting bytes | N/A | 27,109 |

The optimized 144 reads include every complete spec and approval twice: initial validation and
final fresh raw-SHA observation. Its reduced I/O comes from removing A repeated spec scans;
the new path never skips a historical record. This fixture measured about 16× less CPU for
this lookup only. It is not a full recovery benchmark, a portable latency claim, a heap/RSS
hard bound, or evidence that a long-lived memory leak has ended. Within-budget deterministic
decoding is S + A; overflow deliberately restores original cost.

Only nonsensitive counts/times are saved in
`/tmp/ase-product-approval-prefix-benchmark-20261012.json` (0600). The temporary fixture was
removed after measurement; no production Product body, approval, config or SQL was read.

## 存量数据处置 and rollback

No migration or new Requirement. Original durable bytes/hashes/approvals/drafts remain unchanged.
Deploy only during an idle controlled service window, then continue the original Requirement
through its public recovery/continue entry. Preserve any exact baseline approval; loading runtime
code does not authorize source rebinding. Revert the optimization while idle for rollback;
original repeated read cost returns without altering any durable fact.
