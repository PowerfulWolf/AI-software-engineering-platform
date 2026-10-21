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

Actual focused checks, deployment, public continuation attempts and current recovery facts are
recorded below. Tests/probes alone do not establish real K1 delivery.

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

The final implementation was reduced to the complete isolated facade/worker and narrow
engine seams, reusing the original kernel identity and full argv algorithms inside that isolated
interpreter. Failed intermediate native/argument subprocess protocols were removed and did not
become additional production capabilities. The final checks and real four-survey measurements
below used this reduced implementation after test subprocesses exited.

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
guard. The later independent assessment, deployment and public recovery observations are
recorded below; the earlier unknown observations remain unexplained.

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

## Actual deployment and first original continuation retry

Maintenance commit d401eda1d32d62348759f1e657ded5f4243b46c5 was fast-forwarded to main and
pushed to origin/main. Official stop ofPID99948 reached READY and confirmed actual exit;
official startup createdPID55446, instance console_instance_9f730f95bf6805a3e835e7b67a669f7f,
started2026-10-20T08:09:15.671949Z. Public Console is normal/ready/contract10. The original
configuration apply request remains SUCCEEDED and restart_required=false. Original K1
Task revision11 and attempt6 WAITING_HUMAN remained unchanged before continuation.

Only the Operation key changed for retry02; complete original RESUME intent/reference equals
the already sealed authorization, comparison SHA b0c070090d057389be317305338c72962ab77c1635ff5385277b022e7cdc7820.
Public operation_25d29b7ca9d954a97b0257a632ad6113 was accepted QUEUED then FAILED with
LEGACY_LOCAL_SURVEY_INCOMPLETE. No new incomplete-phase log followed the deployed worker;
unknown-state is a hypothesis, not yet a proved reason for this exact failed Operation.
The failed Operation is retained. The wait, retry allowance and old facts were not edited. The
subsequent temporary aggregate-only exact full-worker diagnostic and public retry are recorded
below; no cause for this exact failed Operation was inferred from later idle observations.


## Bounded unknown-state diagnostic and subsequent public continuation

Root executed the fixed temporary harness once, for exactly four complete surveys in the order
repository, repository, worktree, worktree. The diagnostic subclass only wrapped the original
worker's `_processes`; the original engine, returned inventory objects, blockers, actual-parent
identity checks, single owned SID and final ownership cleanup remained unchanged. The same
absolute **5.0-second** scan deadline and **min(1.5 seconds, remaining)** fixed-query budget
applied. No production code, status gate, database, verdict or K1 draft was changed by diagnosis.
The complete aggregate-only report is preserved in `evidence/unknown-state-diagnostic.json`.

| Scan | Root kind | Duration | Result |
|---|---|---|---|
| 1 | repository | 1.643s | idle; typed result validated |
| 2 | repository | 1.328s | idle; typed result validated |
| 3 | worktree | 1.265s | idle; typed result validated |
| 4 | worktree | 1.387s | idle; typed result validated |

All eight before/after inventories contained no unknown primary state. Consequently the
conditional diagnostic native reads were **0**, and state transitions, native-status counts and
positive-gone observations were empty. The owned registry was empty after all four scans.
These results did **not reproduce** the earlier refusal: they provide no unknown character,
no proof of its cause and no reason to relax the state whitelist. The temporary diagnostic
cannot replace the production's fresh recovery gates, and cannot turn current idle into a
historical process-stop or no-start fact.

The separate original-intent public RESUME retry03,
`operation_fc40a17eef8750bb1c18824d3eb119ab`, subsequently passed the production fresh gate
and entered the normal queue. An earlier public detail observation recorded attempt **6 CLOSED** and
attempt **7 RUNNING**, with execution phase **KNOWLEDGE_PREPARATION**, **LEASE_VALID** and
heartbeat **2026-10-20T08:33:58.545665Z**. This is a current queue/execution observation; the
Operation was still **RUNNING**. It does not assert Operation SUCCEEDED, K1 DONE, a new
accepted Coder implementation, a confirmed main-execution Run/Context, or any QA/Review
verdict.

Independent typed execution-history audit explains the attempt 6-to-7 transition: attempt 6's
assessment has a sealed **FAILED / PROVIDER_UNAVAILABLE / transient=true** outcome at
**2026-10-20T08:30:06Z**, SHA
`4d7abd84acf64e7c6d52abe149b2952348fb95e5ea3f374eff59d54f164e0379`.
Attempt 7's new knowledge run is `run_knowledge_6b56e4ed0db2352c4138166904174062`.
Its intent phase returned at **2026-10-20T08:33:06Z**, SHA
`aad780938bd2fc48241d276dcb782bf5f45ea019e08e304e4590c4b2f01a77bd`;
assessment intent SHA
`cf6d3b12e8b29d848ac0d9f73c738bb7536d3308c5432451dae70c63a247c642`
was written at **2026-10-20T08:33:09Z** with no assessment outcome yet at that observation.
This records a typed transient-failure retry, rather than inferring a new ordinary-work charge
from the incremented execution identity. A separate exact typed Task read at
**2026-10-20T08:46:42.616009Z**, inside a consistent-snapshot READ ONLY transaction that was
rolled back and closed, confirmed execution identity **7**, ordinary work attempt **6 of 10**,
and Coder transient failures **1 of 10**. The sole retry-failure fact is attempt 6,
Coder/PROVIDER_UNAVAILABLE. The aggregate is stored in `evidence/continuation-budget.json`;
it used no Host, queue mutation, budget restoration or control call. A first temporary output
formatter incorrectly treated a literal string as an enum and failed after read-only rollback;
the corrected formatter produced this report. That diagnostic-script error was not a platform
execution failure. No extra approval or main-execution completion is inferred from these facts.


