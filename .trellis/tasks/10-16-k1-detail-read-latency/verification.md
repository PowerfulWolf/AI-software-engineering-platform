# Verification and deployment handoff

## Results

- Author: 14 new Request projection cases passed; related reader cases 47 passed with one
  MySQL case deselected. Ruff, format and strict Mypy passed for the two Python files.
- Independent reviewer `/root/run6_owned_uncertainty`: 40 reader cases, 63 live/Console
  cases and seven temporary HTTP cases passed (110 total). Six MySQL cases were excluded;
  this read projection does not change SQL. Negative probes for final-observation current
  engineering corruption, a corrupt foreign joint journal and a corrupt foreign native
  journal all refused. Both independently fresh current Task observations were confirmed.
- Root repeated `git diff --check`, Ruff check and Ruff format check successfully before
  staging this exact change. No production write or database reset belongs to this task.

Independent review report:
`/tmp/ase-k1-request-detail-perf-independent-review-20261016.json`, SHA-256
`f71df848b85fc985e1119ba3c350f387cd73fef7255451e29a3d15aea05c05af`.
The reviewed reader body SHA-256 is
`87c89dd02196943b37334a4fae7b4388419ebd58615291a0bde6aa210c75e9d2`.

## Real read-only measurements

The complete same K1 Request detail took 11.571s wall / 10.898s CPU before the change,
including only 0.37s database time. The author measured 7.394s and root independently
measured 6.992s wall / 6.807s CPU after it. Both snapshots remain; Task detail and
engineering-history projections dropped from 24 to two. This is a measured reduction,
not a claim that frontend refresh is now fast or that the global read gate was deadlocked.

Root report `/tmp/ase-k1-request-detail-read-profile-root-after-20261016.json`, SHA-256
`744a58a1f0b97b2e97edbd39ef94751e8e3f301e3d3ae1c6ecd2f2e1b1e4c6a2`.
Remaining hotspots are current engineering history (3.62s) and joint history (2.73s).

## Existing data and rollback

存量数据处置：no data migration, authority rewrite, Task recreation or production SQL repair.
Keep original K1, accepted progress, failure/UNKNOWN history and all retained draft bytes.
Deploy together with the reviewed workspace-admission repair at a controlled idle boundary.
Rollback restores the previous reader projection cost while retaining all durable facts.
Actual browser validation and deployed timing are recorded after that controlled deployment.

## Post-deployment public reads and remaining latency — 2026-10-19

Independent reviewer `/root/run6_owned_uncertainty` made one sequential public GET per
endpoint after the combined deployment. `/api/v1/console` returned 200 in 0.010277s;
the project Team summary returned 200 in 3.718963s; exact K1 Request detail, queried
from that fresh typed summary, returned 200 in 5.555748s. Both resource responses passed
typed scope/checkpoint validation. Almost all elapsed time preceded response headers;
JSON parsing took 0.000211s and 0.000285s. These are single public HTTP samples, not
browser-rendering measurements or a latency distribution. K1 was DELIVERING then;
these reads do not establish business acceptance or delivery completion.

One additional standalone read-only summary→exact-detail cProfile scenario returned valid
typed results: summary 4.833985s wall / 4.502023s CPU; detail 7.314176s wall / 7.113622s
CPU. These include profiler overhead and must not be reported as public HTTP timings.
The detail still has exactly two selected Task observations, so the earlier reduction
from 24 detail hydrations remains effective. Separate dominant detail branches are
engineering history (two calls, 3.095s cumulative), joint history (four calls, 2.361s)
and role queue/source resolution (two calls, 1.270s). SQL execute totals only 0.170s.
Nested cumulative timings must not be added to their callers: engineering history
includes recovery Plan/Start decode (18 calls, 2.156s), of which defensive model copies
consume 1.333s. Joint history includes 170 generator resumes (1.877s, covering 166
records and four iteration endings) and 166 public return copies (0.483s).
Historical decoding, integrity serialization and
deep copying dominate the remaining server cost.

Smallest safe follow-up: share one bounded read-only JointJournal exact-byte decoder
only within a `detail()` call, while constructing a fresh `_JointHistorySnapshot` for
each observation. Preserve complete fresh file reads and SHA/predecessor checks,
filename/chain/Team/Project/retirement/ownership checks, and the second independent SQL
snapshot. Actual record decode and integrity calls can fall from 166 to 83, while all
166 fresh byte/SHA reads and 170 generator resumes remain. Direct decode, integrity
and successor validation take 0.755s, 0.849s and 0.128s respectively; half of this is
roughly 0.87s of duplicated profiled CPU work. This is not a measured gain or a promise
of more than one second improvement.
A later reader-private Plan/Start projection could address the 1.333s defensive-copy
budget only if full graphs cannot escape and all current authority/binding/Task checks
remain fresh. Do not remove public deep copies, reuse permission decisions, share
EngineeringHistorySnapshot/BaselineBindingSnapshot across observations, or introduce
cross-request caching. Ordinary tests should assert exact decode counts, typed
equivalence, corrupt/changed-byte refusal, final-observation changes, nested-metadata
isolation, bounded retention and cleanup on return/exception; no wall-clock threshold.

