# Incremental verification

## Root cause and implementation

- Real concurrent readonly summary/detail reproduced `TEAM_READ_IN_PROGRESS`:
  summary 200/3.550s; detail 503/0.006s. This is bounded worker contention,
  not evidence corruption. Browser summaries now use the same finite 1/2/4s
  busy-only retry as detail, under the original 40s deadline and scope checks.
- Detail performed an unused complete Project header and reprojected the current
  Task for body hydration. Native task detail now reads only its selected work
  and complete historical feedback; final exact-source observation still opens
  independent filesystem/SQL facts.
- Complete native rule bodies repeatedly scanned after generic cache capacity
  was occupied by short fields. Typed clean-body facts now get bounded priority;
  the full exact text/pattern set, secret rejection and shared 512/16MiB bounds
  remain. Native epoch decode uses the original shared 512/32MiB scope and full
  bytes/hash reads; current authority is never cached.

## Checks

- `pytest -q --tb=short -m 'not mysql'` on detail latency, summary/detail reader,
  task/snapshot scopes, HTTP coalescing/routes, source/generic/body redaction and
  native rule epoch scope: **109 passed**. Separate existing recovery scope and
  epoch regression selection: **23 passed**. Source/generic/body/epoch selection:
  **39 passed**. Tests overlap; these numbers are not an aggregate unique total.
- `node --test tests/team_view/team-summary-reading.test.cjs`: **32 passed**.
- Chrome fixture `browser/team-summary-reading.test.cjs`: **7 passed**.
- Changed-file Ruff and strict mypy (8 files): passed; JS syntax and diff check passed.
- MySQL `test_live.py -m mysql`: **5 passed, 1 failed**. The failing
  `test_real_inflight_joint_and_terminal_reads` also fails on untouched main
  f6d291e with the same BLOCKED-versus-DONE fixture assertion. It is not counted
  as passed or fixed here. Initial sandbox connection errors were rerun with
  permission against the dedicated test database, never the production DB.
- No full test suite or real model execution ran.

## Independent review and corrective verification

Standards review identified a valid standalone candidate verification whose selected
detail omitted its native Requirement owner, plus inconsistent wording about epoch
decoding reuse. Spec review independently identified the same missing-owner regression.
The selected verification now derives its owner from validated native/source facts for
both body assembly and the independent final source fence, without unrelated Task reads.
Fresh current authority and complete byte reads remain distinct from immutable decoding.

- Extended `test_live.py::test_active_candidate_verification_is_visible_as_qa_work`
  from full snapshot to public summary → exact detail. Before correction it failed at
  the missing-owner locator check; after correction: **1 passed** against the isolated
  test database. Complete detail equals the original full snapshot, the exact source
  matches, and persisted filesystem bytes are unchanged.
- Follow-up detail latency/summary-detail selection: **23 passed**; final body/source/
  epoch selection: **16 passed**; Node summary read tests: **32 passed**.
- Ruff on the two changed Python files, strict reader mypy and diff check passed.
- Both independent reviews found no remaining material issue in the corrective diff.

## Bounded production measurements

Sequential fresh-process complete K1 read with no profiler: main **13.206s**;
final clean-body-priority implementation **10.727s**. Earlier intermediate fixes
alone measured 13.630s and 14.925s and did not establish an improvement. Counts
fell from 32 to 7 `_read_task_details` calls in a profiler run; counts alone were
not treated as a latency result. Timing is environment-specific, not a universal SLA.

All measured complete bodies contain 19 documents, 19 timeline entries, **216**
execution-history entries and 19 runs. Body SHA remains
`d0cb0c92c36b83236c3c4eb79ee325ad1293495c96cfe23bd67b77b2a0a428df`;
exact scope SHA remains
`69028f17051420349947241943bd82b67543c9bd1d2bb7d5f8464868a9fc05f5`.
Initial complete reading still costs seconds; no claim of instant history reading
or removal of server's deliberate busy response is made.

## Existing data treatment / rollback

No migration or direct SQL/journal/Task/Operation/approval/queue/worktree edits.
Original K1 drafts, unknown outcomes and all feedback remain. Ordinary controlled
restart loads the fix, then a browser reload loads assets. K1's last immutable
preflight receipt reported `VERIFICATION_MYSQL_IMAGE_UNAVAILABLE`; current readonly
registered-host discovery reports AVAILABLE. Platform must recheck the original
Task through its public workflow; this read fix does not approve or resume it.

Rollback by reverting the read-side commit and ordinary controlled restart. No
fact restoration, new Requirement, verdict editing or draft cleanup is required.

## Prevention

Busy is a flow-control result and must be tested separately from damaged facts.
Keep deterministic real refresh/HTTP tests and full-body hash comparisons. Do not
raise cache/worker counts or reduce history to improve responsiveness. Finite
immutable decode reuse and pure secret detection need explicit ownership, shared
aggregate bounds and actual saturation tests; current engineering authority stays
fresh even when historical bytes are unchanged.