### Later production observation: Coder main execution started

The **08:33** knowledge-preparation snapshot above remains a historical observation. A later
public detail observation with heartbeat **2026-10-20T08:38:50.314385Z** confirmed attempt **7**,
`lease_liveness=LEASE_VALID`, execution phase **ROLE_EXECUTION**, and execution
`state=RUNNING` / `reason_code=ROLE_RUNNING`. The separate resource-level
`execution_liveness` remained **UNKNOWN**; a role start does not establish current OS
liveness or rewrite that independent field. Independent typed
state/invocation inspection confirmed the main-role start at
**2026-10-20T08:38:17.812830Z**:

- Run: `run_88a8310012cb46f8a7b973ca180b0429`.
- Start SHA: `a493cb3d65fc616bfb35603ad74a7f6d5c44e4f765114abb984109ecf96348dc`.
- Context: `ctx_2399054d9b9ff8f1e15564c33b355c83b8f61a809ed59a858f7cc907c9573ecc`.
- Lease: `lease_8471054ed31adaa8b708aff8`, retaining the same Task/source binding.

The same independent audit subsequently verified attempt 7 assessment's RETURNED outcome at
**2026-10-20T08:38:02Z**, SHA
`f832f9e7d25be99c7836b6a1c5b7f0f946ab9993b3426d0933724e6e11eec332`,
with native return code 0 and owned-session proof
`5a30d20fbf3e7d82c4a6222fdac3130c69b49522c3399836671e36d9150f1b1c`.
Attempt 6's failed HTTP/native fallback also has a complete owned-session proof,
`231df92bc64883c991c259013fbbcfb95e859bf943f9019a34b26752983ca5f6`.
These typed transient and current successful fallback records are distinct from the older
UNKNOWN history, which was retained without a fabricated stop or no-start conclusion.

Recovery has therefore actually reached Coder main execution through the public continuation
path. The Operation was still **RUNNING**, and no main-role outcome was present in the stores
at the independent audit. No accepted candidate, QA/Review verdict, Operation SUCCEEDED or K1 DONE is
claimed. These observations did not require a new Requirement, direct database updates or a
change to the unknown-state guard.


## Later terminal result of the failed invocation (2026-10-21)

The earlier running snapshots above are historical. A fresh public read on October 21 reports
the same Task BLOCKED at revision 12, attempt 7 CLOSED and no candidate. The original public
RESUME operation `operation_fc40a17eef8750bb1c18824d3eb119ab` completed SUCCEEDED at
2026-10-20T08:59:01.088877Z: continuation was processed, but delivery did not finish.

Independent read-only typed inspection of the exact attempt 7 invocation verified outcome SHA
`266a96d28ac1c36c86f81a8f15c00e3449c180436a02b1d3d35b5832d91aff6b`.
Its FAILED/POLICY_VIOLATION error says the native CLI exited with unknown cause, return code 1,
and the post-failure workspace could not be accepted as unchanged. Output was absent and no
role artifact was accepted. The diagnostic contains only stdout/stderr SHA values; it does not
establish a denied tool or the original provider failure's cause. The before/after guard also
refuses failed inventory observation, so the final error alone cannot distinguish new source
changes from observation failure. Do not infer unauthorized writes from the UI's coarse
PERMISSION_DENIED label.

The actual owned process stop is complete, unlike the older UNKNOWN history:

- Capture start: `db480284725c615cd465043541845ad738765642124739e7490ea875ec324883`.
- Capture stop: `8042d134da70c1f7c1ea30a5ef293dcd0806949a723e65cfb29d284f5ddb931d`.
- Native failed stop: `ed633f01f070df8c759f830a2659f94eeafe2d47f92ebab65f68f216e36495f6`,
  return code 1, stopped 2026-10-20T08:58:05.014284Z.
- Complete owned-session proof:
  `b8d6858d0df3fc8844c1ad1e4f950545a9a4b8aead009406cbefe0f423bbd7db`.

Existing production-team-host policy explicitly rejects dirty/uncertain failed invocations
without automatic retry. This inspection establishes no new permission defect. The latest
accepted progress remains checkpoint 4 (steps 01-03 complete, 04-08 remaining); attempt 7 has
no candidate, QA PASS or Review APPROVE. Preserve its outcome and all draft bytes. The
STOPPED_FAILURE_RETRY same-Task path is inapplicable to a final POLICY_VIOLATION; use the
normal exact terminal recovery proposal/approval path in the original Requirement instead.
No SQL migration, historical result rewrite, Task reset or budget refund has been performed.

The independent audit of the earlier successful admission and knowledge retry is separately
stored in `evidence/continuation-independent-audit.json`. It describes those earlier reads,
not this later terminal state or completion. Deployment rollback still requires the official
controlled idle stop and actual exit; keep additive readers and every persisted recovery
record. Reverting the performance fix can restore the measured survey timeout, and reverting
the configuration helper can strand escaped-Unicode apply requests again.