The Console now reads successfully, but refresh latency is **not fully resolved**.
No code, production facts, providers, restart or migration was changed by this diagnosis.
Any later optimization must be independently verified and measured after implementation,
then deployed at a controlled idle boundary. Rollback concerns reader source only;
K1 execution, original UNKNOWN/failure history, approvals and drafts remain durable.

Public HTTP report:
`/private/tmp/ase-postdeploy-console-read-independent-20261019.json`, SHA-256
`c56eb80ba19f69aa70edcb928499231dad9323b224659e0fea680db197c222ed`.
One profile report:
`/private/tmp/ase-console-read-profile-independent-20261019.json`, SHA-256
`c8bc94cc161dfcf9dcee599363c0a1805ff5704c8510b6f86b0a971a1faeef00`.
Full diagnosis with call attribution, safe seams and verification requirements:
`/private/tmp/ase-console-latency-diagnosis-independent-20261019.md`, SHA-256
`3c158245a99873c4cca939053e0fb9c868b9d4839af8ebbd158c6dcd4bec3fee`.
Source HEAD was independently read as `7e7a54915cab4afa6b47ae27255ac5014f3d5897`;
the profile JSON's boolean `revision` field is not a revision measurement.

## Call-local Joint decoder repair — implementation verification, 2026-10-19

The smallest follow-up is implemented only in the maintenance worktree; it has not been
committed, loaded or deployed. Active K1 and its production service were not interrupted.
No MySQL DSN was used: tests explicitly unset `ASE_TEST_MYSQL_DSN`, use `PYTHONPATH=src`
and run file/fake fixtures with `-m 'not mysql'`.

Red evidence before the implementation: public `reader.detail()` read each of three
original journal files twice but decoded six records; the new exact-decode test expected
three and failed (`1 failed in 0.44s`). After explicit detail-owned reuse, the test proves
three decodes/successor validations, six complete reads and six public deep copies, two
different `_JointHistorySnapshot`s and one shared decoder. A later independent detail and
summary each decode the same history again. No current source or SQL observation is shared.

Independent pre-review identified a real lifetime gap in dictionary-only cleanup. A warm
source read failing on a later symlink, or a resealed ancestor with unchanged cached
successor, retained one original private model through generator/genexpr/validator traceback
locals. Both public detail weak-reference tests failed before the final cleanup. The
`history()` failure boundary now clears only completed traceback frames; the retained
exception type, args and traceback locations remain unchanged, and both tests pass while
the complete error/cause chain stays alive. The original decoder/chain loop is unchanged.

Author verification:

```text
env -u ASE_TEST_MYSQL_DSN PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 <python> -m pytest -q \
  -m 'not mysql' tests/team_view/test_detail_joint_decoder_scope.py \
  tests/team_view/test_joint_history_snapshot.py tests/team_view/test_detail_latency_scope.py \
  tests/team_view/test_summary_detail_reader.py tests/team_view/test_request_detail_projection.py \
  tests/team_view/test_snapshot_record_scope.py tests/team_view/test_task_read_snapshot.py \
  tests/multi_directory/test_current_journal_copy.py
```

Result: **89 passed in 102.50s**. The 15 new cases include unchanged output/decode/read/copy
counts, independent requests, same-size/mtime tamper, resealed ancestor, missing prefix,
filename/symlink refusal after body, new-tail stale detection, body/source/cancellation
release, retained error model release, changed-root/empty cleanup and complete 513-record
history despite the existing 512-entry cache bound. Two hot-source cases were rerun after
adding exact exception args/traceback-location assertions: **2 passed** (overlap, not an
additional unique test count). Existing selected-current SQL tests still assert two separate
connections and fresh final authority/retirement/native ownership failure.

Ruff check and format check passed for both source and three affected test files; strict
Mypy passed for both source files using an isolated `/tmp` cache; `git diff --check` passed.
`<python>` is the main checkout's `.venv/bin/python`, but imports and tests use the maintenance
worktree's `src`. This checkout lacks `.trellis/scripts/get_context.py`; the spec index
documents one `core` package, so its applicable checklist/contracts were read directly.
There is no corresponding source-template spec copy. New ownership and the retained-frame
failure mode are recorded in `team-summary-detail.md` and the task design/implementation.

This fixture verification measures eliminated duplicate work, not public latency gain.
The 2026-10-19 HTTP figures above remain the last deployed timings. Summary cost, baseline
Plan/Start copies and queue historical decoding are outside this repair and remain open.
Existing data needs no migration/recreation; rollback removes only this source optimization
and restores repeated decode cost. Parent owns later controlled idle deployment and any
new public measurements after the current K1 execution has finished.

Independent reviewer `/root/workspace_refusal_recovery_wire` reports
**NO_BLOCKING_FINDINGS** and reproduced **67 passed in 40.66s** across the new scope,
current-journal copy, selected Request projection, summary/detail and detail-latency files
with both MySQL DSN variables unset. Independent Ruff check/format, strict Mypy and diff
checks passed. These overlap the author's 89 cases and must not be added as unique tests.
Six source/test/contract SHA values matched before and after the independent run.
Formal report: `/private/tmp/ase-detail-joint-decoder-independent-review-20261019.json`,
SHA-256 `611c4199d9246cf74a589030f89402d14f4e0e46179cafbd92b08275bb7955ff`.
