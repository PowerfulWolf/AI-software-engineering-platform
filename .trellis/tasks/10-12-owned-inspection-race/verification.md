# Incremental verification

| Check | Result |
| --- | --- |
| New errno 0/ENOENT confirmed-exit seam before source fix | 2 failed, 13 deselected in 0.13s; both raised `OS process birth identity is unavailable` instead of accepting fresh kernel absence |
| Initial focused inspection tests | 22 passed in 0.12s |
| Inspection + actual session stop + record finalization + stop Schema contracts | 62 passed in 11.72s |
| Final inspection tests, including positive partial-byte-count variant | 24 passed in 0.12s |
| Scoped strict mypy over source and inspection test | 2 files passed |
| Scoped Ruff check/format and git diff check | Passed |
| Independent `owned_scan_review` static review | No blocking finding; active/recycled/denied facts still fail closed |

Commands used the shared venv with `PYTHONPATH=src` (and `MYPYPATH=src` for mypy) in the
isolated checkout. No full suite or real model calls were run. The real exit test is Darwin only;
the deterministic short-query matrix is portable. Its actual child exits between initial SID and
birth query; the real API may report ESRCH, which the prior code already supported. The **new**
red/green cases are the defensive errno 0/ENOENT plus fresh kernel ESRCH seam.

Earlier diagnosis, separately authorized by Root, serially reran the exact public same-base fixture
in main with in-memory owned-boundary exception instrumentation: 1 passed, 10 deselected in 35.67s.
No owned exception was raised. A separate 300-command actual Git/save probe completed; a bounded
1,500-child fork/exit probe observed 2,000 full sweeps without failure. These do not explain the
original pytest-1947 failure, whose inner cause was not recorded. No concurrent MySQL test was run.
Root owns the subsequent integrated public test and deployment.

No debug instrumentation or throwaway files remain in the repo; the command probe's temporary
record directory was automatically removed. The implementation changes nine source lines only.
