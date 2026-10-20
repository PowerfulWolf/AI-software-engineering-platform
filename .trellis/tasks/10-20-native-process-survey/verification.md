# Native identity survey verification (2026-10-20)

## Red reproduction

Read-only harness: `/tmp/ase-survey-native-read-comparison-20261020.py`, using the production
TrustedLegacyLocalExecutionObserver and three finite CPU probe threads. Command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python /tmp/ase-survey-native-read-comparison-20261020.py
```

| Round | Current observer | Single-read-per-inventory prototype |
|---|---|---|
| 1 | 5.150s, PROCESS_SCAN_INCOMPLETE, 1056 native reads | 5.081s, PROCESS_SCAN_INCOMPLETE, 526 native reads |
| 2 | 5.160s, PROCESS_SCAN_INCOMPLETE, 1048 native reads | 5.167s, PROCESS_SCAN_INCOMPLETE, 524 native reads |

All four safe logs report process_inventory_before; all three probe threads exited. The prototype
was diagnostic only, did not modify platform code or recovery facts, and establishes no authority.
Aggregate-only evidence is saved in evidence/native-read-comparison.json.

## Existing-data treatment before this implementation

The saved-config request completed through the repaired supervisor, preserving original ID.
Old K1 plan 6d5c2615ca4a769302931cddcd8d4f59eae5830afe3be9ae66a498bb40c7f80c
correctly refused after the saved ProductionConfig changed its runtime manifest. A fresh public
proposal created plan 3cf975409719c9614e4bae771cd72da4db17e8ba5a7d3155bc0c1e4bd6e0a95a;
source/base, Task intent, full current/inherited patches, preview, scope/permissions and inventory
were compared and unchanged. Only runtime/current observations and their derived digests changed.
Public execute operation_a5290b10f699f137a46e281b04059e77 SUCCEEDED with PAUSE binding
bff4531e8fcec28f28443a7677a876aa597feaff192c86400b1dbe3493547b3f. Before/after inventory both
590d520b56dc6f8a0ded53a3b6d18e39dd7baffdd04a7a1feefebf7201881401. Public summary confirmed
old attempt5 WorkItem CLOSED and unique attempt6 successor WAITING_HUMAN at Task revision11.

Separate RESUME operation_98b11e25a9689cd4f620e41a023fdb19 sealed exact continuation authority
6009222522cbb066c38401e833728a28a90d0c2d525dec95a62fda01ceb01057 before fresh validation
refused WORKTREE_PROCESS_ACTIVE. Real scans identified an idle terminal's Git status helper
holding registered repository files; the original Coder worktree itself was idle. After the user's
explicit authorization, the exact account/parent/TTY/program/birth/file-reference checked helper
was normally stopped with SIGTERM. Its exit was verified; terminal and workspace files retained.
Subsequent production boundary inspection completed repository/repository/worktree/worktree in
7.045s total, each idle and each subject to its own original five-second budget.

With identical intent/reference and a new Operation key, retry01 operation_f1f87391656d4b18645521d635fffeb6
then failed the Host process-inventory deadline. The production log reports 5.033s at
process_inventory_after. Keep the original sealed continuation authority, PAUSE, same Task/source,
full progress, unknown history and both failed Operations. No direct database repair is required;
only public exact RESUME after the observation defect is repaired. No new real Coder claim or
K1 QA/Review completion is asserted in this initial record.

## Post-fix checks, deployment and recovery

To be appended after actual execution. Tests/probes alone do not establish real K1 delivery.

## Native batch intermediate real measurement (not acceptance)

Four full surveys after the native batch implementation, with three competing CPU threads, still
refused incomplete at 5.089 / 5.268 / 5.276 / 5.224 seconds. Observer source SHA at measurement:
2e3a7ad66929da561e026be4c6488b7cf2833eff5fed4590649a99a32c2cc298.
All CPU probes exited; no deployment or K1 release was attempted from this failed result.
The full profile then located captured-argument alias resolution under desktop attribution.
This evidence is kept alongside the original red result; focused test success alone did not approve
production rollout. Aggregate acceptance remains required after the additional parsing isolation.

## Captured-argument isolation intermediate result (not acceptance)

After adding complete captured-argument alias interpretation to the fixed worker, all four
three-CPU-thread full surveys still refused at 5.103 / 5.383 / 5.279 / 5.506 seconds. All
probe threads exited. The aggregate result and full profile are preserved in evidence.
The next profile refused at paths_before in 5.419s; five owned query lifecycles had already
used 1.390s in ownership observation and 1.069s in finalization, with another 0.805s creating
private files. The remaining parent-thread cost is distributed across multiple launch/cleanup
round trips, not only native FFI or path alias resolution. No failing version was deployed.

Focused native/path/legacy/knowledge regressions at this intermediate point passed 431 tests
in 8.14s. They establish correctness of the narrow adapters, not real full-survey performance.
The final architecture and final check results must be recorded separately.

## First complete isolated survey measurement (not final acceptance)

The complete isolated facade removed the observed deadline bottleneck. Four real scans with
three competing parent CPU threads measured 2.253 / 2.264 / 2.405 / 2.320 seconds. Repository
both scans and the second worktree scan were idle. The first worktree scan correctly retained
PROCESS_SCAN_INCOMPLETE at process_identity_final, so this is not four-of-four acceptance.
All probe threads exited. Evidence is kept in evidence/whole-survey-first-measurement.json.
Final native identity/coverage uncertainty is retained; it is not converted into idle.

The final implementation is being reduced to the complete isolated facade/worker and narrow
engine seams, reusing the original kernel identity and full argv algorithms inside that isolated
interpreter. Failed intermediate native/argument subprocess protocols are not required by the
final design and will not become additional production capabilities. Final tests and real
four-survey acceptance must use this reduced implementation, after test subprocesses exit.

## Final reduced implementation checks

The final production implementation excludes all intermediate native/argv batch protocols.
It reuses the original full algorithm in one fixed owned worker, plus the narrow fresh-errno
and embedded-PID validation correction. Final focused command:

```sh
PYTHONPATH=src /Users/zhangjunshuai/workspace/code/AI-software-engineering-platform/.venv/bin/python -m pytest -q -p no:cacheprovider tests/manager/test_local_survey_observation.py tests/manager/test_local_path_observation.py tests/manager/test_legacy_local_execution.py tests/manager/test_knowledge_isolation.py
```

Result: **367 passed in8.53s**. All test workers/temporary peers exited; registry empty and
require_stopped assertions passed. Ruff check and format plus strict Mypy passed for the four
changed production modules and two changed test files (six files, including baseline default).
This is focused maintenance validation; no claim of an all-project green run or K1 verdict.

Independent final read-only review found0 unresolved correctness/security blockers. Frozen
production SHA-256 values:

- local_survey_observation.py:b9dc894e991ea6bf99f339d94a400a180d73b85bdca48d6a16e13c64a17f962f
- local_survey_worker.py:701f173d5f68cf2f95f94a71e79f6d7bca9910ee51eb082a0d252473237d96f0
- legacy_local_execution.py:eed77206f0a53d69f6dd476b52df3570eba4555d9c3fb7817888a385615f26fc
- baseline_production.py:1075964acd8c0d888ae8246ff4e0ca50f3a5607398f6651024f4ec8a36d1c97a

## Final real contention measurements, separate from idle qualification

After all test workers exited, the final facade ran two independent four-survey rounds with
three competing parent CPU threads. Round1 durations were2.300/1.768/1.913/2.097s; round2
2.430/2.225/2.000/2.379s. All8 complete calls were within the unchanged5-second budget; none
reported PROCESS_SCAN_INCOMPLETE. Six were idle; one observation in each round retained
PROCESS_STATE_UNKNOWN. Both rounds correctly failed their four-idle assertion and all probes
exited. Full aggregate evidence and exact source hashes are preserved for both rounds.

The measured deadline defect is resolved on this workload. These results do not establish
current four-survey recovery eligibility. Unknown state remains a refusal under the original
guard; its cause is independently being checked before final deployment/recovery observation.

## Independent unknown-state assessment and deployment admission

The independent read-only investigator checked the original stat parsing against this machine's
ps.1: the first stat character is the primary state, documented I/R/S/T/U/Z are already covered,
and E is a suffix. The exact query-PID/argv exclusion occurs before classification. Four current
aggregate-only ps samples each observed497 processes and no unknown primary state:
R2/S494/Z1, R2/S494/Z1, R4/S492/Z1, R6/S490/Z1. No PID or argv was persisted.
These later samples cannot explain the earlier two unknown observations. No known-state omission
or deterministic whole-worker defect was established; do not change the original whitelist.

The investigator and root explicitly distinguish the measured performance acceptance from idle
recovery eligibility. The PRD now records that separation and both failed four-idle assertions.
Deployment of the bounded performance fix is admitted, with unknown still closed; the original
public RESUME must independently pass all current fresh gates. No idle authority is inferred.
Official predeployment status confirmed old servicePID99948 still running normally.

The final production-default constructor follow-up uses the actual collector __init__ and
checks both default isolated observer and exact explicit injection, allocation validation and
task ID binding. Its separate narrow run passed2 tests (101 deselected) in0.33s; Ruff and
strict Mypy for that test file passed. Production source hashes did not change. The complete
four-suite367 result above precedes this two-case addition; it was not rerun or relabeled369.
