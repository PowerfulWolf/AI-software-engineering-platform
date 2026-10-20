# Local path survey performance verification (2026-10-20)

## Cause and real measurements

Before repair, the real `--contention` profile remained for a long time in
`_mac_paths → Path.resolve` while Host Python work competed for execution. This observation
identifies the parent-thread parsing bottleneck; no historical execution state is inferred.

After repair, the real profile completed in **3.087s**, with `blockers=[]`.
The operator then observed both original root kinds twice with parent CPU contention:

| Round | Root kind | Duration | Blockers |
|---|---|---|---|
| 1 | repository | 2.874s | `[]` |
| 1 | worktree | 2.544s | `[]` |
| 2 | repository | 2.612s | `[]` |
| 2 | worktree | 3.144s | `[]` |

Each observation completed within the unchanged **5.0s** survey budget and retained the
**1.5s** query limit. The CPU probe thread joined and exited. The original aggregate-only
JSON is preserved as `evidence/dual-root-contention-20261020.json`; it includes exact survey
hashes, root kinds, durations and probe completion, without raw lsof or discovered process data.
These current performance observations are not historical stop evidence, K1 QA or K1 delivery.

## Focused tests and static checks

The deployment operator ran the following from the isolated maintenance checkout:

```sh
env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest tests/manager/test_local_path_observation.py tests/manager/test_legacy_local_execution.py tests/manager/test_knowledge_isolation.py -q -p no:cacheprovider
```

Result: **254 passed in 6.83s**. This covers the owned real parser child and unchanged observer,
alias, classification, deadline, strict protocol, startup-hook and isolation proof boundaries.
Changed-file Ruff check/format and final strict Mypy passed for all seven implementation/test
files. Independent static read-only review found **0 findings**; it is not a native K1 QA/Review
verdict. The earlier five-file Mypy result is superseded by the successful seven-file check.

## Existing-data treatment and deployment boundary

This repair changes no persistent/public wire or scanner version and requires no SQL migration.
All original K1 history, source, worktree and progress remain. Actual recovery has not been
executed at this record's creation. Follow only the original exact-plan public PAUSE and separate
RESUME, preserving any already sealed authority/start/binding and all original UNKNOWN facts.
Do not directly update SQL, reset attempts, fabricate an old stop, edit a draft or replace QA/Review.
The root deployment operator will append actual deployment and recovery observations separately.

## Risks and rollback

Performance observations cover this machine and current workload, not every future filesystem
condition. Path or process uncertainty still refuses recovery; a bounded owned cleanup remains
mandatory after a timeout. Do not increase limits or skip expensive aliases to make a survey idle.
For deployment or rollback, perform the official controlled stop, verify the predecessor really
exited, update/revert code and restart. Preserve immutable Requirement and lifecycle history.
