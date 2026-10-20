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

## Real deployment (2026-10-20)

Maintenance commit `19d63af` was fast-forwarded to `main` and pushed to `origin/main` after
PID67899 completed the official controlled READY/actual-exit handshake. Official startup
created PID99948, instance `console_instance_22493331af66aec0da7dbaf4f31d5e58`, at
`2026-10-20T06:21:18.609887Z`. Public Console reports normal/ready/contract10. Settings still
reports `restart_required=false`, and the original configuration apply request remains SUCCEEDED.

The original exact K1 PAUSE payload was resubmitted with only a fresh Console idempotency key;
its intent/reference, checkpoint, plan `6d5c2615ca4a769302931cddcd8d4f59eae5830afe3be9ae66a498bb40c7f80c`
and original source were unchanged. Public submission accepted
`operation_2a67ac0bb11d12a0865323133419ded1` as QUEUED. Final outcome is recorded below when observed;
acceptance alone is not recovery success or delivery.

Final independent read-only review by `/root/survey_isolation_design` found 0 findings.
Reviewed production file SHA-256 values:

- local_path_observation.py: `62cbf0fdb13b3a01d024379fa5bfe3d97d652ccc2e6285f9d0e1ee165b98ce4e`
- local_path_worker.py: `fad7004e82d19585a8c6939b1b3a78121bc5106586d63374355d7cb0e749ac11`
- legacy_local_execution.py: `e71e3f1470df6e58b9e2a7f3bafc4d30e13751f76e1aaf1a91756e7f16bd5c1f`
- knowledge_isolation.py: `0d4424c5a7448b0c8309a14918348fce0a620092a2efbef5927ca25a403c3ed4`

## Follow-up public recovery observation

The old-plan retry correctly refused `COMMAND_REJECTED` because the user's saved ProductionConfig
changed the runtime manifest from 5984cd671e585837a54ea83f94b8876f022983f66e93ace7fdaa2a6178bf9f92
to 298440fc6c8033ef7b4d3754f15c0cc63a642a62fc9308608410df2f123ba5b7. Original source, complete
patches, progress, scopes and permissions stayed unchanged. Fresh exact public proposal/approval
produced a successful PAUSE binding. Separate RESUME first refused real terminal-helper source
access, then after authorized normal helper shutdown and four idle surveys, refused a native
identity phase deadline under real Host contention. The path-parser fix remains valid; it did
not remove this separately measured parent-thread FFI bottleneck.

Full immutable operation/authorization references, preservation checks and red reproduction are
recorded in the next maintenance task, `../10-20-native-process-survey/verification.md`.
Original Task, source, complete drafts and UNKNOWN history remain; no real K1 completion is claimed.
